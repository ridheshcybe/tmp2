#!/usr/bin/env python3
"""
Engine Health Index Calculator
==============================
Derives real-time engine condition metrics from the fused latent
vector (from :class:`CrossModalFusionNet`) and raw telemetry.

Metrics
-------
* **Engine Health Index (EHI)**: 0–100% composite score.
* **Combustion Degradation Metric (CDM)**: BSFC comparison vs baseline.
* **Cylinder Thermal Balance**: std-dev spread across cylinders.

Usage
-----
    calc = HealthIndexCalculator()
    result = calc.compute(fused_vector, raw_frame)
    print(result["engine_health_index"], "%")
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


# ══════════════════════════════════════════════════════════════════
#  Reference / baseline constants
# ══════════════════════════════════════════════════════════════════

# Theoretical optimal BSFC for this engine class [kg/(kW·h)]
BSFC_OPTIMAL_KG_PER_KWH = 0.26

# Fuel density [kg/L]
FUEL_DENSITY_KG_PER_L = 0.72

# Typical nominal values for healthy engine at cruise
NOMINAL = {
    "rpm": 2200.0,
    "map_kpa": 78.0,
    "fuel_flow_lph": 13.0,
    "cht_mean_c": 180.0,
    "egt_mean_c": 740.0,
    "oil_pressure_kpa": 400.0,
    "oil_temp_c": 90.0,
    "vibration_rms_g": 1.5,
    "equivalence_ratio": 0.85,
}

# Alarm thresholds
THRESHOLDS = {
    "cht_max_c": 260.0,
    "egt_max_c": 870.0,
    "oil_pressure_min_kpa": 180.0,
    "oil_temp_max_c": 140.0,
    "vibration_max_g": 1.8,
}


# ══════════════════════════════════════════════════════════════════
#  Health status classification
# ══════════════════════════════════════════════════════════════════

class HealthStatus:
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"


# ══════════════════════════════════════════════════════════════════
#  Output dataclass
# ══════════════════════════════════════════════════════════════════

@dataclass
class HealthReport:
    """
    Complete engine health assessment.

    Attributes
    ----------
    engine_health_index : float
        Composite health score 0.0 (critical) – 100.0 (pristine).
    thermal_strain_index : float
        Sub-index: thermal health 0–100.
    mechanical_stress_index : float
        Sub-index: mechanical health 0–100.
    lubrication_health : float
        Sub-index: oil system health 0–100.
    model_anomaly_residual : float
        Sub-index: ML model agreement 0–100.
    combustion_efficiency : float
        CDM score: 100 = optimal, < 70 = severe degradation.
    thermal_balance_spread : float
        Std-dev spread across CHT and EGT cylinders.
    health_status : str
        "NORMAL" | "DEGRADED" | "CRITICAL".
    """

    engine_health_index: float
    thermal_strain_index: float
    mechanical_stress_index: float
    lubrication_health: float
    model_anomaly_residual: float
    combustion_efficiency: float
    thermal_balance_spread: float
    health_status: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "engine_health_index": round(self.engine_health_index, 2),
            "combustion_efficiency": round(self.combustion_efficiency, 2),
            "thermal_balance_spread": round(self.thermal_balance_spread, 2),
            "health_status": self.health_status,
            # Sub-indices for detailed diagnostics
            "thermal_strain_index": round(self.thermal_strain_index, 2),
            "mechanical_stress_index": round(self.mechanical_stress_index, 2),
            "lubrication_health": round(self.lubrication_health, 2),
            "model_anomaly_residual": round(self.model_anomaly_residual, 2),
        }


# ══════════════════════════════════════════════════════════════════
#  Health Index Calculator
# ══════════════════════════════════════════════════════════════════

class HealthIndexCalculator:
    """
    Computes real-time engine condition metrics from fused latent
    vectors and raw telemetry frames.

    Parameters
    ----------
    ehi_weights : dict
        Weights for the four EHI sub-indices.  Keys:
        ``thermal_strain``, ``mechanical_stress``, ``lubrication``,
        ``model_anomaly``.  Must sum to 1.0.
    """

    # Default EHI weights
    DEFAULT_WEIGHTS = {
        "thermal_strain": 0.35,
        "mechanical_stress": 0.35,
        "lubrication": 0.15,
        "model_anomaly": 0.15,
    }

    def __init__(
        self,
        ehi_weights: Optional[Dict[str, float]] = None,
    ) -> None:
        self.weights = ehi_weights or self.DEFAULT_WEIGHTS.copy()
        total_w = sum(self.weights.values())
        if abs(total_w - 1.0) > 0.001:
            raise ValueError(
                f"EHI weights must sum to 1.0, got {total_w:.4f}"
            )

    # ── Public API ─────────────────────────────────────────────

    def compute(
        self,
        fused_vector: Optional[Any] = None,
        raw_frame: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Compute the full health report.

        Parameters
        ----------
        fused_vector : array-like, optional
            32-dim fused latent from :class:`CrossModalFusionNet`.
            If *None*, ``model_anomaly`` sub-index defaults to 80.
        raw_frame : dict
            Telemetry frame with keys like ``rpm``, ``cht_c``, ``egt_c``,
            ``oil_pressure_kpa``, ``oil_temp_c``, ``vibration_rms_g``,
            ``fuel_flow_lph``, ``map_kpa``.

        Returns
        -------
        dict
            Health report (see :class:`HealthReport`).
        """
        if raw_frame is None:
            raise ValueError("raw_frame is required")

        # ── Extract sensor values ──
        sensors = self._extract_sensors(raw_frame)

        # ── Compute sub-indices ──
        tsi = self._thermal_strain_index(sensors)
        msi = self._mechanical_stress_index(sensors)
        lhi = self._lubrication_health(sensors)
        mar = self._model_anomaly_residual(fused_vector)

        # ── Composite EHI ──
        ehi = (
            self.weights["thermal_strain"] * tsi
            + self.weights["mechanical_stress"] * msi
            + self.weights["lubrication"] * lhi
            + self.weights["model_anomaly"] * mar
        )
        ehi = max(0.0, min(100.0, ehi))

        # ── Combustion Degradation Metric ──
        cdm = self._combustion_degradation_metric(sensors)

        # ── Cylinder Thermal Balance ──
        ctbs = self._cylinder_thermal_balance(sensors)

        # ── Health Status classification ──
        status = self._classify_status(ehi, ctm=ctbs, sensors=sensors)

        report = HealthReport(
            engine_health_index=ehi,
            thermal_strain_index=tsi,
            mechanical_stress_index=msi,
            lubrication_health=lhi,
            model_anomaly_residual=mar,
            combustion_efficiency=cdm,
            thermal_balance_spread=ctbs,
            health_status=status,
        )

        return report.to_dict()

    # ── Sub-index: Thermal Strain ──────────────────────────────

    def _thermal_strain_index(self, s: Dict[str, float]) -> float:
        """
        Thermal health: penalises high CHT, high EGT, and high EGT-CHT
        differential (indicates combustion problems).

        Score: 100 = all temps nominal, 0 = all temps at alarm.
        """
        cht_mean = s["cht_mean"]
        egt_mean = s["egt_mean"]

        # CHT component: linear penalty from nominal to alarm
        cht_penalty = self._linear_penalty(
            cht_mean, NOMINAL["cht_mean_c"], THRESHOLDS["cht_max_c"]
        )

        # EGT component
        egt_penalty = self._linear_penalty(
            egt_mean, NOMINAL["egt_mean_c"], THRESHOLDS["egt_max_c"]
        )

        # EGT-CHT differential (healthy ≈ 560°C; rising = bad)
        delta_egt_cht = egt_mean - cht_mean
        nominal_delta = NOMINAL["egt_mean_c"] - NOMINAL["cht_mean_c"]
        delta_penalty = self._linear_penalty(
            delta_egt_cht, nominal_delta, nominal_delta + 150.0
        )

        # Weighted combination
        score = 100.0 - (0.4 * cht_penalty + 0.4 * egt_penalty + 0.2 * delta_penalty)
        return max(0.0, min(100.0, score))

    # ── Sub-index: Mechanical Stress ───────────────────────────

    def _mechanical_stress_index(self, s: Dict[str, float]) -> float:
        """
        Mechanical health: penalises high vibration, RPM deviation,
        and thermal balance spread.

        Score: 100 = all mechanical parameters nominal.
        """
        vib = s["vibration"]
        rpm = s["rpm"]

        # Vibration penalty
        vib_penalty = self._linear_penalty(
            vib, NOMINAL["vibration_rms_g"], THRESHOLDS["vibration_max_g"]
        )

        # RPM deviation from nominal (non-directional)
        rpm_dev = abs(rpm - NOMINAL["rpm"]) / NOMINAL["rpm"]
        rpm_penalty = min(100.0, rpm_dev * 200.0)  # 50% deviation = 100 penalty

        # Cylinder imbalance penalty
        cht_std = s["cht_std"]
        egt_std = s["egt_std"]
        imbalance = (cht_std + egt_std) / 2.0
        imbalance_penalty = min(100.0, imbalance * 2.0)  # 50°C std = 100

        score = 100.0 - (0.45 * vib_penalty + 0.30 * rpm_penalty + 0.25 * imbalance_penalty)
        return max(0.0, min(100.0, score))

    # ── Sub-index: Lubrication Health ──────────────────────────

    def _lubrication_health(self, s: Dict[str, float]) -> float:
        """
        Lubrication health: penalises low oil pressure and high oil
        temperature (indicates leak, contamination, or bearing wear).

        Score: 100 = oil system nominal.
        """
        oil_p = s["oil_pressure"]
        oil_t = s["oil_temp"]

        # Oil pressure: penalty for dropping below nominal
        p_deviation = max(0.0, NOMINAL["oil_pressure_kpa"] - oil_p)
        p_penalty = min(100.0, (p_deviation / NOMINAL["oil_pressure_kpa"]) * 200.0)

        # Oil temperature: penalty for exceeding nominal
        t_penalty = self._linear_penalty(
            oil_t, NOMINAL["oil_temp_c"], THRESHOLDS["oil_temp_max_c"]
        )

        score = 100.0 - (0.6 * p_penalty + 0.4 * t_penalty)
        return max(0.0, min(100.0, score))

    # ── Sub-index: Model Anomaly Residual ──────────────────────

    def _model_anomaly_residual(
        self,
        fused_vector: Optional[Any],
    ) -> float:
        """
        Anomaly residual from the fusion model.  If no vector is
        provided, returns a default (assumes nominal).
        """
        if fused_vector is None:
            return 80.0  # neutral default

        vec = np.asarray(fused_vector, dtype=np.float64).ravel()

        # Compute L2 norm of the fused vector as a proxy for anomaly
        # distance from a "zero-mean nominal" embedding.
        # In production, this would be compared against a learned
        # nominal manifold.  Here we use a simple heuristic.
        l2_norm = np.linalg.norm(vec)

        # Typical range: 0–20 for normal, >5 for anomalous
        # Map to 0–100 health score
        score = max(0.0, 100.0 - (l2_norm - 2.0) * 15.0)
        return min(100.0, score)

    # ── Combustion Degradation Metric ──────────────────────────

    def _combustion_degradation_metric(self, s: Dict[str, float]) -> float:
        """
        Compares actual BSFC against theoretical optimal baseline.

        BSFC = fuel_flow [kg/h] / power [kW]
             = (fuel_flow_lph × fuel_density) / power_kw

        Power estimated from MAP, RPM, and displacement:
            P = MAP × V_d × RPM / (60 × 2)  [4-stroke]
        """
        fuel_lph = s["fuel_flow"]
        map_kpa = s["map_kpa"]
        rpm = s["rpm"]

        if fuel_lph <= 0 or rpm <= 0:
            return 0.0

        # Fuel mass flow [kg/h]
        fuel_kg_h = fuel_lph * FUEL_DENSITY_KG_PER_L

        # Estimated power [kW]
        displacement_m3 = 3.2e-3  # 3.2 L total
        vol_eff = 0.85  # average volumetric efficiency
        bmep = map_kpa * vol_eff * 0.80  # kPa
        power_kw = (bmep * displacement_m3 * rpm) / (60.0 * 2.0)

        if power_kw <= 0:
            return 0.0

        # Actual BSFC
        bsfc_actual = fuel_kg_h / power_kw  # kg/(kW·h)

        # CDM = optimal / actual (1.0 = optimal, < 0.7 = severe)
        # If actual BSFC is higher than optimal, combustion is worse
        cdm_ratio = BSFC_OPTIMAL_KG_PER_KWH / max(bsfc_actual, 0.01)
        cdm_ratio = min(1.2, max(0.0, cdm_ratio))  # clamp

        # Convert to 0–100 score
        score = cdm_ratio * 100.0
        return max(0.0, min(100.0, score))

    # ── Cylinder Thermal Balance ───────────────────────────────

    def _cylinder_thermal_balance(self, s: Dict[str, float]) -> float:
        """
        Standard deviation across all 4 CHT and 4 EGT cylinders.
        High spread = uncoordinated wear or injector clogging.
        """
        cht_std = s["cht_std"]
        egt_std = s["egt_std"]
        # Combined spread (averaged)
        return (cht_std + egt_std) / 2.0

    # ── Health Status Classification ───────────────────────────

    def _classify_status(
        self,
        ehi: float,
        ctm: float,
        sensors: Dict[str, float],
    ) -> str:
        """
        Classify engine health into NORMAL, DEGRADED, or CRITICAL.

        CRITICAL conditions:
        - EHI < 40%
        - Any single sensor at alarm threshold
        - CHT spread > 30°C (severe imbalance)
        """
        # Critical: EHI too low
        if ehi < 40.0:
            return HealthStatus.CRITICAL

        # Critical: any sensor at alarm
        if (
            sensors["cht_mean"] > THRESHOLDS["cht_max_c"]
            or sensors["egt_mean"] > THRESHOLDS["egt_max_c"]
            or sensors["oil_pressure"] < THRESHOLDS["oil_pressure_min_kpa"]
            or sensors["vibration"] > THRESHOLDS["vibration_max_g"]
        ):
            return HealthStatus.CRITICAL

        # Critical: severe thermal imbalance
        if ctm > 30.0:
            return HealthStatus.CRITICAL

        # Degraded
        if ehi < 70.0:
            return HealthStatus.DEGRADED

        return HealthStatus.NORMAL

    # ── Helpers ────────────────────────────────────────────────

    def _extract_sensors(self, frame: Dict[str, Any]) -> Dict[str, float]:
        """Extract and compute derived sensor values from a frame."""
        # Handle both flat and nested cht/egt formats
        cht = frame.get("cht_c", frame.get("cht", [0, 0, 0, 0]))
        egt = frame.get("egt_c", frame.get("egt", [0, 0, 0, 0]))

        cht_arr = np.array(cht, dtype=np.float64)
        egt_arr = np.array(egt, dtype=np.float64)

        return {
            "rpm": float(frame.get("rpm", 0)),
            "map_kpa": float(frame.get("map_kpa", 0)),
            "fuel_flow": float(frame.get("fuel_flow_lph", 0)),
            "oil_pressure": float(frame.get("oil_pressure_kpa", 0)),
            "oil_temp": float(frame.get("oil_temp_c", 0)),
            "vibration": float(frame.get("vibration_rms_g", 0)),
            "equivalence_ratio": float(frame.get("equivalence_ratio", 0)),
            "cht_mean": float(cht_arr.mean()),
            "cht_std": float(cht_arr.std()),
            "egt_mean": float(egt_arr.mean()),
            "egt_std": float(egt_arr.std()),
        }

    @staticmethod
    def _linear_penalty(
        value: float,
        nominal: float,
        alarm: float,
    ) -> float:
        """
        Linear penalty: 0 at nominal, 100 at alarm.
        Returns 0 below nominal, 100 above alarm.
        """
        if alarm <= nominal:
            return 0.0
        if value <= nominal:
            return 0.0
        if value >= alarm:
            return 100.0
        return ((value - nominal) / (alarm - nominal)) * 100.0


