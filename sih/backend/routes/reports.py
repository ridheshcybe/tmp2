"""
AeroTwin Backend — Report Routes
==================================

GET  /api/reports/{mission_id}          — Generate mission report
GET  /api/reports/{mission_id}/download — Download report as JSON
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/reports", tags=["Reports"])


@router.get("/{mission_id}")
async def get_mission_report(mission_id: str) -> Dict[str, Any]:
    """
    Generate a full mission report.

    Includes executive summary, health timeline, anomaly events,
    fault predictions, RUL timeline, and maintenance advisories.
    """
    from backend.services.report import get_report_service
    svc = get_report_service()
    report = await svc.generate(mission_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
    return report


@router.get("/{mission_id}/download")
async def download_mission_report(mission_id: str) -> JSONResponse:
    """Download mission report as a JSON file."""
    from backend.services.report import get_report_service
    import json

    svc = get_report_service()
    report = await svc.generate(mission_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

    return JSONResponse(
        content=report,
        headers={
            "Content-Disposition": f"attachment; filename=report_{mission_id[:8]}.json",
        },
    )


@router.get("/{mission_id}/health-timeline")
async def get_health_timeline(mission_id: str) -> Dict[str, Any]:
    """Get the full health index timeline for charting."""
    import backend.database as db
    timeline = await db.get_health_timeline(mission_id)
    return {
        "mission_id": mission_id,
        "count": len(timeline),
        "data": timeline,
    }
