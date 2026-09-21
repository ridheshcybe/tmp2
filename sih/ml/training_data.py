"""
Labelled training-run generation.
=================================

Builds the dataset from :mod:`simulator.telemetry_gen`:

* healthy runs (several seeds),
* one run per fault type × severity level × seed, with the fault anchored in
  the CRUISE / ENDURANCE phases so every run has a healthy lead-in and a
  meaningful degradation window.

Durations are compressed (~17 min per run at 1 Hz) so a full dataset of
~20 runs trains in seconds on a laptop. Each run is returned with a
:class:`ml.labels.RunMeta` so splits happen at run level (no leakage).
"""

from __future__ import annotations

import copy
from typing import Dict, List, Optional, Tuple

from ml.labels import HEALTHY_LABEL, RunMeta
from simulator.telemetry_gen.fault_injection import FaultSpec
from simulator.telemetry_gen.mission_profiles import (
    MissionPhase,
    MissionProfile,
    build_mission_plan,
)
from simulator.telemetry_gen.run_simulation import simulate
from simulator.telemetry_gen.telemetry_schema import FaultType

#: Compressed mission (~17 min) for fast training runs.
TRAIN_DURATIONS: Dict[str, float] = {
    "STARTUP": 30.0,
    "TAKEOFF": 15.0,
    "CLIMB": 120.0,
    "CRUISE": 240.0,
    "ENDURANCE": 480.0,
    "DESCENT": 120.0,
    "LANDING": 30.0,
}

TRAIN_HZ = 1.0

#: Fault ramp length for a visible degradation window inside the run.
FAULT_RAMP_S = 180.0

#: Sensor targets for drift / dropout runs.
DEFAULT_DRIFT_CHANNEL = "egt_c2"
DEFAULT_DROP_CHANNEL = "egt_c1"


def _phase_anchor(profile: MissionProfile, phase: MissionPhase, offset: float) -> float:
    return profile.phase_start_s(phase) + offset


def build_fault_specs(
    fault_type: FaultType,
    severity: float,
    profile: MissionProfile,
    drift_channel: str = DEFAULT_DRIFT_CHANNEL,
    drop_channel: str = DEFAULT_DROP_CHANNEL,
) -> List[FaultSpec]:
    """
    Anchor a single fault mid-CRUISE so the run has a healthy lead-in, a
    ramp, and a developed-fault tail. Drift/dropout get a channel.
    """
    onset = _phase_anchor(profile, MissionPhase.CRUISE, 60.0)
    if fault_type in (FaultType.SENSOR_DRIFT, FaultType.SENSOR_DROPOUT):
        # drift needs a long window to become visible; dropout freeze near
        # the end keeps the mission mostly healthy
        if fault_type == FaultType.SENSOR_DRIFT:
            onset = _phase_anchor(profile, MissionPhase.CRUISE, 120.0)
            ramp = 0.0
        else:
            onset = _phase_anchor(profile, MissionPhase.ENDURANCE, 180.0)
            ramp = 0.0
        channel = drift_channel if fault_type == FaultType.SENSOR_DRIFT else drop_channel
        return [FaultSpec(fault_type, severity=severity, onset_s=onset, ramp_s=ramp, channel=channel)]
    return [FaultSpec(fault_type, severity=severity, onset_s=onset, ramp_s=FAULT_RAMP_S)]


def generate_run(
    fault_type: Optional[FaultType],
    severity: float,
    seed: int,
    run_id: str,
    hz: float = TRAIN_HZ,
    durations: Optional[Dict[str, float]] = None,
    drift_channel: str = DEFAULT_DRIFT_CHANNEL,
    drop_channel: str = DEFAULT_DROP_CHANNEL,
) -> Tuple[List[Dict[str, object]], RunMeta]:
    """
    Generate one labelled run.

    ``fault_type=None`` ⇒ healthy run. Returns ``(rows, meta)`` where rows
    are flat telemetry dicts (same keys as the CSV columns).
    """
    durations = durations or TRAIN_DURATIONS
    plan = build_mission_plan(durations)
    profile = MissionProfile(plan)

    faults: List[FaultSpec] = []
    if fault_type is not None:
        faults = build_fault_specs(fault_type, severity, profile, drift_channel, drop_channel)

    rows = simulate(hz=hz, seed=seed, phase_durations=durations, faults=faults)

    if fault_type is None:
        meta = RunMeta(
            run_id=run_id,
            fault_type=HEALTHY_LABEL,
            severity=0.0,
            onset_s=0.0,
            ramp_s=0.0,
            t_fail_s=0.0,
            mission_end_s=profile.total_duration_s,
        )
    else:
        spec = faults[0]
        meta = RunMeta(
            run_id=run_id,
            fault_type=fault_type.value,
            severity=severity,
            onset_s=spec.onset_s,
            ramp_s=spec.ramp_s,
            t_fail_s=spec.onset_s + spec.ramp_s,
            mission_end_s=profile.total_duration_s,
        )
    return rows, meta


#: Order of fault types in generated datasets (faulted runs first, healthy last).
TRAIN_FAULTS: List[Optional[FaultType]] = [
    FaultType.INJECTOR_DEGRADATION,
    FaultType.MISFIRE,
    FaultType.LUBRICATION_FAILURE,
    FaultType.OVERHEATING,
    FaultType.SENSOR_DRIFT,
    FaultType.SENSOR_DROPOUT,
    FaultType.ABNORMAL_VIBRATION,
    FaultType.ALTERNATOR_DEGRADATION,
    None,  # healthy
]


def generate_training_runs(
    runs_per_fault: int = 2,
    healthy_runs: int = 4,
    severity: float = 0.7,
    base_seed: int = 7,
    hz: float = TRAIN_HZ,
    durations: Optional[Dict[str, float]] = None,
) -> List[Tuple[List[Dict[str, object]], RunMeta]]:
    """
    Generate the full training set: ``runs_per_fault`` seeded runs per fault
    type + ``healthy_runs`` healthy runs. Returns ``(rows, meta)`` pairs.
    """
    out: List[Tuple[List[Dict[str, object]], RunMeta]] = []
    rid = 0
    for ft in TRAIN_FAULTS:
        n = healthy_runs if ft is None else runs_per_fault
        for i in range(n):
            seed = base_seed + rid
            run_id = f"{ft.value if ft else HEALTHY_LABEL.lower()}_s{seed}"
            rows, meta = generate_run(ft, severity, seed, run_id, hz=hz, durations=durations)
            out.append((rows, meta))
            rid += 1
    return out