"""
Analytic physics baseline.
==========================

Computes the *expected* (healthy) value of every sensor given the current
operating conditions (throttle, altitude, ambient temperature, RPM). These
steady-state expectations mirror the calibration equations in
:mod:`simulator.telemetry_gen.engine_model`, so a healthy engine produces
residuals ≈ 0 and every fault produces a characteristic residual pattern.

    residual = observed − expected

The baseline is purely analytic (no training), which makes it:

* deterministic and explainable ("EGT is +76 °C above the physics model"),
* robust to dataset shift,
* usable as the hybrid-model backbone: ``predicted = physics + ML_correction``.

Note: expectations are cylinder-*symmetric* (mean behaviour); the small
per-cylinder manufacturing spread in the generator shows up as a ±15 °C
residual offset on EGT, which is a deliberate, learnable pattern.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from simulator.telemetry_gen.engine_model import (
    FUEL_GAIN_LPH,
    FUEL_IDLE_LPH,
    OIL_P0_KPA,
    OIL_P_RPM_KPA,
    OIL_P_TEMP_KPA,
    isa_conditions,
)

NUM_CYL = 4


def expected_sensors(row: Dict[str, object]) -> Dict[str, float]:
    """
    Expected healthy values for the sensor set, keyed like the telemetry CSV.

    Consumes the *observed* ``rpm`` and ``oil_temp_c`` (physical feedback
    loop: RPM and oil temperature are slow states, not fast sensor artefacts).
    """
    throttle = float(row["throttle"])
    altitude_ft = float(row["altitude_ft"])
    ambient = float(row["ambient_temp_c"])
    rpm = float(row["rpm"])
    oil_temp = float(row["oil_temp_c"])

    rho = isa_conditions(altitude_ft)["density_ratio"]
    eff = max(0.02, throttle * (0.55 + 0.45 * rho))

    # ── fuel flow ──
    fuel = FUEL_IDLE_LPH + FUEL_GAIN_LPH * eff ** 1.3

    # ── EGT (fast, altitude-lean) ──
    egt = 380.0 + 0.045 * rpm + 9.0 * fuel + 0.6 * max(0.0, (altitude_ft - 3000.0) / 1000.0)

    # ── CHT (slow thermal steady state) ──
    heat_in = 6.0 + 13.0 * fuel ** 0.9
    cht_rise = heat_in / (0.22 + 0.10 * rpm / 1000.0) / (0.8 + 0.2 * rho)
    cht = ambient + cht_rise

    # ── oil ──
    oil_p = (
        OIL_P0_KPA
        + OIL_P_RPM_KPA * rpm
        - OIL_P_TEMP_KPA * max(0.0, oil_temp - 90.0)
    )
    oil_t = 38.0 + 55.0 * eff + 0.004 * rpm + 0.1 * (ambient - 15.0)

    # ── vibration / electrical / injection ──
    vib = 0.28 + 0.000085 * rpm + 0.35 * eff ** 1.6
    battery = 14.25 if rpm >= 1500.0 else 12.55
    alternator = 22.0

    cht_avg = _mean_cyl(row, "cht")
    advance = min(
        38.0, max(18.0, 22.0 + 0.0026 * rpm - 0.05 * max(0.0, cht_avg - 165.0))
    )

    return {
        "fuel_flow_lph": fuel,
        "egt_c1": egt, "egt_c2": egt, "egt_c3": egt, "egt_c4": egt,
        "cht_c1": cht, "cht_c2": cht, "cht_c3": cht, "cht_c4": cht,
        "oil_pressure_kpa": max(0.0, oil_p),
        "oil_temp_c": oil_t,
        "vibration_rms_g": vib,
        "battery_v": battery,
        "alternator_a": alternator,
        "injection_timing_deg": advance,
    }


def residuals(row: Dict[str, object], expected: Dict[str, float]) -> Dict[str, float]:
    """observed − expected for every numeric sensor channel."""
    out: Dict[str, float] = {}
    for key, exp in expected.items():
        obs = float(row[key])
        out[key] = obs - exp
    return out


def residual_summary(row: Dict[str, object]) -> Dict[str, float]:
    """
    Compact residual vector used by the feature extractor:

    * ``r_cht_avg / r_cht_max`` — signed mean / max-abs per-cylinder CHT res
    * ``r_egt_avg / r_egt_max`` — same for EGT
    * per-channel residuals for the remaining sensors
    """
    exp = expected_sensors(row)
    res = residuals(row, exp)

    def cyl(name: str) -> List[float]:
        return [res[f"{name}_c{i}"] for i in range(1, NUM_CYL + 1)]

    def avg(vals: List[float]) -> float:
        return sum(vals) / len(vals)

    def max_abs(vals: List[float]) -> float:
        return max(abs(v) for v in vals)

    cht_vals, egt_vals = cyl("cht"), cyl("egt")
    return {
        "r_cht_avg": avg(cht_vals),
        "r_cht_max": max_abs(cht_vals),
        "r_egt_avg": avg(egt_vals),
        "r_egt_max": max_abs(egt_vals),
        "r_fuel": res["fuel_flow_lph"],
        "r_oil_p": res["oil_pressure_kpa"],
        "r_oil_t": res["oil_temp_c"],
        "r_vib": res["vibration_rms_g"],
        "r_batt": res["battery_v"],
        "r_alt": res["alternator_a"],
    }


def _mean_cyl(row: Dict[str, object], kind: str) -> float:
    vals = [float(row[f"{kind}_c{i}"]) for i in range(1, NUM_CYL + 1)]
    return sum(vals) / len(vals)