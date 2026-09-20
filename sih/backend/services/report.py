"""
AeroTwin Backend — Report Generation Service
==============================================

Generates post-mission summary reports with health timeline,
anomaly events, fault predictions, and maintenance advisories.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import backend.database as db


class ReportService:
    """Generate exportable mission reports."""

    def __init__(self) -> None:
        pass

    async def generate(self, mission_id: str) -> Optional[Dict[str, Any]]:
        """Generate a full mission report."""
        mission = await db.get_mission(mission_id)
        if mission is None:
            return None

        stats = await db.get_mission_stats(mission_id)
        health_timeline = await db.get_health_timeline(mission_id)

        # Extract key events
        anomaly_events = [
            h for h in health_timeline if h.get("is_anomaly")
        ]
        fault_events = [
            h for h in health_timeline
            if h.get("fault_class") and h.get("fault_class") != "HEALTHY"
        ]
        rul_events = [
            h for h in health_timeline if h.get("rul_minutes") is not None
        ]

        # Build executive summary
        summary = self._build_summary(mission, stats, anomaly_events, fault_events)

        # Maintenance advisories
        advisories = self._build_advisories(stats, fault_events)

        # Sensor summary
        sensor_summary = self._build_sensor_summary(health_timeline)

        return {
            "mission": mission,
            "executive_summary": summary,
            "health_timeline": health_timeline[:500],  # downsample for export
            "anomaly_events": anomaly_events,
            "fault_predictions": fault_events,
            "rul_timeline": rul_events[:500],
            "maintenance_advisories": advisories,
            "sensor_summary": sensor_summary,
            "environmental_summary": {
                "mission_duration_s": mission.get("duration_s", 0),
                "ambient_offset_c": mission.get("ambient_offset_c", 0),
            },
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }

    def _build_summary(
        self,
        mission: Dict[str, Any],
        stats: Dict[str, Any],
        anomaly_events: List,
        fault_events: List,
    ) -> str:
        lines = [
            f"Mission Report: {mission.get('name', mission.get('mission_id', 'Unknown'))}",
            f"Engine: {mission.get('engine_id', 'N/A')}",
            f"Duration: {mission.get('duration_s', 0)} seconds",
            f"Status: {mission.get('status', 'N/A')}",
            "",
            "Summary:",
            f"  • Total telemetry frames: {stats.get('frame_count', 0)}",
            f"  • Average health index: {stats.get('avg_health', 0):.1f}/100",
            f"  • Minimum health index: {stats.get('min_health', 0):.1f}/100",
            f"  • Anomaly events detected: {stats.get('anomaly_count', 0)}",
            f"  • Fault classes observed: {len(stats.get('fault_distribution', {}))}",
        ]

        if fault_events:
            lines.append("")
            lines.append("Faults Detected:")
            for fe in fault_events[:5]:
                lines.append(
                    f"  • {fe.get('fault_class', 'N/A')} "
                    f"(confidence: {fe.get('fault_confidence', 0):.2f}, "
                    f"severity: {fe.get('fault_severity', 0):.2f})"
                )

        if stats.get("min_rul") is not None:
            lines.append(f"\n  • Minimum RUL: {stats['min_rul']:.1f} minutes")

        return "\n".join(lines)

    def _build_advisories(
        self, stats: Dict[str, Any], fault_events: List
    ) -> List[Dict[str, Any]]:
        advisories = []
        dist = stats.get("fault_distribution", {})

        if dist.get("LUBRICATION_FAILURE", 0) > 0:
            advisories.append({
                "priority": "CRITICAL",
                "action": "Inspect oil pump, filter and for leaks immediately.",
                "reason": "Lubrication failure events detected.",
            })
        if dist.get("OVERHEATING", 0) > 0:
            advisories.append({
                "priority": "HIGH",
                "action": "Check cooling system, baffles and oil cooler.",
                "reason": "Overheating events detected.",
            })
        if dist.get("INJECTOR_DEGRADATION", 0) > 0:
            advisories.append({
                "priority": "MEDIUM",
                "action": "Inspect injectors and fuel delivery system.",
                "reason": "Injector degradation detected.",
            })
        if dist.get("ABNORMAL_VIBRATION", 0) > 0:
            advisories.append({
                "priority": "MEDIUM",
                "action": "Inspect engine mounts and propeller balance.",
                "reason": "Abnormal vibration patterns detected.",
            })

        if not advisories:
            advisories.append({
                "priority": "LOW",
                "action": "No specific maintenance required. Continue standard inspection schedule.",
                "reason": "No significant faults detected during mission.",
            })

        return advisories

    def _build_sensor_summary(self, health_timeline: List[Dict]) -> Dict[str, Any]:
        if not health_timeline:
            return {"total_snapshots": 0}

        fault_classes = {}
        for h in health_timeline:
            fc = h.get("fault_class", "HEALTHY")
            fault_classes[fc] = fault_classes.get(fc, 0) + 1

        return {
            "total_snapshots": len(health_timeline),
            "fault_class_distribution": fault_classes,
            "avg_health_index": sum(h.get("health_index", 0) for h in health_timeline) / len(health_timeline),
        }


_report_service: Optional[ReportService] = None


def get_report_service() -> ReportService:
    global _report_service
    if _report_service is None:
        _report_service = ReportService()
    return _report_service
