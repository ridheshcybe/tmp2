"""
Physics-based healthy baseline engine model.
=============================================

A simplified, *physically plausible* simulation of a ~100-130 hp air-cooled,
horizontally-opposed 4-cylinder aero piston engine (the class of engine used
in MALE UAVs such as DRDO Tapas-BH-201).

IMPORTANT: these are simulation equations calibrated to land inside realistic
sensor envelopes (idle vs cruise vs climb), NOT certified engine equations.
They exist to make the digital-twin demonstrator behave credibly and to give
downstream residual-based fault detection a meaningful baseline.

Sub-models
----------
* ISA atmosphere (temperature, pressure, density ratio vs altitude).
* RPM dynamics (first-order lag toward a throttle × air-density target).
* Fuel flow (throttle/air-density power law).
* Per-cylinder CHT thermal model (Newton's law of cooling, slow time constant).
* Per-cylinder EGT model (fast, altitude-lean effect).
* Oil temperature (slow integrator) and oil pressure (pump ∝ RPM, viscosity ∝ T).
* Vibration RMS baseline (RPM + load).
* Battery voltage / alternator current (charging bus above ~1500 RPM).
* Injection timing advance (RPM advance + CHT retard).

Determinism: the only source of randomness is the injected ``rng``
(``numpy.random.default_rng(seed)``).
"""

from __future__ import annotations

import math
from typing import Dict, List

import numpy as np

from simulator.telemetry_gen.telemetry_schema import (
    CYLINDER_KEYS,
    NUM_CYLINDERS,
    SENSOR_NOISE_STD,
)

# ──────────────────────────────────────────────────────────────────────────
#  Calibration constants (tuned to realistic envelopes, see README table)
# ──────────────────────────────────────────────────────────────────────────

RPM_IDLE = 1100.0            # engine speed at closed throttle, rpm
RPM_MAX = 5600.0             # rated speed, rpm
RPM_EXPONENT = 0.95          # throttle→speed curvature

FUEL_IDLE_LPH = 1.1          # l/h at idle
FUEL_GAIN_LPH = 13.8         # l/h per unit (throttle_eff ** 1.3)

TAU_RPM_S = 1.0              # rpm first-order lag, s
TAU_CHT_S = 45.0             # cylinder head thermal lag, s
TAU_EGT_S = 2.0              # exhaust gas lag, s
TAU_OIL_S = 400.0            # oil temperature lag, s

OIL_P0_KPA = 265.0           # oil pressure base, kPa
OIL_P_RPM_KPA = 0.052        # kPa per rpm (mechanical pump)
OIL_P_TEMP_KPA = 2.6         # kPa loss per °C above 90 (viscosity)

# Per-cylinder manufacturing spread (deterministic, fractional)
CYL_SPREAD_CHT = np.array([-0.025, -0.005, 0.020, 0.010])
CYL_SPREAD_EGT = np.array([-0.020, 0.000, 0.015, 0.005])


def isa_conditions(altitude_ft: float) -> Dict[str, float]:
    """
    International Standard Atmosphere at ``altitude_ft``.

    Returns ambient temperature (°C), pressure ratio (P/P0) and
    density ratio (rho/rho0). Troposphere lapse below 11 km, isothermal
    stratosphere above.
    """
    h_m = max(0.0, altitude_ft) * 0.3048
    L = 0.0065          # K/m lapse rate
    T0 = 288.15         # K at sea level
    P0 = 101325.0       # Pa at sea level
    g = 9.80665
    R = 287.05

    if h_m <= 11000.0:
        T = T0 - L * h_m
        P = P0 * (T / T0) ** (g / (L * R))
    else:
        T = 216.65
        P = 22632.0 * math.exp(-g * (h_m - 11000.0) / (R * T))

    rho = P / (R * T)
    return {
        "ambient_temp_c": T - 273.15,
        "pressure_ratio": P / P0,
        "density_ratio": rho / 1.225,
    }


