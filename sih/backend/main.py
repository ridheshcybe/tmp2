"""
AeroTwin Backend — FastAPI Application
========================================

Entry point for the Python backend API server.

Startup:
    uvicorn main:app --host 0.0.0.0 --port 8081 --reload

Or:
    python main.py
"""

from __future__ import annotations

import logging
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import get_settings

# ══════════════════════════════════════════════════════════════════════════════
#  Logging Setup
# ══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("aerotwin")


# ══════════════════════════════════════════════════════════════════════════════
#  Lifespan (startup / shutdown)
# ══════════════════════════════════════════════════════════════════════════════

_start_time: float = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — init DB, log startup, cleanup on shutdown."""
    global _start_time
    _start_time = time.time()

    settings = get_settings()
    logger.info("═══════════════════════════════════════════════════════════════")
    logger.info("  AeroTwin Digital Twin API — FastAPI Backend")
    logger.info(f"  Version: {settings.APP_VERSION}")
    logger.info(f"  Port:    {settings.PORT}")
    logger.info(f"  Models:  {settings.MODEL_DIR}")
    logger.info("═══════════════════════════════════════════════════════════════")

    # Initialize database
    try:
        import backend.database as db
        await db.init_db()
        logger.info("✓ SQLite database initialized")
    except Exception as e:
        logger.error(f"✗ Database init failed: {e}")

    # Pre-initialize ML services
    try:
        from services.anomaly import get_anomaly_service
        from services.health_index import get_health_service
        get_anomaly_service()
        get_health_service()
        logger.info("✓ ML services initialized")
    except Exception as e:
        logger.warning(f"⚠ ML services init warning: {e}")

    logger.info("✓ Backend ready")

    yield

    # Shutdown
    logger.info("Shutting down...")
    try:
        from services.simulator import get_simulator
        sim = get_simulator()
        if sim.is_running:
            await sim.stop()
    except Exception:
        pass
    try:
        from backend.database import flush_telemetry, close_db
        await flush_telemetry()
        await close_db()
    except Exception:
        pass
    logger.info("✓ Shutdown complete")


# ══════════════════════════════════════════════════════════════════════════════
#  FastAPI App
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="AeroTwin Digital Twin API",
    description=(
        "AI-Enabled Real-Time Digital Twin for aero piston engine health "
        "monitoring, fault prediction and mission reliability. "
        "Prototype for SIH26054 / DRDO."
    ),
    version=get_settings().APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ══════════════════════════════════════════════════════════════════════════════
#  CORS
# ══════════════════════════════════════════════════════════════════════════════

settings = get_settings()
origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]

if "*" in origins:
    # Wildcard + allow_credentials is rejected by browsers — drop credentials.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Telemetry frames + health timelines are JSON-heavy; compress on the wire.
app.add_middleware(GZipMiddleware, minimum_size=1024)


# ══════════════════════════════════════════════════════════════════════════════
#  Exception Handlers
# ══════════════════════════════════════════════════════════════════════════════

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    # Full detail goes to the logs only — leaking str(exc) to clients can
    # expose filesystem paths, SQL fragments and library internals.
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "status_code": 500,
        },
    )


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={"error": "Not found", "detail": str(exc), "status_code": 404},
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Routes — Register all routers
# ══════════════════════════════════════════════════════════════════════════════

from backend.routes.engine import router as engine_router
from backend.routes.mission import router as mission_router
from backend.routes.faults import router as faults_router
from backend.routes.replay import router as replay_router
from backend.routes.reports import router as reports_router
from backend.routes.simulation import router as simulation_router

app.include_router(engine_router)
app.include_router(mission_router)
app.include_router(faults_router)
app.include_router(replay_router)
app.include_router(reports_router)
app.include_router(simulation_router)


# ══════════════════════════════════════════════════════════════════════════════
#  Root & Health Endpoints
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
async def health_check() -> Dict[str, Any]:
    uptime = time.time() - _start_time

    # Check ML models
    ml_status = "unknown"
    try:
        from pathlib import Path
        model_dir = Path(settings.MODEL_DIR)
        if (model_dir / "bundle.json").exists():
            ml_status = "loaded"
        else:
            ml_status = "fallback"
    except Exception:
        ml_status = "error"

    # Check simulator
    sim_running = False
    try:
        from services.simulator import get_simulator
        sim_running = get_simulator().is_running
    except Exception:
        pass

    # Check WS clients
    ws_count = 0
    try:
        from backend.websocket_handler import get_manager
        ws_count = get_manager().count
    except Exception:
        pass

    # Check database (real connectivity probe, not just "it's sqlite")
    db_status = "unknown"
    try:
        import backend.database as _db
        conn = _db.get_db()
        await conn.execute("SELECT 1")
        db_status = "ok"
    except Exception:
        db_status = "error"

    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "uptime_s": round(uptime, 1),
        "components": {
            "ml_models": ml_status,
            "simulator": "running" if sim_running else "idle",
            "websocket_clients": ws_count,
            "database": db_status,
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
#  WebSocket Route
# ══════════════════════════════════════════════════════════════════════════════

from fastapi import WebSocket as _WS

@app.websocket("/ws/telemetry/{engine_id}")
async def websocket_endpoint(ws: _WS, engine_id: str):
    """
    WebSocket endpoint for real-time telemetry streaming.

    Connect from the React dashboard to receive live engine state
    updates at the simulation Hz rate.
    """
    from backend.websocket_handler import ws_handler
    await ws_handler(ws)


# ══════════════════════════════════════════════════════════════════════════════
#  Request Logging Middleware
# ══════════════════════════════════════════════════════════════════════════════

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    elapsed = (time.time() - start) * 1000
    if elapsed > 100:  # only log slow requests
        logger.warning(f"Slow request: {request.method} {request.url.path} — {elapsed:.0f}ms")
    return response


# ══════════════════════════════════════════════════════════════════════════════
#  Direct Run
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
#  Serve the standalone dashboard from this same origin (cloud deploys and local)
#  Serve the standalone dashboard from this same origin by default (cloud
#  deploys and local). Set AEROTWIN_SERVE_FRONTEND=0 to disable explicitly.
#  Mounted last so /api and /ws routes registered above always win.
# ══════════════════════════════════════════════════════════════════════════════

import os as _os

_serve_frontend = _os.environ.get("AEROTWIN_SERVE_FRONTEND", "").strip()

if _serve_frontend != "0":
    from pathlib import Path as _Path

    _frontend_dir = _Path(
        _os.environ.get(
            "AEROTWIN_FRONTEND_DIR",
            str(_Path(__file__).resolve().parents[2] / "src" / "frontend"),
        )
    )
    if _frontend_dir.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=str(_frontend_dir), html=True),
            name="dashboard",
        )
        logger.info(f"Serving dashboard from {_frontend_dir}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
    )
