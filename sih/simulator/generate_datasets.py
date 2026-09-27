#!/usr/bin/env python3
"""
Aero Piston Engine — Dataset Generator
---------------------------------------
Runs the engine digital-twin simulation and exports two structured
CSVs to ``/data/``:

* ``flight_dataset_nominal.csv``  — 2-hour nominal mission profile
* ``flight_dataset_faults.csv``   — multiple 1-hour fault-injected runs

Usage
-----
    python -m simulator.generate_datasets          # generate both
    python -m simulator.generate_datasets nominal   # nominal only
    python -m simulator.generate_datasets faults    # faults only
"""

from __future__ import annotations

import os
import random
import sys
import time as _time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm

from simulator.engine_physics import AeroPistonEngine, NUM_CYLINDERS
from simulator.fault_injector import FaultInjector, FaultType


# ══════════════════════════════════════════════════════════════════
#  Configuration
# ══════════════════════════════════════════════════════════════════

DT = 0.1                           # simulation time-step [s]
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
NOMINAL_CSV = DATA_DIR / "flight_dataset_nominal.csv"
FAULTS_CSV = DATA_DIR / "flight_dataset_faults.csv"

# ── Nominal mission profile (total 7200 s = 2 hours) ──────────
# (start_s, end_s, throttle, alt_ft, phase_name)
NOMINAL_PHASES: List[Tuple[float, float, float, float, str]] = [
    (0,     300,   0.35,    0,      "TAXI_TAKEOFF"),      #  5 min
    (300,   1200,  0.82,    None,   "CLIMB"),              # 15 min (alt ramps)
    (1200,  6000,  0.65,    18000,  "CRUISE"),             # 80 min
    (6000,  6900,  0.40,    None,   "DESCENT"),            # 15 min (alt ramps)
    (6900,  7200,  0.25,    0,      "LANDING"),            #  5 min
]
NOMINAL_TOTAL_S = 7200

# ── Fault scenario configuration ──────────────────────────────
FAULT_RUNS = 12                       # number of 1-hour fault runs
FAULT_RUN_DURATION_S = 3600           # 1 hour per run
CRUISE_FAULT_WINDOW = (600, 3000)     # faults trigger between 10–50 min

# Fault parameters: (severity, rate_per_sec)
FAULT_PARAMS: Dict[str, Tuple[float, float]] = {
    FaultType.LEAN_BURN_RUNAWAY:        (0.75, 0.012),
    FaultType.PISTON_RING_WEAR:         (0.80, 0.015),
    FaultType.OIL_LEAK_PRESSURE_LOSS:   (0.85, 0.010),
    FaultType.SENSOR_FREEZE:            (1.00, 1.000),  # instant
}

# Critical thresholds for RUL calculation
CRITICAL_THRESHOLDS = {
    "egt_max_c":       900.0,    # EGT danger zone
    "cht_max_c":       270.0,    # CHT redline
    "oil_pressure_min_kpa": 150.0,
    "vibration_max_g": 1.8,
}

# Sensor columns that go into the CSV
SENSOR_COLS = [
    "rpm", "map_kpa", "fuel_flow_lph", "equivalence_ratio",
    "cht_1_c", "cht_2_c", "cht_3_c", "cht_4_c",
    "egt_1_c", "egt_2_c", "egt_3_c", "egt_4_c",
    "oil_pressure_kpa", "oil_temp_c", "vibration_rms_g",
    "air_density_kg_m3", "ambient_temp_c", "ambient_pressure_kpa",
]


# ══════════════════════════════════════════════════════════════════
#  Mission profile helpers
# ══════════════════════════════════════════════════════════════════

def _get_phase(t: float) -> Tuple[float, float, float, Optional[float], str]:
    """Return (throttle, altitude, phase_name) for sim time *t*."""
    for start, end, thr, alt, name in NOMINAL_PHASES:
        if start <= t < end:
            return thr, alt, name
    return NOMINAL_PHASES[-1][2], NOMINAL_PHASES[-1][3], NOMINAL_PHASES[-1][4]


