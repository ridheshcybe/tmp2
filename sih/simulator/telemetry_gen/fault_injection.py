"""
Fault injection engine.
=======================

Implements 8 fault modes with *time-dependent*, per-sensor effects applied
on top of the healthy engine baseline. Each fault is defined by:

* ``onset_s``  — simulation time the fault becomes active.
* ``ramp_s``   — duration over which the fault severity ramps from 0 to the
                 configured severity (0 = sudden step).
* ``severity`` — 0..1 strength scaling of every effect.

Ground truth is written into the CSV row: ``faults_active`` (comma-joined
names) and ``fault_severity`` (max active severity). All randomness flows
through the injected RNG so runs are reproducible for a given seed.

Fault → sensor effect summary (details in ``README.md``):

+---------------------------+----------------------------------------------------+
| Fault                     | Affected sensors                                   |
+---------------------------+----------------------------------------------------+
| INJECTOR_DEGRADATION      | EGT/CHT cyl ↑ (lean), fuel flow ↓ + oscillates,    |
|                           | vibration ↑, injection advance ↓                    |
| MISFIRE                   | EGT/CHT cyl ↓ (cold), vibration ↑ periodic, RPM ↓, |
|                           | fuel flow ↑ (unburned)                              |
| LUBRICATION_FAILURE       | Oil pressure ↓ accelerating, oil temp ↑, CHT/EGT ↑ |
| OVERHEATING               | All CHT/EGT ↑, oil temp ↑, oil pressure ↓, RPM ↓   |
| SENSOR_DRIFT              | One channel drifts linearly (configurable rate)    |
| SENSOR_DROPOUT            | One channel freezes (stuck-at-last-value)          |
| ABNORMAL_VIBRATION        | Vibration ↑ with low-freq pulsing, CHT/EGT ripple  |
| ALTERNATOR_DEGRADATION    | Alternator current ↓, battery voltage decays       |
+---------------------------+----------------------------------------------------+
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from simulator.telemetry_gen.telemetry_schema import (
    DRIFTABLE_CHANNELS,
    NUM_CYLINDERS,
    FaultType,
)

# ──────────────────────────────────────────────────────────────────────────
#  Config
# ──────────────────────────────────────────────────────────────────────────

#: Default drift rates per channel family (units per hour at severity 1.0).
DRIFT_RATES: Dict[str, float] = {
    "rpm": 120.0,
    "fuel_flow_lph": 1.2,
    "cht": 40.0,                 # per cht_cX
    "egt": 90.0,                 # per egt_cX
    "oil_pressure_kpa": 25.0,
    "oil_temp_c": 8.0,
    "vibration_rms_g": 0.5,
    "battery_v": 0.4,
    "alternator_a": 4.0,
    "injection_timing_deg": 2.0,
}

#: Seconds a SENSOR_DROPOUT runs before the channel freezes (grace period).
DROPOUT_GRACE_S = 30.0


def _drift_rate(channel: str) -> float:
    if channel.startswith("cht_"):
        return DRIFT_RATES["cht"]
    if channel.startswith("egt_"):
        return DRIFT_RATES["egt"]
    return DRIFT_RATES.get(channel, 25.0)


# ──────────────────────────────────────────────────────────────────────────
#  Spec + state
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class FaultSpec:
    """One fault to inject. ``channel`` only used by drift/dropout."""

    fault_type: FaultType
    severity: float = 0.5
    onset_s: float = 0.0
    ramp_s: float = 0.0          # 0 = sudden
    channel: Optional[str] = None

    def __post_init__(self) -> None:
        if not (0.0 <= self.severity <= 1.0):
            raise ValueError(f"severity must be in [0, 1], got {self.severity}")
        if self.ramp_s < 0.0:
            raise ValueError("ramp_s must be >= 0")
        if self.fault_type in (FaultType.SENSOR_DRIFT, FaultType.SENSOR_DROPOUT):
            if self.channel is None:
                raise ValueError(
                    f"{self.fault_type.value} requires a target channel"
                )
            if self.channel not in DRIFTABLE_CHANNELS:
                raise ValueError(
                    f"channel '{self.channel}' is not driftable/droppable"
                )


class _FaultRuntime:
    """Per-fault runtime state (dropout freeze value, etc.)."""

    def __init__(self, spec: FaultSpec) -> None:
        self.spec = spec
        self._frozen = False
        self._last_value: Optional[float] = None

    def progress(self, t: float) -> float:
        """0 → 1 severity ramp progress at time t (1 for sudden faults)."""
        elapsed = t - self.spec.onset_s
        if elapsed < 0.0:
            return 0.0
        if self.spec.ramp_s <= 0.0:
            return 1.0
        return min(1.0, elapsed / self.spec.ramp_s)


class FaultInjector:
    """
    Applies active faults to healthy engine rows.

    Usage::

        injector = FaultInjector([FaultSpec(...), ...], seed=42)
        row = injector.apply(row, t_sim)          # mutates and returns row
    """

    def __init__(self, specs: List[FaultSpec], seed: int = 0) -> None:
        self.rng = np.random.default_rng(seed)
        self.specs = specs
        self.runtimes: List[_FaultRuntime] = [_FaultRuntime(s) for s in specs]

    # ──────────────────────────────────────────────────────────────────────
    #  Public API
    # ──────────────────────────────────────────────────────────────────────

    def apply(self, row: Dict[str, object], t: float) -> Dict[str, object]:
        """Mutate ``row`` with all active faults; return it with labels."""
        active_names: List[str] = []
        max_severity = 0.0

        for rt in self.runtimes:
            spec = rt.spec
            if t < spec.onset_s:
                continue
            p = rt.progress(t)
            if p <= 0.0:
                continue
            s = spec.severity * p
            self._apply_one(row, t, spec, s, rt)
            active_names.append(spec.fault_type.value)
            max_severity = max(max_severity, s)

        row["faults_active"] = ",".join(active_names)
        row["fault_severity"] = max_severity
        return row

    @property
    def active_fault_types(self) -> List[str]:
        return [s.fault_type.value for s in self.specs]

    # ──────────────────────────────────────────────────────────────────────
    #  Per-fault effect implementations
    # ──────────────────────────────────────────────────────────────────────

    def _apply_one(
        self,
        row: Dict[str, object],
        t: float,
        spec: FaultSpec,
        s: float,          # effective severity (severity × progress)
        rt: _FaultRuntime,
    ) -> None:
        ft = spec.fault_type
        rng = self.rng
        cyl = self._cyl(spec)

        if ft == FaultType.INJECTOR_DEGRADATION:
            # Lean + pulsing fuel delivery on one cylinder.
            pulse = math.sin(2.0 * math.pi * 0.35 * t)
            row["fuel_flow_lph"] -= s * 2.8 + s * 1.3 * pulse
            # a real injector never reports negative flow — floor at idle dribble
            row["fuel_flow_lph"] = max(0.3, float(row["fuel_flow_lph"]))
            row[f"egt_{cyl}"] += s * 120.0 + s * 25.0 * pulse
            row[f"cht_{cyl}"] += s * 22.0
            row["vibration_rms_g"] += s * 0.28
            row["injection_timing_deg"] -= s * 3.0

        elif ft == FaultType.MISFIRE:
            # Lost combustion on one cylinder: cold exhaust, rough idle,
            # wasted fuel, surging vibration.
            row[f"egt_{cyl}"] -= s * 150.0
            row[f"cht_{cyl}"] -= s * 35.0
            row["rpm"] -= s * 300.0
            row["fuel_flow_lph"] += s * 0.7
            row["vibration_rms_g"] += s * 0.9 + s * 0.4 * math.sin(
                2.0 * math.pi * 0.4 * t
            )
            for k in range(1, NUM_CYLINDERS + 1):
                other = f"c{k}"
                if other != cyl:
                    row[f"egt_{other}"] += s * 25.0

        elif ft == FaultType.LUBRICATION_FAILURE:
            # Oil pump/leak: pressure falls (accelerating), temp climbs,
            # friction raises CHT/EGT and roughens vibration.
            row["oil_pressure_kpa"] -= s * 120.0 * (s / spec.severity) ** 0.3
            row["oil_temp_c"] += s * 10.0
            for k in range(1, NUM_CYLINDERS + 1):
                row[f"cht_c{k}"] += s * 15.0
                row[f"egt_c{k}"] += s * 18.0
            row["vibration_rms_g"] += s * 0.35
            row["rpm"] -= s * 100.0

        elif ft == FaultType.OVERHEATING:
            # Cooling failure: all temps rise, thermal derate cuts RPM,
            # oil thins → pressure drops.
            for k in range(1, NUM_CYLINDERS + 1):
                row[f"cht_c{k}"] += s * 65.0
                row[f"egt_c{k}"] += s * 55.0
            row["oil_temp_c"] += s * 16.0
            row["oil_pressure_kpa"] -= s * 55.0
            row["rpm"] -= s * 380.0

        elif ft == FaultType.SENSOR_DRIFT:
            # Linear additive drift on one channel, units/hour.
            elapsed_hr = max(0.0, t - spec.onset_s) / 3600.0
            row[spec.channel] += s * _drift_rate(spec.channel) * elapsed_hr

        elif ft == FaultType.SENSOR_DROPOUT:
            # Stuck-at-last-value after a grace period.
            if not rt._frozen and (t - spec.onset_s) >= DROPOUT_GRACE_S:
                rt._frozen = True
                rt._last_value = float(row[spec.channel])
            if rt._frozen:
                row[spec.channel] = rt._last_value

        elif ft == FaultType.ABNORMAL_VIBRATION:
            # Mechanical imbalance / loose mount: vibration climbs with a
            # low-frequency pulsation and a small thermal ripple.
            row["vibration_rms_g"] += s * 1.5 + s * 0.35 * math.sin(
                2.0 * math.pi * 0.22 * t
            )
            for k in range(1, NUM_CYLINDERS + 1):
                row[f"egt_c{k}"] += s * 12.0
                row[f"cht_c{k}"] += s * 8.0

        elif ft == FaultType.ALTERNATOR_DEGRADATION:
            # Alternator output collapses; battery drains toward 12 V.
            row["alternator_a"] -= s * 20.0
            row["alternator_a"] = max(0.0, float(row["alternator_a"]))
            battery = float(row["battery_v"])
            row["battery_v"] = max(11.6, battery - s * 2.1)
            if float(row["rpm"]) < 1500.0:
                row["battery_v"] = min(float(row["battery_v"]), 12.4)

        else:  # pragma: no cover — guarded by enum
            raise ValueError(f"unhandled fault type: {ft}")

    @staticmethod
    def _cyl(spec: FaultSpec) -> str:
        """Target cylinder for cylinder-local faults (stable default c2)."""
        if spec.channel and spec.channel.startswith(("cht_", "egt_")):
            return spec.channel.split("_")[1]
        return "c2"