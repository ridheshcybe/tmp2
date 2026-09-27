"""
AeroTwin Backend — RUL Estimation Service
===========================================

Remaining Useful Life estimation using tree-ensemble variance
for confidence intervals. Falls back to severity-slope extrapolation.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class RULService:
    """RUL estimation + RTB (Return-to-Base) alert logic."""

    # RTB thresholds (minutes)
    RTB_CRITICAL_MIN = 10.0
    RTB_ADVISORY_MIN = 30.0
    MISSION_ENDURANCE_MIN = 180.0  # for progress bar

    def __init__(self) -> None:
        self._last_severity: Optional[float] = None
        self._last_time: Optional[float] = None

    def estimate(
        self,
        row: Dict[str, Any],
        prediction: Dict[str, Any],
        health_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Estimate RUL and RTB alert level.

        Returns:
            Dict with rul_minutes, rul_lo, rul_hi, rul_confidence,
            rtb_alert, rul_trend, progress_pct
        """
        # Extract RUL from ML pipeline
        rul_min = prediction.get("rul_min")
        rul_lo = prediction.get("rul_lo")
        rul_hi = prediction.get("rul_hi")
        rul_conf = prediction.get("rul_conf", 0.0)

        # Fallback: slope-based extrapolation
        if rul_min is None:
            rul_min = self._slope_rul(prediction)

        # Confidence label
        if rul_conf > 0.7:
            conf_label = "HIGH"
        elif rul_conf > 0.4:
            conf_label = "MEDIUM"
        else:
            conf_label = "LOW"

        # RTB alert
        rtb = "NONE"
        if rul_min is not None:
            if rul_min <= self.RTB_CRITICAL_MIN:
                rtb = "RTB_CRITICAL"
            elif rul_min <= self.RTB_ADVISORY_MIN:
                rtb = "RTB_ADVISORY"

        # Progress percentage
        progress = 100.0
        if rul_min is not None:
            progress = max(0.0, min(100.0, (rul_min / self.MISSION_ENDURANCE_MIN) * 100.0))

        # Trend from health index
        trend = health_result.get("trend", "stable")

        return {
            "rul_minutes": round(rul_min, 1) if rul_min is not None else None,
            "rul_lo": round(rul_lo, 1) if rul_lo is not None else None,
            "rul_hi": round(rul_hi, 1) if rul_hi is not None else None,
            "rul_confidence": conf_label,
            "rul_trend": trend,
            "rtb_alert": rtb,
            "rtb_window_active": rtb != "NONE",
            "progress_pct": round(progress, 1),
        }

    def _slope_rul(self, prediction: Dict[str, Any]) -> Optional[float]:
        """Simple severity-slope extrapolation fallback."""
        severity = float(prediction.get("severity", 0.0))
        t = prediction.get("sim_time_s")

        if t is None:
            return None

        if self._last_severity is not None and self._last_time is not None and t > self._last_time:
            dt_min = (t - self._last_time) / 60.0
            if dt_min > 0:
                rate = (severity - self._last_severity) / dt_min
                if rate > 1e-4:
                    rul = max(0.0, (0.9 - severity) / rate)
                    self._last_severity = severity
                    self._last_time = t
                    return rul

        self._last_severity = severity
        self._last_time = t
        return None


_rul_service: Optional[RULService] = None


def get_rul_service() -> RULService:
    global _rul_service
    if _rul_service is None:
        _rul_service = RULService()
    return _rul_service