# ══════════════════════════════════════════════════════════════════
#  CLI demo
# ══════════════════════════════════════════════════════════════════

def _demo() -> None:
    """Demonstrate health index calculation with nominal and faulty frames."""
    calc = HealthIndexCalculator()

    # Nominal frame
    nominal_frame = {
        "rpm": 2200, "map_kpa": 78, "fuel_flow_lph": 13.0,
        "cht_c": [178.0, 177.0, 179.0, 176.0],
        "egt_c": [740.0, 738.0, 742.0, 736.0],
        "oil_pressure_kpa": 410.0, "oil_temp_c": 88.0,
        "vibration_rms_g": 1.45, "equivalence_ratio": 0.85,
    }

    # Faulty frame (lean burn)
    faulty_frame = {
        "rpm": 1950, "map_kpa": 65, "fuel_flow_lph": 8.0,
        "cht_c": [245.0, 242.0, 248.0, 240.0],
        "egt_c": [890.0, 885.0, 895.0, 880.0],
        "oil_pressure_kpa": 280.0, "oil_temp_c": 125.0,
        "vibration_rms_g": 1.95, "equivalence_ratio": 0.62,
    }

    print("\n  Engine Health Index Calculator — Demo")
    print("  " + "=" * 55)

    for label, frame in [("NOMINAL", nominal_frame), ("FAULTY (Lean Burn)", faulty_frame)]:
        report = calc.compute(raw_frame=frame)
        print(f"\n  {label}:")
        for k, v in report.items():
            print(f"    {k:<30s}  {v}")

    print()


if __name__ == "__main__":
    _demo()
