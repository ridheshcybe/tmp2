#!/usr/bin/env python3
"""
Real-Time Telemetry Streamer
-----------------------------
WebSocket server that runs the Aero Piston Engine digital twin at
exactly 10 Hz and broadcasts JSON telemetry packets to all connected
clients.

Clients may also send JSON commands to dynamically control the live
simulation (inject/clear faults, change throttle, altitude, etc.).

Server:  localhost:8765
Rate:    10 Hz (100 ms), drift-compensated

Usage
-----
    python -m simulator.telemetry_streamer                  # start server
    python -m simulator.telemetry_streamer --port 9000      # custom port
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

try:
    import websockets
    from websockets.asyncio.server import serve, ServerConnection
except ImportError:
    print(
        "  ERROR: 'websockets' package not found.\n"
        "  Install with:  pip install websockets>=12.0\n",
        file=sys.stderr,
    )
    sys.exit(1)

from simulator.fault_injector import FaultInjector, FaultType


# ══════════════════════════════════════════════════════════════════
#  Configuration
# ══════════════════════════════════════════════════════════════════

DEFAULT_PORT = 8765
SIM_HZ = 10                        # target tick rate
SIM_DT = 1.0 / SIM_HZ             # 0.1 s per tick
LOG_FMT = "%(asctime)s  %(levelname)-7s  %(message)s"

logging.basicConfig(level=logging.INFO, format=LOG_FMT)
log = logging.getLogger("telemetry")


# ══════════════════════════════════════════════════════════════════
#  Telemetry packet builder
# ══════════════════════════════════════════════════════════════════

def _build_packet(
    frame: Dict[str, Any],
    frame_id: int,
    altitude_ft: float,
    throttle: float,
) -> Dict[str, Any]:
    """
    Flatten the engine frame into the broadcast packet format.

    Packet schema::

        {
          "timestamp":       "2026-08-31T12:00:00.123456Z",
          "frame_id":        int,
          "altitude_ft":     float,
          "throttle":        float,
          "rpm":             float,
          "map_kpa":         float,
          "fuel_flow_lph":   float,
          "cht":             [c1, c2, c3, c4],
          "egt":             [e1, e2, e3, e4],
          "oil_pressure_kpa": float,
          "oil_temp_c":      float,
          "vibration_rms":   float,
          "ambient_temp_c":  float,
          "injected_fault":  str | null,
        }
    """
    faults = frame.get("faults_active", [])
    injected = faults[0] if faults else None

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "frame_id": frame_id,
        "altitude_ft": altitude_ft,
        "throttle": throttle,
        "rpm": frame.get("rpm", 0.0),
        "map_kpa": frame.get("map_kpa", 0.0),
        "fuel_flow_lph": frame.get("fuel_flow_lph", 0.0),
        "cht": frame.get("cht_c", [0.0, 0.0, 0.0, 0.0]),
        "egt": frame.get("egt_c", [0.0, 0.0, 0.0, 0.0]),
        "oil_pressure_kpa": frame.get("oil_pressure_kpa", 0.0),
        "oil_temp_c": frame.get("oil_temp_c", 0.0),
        "vibration_rms": frame.get("vibration_rms_g", 0.0),
        "ambient_temp_c": frame.get("ambient_temp_c", 15.0),
        "injected_fault": injected,
    }


# ══════════════════════════════════════════════════════════════════
#  Command processor
# ══════════════════════════════════════════════════════════════════

def _process_command(
    injector: FaultInjector,
    cmd: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Execute a client command and return an acknowledgement dict.

    Supported commands
    ------------------
    INJECT_FAULT
        {"command": "INJECT_FAULT", "type": "PISTON_RING_WEAR",
         "severity": 0.6, "rate_per_sec": 0.01}

    CLEAR_FAULTS
        {"command": "CLEAR_FAULTS"}

    SET_THROTTLE
        {"command": "SET_THROTTLE", "value": 0.8}

    SET_ALTITUDE
        {"command": "SET_ALTITUDE", "value": 15000}

    STATUS
        {"command": "STATUS"}
    """
    command = cmd.get("command", "").upper()

    match command:
        case "INJECT_FAULT":
            ft = cmd.get("type", "").upper()
            severity = float(cmd.get("severity", 0.5))
            rate = float(cmd.get("rate_per_sec", 0.01))
            frozen_cyl = int(cmd.get("frozen_cyl", 1))

            try:
                injector.trigger_fault(ft, severity, rate, frozen_cyl)
                log.info(
                    "FAULT INJECTED: %s  severity=%.2f  rate=%.4f",
                    ft, severity, rate,
                )
                return {
                    "status": "ok",
                    "command": "INJECT_FAULT",
                    "fault_type": ft,
                    "active_faults": injector.fault_types_active,
                }
            except ValueError as e:
                return {"status": "error", "message": str(e)}

        case "CLEAR_FAULTS":
            injector.clear_faults()
            log.info("ALL FAULTS CLEARED")
            return {
                "status": "ok",
                "command": "CLEAR_FAULTS",
                "active_faults": [],
            }

        case "SET_THROTTLE":
            val = float(cmd.get("value", 0.5))
            val = max(0.0, min(1.0, val))
            injector.engine.throttle = val
            log.info("THROTTLE SET: %.2f", val)
            return {"status": "ok", "command": "SET_THROTTLE", "value": val}

        case "SET_ALTITUDE":
            val = float(cmd.get("value", 0.0))
            val = max(0.0, min(40_000.0, val))
            injector.engine._last_altitude = val
            log.info("ALTITUDE SET: %.0f ft", val)
            return {"status": "ok", "command": "SET_ALTITUDE", "value": val}

        case "STATUS":
            return {
                "status": "ok",
                "command": "STATUS",
                "active_faults": injector.fault_types_active,
                "sim_time_s": injector.engine.sim_time,
                "rpm": injector.engine.rpm,
            }

        case _:
            return {
                "status": "error",
                "message": f"Unknown command: '{command}'",
                "valid_commands": [
                    "INJECT_FAULT", "CLEAR_FAULTS",
                    "SET_THROTTLE", "SET_ALTITUDE", "STATUS",
                ],
            }


