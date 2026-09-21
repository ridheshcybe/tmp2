"""Throwaway: live trajectory of a fresh mission — when does health stabilise?"""
import json
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8081"
EID = "TAPAS-BH-201-001"
SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 150


def call(method, path, body=None, timeout=20):
    req = urllib.request.Request(BASE + path, method=method)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()[:200]}
    except Exception as e:                                     # noqa: BLE001
        return {"error": str(e)}


call("POST", "/api/faults/clear")
start = call("POST", "/api/missions/start", {"engine_id": EID, "duration_s": 600, "name": "trajectory"})
mid = start.get("mission_id")
print("mission:", mid)
print(f"\n{'t':>5} {'phase':<10} {'rpm':>6} {'thr':>5} {'cht':>6} {'egt':>6} "
      f"{'anom':>6} {'ehi':>6} {'sev':>5} {'cat':<10} drivers")

t0 = time.time()
while time.time() - t0 < SECONDS:
    st = call("GET", f"/api/engine/{EID}/state")
    el = int(time.time() - t0)
    if "error" in st:
        print(f"{el:5} unavailable: {st}")
    else:
        obs = st.get("observed") or {}
        cht = obs.get("cht") or [0]
        egt = obs.get("egt") or [0]
        cons = st.get("health_contributors") or []
        drivers = ", ".join(f"{c.get('component')}={c.get('penalty')}" for c in cons[:3])
        print(f"{el:5} {str(obs.get('phase')):<10} {obs.get('rpm', 0):6.0f} "
              f"{obs.get('throttle', 0):5.2f} {sum(cht) / 4:6.1f} {sum(egt) / 4:6.1f} "
              f"{st.get('anomaly_score', 0):6.1f} {st.get('health_index', 0):6.1f} "
              f"{st.get('fault_severity', 0):5.2f} {str(st.get('health_category')):<10} {drivers}")
    time.sleep(10)

call("POST", f"/api/missions/{mid}/stop")
print("\nstopped")
