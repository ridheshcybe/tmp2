#!/usr/bin/env python3
"""
Standalone AeroTwin service manager.

Starts/stops/statuses the real AeroTwin services:

    backend   - the sih FastAPI app (uvicorn) on 127.0.0.1:8081;
                serves /api, the telemetry WebSocket and the ML pipeline.
    frontend  - the standalone viewer (serve.py) on port 8000;
                proxies /api to the backend and hosts phone pairing.
    tunnel    - optional ngrok tunnel to the frontend, so the phone
                pairing QR works from ANY network, not just the LAN.
                Enabled automatically when the ngrok binary is on PATH
                and an authtoken is configured (NGROK_AUTHTOKEN env var
                or `ngrok config add-authtoken ...` run once before).
                Set AEROTWIN_NGROK_DOMAIN to pin a reserved domain.

Usage: python start_app.py start|stop|status|restart
Stop is port-based, so it also catches servers started by run.bat
outside this manager.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent            # sih/
REPO_ROOT = PROJECT_ROOT.parent                           # repo root
FRONTEND_DIR = REPO_ROOT / "src" / "frontend"

BACKEND_PORT = 8081
FRONTEND_PORT = 8000

# ngrok's local inspection API.  serve.py polls it to discover the public
# URL; the manager uses the port as the tunnel's liveness probe.
NGROK_API_PORT = 4040


# ---------------------------------------------------------------------------
# Optional ngrok tunnel for worldwide phone pairing.
# ---------------------------------------------------------------------------

def _find_ngrok():
    from shutil import which
    return which("ngrok")


def _ngrok_authenticated():
    """True when ngrok has an authtoken: env var, or its config file
    written once by `ngrok config add-authtoken <token>`."""
    if os.environ.get("NGROK_AUTHTOKEN", "").strip():
        return True
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or "")
    local = os.environ.get("LOCALAPPDATA")
    candidates = [home / ".config" / "ngrok" / "ngrok.yml"]
    if local:
        candidates.append(Path(local) / "ngrok" / "ngrok.yml")
    return any(c.exists() for c in candidates)


def _tunnel_service():
    """The ngrok service entry, or None when worldwide pairing cannot
    be attempted on this machine.  Purely optional: without it the
    pairing QR simply stays on the LAN address."""
    exe = _find_ngrok()
    if not exe or not _ngrok_authenticated():
        return None
    cmd = [exe, "http", str(FRONTEND_PORT)]
    domain = os.environ.get("AEROTWIN_NGROK_DOMAIN", "").strip()
    if domain:
        cmd += ["--domain", domain]
    token = os.environ.get("NGROK_AUTHTOKEN", "").strip()
    if token:
        cmd += ["--authtoken", token]
    return {
        "name": "tunnel",
        "port": NGROK_API_PORT,
        "cmd": cmd,
        "cwd": str(REPO_ROOT),
        "env": {},
    }

SERVICES = [
    {
        "name": "backend",
        "port": BACKEND_PORT,
        "cmd": [sys.executable, "-m", "uvicorn", "backend.main:app",
                "--host", "127.0.0.1", "--port", str(BACKEND_PORT)],
        "cwd": PROJECT_ROOT,
        "env": {
            "PYTHONPATH": os.pathsep.join([str(PROJECT_ROOT),
                                           str(PROJECT_ROOT / "backend")]),
            "PYTHONIOENCODING": "utf-8",
        },
    },
    {
        "name": "frontend",
        "port": FRONTEND_PORT,
        "cmd": [sys.executable, "serve.py", str(FRONTEND_PORT)],
        "cwd": FRONTEND_DIR,
        "env": {},
    },
]

_LOGS = {}


def _log_path(name):
    if name not in _LOGS:
        _LOGS[name] = open(PROJECT_ROOT / ("." + name + ".log"), "ab")
    return _LOGS[name]


def port_busy(port):
    """True when something is listening on 127.0.0.1:<port>."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_service(svc):
    if port_busy(svc["port"]):
        print("  [=] " + svc["name"] + ": already running on port " + str(svc["port"]))
        return True

    env = os.environ.copy()
    env.update(svc.get("env", {}))
    creationflags = 0
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    detached = 0x00000008 if os.name == "nt" else 0
    proc = subprocess.Popen(
        svc["cmd"], cwd=str(svc["cwd"]), env=env,
        stdout=_log_path(svc["name"]), stderr=subprocess.STDOUT,
        creationflags=creationflags | detached,
    )
    print("  [+] " + svc["name"] + ": started (PID " + str(proc.pid)
          + ", port " + str(svc["port"]) + ")")

    for _ in range(15):                       # ~7.5 s to come up
        time.sleep(0.5)
        if port_busy(svc["port"]):
            print("  [OK] " + svc["name"] + ": listening on " + str(svc["port"]))
            return True
    print("  [WARN] " + svc["name"] + ": not listening yet - check sih/."
          + svc["name"] + ".log")
    return False


