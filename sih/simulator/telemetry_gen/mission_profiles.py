"""
Mission profile generator.
==========================

Defines the mission timeline as a sequence of phase segments, each with a
start/end throttle and altitude. Throttle and altitude ramp linearly inside a
segment, so transitions are smooth. Durations are configurable per phase,
which also lets the demo compress a long-endurance mission into a short run.

Default plan (~99 minutes at 1 Hz):

    STARTUP  (120 s,  idle)
    TAKEOFF  ( 60 s,  full-power roll)
    CLIMB    (900 s,  800 ft → 18,000 ft, high throttle)
    CRUISE   (1800 s, 18,000 ft)
    ENDURANCE(2400 s, 18,000 → 19,000 ft, loiter)
    DESCENT  (600 s,  19,000 → 1,500 ft)
    LANDING  ( 90 s,  flare to idle)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from simulator.telemetry_gen.telemetry_schema import MissionPhase, PHASE_ORDER


@dataclass(frozen=True)
class PhaseSegment:
    """One mission phase: linear throttle/altitude ramp over duration_s."""

    phase: MissionPhase
    duration_s: float
    throttle_start: float
    throttle_end: float
    altitude_start_ft: float
    altitude_end_ft: float

    def throttle_at(self, t_in_segment: float) -> float:
        if self.duration_s <= 0.0:
            return self.throttle_end
        frac = min(1.0, t_in_segment / self.duration_s)
        return self.throttle_start + (self.throttle_end - self.throttle_start) * frac

    def altitude_at(self, t_in_segment: float) -> float:
        if self.duration_s <= 0.0:
            return self.altitude_end_ft
        frac = min(1.0, t_in_segment / self.duration_s)
        return self.altitude_start_ft + (self.altitude_end_ft - self.altitude_start_ft) * frac


#: Default mission plan (seconds, throttle, altitude in ft).
DEFAULT_PLAN: List[PhaseSegment] = [
    PhaseSegment(MissionPhase.STARTUP, 120.0, 0.10, 0.12, 0.0, 0.0),
    PhaseSegment(MissionPhase.TAKEOFF, 60.0, 0.15, 0.95, 0.0, 800.0),
    PhaseSegment(MissionPhase.CLIMB, 900.0, 0.88, 0.85, 800.0, 18000.0),
    PhaseSegment(MissionPhase.CRUISE, 1800.0, 0.78, 0.78, 18000.0, 18000.0),
    PhaseSegment(MissionPhase.ENDURANCE, 2400.0, 0.68, 0.70, 18000.0, 19000.0),
    PhaseSegment(MissionPhase.DESCENT, 600.0, 0.30, 0.25, 19000.0, 1500.0),
    PhaseSegment(MissionPhase.LANDING, 90.0, 0.15, 0.06, 1500.0, 0.0),
]


def build_mission_plan(
    duration_overrides: Optional[Dict[str, float]] = None,
) -> List[PhaseSegment]:
    """
    Return the default plan with optional per-phase duration overrides,
    e.g. ``{"CRUISE": 3600.0, "ENDURANCE": 4800.0}``.
    """
    overrides = duration_overrides or {}
    plan: List[PhaseSegment] = []
    for seg in DEFAULT_PLAN:
        dur = overrides.get(seg.phase.value, seg.duration_s)
        plan.append(
            PhaseSegment(
                phase=seg.phase,
                duration_s=dur,
                throttle_start=seg.throttle_start,
                throttle_end=seg.throttle_end,
                altitude_start_ft=seg.altitude_start_ft,
                altitude_end_ft=seg.altitude_end_ft,
            )
        )
    return plan


class MissionProfile:
    """
    Interpolates the mission state at any simulation time.

    Usage::

        profile = MissionProfile(build_mission_plan())
        phase, throttle, altitude = profile.at(t_sim)
    """

    def __init__(self, plan: List[PhaseSegment]) -> None:
        if not plan:
            raise ValueError("mission plan must contain at least one segment")
        self.plan = plan
        self.phase_order = [seg.phase for seg in plan]

        # absolute start/end time per segment
        self._starts: List[float] = []
        t = 0.0
        for seg in plan:
            self._starts.append(t)
            t += seg.duration_s
        self.total_duration_s = t

    def at(self, t_sim: float) -> Tuple[MissionPhase, float, float]:
        """Return ``(phase, throttle, altitude_ft)`` at simulation time."""
        t = min(max(0.0, t_sim), self.total_duration_s - 1e-9)
        # linear scan — plan has ≤ 8 segments, fine at any sampling rate
        for i, seg in enumerate(self.plan):
            if t < self._starts[i] + seg.duration_s:
                t_in = t - self._starts[i]
                return (
                    seg.phase,
                    seg.throttle_at(t_in),
                    seg.altitude_at(t_in),
                )
        last = self.plan[-1]
        return (last.phase, last.throttle_end, last.altitude_end_ft)

    def phase_start_s(self, phase: MissionPhase) -> float:
        """Absolute start time of a phase (used to anchor fault onset)."""
        for seg, start in zip(self.plan, self._starts):
            if seg.phase == phase:
                return start
        raise KeyError(f"phase {phase} not in plan")

    # convenience -----------------------------------------------------------

    @property
    def all_phases_present(self) -> bool:
        return all(p in self.phase_order for p in PHASE_ORDER)