def _interpolate_altitude(t: float) -> float:
    """Linearly interpolate altitude during climb / descent phases."""
    # Climb: 300–1200 s → 0–18000 ft
    if 300 <= t < 1200:
        frac = (t - 300) / 900.0
        return frac * 18_000.0
    # Descent: 6000–6900 s → 18000–0 ft
    if 6000 <= t < 6900:
        frac = (t - 6000) / 900.0
        return (1.0 - frac) * 18_000.0
    return None  # use phase constant


def _add_turbulence(base: float, t: float, amplitude: float = 0.02) -> float:
    """Add smooth turbulence variation to throttle / altitude."""
    turb = (
        amplitude * np.sin(2.1 * t)
        + 0.5 * amplitude * np.sin(5.7 * t)
        + 0.3 * amplitude * np.cos(13.3 * t)
    )
    return max(0.0, min(1.0, base + turb))


def _altitude_turbulence(alt: float, t: float) -> float:
    """Altitude turbulence: ±50 ft sinusoidal wobble."""
    wobble = (
        30.0 * np.sin(0.8 * t)
        + 15.0 * np.cos(2.3 * t)
        + 5.0 * np.sin(7.1 * t)
    )
    return max(0.0, alt + wobble)


# ══════════════════════════════════════════════════════════════════
#  Frame → flat row
# ══════════════════════════════════════════════════════════════════

def _frame_to_row(
    frame: Dict[str, Any],
    phase: str = "NOMINAL",
    is_anomaly: int = 0,
    fault_type: str = "NONE",
    rul_sec: float = -1.0,
) -> Dict[str, Any]:
    """Flatten a frame dict into a single-row dict for CSV export."""
    row: Dict[str, Any] = {
        "sim_time_s":       frame["sim_time_s"],
        "altitude_ft":      frame["altitude_ft"],
        "weather":          frame["weather"],
        "throttle":         frame["throttle"],
        "phase":            phase,
        # Sensors
        "rpm":              frame["rpm"],
        "map_kpa":          frame["map_kpa"],
        "fuel_flow_lph":    frame["fuel_flow_lph"],
        "equivalence_ratio": frame["equivalence_ratio"],
        "cht_1_c":          frame["cht_c"][0],
        "cht_2_c":          frame["cht_c"][1],
        "cht_3_c":          frame["cht_c"][2],
        "cht_4_c":          frame["cht_c"][3],
        "egt_1_c":          frame["egt_c"][0],
        "egt_2_c":          frame["egt_c"][1],
        "egt_3_c":          frame["egt_c"][2],
        "egt_4_c":          frame["egt_c"][3],
        "oil_pressure_kpa": frame["oil_pressure_kpa"],
        "oil_temp_c":       frame["oil_temp_c"],
        "vibration_rms_g":  frame["vibration_rms_g"],
        "air_density_kg_m3": frame["air_density_kg_m3"],
        "ambient_temp_c":   frame["ambient_temp_c"],
        "ambient_pressure_kpa": frame["ambient_pressure_kpa"],
    }
    # Fault metadata
    row["is_anomaly"] = is_anomaly
    row["fault_type"] = fault_type
    row["remaining_useful_life_sec"] = rul_sec
    return row


# ══════════════════════════════════════════════════════════════════
#  RUL estimation
# ══════════════════════════════════════════════════════════════════

def _is_critical(row: Dict[str, Any]) -> bool:
    """Check if a row has crossed any critical threshold."""
    if row.get("egt_1_c", 0) > CRITICAL_THRESHOLDS["egt_max_c"]:
        return True
    if any(
        row.get(f"cht_{i}_c", 0) > CRITICAL_THRESHOLDS["cht_max_c"]
        for i in range(1, NUM_CYLINDERS + 1)
    ):
        return True
    if row.get("oil_pressure_kpa", 999) < CRITICAL_THRESHOLDS["oil_pressure_min_kpa"]:
        return True
    if row.get("vibration_rms_g", 0) > CRITICAL_THRESHOLDS["vibration_max_g"]:
        return True
    return False


