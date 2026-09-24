"""
    Tiny static server for the AeroTwin frontend (standard library only).

    Same as `python -m http.server`, plus:

      * /__lanip - JSON {ip, scheme, port} so the page can build a QR code
        the phone can scan (a browser cannot see the host's own LAN IP).
        When an ngrok tunnel is up (or AEROTWIN_PUBLIC_ORIGIN is set) the
        QR carries that public URL instead, so ANY phone on Earth can
        pair - not just phones on the same Wi-Fi.
      * /__pair - a tiny in-memory relay for the WebRTC handshake.  The
        desktop parks its offer under a one-time token and polls for the
        phone's answer, so the QR link is the whole pairing: nothing is
        ever typed, copied or pasted on either side.
      * /__ice - the STUN/TURN servers both WebRTC peers should use.
        STUN pairs across one network; TURN (AEROTWIN_TURN_URL/_USER/
        _CRED) keeps the video path alive through carrier CGNAT.
      * a second HTTPS listener with a self-signed certificate (generated
        once with openssl, if it is installed), because phones refuse
        camera access over plain http.  Accept the certificate warning
        once on the phone - after that it works like any other site.

    When AEROTWIN_KEY is set, every phone-side relay call (offer fetch,
    answer POST, /__ctl POST) must present that key - the QR link carries
    it automatically, so a legitimately scanned phone still pairs with
    zero human steps while strangers on the internet get a 403.

    Usage:  python serve.py [http-port] [https-port]
"""
import hmac
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))

PHONE_INFO = {"ip": "127.0.0.1", "scheme": "http", "port": 8000}

# ---------------------------------------------------------------------------
# Worldwide (internet) pairing configuration.  All of it is env-var driven:
#
#   AEROTWIN_PUBLIC_ORIGIN     public URL that replaces the LAN address in
#                              the pairing QR, e.g. a tunnel URL.  When it
#                              is unset, serve.py discovers an ngrok tunnel
#                              on ngrok's local API (127.0.0.1:4040) and
#                              uses that automatically.
#   AEROTWIN_NGROK_DOMAIN      optional reserved ngrok domain; start_app.py
#                              passes it to ngrok so the URL stays stable.
#   AEROTWIN_TURN_URL/_USER/_CRED   TURN relay handed to both WebRTC peers
#                              through /__ice, so the camera video survives
#                              carrier CGNAT (a phone on mobile data).
#   AEROTWIN_KEY               when set, phone-side relay calls must present
#                              it - the QR link carries it, so nobody else
#                              can drive the exposed relays.
# ---------------------------------------------------------------------------

NGROK_API = "http://127.0.0.1:4040/api/tunnels"
TUNNEL_INFO = {"public": None}


def public_origin():
    return os.environ.get("AEROTWIN_PUBLIC_ORIGIN", "").strip().rstrip("/")


def turn_servers():
    url = os.environ.get("AEROTWIN_TURN_URL", "").strip()
    if not url:
        return []
    server = {"urls": url}
    user = os.environ.get("AEROTWIN_TURN_USER", "").strip()
    cred = os.environ.get("AEROTWIN_TURN_CRED", "").strip()
    if user or cred:
        server["username"] = user
        server["credential"] = cred
    return [server]


def access_key():
    return os.environ.get("AEROTWIN_KEY", "").strip()


def ice_config():
    servers = turn_servers()
    servers.append({"urls": "stun:stun.l.google.com:19302"})
    return {"iceServers": servers, "turn": bool(turn_servers())}


def poll_ngrok_forever():
    """Discover the ngrok tunnel URL from ngrok's local API, forever.

    Runs as a daemon thread: with a tunnel up, /__lanip hands the public
    URL to the pages and the pairing QR becomes world-reachable; with no
    tunnel it quietly stays on the LAN address.
    """
    import urllib.request

    while True:
        try:
            with urllib.request.urlopen(NGROK_API, timeout=2) as up:
                data = json.loads(up.read().decode("utf-8"))
            public = None
            for tun in data.get("tunnels", []):
                if tun.get("proto") == "https":
                    public = str(tun.get("public_url", "")).rstrip("/")
                    break
            TUNNEL_INFO["public"] = public
        except Exception:
            TUNNEL_INFO["public"] = None
        time.sleep(5)

