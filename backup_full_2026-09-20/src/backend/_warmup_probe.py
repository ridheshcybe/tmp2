"""Throwaway: does health recover after warm-up, or is a healthy engine stuck? """
import json
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8081"
EID = "TAPAS-BH-201-001"


def call(method, path, body=None, timeout=15):
    req = urllib.request.Request(BASE + path, method=method)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": e.code}
    except Exception as e:                                     # noqa: BLE001
        return {"error": str(e)}


print("clean slate: clear faults, start a fresh 300 s mission")
call("POST", "/api/faults/clear")
start = call("POST", "/api/missions/start", {
    "engine_id": EID, "duration_s": 300, "ambient_offset_c": 0.0, "name": "warmup probe",
})
mid = start.get("mission_id")
print("mission:", mid)

print(f"\n{'t':>5} {'rpm':>6} {'cht':>6} {'egt':>6} {'ehi':>6} {'anom':>6} "
      f"{'fault':<22} {'cat':<10}")
for i in range(13):
    t = i * 5
    tel = call("GET", f"/api/engine/{EID}/telemetry?limit=1")
    frames = tel.get("frames") or []
    f = frames[-1] if frames else {}
    h = call("GET", f"/api/engine/{EID}/state")
    if "error" in h:
        print(f"{t:5} telemetry/state unavailable: {h['error']}")
    else:
        cht = f.get("cht") or [0]
        egt = f.get("egt") or [0]
        print(f"{t:5} {f.get('rpm', 0):6.0f} "
              f"{sum(cht) / len(cht):6.1f} {sum(egt) / len(egt):6.1f} "
              f"{h.get('health_index', 0):6.1f} {h.get('anomaly_score', 0):6.1f} "
              f"{str(h.get('fault_class')):<22} {str(h.get('health_category')):<10}")
    if i < 12:
        time.sleep(5)

print("\nresiduals (last frame):")
st = call("GET", f"/api/engine/{EID}/state")
for r in (st.get("residuals") or [])[:12]:
    print(f"  {r.get('channel'):<12} observed {r.get('observed'):>8.1f} "
          f"expected {r.get('expected'):>8.1f} residual {r.get('residual'):>8.1f} "
          f"z={r.get('z_score'):>7.2f}")
print("  expected:", json.dumps(st.get("expected"))[:300])
print("  explanation:", json.dumps(st.get("health_explanation"))[:300])

call("POST", f"/api/missions/{mid}/stop")
print("\nstopped")
