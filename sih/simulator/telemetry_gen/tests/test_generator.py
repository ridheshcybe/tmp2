"""
Tests for the synthetic telemetry generator.
============================================

Run from the repo root::

    python -m pytest simulator/telemetry_gen/tests -q
"""

from __future__ import annotations

import statistics

import pytest

from simulator.telemetry_gen.engine_model import EngineModel, isa_conditions
from simulator.telemetry_gen.fault_injection import FaultInjector, FaultSpec
from simulator.telemetry_gen.mission_profiles import (
    MissionPhase,
    MissionProfile,
    build_mission_plan,
)
from simulator.telemetry_gen.run_simulation import simulate
from simulator.telemetry_gen.telemetry_schema import (
    CSV_COLUMNS,
    PHASE_ORDER,
    FaultType,
    validate_row,
)

HZ = 1.0
SEED = 7


def healthy_rows() -> list:
    return simulate(hz=HZ, seed=SEED)


# ── determinism ────────────────────────────────────────────────────────────


def test_determinism_same_seed_identical():
    a = simulate(hz=HZ, seed=SEED)
    b = simulate(hz=HZ, seed=SEED)
    assert a == b


def test_different_seed_differs():
    a = simulate(hz=HZ, seed=SEED)
    b = simulate(hz=HZ, seed=SEED + 1)
    assert a != b


# ── mission structure ──────────────────────────────────────────────────────


def test_all_phases_present_in_order():
    plan = build_mission_plan()
    profile = MissionProfile(plan)
    seen = []
    for seg in plan:
        seen.append(seg.phase)
    assert seen == PHASE_ORDER


def test_row_count_matches_duration():
    rows = healthy_rows()
    plan = build_mission_plan()
    total = sum(seg.duration_s for seg in plan)
    assert len(rows) == round(total * HZ)


def test_phase_transition_matches_plan():
    rows = healthy_rows()
    plan = build_mission_plan()
    profile = MissionProfile(plan)
    t_expected = profile.phase_start_s(MissionPhase.CRUISE)
    # row just before CRUISE must be CLIMB, row at CRUISE start must be CRUISE
    row_before = min(rows, key=lambda r: abs(float(r["sim_time_s"]) - (t_expected - 0.5)))
    row_at = min(rows, key=lambda r: abs(float(r["sim_time_s"]) - t_expected))
    assert row_before["phase"] == MissionPhase.CLIMB.value
    assert row_at["phase"] == MissionPhase.CRUISE.value


# ── physical validity ──────────────────────────────────────────────────────


def test_healthy_rows_within_limits():
    rows = healthy_rows()
    violations = [msg for r in rows for msg in validate_row(r)]
    assert violations == [], f"violations: {violations[:5]}"


def test_cruise_steady_state_values():
    """Sanity-check physically plausible cruise numbers."""
    rows = healthy_rows()
    cruise = [r for r in rows if r["phase"] == MissionPhase.CRUISE.value]
    rpm = statistics.fmean(float(r["rpm"]) for r in cruise[600:])
    egt1 = statistics.fmean(float(r["egt_c1"]) for r in cruise[600:])
    cht1 = statistics.fmean(float(r["cht_c1"]) for r in cruise[600:])
    oil_p = statistics.fmean(float(r["oil_pressure_kpa"]) for r in cruise[600:])
    assert 3500 < rpm < 5000, rpm
    assert 600 < egt1 < 750, egt1
    assert 120 < cht1 < 200, cht1
    assert 300 < oil_p < 600, oil_p


def test_battery_charges_above_idle():
    rows = healthy_rows()
    cruise = [r for r in rows if r["phase"] == MissionPhase.CRUISE.value]
    assert statistics.fmean(float(r["battery_v"]) for r in cruise) > 14.0


def test_isa_altitude_cooling():
    _, temp0 = 15.0, None
    temp_sea = isa_conditions(0.0)["ambient_temp_c"]
    temp_18k = isa_conditions(18000.0)["ambient_temp_c"]
    assert abs(temp_sea - 15.0) < 1.0
    assert temp_18k < -15.0, temp_18k


# ── fault effects ──────────────────────────────────────────────────────────


def _fault_run(specs, window_start, window_end, healthy_col="egt_c1"):
    """Mean of a column over [start, end) for healthy vs faulted runs."""
    healthy = healthy_rows()
    faulted = simulate(hz=HZ, seed=SEED, faults=specs)

    def mean_over(rows, col):
        vals = [
            float(r[col]) for r in rows
            if window_start <= float(r["sim_time_s"]) < window_end
        ]
        return statistics.fmean(vals)

    return mean_over(healthy, healthy_col), mean_over(faulted, healthy_col)


