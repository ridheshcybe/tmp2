#!/usr/bin/env python3
"""
4-Cylinder Aero Piston Engine Physics Model
--------------------------------------------
Real-time digital-twin simulation of a naturally-aspirated,
fuel-injected 4-cylinder aircraft engine (e.g. Rotax 912 / Lycoming
O-320 class, ~150 HP).

Integrates with :class:`simulator.environment_model.AtmosphereModel`
to couple engine performance to flight altitude and weather.

State is advanced per time-step (dt = 0.1 s default) via :meth:`step`.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from simulator.environment_model import AtmosphereModel


# ══════════════════════════════════════════════════════════════════
#  Engine physical constants (Lycoming O-320 / Rotax 912 class)
# ══════════════════════════════════════════════════════════════════

# Mechanical
NUM_CYLINDERS = 4
DISPLACEMENT_L = 3.2          # total swept volume [litres]
BORE_MM = 120.0
STROKE_MM = 140.0
MAX_RPM = 2_700               # redline
IDLE_RPM = 600
RPMGovernor_TARGET = 2_400    # typical cruise RPM set-point

# Thermal
CYLINDER_THERMAL_MASS = 0.35  # effective thermal capacitance [kJ/°C]
COMBUSTION_HEAT_PER_REV = 6.8  # heat to cylinder head per power stroke [kJ]
HEAT_TRANSFER_COEFF = 0.12   # convective cooling coeff  [kJ/(s·°C·ΔT)]
OIL_HEAT_CAPACITY = 8.0      # oil sump thermal inertia [kJ/°C]
OIL_COOLING_COEFF = 0.05     # oil-to-ambient heat rejection [kJ/(s·°C)]

# Fuel
BSFC_KG_PER_KWH = 0.28       # brake-specific fuel consumption [kg/(kW·h)]
FUEL_DENSITY_KG_PER_L = 0.72  # Avgas 100LL density
STOICH_AFR = 14.7            # stoichiometric air-fuel ratio
LHV_FUEL = 43_500            # lower heating value of Avgas [kJ/kg]

# Pressure / intake
THROTTLE_VENTURI_RATIO = 0.35  # pressure drop at WOT through venturi

# Vibration
VIB_BASELINE_G = 0.15        # mechanical vibration at idle [RMS g]
VIB_RPM_COEFF = 3.5e-5       # vibration scaling factor [g/RPM²]

# Sensor noise standard deviations
NOISE_RPM_SD = 15.0
NOISE_MAP_SD = 0.12
NOISE_FUEL_SD = 0.08
NOISE_CHT_SD = 0.8           # °C
NOISE_EGT_SD = 1.2           # °C
NOISE_OIL_P_SD = 0.6
NOISE_OIL_T_SD = 0.3
NOISE_VIB_SD = 0.005


# ══════════════════════════════════════════════════════════════════
#  CHT initialisation (slight cylinder-to-cylinder spread)
# ══════════════════════════════════════════════════════════════════

_CHT_OFFSETS = [0.0, -1.2, 0.8, -0.5]   # manufacturing variance [°C]


# ══════════════════════════════════════════════════════════════════
#  Engine state
# ══════════════════════════════════════════════════════════════════

class AeroPistonEngine:
    """
    High-fidelity 4-cylinder aero piston engine digital twin.

    Parameters
    ----------
    dt : float
        Simulation time-step in seconds (default 0.1 s).
    ambient_pressure_kpa : float
        Ambient atmospheric pressure [kPa].  Typically obtained from
        :class:`AtmosphereModel`.
    ambient_temp_c : float
        Ambient (intake) air temperature [°C].
    air_density : float
        Ambient air density [kg/m³].
    enable_noise : bool
        If *True* (default), Gaussian sensor noise is applied.
    """

    def __init__(
        self,
        dt: float = 0.1,
        ambient_pressure_kpa: float = 101.325,
        ambient_temp_c: float = 15.0,
        air_density: float = 1.225,
        enable_noise: bool = True,
    ) -> None:
        self.dt = dt
        self.enable_noise = enable_noise

        # ── Atmospheric inputs ──
        self.ambient_pressure_kpa = ambient_pressure_kpa
        self.ambient_temp_c = ambient_temp_c
        self.air_density = air_density
        self.density_ratio = air_density / 1.225

        # ── Mutable state ──
        self.rpm = float(IDLE_RPM)
        self.throttle = 0.0           # 0.0 – 1.0
        self.egt_c = [650.0] * NUM_CYLINDERS
        self.cht_c = [120.0 + off for off in _CHT_OFFSETS]
        self.oil_pressure_kpa = 380.0
        self.oil_temp_c = 80.0
        self.fuel_flow_lph = 0.0
        self.vibration_rms_g = VIB_BASELINE_G
        self.equivalence_ratio = 0.85  # lean cruise by default

        # Cumulative simulation time
        self.sim_time = 0.0

    # ── Atmosphere helper ───────────────────────────────────────

    def set_atmosphere(self, atm: AtmosphereModel) -> None:
        """Convenience: pull all atmosphere fields from an
        :class:`AtmosphereModel` instance."""
        s = atm.compute()
        self.ambient_pressure_kpa = s["ambient_pressure_kpa"]
        self.ambient_temp_c = s["ambient_temp_c"]
        self.air_density = s["air_density_kg_m3"]
        self.density_ratio = s["density_ratio"]

    # ── RPM dynamics ────────────────────────────────────────────

    def _target_rpm(self) -> float:
        """
        Desired RPM from throttle position, scaled by air density.

        At full throttle the engine reaches MAX_RPM; at idle it sits
        at IDLE_RPM.  Air-density ratio modulates the available
        torque (proportional to ρ/ρ₀).
        """
        base = IDLE_RPM + (MAX_RPM - IDLE_RPM) * self.throttle
        return base * max(self.density_ratio, 0.3)

    def _update_rpm(self) -> None:
        """
        First-order lag toward target RPM.  Time constant is shorter
        on acceleration (fuel available) than on deceleration (engine
        braking + propeller drag).
        """
        target = self._target_rpm()
        tau_up = 1.8      # accel time-constant [s]
        tau_dn = 3.0      # decel time-constant [s]
        tau = tau_up if target > self.rpm else tau_dn
        alpha = 1.0 - math.exp(-self.dt / tau)
        self.rpm += alpha * (target - self.rpm)

    # ── Manifold Absolute Pressure ──────────────────────────────

    def _update_map(self) -> None:
        """
        MAP modelled as a linear interpolation between ambient
        pressure (throttle open) and a partial-vacuum floor
        (throttle closed), scaled by venturi geometry.
        """
        p_vacuum = self.ambient_pressure_kpa * (1.0 - THROTTLE_VENTURI_RATIO)
        self.map_kpa = (
            p_vacuum
            + (self.ambient_pressure_kpa - p_vacuum) * self.throttle
        )

    # ── Power & fuel flow ───────────────────────────────────────

    def _update_fuel_flow(self) -> None:
        """
        BSFC-based fuel flow.

        Power ≈ bmep × displacement × RPM / (60 × n_strokes)
        For a 4-stroke: n_strokes = 2.
        bmep (brake mean effective pressure) is approximated from
        MAP and volumetric efficiency.
        """
        vol_eff = 0.82 + 0.08 * self.throttle   # 0.82 – 0.90
        bmep = self.map_kpa * vol_eff * 0.80     # kPa (approx)
        displacement_m3 = DISPLACEMENT_L * 1e-3
        # Brake power [kW] for a 4-stroke engine
        power_kw = (bmep * displacement_m3 * self.rpm) / (60.0 * 2.0)
        power_kw = max(power_kw, 0.0)

        # Fuel mass flow [kg/s]
        fuel_kg_s = power_kw * BSFC_KG_PER_KWH / 3600.0
        # Convert to L/hr
        self.fuel_flow_lph = (fuel_kg_s * 3600.0) / FUEL_DENSITY_KG_PER_L

        # Equivalence ratio (λ⁻¹) — richer at high throttle
        if power_kw > 0:
            afr = STOICH_AFR * (1.2 - 0.35 * self.throttle)
            self.equivalence_ratio = STOICH_AFR / max(afr, 8.0)
        else:
            self.equivalence_ratio = 0.0

    # ── CHT (4-cylinder, Newton's cooling) ──────────────────────

    def _update_cht(self) -> None:
        """
        Each cylinder follows:
            dT/dt = (Q_comb − h·(T_cyl − T_amb)) / C_thermal

        Where Q_comb is proportional to power per cylinder.
        """
        power_per_cyl_kw = (
            (self.rpm / MAX_RPM) * COMBUSTION_HEAT_PER_REV
            * (self.rpm / 60.0) * 0.5   # 4-stroke factor
        )
        for i in range(NUM_CYLINDERS):
            q_comb = power_per_cyl_kw + _CHT_OFFSETS[i] * 0.05
            cooling = HEAT_TRANSFER_COEFF * (self.cht_c[i] - self.ambient_temp_c)
            dch_dt = (q_comb - cooling) / CYLINDER_THERMAL_MASS
            self.cht_c[i] += dch_dt * self.dt

    # ── EGT (equivalence-ratio dependent) ───────────────────────

    def _update_egt(self) -> None:
        """
        EGT base = CHT + ΔT_exhaust.
        ΔT_exhaust peaks near stoichiometric (φ ≈ 1.0) and drops
        for lean or rich mixtures.
        """
        phi = self.equivalence_ratio
        # Parabolic relationship: peak ΔT at φ = 1.0
        delta_t_max = 580.0  # peak exhaust rise above CHT [°C]
        delta_t = delta_t_max * (1.0 - 1.6 * (phi - 1.0) ** 2)
        delta_t = max(delta_t, 200.0)   # floor

        for i in range(NUM_CYLINDERS):
            self.egt_c[i] = self.cht_c[i] + delta_t + _CHT_OFFSETS[i] * 0.3

    # ── Oil system ──────────────────────────────────────────────

    def _update_oil(self) -> None:
        """Oil pressure tracks RPM; oil temperature follows thermal
        dissipation toward a steady-state that rises with power."""
        # Pressure: linear with RPM, temperature-corrected
        rpm_factor = self.rpm / MAX_RPM
        temp_factor = 1.0 - 0.0005 * (self.oil_temp_c - 80.0)
        self.oil_pressure_kpa = 250.0 + 350.0 * rpm_factor * temp_factor

        # Oil temperature: Newton cooling toward heat-input steady state
        heat_input = 0.08 * (self.rpm / MAX_RPM) ** 2  # kW-ish
        t_steady = self.ambient_temp_c + heat_input / OIL_COOLING_COEFF * 10
        alpha = 1.0 - math.exp(-self.dt * OIL_COOLING_COEFF / OIL_HEAT_CAPACITY)
        self.oil_temp_c += alpha * (t_steady - self.oil_temp_c)

    # ── Vibration ───────────────────────────────────────────────

    def _update_vibration(self) -> None:
        """Baseline + RPM² mechanical vibration."""
        self.vibration_rms_g = (
            VIB_BASELINE_G + VIB_RPM_COEFF * self.rpm ** 2
        )

    # ── Sensor noise ────────────────────────────────────────────

    def _apply_noise(self, v: float, sd: float) -> float:
        if self.enable_noise:
            return v + random.gauss(0.0, sd)
        return v

    # ── Public step interface ───────────────────────────────────

    def step(
        self,
        throttle: float,
        altitude_ft: float = 0.0,
        weather: str = "CLEAR",
        timestamp: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Advance the simulation by one time-step.

        Parameters
        ----------
        throttle : float
            Throttle lever position, 0.0 (idle) to 1.0 (full).
        altitude_ft : float
            Current barometric altitude [ft].
        weather : str
            Weather condition string passed to AtmosphereModel.
        timestamp : float | None
            Unix timestamp for the frame.  Auto-generated if *None*.

        Returns
        -------
        dict
            Single timestamped frame of all engine parameters.
        """
        # Clamp inputs
        self.throttle = max(0.0, min(1.0, throttle))

        # Update atmosphere coupling
        atm = AtmosphereModel(altitude_ft, weather)
        self.set_atmosphere(atm)

        # Advance all sub-models
        self._update_rpm()
        self._update_map()
        self._update_fuel_flow()
        self._update_cht()
        self._update_egt()
        self._update_oil()
        self._update_vibration()

        self.sim_time += self.dt
        ts = timestamp if timestamp is not None else time.time()

        # Build output frame
        rpm = self._apply_noise(self.rpm, NOISE_RPM_SD)
        map_kpa = self._apply_noise(self.map_kpa, NOISE_MAP_SD)
        fuel = self._apply_noise(self.fuel_flow_lph, NOISE_FUEL_SD)
        oil_p = self._apply_noise(self.oil_pressure_kpa, NOISE_OIL_P_SD)
        oil_t = self._apply_noise(self.oil_temp_c, NOISE_OIL_T_SD)
        vib = self._apply_noise(self.vibration_rms_g, NOISE_VIB_SD)

        cht = [self._apply_noise(c, NOISE_CHT_SD) for c in self.cht_c]
        egt = [self._apply_noise(e, NOISE_EGT_SD) for e in self.egt_c]

        return {
            "timestamp": ts,
            "sim_time_s": round(self.sim_time, 2),
            "altitude_ft": altitude_ft,
            "weather": weather,
            "throttle": self.throttle,
            "rpm": round(rpm, 1),
            "map_kpa": round(map_kpa, 3),
            "fuel_flow_lph": round(fuel, 3),
            "equivalence_ratio": round(self.equivalence_ratio, 4),
            "cht_c": [round(c, 2) for c in cht],
            "egt_c": [round(e, 2) for e in egt],
            "oil_pressure_kpa": round(oil_p, 2),
            "oil_temp_c": round(oil_t, 2),
            "vibration_rms_g": round(vib, 4),
            "air_density_kg_m3": round(self.air_density, 6),
            "ambient_temp_c": round(self.ambient_temp_c, 2),
            "ambient_pressure_kpa": round(self.ambient_pressure_kpa, 3),
        }

    # ── Convenience: multi-step run ─────────────────────────────

    def run(
        self,
        duration_s: float,
        throttle_schedule: Optional[Dict[float, float]] = None,
        altitude_ft: float = 0.0,
        weather: str = "CLEAR",
    ) -> list[Dict[str, Any]]:
        """
        Run the engine for *duration_s* seconds, returning a list of
        frame dicts.  *throttle_schedule* maps sim-time → throttle
        (linearly interpolated).  If *None*, current throttle is held.
        """
        steps = int(duration_s / self.dt)
        frames: list[Dict[str, Any]] = []

        for _ in range(steps):
            thr = self.throttle
            if throttle_schedule:
                thr = _interpolate(throttle_schedule, self.sim_time)
            frames.append(self.step(thr, altitude_ft, weather))

        return frames


# ── Linear interpolation helper ─────────────────────────────────

def _interpolate(schedule: Dict[float, float], t: float) -> float:
    """Return linearly-interpolated throttle from a time→throttle map."""
    times = sorted(schedule.keys())
    if t <= times[0]:
        return schedule[times[0]]
    if t >= times[-1]:
        return schedule[times[-1]]
    for i in range(len(times) - 1):
        if times[i] <= t < times[i + 1]:
            frac = (t - times[i]) / (times[i + 1] - times[i])
            return schedule[times[i]] + frac * (
                schedule[times[i + 1]] - schedule[times[i]]
            )
    return schedule[times[-1]]
