"""
AeroTwin Backend — Fault Injection Routes
===========================================

POST /api/faults/inject  — Inject a fault
POST /api/faults/clear   — Clear all faults
GET  /api/faults/types   — List available fault types
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from backend.models import FaultInjectionRequest

router = APIRouter(prefix="/api/faults", tags=["Faults"])


@router.post("/inject")
async def inject_fault(body: FaultInjectionRequest) -> Dict[str, Any]:
    """
    Inject a fault into the running simulation.

    The fault affects telemetry values according to the physics model
    and triggers fault detection in the ML pipeline.
    """
    import backend.database as db
    from backend.services.simulator import get_simulator
    from datetime import datetime

    sim = get_simulator()
    if not sim.is_running:
        raise HTTPException(status_code=400, detail="No mission running — start a mission first")

    sim.inject_fault(
        fault_type=body.fault_type.value,
        severity=body.severity,
        target_sensor=body.target_sensor,
    )

    # Log to DB
    await db.log_fault_injection(
        mission_id=sim.mission_id,
        fault_type=body.fault_type.value,
        severity=body.severity,
        target_sensor=body.target_sensor,
    )

    # Broadcast notification via WebSocket
    try:
        from backend.websocket_handler import broadcast_message
        await broadcast_message({
            "type": "FAULT_INJECTED",
            "payload": {
                "fault_type": body.fault_type.value,
                "severity": body.severity,
                "mission_id": sim.mission_id,
            },
        })
    except Exception:
        pass

    return {
        "fault_type": body.fault_type.value,
        "severity": body.severity,
        "injected_at": datetime.utcnow().isoformat() + "Z",
        "mission_id": sim.mission_id,
    }


@router.post("/clear")
async def clear_faults() -> Dict[str, Any]:
    """Clear all injected faults and return to nominal operation."""
    from backend.services.simulator import get_simulator
    sim = get_simulator()
    sim.clear_faults()

    try:
        from backend.websocket_handler import broadcast_message
        await broadcast_message({
            "type": "FAULTS_CLEARED",
            "payload": {"mission_id": sim.mission_id},
        })
    except Exception:
        pass

    return {"status": "cleared", "mission_id": sim.mission_id}


@router.get("/types")
async def list_fault_types() -> Dict[str, Any]:
    """List all available fault types with their metadata."""
    from backend.services.fault_prediction import get_fault_service
    svc = get_fault_service()
    return {"fault_types": svc.get_all_fault_types()}
