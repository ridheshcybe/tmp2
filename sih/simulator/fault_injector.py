#!/usr/bin/env python3
"""
Fault Injector for Aero Piston Engine Digital Twin
--------------------------------------------------
Wraps :class:`AeroPistonEngine` and applies progressive mechanical
degradations and sensor anomalies.  Every frame returned by
:meth:`FaultInjector.step` carries a ``fault_labels`` dict giving
ground-truth anomaly state for AI/ML supervision.

Supported failure modes
-----------------------
LEAN_BURN_RUNAWAY   – Progressive lean-mixture drift → EGT spike + CHT climb
PISTON_RING_WEAR    – Compression loss → RPM drop, vibration ↑, oil temp ↑
OIL_LEAK_PRESSURE_LOSS – Oil pressure drop + friction-driven CHT rise
SENSOR_FREEZE       – One sensor locked to a static value

Usage
-----
    inj = FaultInjector(dt=0.1)
    inj.trigger_fault("PISTON_RING_WEAR", severity=0.05, rate_per_sec=0.01)
    for _ in range(600):          # 60 s at dt=0.1
        frame = inj.step(throttle=0.7)
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from simulator.engine_physics import (
    AeroPistonEngine,
    MAX_RPM,
    NUM_CYLINDERS,
)


# ══════════════════════════════════════════════════════════════════
#  Fault-type constants
# ══════════════════════════════════════════════════════════════════

class FaultType:
    LEAN_BURN_RUNAWAY = "LEAN_BURN_RUNAWAY"
    PISTON_RING_WEAR = "PISTON_RING_WEAR"
    OIL_LEAK_PRESSURE_LOSS = "OIL_LEAK_PRESSURE_LOSS"
    SENSOR_FREEZE = "SENSOR_FREEZE"

    ALL = {LEAN_BURN_RUNAWAY, PISTON_RING_WEAR, OIL_LEAK_PRESSURE_LOSS, SENSOR_FREEZE}


# ══════════════════════════════════════════════════════════════════
#  Internal fault state
# ══════════════════════════════════════════════════════════════════

class _FaultState:
    """Mutable accumulator for a single active fault."""

    __slots__ = (
        "fault_type", "severity", "rate_per_sec",
        "accumulated", "frozen_cyl", "frozen_value",
    )

    def __init__(
        self,
        fault_type: str,
        severity: float,
        rate_per_sec: float,
        frozen_cyl: int = 1,
        frozen_value: float = 0.0,
    ) -> None:
        self.fault_type = fault_type
        self.severity = severity          # 0.0 – 1.0  (peak intensity)
        self.rate_per_sec = rate_per_sec  # progression rate
        self.accumulated = 0.0            # cumulative fault progress [0, severity]
        self.frozen_cyl = frozen_cyl      # for SENSOR_FREEZE
        self.frozen_value = frozen_value  # for SENSOR_FREEZE


# ══════════════════════════════════════════════════════════════════
#  FaultInjector
# ══════════════════════════════════════════════════════════════════

class FaultInjector:
    """
    Transparent wrapper around :class:`AeroPistonEngine` that injects
    realistic fault dynamics.  The underlying engine is advanced first,
    then fault modifiers are applied to the output frame (and, where
    physically motivated, to the engine's internal state).

    Parameters
    ----------
    dt : float
        Simulation time-step [s].
    enable_noise : bool
        Forwarded to the inner engine.
    """

    def __init__(
        self,
        dt: float = 0.1,
        enable_noise: bool = True,
    ) -> None:
        self.engine = AeroPistonEngine(dt=dt, enable_noise=enable_noise)
        self.dt = dt
        self.active_faults: List[_FaultState] = []

    # ── Public API ─────────────────────────────────────────────

    def trigger_fault(
        self,
        fault_type: str,
        severity: float = 0.5,
        rate_per_sec: float = 0.01,
        frozen_cyl: int = 1,
    ) -> None:
        """
        Activate a fault.

        Parameters
        ----------
        fault_type : str
            One of FaultType.{LEAN_BURN_RUNAWAY, PISTON_RING_WEAR,
            OIL_LEAK_PRESSURE_LOSS, SENSOR_FREEZE}.
        severity : float
            Peak intensity of the fault (0.0 – 1.0).
        rate_per_sec : float
            How fast the fault progresses per simulated second.
        frozen_cyl : int
            Cylinder index (0-based) to freeze for SENSOR_FREEZE.
        """
        ft = fault_type.upper()
        if ft not in FaultType.ALL:
            raise ValueError(
                f"Unknown fault_type '{fault_type}'. "
                f"Valid: {FaultType.ALL}"
            )

        frozen_val = 0.0
        if ft == FaultType.SENSOR_FREEZE:
            # Snapshot current CHT so the frozen value is realistic
            frozen_val = self.engine.cht_c[frozen_cyl % NUM_CYLINDERS]

        fs = _FaultState(
            fault_type=ft,
            severity=min(max(severity, 0.0), 1.0),
            rate_per_sec=rate_per_sec,
            frozen_cyl=frozen_cyl % NUM_CYLINDERS,
            frozen_value=frozen_val,
        )
        self.active_faults.append(fs)

    def clear_faults(self) -> None:
        """Remove all active faults and reset accumulated damage."""
        self.active_faults.clear()

    @property
    def fault_types_active(self) -> List[str]:
        """List of currently active fault type strings."""
        return [f.fault_type for f in self.active_faults]

    # ── Step with fault injection ───────────────────────────────

    def step(
        self,
        throttle: float,
        altitude_ft: float = 0.0,
        weather: str = "CLEAR",
        timestamp: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Advance the engine by one dt, then apply all active faults.

        Returns
        -------
        dict
            Engine frame augmented with ``fault_labels`` dict:

            .. code-block:: python

                {
                    ...engine keys...,
                    "fault_labels": {
                        "LEAN_BURN_RUNAWAY": {"active": True, "progress": 0.35, ...},
                        "PISTON_RING_WEAR":  {"active": True, "progress": 0.12, ...},
                        "OIL_LEAK_PRESSURE_LOSS": {"active": False, ...},
                        "SENSOR_FREEZE":     {"active": False, ...},
                    },
                    "faults_active": ["LEAN_BURN_RUNAWAY", "PISTON_RING_WEAR"],
                }
        """
        dt = self.dt

        # ── 1. Advance the clean engine ──
        frame = self.engine.step(throttle, altitude_ft, weather, timestamp)

        # ── 2. Apply each active fault ──
        for fs in self.active_faults:
            # Progress the fault accumulator
            if fs.fault_type != FaultType.SENSOR_FREEZE:
                fs.accumulated = min(
                    fs.accumulated + fs.rate_per_sec * dt,
                    fs.severity,
                )
            progress_ratio = fs.accumulated / fs.severity if fs.severity > 0 else 1.0

            match fs.fault_type:
                # ──────────────────────────────────────────────
                case FaultType.LEAN_BURN_RUNAWAY:
                    self._apply_lean_burn(frame, fs, progress_ratio)

                case FaultType.PISTON_RING_WEAR:
                    self._apply_piston_ring_wear(frame, fs, progress_ratio)

                case FaultType.OIL_LEAK_PRESSURE_LOSS:
                    self._apply_oil_leak(frame, fs, progress_ratio)

                case FaultType.SENSOR_FREEZE:
                    self._apply_sensor_freeze(frame, fs)

        # ── 3. Build fault_labels dict ──
        all_types = [FaultType.LEAN_BURN_RUNAWAY, FaultType.PISTON_RING_WEAR,
                     FaultType.OIL_LEAK_PRESSURE_LOSS, FaultType.SENSOR_FREEZE]
        active_map = {f.fault_type: f for f in self.active_faults}

        fault_labels: Dict[str, Dict[str, Any]] = {}
        for ft_name in all_types:
            if ft_name in active_map:
                fs = active_map[ft_name]
                fault_labels[ft_name] = {
                    "active": True,
                    "severity": fs.severity,
                    "rate_per_sec": fs.rate_per_sec,
                    "progress": round(fs.accumulated, 6),
                    "progress_ratio": round(
                        fs.accumulated / fs.severity if fs.severity > 0 else 1.0, 4
                    ),
                }
            else:
                fault_labels[ft_name] = {
                    "active": False,
                    "severity": 0.0,
                    "rate_per_sec": 0.0,
                    "progress": 0.0,
                    "progress_ratio": 0.0,
                }

        frame["fault_labels"] = fault_labels
        frame["faults_active"] = self.fault_types_active

        return frame

    # ── Fault modifiers ─────────────────────────────────────────

    def _apply_lean_burn(
        self,
        frame: Dict[str, Any],
        fs: _FaultState,
        progress: float,
    ) -> None:
        """
        LEAN_BURN_RUNAWAY physics:
        - Equivalence ratio drops progressively (leaner mixture).
        - EGT spikes because lean burn has higher exhaust temps.
        - CHT climbs as the combustion shifts toward pre-ignition.
        - Fuel flow decreases (less fuel per cycle).
        """
        # ── Modify engine internals for physics coupling ──
        # Shift equivalence ratio leaner: typical cruise ~0.85 → drops toward ~0.55
        er_drop = 0.30 * progress * fs.severity
        self.engine.equivalence_ratio = max(
            self.engine.equivalence_ratio - er_drop, 0.45
        )

        # EGT spike: lean burn raises exhaust temps by up to +250°C
        egt_boost = 250.0 * progress * fs.severity
        frame["egt_c"] = [round(e + egt_boost, 2) for e in frame["egt_c"]]

        # CHT climb: lean condition increases combustion temperature
        cht_boost = 80.0 * progress * fs.severity
        frame["cht_c"] = [round(c + cht_boost, 2) for c in frame["cht_c"]]

        # Fuel flow reduction (leaner = less fuel)
        fuel_factor = 1.0 - 0.25 * progress * fs.severity
        frame["fuel_flow_lph"] = round(frame["fuel_flow_lph"] * fuel_factor, 3)

        # Vibrations increase slightly from detonation tendency
        vib_boost = 0.15 * progress * fs.severity
        frame["vibration_rms_g"] = round(
            frame["vibration_rms_g"] + vib_boost, 4
        )

    def _apply_piston_ring_wear(
        self,
        frame: Dict[str, Any],
        fs: _FaultState,
        progress: float,
    ) -> None:
        """
        PISTON_RING_WEAR physics:
        - Compression ratio drops → power loss → RPM drops.
        - Blow-by gases contaminate oil → oil temperature rises.
        - Vibration increases due to uneven combustion.
        - Fuel efficiency decreases (unburnt fuel).
        """
        # ── Modify engine internals ──
        # Compression loss: RPM reduced by up to 15% at full severity
        rpm_loss = 0.15 * progress * fs.severity
        self.engine.rpm *= (1.0 - rpm_loss * 0.05)  # gradual per-step nudge

        # Blow-by increases oil temperature (+30°C at full severity)
        oil_t_boost = 30.0 * progress * fs.severity
        self.engine.oil_temp_c += oil_t_boost * 0.01  # gradual

        # ── Modify frame ──
        frame["rpm"] = round(frame["rpm"] * (1.0 - rpm_loss), 1)

        # Vibration increases significantly (+40% at full severity)
        vib_factor = 1.0 + 0.40 * progress * fs.severity
        frame["vibration_rms_g"] = round(
            frame["vibration_rms_g"] * vib_factor, 4
        )

        # Oil temp elevated
        frame["oil_temp_c"] = round(
            frame["oil_temp_c"] + oil_t_boost, 2
        )

        # CHT rises slightly from poor combustion
        cht_boost = 15.0 * progress * fs.severity
        frame["cht_c"] = [round(c + cht_boost, 2) for c in frame["cht_c"]]

        # Fuel efficiency drops
        fuel_factor = 1.0 + 0.20 * progress * fs.severity
        frame["fuel_flow_lph"] = round(frame["fuel_flow_lph"] * fuel_factor, 3)

    def _apply_oil_leak(
        self,
        frame: Dict[str, Any],
        fs: _FaultState,
        progress: float,
    ) -> None:
        """
        OIL_LEAK_PRESSURE_LOSS physics:
        - Oil pressure drops steadily (leak path to sump/externally).
        - Reduced oil film → increased friction → CHT rises.
        - Oil temperature initially rises (less oil = less cooling).
        """
        # ── Modify engine internals ──
        # Oil pressure drops by up to 70% at full severity
        pressure_drop = 0.70 * progress * fs.severity
        self.engine.oil_pressure_kpa *= (1.0 - pressure_drop * 0.02)

        # ── Modify frame ──
        frame["oil_pressure_kpa"] = round(
            frame["oil_pressure_kpa"] * (1.0 - pressure_drop), 2
        )

        # CHT rises from friction (+50°C at full severity)
        cht_boost = 50.0 * progress * fs.severity
        frame["cht_c"] = [round(c + cht_boost, 2) for c in frame["cht_c"]]

        # Oil temperature rises (+20°C at full severity)
        oil_t_boost = 20.0 * progress * fs.severity
        frame["oil_temp_c"] = round(frame["oil_temp_c"] + oil_t_boost, 2)

        # Vibration increases from friction
        vib_boost = 0.10 * progress * fs.severity
        frame["vibration_rms_g"] = round(
            frame["vibration_rms_g"] + vib_boost, 4
        )

    def _apply_sensor_freeze(
        self,
        frame: Dict[str, Any],
        fs: _FaultState,
    ) -> None:
        """
        SENSOR_FREEZE: locks one cylinder's CHT reading to a static
        value (the snapshot taken at trigger time).
        """
        cyl_idx = fs.frozen_cyl
        if cyl_idx < len(frame["cht_c"]):
            frame["cht_c"][cyl_idx] = round(fs.frozen_value, 2)

        # Also flag the corresponding EGT as potentially stale
        # (some sensor boards share wiring — minor cross-talk)
        if cyl_idx < len(frame["egt_c"]):
            frame["egt_c"][cyl_idx] = round(
                fs.frozen_value + 450.0, 2  # approximate EGT offset
            )


# ══════════════════════════════════════════════════════════════════
#  Demo: Piston Ring Wear over 60 seconds
# ══════════════════════════════════════════════════════════════════

def _demo_piston_ring_wear() -> None:
    """Run a 60-second simulation with progressive piston ring wear."""
    inj = FaultInjector(dt=0.1, enable_noise=True)

    # Start engine at cruise, let it stabilise for 5 s
    for _ in range(50):
        inj.step(throttle=0.7, altitude_ft=0)

    # Trigger piston ring wear
    inj.trigger_fault(
        fault_type=FaultType.PISTON_RING_WEAR,
        severity=0.8,
        rate_per_sec=0.015,
    )

    print("\n  Piston Ring Wear Demo — 60 s @ throttle 0.7")
    print("  ─" * 40)

    header = (
        f"  {'t (s)':>6}  {'RPM':>7}  {'CHT₁°C':>7}  {'CHT₂°C':>7}  "
        f"{'Oil P kPa':>9}  {'Oil T°C':>7}  {'Vib g':>6}  "
        f"{'Progress':>8}"
    )
    print(header)
    print("  " + "─" * (len(header) - 2))

    for i in range(600):   # 60 s at dt=0.1
        frame = inj.step(throttle=0.7, altitude_ft=0)
        t = frame["sim_time_s"]

        # Print every second
        if i % 10 == 0:
            pr = frame["fault_labels"]["PISTON_RING_WEAR"]["progress"]
            print(
                f"  {t:>6.1f}  "
                f"{frame['rpm']:>7.0f}  "
                f"{frame['cht_c'][0]:>7.1f}  "
                f"{frame['cht_c'][1]:>7.1f}  "
                f"{frame['oil_pressure_kpa']:>9.1f}  "
                f"{frame['oil_temp_c']:>7.1f}  "
                f"{frame['vibration_rms_g']:>6.3f}  "
                f"{pr:>8.4f}"
            )

    print("  " + "─" * (len(header) - 2))
    print("  Demo complete.\n")


if __name__ == "__main__":
    _demo_piston_ring_wear()
