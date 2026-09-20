"""
Telemetry schema for the synthetic generator.
=============================================

Defines the single source of truth for:

* CSV column names and their order (``CSV_COLUMNS``).
* Mission phases and fault types (``MissionPhase``, ``FaultType``).
* Physically plausible envelopes (``SENSOR_LIMITS``) used for validation.
* Per-sensor measurement noise (``SENSOR_NOISE_STD``).

Every module in :mod:`simulator.telemetry_gen` imports from here so the
generator, fault injection, tests and downstream consumers all agree on
naming and units.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Tuple

# ──────────────────────────────────────────────────────────────────────────
#  Engine geometry
# ──────────────────────────────────────────────────────────────────────────

NUM_CYLINDERS = 4

# Cylinder numbering convention used across the whole package.
CYLINDER_KEYS: Tuple[str, ...] = ("c1", "c2", "c3", "c4")

# ──────────────────────────────────────────────────────────────────────────
#  Mission phases
# ──────────────────────────────────────────────────────────────────────────


class MissionPhase(str, Enum):
    """Flight phases supported by the mission profile generator."""

    STARTUP = "STARTUP"
    TAKEOFF = "TAKEOFF"
    CLIMB = "CLIMB"
    CRUISE = "CRUISE"
    ENDURANCE = "ENDURANCE"
    DESCENT = "DESCENT"
    LANDING = "LANDING"


PHASE_ORDER: List[MissionPhase] = list(MissionPhase)

# ──────────────────────────────────────────────────────────────────────────
#  Fault types
# ──────────────────────────────────────────────────────────────────────────


class FaultType(str, Enum):
    """Supported fault modes for injection (ground-truth labels)."""

    INJECTOR_DEGRADATION = "INJECTOR_DEGRADATION"
    MISFIRE = "MISFIRE"
    LUBRICATION_FAILURE = "LUBRICATION_FAILURE"
    OVERHEATING = "OVERHEATING"
    SENSOR_DRIFT = "SENSOR_DRIFT"
    SENSOR_DROPOUT = "SENSOR_DROPOUT"
    ABNORMAL_VIBRATION = "ABNORMAL_VIBRATION"
    ALTERNATOR_DEGRADATION = "ALTERNATOR_DEGRADATION"


# ──────────────────────────────────────────────────────────────────────────
#  CSV columns
# ──────────────────────────────────────────────────────────────────────────

#: Exact CSV column order written by :func:`run_simulation.write_csv`.
CSV_COLUMNS: List[str] = [
    # meta
    "timestamp",            # ISO-8601 UTC, synthetic wall clock
    "sim_time_s",           # mission-relative seconds since start
    "phase",                # MissionPhase value
    # operating conditions
    "throttle",             # 0..1
    "altitude_ft",          # ft
    "ambient_temp_c",       # ISA ambient air temperature
    # engine sensors
    "rpm",                  # engine speed
    "fuel_flow_lph",        # litres / hour
    "cht_c1", "cht_c2", "cht_c3", "cht_c4",      # cylinder head temp °C
    "egt_c1", "egt_c2", "egt_c3", "egt_c4",      # exhaust gas temp °C
    "oil_pressure_kpa",     # kPa
    "oil_temp_c",           # °C
    "vibration_rms_g",      # g RMS
    "battery_v",            # volts
    "alternator_a",         # alternator output current, A
    "injection_timing_deg", # spark/injection advance, °BTDC
    # ground truth (labels)
    "faults_active",        # comma-joined fault names, "" when healthy
    "fault_severity",       # max active severity, 0.0 when healthy
]

# ──────────────────────────────────────────────────────────────────────────
#  Sensor limits (validation envelope)
# ──────────────────────────────────────────────────────────────────────────

#: (min, max) physically plausible envelope per numeric column. Rows outside
#: this envelope are counted as violations by ``validate_row`` — the
#: generator should never produce them for default profiles + supported faults.
SENSOR_LIMITS: Dict[str, Tuple[float, float]] = {
    "throttle": (0.0, 1.0),
    "altitude_ft": (0.0, 45000.0),
    "ambient_temp_c": (-70.0, 60.0),
    "rpm": (0.0, 6000.0),
    "fuel_flow_lph": (0.0, 25.0),
    "cht_c1": (-30.0, 350.0),
    "cht_c2": (-30.0, 350.0),
    "cht_c3": (-30.0, 350.0),
    "cht_c4": (-30.0, 350.0),
    "egt_c1": (-30.0, 900.0),
    "egt_c2": (-30.0, 900.0),
    "egt_c3": (-30.0, 900.0),
    "egt_c4": (-30.0, 900.0),
    "oil_pressure_kpa": (0.0, 650.0),
    "oil_temp_c": (-10.0, 150.0),
    "vibration_rms_g": (0.0, 8.0),
    "battery_v": (10.0, 16.0),
    "alternator_a": (0.0, 60.0),
    "injection_timing_deg": (0.0, 60.0),
    "fault_severity": (0.0, 1.0),
}

# ──────────────────────────────────────────────────────────────────────────
#  Sensor noise model (1σ per channel, applied on top of the clean signal)
# ──────────────────────────────────────────────────────────────────────────

SENSOR_NOISE_STD: Dict[str, float] = {
    "rpm": 12.0,                # rpm
    "fuel_flow_lph": 0.12,      # l/h
    "cht_c1": 1.6,              # °C
    "cht_c2": 1.6,
    "cht_c3": 1.6,
    "cht_c4": 1.6,
    "egt_c1": 5.0,              # °C
    "egt_c2": 5.0,
    "egt_c3": 5.0,
    "egt_c4": 5.0,
    "oil_pressure_kpa": 3.5,    # kPa
    "oil_temp_c": 0.4,          # °C
    "vibration_rms_g": 0.04,    # g
    "battery_v": 0.04,          # V
    "alternator_a": 0.7,        # A
    "injection_timing_deg": 0.35,  # °BTDC
}

#: Channels that may be targeted by SENSOR_DRIFT / SENSOR_DROPOUT.
DRIFTABLE_CHANNELS: List[str] = [
    "rpm",
    "fuel_flow_lph",
    "cht_c1", "cht_c2", "cht_c3", "cht_c4",
    "egt_c1", "egt_c2", "egt_c3", "egt_c4",
    "oil_pressure_kpa",
    "oil_temp_c",
    "vibration_rms_g",
    "battery_v",
    "alternator_a",
    "injection_timing_deg",
]

# ──────────────────────────────────────────────────────────────────────────
#  Validation helper
# ──────────────────────────────────────────────────────────────────────────


def validate_row(row: Dict[str, object]) -> List[str]:
    """
    Check one flat telemetry row against the physical envelope.

    Returns a list of human-readable violation messages (empty == OK).
    Non-numeric columns (timestamp, phase, faults_active) are skipped.
    """
    violations: List[str] = []
    for col, (lo, hi) in SENSOR_LIMITS.items():
        val = row.get(col)
        if not isinstance(val, (int, float)):
            continue
        if not (lo <= val <= hi):
            violations.append(
                f"{col}={val:.3f} outside [{lo}, {hi}]"
            )
    return violations


# ──────────────────────────────────────────────────────────────────────────
#  Frame type hint
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class TelemetryFrame:
    """Typed view of one flat telemetry row (engine_model output)."""

    sim_time_s: float = 0.0
    phase: str = MissionPhase.STARTUP.value
    throttle: float = 0.0
    altitude_ft: float = 0.0
    ambient_temp_c: float = 15.0
    rpm: float = 0.0
    fuel_flow_lph: float = 0.0
    cht_c: List[float] = field(default_factory=lambda: [15.0] * NUM_CYLINDERS)
    egt_c: List[float] = field(default_factory=lambda: [15.0] * NUM_CYLINDERS)
    oil_pressure_kpa: float = 0.0
    oil_temp_c: float = 15.0
    vibration_rms_g: float = 0.0
    battery_v: float = 12.5
    alternator_a: float = 0.0
    injection_timing_deg: float = 24.0
    faults_active: str = ""
    fault_severity: float = 0.0