# ══════════════════════════════════════════════════════════════════
#  Server
# ══════════════════════════════════════════════════════════════════

class TelemetryServer:
    """
    Async WebSocket server that:
    1. Runs the engine sim at 10 Hz in a dedicated loop.
    2. Broadcasts each new packet to every connected client.
    3. Listens for incoming JSON commands from any client.
    """

    def __init__(self, port: int = DEFAULT_PORT) -> None:
        self.port = port
        self.injector = FaultInjector(dt=SIM_DT, enable_noise=True)

        # ── Simulation parameters (mutable via commands) ──
        self._throttle = 0.65
        self._altitude_ft = 18_000.0
        self._weather = "CLEAR"

        # ── Client tracking ──
        self._clients: Set[ServerConnection] = set()
        self._frame_id = 0

        # ── Drift-compensation state ──
        self._next_tick: float = 0.0

    # ── Client handler ──────────────────────────────────────────

    async def _handler(self, ws: ServerConnection) -> None:
        """Per-client coroutine: register, listen for commands, clean up."""
        self._clients.add(ws)
        remote = ws.remote_address
        log.info("Client connected: %s  (total: %d)", remote, len(self._clients))

        try:
            async for raw in ws:
                try:
                    cmd = json.loads(raw)
                    resp = _process_command(self.injector, cmd)
                    await ws.send(json.dumps(resp))
                except json.JSONDecodeError:
                    await ws.send(json.dumps({
                        "status": "error",
                        "message": "Invalid JSON",
                    }))
        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(ws)
            log.info("Client disconnected: %s  (total: %d)", remote, len(self._clients))

    # ── Simulation + broadcast loop ─────────────────────────────

    async def _broadcast_loop(self) -> None:
        """
        Tick the engine at exactly SIM_HZ, broadcasting each frame.

        Uses drift-compensated timing: each tick is scheduled for
        ``next_tick`` regardless of how long the previous tick took.
        """
        self._next_tick = time.monotonic()

        while True:
            # ── Sleep until the next tick ──
            now = time.monotonic()
            wait = self._next_tick - now
            if wait > 0:
                await asyncio.sleep(wait)

            # ── Compute actual dt (handles overshoot) ──
            actual_now = time.monotonic()
            # For the sim engine, dt is fixed at SIM_DT regardless
            # of wall-clock overshoot.  The drift-compensation keeps
            # the *average* rate at SIM_HZ.

            # ── Advance simulation ──
            frame = self.injector.step(
                throttle=self._throttle,
                altitude_ft=self._altitude_ft,
                weather=self._weather,
            )
            self._frame_id += 1

            # ── Build packet ──
            packet = _build_packet(
                frame, self._frame_id, self._altitude_ft, self._throttle,
            )
            payload = json.dumps(packet)

            # ── Broadcast to all clients ──
            if self._clients:
                stale: list[ServerConnection] = []
                for ws in list(self._clients):
                    try:
                        await ws.send(payload)
                    except websockets.ConnectionClosed:
                        stale.append(ws)
                for ws in stale:
                    self._clients.discard(ws)

            # ── Schedule next tick (drift-compensated) ──
            self._next_tick += SIM_DT

            # If we've fallen behind by more than 5 ticks, snap forward
            if time.monotonic() - self._next_tick > 5 * SIM_DT:
                log.warning("Simulation fell behind; snapping to real-time.")
                self._next_tick = time.monotonic() + SIM_DT

    # ── Entrypoint ──────────────────────────────────────────────

    async def run(self) -> None:
        log.info(
            "Telemetry server starting on ws://localhost:%d  (%d Hz)",
            self.port, SIM_HZ,
        )
        log.info("Waiting for clients…")

        async with serve(self._handler, "localhost", self.port):
            await self._broadcast_loop()


# ══════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aero Piston Engine Telemetry Streamer",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"WebSocket port (default: {DEFAULT_PORT})",
    )
    args = parser.parse_args()

    server = TelemetryServer(port=args.port)
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        log.info("Server shut down.")


if __name__ == "__main__":
    main()
