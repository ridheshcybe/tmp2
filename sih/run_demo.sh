#!/bin/bash
# ============================================================
#  Aero Piston Engine Digital Twin - One-Click Demo Launcher
#  (Linux/macOS). Starts the sih backend + dashboard and opens
#  the browser. Paths resolve from this script's location.
# ============================================================
set -e

# Repo root - resolved from this script's location.
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

print_status() { echo -e "\033[0;32m✓\033[0m $1"; }
print_warning() { echo -e "\033[1;33m⚠\033[0m $1"; }
print_error() { echo -e "\033[0;31m✗\033[0m $1"; }

echo ""
echo "  ============================================================"
echo "   AeroTwin - MALE UAV Aero-Engine Digital Twin"
echo "   (DRDO Tapas-BH-201) - one-click demo"
echo "  ============================================================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 is not installed!"
    exit 1
fi
print_status "Python 3 is available"

# Check dependencies
if ! python3 -c "import fastapi, uvicorn, aiosqlite, numpy" &> /dev/null; then
    print_warning "Backend dependencies missing - run setup_environment.sh / pip install -r requirements.txt first. Trying anyway..."
fi

# Create .env from the example on first run
if [ -f "$ROOT/.env.example" ] && [ ! -f "$ROOT/.env" ]; then
    cp "$ROOT/.env.example" "$ROOT/.env"
    print_status "Created .env from .env.example"
fi

echo ""
echo "[START] Launching services..."
python3 "$ROOT/start_app.py" start

echo ""
echo "[INFO] Waiting for the backend to answer..."
wait_time=0
while [ $wait_time -lt 30 ]; do
    if curl -s http://127.0.0.1:8081/health &> /dev/null; then
        break
    fi
    sleep 2
    wait_time=$((wait_time + 2))
done

echo ""
echo "  ============================================================"
echo "   Services Running"
echo "  ------------------------------------------------------------"
echo "   Dashboard : http://localhost:8000/index.html"
echo "   REST API  : http://localhost:8000/api/...  (proxied)"
echo "   Backend   : http://127.0.0.1:8081"
echo "  ------------------------------------------------------------"
echo "   Stop      : python3 start_app.py stop"
echo "   Status    : python3 start_app.py status"
echo "  ============================================================"
echo ""

# Open the dashboard
case "$OSTYPE" in
    darwin*)      open "http://localhost:8000/index.html" ;;
    linux*)       xdg-open "http://localhost:8000/index.html" 2>/dev/null || echo "Please navigate to: http://localhost:8000/index.html" ;;
    msys*|cygwin*) start "http://localhost:8000/index.html" ;;
    *)            echo "Please navigate to: http://localhost:8000/index.html" ;;
esac

trap 'echo -e "\n\033[0;31mScript interrupted\033[0m"; python3 "$ROOT/start_app.py" stop 2>/dev/null; exit 1' INT TERM
