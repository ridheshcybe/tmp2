#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# Aero Piston Engine Digital Twin - One-Click Demo Launcher (Standalone)
# ══════════════════════════════════════════════════════════════════════════════
#
# This script launches the complete Digital Twin system and opens the
# dashboard in your default browser. No Docker required.
#
# Usage:
#   chmod +x run_demo.sh
#   ./run_demo.sh
#
# ══════════════════════════════════════════════════════════════════════════════

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_status() { echo -e "${GREEN}✓${NC} $1"; }
print_warning() { echo -e "${YELLOW}⚠${NC} $1"; }
print_error() { echo -e "${RED}✗${NC} $1"; }
print_info() { echo -e "${BLUE}ℹ${NC} $1"; }

# Check Python
check_python() {
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 is not installed!"
        exit 1
    fi
    print_status "Python 3 is available"
}

# Verify dependencies
check_deps() {
    print_info "Verifying Python dependencies..."
    if [ ! -f "E:/projects/sih/requirements.txt" ]; then
        print_error "requirements.txt not found!"
        exit 1
    fi
    pip3 check 2>/dev/null || print_warning "Some packages may be missing. Run: pip install -r requirements.txt"
    print_status "Dependencies checked"
}

# Verify environment
check_env() {
    print_info "Verifying environment..."
    if [ -f "E:/projects/sih/.env.example" ]; then
        if [ ! -f "E:/projects/sih/.env" ]; then
            cp "E:/projects/sih/.env.example" "E:/projects/sih/.env"
            print_status "Created .env from .env.example"
        fi
    fi
    print_status "Environment verified"
}

# Start services
start_services() {
    print_info "Starting AeroTwin Digital Twin system..."
    print_info "This will launch all services as standalone processes."
    echo ""
    python3 "E:/projects/sih/start_app.py" start
}

# Wait for services
wait_for_services() {
    print_info "Waiting for services to become ready..."
    max_wait=60
    wait_time=0
    
    echo -n "  Waiting for Simulator (port 8765) "
    while [ $wait_time -lt $max_wait ]; do
        if curl -s http://localhost:8765/health &> /dev/null 2>&1; then
            echo -e " ${GREEN}✓${NC}"
            break
        fi
        echo -n "."
        sleep 2
        wait_time=$((wait_time + 2))
    done
    
    echo -n "  Waiting for AI Service (port 8766) "
    wait_time=0
    while [ $wait_time -lt $max_wait ]; do
        if curl -s http://localhost:8766/health &> /dev/null 2>&1; then
            echo -e " ${GREEN}✓${NC}"
            break
        fi
        echo -n "."
        sleep 2
        wait_time=$((wait_time + 2))
    done
    
    echo -n "  Waiting for Backend (port 8080) "
    wait_time=0
    while [ $wait_time -lt $max_wait ]; do
        if curl -s http://localhost:8081/health &> /dev/null 2>&1; then
            echo -e " ${GREEN}✓${NC}"
            break
        fi
        echo -n "."
        sleep 2
        wait_time=$((wait_time + 2))
    done
    
    echo ""
    print_status "All services are ready"
}

# Open browser
open_browser() {
    print_info "Opening dashboard in browser..."
    case "$OSTYPE" in
        darwin*)      open "http://localhost:3000" ;;
        linux*)       xdg-open "http://localhost:3000" 2>/dev/null || gnome-open "http://localhost:3000" 2>/dev/null || echo "Please navigate to: http://localhost:3000" ;;
        msys*|cygwin*) start "http://localhost:3000" ;;
        *)            echo "Please navigate to: http://localhost:3000" ;;
    esac
}

# Print service info
print_status_info() {
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  Services Running (Standalone Mode)${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${GREEN}Dashboard:${NC}      http://localhost:3000"
    echo -e "  ${GREEN}WebSocket:${NC}      ws://localhost:8080"
    echo -e "  ${GREEN}REST API:${NC}       http://localhost:8081"
    echo -e "  ${GREEN}Simulator:${NC}      ws://localhost:8765"
    echo -e "  ${GREEN}AI Service:${NC}     ws://localhost:8766"
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  ${YELLOW}Commands:${NC}"
    echo -e "    Stop services:  python start_app.py stop"
    echo -e "    Restart:        python start_app.py restart"
    echo -e "    Check status:   python start_app.py status"
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════════════════════════════════════${NC}"
    echo ""
}

# Handle script interruption
trap 'echo -e "\n${RED}Script interrupted${NC}"; python3 "E:/projects/sih/start_app.py" stop 2>/dev/null; exit 1' INT TERM

# Main execution
main() {
    echo ""
    check_python
    check_deps
    check_env
    
    echo ""
    start_services
    wait_for_services
    open_browser
    print_status_info
}

# Run main
main