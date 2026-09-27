"""
AeroTwin Backend — Anomaly Detection Service
==============================================

Wraps the ML inference pipeline for anomaly scoring.
Falls back to z-scored physics residuals when models are unavailable.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class AnomalyService:
    """Anomaly detection via Isolation Forest or rule-based fallback."""

    def __init__(self) -> None:
        self._pipeline = None
        self._init_pipeline()

    def _init_pipeline(self) -> None:
        try:
            from ml.inference import build_pipeline
            from backend.config import get_settings
            settings = get_settings()
            self._pipeline = build_pipeline(settings.MODEL_DIR)
        except Exception:
            self._pipeline = None

    def predict(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run anomaly detection + classification on one row.

        Returns dict with: anomaly_score, is_anomaly, fault_class,
        confidence, severity, rul_min, alert_level, etc.
        """
        if self._pipeline is not None:
            try:
                result = self._pipeline.predict(row)
                if result is None:
                    return self._warmup_result()
                return self._to_floats(result)
            except Exception as e:
                return self._fallback(row, error=str(e))
        return self._fallback(row)

    def predict_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Update + predict (for InferencePipeline with stateful feature extractor)."""
        if self._pipeline is not None and hasattr(self._pipeline, "predict_row"):
            try:
                result = self._pipeline.predict_row(row)
                return self._to_floats(result)
            except Exception as e:
                return self._fallback(row, error=str(e))
        return self.predict(row)

    def _to_floats(self, d: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure numpy types are JSON-serialisable."""
        import numpy as np
        out = {}
        for k, v in d.items():
            if isinstance(v, (np.floating, float)):
                out[k] = float(v)
            elif isinstance(v, (np.integer, int)):
                out[k] = int(v)
            elif isinstance(v, np.bool_):
                out[k] = bool(v)
            else:
                out[k] = v
        return out

    def _warmup_result(self) -> Dict[str, Any]:
        return {
            "sim_time_s": 0.0, "warmup": True,
            "anomaly_score": 0.0, "is_anomaly": False,
            "fault_class": "HEALTHY", "confidence": 0.0,
            "low_confidence": True, "severity": 0.0,
            "severity_conf": 0.0, "rul_min": None,
            "rul_lo": None, "rul_hi": None,
            "rul_conf": 0.0, "alert_level": "NONE",
        }

    def _fallback(self, row: Dict[str, Any], error: Optional[str] = None) -> Dict[str, Any]:
        """Rule-based fallback using physics residuals."""
        try:
            from ml.inference import FallbackAnalyzer
            if not hasattr(self, "_fallback_analyzer"):
                self._fallback_analyzer = FallbackAnalyzer()
            result = self._fallback_analyzer.predict(row)
            return self._to_floats(result)
        except Exception:
            # Ultra-minimal fallback
            rpm = float(row.get("rpm", 0))
            vib = float(row.get("vibration_rms_g", row.get("vibration_rms", 0)))
            anomaly_score = min(100.0, max(0.0, vib * 20 + (1.0 if rpm > 3000 else 0)))
            return {
                "anomaly_score": anomaly_score,
                "is_anomaly": anomaly_score > 50,
                "fault_class": "HEALTHY" if anomaly_score < 50 else "UNKNOWN",
                "confidence": 0.3,
                "low_confidence": True,
                "severity": 0.0,
                "severity_conf": 0.0,
                "rul_min": None, "rul_lo": None, "rul_hi": None,
                "rul_conf": 0.0,
                "alert_level": "NONE",
                "fallback": True,
            }


_anomaly_service: Optional[AnomalyService] = None


def get_anomaly_service() -> AnomalyService:
    global _anomaly_service
    if _anomaly_service is None:
        _anomaly_service = AnomalyService()
    return _anomaly_service
