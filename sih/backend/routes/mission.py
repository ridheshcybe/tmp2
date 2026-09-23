"""
AeroTwin Backend — Mission Routes
===================================

POST /api/missions/start     — Start a new mission
POST /api/missions/{id}/stop — Stop a mission
GET  /api/missions           — List all missions
GET  /api/missions/{id}      — Get mission details
GET  /api/missions/{id}/summary — Get mission summary
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from backend.config import get_settings
from backend.models import MissionCreate, MissionInfo

router = APIRouter(prefix="/api/missions", tags=["Missions"])


@router.post("/start")
async def start_mission(body: MissionCreate) -> Dict[str, Any]:
    """
    Start a new mission with telemetry simulation.

    Creates a mission record, starts the simulator, and begins
    streaming telemetry through the ML pipeline.
    """
    import backend.database as db
    from backend.services.simulator import get_simulator

    mission_id = str(uuid.uuid4())
    settings = get_settings()

    # Create DB record
    mission = await db.create_mission(
        mission_id=mission_id,
        engine_id=body.engine_id,
        name=body.name,
        duration_s=body.duration_s,
        ambient_offset_c=body.ambient_offset_c,
    )

    # Start simulator
    sim = get_simulator()

    # Fresh health-index state: a new mission runs a (healthy) engine, so it
    # must not inherit the previous mission's degraded EMA value.
    from backend.services.health_index import get_health_service
    get_health_service().reset()

    # Wire up frame processing pipeline
    from backend.services.digital_twin import get_digital_twin_service
    twin_svc = get_digital_twin_service()

    async def process_and_store(frame: Dict[str, Any]) -> None:
        """Process each frame: ML → DB → buffer for WS broadcast."""
        # Store telemetry
        await db.insert_telemetry(frame)

        # Process through ML pipeline
        state = twin_svc.process_frame(frame)

        # Store health snapshot
        await db.insert_health_snapshot({
            "mission_id": mission_id,
            "frame_id": frame["frame_id"],
            "sim_time_s": frame.get("sim_time_s", 0),
            "health_index": state.get("health_index"),
            "health_category": state.get("health_category"),
            "anomaly_score": state.get("anomaly_score"),
            "is_anomaly": state.get("is_anomaly"),
            "fault_class": state.get("fault_class"),
            "fault_confidence": state.get("fault_confidence"),
            "fault_severity": state.get("fault_severity"),
            "rul_minutes": state.get("rul_minutes"),
            "rul_lo": state.get("rul_lo"),
            "rul_hi": state.get("rul_hi"),
            "rtb_alert": state.get("rtb_alert"),
            "explanation": state.get("health_explanation"),
            "contributors": state.get("health_contributors"),
        })

        # Broadcast via WebSocket
        try:
            from backend.websocket_handler import broadcast_frame
            await broadcast_frame(state)
        except Exception:
            pass

    # Start the simulator FIRST — sim.start() clears stale callbacks from the
    # previous mission, so registering our frame callback must happen AFTER
    # it (registering before used to wipe the pipeline: no telemetry stored,
    # no ML processing, no WebSocket frames at all).
    await sim.start(
        mission_id=mission_id,
        duration_s=body.duration_s,
        ambient_offset_c=body.ambient_offset_c,
        profile=body.profile,
    )
    sim.on_frame(process_and_store)

    return {
        "mission_id": mission_id,
        "engine_id": body.engine_id,
        "status": "RUNNING",
        "duration_s": body.duration_s,
        "profile": body.profile,
        "started_at": mission["started_at"],
    }

@router.post("/{mission_id}/stop")
async def stop_mission(mission_id: str) -> Dict[str, Any]:
    """Stop a running mission."""
    import backend.database as db
    from datetime import datetime, timezone
    from backend.services.simulator import get_simulator
    from backend.database import flush_telemetry

    sim = get_simulator()
    if sim.mission_id == mission_id:
        await sim.stop()
        await flush_telemetry()
        await db.update_mission(
            mission_id,
            status="COMPLETED",
            ended_at=datetime.now(timezone.utc).isoformat() + "Z",
        )

    mission = await db.get_mission(mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

    # Report actual status — this endpoint used to always claim COMPLETED
    # even when it only read a mission that was already COMPLETED, RUNNING
    # or missing from the simulator entirely.
    return {"mission_id": mission_id, "status": mission["status"]}


@router.get("")
async def list_missions(limit: int = 50) -> Dict[str, Any]:
    """List all missions, newest first."""
    import backend.database as db
    limit = max(1, min(limit, 500))  # sanity clamp
    missions = await db.list_missions(limit=limit)
    return {"missions": missions, "count": len(missions)}


@router.get("/{mission_id}")
async def get_mission(mission_id: str) -> Dict[str, Any]:
    """Get detailed information about a specific mission."""
    import backend.database as db
    mission = await db.get_mission(mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
    stats = await db.get_mission_stats(mission_id)
    return {**mission, "stats": stats}


@router.get("/{mission_id}/summary")
async def get_mission_summary(mission_id: str) -> Dict[str, Any]:
    """Get a post-mission summary report."""
    from backend.services.report import get_report_service
    svc = get_report_service()
    report = await svc.generate(mission_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
    return report
