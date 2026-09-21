"""Throwaway: what drives the health index during a cold mission start?"""
import json
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8081"
EID = "TAPAS-BH-201-001"


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
start = call("POST", "/api/missions/start", {"engine_id": EID, "duration_s": 180, "name": "cold probe"})
mid = start.get("mission_id")
print("mission:", mid, "\n")

print(f"{'t':>4} {'phase':<10} {'rpm':>5} {'cht':>6} {'ehi':>6} {'anom':>6} {'cat':<10} contributors")
for i in range(11):
    st = call("GET", f"/api/engine/{EID}/state")
    if "error" in st:
        print(f"{i * 4:4} unavailable: {st}")
        time.sleep(4)
        continue
    obs = st.get("observed") or {}
    cht = obs.get("cht") or [0]
    cons = st.get("health_contributors") or []
    brief = "; ".join(
        f"{(c.get('label') or c.get('channel'))}={c.get('penalty')}" for c in cons[:4]
    )
    print(f"{i * 4:4} {str(obs.get('phase')):<10} {obs.get('rpm', 0):5.0f} "
          f"{sum(cht) / max(1, len(cht)):6.1f} {st.get('health_index', 0):6.1f} "
          f"{st.get('anomaly_score', 0):6.1f} {str(st.get('health_category')):<10} {brief}")

st = call("GET", f"/api/engine/{EID}/state")
print("\nexplanation:", json.dumps(st.get("health_explanation"), indent=2)[:900])
print("\ncontributors:", json.dumps(st.get("health_contributors"), indent=2)[:900])
print("\nalerts:", json.dumps(st.get("alerts"))[:400])
call("POST", f"/api/missions/{mid}/stop")
print("\nstopped")
