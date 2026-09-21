"""
AeroTwin Backend — SQLite Database Layer
=========================================

Async SQLite via aiosqlite.  Designed for the hackathon prototype: zero
external dependencies, fast enough for 10 Hz telemetry, and easy to swap
for PostgreSQL later.

Tables
------
engines          — registered engines
missions         — mission metadata
telemetry        — every tick (partitioned by mission_id)
fault_injections — injected faults (demo audit trail)
health_snapshots — per-tick health index + explanation
"""

from __future__ import annotations

import aiosqlite
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from backend.config import get_settings

# ══════════════════════════════════════════════════════════════════════════════
#  Schema
# ══════════════════════════════════════════════════════════════════════════════

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS engines (
    engine_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    model       TEXT DEFAULT 'aero-piston-4cyl',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS missions (
    mission_id   TEXT PRIMARY KEY,
    engine_id    TEXT NOT NULL REFERENCES engines(engine_id),
    name         TEXT,
    status       TEXT NOT NULL DEFAULT 'IDLE',
    started_at   TEXT NOT NULL,
    ended_at     TEXT,
    duration_s   INTEGER NOT NULL DEFAULT 600,
    ambient_offset_c REAL DEFAULT 0.0,
    frame_count  INTEGER DEFAULT 0,
    max_anomaly_score REAL DEFAULT 0.0,
    min_health_index  REAL DEFAULT 100.0,
    faults_observed TEXT DEFAULT '[]',
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS telemetry (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id    TEXT NOT NULL REFERENCES missions(mission_id),
    frame_id      INTEGER NOT NULL,
    timestamp     TEXT NOT NULL,
    sim_time_s    REAL NOT NULL,
    phase         TEXT,
    throttle      REAL,
    altitude_ft   REAL,
    ambient_temp_c REAL,
    rpm           REAL,
    fuel_flow_lph REAL,
    cht           TEXT,       -- JSON array [c1,c2,c3,c4]
    egt           TEXT,       -- JSON array [c1,c2,c3,c4]
    oil_pressure_kpa REAL,
    oil_temp_c    REAL,
    vibration_rms REAL,
    battery_voltage   REAL,
    alternator_current REAL,
    injection_timing  REAL,
    injected_fault TEXT,
    fault_severity REAL DEFAULT 0.0,
    UNIQUE(mission_id, frame_id)
);

CREATE TABLE IF NOT EXISTS fault_injections (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id   TEXT NOT NULL REFERENCES missions(mission_id),
    fault_type   TEXT NOT NULL,
    severity     REAL NOT NULL,
    target_sensor TEXT,
    injected_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS health_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id   TEXT NOT NULL REFERENCES missions(mission_id),
    frame_id     INTEGER NOT NULL,
    sim_time_s   REAL NOT NULL,
    health_index REAL,
    health_category TEXT,
    anomaly_score   REAL,
    is_anomaly      INTEGER DEFAULT 0,
    fault_class     TEXT,
    fault_confidence REAL,
    fault_severity  REAL,
    rul_minutes     REAL,
    rul_lo          REAL,
    rul_hi          REAL,
    rtb_alert       TEXT DEFAULT 'NONE',
    explanation     TEXT,       -- JSON array of strings
    contributors    TEXT,       -- JSON array of objects
    UNIQUE(mission_id, frame_id)
);

CREATE INDEX IF NOT EXISTS idx_tel_mission ON telemetry(mission_id, frame_id);
CREATE INDEX IF NOT EXISTS idx_tel_time ON telemetry(mission_id, sim_time_s);
CREATE INDEX IF NOT EXISTS idx_health_mission ON health_snapshots(mission_id, frame_id);
CREATE INDEX IF NOT EXISTS idx_faults_mission ON fault_injections(mission_id);
"""


# ══════════════════════════════════════════════════════════════════════════════
#  Connection Management
# ══════════════════════════════════════════════════════════════════════════════

_db: Optional[aiosqlite.Connection] = None


async def init_db() -> aiosqlite.Connection:
    """Open DB, create tables, return connection."""
    global _db
    settings = get_settings()
    Path(settings.DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    _db = await aiosqlite.connect(settings.DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(SCHEMA_SQL)
    await _db.commit()

    # Seed default engine if not exists
    await _db.execute(
        "INSERT OR IGNORE INTO engines (engine_id, name) VALUES (?, ?)",
        (settings.ENGINE_ID, "DRDO Tapas-BH-201"),
    )
    await _db.commit()
    return _db


async def close_db() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None


def get_db() -> aiosqlite.Connection:
    assert _db is not None, "Database not initialized — call init_db() first"
    return _db


# ══════════════════════════════════════════════════════════════════════════════
#  Mission CRUD
# ══════════════════════════════════════════════════════════════════════════════


async def create_mission(
    mission_id: str,
    engine_id: str,
    name: Optional[str],
    duration_s: int,
    ambient_offset_c: float,
) -> Dict[str, Any]:
    db = get_db()
    now = datetime.utcnow().isoformat() + "Z"
    await db.execute(
        """INSERT INTO missions
           (mission_id, engine_id, name, status, started_at, duration_s, ambient_offset_c)
           VALUES (?, ?, ?, 'RUNNING', ?, ?, ?)""",
        (mission_id, engine_id, name or f"Mission {mission_id[:8]}", now, duration_s, ambient_offset_c),
    )
    await db.commit()
    return {"mission_id": mission_id, "engine_id": engine_id, "status": "RUNNING", "started_at": now}


async def get_mission(mission_id: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    cursor = await db.execute("SELECT * FROM missions WHERE mission_id = ?", (mission_id,))
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def update_mission(mission_id: str, **kwargs: Any) -> None:
    db = get_db()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [mission_id]
    await db.execute(f"UPDATE missions SET {sets} WHERE mission_id = ?", vals)
    await db.commit()


async def list_missions(limit: int = 50) -> List[Dict[str, Any]]:
    db = get_db()
    cursor = await db.execute(
        "SELECT * FROM missions ORDER BY started_at DESC LIMIT ?", (limit,)
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
#  Telemetry Insert (batch-optimised)
# ══════════════════════════════════════════════════════════════════════════════

_telemetry_buffer: List[tuple] = []
_BUFFER_LIMIT = 50


async def insert_telemetry(frame: Dict[str, Any]) -> None:
    """Buffer a telemetry row; flushes every _BUFFER_LIMIT rows."""
    global _telemetry_buffer
    _telemetry_buffer.append((
        frame["mission_id"],
        frame["frame_id"],
        frame["timestamp"],
        frame["sim_time_s"],
        frame.get("phase"),
        frame.get("throttle"),
        frame.get("altitude_ft"),
        frame.get("ambient_temp_c"),
        frame.get("rpm"),
        frame.get("fuel_flow_lph"),
        json.dumps(frame.get("cht", [])),
        json.dumps(frame.get("egt", [])),
        frame.get("oil_pressure_kpa"),
        frame.get("oil_temp_c"),
        frame.get("vibration_rms"),
        frame.get("battery_voltage"),
        frame.get("alternator_current"),
        frame.get("injection_timing"),
        frame.get("injected_fault"),
        frame.get("fault_severity", 0.0),
    ))
    if len(_telemetry_buffer) >= _BUFFER_LIMIT:
        await flush_telemetry()


async def flush_telemetry() -> None:
    global _telemetry_buffer
    if not _telemetry_buffer:
        return
    db = get_db()
    await db.executemany(
        """INSERT OR IGNORE INTO telemetry
           (mission_id, frame_id, timestamp, sim_time_s, phase, throttle,
            altitude_ft, ambient_temp_c, rpm, fuel_flow_lph, cht, egt,
            oil_pressure_kpa, oil_temp_c, vibration_rms, battery_voltage,
            alternator_current, injection_timing, injected_fault, fault_severity)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        _telemetry_buffer,
    )
    await db.commit()
    _telemetry_buffer.clear()


# ══════════════════════════════════════════════════════════════════════════════
#  Health Snapshot Insert
# ══════════════════════════════════════════════════════════════════════════════


async def insert_health_snapshot(snap: Dict[str, Any]) -> None:
    db = get_db()
    await db.execute(
        """INSERT OR IGNORE INTO health_snapshots
           (mission_id, frame_id, sim_time_s, health_index, health_category,
            anomaly_score, is_anomaly, fault_class, fault_confidence,
            fault_severity, rul_minutes, rul_lo, rul_hi, rtb_alert,
            explanation, contributors)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            snap["mission_id"],
            snap["frame_id"],
            snap["sim_time_s"],
            snap.get("health_index"),
            snap.get("health_category"),
            snap.get("anomaly_score"),
            1 if snap.get("is_anomaly") else 0,
            snap.get("fault_class"),
            snap.get("fault_confidence"),
            snap.get("fault_severity"),
            snap.get("rul_minutes"),
            snap.get("rul_lo"),
            snap.get("rul_hi"),
            snap.get("rtb_alert", "NONE"),
            json.dumps(snap.get("explanation", [])),
            json.dumps(snap.get("contributors", [])),
        ),
    )
    await db.commit()


# ══════════════════════════════════════════════════════════════════════════════
#  Fault Injection Log
# ══════════════════════════════════════════════════════════════════════════════


async def log_fault_injection(
    mission_id: str, fault_type: str, severity: float,
    target_sensor: Optional[str] = None,
) -> None:
    db = get_db()
    now = datetime.utcnow().isoformat() + "Z"
    await db.execute(
        "INSERT INTO fault_injections (mission_id, fault_type, severity, target_sensor, injected_at) VALUES (?,?,?,?,?)",
        (mission_id, fault_type, severity, target_sensor, now),
    )
    await db.commit()


# ══════════════════════════════════════════════════════════════════════════════
#  Replay Queries
# ══════════════════════════════════════════════════════════════════════════════


async def get_replay_frames(
    mission_id: str,
    start_s: Optional[float] = None,
    end_s: Optional[float] = None,
    limit: int = 10_000,
) -> List[Dict[str, Any]]:
    db = get_db()
    conditions = ["mission_id = ?"]
    params: list = [mission_id]
    if start_s is not None:
        conditions.append("sim_time_s >= ?")
        params.append(start_s)
    if end_s is not None:
        conditions.append("sim_time_s <= ?")
        params.append(end_s)
    where = " AND ".join(conditions)
    params.append(limit)
    cursor = await db.execute(
        f"SELECT * FROM telemetry WHERE {where} ORDER BY sim_time_s ASC LIMIT ?",
        params,
    )
    rows = await cursor.fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["cht"] = json.loads(d["cht"]) if d.get("cht") else []
        d["egt"] = json.loads(d["egt"]) if d.get("egt") else []
        results.append(d)
    return results


async def get_health_timeline(mission_id: str) -> List[Dict[str, Any]]:
    db = get_db()
    cursor = await db.execute(
        """SELECT sim_time_s, health_index, health_category, anomaly_score,
                  is_anomaly, fault_class, fault_confidence, fault_severity,
                  rul_minutes, rul_lo, rul_hi, rtb_alert, explanation, contributors
           FROM health_snapshots
           WHERE mission_id = ?
           ORDER BY sim_time_s ASC""",
        (mission_id,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
#  Statistics Helpers
# ══════════════════════════════════════════════════════════════════════════════


async def get_mission_stats(mission_id: str) -> Dict[str, Any]:
    db = get_db()
    cursor = await db.execute(
        """SELECT
            COUNT(*) as frame_count,
            MAX(anomaly_score) as max_anomaly,
            MIN(health_index) as min_health,
            AVG(health_index) as avg_health,
            AVG(rul_minutes) as avg_rul,
            MIN(rul_minutes) as min_rul
           FROM health_snapshots WHERE mission_id = ?""",
        (mission_id,),
    )
    row = await cursor.fetchone()
    stats = dict(row) if row else {}

    # Fault distribution
    cursor2 = await db.execute(
        """SELECT fault_class, COUNT(*) as cnt
           FROM health_snapshots
           WHERE mission_id = ? AND fault_class != 'HEALTHY'
           GROUP BY fault_class""",
        (mission_id,),
    )
    fault_rows = await cursor2.fetchall()
    stats["fault_distribution"] = {r["fault_class"]: r["cnt"] for r in fault_rows}

    # Anomaly count
    cursor3 = await db.execute(
        "SELECT COUNT(*) as cnt FROM health_snapshots WHERE mission_id = ? AND is_anomaly = 1",
        (mission_id,),
    )
    anom = await cursor3.fetchone()
    stats["anomaly_count"] = anom["cnt"] if anom else 0

    return stats
