"""
Cadence-adaptive smoothing, rate limit and mission-reset tests.
===============================================================

The live API feeds the Health Index at 10 Hz while CSV replay feeds it at
1 Hz.  These tests pin down that the EMA time constant (τ ≈ 60 s) and the
rate limit (±15 points/s) behave the same at both cadences, that a single
update never moves the needle more than its per-tick allowance, and that
``reset()`` fully clears state at mission start.

    python -m pytest ml/tests/test_health_index_streaming.py -q
"""

from __future__ import annotations

from ml.health_index import HealthIndexCalculator
from ml.training_data import generate_run
from simulator.telemetry_gen.telemetry_schema import FaultType

SEED = 21

SEVERE = {
    "fault_class": "OVERHEATING",
    "confidence": 0.99,
    "anomaly_score": 99.0,
    "severity": 1.0,
    "is_anomaly": True,
}
HEALTHY = {
    "fault_class": "HEALTHY",
    "confidence": 0.9,
    "anomaly_score": 5.0,
    "severity": 0.0,
    "is_anomaly": False,
}


def _row(run_fault: FaultType, index: int = -60) -> dict:
    rows, _ = generate_run(run_fault, 0.8, seed=SEED, run_id="ehi_stream")
    return rows[index]


HEALTHY_ROW = _row(None, len(generate_run(None, 0.0, seed=SEED, run_id="ehi_s")[0]) // 2)
BAD_ROW = _row(FaultType.OVERHEATING)


def _run_cadence(calc: HealthIndexCalculator, dt: float, bad_at_s: float,
                 total_s: float) -> float:
    """Drive ``calc`` at ``dt`` s/tick; fault at ``bad_at_s``; return final EHI."""
    steps = int(total_s / dt)
    t = 0.0
    for _ in range(steps):
        row, pred = (BAD_ROW, SEVERE) if t >= bad_at_s else (HEALTHY_ROW, HEALTHY)
        res = calc.update(row, pred, t=t)
        t += dt
    return float(res["ehi"])


# ── 1. smoothing time constant is cadence-invariant ─────────────────────────

def test_1_smoothing_time_constant_is_cadence_invariant():
    at_1hz = _run_cadence(HealthIndexCalculator(), dt=1.0, bad_at_s=10.0, total_s=60.0)
    at_10hz = _run_cadence(HealthIndexCalculator(), dt=0.1, bad_at_s=10.0, total_s=60.0)
    # both approximate the same continuous EMA → nearly identical after 60 s
    assert abs(at_1hz - at_10hz) < 0.5, (at_1hz, at_10hz)
    # and both have reacted but not collapsed instantly (τ ≈ 60 s)
    raw_bad = HealthIndexCalculator().update(BAD_ROW, SEVERE)["raw"]
    assert at_1hz > raw_bad + 20.0, (at_1hz, raw_bad)


# ── 2. per-tick rate limit scales with cadence ──────────────────────────────

def test_2_rate_limit_scales_with_dt():
    fast = HealthIndexCalculator()          # 10 Hz → 1.5 points max per tick
    before_fast = fast.update(HEALTHY_ROW, HEALTHY, t=0.0)["ehi"]
    res_fast = fast.update(BAD_ROW, SEVERE, t=0.1)
    drop_fast = before_fast - res_fast["ehi"]
    assert drop_fast <= 1.5 + 1e-6, drop_fast

    slow = HealthIndexCalculator()          # 1 Hz → 15 points max per tick
    before_slow = slow.update(HEALTHY_ROW, HEALTHY, t=0.0)["ehi"]
    res_slow = slow.update(BAD_ROW, SEVERE, t=1.0)
    drop_slow = before_slow - res_slow["ehi"]
    assert drop_slow <= 15.0 + 1e-6, drop_slow
    assert drop_slow > drop_fast  # a full second of bad evidence hits harder


# ── 3. a data gap must not cause a jump ─────────────────────────────────────

def test_3_data_gap_does_not_jump():
    calc = HealthIndexCalculator()
    _run_cadence(calc, dt=1.0, bad_at_s=1e9, total_s=60.0)  # healthy so far (~99)
    before = float(calc._ehi)
    raw_bad = HealthIndexCalculator().update(BAD_ROW, SEVERE)["raw"]
    # a 540 s telemetry gap lands on a fully-developed fault
    res = calc.update(BAD_ROW, SEVERE, t=600.0)
    # one update may move at most max_step points — no instant collapse
    assert 0.0 < before - res["ehi"] <= 15.0 + 1e-6, (before, res["ehi"])
    assert res["ehi"] > raw_bad + 50.0  # EMA still holds most of the healthy score


# ── 4. mission reset clears history and restarts healthy ────────────────────

def test_4_reset_restores_fresh_healthy_start():
    calc = HealthIndexCalculator()
    _run_cadence(calc, dt=1.0, bad_at_s=0.0, total_s=120.0)
    assert calc._ehi is not None and calc._ehi < 70.0  # degraded state

    calc.reset()
    assert calc._ehi is None
    assert len(calc._history) == 0

    res = calc.update(HEALTHY_ROW, HEALTHY, t=0.0)
    # fresh-start score equals the raw healthy score of a brand-new calculator
    fresh = HealthIndexCalculator()
    assert res["ehi"] == fresh.update(HEALTHY_ROW, HEALTHY, t=0.0)["ehi"]
    assert res["category"] in ("NORMAL", "WATCH")
