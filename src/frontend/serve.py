"""
    Tiny static server for the AeroTwin frontend (standard library only).

    Same as `python -m http.server`, plus:

      * /__lanip - JSON {ip, scheme, port} so the page can build a QR code
        the phone can scan (a browser cannot see the host's own LAN IP).
      * a second HTTPS listener with a self-signed certificate (generated
        once with openssl, if it is installed), because phones refuse
        camera access over plain http.  Accept the certificate warning
        once on the phone - after that it works like any other site.

    Usage:  python serve.py [http-port] [https-port]
"""
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))

PHONE_INFO = {"ip": "127.0.0.1", "scheme": "http", "port": 8000}


def lan_ip():
    """The address on the default route.  No packet actually goes out."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        s.close()


def ensure_cert():
    """A self-signed pair, created once, for the phone's https listener."""
    cert = os.path.join(HERE, "cert.pem")
    key = os.path.join(HERE, "key.pem")
    if os.path.exists(cert) and os.path.exists(key):
        return cert, key
    if not shutil.which("openssl"):
        return None
    try:
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-keyout", key, "-out", cert, "-days", "3650",
             "-subj", "/CN=aerotwin-local"],
            check=True, capture_output=True, timeout=60)
        return cert, key
    except Exception:
        return None


class Handler(SimpleHTTPRequestHandler):

    # The sih FastAPI backend, for the REST proxy below.  Pages on this
    # origin speak /api/* same-origin; without the proxy the backend's
    # CORS list (localhost:3000/5173 only) would block them.
    BACKEND = "127.0.0.1", 8081

    def _lanip(self):
        body = json.dumps(PHONE_INFO).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _proxy(self, body):
        """Forward /api/* and /health to the backend, same-origin."""
        import urllib.request
        import urllib.error

        url = "http://%s:%d%s" % (self.BACKEND[0], self.BACKEND[1], self.path)
        req = urllib.request.Request(url, data=body, method=self.command,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as up:
                payload, code, ctype = up.read(), up.status, up.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as e:
            payload, code, ctype = e.read(), e.code, e.headers.get("Content-Type", "application/json")
        except Exception:
            payload = json.dumps({"detail": "backend unreachable - is the sih backend running on 127.0.0.1:8081?"}).encode("utf-8")
            code, ctype = 503, "application/json"

        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        route = self.path.split("?")[0]
        if route == "/__lanip":
            self._lanip()
        elif route == "/api" or route.startswith("/api/") or route == "/health":
            self._proxy(None)
        else:
            super().do_GET()

    def do_POST(self):
        route = self.path.split("?")[0]
        if route == "/api" or route.startswith("/api/"):
            length = int(self.headers.get("Content-Length") or 0)
            self._proxy(self.rfile.read(length) if length else None)
        else:
            self.send_error(404)

    def log_message(self, fmt, *args):
        pass


def main():
    http_port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    https_port = int(sys.argv[2]) if len(sys.argv) > 2 else 8443

    os.chdir(HERE)
    ip = lan_ip()

    tls = ensure_cert()
    if tls:
        PHONE_INFO.update(scheme="https", port=https_port)
    PHONE_INFO.update(ip=ip)

    httpd = ThreadingHTTPServer(("0.0.0.0", http_port), Handler)

    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(tls[0], tls[1])
        httpsd = ThreadingHTTPServer(("0.0.0.0", https_port), Handler)
        httpsd.socket = ctx.wrap_socket(httpsd.socket, server_side=True)
        threading.Thread(target=httpsd.serve_forever, daemon=True).start()

    print("")
    print("  AeroTwin frontend  (serving %s)" % HERE)
    print("  desktop :  http://localhost:%d/" % http_port)
    if tls:
        print("  phone   :  https://%s:%d/phone.html" % (ip, https_port))
        print("             accept the certificate warning once - phones")
        print("             need https before they hand out the camera")
    else:
        print("  phone   :  http://%s:%d/phone.html" % (ip, http_port))
        print("             (openssl not found - without https the phone")
        print("             may refuse to give the page its camera)")
    print("", flush=True)

    httpd.serve_forever()


if __name__ == "__main__":
    main()
