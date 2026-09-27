"""
Demo: Engine Health Index dashboard output.
===========================================

Streams a telemetry CSV (telemetry_gen output) through the trained ML
pipeline and the Health Index calculator, then writes:

* ``data/ehi_timeline.csv``             — per-row EHI, category, alert, top contributor
* ``data/ehi_dashboard_example.txt``    — dashboard-style snapshots + explanations

    python -m ml.demo_health_index --csv data/aerotwin_faulty_demo.csv [--every 2]

If the trained models are missing, the rule-based fallback is used (the
index still works — with lower confidence, as designed).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import Dict, List, Optional

from ml.health_index import HealthIndexCalculator
from ml.inference import build_pipeline


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="ml.demo_health_index")
    parser.add_argument("--csv", default="data/aerotwin_faulty_demo.csv")
    parser.add_argument("--model-dir", default="ml/models")
    parser.add_argument("--every", type=int, default=1,
                        help="process every Nth row (speed vs resolution)")
    parser.add_argument("--out-csv", default="data/ehi_timeline.csv")
    parser.add_argument("--out-txt", default="data/ehi_dashboard_example.txt")
    args = parser.parse_args(argv)

    pipe = build_pipeline(args.model_dir)
    bundle = None
    try:
        with open(f"{args.model_dir}/bundle.json", encoding="utf-8") as fh:
            bundle = json.load(fh)
    except Exception:
        pass
    calc = HealthIndexCalculator(
        healthy_stats=(bundle or {}).get("healthy_residual_stats")
    )

    timeline: List[Dict[str, object]] = []
    snapshots: List[Dict[str, object]] = []
    n = 0

    with open(args.csv, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            row = {k: (float(v) if v not in ("", "None") else None)
                   for k, v in raw.items()}
            row["phase"] = str(raw.get("phase", ""))
            if n % args.every != 0:
                n += 1
                continue
            n += 1

            pred = pipe.predict_row(row) if hasattr(pipe, "predict_row") else pipe.predict(row)
            if pred.get("warmup"):
                continue
            res = calc.update(row, pred)
            res["sim_time_s"] = round(float(row.get("sim_time_s", 0.0)), 1)
            res["phase"] = str(row.get("phase", ""))
            timeline.append(res)

            # snapshot every ~15 min (900 s)
            if int(res["sim_time_s"]) % 900 < args.every:
                snapshots.append(res)

    # ── timeline CSV ──
    with open(args.out_csv, "w", newline="", encoding="utf-8") as fh:
        cols = ["sim_time_s", "phase", "ehi", "category", "alert_level", "trend",
                "anomaly_score", "fault_class", "severity", "rul_min", "confidence"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in timeline:
            w.writerow(r)
    print(f"  timeline     : {args.out_csv} ({len(timeline)} rows)")

    # ── dashboard example text ──
    lines: List[str] = [
        "=" * 66,
        "  AeroTwin — Engine Health Index · dashboard example (synthetic demo)",
        "=" * 66,
    ]
    for i, r in enumerate(snapshots):
        if i == 0 or r["alert_level"] != snapshots[i - 1]["alert_level"] or i == len(snapshots) - 1:
            lines.append("")
            lines.append(f"--- t={r['sim_time_s']:.0f}s  phase={r['phase']} ---")
            lines.extend(r["explanation"])
            lines.append(f"  alert: {r['alert_level']}  "
                         f"confidence: {r['confidence']}  "
                         f"data quality: {r['data_quality']['fraction_valid']:.0%} valid")
    with open(args.out_txt, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    print(f"  dashboard    : {args.out_txt}")
    print("\n".join(lines[-12:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())