def test_injector_degradation_raises_egt_on_target_cylinder():
    spec = FaultSpec(
        FaultType.INJECTOR_DEGRADATION, severity=0.6, onset_s=3000.0, ramp_s=0.0
    )
    # default cylinder for injector faults is c2
    h, f = _fault_run([spec], 3400.0, 3800.0, healthy_col="egt_c2")
    assert f > h + 50.0, f"healthy={h:.1f} faulted={f:.1f}"


def test_misfire_cools_target_cylinder_egt():
    spec = FaultSpec(FaultType.MISFIRE, severity=0.6, onset_s=3000.0, ramp_s=0.0)
    h, f = _fault_run([spec], 3200.0, 3600.0, healthy_col="egt_c2")
    assert f < h - 60.0, f"healthy={h:.1f} faulted={f:.1f}"


def test_lubrication_failure_drops_oil_pressure():
    spec = FaultSpec(
        FaultType.LUBRICATION_FAILURE, severity=0.6, onset_s=3000.0, ramp_s=600.0
    )
    h, f = _fault_run([spec], 3600.0, 3900.0, healthy_col="oil_pressure_kpa")
    assert f < h - 40.0, f"healthy={h:.1f} faulted={f:.1f}"


def test_alternator_degradation_drains_battery():
    spec = FaultSpec(
        FaultType.ALTERNATOR_DEGRADATION, severity=0.7, onset_s=3000.0, ramp_s=400.0
    )
    h, f = _fault_run([spec], 3500.0, 3900.0, healthy_col="battery_v")
    assert f < h - 0.5, f"healthy={h:.1f} faulted={f:.1f}"


def test_sensor_drift_raises_channel_gradually():
    # EGT drift rate = 90 °C/hr × severity 0.5 × ~0.29 hr elapsed (900–1200 s
    # after onset) ⇒ ~13 °C additive; assert clearly above noise and growing.
    spec = FaultSpec(
        FaultType.SENSOR_DRIFT, severity=0.5, onset_s=3000.0, ramp_s=0.0,
        channel="egt_c3",
    )
    h, f = _fault_run([spec], 3900.0, 4200.0, healthy_col="egt_c3")
    assert f > h + 8.0, f"healthy={h:.1f} faulted={f:.1f}"
    # drift must keep growing with time (linear drift)
    early = _fault_run([spec], 3300.0, 3600.0, healthy_col="egt_c3")[1]
    assert f > early + 3.0, f"early={early:.1f} late={f:.1f}"


def test_sensor_dropout_freezes_channel():
    spec = FaultSpec(
        FaultType.SENSOR_DROPOUT, severity=0.7, onset_s=3000.0, ramp_s=0.0,
        channel="egt_c1",
    )
    faulted = simulate(hz=HZ, seed=SEED, faults=[spec])
    window = [r for r in faulted if 4000.0 <= float(r["sim_time_s"]) < 4200.0]
    vals = {float(r["egt_c1"]) for r in window}
    assert len(vals) == 1, f"channel not frozen: {sorted(vals)[:5]}"


def test_abnormal_vibration_raises_rms():
    spec = FaultSpec(
        FaultType.ABNORMAL_VIBRATION, severity=0.6, onset_s=3000.0, ramp_s=300.0
    )
    h, f = _fault_run([spec], 3600.0, 3900.0, healthy_col="vibration_rms_g")
    assert f > h + 0.5, f"healthy={h:.1f} faulted={f:.1f}"


def test_fault_labels_written():
    spec = FaultSpec(
        FaultType.OVERHEATING, severity=0.5, onset_s=3000.0, ramp_s=300.0
    )
    faulted = simulate(hz=HZ, seed=SEED, faults=[spec])
    active = [r for r in faulted if float(r["sim_time_s"]) > 3400.0]
    assert all("OVERHEATING" in str(r["faults_active"]) for r in active)
    assert all(float(r["fault_severity"]) > 0.4 for r in active)
    before = [r for r in faulted if float(r["sim_time_s"]) < 2900.0]
    assert all(str(r["faults_active"]) == "" for r in before)


def test_csv_columns_present():
    rows = healthy_rows()
    assert set(CSV_COLUMNS).issubset(rows[0].keys())