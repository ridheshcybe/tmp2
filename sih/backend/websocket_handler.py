"""
AeroTwin Backend — WebSocket Handler
======================================

Manages WebSocket connections from the React dashboard.
Broadcasts telemetry frames and receives commands (fault injection,
throttle override, etc.).

Protocol:
  Server → Client: {"type": "TELEMETRY", "payload": {...engine_state...}}
  Server → Client: {"type": "FAULT_INJECTED", "payload": {...}}
  Client → Server: {"action": "TRIGGER_FAULT", "fault": "...", "severity": 0.7}
  Client → Server: {"action": "CLEAR_FAULTS"}
  Client → Server: {"action": "SET_THROTTLE", "throttle": 0.8}
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Set

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from backend.config import get_settings

# ══════════════════════════════════════════════════════════════════════════════
#  Connection Manager
# ══════════════════════════════════════════════════════════════════════════════


class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()
        self._settings = get_settings()

    @property
    def count(self) -> int:
        return len(self._connections)

    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await ws.accept()
        self._connections.add(ws)
        print(f"[WS] Client connected ({self.count} total)")

        # Send welcome
        await self._send(ws, {
            "type": "WELCOME",
            "payload": {
                "server_time": datetime.now(timezone.utc).isoformat() + "Z",
                "connected_clients": self.count,
            },
        })

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a disconnected client."""
        self._connections.discard(ws)
        print(f"[WS] Client disconnected ({self.count} remaining)")

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Broadcast a message to all connected clients."""
        dead: List[WebSocket] = []
        for ws in self._connections:
            if ws.client_state == WebSocketState.CONNECTED:
                await self._send(ws, message)
            else:
                dead.append(ws)
        for ws in dead:
            self._connections.discard(ws)

    async def _send(self, ws: WebSocket, message: Dict[str, Any]) -> None:
        try:
            await ws.send_json(message)
        except Exception:
            self._connections.discard(ws)


# ══════════════════════════════════════════════════════════════════════════════
#  Singleton
# ══════════════════════════════════════════════════════════════════════════════

_manager: ConnectionManager = ConnectionManager()


def get_manager() -> ConnectionManager:
    return _manager


# ══════════════════════════════════════════════════════════════════════════════
#  Broadcast Helpers (called by simulator / mission routes)
# ══════════════════════════════════════════════════════════════════════════════


async def broadcast_frame(state: Dict[str, Any]) -> None:
    """Broadcast an engine state frame to all WebSocket clients."""
    await _manager.broadcast({
        "type": "TELEMETRY",
        "payload": state,
        "timestamp": state.get("timestamp", datetime.now(timezone.utc).isoformat() + "Z"),
    })


async def broadcast_message(message: Dict[str, Any]) -> None:
    """Broadcast an arbitrary message to all WebSocket clients."""
    await _manager.broadcast(message)


# ══════════════════════════════════════════════════════════════════════════════
#  WebSocket Endpoint Handler
# ══════════════════════════════════════════════════════════════════════════════


async def ws_handler(ws: WebSocket) -> None:
    """
    Main WebSocket endpoint handler.

    Registers the connection, processes incoming commands,
    and handles disconnection.
    """
    await _manager.connect(ws)
    try:
        while True:
            data = await ws.receive_json()
            await _handle_command(data)
    except WebSocketDisconnect:
        _manager.disconnect(ws)
    except Exception as e:
        print(f"[WS] Error: {e}")
        _manager.disconnect(ws)


async def _handle_command(data: Dict[str, Any]) -> None:
    """Process an incoming WebSocket command."""
    action = data.get("action", "")
    print(f"[WS] Command: {action}")

    if action == "TRIGGER_FAULT":
        from backend.services.simulator import get_simulator
        sim = get_simulator()
        if sim.is_running:
            sim.inject_fault(
                fault_type=data.get("fault", "MISFIRE"),
                severity=data.get("severity", 0.7),
                target_sensor=data.get("sensor"),
            )
            await broadcast_message({
                "type": "FAULT_INJECTED",
                "payload": {
                    "fault_type": data.get("fault"),
                    "severity": data.get("severity", 0.7),
                },
            })

    elif action == "CLEAR_FAULTS":
        from backend.services.simulator import get_simulator
        sim = get_simulator()
        sim.clear_faults()
        await broadcast_message({"type": "FAULTS_CLEARED", "payload": {}})

    elif action == "SET_THROTTLE":
        from backend.services.simulator import get_simulator
        sim = get_simulator()
        if sim.is_running:
            sim.set_throttle(float(data.get("throttle", 0.7)))

    elif action == "SET_ALTITUDE":
        from backend.services.simulator import get_simulator
        sim = get_simulator()
        if sim.is_running:
            sim.set_altitude(float(data.get("altitude_ft", 10000)))

    elif action == "PING":
        await _manager.broadcast({
            "type": "PONG",
            "payload": {"server_time": datetime.now(timezone.utc).isoformat() + "Z"},
        })

    elif action == "GET_STATS":
        from backend.services.simulator import get_simulator
        sim = get_simulator()
        await _manager.broadcast({
            "type": "STATS",
            "payload": {
                "is_running": sim.is_running,
                "frame_id": sim.frame_id,
                "sim_time_s": sim.sim_time,
                "connected_clients": _manager.count,
            },
        })

    else:
        print(f"[WS] Unknown command: {action}")
