"""
AeroTwin Backend — Mission Replay Service
===========================================

Reads stored telemetry from the database and replays it at a configurable
speed via WebSocket to the frontend.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from backend.config import get_settings


class ReplayService:
    """Mission replay — feeds stored frames to a callback at configurable speed."""

    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._mission_id: str = ""
        self._speed: float = 1.0
        self._start_s: Optional[float] = None
        self._end_s: Optional[float] = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def mission_id(self) -> str:
        return self._mission_id

    async def start(
        self,
        mission_id: str,
        callback: Callable,
        speed: float = 1.0,
        start_s: Optional[float] = None,
        end_s: Optional[float] = None,
    ) -> None:
        """Start replaying a mission at given speed."""
        if self._running:
            return

        self._running = True
        self._mission_id = mission_id
        self._speed = speed
        self._start_s = start_s
        self._end_s = end_s

        self._task = asyncio.create_task(self._run(callback))

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self, callback: Callable) -> None:
        """Load frames and replay them."""
        try:
            import backend.database as db
            frames = await db.get_replay_frames(
                self._mission_id,
                start_s=self._start_s,
                end_s=self._end_s,
                limit=get_settings().MAX_REPLAY_FRAMES,
            )
            if not frames:
                self._running = False
                return

            base_dt = 1.0  # assumed 1 Hz storage
            for frame in frames:
                if not self._running:
                    break
                await callback(frame)
                await asyncio.sleep(base_dt / self._speed)

        except asyncio.CancelledError:
            pass
        finally:
            self._running = False


_replay_service: Optional[ReplayService] = None


def get_replay_service() -> ReplayService:
    global _replay_service
    if _replay_service is None:
        _replay_service = ReplayService()
    return _replay_service