def pids_on_port(port):
    """Best-effort PID lookup via netstat (Windows) or lsof (POSIX)."""
    pids = set()
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True,
                             text=True, timeout=10).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[3] == "LISTENING" \
                    and parts[1].endswith(":" + str(port)):
                pids.add(int(parts[4]))
    except Exception:
        pass
    if not pids and os.name != "nt":
        try:
            out = subprocess.run(["lsof", "-t", "-i:" + str(port)],
                                 capture_output=True, text=True,
                                 timeout=10).stdout
            pids.update(int(p) for p in out.split())
        except Exception:
            pass
    return sorted(pids)


def stop_service(svc):
    pids = pids_on_port(svc["port"])
    if not pids:
        print("  [-] " + svc["name"] + ": not running")
        return
    for pid in pids:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True, timeout=10)
            else:
                os.kill(pid, 15)
            print("  [-] " + svc["name"] + ": stopped PID " + str(pid))
        except Exception as e:
            print("  [!] " + svc["name"] + ": could not stop PID " + str(pid) + ": " + str(e))


def start_all():
    tunnel = _tunnel_service()
    label = "backend :8081 + frontend :8000"
    if tunnel:
        label += " + worldwide pairing (ngrok)"
    print("=" * 60)
    print("Starting AeroTwin (%s)" % label)
    print("=" * 60)
    ok = True
    for svc in SERVICES:
        ok = start_service(svc) and ok
    if tunnel:
        start_service(tunnel)      # optional - a miss must not fail startup
    if ok:
        print("")
        print("[SUCCESS] All services started.")
        print("    Dashboard : http://localhost:" + str(FRONTEND_PORT) + "/index.html")
        print("    Backend   : http://127.0.0.1:" + str(BACKEND_PORT) + "/health")
        if tunnel:
            print("    Phone     : the pairing QR now carries a public ngrok")
            print("                URL - ANY phone, on ANY network, can pair")
        else:
            print("    Phone     : LAN only - to pair from any network, install")
            print("                ngrok and set NGROK_AUTHTOKEN (docs/FRONTEND.md)")
    else:
        print("")
        print("[WARN] Some services did not come up - see the .log files in sih/.")


def stop_all():
    print("")
    print("Stopping all services...")
    services = list(SERVICES)
    tunnel = _tunnel_service()
    if tunnel:
        services.append(tunnel)
    for svc in reversed(services):
        stop_service(svc)
    print("All services stopped.")


def status():
    print("")
    print("=" * 60)
    print("Service Status")
    print("=" * 60)
    services = list(SERVICES)
    tunnel = _tunnel_service()
    if tunnel:
        services.append(tunnel)
    for svc in services:
        state = "RUNNING" if port_busy(svc["port"]) else "STOPPED"
        print("  " + svc["name"].ljust(9) + " : " + state.ljust(7)
              + " (port " + str(svc["port"]) + ")")
    if not tunnel:
        print("  (worldwide pairing off: ngrok binary or authtoken missing)")
    print("")


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "start":
        start_all()
    elif command == "stop":
        stop_all()
    elif command == "status":
        status()
    elif command == "restart":
        stop_all()
        time.sleep(2)
        start_all()
    else:
        print("Usage: python start_app.py [start|stop|status|restart]")
        sys.exit(1)


if __name__ == "__main__":
    main()
