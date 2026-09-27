"""Throwaway: which channel pins the fallback anomaly score at 100 on a healthy start?"""
import sys

sys.path.insert(0, "sih")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from ml.inference import FallbackAnalyzer          # noqa: E402
from ml.physics_baseline import residual_summary   # noqa: E402
from ml.training_data import generate_run          # noqa: E402

rows, meta = generate_run(None, 0.0, seed=11, run_id="forensics")
analyzer = FallbackAnalyzer()

print(f"{'t':>6} {'phase':<10} {'rpm':>6} {'anom':>6} {'sev':>5}  channels with |z|>=3")
worst = {}
for row in rows[:90]:
    res = residual_summary(row)
    zs = {k: (res.get(k, 0.0) - s["mean"]) / s["std"] for k, s in analyzer.stats.items()}
    pred = analyzer.predict(row)
    hot = {k: round(v, 1) for k, v in zs.items() if abs(v) >= 3.0}
    for k, v in zs.items():
        if abs(v) > abs(worst.get(k, 0.0)):
            worst[k] = v
    if row["sim_time_s"] % 10 == 0:
        print(f"{row['sim_time_s']:6.0f} {str(row['phase']):<10} {row['rpm']:6.0f} "
              f"{pred['anomaly_score']:6.1f} {pred['severity']:5.2f}  {hot}")

print("\nmax |z| reached per channel over the first 90 frames:")
for k, v in sorted(worst.items(), key=lambda x: -abs(x[1])):
    print(f"  {k:<10} {v:+9.2f}   (healthy baseline mean={analyzer.stats[k]['mean']:+.3f}, "
          f"std={analyzer.stats[k]['std']:.3f})")
print("\nmeta durations:", meta)
