"""
AeroTwin Backend — Configuration
================================

Centralised settings loaded from environment variables (or .env file).
All ports, paths, and tuning constants live here — nothing hardcoded in routes.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings — loaded from env vars / .env file."""

    # ── App ──────────────────────────────────────────────────────────────────
    APP_NAME: str = "AeroTwin Digital Twin API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # ── Server ───────────────────────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8081

    # ── CORS ─────────────────────────────────────────────────────────────────
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///data/aerotwin.db"
    DB_PATH: str = "data/aerotwin.db"

    # ── WebSocket ────────────────────────────────────────────────────────────
    WS_HEARTBEAT_INTERVAL: int = 15  # seconds
    WS_MAX_CONNECTIONS: int = 50

    # ── Simulator ────────────────────────────────────────────────────────────
    SIM_HZ: int = 10
    SIM_SEED: int = 42
    AMBIENT_OFFSET_C: float = 0.0  # hot-weather offset

    # ── ML Models ────────────────────────────────────────────────────────────
    MODEL_DIR: str = "ml/models"
    USE_FALLBACK: bool = True  # use rule-based fallback if models missing

    # ── Mission ──────────────────────────────────────────────────────────────
    DEFAULT_MISSION_DURATION_S: int = 600  # 10 min for demo
    MAX_REPLAY_FRAMES: int = 100_000

    # ── Paths ────────────────────────────────────────────────────────────────
    DATA_DIR: str = "data"
    REPORT_DIR: str = "data/reports"
    LOG_DIR: str = "logs"

    # ── Engine defaults ──────────────────────────────────────────────────────
    ENGINE_ID: str = "TAPAS-BH-201-001"
    NUM_CYLINDERS: int = 4

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    """Cached singleton for app-wide settings."""
    return Settings()
