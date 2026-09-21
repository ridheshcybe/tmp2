"""
Training CLI — the full lightweight pipeline in one command.
=============================================================

    python -m ml.train --runs-per-fault 2 --healthy-runs 4 --model-dir ml/models

Steps
-----
1. Generate labelled runs (healthy + all 8 faults) via
   :mod:`ml.training_data` (deterministic seeds).
2. Extract features (physics residuals + rolling stats + correlations +
   conditions) per run.
3. **Run-level** train / val / test split (no leakage).
4. Train:
   * Anomaly — Isolation Forest on healthy-only training windows; the
     anomaly threshold is fit on *validation* healthy windows.
   * Fault classification — Random Forest (9 classes).
   * Degradation — Random Forest regressor on severity ∈ [0, 1].
   * RUL — Random Forest regressor on log(remaining minutes).
5. Evaluate on the held-out test runs (metrics + confusion matrix + report).
6. Serialize everything (joblib models + metadata JSON) to ``--model-dir``.

Why not an LSTM? The engineered features (trends, rolling std, correlations)
already encode the temporal patterns an LSTM would have to learn from raw
series; a tree ensemble reaches the same accuracy with ~100× less data, no
GPU, and free explainability via feature importances and tree variance.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, RandomForestClassifier, RandomForestRegressor
from sklearn.preprocessing import StandardScaler

from ml import evaluate
from ml.feature_engineering import batch_features_indexed, feature_names
from ml.labels import HEALTHY_LABEL, RunMeta, compute_rul_s, label_row, split_runs
from ml.physics_baseline import residual_summary
from ml.training_data import generate_training_runs

WINDOW_S = 60
TREND_S = 180
STEP = 5
ANOMALY_CONTAM = 0.10          # expected healthy false-positive share (IF prior)
ANOMALY_VAL_P = 0.95           # healthy-only threshold quantile, fit on validation

# ──────────────────────────────────────────────────────────────────────────
#  Dataset assembly
# ──────────────────────────────────────────────────────────────────────────


def build_dataset(
    runs: List[Tuple[List[Dict[str, object]], RunMeta]],
    window_s: int = WINDOW_S,
    trend_s: int = TREND_S,
    step: int = STEP,
) -> Tuple[pd.DataFrame, Dict[str, np.ndarray], Dict[str, RunMeta]]:
    """
    Extract features + labels for every run.

    Returns ``(X, Y, meta_by_run)`` where ``Y`` holds aligned arrays for
    ``class``, ``severity``, ``rul_min``, ``is_fault`` and ``run_id``.
    """
    frames: List[pd.DataFrame] = []
    ys: Dict[str, List] = {
        "class": [], "severity": [], "rul_min": [], "is_fault": [],
        "run_id": [], "sim_time_s": [],
    }
    meta_by_run: Dict[str, RunMeta] = {}

    for rows, meta in runs:
        meta_by_run[meta.run_id] = meta
        features = batch_features_indexed(rows, window_s, trend_s, step)
        if not features:
            continue
        feats = [f for f, _ in features]
        idxs = [i for _, i in features]
        frames.append(pd.DataFrame.from_records(feats))

        for _, row_idx in zip(feats, idxs):
            row = rows[row_idx]
            cls, sev = label_row(row)
            ys["class"].append(cls)
            ys["severity"].append(sev)
            ys["rul_min"].append(compute_rul_s(row, meta) / 60.0)
            ys["is_fault"].append(int(cls != HEALTHY_LABEL))
            ys["run_id"].append(meta.run_id)
            ys["sim_time_s"].append(float(row["sim_time_s"]))

    X = pd.concat(frames, ignore_index=True)
    Y = {k: np.asarray(v) for k, v in ys.items()}
    return X, Y, meta_by_run


def _fit_anomaly(
    X_tr_healthy: pd.DataFrame,
    X_val_healthy: pd.DataFrame,
    seed: int,
) -> Tuple[IsolationForest, StandardScaler, float]:
    """IsolationForest + scaler; threshold = P95 of healthy val decisions."""
    scaler = StandardScaler().fit(X_tr_healthy.values)
    Xs = scaler.transform(X_tr_healthy.values)
    model = IsolationForest(
        n_estimators=200,
        contamination=ANOMALY_CONTAM,
        random_state=seed,
        n_jobs=-1,
    ).fit(Xs)

    val_decision = model.decision_function(scaler.transform(X_val_healthy.values))
    threshold = float(np.percentile(val_decision, ANOMALY_VAL_P * 100.0))
    return model, scaler, threshold


def _fallback_stats(X_tr_healthy: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    """Healthy mean/std per residual feature — powers the no-ML fallback."""
    res_cols = [c for c in X_tr_healthy.columns if c.startswith("r_")]
    stats: Dict[str, Dict[str, float]] = {}
    for c in res_cols:
        s = X_tr_healthy[c]
        stats[c] = {"mean": float(s.mean()), "std": float(s.std())}
    return stats


def _fit_models(
    X_tr: pd.DataFrame,
    Y_tr: Dict[str, np.ndarray],
    seed: int,
) -> Dict[str, object]:
    clf = RandomForestClassifier(
        n_estimators=250, max_depth=14, min_samples_leaf=5,
        class_weight="balanced", random_state=seed, n_jobs=-1,
    ).fit(X_tr.values, Y_tr["class"])

    deg = RandomForestRegressor(
        n_estimators=150, max_depth=10, random_state=seed, n_jobs=-1,
    ).fit(X_tr.values, Y_tr["severity"].astype(float))

    rul_y = np.log1p(Y_tr["rul_min"].astype(float))
    rul = RandomForestRegressor(
        n_estimators=200, max_depth=12, random_state=seed, n_jobs=-1,
    ).fit(X_tr.values, rul_y)

    return {"classifier": clf, "degradation": deg, "rul": rul}


# ──────────────────────────────────────────────────────────────────────────
#  CLI
# ──────────────────────────────────────────────────────────────────────────


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ml.train", description="train the lightweight AeroTwin ML pipeline"
    )
    parser.add_argument("--runs-per-fault", type=int, default=2)
    parser.add_argument("--healthy-runs", type=int, default=4)
    parser.add_argument("--severity", type=float, default=0.7)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--model-dir", default="ml/models")
    parser.add_argument("--window-s", type=int, default=WINDOW_S)
    parser.add_argument("--trend-s", type=int, default=TREND_S)
    parser.add_argument("--step", type=int, default=STEP)
    args = parser.parse_args(argv)

    print("=" * 72)
    print("  AeroTwin lightweight ML pipeline — train")
    print("=" * 72)

    # 1 ── generate runs
    print(f"[1/6] generating runs "
          f"(faults={args.runs_per_fault}/type, healthy={args.healthy_runs}, "
          f"severity={args.severity}, seed={args.seed})")
    runs = generate_training_runs(
        runs_per_fault=args.runs_per_fault,
        healthy_runs=args.healthy_runs,
        severity=args.severity,
        base_seed=args.seed,
    )
    print(f"      → {len(runs)} runs")

    # 2 ── features + labels
    print(f"[2/6] extracting features (window={args.window_s}s, trend={args.trend_s}s, step={args.step})")
    X, Y, meta_by_run = build_dataset(runs, args.window_s, args.trend_s, args.step)
    print(f"      → {X.shape[0]} windows × {X.shape[1]} features; "
          f"classes={sorted(set(Y['class']))}")

    # 3 ── run-level split
    metas = list(meta_by_run.values())
    tr_meta, va_meta, te_meta = split_runs(metas, val_frac=0.2, test_frac=0.2, seed=args.seed)
    tr_mask = np.isin(Y["run_id"], [m.run_id for m in tr_meta])
    va_mask = np.isin(Y["run_id"], [m.run_id for m in va_meta])
    te_mask = np.isin(Y["run_id"], [m.run_id for m in te_meta])
    print(f"[3/6] run-level split: train={len(tr_meta)} val={len(va_meta)} "
          f"test={len(te_meta)} runs "
          f"({int(tr_mask.sum())}/{int(va_mask.sum())}/{int(te_mask.sum())} windows)")

    X_tr, X_va, X_te = X[tr_mask], X[va_mask], X[te_mask]
    Y_tr = {k: v[tr_mask] for k, v in Y.items()}
    Y_va = {k: v[va_mask] for k, v in Y.items()}
    Y_te = {k: v[te_mask] for k, v in Y.items()}

    # 4 ── train
    print("[4/6] training models")
    healthy_tr = X_tr[Y_tr["class"] == HEALTHY_LABEL]
    healthy_va = X_va[Y_va["class"] == HEALTHY_LABEL]
    anomaly, scaler, thr = _fit_anomaly(healthy_tr, healthy_va, args.seed)
    anomaly_scale = float(np.std(
        anomaly.decision_function(scaler.transform(healthy_va.values))
    )) if len(healthy_va) > 1 else 0.05
    models = _fit_models(X_tr, Y_tr, args.seed)
    print(f"      → anomaly: IF(200 trees) threshold={thr:.3f} (P{int(ANOMALY_VAL_P * 100)} healthy val)")
    print(f"      → classifier: RF(250) on {len(set(Y_tr['class']))} classes")
    print(f"      → degradation: RF(150) on severity ∈ [0, {args.severity}]")
    print(f"      → rul: RF(200) on log1p(remaining minutes)")

    # 5 ── evaluate on held-out test runs
    print("[5/6] evaluating on held-out test runs")
    metrics = evaluate.evaluate_models(
        models, anomaly, scaler, thr, X_te, Y_te, meta_by_run
    )
    evaluate.write_report(metrics, args.model_dir)

    # 6 ── serialize
    print(f"[6/6] serializing to {args.model_dir}")
    import joblib
    import os
    os.makedirs(args.model_dir, exist_ok=True)
    joblib.dump(anomaly, f"{args.model_dir}/anomaly.joblib")
    joblib.dump(scaler, f"{args.model_dir}/anomaly_scaler.joblib")
    joblib.dump(models["classifier"], f"{args.model_dir}/classifier.joblib")
    joblib.dump(models["degradation"], f"{args.model_dir}/degradation.joblib")
    joblib.dump(models["rul"], f"{args.model_dir}/rul.joblib")

    bundle = {
        "feature_names": feature_names(args.window_s, args.trend_s),
        "class_names": sorted(set(Y["class"])),
        "window_s": args.window_s,
        "trend_s": args.trend_s,
        "anomaly_threshold": thr,
        "anomaly_val_decision_std": anomaly_scale,
        "anomaly_contamination": ANOMALY_CONTAM,
        "healthy_residual_stats": _fallback_stats(healthy_tr),
        "training": {
            "runs": len(runs),
            "windows": int(len(X)),
            "runs_per_fault": args.runs_per_fault,
            "healthy_runs": args.healthy_runs,
            "severity": args.severity,
            "seed": args.seed,
        },
        "metrics": {k: (float(v) if isinstance(v, (int, float)) else v) for k, v in metrics.items()},
    }
    with open(f"{args.model_dir}/bundle.json", "w", encoding="utf-8") as fh:
        json.dump(bundle, fh, indent=2, sort_keys=True)
    print(f"      → saved anomaly.joblib, classifier.joblib, degradation.joblib, "
          f"rul.joblib, bundle.json, metrics.json, report.md"
          f"{', confusion_matrix.png' if metrics.get('confusion_matrix_png') else ''}")

    evaluate.print_summary(metrics)
    return 0


if __name__ == "__main__":
    sys.exit(main())