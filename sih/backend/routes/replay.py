"""
AeroTwin Backend — Replay Routes
==================================

POST /api/replay/start  — Start replaying a mission
POST /api/replay/stop   — Stop replay
GET  /api/replay/status — Current replay status
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from backend.models import ReplayRequest

router = APIRouter(prefix="/api/replay", tags=["Replay"])


@router.post("/start")
async def start_replay(body: ReplayRequest) -> Dict[str, Any]:
    """
    Start replaying a past mission.

    Streams stored telemetry frames at the specified speed.
    """
    import backend.database as db
    from backend.services.replay import get_replay_service

    mission = await db.get_mission(body.mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail=f"Mission {body.mission_id} not found")

    replay = get_replay_service()
    if replay.is_running:
        await replay.stop()

    # We'll return the initial batch; full streaming is via WebSocket
    frames = await db.get_replay_frames(
        body.mission_id,
        start_s=body.start_s,
        end_s=body.end_s,
        limit=10000,
    )

    return {
        "mission_id": body.mission_id,
        "frame_count": len(frames),
        "speed": body.speed,
        "status": "ready",
        "message": f"Loaded {len(frames)} frames. Connect to WS for streaming.",
    }


@router.get("/frames/{mission_id}")
async def get_replay_frames(
    mission_id: str,
    start_s: Optional[float] = None,
    end_s: Optional[float] = None,
    limit: int = 5000,
) -> Dict[str, Any]:
    """
    Get replay frames for a mission (HTTP fallback for non-WS clients).
    """
    import backend.database as db

    frames = await db.get_replay_frames(
        mission_id, start_s=start_s, end_s=end_s, limit=limit,
    )
    return {
        "mission_id": mission_id,
        "count": len(frames),
        "data": frames,
    }


@router.get("/status")
async def get_replay_status() -> Dict[str, Any]:
    """Get current replay status."""
    from backend.services.replay import get_replay_service
    replay = get_replay_service()
    return {
        "is_running": replay.is_running,
        "mission_id": replay.mission_id if replay.is_running else None,
        "speed": replay._speed if replay.is_running else 1.0,
    }
