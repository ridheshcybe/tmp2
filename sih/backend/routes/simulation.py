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

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/simulation", tags=["Simulation"])


class ThrottleRequest(BaseModel):
    throttle: float = Field(..., ge=0.0, le=1.0)


class AltitudeRequest(BaseModel):
    altitude_ft: float = Field(..., ge=0.0, le=45000)


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
        "hz": sim._hz,
        "active_faults": list(sim._active_faults.keys()) if sim.is_running else [],
    }


@router.post("/throttle")
async def set_throttle(body: ThrottleRequest) -> Dict[str, Any]:
    """Override the simulator throttle for interactive demo."""
    from backend.services.simulator import get_simulator
    sim = get_simulator()
    if not sim.is_running:
        raise HTTPException(status_code=400, detail="No mission running")
    sim.set_throttle(body.throttle)
    return {"throttle": body.throttle, "status": "set"}


@router.post("/altitude")
async def set_altitude(body: AltitudeRequest) -> Dict[str, Any]:
    """Override the simulator altitude for interactive demo."""
    from backend.services.simulator import get_simulator
    sim = get_simulator()
    if not sim.is_running:
        raise HTTPException(status_code=400, detail="No mission running")
    sim.set_altitude(body.altitude_ft)
    return {"altitude_ft": body.altitude_ft, "status": "set"}