def _compute_rul(rows: List[Dict[str, Any]]) -> None:
    """
    Post-hoc RUL computation: scan backward from end to find the
    first critical point, then fill remaining_useful_life_sec
    with the time distance from each row to that point.

    Modifies rows in-place.
    """
    total = len(rows)
    critical_idx = total  # default: never fails

    for i in range(total - 1, -1, -1):
        if _is_critical(rows[i]):
            critical_idx = i
            break

    for i, row in enumerate(rows):
        steps_to_critical = max(critical_idx - i, 0)
        row["remaining_useful_life_sec"] = round(steps_to_critical * DT, 1)


# ══════════════════════════════════════════════════════════════════
#  Dataset 1: Nominal mission
# ══════════════════════════════════════════════════════════════════

def generate_nominal() -> pd.DataFrame:
    """Simulate a 2-hour nominal mission and return a DataFrame."""
    total_steps = int(NOMINAL_TOTAL_S / DT)
    engine = AeroPistonEngine(dt=DT, enable_noise=True)
    rows: List[Dict[str, Any]] = []

    for i in tqdm(range(total_steps), desc="  Nominal mission", ncols=80):
        t = i * DT
        thr_base, alt_fixed, phase = _get_phase(t)

        # Altitude interpolation for climb / descent
        if alt_fixed is None:
            alt = _altitude_turbulence(_interpolate_altitude(t), t)
        else:
            alt = _altitude_turbulence(alt_fixed, t)

        # Add throttle turbulence
        thr = _add_turbulence(thr_base, t, amplitude=0.015)

        frame = engine.step(throttle=thr, altitude_ft=alt)
        row = _frame_to_row(frame, phase=phase, is_anomaly=0, fault_type="NONE")
        rows.append(row)

    # Compute nominal RUL (should be large / infinite for healthy engine)
    for row in rows:
        row["remaining_useful_life_sec"] = -1.0  # undefined for nominal

    df = pd.DataFrame(rows)
    return df


# ══════════════════════════════════════════════════════════════════
#  Dataset 2: Fault-injected runs
# ══════════════════════════════════════════════════════════════════

def _run_fault_scenario(
    fault_type: str,
    fault_trigger_s: float,
    severity: float,
    rate_per_sec: float,
    run_id: int,
) -> List[Dict[str, Any]]:
    """Run a single 1-hour scenario with a fault triggered mid-cruise."""
    total_steps = int(FAULT_RUN_DURATION_S / DT)
    inj = FaultInjector(dt=DT, enable_noise=True)

    # Pre-trigger: cruise at 18,000 ft, throttle 0.65
    trigger_step = int(fault_trigger_s / DT)
    rows: List[Dict[str, Any]] = []
    fault_triggered = False

    for i in range(total_steps):
        t = i * DT

        # Cruise altitude with turbulence
        alt = _altitude_turbulence(18_000.0, t)
        thr = _add_turbulence(0.65, t, amplitude=0.012)

        # Trigger fault at the designated time
        if not fault_triggered and i >= trigger_step:
            inj.trigger_fault(fault_type, severity, rate_per_sec)
            fault_triggered = True

        frame = inj.step(throttle=thr, altitude_ft=alt)

        is_anomaly = 1 if fault_triggered else 0
        ft_label = fault_type if fault_triggered else "NONE"
        row = _frame_to_row(frame, phase="CRUISE", is_anomaly=is_anomaly, fault_type=ft_label)
        row["run_id"] = run_id
        row["fault_trigger_s"] = round(fault_trigger_s, 1)
        rows.append(row)

    # Compute RUL for this run
    _compute_rul(rows)

    return rows


