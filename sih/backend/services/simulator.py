"""
AeroTwin Backend — Simulator Background Task
==============================================

Runs the telemetry generator in-process as an asyncio task.
Produces one TelemetryFrame per tick at the configured Hz,
feeds it through the ML pipeline, and broadcasts via WebSocket.

No external Python process needed — everything runs in the same
uvicorn worker for the hackathon demo.
"""

from __future__ import annotations

import asyncio
import collections
import math
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Deque, Dict, List, Optional

import numpy as np

from backend.config import get_settings

# Simulator imports (from our own package)
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from simulator.telemetry_gen.engine_model import EngineModel, isa_conditions
from simulator.telemetry_gen.fault_injection import FaultInjector, FaultSpec
from simulator.telemetry_gen.mission_profiles import (
    MissionProfile,
    build_mission_plan,
    build_test_flight_plan,
)
from simulator.telemetry_gen.telemetry_schema import FaultType, MissionPhase

# Ring-buffer size for recent frames (used by GET /api/engine/.../telemetry)
_RECENT_LIMIT = 600  # 60 s at 10 Hz


class SimulatorService:
    """
    In-process telemetry simulator.

    Usage::

        sim = SimulatorService()
        sim.start(mission_id="...", duration_s=600)
        # ... frames emitted via callback ...
        sim.stop()
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._engine: Optional[EngineModel] = None
        self._fault_injector: Optional[FaultInjector] = None
        self._mission_id: str = ""
        self._frame_id: int = 0
        self._sim_time: float = 0.0
        self._duration_s: int = 600
        self._hz: int = 10
        self._ambient_offset_c: float = 0.0
        self._active_faults: Dict[str, float] = {}
        self._callbacks: List[Callable] = []
        self._mission_profile: Optional[MissionProfile] = None
        # Active mission profile name ("default" | "test_flight")
        self._profile_name: str = "default"
        # Latest mission phase, exposed on /api/simulation/status so the
        # frontend can show where the (simulated) aircraft is right now.
        self._current_phase: str = MissionPhase.STARTUP.value
        # Latest effective throttle, for /api/simulation/status.
        self._current_throttle: float = 0.0

        # Ring-buffer of recent frames (for REST fallback)
        self._recent_frames: Deque[Dict[str, Any]] = collections.deque(maxlen=_RECENT_LIMIT)
        # Last frame snapshot (for GET /engine/{id}/state)
        self._last_frame: Optional[Dict[str, Any]] = None
        # Interactive overrides
        self._throttle_override: Optional[float] = None
        self._altitude_override: Optional[float] = None

    # ── Public API ────────────────────────────────────────────────────────

    def on_frame(self, callback: Callable) -> None:
        """Register a callback(frame_dict) for each generated tick."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable) -> None:
        self._callbacks = [c for c in self._callbacks if c is not callback]

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def mission_id(self) -> str:
        return self._mission_id

    @property
    def frame_id(self) -> int:
        return self._frame_id

    @property
    def sim_time(self) -> float:
        return self._sim_time

    @property
    def current_phase(self) -> str:
        return self._current_phase

    @property
    def current_throttle(self) -> float:
        return self._current_throttle

    @property
    def throttle_is_manual(self) -> bool:
        return self._throttle_override is not None

    async def start(
        self,
        mission_id: str,
        duration_s: int = 600,
        ambient_offset_c: float = 0.0,
        seed: Optional[int] = None,
        profile: str = "default",
    ) -> None:
        """Start generating telemetry in background.

        ``profile`` selects the mission plan: "default" is the ~99-minute
        STARTUP → LANDING plan, "test_flight" the compressed ~2.5-minute
        plan the frontend's Test Flight demo flies.
        """
        if self._running:
            # A new mission replaces the running one: the dashboard always
            # keeps an interactive session alive, so "start" must actually
            # switch profiles (manual -> test_flight) rather than no-op.
            await self.stop()

        self._running = True
        self._mission_id = mission_id
        self._frame_id = 0
        self._sim_time = 0.0
        self._duration_s = duration_s
        self._hz = self.settings.SIM_HZ
        self._ambient_offset_c = ambient_offset_c
        self._active_faults = {}
        self._recent_frames.clear()
        self._last_frame = None
        # A fresh mission flies its own plan: drop any interactive throttle
        # / altitude override left over from a previous session.
        self._throttle_override = None
        self._altitude_override = None
        self._profile_name = (
            profile if profile in ("default", "test_flight", "manual") else "default"
        )

        rng_seed = seed if seed is not None else self.settings.SIM_SEED
        self._engine = EngineModel(seed=rng_seed, ambient_offset_c=ambient_offset_c)

        # Fault injector starts empty; faults are injected via inject_fault()
        self._fault_injector = FaultInjector(specs=[], seed=rng_seed + 1000)

        # Every mission start registers a fresh frame pipeline (mission
        # start wires ML -> DB -> WS); drop the previous mission's
        # callbacks so frames are not double-processed across missions.
        self._callbacks.clear()

        # Build the mission profile from the selected plan. "manual" is the
        # idle-parked interactive plan the dashboard's presets/slider and
        # the phone controller command from.
        plan = (
            build_test_flight_plan()
            if self._profile_name == "test_flight"
            else build_mission_plan(profile=self._profile_name)
        )
        self._mission_profile = MissionProfile(plan)

        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop the simulator."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def inject_fault(
        self,
        fault_type: str,
        severity: float = 0.7,
        target_sensor: Optional[str] = None,
        ramp_s: float = 60.0,
    ) -> None:
        """Inject a fault into the running simulation."""
        try:
            ft = FaultType(fault_type)
        except ValueError:
            print(f"[Simulator] Unknown fault type: {fault_type}")
            return

        spec = FaultSpec(
            fault_type=ft,
            severity=severity,
            onset_s=self._sim_time,
            ramp_s=ramp_s,
            channel=target_sensor,
        )
        # FaultInjector takes a list; append and recreate runtime state
        self._fault_injector.specs.append(spec)
        from simulator.telemetry_gen.fault_injection import _FaultRuntime
        self._fault_injector.runtimes.append(_FaultRuntime(spec))
        self._active_faults[fault_type] = severity

    def clear_faults(self) -> None:
        """Clear all injected faults."""
        if self._fault_injector:
            self._fault_injector.specs.clear()
            self._fault_injector.runtimes.clear()
        self._active_faults = {}

    def set_throttle(self, throttle: float) -> None:
        """Override throttle (for interactive demo).

        Note: the MissionProfile interpolates linearly within each phase.
        A full override requires rebuilding the plan; for the demo we
        store the override and apply it in the next tick.
        """
        self._throttle_override = max(0.0, min(1.0, throttle))

    def release_throttle(self) -> None:
        """Hand throttle control back to the mission profile."""
        self._throttle_override = None

    def set_altitude(self, altitude_ft: float) -> None:
        """Override altitude (for interactive demo)."""
        self._altitude_override = max(0.0, min(45000.0, altitude_ft))

    # ── Internal Run Loop ─────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        dt = 1.0 / self._hz
        try:
            while self._running and self._sim_time < self._duration_s:
                t_start = time.monotonic()

                # Get mission conditions from profile
                assert self._mission_profile is not None
                phase, throttle, altitude_ft = self._mission_profile.at(self._sim_time)
                self._current_phase = (
                    phase.value if isinstance(phase, MissionPhase) else str(phase)
                )

                # Apply overrides
                if self._throttle_override is not None:
                    throttle = self._throttle_override
                if self._altitude_override is not None:
                    altitude_ft = self._altitude_override
                self._current_throttle = float(throttle)

                # ISA ambient temperature
                ambient_temp_c = isa_conditions(altitude_ft)["ambient_temp_c"] + self._ambient_offset_c

                # Step engine model
                assert self._engine is not None
                row = self._engine.step(throttle, altitude_ft, ambient_temp_c)

                # Apply fault effects
                if self._fault_injector and self._fault_injector.specs:
                    row = self._fault_injector.apply(row, self._sim_time)

                # Build frame
                self._frame_id += 1
                frame = self._build_frame(row, phase, ambient_temp_c)

                # Store in ring buffer + last_frame
                self._last_frame = frame
                self._recent_frames.append(frame)

                # Fire callbacks
                for cb in self._callbacks:
                    try:
                        result = cb(frame)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as e:
                        print(f"[Simulator] Callback error: {e}")

                self._sim_time += dt

                # Sleep to maintain Hz
                elapsed = time.monotonic() - t_start
                sleep_time = max(0, dt - elapsed)
                await asyncio.sleep(sleep_time)

        except asyncio.CancelledError:
            pass
        finally:
            self._running = False

    def _build_frame(
        self, row: Dict[str, Any], phase: MissionPhase, ambient_temp_c: float
    ) -> Dict[str, Any]:
        """Convert a simulator row into a TelemetryFrame dict."""
        active_faults = list(self._active_faults.keys()) if self._active_faults else []
        max_sev = max(self._active_faults.values()) if self._active_faults else 0.0

        return {
            "frame_id": self._frame_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "engine_id": self.settings.ENGINE_ID,
            "mission_id": self._mission_id,
            "sim_time_s": self._sim_time,
            "phase": phase.value if isinstance(phase, MissionPhase) else str(phase),
            "throttle": float(row.get("throttle", 0.0)),
            "altitude_ft": float(row.get("altitude_ft", 0.0)),
            "ambient_temp_c": ambient_temp_c,
            "rpm": float(row.get("rpm", 0.0)),
            "fuel_flow_lph": float(row.get("fuel_flow_lph", 0.0)),
            "cht": [
                float(row.get("cht_c1", 0)),
                float(row.get("cht_c2", 0)),
                float(row.get("cht_c3", 0)),
                float(row.get("cht_c4", 0)),
            ],
            "egt": [
                float(row.get("egt_c1", 0)),
                float(row.get("egt_c2", 0)),
                float(row.get("egt_c3", 0)),
                float(row.get("egt_c4", 0)),
            ],
            "oil_pressure_kpa": float(row.get("oil_pressure_kpa", 0)),
            "oil_temp_c": float(row.get("oil_temp_c", 15)),
            "vibration_rms": float(row.get("vibration_rms_g", 0)),
            "battery_voltage": float(row.get("battery_v", 12.5)),
            "alternator_current": float(row.get("alternator_a", 0)),
            "injection_timing": float(row.get("injection_timing_deg", 24)),
            "injected_fault": ",".join(active_faults) if active_faults else None,
            "fault_severity": float(max_sev),
        }


# Singleton
_simulator: Optional[SimulatorService] = None


def get_simulator() -> SimulatorService:
    global _simulator
    if _simulator is None:
        _simulator = SimulatorService()
    return _simulator
