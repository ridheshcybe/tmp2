"""
AeroTwin Backend — Report Routes
==================================

GET  /api/reports/{mission_id}             — Generate mission report
GET  /api/reports/{mission_id}/download     — Download report as JSON
GET  /api/reports/{mission_id}/download/csv — Download the recorded health log as CSV
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response

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


@router.get("/{mission_id}/download/csv")
async def download_mission_report_csv(mission_id: str) -> Response:
    """
    Download the mission's recorded health log as a CSV file.

    The UI's "download csv" button used to point at the JSON download, so the
    user asked for a CSV and received JSON.  This endpoint returns a real CSV,
    one row per recorded health snapshot.
    """
    import csv
    import io

    import backend.database as db

    mission = await db.get_mission(mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

    timeline = await db.get_health_timeline(mission_id)

    columns = [
        "sim_time_s",
        "health_index",
        "health_category",
        "anomaly_score",
        "is_anomaly",
        "fault_class",
        "fault_confidence",
        "fault_severity",
        "rul_minutes",
        "rul_lo",
        "rul_hi",
        "rtb_alert",
        "explanation",
    ]

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in timeline:
        writer.writerow({key: row.get(key) for key in columns})

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=report_{mission_id[:8]}.csv",
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
