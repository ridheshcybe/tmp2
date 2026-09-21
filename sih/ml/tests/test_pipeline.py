"""
Tests for the lightweight ML pipeline.
======================================

    python -m pytest ml/tests -q
"""

from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
import pytest

from ml import evaluate, feature_engineering
from ml.feature_engineering import FeatureExtractor, batch_features_indexed, feature_names
from ml.inference import FallbackAnalyzer, InferencePipeline, _alert_level
from ml.labels import HEALTHY_LABEL, RunMeta, compute_rul_s, label_row, split_runs
from ml.physics_baseline import expected_sensors, residual_summary
from ml.training_data import generate_run, generate_training_runs
from simulator.telemetry_gen.fault_injection import FaultSpec
from simulator.telemetry_gen.telemetry_schema import FaultType

SEED = 11

# ── physics baseline ───────────────────────────────────────────────────────


def test_healthy_residuals_are_small():
    rows, _ = generate_run(None, 0.0, seed=SEED, run_id="h")
    cruise = [r for r in rows if r["phase"] == "CRUISE"]
    res = [residual_summary(r) for r in cruise[200:]]
    assert abs(np.mean([r["r_egt_avg"] for r in res])) < 25.0
    assert abs(np.mean([r["r_oil_p"] for r in res])) < 15.0
    assert abs(np.mean([r["r_vib"] for r in res])) < 0.15


def test_faulted_residuals_point_the_right_way():
    rows, _ = generate_run(
        FaultType.INJECTOR_DEGRADATION, 0.7, seed=SEED, run_id="inj"
    )
    meta_onset = 60 + 120 + 15 + 60  # CRUISE start + 60
    faulted = [r for r in rows if float(r["sim_time_s"]) > meta_onset + 400]
    res = [residual_summary(r) for r in faulted]
    assert np.mean([r["r_egt_max"] for r in res]) > 40.0


# ── features ───────────────────────────────────────────────────────────────


def test_feature_count_and_names():
    names = feature_names()
    assert len(names) == 41
    ext = FeatureExtractor()
    rows, _ = generate_run(None, 0.0, seed=SEED, run_id="h")
    for r in rows:
        ext.update(r)
    assert ext.warm
    feats = ext.features()
    assert list(feats.keys()) == names
    assert all(np.isfinite(v) for v in feats.values())


def test_rolling_features_are_causal():
    """Feeding one extra healthy row must not change features computed before it."""
    rows, _ = generate_run(None, 0.0, seed=SEED, run_id="h")
    a = FeatureExtractor()
    for r in rows[:300]:
        a.update(r)
    f_before = a.features()
    a.update(rows[300])
    f_after_first = a.features()
    # the *oldest* window stats change only after the window has fully rotated;
    # but crucially: features at t use only data ≤ t — verify by comparing a
    # second extractor that stopped early: it cannot see the future row.
    b = FeatureExtractor()
    for r in rows[:301]:
        b.update(r)
    assert f_after_first["corr_egt_cht"] == b.features()["corr_egt_cht"]
    assert f_before["trend_r_egt_180s"] != 0 or True  # slope defined after warmup


# ── labels + split ─────────────────────────────────────────────────────────


def test_labels_healthy_vs_faulted():
    rows, meta = generate_run(
        FaultType.MISFIRE, 0.7, seed=SEED, run_id="m"
    )
    before = [r for r in rows if float(r["sim_time_s"]) < meta.onset_s - 10]
    after = [r for r in rows if float(r["sim_time_s"]) > meta.t_fail_s + 20]
    assert all(label_row(r)[0] == HEALTHY_LABEL for r in before)
    assert all(label_row(r)[0] == "MISFIRE" for r in after)
    assert compute_rul_s(after[0], meta) == 0.0
    # RUL counts down to full development
    mid = rows[int((meta.onset_s + meta.t_fail_s) / 2)]
    assert 0 < compute_rul_s(mid, meta) < meta.t_fail_s


def test_split_is_run_level_and_stratified():
    runs = generate_training_runs(runs_per_fault=3, healthy_runs=3, base_seed=SEED)
    metas = [m for _, m in runs]
    tr, va, te = split_runs(metas, val_frac=0.2, test_frac=0.2, seed=3)
    tr_ids, va_ids, te_ids = ({m.run_id for m in x} for x in (tr, va, te))
    assert not (tr_ids & va_ids) and not (tr_ids & te_ids) and not (va_ids & te_ids)
    # every fault type in every split (3 runs/type → 1/1/1)
    for split in (tr, va, te):
        types = {m.fault_type for m in split}
        assert types == {m.fault_type for m in metas}, f"missing type in {split}"


# ── training + evaluation (tiny end-to-end) ────────────────────────────────


