"""
AeroTwin Backend — Health Index Service
========================================

Wraps the ML health index calculator with a streaming interface.
Accepts raw telemetry rows + inference predictions, produces a
smoothed EHI with explanation text.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.config import get_settings


class HealthIndexService:
    """Streaming health index calculator for the API layer."""

    def __init__(self) -> None:
        self._calc = None
        self._init_calculator()

    def _init_calculator(self) -> None:
        try:
            from ml.health_index import HealthIndexCalculator
            self._calc = HealthIndexCalculator()
        except ImportError:
            self._calc = None

    def compute(
        self,
        row: Dict[str, Any],
        prediction: Dict[str, Any],
        t: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Compute health index for one telemetry tick.

        Args:
            row: Raw telemetry row (CSV-keyed dict)
            prediction: ML inference output (fault_class, anomaly_score, etc.)
            t: Optional explicit timestamp

        Returns:
            Dict with ehi, category, contributors, explanation, etc.
        """
        if self._calc is None:
            return self._fallback(row, prediction)

        try:
            result = self._calc.update(row, prediction, t=t)
            return result
        except Exception as e:
            return self._fallback(row, prediction, error=str(e))

    def reset(self) -> None:
        """Reset smoothing history (call at mission start)."""
        if self._calc is not None:
            try:
                self._calc.reset()
            except Exception:
                pass

    def _fallback(
        self,
        row: Dict[str, Any],
        prediction: Dict[str, Any],
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Rule-based fallback when ML models are unavailable."""
        # Simple heuristic from anomaly score + fault severity
        anomaly = float(prediction.get("anomaly_score", 0))
        severity = float(prediction.get("severity", 0))
        fault_conf = float(prediction.get("confidence", 0))
        cls = prediction.get("fault_class", "HEALTHY")

        # Penalty terms
        p_anomaly = anomaly / 100.0
        p_fault = fault_conf * severity if cls != "HEALTHY" else 0.0
        p_severity = severity

        ehi = max(0.0, min(100.0, 100.0 * (1.0 - 0.4 * p_anomaly - 0.35 * p_fault - 0.25 * p_severity)))

        category = "NORMAL"
        if ehi < 30:
            category = "EMERGENCY"
        elif ehi < 50:
            category = "CRITICAL"
        elif ehi < 70:
            category = "WARNING"
        elif ehi < 85:
            category = "WATCH"

        contributors = []
        if p_anomaly > 0.05:
            contributors.append({"component": "anomaly", "penalty": round(p_anomaly, 3),
                                 "label": f"Anomaly score {anomaly:.0f}/100"})
        if p_fault > 0.05:
            contributors.append({"component": "fault", "penalty": round(p_fault, 3),
                                 "label": f"{cls} P={fault_conf:.2f}"})
        if p_severity > 0.05:
            contributors.append({"component": "degradation", "penalty": round(p_severity, 3),
                                 "label": f"Severity {severity:.2f}"})

        explanation = [f"Health Index: {ehi:.0f}/100 · {category}"]
        if contributors:
            explanation.append("Main contributors:")
            for c in contributors[:3]:
                explanation.append(f"  – {c['label']}")
        if error:
            explanation.append(f"(fallback mode: {error})")

        return {
            "ehi": round(ehi, 1),
            "raw": round(ehi, 1),
            "category": category,
            "alert_level": "CRITICAL" if ehi < 50 else ("ADVISORY" if ehi < 70 else "WATCH" if ehi < 85 else "NONE"),
            "trend": "stable",
            "delta_5min": 0.0,
            "penalties": {"residual": 0.0, "anomaly": round(p_anomaly, 3), "fault": round(p_fault, 3),
                          "degradation": round(p_severity, 3), "sensor": 0.0},
            "weights_used": {"residual": 0.25, "anomaly": 0.20, "fault": 0.25, "degradation": 0.20, "sensor": 0.10},
            "data_quality": {"fraction_valid": 1.0, "stale": False, "bad_channels": []},
            "confidence": "MEDIUM",
            "contributors": contributors,
            "explanation": explanation,
        }


# Singleton
_health_service: Optional[HealthIndexService] = None


def get_health_service() -> HealthIndexService:
    global _health_service
    if _health_service is None:
        _health_service = HealthIndexService()
    return _health_service
