"""Throwaway: verify the backend fixes against the live server."""
import json
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8081"
EID = "TAPAS-BH-201-001"
fails = []


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


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}  {detail}")
    if not ok:
        fails.append(label)


print("1. fault history endpoint exists")
s, h = call("GET", "/api/faults/history")
check("GET /api/faults/history", s == 200, f"status {s}, count {h.get('count') if isinstance(h, dict) else h}")

print("\n2. residuals carry observed/expected/z_score")
call("POST", "/api/faults/clear")
s, start = call("POST", "/api/missions/start", {"engine_id": EID, "duration_s": 120, "name": "fix check A"})
mid_a = start.get("mission_id")
time.sleep(7)
s, st = call("GET", f"/api/engine/{EID}/state")
res = st.get("residuals") or []
print(f"  health={st.get('health_index')} cat={st.get('health_category')} fault={st.get('fault_class')}")
for r in res[:5]:
    print("   ", json.dumps(r))
complete = bool(res) and all(
    r.get("observed") is not None and r.get("expected") is not None and r.get("z_score") is not None
    for r in res
)
check("every residual has observed/expected/z_score", complete, f"{len(res)} channels")

print("\n3. REST injection is validated and logged")
s, inj = call("POST", "/api/faults/inject", {"fault_type": "MISFIRE", "severity": 0.8})
check("POST /api/faults/inject (valid)", s == 200, f"status {s}")
s, bad = call("POST", "/api/faults/inject", {"fault_type": "NOT_A_FAULT", "severity": 0.8})
check("POST /api/faults/inject (bogus) -> 400", s == 400, f"status {s} {bad if s != 400 else ''}")
s, h = call("GET", "/api/faults/history")
names = [f.get("fault_type") for f in (h.get("faults") or [])]
check("injection appears in history", "MISFIRE" in names, f"{names[:4]}")

print("\n4. a stale fault does not survive into the next mission")
call("POST", f"/api/missions/{mid_a}/stop")
s, sim = call("GET", "/api/simulation/status")
print(f"  after stop, simulator active_faults = {sim.get('active_faults')}")
s, start_b = call("POST", "/api/missions/start", {"engine_id": EID, "duration_s": 120, "name": "fix check B"})
mid_b = start_b.get("mission_id")
s, sim_b = call("GET", "/api/simulation/status")
check("new mission starts with no faults", sim_b.get("active_faults") == [],
      f"active_faults={sim_b.get('active_faults')}")
time.sleep(7)
s, stb = call("GET", f"/api/engine/{EID}/state")
print(f"  mission B: health={stb.get('health_index')} cat={stb.get('health_category')} "
      f"fault={stb.get('fault_class')}")
check("mission B is not EMERGENCY", stb.get("health_category") != "EMERGENCY",
      f"category={stb.get('health_category')}")
call("POST", f"/api/missions/{mid_b}/stop")

print("\n5. per-mission history filter")
s, h2 = call("GET", f"/api/faults/history?mission_id={mid_a}")
mitted = [f for f in (h2.get("faults") or [])]
check("history filters by mission", all(f["mission_id"] == mid_a for f in mitted),
      f"{len(mitted)} entries for mission A")

print(f"\n{'ALL CHECKS PASSED' if not fails else 'FAILURES: ' + ', '.join(fails)}")