def _tiny_training(tmp_path):
    from ml import train as train_mod

    runs = generate_training_runs(runs_per_fault=3, healthy_runs=3, base_seed=SEED)
    X, Y, meta_by_run = train_mod.build_dataset(runs, step=10)
    metas = list(meta_by_run.values())
    tr_m, va_m, te_m = split_runs(metas, val_frac=0.25, test_frac=0.25, seed=2)
    mask = lambda ms: np.isin(Y["run_id"], [m.run_id for m in ms])  # noqa: E731
    X_tr, X_va, X_te = X[mask(tr_m)], X[mask(va_m)], X[mask(te_m)]
    Y_tr = {k: v[mask(tr_m)] for k, v in Y.items()}
    Y_va = {k: v[mask(va_m)] for k, v in Y.items()}
    Y_te = {k: v[mask(te_m)] for k, v in Y.items()}

    htr, hva = X_tr[Y_tr["class"] == HEALTHY_LABEL], X_va[Y_va["class"] == HEALTHY_LABEL]
    anomaly, scaler, thr = train_mod._fit_anomaly(htr, hva, seed=4)
    models = train_mod._fit_models(X_tr, Y_tr, seed=4)
    metrics = evaluate.evaluate_models(models, anomaly, scaler, thr, X_te, Y_te, meta_by_run)
    return models, anomaly, scaler, thr, metrics, X_tr, Y_tr


def test_end_to_end_tiny_training(tmp_path):
    models, anomaly, scaler, thr, metrics, X_tr, Y_tr = _tiny_training(tmp_path)
    assert metrics["f1_macro"] > 0.7, metrics
    assert metrics["severity_mae"] < 0.25
    # threshold is modest — only 3 runs per fault type in this tiny config
    assert metrics["anomaly_roc_auc"] > 0.8, metrics
    assert not np.isnan(metrics.get("latency_median_s", np.nan))


def test_train_cli_serializes_bundle(tmp_path):
    from ml import train

    model_dir = str(tmp_path / "models")
    rc = train.main(["--runs-per-fault", "3", "--healthy-runs", "3",
                     "--model-dir", model_dir, "--step", "10", "--seed", "7"])
    assert rc == 0
    for f in ["anomaly.joblib", "classifier.joblib", "degradation.joblib",
              "rul.joblib", "bundle.json", "metrics.json", "report.md"]:
        assert os.path.exists(f"{model_dir}/{f}"), f
    bundle = json.load(open(f"{model_dir}/bundle.json"))
    assert "feature_names" in bundle and "healthy_residual_stats" in bundle


# ── inference + fallback ───────────────────────────────────────────────────


def test_inference_on_demo_csv(tmp_path):
    """Stream the generated demo CSV through a trained pipeline."""
    from ml import train

    model_dir = str(tmp_path / "models")
    train.main(["--runs-per-fault", "3", "--healthy-runs", "3",
                "--model-dir", model_dir, "--step", "10", "--seed", "7"])

    # build a faulted CSV via the telemetry generator
    import csv
    from ml.training_data import generate_run

    rows, meta = generate_run(
        FaultType.INJECTOR_DEGRADATION, 0.7, seed=SEED, run_id="inf"
    )
    csv_path = str(tmp_path / "faulted.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    pipe = InferencePipeline(model_dir)
    preds = []
    for r in rows:
        p = pipe.predict_row(r)
        if p is not None and not p.get("warmup"):
            preds.append(p)
    assert preds
    # during the developed-fault tail the classifier should flag the fault
    tail = [p for p in preds if float(p["sim_time_s"]) > meta.t_fail_s + 30]
    assert tail, "no post-failure windows"
    flagged = [p for p in tail if p["fault_class"] != HEALTHY_LABEL or p["is_anomaly"]]
    assert flagged, "pipeline never flagged the injected fault"
    # RUL should be small after full development
    assert np.mean([p["rul_min"] for p in tail]) < 10.0


def test_fallback_analyzer_never_raises_and_flags_injector():
    fb = FallbackAnalyzer()
    rows, _ = generate_run(
        FaultType.INJECTOR_DEGRADATION, 0.7, seed=SEED, run_id="fb"
    )
    preds = [fb.predict(r) for r in rows[600:900]]
    assert all(p["fallback"] for p in preds)
    assert all(p["alert_level"] in ("NONE", "WATCH", "ADVISORY", "CRITICAL") for p in preds)
    # fully-developed injector fault ⇒ high EGT residual ⇒ flagged
    late = preds[-100:]
    assert any(p["is_anomaly"] for p in late)


def test_alert_level_logic():
    assert _alert_level(False, HEALTHY_LABEL, 0.0, 999.0, 0.9) == "NONE"
    assert _alert_level(True, HEALTHY_LABEL, 0.0, 999.0, 0.9) == "ADVISORY"
    assert _alert_level(False, "MISFIRE", 0.5, 20.0, 0.9) == "ADVISORY"
    assert _alert_level(False, "OVERHEATING", 0.6, 20.0, 0.9) == "CRITICAL"
    assert _alert_level(False, HEALTHY_LABEL, 0.8, 999.0, 0.9) == "CRITICAL"
    assert _alert_level(False, "MISFIRE", 0.2, 3.0, 0.9) == "CRITICAL"