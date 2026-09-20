"""Throwaway: warm healthy engine nominal, injected fault escalates, clear recovers."""
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
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw[:200]
    except Exception as e:                                     # noqa: BLE001
        return 0, str(e)


def snap(label):
    _, st = call("GET", f"/api/engine/{EID}/state")
    obs = st.get("observed") or {}
    cht = obs.get("cht") or [0]
    print(f"  {label:<26} cht={sum(cht) / 4:6.1f} anom={st.get('anomaly_score', 0):6.1f} "
          f"ehi={st.get('health_index', 0):5.1f} cat={str(st.get('health_category')):<10} "
          f"fault={str(st.get('fault_class')):<22} warm={st.get('warming_up')}")
    return st


fails = []
call("POST", "/api/faults/clear")
_, start = call("POST", "/api/missions/start", {"engine_id": EID, "duration_s": 300, "name": "fault path"})
mid = start.get("mission_id")

print("warming the engine (35 s)...")
time.sleep(35)
st = snap("after warm-up")
if st.get("health_category") not in ("NORMAL", "WATCH"):
    fails.append(f"warm healthy engine read {st.get('health_category')}")
if st.get("warming_up"):
    fails.append("engine reported warming_up after 35 s")

print("\ninjecting INJECTOR_DEGRADATION severity 0.9 (REST) ...")
status, inj = call("POST", "/api/faults/inject", {"fault_type": "INJECTOR_DEGRADATION", "severity": 0.9})
print(f"  POST /api/faults/inject -> {status}")
for i in (5, 12, 20):
    time.sleep(5 if i == 5 else 7)
    snap(f"faulted, +~{i}s")

print("\nclearing faults ...")
status, cleared = call("POST", "/api/faults/clear")
print(f"  POST /api/faults/clear -> {status}")
time.sleep(20)
st = snap("after clear")

status, hist = call("GET", f"/api/faults/history?mission_id={mid}")
rows = hist.get("faults") or []
print(f"\n  fault history for this mission: {[(r['fault_type'], r['severity']) for r in rows]}")

if not rows:
    fails.append("fault history empty for the mission")

call("POST", f"/api/missions/{mid}/stop")
print(f"\n{'ALL CHECKS PASSED' if not fails else 'FAILURES: ' + '; '.join(fails)}")
