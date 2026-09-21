"""
Ten test cases for the Engine Health Index.
===========================================

    python -m pytest ml/tests/test_health_index.py -q
"""

from __future__ import annotations

import numpy as np
import pytest

from ml.health_index import (
    CATEGORY_RANGES,
    CRITICALITY,
    DEFAULT_WEIGHTS,
    HealthIndexCalculator,
    alert_level,
    category,
    compute_ehi,
)
from ml.training_data import generate_run
from simulator.telemetry_gen.telemetry_schema import FaultType

SEED = 21


def _healthy_row() -> dict:
    rows, _ = generate_run(None, 0.0, seed=SEED, run_id="ehi_healthy")
    return rows[len(rows) // 2]


def _faulted_row(ft: FaultType) -> dict:
    rows, _ = generate_run(ft, 0.8, seed=SEED, run_id="ehi_f")
    # well after the fault is fully developed
    return rows[-60]


def _pred(cls: str = "HEALTHY", conf: float = 0.9, anomaly: float = 5.0,
          severity: float = 0.0) -> dict:
    return {
        "fault_class": cls,
        "confidence": conf,
        "anomaly_score": anomaly,
        "severity": severity,
        "is_anomaly": anomaly > 50.0,
    }


def _raw_score(calc: HealthIndexCalculator, row: dict, pred: dict) -> float:
    """Uns-moothed score on a fresh calculator (steady-state comparison)."""
    fresh = HealthIndexCalculator(healthy_stats=calc.stats)
    return fresh.update(row, pred)["raw"]


# ── 1. healthy steady state ────────────────────────────────────────────────


def test_1_healthy_engine_scores_high():
    calc = HealthIndexCalculator()
    row = _healthy_row()
    res = calc.update(row, _pred())
    assert res["ehi"] >= 85.0, res
    assert res["category"] == "NORMAL"
    assert res["alert_level"] in ("NONE", "WATCH")
    assert res["confidence"] in ("HIGH", "MEDIUM")


# ── 2. residual penalty ────────────────────────────────────────────────────


def test_2_extreme_egt_residual_deducts_about_25_points():
    calc = HealthIndexCalculator()
    healthy = _raw_score(calc, _healthy_row(), _pred())
    faulted = _raw_score(calc, _faulted_row(FaultType.INJECTOR_DEGRADATION), _pred())
    # residual weight 0.25 × penalty(≈1) ≈ 25 points
    assert healthy - faulted >= 15.0, (healthy, faulted)
    res = calc.update(_faulted_row(FaultType.INJECTOR_DEGRADATION), _pred())
    assert res["penalties"]["residual"] > 0.5


# ── 3. anomaly penalty ─────────────────────────────────────────────────────


def test_3_anomaly_score_deducts_about_20_points():
    calc = HealthIndexCalculator()
    base = _raw_score(calc, _healthy_row(), _pred())
    high = _raw_score(calc, _healthy_row(), _pred(anomaly=95.0))
    assert base - high >= 12.0  # anomaly weight 0.20 × ~1.0
    res = calc.update(_healthy_row(), _pred(anomaly=95.0))
    assert res["penalties"]["anomaly"] > 0.8


# ── 4. fault probability × criticality ────────────────────────────────────


def test_4_critical_fault_probability_weighs_more_than_minor():
    calc = HealthIndexCalculator()
    row = _healthy_row()
    minor = _raw_score(calc, row, _pred("SENSOR_DRIFT", conf=0.9))
    critical = _raw_score(calc, row, _pred("LUBRICATION_FAILURE", conf=0.9))
    assert critical < minor
    # 0.9 × criticality 1.0 ≈ 0.9 penalty vs 0.9 × 0.35 for drift — ~15 pt gap
    assert minor - critical >= 10.0
    res = calc.update(row, _pred("LUBRICATION_FAILURE", conf=0.9))
    assert res["penalties"]["fault"] > 0.8


# ── 5. degradation penalty ────────────────────────────────────────────────


def test_5_severity_one_deducts_about_20_points():
    calc = HealthIndexCalculator()
    base = _raw_score(calc, _healthy_row(), _pred())
    sev = _raw_score(calc, _healthy_row(), _pred(severity=1.0))
    assert base - sev >= 12.0
    res = calc.update(_healthy_row(), _pred(severity=1.0))
    assert res["penalties"]["degradation"] > 0.9


# ── 6. missing sensors → sensor penalty + stale gate ───────────────────────


def test_6_missing_sensors_penalised_and_stale_at_40_percent():
    calc = HealthIndexCalculator()
    row = _healthy_row()
    bad = {ch: True for ch in row if ch.startswith(("cht_", "egt_"))}
    for ch in bad:
        bad[ch] = False  # all 8 cylinder channels lost
    res = calc.update(row, _pred(), sensor_valid=bad)
    assert res["penalties"]["sensor"] > 0.4
    # half the sensors gone → data-quality gate caps the index at 50
    assert res["data_quality"]["stale"] is True
    assert res["ehi"] <= 50.0
    assert res["confidence"] == "LOW"


# ── 7. smoothing + rate limit ─────────────────────────────────────────────


def test_7_index_changes_gradually_never_jumps():
    calc = HealthIndexCalculator(max_step=15.0)
    healthy = _healthy_row()
    for _ in range(60):
        calc.update(healthy, _pred())
    ehi_before = calc._ehi
    res = calc.update(_faulted_row(FaultType.OVERHEATING),
                      _pred("OVERHEATING", conf=0.99, anomaly=99.0, severity=1.0))
    assert abs(res["ehi"] - ehi_before) <= 15.0 + 1e-9
    # after many more ticks it converges toward the bad score
    for _ in range(400):
        calc.update(_faulted_row(FaultType.OVERHEATING),
                    _pred("OVERHEATING", conf=0.99, anomaly=99.0, severity=1.0))
    assert calc._ehi < ehi_before - 30.0


# ── 8. missing model outputs → weight redistribution ──────────────────────


def test_8_missing_model_fields_redistribute_weights():
    calc = HealthIndexCalculator()
    row = _faulted_row(FaultType.INJECTOR_DEGRADATION)
    partial_pred = {"fault_class": "HEALTHY"}  # no anomaly/severity/confidence
    res = calc.update(row, partial_pred)
    assert res["weights_used"]["anomaly"] == 0.0
    # redistribution: residual weight 0.25 / (0.25+0.10) = 0.714
    assert res["weights_used"]["residual"] == pytest.approx(0.25 / 0.35, abs=0.001)
    assert "Models unavailable" in "\n".join(res["explanation"])
    assert res["confidence"] == "MEDIUM"


# ── 9. explanation readable by a maintenance engineer ──────────────────────


def test_9_explanation_is_plain_language():
    calc = HealthIndexCalculator()
    row = _faulted_row(FaultType.INJECTOR_DEGRADATION)
    res = calc.update(row, _pred("INJECTOR_DEGRADATION", conf=0.82, anomaly=70.0, severity=0.6))
    text = "\n".join(res["explanation"])
    assert "Health Index:" in text
    assert "Main contributors:" in text
    assert "INJECTOR_DEGRADATION probability 0.82" in text
    assert "σ" in text  # residual stated in physical units + sigma
    assert "Inspect" in text  # recommended action in plain words
    assert "degrees" in text.replace("°C", "degrees") or "°C" in text
    assert res["contributors"][0]["label"]  # top contributor has a human label


# ── 10. alert rules + category boundaries + monotonicity ──────────────────


def test_10_alert_rules_and_category_boundaries():
    assert category(95.0) == "NORMAL"
    assert category(85.0) == "NORMAL"
    assert category(84.9) == "WATCH"
    assert category(70.0) == "WATCH"
    assert category(69.9) == "WARNING"
    assert category(50.0) == "WARNING"
    assert category(49.9) == "CRITICAL"
    assert category(29.9) == "EMERGENCY"

    assert alert_level(95.0, {}, "HEALTHY") == "NONE"
    assert alert_level(80.0, {}, "HEALTHY") == "WATCH"
    assert alert_level(60.0, {}, "HEALTHY") == "ADVISORY"
    assert alert_level(45.0, {}, "HEALTHY") == "CRITICAL"
    assert alert_level(60.0, {"fault": 0.9}, "LUBRICATION_FAILURE") == "CRITICAL"

    # monotonicity: higher penalties ⇒ lower EHI, for random penalty vectors
    rng = np.random.default_rng(0)
    for _ in range(50):
        a = {k: float(v) for k, v in zip(DEFAULT_WEIGHTS, rng.random(len(DEFAULT_WEIGHTS)))}
        b = {k: v * 1.3 for k, v in a.items()}
        assert compute_ehi(a, DEFAULT_WEIGHTS) >= compute_ehi(b, DEFAULT_WEIGHTS)

    # saturation
    assert compute_ehi({k: 1.0 for k in DEFAULT_WEIGHTS}, DEFAULT_WEIGHTS) == 0.0
    assert compute_ehi({k: 0.0 for k in DEFAULT_WEIGHTS}, DEFAULT_WEIGHTS) == 100.0
    assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)