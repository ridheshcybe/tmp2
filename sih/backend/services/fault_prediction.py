"""
AeroTwin Backend — Fault Prediction Service
=============================================

Wraps the ML classifier for fault class + probability.
Falls back to physics-residual rules.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Actions per fault class (from ml.inference)
ACTIONS = {
    "INJECTOR_DEGRADATION": "Inspect injector / fuel delivery on the affected cylinder; avoid high-throttle operation.",
    "MISFIRE": "Check spark plug, ignition lead and injector on the misfiring cylinder.",
    "LUBRICATION_FAILURE": "Inspect oil pump, filter and for leaks; monitor oil pressure — do not continue endurance ops.",
    "OVERHEATING": "Check cooling airflow, baffles and oil cooler; reduce power and descend if CHT keeps climbing.",
    "SENSOR_DRIFT": "Verify sensor calibration / wiring; treat readings as advisory until replaced.",
    "SENSOR_DROPOUT": "Sensor channel is frozen — replace sensor or check connector.",
    "ABNORMAL_VIBRATION": "Inspect engine mounts, propeller balance and accessories before next flight.",
    "ALTERNATOR_DEGRADATION": "Inspect alternator / regulator; battery is draining — plan early landing.",
}

CRITICALITY = {
    "HEALTHY": 0.0,
    "LUBRICATION_FAILURE": 1.0,
    "OVERHEATING": 0.90,
    "MISFIRE": 0.75,
    "ABNORMAL_VIBRATION": 0.70,
    "INJECTOR_DEGRADATION": 0.65,
    "ALTERNATOR_DEGRADATION": 0.50,
    "SENSOR_DRIFT": 0.35,
    "SENSOR_DROPOUT": 0.30,
    "UNKNOWN": 0.50,
}


class FaultPredictionService:
    """Fault classification + maintenance recommendations."""

    def __init__(self) -> None:
        pass

    def predict(self, row: Dict[str, Any], prediction: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enrich a prediction dict with fault-specific info.

        Args:
            row: Raw telemetry row
            prediction: Output from anomaly_service.predict()

        Returns:
            Dict with fault_class, confidence, severity, action, criticality
        """
        cls = prediction.get("fault_class", "HEALTHY")
        confidence = float(prediction.get("confidence", 0.0))
        severity = float(prediction.get("severity", 0.0))

        return {
            "fault_class": cls,
            "confidence": confidence,
            "severity": severity,
            "criticality": CRITICALITY.get(cls, 0.5),
            "action": ACTIONS.get(cls, "Inspect engine before next flight."),
            "low_confidence": bool(prediction.get("low_confidence", confidence < 0.6)),
        }

    def get_all_fault_types(self) -> List[Dict[str, Any]]:
        """Return all known fault types with metadata."""
        return [
            {"type": ft, "criticality": CRITICALITY.get(ft, 0.5),
             "action": ACTIONS.get(ft, "Inspect.")}
            for ft in CRITICALITY if ft != "HEALTHY"
        ]


_fault_service: Optional[FaultPredictionService] = None


def get_fault_service() -> FaultPredictionService:
    global _fault_service
    if _fault_service is None:
        _fault_service = FaultPredictionService()
    return _fault_service
