#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# AeroTwin Backend — Startup Script
# ══════════════════════════════════════════════════════════════════════════════
#
# Usage:
#   ./run_backend.sh              # Start in dev mode (auto-reload)
#   ./run_backend.sh production   # Start in production mode
#   ./run_backend.sh test         # Run tests
#
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Colors ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── Functions ───────────────────────────────────────────────────────────────

print_banner() {
    echo -e "${CYAN}"
    echo "═══════════════════════════════════════════════════════════════"
    echo "  AeroTwin Digital Twin — FastAPI Backend"
    echo "  SIH26054 / DRDO — Aero Piston Engine Monitoring"
    echo "═══════════════════════════════════════════════════════════════"
    echo -e "${NC}"
}

check_python() {
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}✗ Python 3 not found. Please install Python 3.10+.${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ Python: $(python3 --version)${NC}"
}

install_deps() {
    if [ ! -d "venv" ]; then
        echo -e "${YELLOW}Creating virtual environment...${NC}"
        python3 -m venv venv
    fi
    source venv/bin/activate

    echo -e "${YELLOW}Installing dependencies...${NC}"
    pip install -q -r requirements.txt

    # Ensure parent dir is on path for simulator imports
    export PYTHONPATH="${SCRIPT_DIR}/..:${SCRIPT_DIR}:${PYTHONPATH:-}"

    echo -e "${GREEN}✓ Dependencies installed${NC}"
}

run_tests() {
    echo -e "${YELLOW}Running tests...${NC}"
    source venv/bin/activate
    export PYTHONPATH="${SCRIPT_DIR}/..:${SCRIPT_DIR}:${PYTHONPATH:-}"
    python -m pytest tests/ -v --tb=short 2>/dev/null || python tests/test_api.py
}

run_dev() {
    echo -e "${YELLOW}Starting dev server (auto-reload on port 8081)...${NC}"
    source venv/bin/activate
    export PYTHONPATH="${SCRIPT_DIR}/..:${SCRIPT_DIR}:${PYTHONPATH:-}"
    python -m uvicorn main:app --host 0.0.0.0 --port 8081 --reload --log-level info
}

run_production() {
    echo -e "${YELLOW}Starting production server (port 8081, 4 workers)...${NC}"
    source venv/bin/activate
    export PYTHONPATH="${SCRIPT_DIR}/..:${SCRIPT_DIR}:${PYTHONPATH:-}"
    python -m uvicorn main:app --host 0.0.0.0 --port 8081 --workers 4 --log-level warning
}

# ── Main ────────────────────────────────────────────────────────────────────

print_banner
check_python

case "${1:-dev}" in
    test)
        install_deps
        run_tests
        ;;
    production|prod)
        install_deps
        run_production
        ;;
    dev|*)
        install_deps
        run_dev
        ;;
esac
