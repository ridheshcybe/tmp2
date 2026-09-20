#!/usr/bin/env python3
"""
Standalone AeroTwin Digital Twin Application Launcher

Removes Docker dependency. Runs services as standalone processes.
Usage: python start_app.py start|stop|status|restart
"""
import subprocess, sys, os, time, json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
processes = {}

SERVICES = [
    {"name": "simulator", "command": "python -m simulator.telemetry_streamer",
     "env": {"SIMULATION_HZ": "10", "WEBSOCKET_PORT": "8765"}, "port": 8765},
    {"name": "ai_service", "command": "python -m fusion_ml.ai_service",
     "env": {"SIMULATOR_WS_URL": "ws://localhost:8765", "BACKEND_WS_URL": "ws://localhost:8766", "PYTHONPATH": str(PROJECT_ROOT)}, "port": 8766},
    {"name": "backend", "command": "node dist/index.js",
     "env": {"NODE_ENV": "production", "AI_STREAM_PORT": "8766", "CLIENT_WS_PORT": "8080", "DATABASE_URL": "postgres://postgres:password@localhost:5432/aerotwin"}, "port": 8080},
]


def start_service(svc):
    """Start a single service as a subprocess."""
    print(f"[START] {svc['name']}: {svc['command']}")
    env = os.environ.copy()
    for k, v in svc.get("env", {}).items():
        env[k] = v
    proc = subprocess.Popen(
        svc["command"], shell=True, env=env, cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
    )
    processes[svc["name"]] = proc
    print(f"  -> PID: {proc.pid}")
    return proc

def wait_for_health(port, max_attempts=30, interval=2):
    """Wait for a service to become healthy via health check endpoint."""
    import requests
    url = f"http://localhost:{port}/health"
    for i in range(max_attempts):
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                print(f"[HEALTHY] Port {port} is responding")
                return True
        except Exception as e:
            pass
        time.sleep(interval)
    print(f"[FAIL] Port {port} did not become healthy within {max_attempts} attempts")
    return False

def start_all():
    """Start all services in order."""
    print("=" * 60)
    print("Starting AeroTwin Digital Twin App (Standalone Mode)")
    print("=" * 60)
    for i, svc in enumerate(SERVICES):
        print(f"\n[{i+1}/{len(SERVICES)}] Starting {svc['name']}...")
        start_service(svc)
        if i < len(SERVICES) - 1:
            time.sleep(3)
    print("\n[SUCCESS] All services started!")
    return True

def stop_all():
    """Stop all services."""
    print("\nStopping all services...")
    for name, proc in sorted(processes.items(), key=lambda x: x[1].pid, reverse=True):
        if proc:
            print(f"  -> Stopping {name} (PID: {proc.pid})")
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                print(f"  -> Force killed {name}")
    print("All services stopped.")
    return True

def status():
    """Print the status of all services."""
    print("\n" + "=" * 60)
    print("Service Status")
    print("=" * 60)
    for name, proc in sorted(processes.items(), key=lambda x: x[1].pid, reverse=True):
        state = "RUNNING" if proc.poll() is None else "STOPPED"
        print(f"{name}: {state}")
    print()

def main():
    if len(sys.argv) < 2:
        print("Usage: python start_app.py [start|stop|status|restart]")
        sys.exit(1)

    command = sys.argv[1]

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
        print(f"Unknown command: {command}")
        print("Valid commands: start, stop, status, restart")
        sys.exit(1)

if __name__ == "__main__":
    main()