# ---------------------------------------------------------------------------
# WebRTC signaling relay.  token -> {offer, answer, created}.  Purely local
# and in-memory: a session dies with the server, and stale ones are dropped
# after PAIR_TTL seconds.  The token rides to the phone inside the QR link,
# so there is no code for a human to handle.
# ---------------------------------------------------------------------------

PAIR_LOCK = threading.Lock()
PAIR_SESSIONS = {}
PAIR_TTL = 900.0

# ---------------------------------------------------------------------------
# Phone-controller relay.  The paired phone POSTs control commands here
# ({cmd, value}) and the dashboard polls them (GET /__ctl?since=<cursor>).
# In-memory queue, newest last; the dashboard drains by cursor.  The
# WebRTC data channel is the primary path - this is the fallback that
# keeps the phone working even when the peer connection has not opened.
# ---------------------------------------------------------------------------

CTL_LOCK = threading.Lock()
CTL_QUEUE = []
CTL_CURSOR = 0
CTL_MAX = 200


def ctl_enqueue(cmd, value):
    global CTL_CURSOR
    with CTL_LOCK:
        CTL_CURSOR += 1
        CTL_QUEUE.append({
            "seq": CTL_CURSOR,
            "cmd": str(cmd or ""),
            "value": value,
            "at": time.time(),
        })
        # keep the queue bounded: drop the oldest beyond CTL_MAX
        del CTL_QUEUE[:-CTL_MAX]


def ctl_since(cursor):
    with CTL_LOCK:
        return [c for c in CTL_QUEUE if c["seq"] > cursor], CTL_CURSOR