class EngineModel:
    """
    Deterministic healthy-baseline engine.

    Call :meth:`step` once per simulation tick. State persists across
    calls so thermal/oil/RPM dynamics carry over realistically.
    """

    def __init__(
        self,
        seed: int = 0,
        ambient_offset_c: float = 0.0,
        cylinders: int = NUM_CYLINDERS,
    ) -> None:
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.ambient_offset_c = ambient_offset_c
        self.cylinders = cylinders

        # ── persistent state ──
        self.rpm = 0.0
        self.cht_c = [15.0] * cylinders
        self.egt_c = [15.0] * cylinders
        self.oil_temp_c = 25.0
        self.oil_pressure_kpa = 0.0
        self.vibration_rms_g = 0.15
        self.battery_v = 12.5
        self.alternator_a = 0.0
        self.injection_timing_deg = 24.0

        # tiny deterministic per-instance cylinder jitter
        self._spread_cht = CYL_SPREAD_CHT[:cylinders] + self.rng.normal(
            0.0, 0.004, size=cylinders
        )
        self._spread_egt = CYL_SPREAD_EGT[:cylinders] + self.rng.normal(
            0.0, 0.003, size=cylinders
        )

    # ──────────────────────────────────────────────────────────────────────
    #  Core step
    # ──────────────────────────────────────────────────────────────────────

    def step(
        self,
        throttle: float,
        altitude_ft: float,
        ambient_temp_c: float,
    ) -> Dict[str, object]:
        """
        Advance the healthy engine by one tick (dt = 1 / hz) and return a
        flat, *noisy* telemetry row keyed like ``CSV_COLUMNS``.

        ``ambient_temp_c`` is the externally supplied ambient temperature
        (already ISA-derived + offset by the caller) — used for thermal
        reference and cooling delta.
        """
        rng = self.rng

        # ── atmosphere / air density ──
        isa = isa_conditions(altitude_ft)
        sigma_rho = isa["density_ratio"]

        # Naturally-aspirated power loss with altitude.
        power_ratio = 0.55 + 0.45 * sigma_rho
        throttle_eff = max(0.02, throttle * power_ratio)

        # ── RPM dynamics (first-order lag) ──
        rpm_target = RPM_IDLE + (RPM_MAX - RPM_IDLE) * throttle_eff ** RPM_EXPONENT
        alpha_rpm = 1.0 / TAU_RPM_S
        self.rpm += (rpm_target - self.rpm) * alpha_rpm
        rpm = self.rpm

        # ── fuel flow ──
        fuel_flow = FUEL_IDLE_LPH + FUEL_GAIN_LPH * throttle_eff ** 1.3

        # ── CHT (slow thermal model, Newton's law of cooling) ──
        #   heat_in      ∝ fuel burned (damped at high flow)
        #   heat_out     ∝ cooling airflow (RPM × air density)
        heat_in = 6.0 + 13.0 * fuel_flow ** 0.9
        cool_denom = 0.22 + 0.10 * (rpm / 1000.0)
        alt_cool_factor = 1.0 / (0.8 + 0.2 * sigma_rho)
        cht_ss_rise = heat_in / cool_denom * alt_cool_factor
        alpha_cht = 1.0 / TAU_CHT_S
        self.cht_c = [
            c + (ambient_temp_c + cht_ss_rise * (1.0 + spread) - c) * alpha_cht
            for c, spread in zip(self.cht_c, self._spread_cht)
        ]
        cht_avg = float(np.mean(self.cht_c))

        # ── EGT (fast, altitude-lean effect) ──
        egt_lean = 0.6 * max(0.0, (altitude_ft - 3000.0) / 1000.0)
        egt_ss = 380.0 + 0.045 * rpm + 9.0 * fuel_flow + egt_lean
        alpha_egt = 1.0 / TAU_EGT_S
        self.egt_c = [
            e + (egt_ss * (1.0 + spread) - e) * alpha_egt
            for e, spread in zip(self.egt_c, self._spread_egt)
        ]

        # ── oil temperature (slow integrator) ──
        oil_ss = (
            38.0
            + 55.0 * throttle_eff
            + 0.004 * rpm
            + 0.1 * (ambient_temp_c - 15.0)
        )
        alpha_oil = 1.0 / TAU_OIL_S
        self.oil_temp_c += (oil_ss - self.oil_temp_c) * alpha_oil
        oil_temp = self.oil_temp_c

        # ── oil pressure (pump ∝ RPM, viscosity loss above 90 °C) ──
        oil_pressure = (
            OIL_P0_KPA
            + OIL_P_RPM_KPA * rpm
            - OIL_P_TEMP_KPA * max(0.0, oil_temp - 90.0)
        )
        oil_pressure = max(0.0, oil_pressure)

        # ── vibration RMS baseline ──
        vibration = 0.28 + 0.000085 * rpm + 0.35 * throttle_eff ** 1.6

        # ── battery / alternator ──
        alternator_a = 22.0
        battery_v = 14.25 if rpm >= 1500.0 else 12.55

        # ── injection timing advance (RPM advance, CHT retard) ──
        advance = 22.0 + 0.0026 * rpm - 0.05 * max(0.0, cht_avg - 165.0)
        advance = min(38.0, max(18.0, advance))

        # ── assemble row ──
        row: Dict[str, object] = {
            "sim_time_s": 0.0,      # filled by caller
            "phase": "",            # filled by caller
            "throttle": throttle,
            "altitude_ft": altitude_ft,
            "ambient_temp_c": ambient_temp_c,
            "rpm": rpm,
            "fuel_flow_lph": fuel_flow,
        }
        for i, key in enumerate(CYLINDER_KEYS[: self.cylinders]):
            row[f"cht_{key}"] = self.cht_c[i]
            row[f"egt_{key}"] = self.egt_c[i]
        row.update(
            {
                "oil_pressure_kpa": oil_pressure,
                "oil_temp_c": oil_temp,
                "vibration_rms_g": vibration,
                "battery_v": battery_v,
                "alternator_a": alternator_a,
                "injection_timing_deg": advance,
            }
        )

        # ── apply sensor noise (deterministic via self.rng) ──
        for col, std in SENSOR_NOISE_STD.items():
            if col in row and isinstance(row[col], (int, float)):
                row[col] = float(row[col]) + rng.normal(0.0, std)

        return row