"""
AeroTwin Backend — API Integration Tests
==========================================

Run:  cd backend && python -m pytest tests/ -v

Or:   cd backend && python tests/test_api.py
"""

from __future__ import annotations

import sys
import os
import asyncio
import json

# Ensure backend is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ASGITransport does not run the app's lifespan, so tests that touch mission
# routes need the database initialized explicitly (mirrors run_all() below).
import pytest


@pytest.fixture(autouse=True)
async def _init_db():
    import backend.database as db
    await db.init_db()
    yield
    try:
        await db.close_db()
    except Exception:
        pass


async def test_health_endpoint():
    """Test GET /health returns 200 with expected fields."""
    from httpx import AsyncClient, ASGITransport
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "uptime_s" in data
        assert "components" in data
        print("  ✓ test_health_endpoint")


async def test_root_endpoint():
    """Test GET / returns API info."""
    from httpx import AsyncClient, ASGITransport
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "AeroTwin" in data["name"]
        assert data["docs"] == "/docs"
        print("  ✓ test_root_endpoint")


async def test_fault_types():
    """Test GET /api/faults/types returns fault metadata."""
    from httpx import AsyncClient, ASGITransport
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/faults/types")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["fault_types"]) == 8
        types = [ft["type"] for ft in data["fault_types"]]
        assert "LUBRICATION_FAILURE" in types
        assert "MISFIRE" in types
        print("  ✓ test_fault_types")


async def test_list_missions_empty():
    """Test GET /api/missions returns empty list initially."""
    from httpx import AsyncClient, ASGITransport
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/missions")
        assert resp.status_code == 200
        data = resp.json()
        assert "missions" in data
        assert isinstance(data["missions"], list)
        print("  ✓ test_list_missions_empty")


async def test_start_mission():
    """Test POST /api/missions/start creates a running mission."""
    from httpx import AsyncClient, ASGITransport
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/missions/start", json={
            "duration_s": 3,
            "engine_id": "TAPAS-BH-201-001",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "RUNNING"
        assert "mission_id" in data
        print(f"  ✓ test_start_mission (id={data['mission_id'][:8]}...)")


async def test_simulation_status():
    """Test GET /api/simulation/status."""
    from httpx import AsyncClient, ASGITransport
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/simulation/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "is_running" in data
        assert "frame_id" in data
        assert "sim_time_s" in data
        print(f"  ✓ test_simulation_status (running={data['is_running']})")


async def test_engine_state():
    """Test engine state endpoint (may return 503 if no sim)."""
    from httpx import AsyncClient, ASGITransport
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/engine/TAPAS-BH-201-001/state")
        assert resp.status_code in (200, 503)
        print(f"  ✓ test_engine_state (status={resp.status_code})")


async def test_pydantic_schemas():
    """Test Pydantic model validation."""
    from backend.models import (
        TelemetryFrame, EngineState, MissionCreate,
        FaultInjectionRequest, FaultType, HealthCheck,
    )

    # TelemetryFrame
    frame = TelemetryFrame(
        frame_id=1, rpm=2400,
        cht=[175, 180, 178, 182],
        egt=[620, 625, 630, 615],
    )
    assert frame.frame_id == 1
    assert len(frame.cht) == 4

    # MissionCreate
    mission = MissionCreate(duration_s=300)
    assert mission.engine_id == "TAPAS-BH-201-001"

    # FaultInjectionRequest
    fault = FaultInjectionRequest(fault_type=FaultType.MISFIRE, severity=0.8)
    assert fault.fault_type == FaultType.MISFIRE
    assert fault.severity == 0.8

    # Health check
    hc = HealthCheck(version="1.0.0", uptime_s=42.0)
    assert hc.status == "ok"

    print("  ✓ test_pydantic_schemas")


async def test_simulator_imports():
    """Test that the simulator module imports correctly with fixed APIs."""
    from simulator.telemetry_gen.engine_model import EngineModel
    from simulator.telemetry_gen.fault_injection import FaultInjector, FaultSpec
    from simulator.telemetry_gen.mission_profiles import MissionProfile, build_mission_plan
    from simulator.telemetry_gen.telemetry_schema import FaultType, MissionPhase

    # Build a mission profile
    plan = build_mission_plan()
    profile = MissionProfile(plan)
    phase, throttle, alt = profile.at(300.0)
    assert isinstance(phase, MissionPhase)
    assert 0.0 <= throttle <= 1.0
    assert alt >= 0.0

    # Build a fault injector
    spec = FaultSpec(fault_type=FaultType.MISFIRE, severity=0.7, onset_s=100.0, ramp_s=30.0)
    injector = FaultInjector(specs=[spec], seed=42)

    # Build engine model
    engine = EngineModel(seed=42)
    row = engine.step(throttle=0.7, altitude_ft=10000, ambient_temp_c=15.0)
    assert "rpm" in row
    assert row["rpm"] > 0

    # Apply fault
    row = injector.apply(row, t=200.0)
    assert "faults_active" in row

    print("  ✓ test_simulator_imports")


async def test_simulator_service():
    """Test SimulatorService uses correct APIs."""
    from backend.services.simulator import SimulatorService
    import asyncio

    sim = SimulatorService()
    assert not sim.is_running
    assert sim.mission_id == ""

    # Start with a short mission
    await sim.start(mission_id="test-mission", duration_s=2, seed=42)

    # Wait for some frames
    await asyncio.sleep(1.5)

    assert sim.is_running
    assert sim.frame_id > 0
    assert sim._last_frame is not None
    assert len(sim._recent_frames) > 0
    assert sim._last_frame["mission_id"] == "test-mission"

    # Stop
    await sim.stop()
    assert not sim.is_running

    print(f"  ✓ test_simulator_service ({sim.frame_id} frames generated)")


async def run_all():
    """Run all tests."""
    print("\n═══════════════════════════════════════════════════════════════")
    print("  AeroTwin Backend — API Tests")
    print("═══════════════════════════════════════════════════════════════\n")

    # ASGITransport does not run the app's lifespan, so the database the
    # mission routes need has to be brought up (and torn down) by hand.
    import backend.database as db
    await db.init_db()

    tests = [
        test_pydantic_schemas,
        test_simulator_imports,
        test_health_endpoint,
        test_root_endpoint,
        test_fault_types,
        test_list_missions_empty,
        test_engine_state,
        test_simulation_status,
        test_simulator_service,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            print(f"  ✗ {test.__name__} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'═' * 60}")
    print(f"  Results: {passed} passed, {failed} failed")
    print(f"{'═' * 60}\n")

    try:
        await db.close_db()
    except Exception:
        pass

    return failed


if __name__ == "__main__":
    sys.exit(asyncio.run(run_all()))
