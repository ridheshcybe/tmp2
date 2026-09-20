"""
AeroTwin Synthetic Telemetry Generator
======================================

A self-contained, deterministic synthetic telemetry generator for the Aero
Piston Engine digital twin prototype.

Pipeline::

    mission_profiles ──► engine_model ──► fault_injection ──► CSV + plots
    (throttle/alt)        (physics baseline)   (8 fault modes)

Everything is deterministic given a seed (``numpy.random.default_rng(seed)``
is the *only* source of randomness), so dataset generation is reproducible.

Modules
-------
telemetry_schema.py : enums, CSV column order, sensor limits, noise model.
engine_model.py     : physics-based healthy baseline (ISA atmosphere, 4-cyl
                      thermal model, oil/fuel/battery sub-models).
mission_profiles.py : STARTUP → LANDING mission plan with per-phase
                      throttle / altitude profiles.
fault_injection.py  : 8 fault modes with per-sensor, time-dependent effects.
run_simulation.py   : CLI entry point — mission → CSV (+ optional plots).

Example
-------
    python -m simulator.telemetry_gen.run_simulation --demo-faults --plot
"""

from simulator.telemetry_gen.engine_model import EngineModel
from simulator.telemetry_gen.fault_injection import FaultSpec, FaultInjector
from simulator.telemetry_gen.mission_profiles import (
    DEFAULT_PLAN,
    MissionPhase,
    MissionProfile,
    build_mission_plan,
)
from simulator.telemetry_gen.telemetry_schema import (
    CSV_COLUMNS,
    SENSOR_LIMITS,
    SENSOR_NOISE_STD,
    FaultType,
)

__all__ = [
    "EngineModel",
    "FaultSpec",
    "FaultInjector",
    "DEFAULT_PLAN",
    "MissionPhase",
    "MissionProfile",
    "build_mission_plan",
    "CSV_COLUMNS",
    "SENSOR_LIMITS",
    "SENSOR_NOISE_STD",
    "FaultType",
]