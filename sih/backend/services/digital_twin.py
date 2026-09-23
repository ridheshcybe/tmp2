"""
AeroTwin Backend — Digital Twin Orchestration Service
======================================================

The central hub: takes a raw telemetry frame, runs it through
anomaly detection → fault classification → health index → RUL,
and produces the complete EngineState that the dashboard consumes.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.config import get_settings

# ML imports (safe — all degrade gracefully)
try:
    from ml.physics_baseline import expected_sensors, residual_summary
except ImportError:
    expected_sensors = None
    residual_summary = None

from backend.services.anomaly import get_anomaly_service
from backend.services.fault_prediction import get_fault_service
from backend.services.health_index import get_health_service
from backend.services.rul import get_rul_service


class DigitalTwinService:
    """Orchestrates the full analysis pipeline for each telemetry frame."""

    def __init__(self) -> None:
        self._anomaly_svc = get_anomaly_service()
        self._fault_svc = get_fault_service()
        self._health_svc = get_health_service()
        self._rul_svc = get_rul_service()
        self._frame_count = 0

    def process_frame(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        """
        Full pipeline: raw frame → EngineState dict.

        Args:
            frame: TelemetryFrame dict (from simulator or WebSocket)

        Returns:
            Complete engine state with all ML outputs
        """
        self._frame_count += 1
        t_start = time.monotonic()

        # Convert frame to flat CSV-keyed row for ML
        row = self._frame_to_row(frame)

        # 1. Physics expected values + residuals
        expected, residuals = self._compute_residuals(row)

        # 2. Anomaly detection + fault classification
        prediction = self._anomaly_svc.predict_row(row)

        # 3. Health index
        health_result = self._health_svc.compute(row, prediction)

        # 4. Fault prediction enrichment
        fault_result = self._fault_svc.predict(row, prediction)

        # 5. RUL estimation
        rul_result = self._rul_svc.estimate(row, prediction, health_result)

        # 6. Build alerts
        alerts = self._build_alerts(health_result, prediction, rul_result)

        # 7. Sensor status
        sensor_status, isolated = self._sensor_status(row)

        # 8. Assemble state
        state = {
            "engine_id": frame.get("engine_id", get_settings().ENGINE_ID),
            "mission_id": frame.get("mission_id"),
            "timestamp": frame.get("timestamp", datetime.now(timezone.utc).isoformat() + "Z"),
            "frame_id": frame.get("frame_id", self._frame_count),

            # Observed telemetry
            "observed": frame,

            # Physics model
            "expected": expected,
            "residuals": residuals,

            # Health
            "health_index": health_result.get("ehi", 100.0),
            "health_category": health_result.get("category", "NORMAL"),
            "health_trend": health_result.get("trend", "stable"),
            "health_delta_5min": health_result.get("delta_5min", 0.0),
            "health_confidence": health_result.get("confidence", "HIGH"),
            "health_explanation": health_result.get("explanation", []),
            "health_contributors": health_result.get("contributors", []),

            # Anomaly
            "anomaly_score": prediction.get("anomaly_score", 0.0),
            "is_anomaly": prediction.get("is_anomaly", False),

            # Fault
            "fault_class": fault_result.get("fault_class", "HEALTHY"),
            "fault_confidence": fault_result.get("confidence", 0.0),
            "fault_severity": fault_result.get("severity", 0.0),
            "fault_criticality": fault_result.get("criticality", 0.0),
            "fault_action": fault_result.get("action", ""),

            # RUL
            "rul_minutes": rul_result.get("rul_minutes"),
            "rul_lo": rul_result.get("rul_lo"),
            "rul_hi": rul_result.get("rul_hi"),
            "rul_confidence": rul_result.get("rul_confidence", "LOW"),
            "rul_trend": rul_result.get("rul_trend", "stable"),
            "rtb_alert": rul_result.get("rtb_alert", "NONE"),
            "rtb_window_active": rul_result.get("rtb_window_active", False),
            "progress_pct": rul_result.get("progress_pct", 100.0),

            # Sensors
            "sensor_status": sensor_status,
            "isolated_sensors": isolated,

            # Alerts
            "alerts": alerts,

            # Timing
            "processing_time_ms": round((time.monotonic() - t_start) * 1000, 2),
        }

        return state

    # ── Internal ──────────────────────────────────────────────────────────

    def _frame_to_row(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        """Convert API frame to flat CSV-keyed dict for ML."""
        cht = frame.get("cht", [0] * 4)
        egt = frame.get("egt", [0] * 4)
        return {
            "sim_time_s": frame.get("sim_time_s", 0.0),
            "phase": frame.get("phase", "CRUISE"),
            "throttle": frame.get("throttle", 0.0),
            "altitude_ft": frame.get("altitude_ft", 0.0),
            "ambient_temp_c": frame.get("ambient_temp_c", 15.0),
            "rpm": frame.get("rpm", 0.0),
            "fuel_flow_lph": frame.get("fuel_flow_lph", 0.0),
            "cht_c1": cht[0] if len(cht) > 0 else 0,
            "cht_c2": cht[1] if len(cht) > 1 else 0,
            "cht_c3": cht[2] if len(cht) > 2 else 0,
            "cht_c4": cht[3] if len(cht) > 3 else 0,
            "egt_c1": egt[0] if len(egt) > 0 else 0,
            "egt_c2": egt[1] if len(egt) > 1 else 0,
            "egt_c3": egt[2] if len(egt) > 2 else 0,
            "egt_c4": egt[3] if len(egt) > 3 else 0,
            "oil_pressure_kpa": frame.get("oil_pressure_kpa", 0),
            "oil_temp_c": frame.get("oil_temp_c", 15),
            "vibration_rms_g": frame.get("vibration_rms", frame.get("vibration_rms_g", 0)),
            "battery_v": frame.get("battery_voltage", frame.get("battery_v", 12.5)),
            "alternator_a": frame.get("alternator_current", frame.get("alternator_a", 0)),
            "injection_timing_deg": frame.get("injection_timing", frame.get("injection_timing_deg", 24)),
            "faults_active": frame.get("injected_fault", ""),
            "fault_severity": frame.get("fault_severity", 0.0),
        }

    def _compute_residuals(self, row: Dict[str, Any]) -> tuple:
        """Compute physics expected values and residuals."""
        if expected_sensors is None or residual_summary is None:
            return {}, []

        try:
            exp = expected_sensors(row)
            res = residual_summary(row)

            residuals_list = []
            for key, val in res.items():
                if key in ("r_oil_t",):  # excluded from penalty
                    continue
                unit = ""
                if "egt" in key or "cht" in key:
                    unit = "°C"
                elif "fuel" in key:
                    unit = "l/h"
                elif "oil_p" in key:
                    unit = "kPa"
                elif "vib" in key:
                    unit = "g"
                elif "batt" in key:
                    unit = "V"
                elif "alt" in key:
                    unit = "A"

                residuals_list.append({
                    "channel": key,
                    "residual": round(float(val), 2),
                    "unit": unit,
                })

            return exp, residuals_list
        except Exception:
            return {}, []

    def _build_alerts(
        self,
        health: Dict[str, Any],
        prediction: Dict[str, Any],
        rul: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        alerts = []
        ehi = health.get("ehi", 100)
        cls = prediction.get("fault_class", "HEALTHY")
        rul_min = rul.get("rul_minutes")
        rtb = rul.get("rtb_alert", "NONE")

        if ehi < 50:
            alerts.append({"level": "CRITICAL", "message": f"Health index critical: {ehi:.0f}/100", "type": "HEALTH"})
        elif ehi < 70:
            alerts.append({"level": "ADVISORY", "message": f"Health index degraded: {ehi:.0f}/100", "type": "HEALTH"})

        if cls != "HEALTHY" and prediction.get("confidence", 0) > 0.5:
            alerts.append({
                "level": "WARNING" if prediction.get("severity", 0) < 0.7 else "CRITICAL",
                "message": f"Fault: {cls} (P={prediction['confidence']:.2f})",
                "type": "FAULT",
            })

        if rtb == "RTB_CRITICAL":
            alerts.append({"level": "CRITICAL", "message": f"RTB CRITICAL — RUL: {rul_min:.0f} min", "type": "RTB"})
        elif rtb == "RTB_ADVISORY":
            alerts.append({"level": "ADVISORY", "message": f"RTB Advisory — RUL: {rul_min:.0f} min", "type": "RTB"})

        return alerts

    def _sensor_status(self, row: Dict[str, Any]) -> tuple:
        """Determine per-sensor health."""
        status = {}
        isolated = []
        for ch in ["rpm", "fuel_flow_lph", "cht_c1", "cht_c2", "cht_c3", "cht_c4",
                     "egt_c1", "egt_c2", "egt_c3", "egt_c4", "oil_pressure_kpa",
                     "oil_temp_c", "vibration_rms_g", "battery_v", "alternator_a"]:
            val = row.get(ch)
            ok = val is not None and str(val) not in ("", "nan", "None")
            status[ch] = ok
            if not ok:
                isolated.append(ch)
        return status, isolated


_twin_service: Optional[DigitalTwinService] = None


def get_digital_twin_service() -> DigitalTwinService:
    global _twin_service
    if _twin_service is None:
        _twin_service = DigitalTwinService()
    return _twin_service
