"""
Evaluation — metrics, detection latency, reports.
=================================================

All metrics are computed on **held-out test runs** (never the training runs).

Anomaly detection
    ROC-AUC, precision/recall at the deployed threshold, false-alarm rate on
    healthy test windows, and *detection latency*: for each faulted test run,
    seconds from fault onset to the first flagged window.

Fault classification
    accuracy, macro-averaged F1 (per class), confusion matrix (PNG + table).

Degradation & RUL
    RMSE / MAE / R² and "within ±20%" for RUL in minutes.

Why accuracy alone is insufficient
    On imbalanced streaming data a classifier that always says "healthy" gets
    ~90% accuracy. We therefore report per-class F1, false-alarm rate and
    *latency*, which is the metric that actually matters for a 30-minute
    return-to-base decision.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix as cm_fun,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_recall_fscore_support,
    r2_score,
    roc_auc_score,
)

from ml.labels import HEALTHY_LABEL, RunMeta

# ──────────────────────────────────────────────────────────────────────────
#  Core metrics
# ──────────────────────────────────────────────────────────────────────────


def _anomaly_metrics(anomaly, scaler, threshold, X_te, Y_te) -> Dict[str, float]:
    decision = anomaly.decision_function(scaler.transform(X_te.values))
    pred = (decision < threshold).astype(int)
    y = Y_te["is_fault"].astype(int)

    out: Dict[str, float] = {}
    if len(set(y)) > 1:
        out["anomaly_roc_auc"] = float(roc_auc_score(y, -decision))  # lower=more anomalous
    out["anomaly_precision"] = float(_p_or_r(y, pred, "precision"))
    out["anomaly_recall"] = float(_p_or_r(y, pred, "recall"))
    healthy = y == 0
    out["anomaly_false_alarm_rate"] = float(
        pred[healthy].mean() if healthy.any() else 0.0
    )
    return out


def _classification_metrics(clf, X_te, Y_te) -> Dict[str, object]:
    pred = clf.predict(X_te.values)
    y = Y_te["class"]
    out: Dict[str, object] = {
        "accuracy": float(accuracy_score(y, pred)),
        "f1_macro": float(f1_score(y, pred, average="macro", zero_division=0)),
    }
    support = precision_recall_fscore_support(
        y, pred, average=None, zero_division=0, labels=sorted(set(y))
    )
    classes = sorted(set(y))
    out["per_class_f1"] = {
        c: float(f1) for c, f1 in zip(classes, support[2])
    }
    out["per_class_recall"] = {
        c: float(r) for c, r in zip(classes, support[0])
    }
    return out


def _regression_metrics(model, X_te, Y_te, target: str, log_scale: bool = False) -> Dict[str, float]:
    y = Y_te[target].astype(float)
    if log_scale:
        pred = np.expm1(model.predict(X_te.values))
    else:
        pred = model.predict(X_te.values)
    pred = np.clip(pred, 0.0, None)
    mae = mean_absolute_error(y, pred)
    rmse = float(np.sqrt(mean_squared_error(y, pred)))
    out: Dict[str, float] = {
        f"{target}_rmse": rmse,
        f"{target}_mae": mae,
        f"{target}_r2": float(r2_score(y, pred)),
    }
    if target == "rul_min":
        within = np.mean(np.abs(pred - y) <= 0.2 * np.maximum(y, 1.0))
        out["rul_within_20pct"] = float(within)
    return out


def detection_latency(
    clf, anomaly, scaler, threshold, X_te, Y_te, meta_by_run: Dict[str, RunMeta]
) -> Dict[str, float]:
    """
    Seconds from fault onset to the first flagged window, per faulted test
    run. Flagged = classifier predicts a fault **or** the anomaly detector
    fires. Healthy runs are skipped.
    """
    decision = anomaly.decision_function(scaler.transform(X_te.values))
    clf_pred = clf.predict(X_te.values)

    per_run: Dict[str, List[float]] = {}
    for i in range(len(Y_te["run_id"])):
        run_id = str(Y_te["run_id"][i])
        meta = meta_by_run[run_id]
        if not meta.faulted:
            continue
        onset = meta.onset_s
        t = float(Y_te["sim_time_s"][i])
        if t < onset:
            continue
        flagged = clf_pred[i] != HEALTHY_LABEL or float(decision[i]) < threshold
        if flagged:
            per_run.setdefault(run_id, []).append(t - onset)

    latencies = [min(v) for v in per_run.values() if v]
    if not latencies:
        return {"latency_mean_s": float("nan"), "latency_median_s": float("nan"),
                "latency_p95_s": float("nan"), "runs_detected": 0.0}
    return {
        "latency_mean_s": float(np.mean(latencies)),
        "latency_median_s": float(np.median(latencies)),
        "latency_p95_s": float(np.percentile(latencies, 95)),
        "runs_detected": float(len(latencies)),
    }


# ──────────────────────────────────────────────────────────────────────────
#  Orchestration
# ──────────────────────────────────────────────────────────────────────────


def evaluate_models(
    models: Dict[str, object],
    anomaly,
    scaler,
    threshold: float,
    X_te: pd.DataFrame,
    Y_te: Dict[str, np.ndarray],
    meta_by_run: Optional[Dict[str, RunMeta]] = None,
) -> Dict[str, object]:
    metrics: Dict[str, object] = {}
    metrics.update(_anomaly_metrics(anomaly, scaler, threshold, X_te, Y_te))
    metrics.update(_classification_metrics(models["classifier"], X_te, Y_te))
    metrics.update(_regression_metrics(models["degradation"], X_te, Y_te, "severity"))
    metrics.update(_regression_metrics(models["rul"], X_te, Y_te, "rul_min", log_scale=True))

    if meta_by_run is not None:
        metrics.update(detection_latency(
            models["classifier"], anomaly, scaler, threshold, X_te, Y_te, meta_by_run
        ))

    # confusion matrix for the report
    pred = models["classifier"].predict(X_te.values)
    y = Y_te["class"]
    classes = sorted(set(y))
    cm = cm_fun(y, pred, labels=classes)
    metrics["_confusion"] = {"classes": classes, "matrix": cm.tolist()}
    return metrics


def write_report(metrics: Dict[str, object], model_dir: str) -> None:
    os.makedirs(model_dir, exist_ok=True)

    public = {k: v for k, v in metrics.items() if not k.startswith("_")}
    with open(f"{model_dir}/metrics.json", "w", encoding="utf-8") as fh:
        json.dump(public, fh, indent=2, sort_keys=True)

    # confusion matrix PNG (optional — needs matplotlib)
    png = None
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        cfg = metrics["_confusion"]
        fig, ax = plt.subplots(figsize=(8, 6))
        im = ax.imshow(cfg["matrix"], cmap="Blues")
        ax.set_xticks(range(len(cfg["classes"])), cfg["classes"], rotation=45, ha="right")
        ax.set_yticks(range(len(cfg["classes"])), cfg["classes"])
        ax.set_xlabel("predicted")
        ax.set_ylabel("actual")
        for i in range(len(cfg["classes"])):
            for j in range(len(cfg["classes"])):
                ax.text(j, i, cfg["matrix"][i][j], ha="center", va="center",
                        color="white" if cfg["matrix"][i][j] > np.asarray(cfg["matrix"]).max() / 2 else "black")
        fig.colorbar(im)
        fig.tight_layout()
        png = f"{model_dir}/confusion_matrix.png"
        fig.savefig(png, dpi=110)
        plt.close(fig)
    except ImportError:
        png = None
    if png:
        metrics["confusion_matrix_png"] = png

    with open(f"{model_dir}/report.md", "w", encoding="utf-8") as fh:
        fh.write("# AeroTwin ML pipeline — evaluation report (held-out test runs)\n\n")
        for k in sorted(public):
            v = public[k]
            if isinstance(v, dict):
                fh.write(f"## {k}\n")
                for kk in sorted(v):
                    fh.write(f"- {kk}: {v[kk]:.4f}\n" if isinstance(v[kk], float) else f"- {kk}: {v[kk]}\n")
            else:
                fh.write(f"- {k}: {v:.4f}\n" if isinstance(v, float) else f"- {k}: {v}\n")


def print_summary(metrics: Dict[str, object]) -> None:
    print("-" * 72)
    print("  evaluation summary (held-out test runs)")
    print("-" * 72)
    rows = [
        ("anomaly_roc_auc", "anomaly ROC-AUC"),
        ("anomaly_precision", "anomaly precision"),
        ("anomaly_recall", "anomaly recall"),
        ("anomaly_false_alarm_rate", "healthy false-alarm rate"),
        ("accuracy", "fault-class accuracy"),
        ("f1_macro", "fault-class F1 (macro)"),
        ("severity_mae", "degradation MAE (0-1)"),
        ("rul_min_mae", "RUL MAE (minutes)"),
        ("rul_within_20pct", "RUL within ±20%"),
        ("latency_median_s", "detection latency (median, s)"),
        ("runs_detected", "faulted test runs detected"),
    ]
    for key, label in rows:
        v = metrics.get(key)
        if v is not None and not (isinstance(v, float) and np.isnan(v)):
            print(f"  {label:<32} {v:>10.3f}")
    print("-" * 72)


def _p_or_r(y, pred, kind: str) -> float:
    tp = float(np.sum((pred == 1) & (y == 1)))
    if kind == "precision":
        denom = float(np.sum(pred == 1))
        return tp / denom if denom > 0 else 0.0
    denom = float(np.sum(y == 1))
    return tp / denom if denom > 0 else 0.0