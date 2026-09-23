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
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from backend.config import get_settings

# ══════════════════════════════════════════════════════════════════════════════
#  Connection Manager
# ══════════════════════════════════════════════════════════════════════════════


class ConnectionManager:
    """Manages active WebSocket connections.

    Each client gets its own ``asyncio.Lock`` so a slow consumer can never
    serialize or starve broadcasts to the other clients (one stuck send used
    to block every client's telemetry stream).
    """

    def __init__(self, max_connections: Optional[int] = None) -> None:
        self._connections: Set[WebSocket] = set()
        self._send_locks: Dict[WebSocket, asyncio.Lock] = {}
        self._lock = asyncio.Lock()
        self._max = max_connections if max_connections is not None \
            else get_settings().WS_MAX_CONNECTIONS

    @property
    def count(self) -> int:
        return len(self._connections)

    async def connect(self, ws: WebSocket) -> bool:
        """Accept and register a new WebSocket connection.

        Returns False (after closing the socket) when the server is at its
        connection limit — previously unlimited connections could exhaust
        memory / file descriptors.
        """
        async with self._lock:
            if self.count >= self._max:
                # Reject politely: accept so we can send a reason, then close.
                try:
                    await ws.accept()
                    await ws.send_json({
                        "type": "ERROR",
                        "payload": {"reason": "connection_limit_reached"},
                    })
                    await ws.close(code=1013)  # try again later
                except Exception:
                    pass
                return False
            await ws.accept()
            self._connections.add(ws)
            self._send_locks[ws] = asyncio.Lock()

        try:
            await self._send(ws, {
                "type": "WELCOME",
                "payload": {
                    "server_time": datetime.now(timezone.utc).isoformat() + "Z",
                    "connected_clients": self.count,
                },
            })
        except Exception:
            self.disconnect(ws)
        return True

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a disconnected client."""
        self._connections.discard(ws)
        self._send_locks.pop(ws, None)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Broadcast a message to all connected clients concurrently.

        A failing/stale client is dropped without affecting delivery to
        the others.
        """
        async with self._lock:
            targets = list(self._connections)

        async def _safe_send(ws: WebSocket) -> None:
            ok = await self._send(ws, message)
            if not ok:
                self.disconnect(ws)

        if targets:
            await asyncio.gather(*(_safe_send(ws) for ws in targets))

    async def _send(self, ws: WebSocket, message: Dict[str, Any]) -> bool:
        """Send with per-client lock; returns False when the client died."""
        lock = self._send_locks.get(ws)
        if lock is None:
            return False
        async with lock:
            state = getattr(ws, "client_state", None)
            if state != WebSocketState.CONNECTED:
                return False
            try:
                await ws.send_json(message)
                return True
            except Exception:
                return False


# ══════════════════════════════════════════════════════════════════════════════
#  Singleton
# ══════════════════════════════════════════════════════════════════════════════

_manager: Optional[ConnectionManager] = None


def get_manager() -> ConnectionManager:
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager


# ══════════════════════════════════════════════════════════════════════════════
#  Broadcast Helpers (called by simulator / mission routes)
# ══════════════════════════════════════════════════════════════════════════════


async def broadcast_frame(state: Dict[str, Any]) -> None:
    """Broadcast an engine state frame to all WebSocket clients."""
    await get_manager().broadcast({
        "type": "TELEMETRY",
        "payload": state,
        "timestamp": state.get("timestamp", datetime.now(timezone.utc).isoformat() + "Z"),
    })


async def broadcast_message(message: Dict[str, Any]) -> None:
    """Broadcast an arbitrary message to all WebSocket clients."""
    await get_manager().broadcast(message)


# ══════════════════════════════════════════════════════════════════════════════
#  WebSocket Endpoint Handler
# ══════════════════════════════════════════════════════════════════════════════


async def ws_handler(ws: WebSocket) -> None:
    """
    Main WebSocket endpoint handler.

    Registers the connection, processes incoming commands,
    and handles disconnection.  Malformed client messages are logged and
    skipped — one bad frame must not tear down the connection.
    """
    manager = get_manager()
    if not await manager.connect(ws):
        return
    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except (ValueError, TypeError):
                await manager._send(ws, {
                    "type": "ERROR",
                    "payload": {"reason": "malformed_json"},
                })
                continue
            if not isinstance(data, dict):
                await manager._send(ws, {
                    "type": "ERROR",
                    "payload": {"reason": "expected_object"},
                })
                continue
            try:
                await _handle_command(data, ws)
            except Exception as e:
                print(f"[WS] Command error: {e}")
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception as e:
        print(f"[WS] Error: {e}")
        manager.disconnect(ws)


async def _handle_command(data: Dict[str, Any], ws: WebSocket) -> None:
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
        # Unicast reply — a PONG broadcast used to spam every other client.
        await get_manager()._send(ws, {
            "type": "PONG",
            "payload": {"server_time": datetime.now(timezone.utc).isoformat() + "Z"},
        })

    elif action == "GET_STATS":
        from backend.services.simulator import get_simulator
        sim = get_simulator()
        await get_manager()._send(ws, {
            "type": "STATS",
            "payload": {
                "is_running": sim.is_running,
                "frame_id": sim.frame_id,
                "sim_time_s": sim.sim_time,
                "connected_clients": get_manager().count,
            },
        })

    else:
        print(f"[WS] Unknown command: {action}")
