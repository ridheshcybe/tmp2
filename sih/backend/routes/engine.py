"""
AeroTwin Backend — Engine Routes
=================================

GET  /api/engine/{engine_id}/state     — Current digital twin state
GET  /api/engine/{engine_id}/telemetry — Recent telemetry history
GET  /api/engine/{engine_id}/health    — Current health index
GET  /api/engine/{engine_id}/faults    — Current fault predictions
GET  /api/engine/{engine_id}/rul       — Current RUL estimate
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.config import get_settings

router = APIRouter(prefix="/api/engine", tags=["Engine"])

# ── Cached latest state (avoids re-processing the same frame) ──────────────
_cached_state: Optional[Dict[str, Any]] = None
_cached_frame_id: int = -1


def _get_current_state() -> Optional[Dict[str, Any]]:
    """Get the latest engine state from the digital twin service."""
    global _cached_state, _cached_frame_id

    try:
        from backend.services.simulator import get_simulator
        from backend.services.digital_twin import get_digital_twin_service

        sim = get_simulator()
        if not sim.is_running or sim._last_frame is None:
            return None

        # Only re-process if a new frame has arrived
        frame_id = sim._last_frame.get("frame_id", -1)
        if _cached_state is not None and _cached_frame_id == frame_id:
            return _cached_state

        svc = get_digital_twin_service()
        _cached_state = svc.process_frame(sim._last_frame)
        _cached_frame_id = frame_id
        return _cached_state
    except Exception as e:
        print(f"[Engine] Error getting state: {e}")
        return None


@router.get("/{engine_id}/state")
async def get_engine_state(engine_id: str) -> Dict[str, Any]:
    """
    Get the current digital twin state for an engine.

    Returns the complete EngineState with observed telemetry,
    physics-expected values, residuals, health index, anomaly score,
    fault prediction, RUL, and alerts.
    """
    state = _get_current_state()
    if state is None:
        raise HTTPException(
            status_code=503,
            detail="Simulation not running or no telemetry available",
        )
    return state


@router.get("/{engine_id}/telemetry")
async def get_engine_telemetry(
    engine_id: str,
    # Clamp: the ring buffer holds _RECENT_LIMIT frames; an unbounded
    # ?limit=1000000000 used to serialize and ship all of it.
    limit: int = Query(100, ge=1, le=600),
) -> Dict[str, Any]:
    """
    Get recent telemetry history for an engine.

    Returns the last `limit` telemetry frames from the ring buffer.
    """
    try:
        from backend.services.simulator import get_simulator

        sim = get_simulator()
        if not sim._recent_frames:
            return {"engine_id": engine_id, "frames": [], "count": 0}

        frames: List[Dict[str, Any]] = list(sim._recent_frames)[-limit:]
        return {"engine_id": engine_id, "frames": frames, "count": len(frames)}
    except Exception:
        return {"engine_id": engine_id, "frames": [], "count": 0}


@router.get("/{engine_id}/health")
async def get_engine_health(engine_id: str) -> Dict[str, Any]:
    """
    Get current health index with full breakdown.

    Returns EHI score, category, trend, contributors, and explanation.
    """
    state = _get_current_state()
    if state is None:
        raise HTTPException(status_code=503, detail="Simulation not running")
    return {
        "engine_id": engine_id,
        "health_index": state.get("health_index", 100),
        "category": state.get("health_category", "NORMAL"),
        "trend": state.get("health_trend", "stable"),
        "delta_5min": state.get("health_delta_5min", 0),
        "confidence": state.get("health_confidence", "HIGH"),
        "contributors": state.get("health_contributors", []),
        "explanation": state.get("health_explanation", []),
    }


@router.get("/{engine_id}/faults")
async def get_engine_faults(engine_id: str) -> Dict[str, Any]:
    """Get current fault classification and prediction."""
    state = _get_current_state()
    if state is None:
        raise HTTPException(status_code=503, detail="Simulation not running")
    return {
        "engine_id": engine_id,
        "fault_class": state.get("fault_class", "HEALTHY"),
        "confidence": state.get("fault_confidence", 0),
        "severity": state.get("fault_severity", 0),
        "criticality": state.get("fault_criticality", 0),
        "action": state.get("fault_action", ""),
        "anomaly_score": state.get("anomaly_score", 0),
        "is_anomaly": state.get("is_anomaly", False),
    }


@router.get("/{engine_id}/rul")
async def get_engine_rul(engine_id: str) -> Dict[str, Any]:
    """Get current RUL estimate with confidence and RTB alert."""
    state = _get_current_state()
    if state is None:
        raise HTTPException(status_code=503, detail="Simulation not running")
    return {
        "engine_id": engine_id,
        "rul_minutes": state.get("rul_minutes"),
        "rul_lo": state.get("rul_lo"),
        "rul_hi": state.get("rul_hi"),
        "confidence": state.get("rul_confidence", "LOW"),
        "trend": state.get("rul_trend", "stable"),
        "rtb_alert": state.get("rtb_alert", "NONE"),
        "rtb_window_active": state.get("rtb_window_active", False),
        "progress_pct": state.get("progress_pct", 100),
    }
