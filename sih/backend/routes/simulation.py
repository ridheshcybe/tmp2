"""
AeroTwin Backend — Simulation Routes
======================================

POST /api/simulation/start   — Start simulation (alias for mission start)
POST /api/simulation/stop    — Stop simulation
POST /api/simulation/throttle — Override throttle
POST /api/simulation/altitude — Override altitude
GET  /api/simulation/status   — Get simulation status
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/simulation", tags=["Simulation"])


class SimulationStartRequest(BaseModel):
    """Request to start the simulation (mission-start alias)."""

    engine_id: str = "TAPAS-BH-201-001"
    name: Optional[str] = None
    duration_s: int = 600
    ambient_offset_c: float = 0.0
    profile: str = Field(default="default", pattern="^(default|test_flight|manual)$")


class ThrottleRequest(BaseModel):
    throttle: float = Field(..., ge=0.0, le=1.0)


class AltitudeRequest(BaseModel):
    altitude_ft: float = Field(..., ge=0.0, le=45000)


async def _ensure_running(profile: str = "manual") -> Any:
    """Guarantee a mission is running before an interactive override.

    The dashboard's manual throttle (and the phone controller) must work
    the moment a page is opened, without the user having to start a
    mission first: if nothing is running, start an idle-parked
    ``manual`` session - the engine holds ground idle until the override
    commands it from the next tick.
    """
    from backend.services.simulator import get_simulator

    sim = get_simulator()
    if sim.is_running:
        return sim

    from backend.models import MissionCreate
    from backend.routes.mission import start_mission

    await start_mission(
        MissionCreate(
            engine_id="TAPAS-BH-201-001",
            name="Interactive session",
            duration_s=3600,
            profile=profile,
        )
    )
    sim = get_simulator()
    if not sim.is_running:
        raise HTTPException(status_code=500, detail="Simulation failed to start")
    return sim


@router.get("/status")
async def get_simulation_status() -> Dict[str, Any]:
    """Get current simulation status."""
    from backend.services.simulator import get_simulator
    sim = get_simulator()
    return {
        "is_running": sim.is_running,
        "mission_id": sim.mission_id if sim.is_running else None,
        "frame_id": sim.frame_id,
        "sim_time_s": sim.sim_time,
        "phase": sim.current_phase if sim.is_running else None,
        "profile": sim._profile_name if sim.is_running else None,
        "throttle": sim.current_throttle,
        "throttle_manual": sim.throttle_is_manual,
        "hz": sim._hz,
        "active_faults": list(sim._active_faults.keys()) if sim.is_running else [],
    }


@router.post("/throttle")
async def set_throttle(body: ThrottleRequest) -> Dict[str, Any]:
    """Override the simulator throttle for interactive demo.

    Auto-starts an interactive session when no mission is running, so the
    dashboard slider and the phone controller work immediately.
    """
    sim = await _ensure_running()
    sim.set_throttle(body.throttle)
    return {
        "throttle": body.throttle,
        "status": "set",
        "mission_id": sim.mission_id,
        "auto_started": True,
    }


@router.post("/throttle/release")
async def release_throttle() -> Dict[str, Any]:
    """Hand throttle control back to the mission profile."""
    from backend.services.simulator import get_simulator

    sim = get_simulator()
    if not sim.is_running:
        raise HTTPException(status_code=400, detail="No mission running")
    sim.release_throttle()
    return {"status": "released"}


@router.post("/start")
async def start_simulation(body: SimulationStartRequest) -> Dict[str, Any]:
    """Start the simulation — the same machinery as mission start."""
    from backend.models import MissionCreate
    from backend.routes.mission import start_mission

    return await start_mission(
        MissionCreate(
            engine_id=body.engine_id,
            name=body.name,
            duration_s=body.duration_s,
            ambient_offset_c=body.ambient_offset_c,
            profile=body.profile,
        )
    )


@router.post("/stop")
async def stop_simulation() -> Dict[str, Any]:
    """Stop the running simulation and mark its mission COMPLETED."""
    from datetime import datetime, timezone

    import backend.database as db
    from backend.database import flush_telemetry
    from backend.services.simulator import get_simulator

    sim = get_simulator()
    mission_id = sim.mission_id if sim.is_running else None
    if not mission_id:
        return {"mission_id": None, "status": "NOT_RUNNING"}

    await sim.stop()
    await flush_telemetry()
    await db.update_mission(
        mission_id,
        status="COMPLETED",
        ended_at=datetime.now(timezone.utc).isoformat() + "Z",
    )
    return {"mission_id": mission_id, "status": "COMPLETED"}


@router.post("/altitude")
async def set_altitude(body: AltitudeRequest) -> Dict[str, Any]:
    """Override the simulator altitude for interactive demo.

    Auto-starts an interactive session when no mission is running.
    """
    sim = await _ensure_running()
    sim.set_altitude(body.altitude_ft)
    return {
        "altitude_ft": body.altitude_ft,
        "status": "set",
        "mission_id": sim.mission_id,
        "auto_started": True,
    }
