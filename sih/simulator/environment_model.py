#!/usr/bin/env python3
"""
International Standard Atmosphere (ISA) Model
----------------------------------------------
Valid for the troposphere (0 – 11 000 m / ~36 089 ft).
This implementation targets MALE UAV operating ceilings (≤ 25 000 ft).

References:
    - ICAO Standard Atmosphere 1993
    - MIL-HDBK-310 / ISO 2533
"""

from __future__ import annotations

import enum
from typing import Dict


# ── ISA constants ────────────────────────────────────────────────
T0_K = 288.15          # Sea-level standard temperature  [K]
P0_KPA = 101.325       # Sea-level standard pressure      [kPa]
G0 = 9.80665           # Gravitational acceleration        [m/s²]
L_RATE = 0.0065        # Tropospheric lapse rate           [K/m]
R_DRY = 287.058        # Specific gas constant – dry air   [J/(kg·K)]
GAMMA = 1.400          # Specific-heat ratio (dry air)


class WeatherCondition(enum.Enum):
    CLEAR = "CLEAR"
    HUMID = "HUMID"
    RAIN = "RAIN"
    DUST = "DUST"


class AtmosphereModel:
    """
    Computes ISA thermodynamic properties for a given altitude
    with optional weather-condition modifiers.

    Parameters
    ----------
    altitude_ft : float
        Barometric altitude in feet (0 – 25 000 typical).
    weather_condition : WeatherCondition | str
        One of 'CLEAR', 'HUMID', 'RAIN', 'DUST'.
    """

    # Maximum tropospheric altitude before stratospheric equations
    # would be needed (tropopause ≈ 36 089 ft).
    MAX_TROPOSPHERE_FT = 36_089

    def __init__(
        self,
        altitude_ft: float,
        weather_condition: WeatherCondition | str = WeatherCondition.CLEAR,
    ) -> None:
        if altitude_ft < 0:
            raise ValueError(f"altitude_ft must be ≥ 0, got {altitude_ft}")
        if altitude_ft > self.MAX_TROPOSPHERE_FT:
            raise ValueError(
                f"altitude {altitude_ft} ft exceeds tropopause "
                f"({self.MAX_TROPOSPHERE_FT} ft). "
                "Only tropospheric model is implemented."
            )

        self.altitude_ft = altitude_ft
        self.altitude_m = altitude_ft * 0.3048  # exact ft → m

        if isinstance(weather_condition, str):
            self.weather = WeatherCondition(weather_condition.upper())
        else:
            self.weather = weather_condition

        # Compute base ISA properties, then apply weather
        self._t = self._isa_temperature()
        self._p = self._isa_pressure()
        self._rho = self._isa_density()

        self._apply_weather_modifiers()

    # ── Core ISA equations ──────────────────────────────────────

    def _isa_temperature(self) -> float:
        """Tropospheric temperature:  T = T₀ − L·h  [K]."""
        return T0_K - L_RATE * self.altitude_m

    def _isa_pressure(self) -> float:
        """
        Barometric formula (troposphere):
            P = P₀ · (T / T₀)^(g₀ / (L·R))
        Returns pressure in kPa.
        """
        exponent = G0 / (L_RATE * R_DRY)  # ≈ 5.2559
        return P0_KPA * (self._t / T0_K) ** exponent

    def _isa_density(self) -> float:
        """Ideal-gas density:  ρ = P / (R·T)  [kg/m³]."""
        p_pa = self._p * 1000.0  # kPa → Pa
        return p_pa / (R_DRY * self._t)

    # ── Weather modifiers ──────────────────────────────────────

    def _apply_weather_modifiers(self) -> None:
        """Mutate _t, _p, _rho in-place based on weather condition."""
        match self.weather:
            case WeatherCondition.HUMID:
                # Humid air is less dense than dry air at same T, P
                # because water vapor (M=18) displaces N₂/O₂ (M≈29).
                # We model a 1.5 % reduction in dry-air density.
                self._rho *= 0.985

            case WeatherCondition.RAIN:
                # Cooling of intake air by 3 K (evaporative effect)
                self._t -= 3.0
                # Recalculate density at the cooler temperature
                p_pa = self._p * 1000.0
                self._rho = p_pa / (R_DRY * self._t)
                # 0.5 % drag resistance is not an atmosphere property
                # per se — it is a flight-dynamics modifier.  We store
                # it as a named attribute for downstream modules.
                self.drag_factor = 1.005

            case WeatherCondition.DUST:
                # Dust in the atmosphere increases filtration losses;
                # we model this as a 3 % reduction in intake-manifold
                # flow-efficiency factor.
                self.intake_efficiency = 0.97

            case WeatherCondition.CLEAR:
                # No modifiers
                pass

    # ── Public API ─────────────────────────────────────────────

    def compute(self) -> Dict[str, float]:
        """
        Return the full atmosphere state dictionary.

        Keys
        ----
        ambient_temp_k        : Ambient temperature [K]
        ambient_temp_c        : Ambient temperature [°C]
        ambient_pressure_kpa  : Ambient pressure   [kPa]
        air_density_kg_m3     : Air density         [kg/m³]
        density_ratio         : ρ / ρ₀ (ratio to sea-level density)
        """
        rho0 = P0_KPA * 1000.0 / (R_DRY * T0_K)  # sea-level density

        return {
            "ambient_temp_k": round(self._t, 4),
            "ambient_temp_c": round(self._t - 273.15, 4),
            "ambient_pressure_kpa": round(self._p, 4),
            "air_density_kg_m3": round(self._rho, 6),
            "density_ratio": round(self._rho / rho0, 6),
        }


# ── CLI validation table ────────────────────────────────────────

def _print_table() -> None:
    """Print a formatted validation table for standard altitudes."""
    altitudes = list(range(0, 25_001, 5_000))

    header = (
        f"{'Alt (ft)':>10}  {'Alt (m)':>10}  {'T (K)':>8}  {'T (°C)':>8}  "
        f"{'P (kPa)':>9}  {'ρ (kg/m³)':>10}  {'σ (ρ/ρ₀)':>10}  {'Weather':<8}"
    )
    sep = "─" * len(header)

    print("\n  ISA Atmosphere Model — Validation Table")
    print(f"  Weather conditions tested: CLEAR, HUMID, RAIN, DUST\n")
    print(f"  {header}")
    print(f"  {sep}")

    for weather in WeatherCondition:
        if weather != WeatherCondition.CLEAR:
            print()  # blank line between weather blocks
        for alt_ft in altitudes:
            model = AtmosphereModel(alt_ft, weather)
            s = model.compute()
            print(
                f"  {alt_ft:>10,}  {alt_ft * 0.3048:>10.1f}  "
                f"{s['ambient_temp_k']:>8.2f}  {s['ambient_temp_c']:>8.2f}  "
                f"{s['ambient_pressure_kpa']:>9.3f}  "
                f"{s['air_density_kg_m3']:>10.6f}  "
                f"{s['density_ratio']:>10.6f}  {weather.value:<8}"
            )

    print(f"\n  {sep}")
    print("  Validation complete.\n")


if __name__ == "__main__":
    _print_table()