def generate_faults() -> pd.DataFrame:
    """Generate multiple 1-hour fault-injected runs."""
    all_rows: List[Dict[str, Any]] = []

    fault_types = list(FAULT_PARAMS.keys())

    for run_id in tqdm(range(FAULT_RUNS), desc="  Fault scenarios", ncols=80):
        # Pick a random fault type
        ft = fault_types[run_id % len(fault_types)]
        severity, rate = FAULT_PARAMS[ft]

        # Random trigger time within cruise window
        trigger_s = random.uniform(*CRUISE_FAULT_WINDOW)

        rows = _run_fault_scenario(ft, trigger_s, severity, rate, run_id)
        all_rows.extend(rows)

    df = pd.DataFrame(all_rows)
    return df


# ══════════════════════════════════════════════════════════════════
#  Summary statistics
# ══════════════════════════════════════════════════════════════════

def _print_summary(df: pd.DataFrame, name: str) -> None:
    """Print dataset summary statistics."""
    print(f"\n  {'═' * 60}")
    print(f"  {name}")
    print(f"  {'═' * 60}")
    print(f"  Rows:              {len(df):,}")
    print(f"  Columns:           {len(df.columns)}")
    print(f"  Memory usage:      {df.memory_usage(deep=True).sum() / 1024**2:.2f} MB")
    print(f"  Duration covered:  {df['sim_time_s'].max():.0f} s")
    print()

    # Feature distributions for key sensors
    key_features = ["rpm", "cht_1_c", "egt_1_c", "oil_pressure_kpa", "vibration_rms_g"]
    present = [c for c in key_features if c in df.columns]
    if present:
        print("  Feature distributions:")
        print("  " + "-" * 56)
        stats = df[present].describe().T[["mean", "std", "min", "max"]]
        stats.columns = ["Mean", "Std", "Min", "Max"]
        print(stats.to_string(header=True, float_format="{:>10.2f}".format))
        print("  " + "-" * 56)

    # Fault distribution (faults dataset only)
    if "fault_type" in df.columns:
        print("\n  Fault distribution:")
        print("  " + "-" * 56)
        vc = df["fault_type"].value_counts()
        for ft_name, count in vc.items():
            pct = 100.0 * count / len(df)
            print(f"  {ft_name:<30s}  {count:>8,}  ({pct:>5.1f}%)")
        print("  " + "-" * 56)

    if "is_anomaly" in df.columns:
        n_anom = df["is_anomaly"].sum()
        print(f"\n  Anomaly ratio:  {n_anom:,} / {len(df):,}  ({100*n_anom/len(df):.1f}%)")

    if "remaining_useful_life_sec" in df.columns:
        rul_valid = df[df["remaining_useful_life_sec"] >= 0]["remaining_useful_life_sec"]
        if len(rul_valid) > 0:
            print(f"  RUL range:      {rul_valid.min():.0f} – {rul_valid.max():.0f} s")

    print(f"\n  {'═' * 60}\n")


# ══════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════

def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    target = sys.argv[1].lower() if len(sys.argv) > 1 else "all"

    print("\n  Aero Piston Engine Digital Twin — Dataset Generator")
    print("  " + "=" * 50)

    if target in ("all", "nominal"):
        t0 = _time.time()
        df_nominal = generate_nominal()
        elapsed = _time.time() - t0
        df_nominal.to_csv(NOMINAL_CSV, index=False)
        print(f"  Saved: {NOMINAL_CSV}  ({elapsed:.1f}s)")
        _print_summary(df_nominal, "Nominal Mission Profile (2 h)")

    if target in ("all", "faults"):
        t0 = _time.time()
        df_faults = generate_faults()
        elapsed = _time.time() - t0
        df_faults.to_csv(FAULTS_CSV, index=False)
        print(f"  Saved: {FAULTS_CSV}  ({elapsed:.1f}s)")
        _print_summary(df_faults, "Fault-Injected Scenarios (12 × 1 h)")

    print("  Done.\n")


if __name__ == "__main__":
    main()
