"""Throwaway: exercise every AeroTwin backend endpoint and report what works."""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8081"
EID = "TAPAS-BH-201-001"


def call(method, path, body=None, timeout=25):
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
    except Exception as e:                                    # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def show(label, status, payload, keys=None):
    mark = "OK " if 200 <= status < 300 else "ERR"
    body = ""
    if isinstance(payload, dict):
        if keys:
            body = json.dumps({k: payload.get(k) for k in keys})[:220]
        else:
            body = ", ".join(list(payload)[:10])
    else:
        body = str(payload)[:160]
    print(f"  {mark} {status:3} {label:34} {body}")


results = []

print("== health ==")
s, p = call("GET", "/health")
show("GET /health", s, p)
results.append(("/health", s))

print("\n== mission lifecycle ==")
s, p = call("POST", "/api/missions/start", {
    "engine_id": EID, "duration_s": 180, "ambient_offset_c": 5.0, "name": "smoke test",
})
show("POST /api/missions/start", s, p, ["mission_id", "status", "started_at"])
results.append(("POST /api/missions/start", s))
mid = p.get("mission_id") if isinstance(p, dict) else None

print("  (letting the simulator run 10 s)")
time.sleep(10)

print("\n== engine state (REST) ==")
for path, keys in [
    (f"/api/engine/{EID}/state", ["health_index", "health_category", "fault_class",
                                  "anomaly_score", "rul_minutes", "rtb_alert"]),
    (f"/api/engine/{EID}/health", ["health_index", "category", "trend", "confidence"]),
    (f"/api/engine/{EID}/faults", ["fault_class", "confidence", "severity", "criticality"]),
    (f"/api/engine/{EID}/rul", ["rul_minutes", "confidence", "trend", "rtb_alert"]),
    (f"/api/engine/{EID}/telemetry?limit=5", ["count"]),
]:
    s, p = call("GET", path)
    show("GET " + path, s, p, keys)
    results.append(("GET " + path, s))

print("\n== simulation control ==")
for label, path, body in [
    ("POST /api/simulation/throttle", "/api/simulation/throttle", {"throttle": 0.85}),
    ("POST /api/simulation/altitude", "/api/simulation/altitude", {"altitude_ft": 14000}),
    ("GET  /api/simulation/status", "/api/simulation/status", None),
]:
    m = "GET" if path.startswith("/api/simulation/status") else "POST"
    s, p = call(m, path, body)
    show(label, s, p)
    results.append((label, s))

print("\n== faults ==")
s, p = call("GET", "/api/faults/types")
show("GET /api/faults/types", s, p)
results.append(("GET /api/faults/types", s))
if isinstance(p, dict):
    types = p.get("fault_types")
    if isinstance(types, list) and types:
        if isinstance(types[0], dict):
            print("      fault type entries:", json.dumps(types[0])[:200])
            print("      all names:", [t.get("fault_type") or t.get("name") for t in types])
        else:
            print("      all names:", types)

for label, path, body in [
    ("POST /api/faults/inject", "/api/faults/inject",
     {"fault_type": "MISFIRE", "severity": 0.8}),
    ("POST /api/faults/clear", "/api/faults/clear", None),
]:
    s, p = call("POST", path, body)
    show(label, s, p)
    results.append((label, s))

print("\n== replay ==")
if mid:
    for label, path, body in [
        ("GET  /api/replay/frames/{id}", f"/api/replay/frames/{mid}?limit=5", None),
        ("POST /api/replay/start", "/api/replay/start",
         {"mission_id": mid, "speed": 2.0}),
        ("GET  /api/replay/status", "/api/replay/status", None),
    ]:
        m = "GET" if "GET" in label else "POST"
        s, p = call(m, path, body)
        show(label, s, p)
        results.append((label, s))
        if label.startswith("GET  /api/replay/frames") and isinstance(p, dict):
            frames = p.get("data") or []
            if frames:
                print("      frame keys:", sorted(frames[0].keys()))

print("\n== missions ==")
for label, path, body in [
    ("GET  /api/missions", "/api/missions?limit=5", None),
    ("GET  /api/missions/{id}", f"/api/missions/{mid}", None),
    ("GET  /api/missions/{id}/summary", f"/api/missions/{mid}/summary", None),
]:
    s, p = call("GET", path, body)
    show(label, s, p)
    results.append((label, s))
    if label.endswith("/summary}") and isinstance(p, dict):
        print("      summary keys:", sorted(p.keys()))

print("\n== reports ==")
if mid:
    for label, path in [
        ("GET  /api/reports/{id}", f"/api/reports/{mid}"),
        ("GET  /api/reports/{id}/health-timeline", f"/api/reports/{mid}/health-timeline"),
        ("GET  /api/reports/{id}/download", f"/api/reports/{mid}/download"),
    ]:
        s, p = call("GET", path)
        show(label, s, p)
        results.append((label, s))
        if label.endswith("/{id}") and isinstance(p, dict):
            print("      report keys:", sorted(p.keys()))
            print("      executive_summary:", str(p.get("executive_summary"))[:180])

print("\n== stop mission ==")
if mid:
    s, p = call("POST", f"/api/missions/{mid}/stop")
    show("POST /api/missions/{id}/stop", s, p)
    results.append(("POST /api/missions/{id}/stop", s))

print("\n== untested-by-frontend code paths ==")
s, p = call("GET", "/api/logs/download")
show("GET /api/logs/download (modal)", s, p)
results.append(("GET /api/logs/download", s))

bad = [(n, s) for n, s in results if not (200 <= s < 300)]
print(f"\n== {len(results) - len(bad)}/{len(results)} endpoints OK ==")
for n, s in bad:
    print(f"  FAILED {s:3} {n}")
sys.exit(0)
