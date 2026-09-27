"""Throwaway: does the recalibrated fallback separate healthy from faulted runs?"""
import sys

sys.path.insert(0, "sih")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np                                              # noqa: E402

from ml.inference import FallbackAnalyzer                       # noqa: E402
from ml.training_data import generate_run                       # noqa: E402
from simulator.telemetry_gen.telemetry_schema import FaultType   # noqa: E402

CASES = [
    (None, 0.0, "HEALTHY"),
    (FaultType.INJECTOR_DEGRADATION, 0.7, "INJECTOR_DEGRADATION"),
    (FaultType.MISFIRE, 0.7, "MISFIRE"),
    (FaultType.LUBRICATION_FAILURE, 0.7, "LUBRICATION_FAILURE"),
    (FaultType.ABNORMAL_VIBRATION, 0.7, "ABNORMAL_VIBRATION"),
]

print(f"{'run':<24} {'anom mean':>9} {'anom p95':>9} {'anomaly%':>9} "
      f"{'sev mean':>9} {'top class':<22} {'health-frame rate':>17}")
summary = {}
for fault, severity, label in CASES:
    rows, meta = generate_run(fault, severity, seed=11, run_id=label.lower())
    analyzer = FallbackAnalyzer()
    preds = [analyzer.predict(r) for r in rows]

    # Second half of the run: for faulted runs that is well past fault onset.
    tail = preds[len(preds) // 2:]
    scores = np.array([p["anomaly_score"] for p in tail])
    sevs = np.array([p["severity"] for p in tail])
    anomal = np.array([bool(p["is_anomaly"]) for p in tail])
    classes = {}
    for p in tail:
        classes[p["fault_class"]] = classes.get(p["fault_class"], 0) + 1
    top = max(classes, key=classes.get)
    healthy_rate = classes.get("HEALTHY", 0) / len(tail)

    summary[label] = {
        "anomaly_mean": float(scores.mean()),
        "anomaly_p95": float(np.percentile(scores, 95)),
        "anomaly_rate": float(anomal.mean()),
        "severity_mean": float(sevs.mean()),
        "healthy_rate": float(healthy_rate),
    }
    print(f"{label:<24} {scores.mean():9.1f} {np.percentile(scores, 95):9.1f} "
          f"{anomal.mean() * 100:8.1f}% {sevs.mean():9.2f} {top:<22} "
          f"{healthy_rate * 100:16.1f}%")

h = summary["HEALTHY"]
print("\nacceptance criteria")
print(f"  healthy anomaly mean < 50            : {h['anomaly_mean']:.1f}  "
      f"{'PASS' if h['anomaly_mean'] < 50 else 'FAIL'}")
print(f"  healthy is_anomaly rate < 25%        : {h['anomaly_rate'] * 100:.0f}%  "
      f"{'PASS' if h['anomaly_rate'] < 0.25 else 'FAIL'}")
print(f"  healthy severity mean < 0.5          : {h['severity_mean']:.2f}  "
      f"{'PASS' if h['severity_mean'] < 0.5 else 'FAIL'}")
for label, s in summary.items():
    if label == "HEALTHY":
        continue
    print(f"  {label:<20} anomaly mean > healthy   : {s['anomaly_mean']:.1f}  "
          f"{'PASS' if s['anomaly_mean'] > h['anomaly_mean'] else 'FAIL'}")
