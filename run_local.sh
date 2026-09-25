#!/bin/bash
# run_local.sh — start AeroTwin locally (backend :8081 + frontend :8000 + ngrok tunnel).
# Runs in the background; write a PID file so you can stop it later.
# Usage:  nohup ./run_local.sh > run_local.log 2>&1 &  echo $! > run_local.pid
# Then:   ./run_local.sh status | ./run_local.sh stop

set -euo pipefail

cd "$(dirname "$0")"

PY="${PY:-venv/Scripts/python.exe}"
if [ ! -x "$PY" ]; then
  PY="python"
fi

echo "==> AeroTwin local launcher"
echo "    backend :8081  (FastAPI /sih/start_app.py)"
echo "    frontend: :8000  (serve.py, serves src/frontend)"
echo "    tunnel  : ngrok   (optional, worldwide phone pairing)"

# ---- 1. start services (manager skips anything already up) ----
echo "==> Starting services..."
"$PY" sih/start_app.py start

# ---- 2. wait for backend :8081 ----
echo "==> Waiting for backend :8081 ..."
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8081/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -sf http://127.0.0.1:8081/health >/dev/null 2>&1; then
  echo "!! Backend did not answer within 30 s — check sih/.backend.log"
  "$PY" sih/start_app.py status
  exit 1
fi

# ---- 3. wait for frontend :8000 ----
echo "==> Waiting for frontend :8000 ..."
for i in $(seq 1 10); do
  if curl -sf http://127.0.0.1:8000/ >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo
echo "=========================================="
echo "  AeroTwin is running locally"
echo "=========================================="
"$PY" sih/start_app.py status

echo
echo "  Dashboard : http://localhost:8000/index.html"
echo "  Backend   : http://127.0.0.1:8081"
echo "  API docs  : http://127.0.0.1:8081/docs"
echo "  Tunnel    : $(curl -sf http://127.0.0.1:4040/api/tunnels 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tunnels',[{}])[0].get('public_url','none'))" 2>/dev/null || echo "ngrok not up")"
echo "  Stop      : $0 stop"
echo "=========================================="