def pair_housekeeping():
    now = time.time()
    stale = [t for t, s in PAIR_SESSIONS.items()
             if now - s["created"] > PAIR_TTL]
    for t in stale:
        del PAIR_SESSIONS[t]


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

    def _is_local(self):
        """True when the request comes from this machine (the desktop)."""
        # A tunnel (ngrok) forwards internet traffic through a local agent,
        # so every tunneled request arrives from 127.0.0.1.  Proxies mark
        # such requests with X-Forwarded-For - treat them as non-local so
        # the access key stays enforced behind the tunnel.
        if self.headers.get("x-forwarded-for"):
            return False
        try:
            return str(self.client_address[0]) in ("127.0.0.1", "::1")
        except Exception:
            return False

    def _presented_key(self):
        """The access key as the caller sent it (?key= or the header)."""
        if "?" in self.path:
            for part in self.path.split("?", 1)[1].split("&"):
                if part.startswith("key="):
                    return unquote(part[4:])
        return self.headers.get("x-aerotwin-key", "") or ""

    def _key_ok(self):
        """True when the caller may use the phone-side relays."""
        want = access_key()
        if not want:
            return True
        return hmac.compare_digest(str(self._presented_key()), want)

    def _lanip(self):
        info = dict(PHONE_INFO)

        public = public_origin() or TUNNEL_INFO["public"]
        if public:
            info["public"] = public

        # The access key rides only to pages served on this machine, and
        # only into the QR - that is what keeps an internet-exposed relay
        # from being driven by strangers who never scanned the QR.
        want = access_key()
        if want:
            info["key_required"] = True
            if self._is_local():
                info["key"] = want

        body = json.dumps(info).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _ice(self):
        # TURN credentials: this machine always gets them; from the
        # internet only a caller presenting the access key does.
        want = access_key()
        if want and not (self._is_local() or self._key_ok()):
            return self._respond({"detail": "invalid pairing key"}, 403)
        self._respond(ice_config())

    def _respond(self, payload, code=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _pair_create(self, body):
        """Desktop: park a WebRTC offer, get back a one-time token."""
        try:
            offer = str((json.loads(body or b"{}")).get("offer") or "")
        except Exception:
            offer = ""
        if not offer:
            return self._respond({"detail": "offer required"}, 400)
        # Parking offers is the desktop's job; from the internet (tunnel up)
        # only a caller presenting the access key may park one.
        if not (self._is_local() or self._key_ok()):
            return self._respond({"detail": "invalid pairing key"}, 403)
        token = uuid.uuid4().hex[:16]
        with PAIR_LOCK:
            pair_housekeeping()
            PAIR_SESSIONS[token] = {"offer": offer, "answer": None,
                                    "created": time.time()}
        self._respond({"token": token})

    def _pair_offer(self, token):
        """Phone: fetch the offer parked under the token from the QR."""
        if not self._key_ok():
            return self._respond({"detail": "invalid pairing key"}, 403)
        with PAIR_LOCK:
            session = PAIR_SESSIONS.get(token)
            if session is None:
                return self._respond({"detail": "unknown or expired token"}, 404)
            offer = session["offer"]
        self._respond({"offer": offer})

    def _pair_poll(self, token):
        """Desktop: poll until the phone has delivered its answer."""
        with PAIR_LOCK:
            session = PAIR_SESSIONS.get(token)
            if session is None:
                return self._respond({"state": "gone"}, 404)
            answered = session["answer"] is not None
            payload = {"state": "answered" if answered else "waiting"}
            if answered:
                payload["answer"] = session["answer"]
        self._respond(payload)

    def _pair_answer(self, token, body):
        """Phone: deliver the WebRTC answer for the token from its QR."""
        if not self._key_ok():
            return self._respond({"detail": "invalid pairing key"}, 403)
        try:
            answer = str((json.loads(body or b"{}")).get("answer") or "")
        except Exception:
            answer = ""
        if not answer:
            return self._respond({"detail": "answer required"}, 400)
        with PAIR_LOCK:
            session = PAIR_SESSIONS.get(token)
            if session is None:
                return self._respond({"detail": "unknown or expired token"}, 404)
            session["answer"] = answer
        self._respond({"ok": True})

    def _ctl_post(self, body):
        """Phone: queue one control command for the dashboard."""
        if not self._key_ok():
            return self._respond({"detail": "invalid pairing key"}, 403)
        try:
            data = json.loads(body or b"{}")
        except Exception:
            return self._respond({"detail": "bad json"}, 400)
        ctl_enqueue(data.get("cmd"), data.get("value"))
        self._respond({"ok": True})

    def _ctl_get(self, query):
        """Dashboard: drain commands newer than ?since=<cursor>."""
        since = 0
        for part in query.split("&"):
            if part.startswith("since="):
                try:
                    since = int(part[6:])
                except ValueError:
                    since = 0
        commands, cursor = ctl_since(since)
        self._respond({"commands": commands, "cursor": cursor})

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
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        if route == "/__lanip":
            self._lanip()
        elif route == "/__ice":
            self._ice()
        elif route == "/__ctl":
            self._ctl_get(query)
        elif route.startswith("/__pair/") and route.endswith("/answer"):
            self._pair_poll(route[len("/__pair/"):-len("/answer")])
        elif route.startswith("/__pair/"):
            self._pair_offer(route[len("/__pair/"):])
        elif route == "/api" or route.startswith("/api/") or route == "/health":
            self._proxy(None)
        else:
            super().do_GET()

    def do_POST(self):
        route = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        if route == "/__pair":
            self._pair_create(body)
        elif route == "/__ctl":
            self._ctl_post(body)
        elif route.startswith("/__pair/") and route.endswith("/answer"):
            self._pair_answer(route[len("/__pair/"):-len("/answer")], body)
        elif route == "/api" or route.startswith("/api/"):
            self._proxy(body)
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

    # Worldwide pairing: watch for an ngrok tunnel (or honour a fixed
    # AEROTWIN_PUBLIC_ORIGIN) so the QR can carry a public URL.
    if not public_origin():
        threading.Thread(target=poll_ngrok_forever,
                         daemon=True).start()
    else:
        TUNNEL_INFO["public"] = public_origin()

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
    if TUNNEL_INFO["public"] or public_origin():
        print("  world   :  pairing QR carries the public URL below -")
        print("             any phone on any network can pair")
    else:
        print("  world   :  no ngrok tunnel found yet - QR stays LAN-only")
        print("             (start_app.py starts one automatically when the")
        print("             ngrok binary + NGROK_AUTHTOKEN are available)")
    if access_key():
        print("  key     :  AEROTWIN_KEY is set - phone relay calls are gated")
    else:
        print("  key     :  AEROTWIN_KEY not set - relay endpoints are open")
        print("             (set it before exposing the relays to the internet)")
    print("", flush=True)

    httpd.serve_forever()


if __name__ == "__main__":
    main()
