# AeroTwin — Backend Reference

Package `sih/backend/` — FastAPI application, services, database, configuration.
Entry point: `sih/backend/main.py` → `app`. Run from `sih/` so the `backend.*` imports resolve:

```bash
cd sih && python -m uvicorn main:app --host 127.0.0.1 --port 8081
```

> **Module-identity rule:** all internal imports must use the `backend.` prefix (e.g. `from backend.database import ...`). Importing bare `database` creates a *second* module instance with its own DB handle — this was a real bug (routes saw "Database not initialized" while `init_db()` "succeeded").

---

## 1. `main.py` — application lifecycle

| Piece | Behaviour |
|---|---|
| `lifespan(app)` | On startup: `db.init_db()`, pre-initialises `anomaly` + `health` services (warms models), logs banner. On shutdown: stops the simulator if running, `flush_telemetry()`, `close_db()`. |
| CORS | Origins from `CORS_ORIGINS` (default React dev ports 3000/5173). The standalone frontend bypasses CORS via the serve.py proxy. |
| Exception handlers | Global 500 → `{error, detail, status_code}`; 404 → same shape. |
| Middleware | Logs any request slower than 100 ms as a warning. |
| Routers | `engine`, `mission`, `faults`, `replay`, `reports`, `simulation` (see API_REFERENCE.md). |
| `GET /`, `GET /health` | Banner + component health (see API_REFERENCE.md §1). |
| `WS /ws/telemetry/{engine_id}` | Delegates to `websocket_handler.ws_handler`. |

---

## 2. Services — `backend/services/`

All services are singletons obtained via `get_*_service()` / `get_simulator()`.

### 2.1 `simulator.py` — `SimulatorService`
The in-process telemetry producer (no external process). One instance.

| Member | Description |
|---|---|
| `start(mission_id, duration_s=600, ambient_offset_c=0.0, seed=None)` | Resets state (frame 0, time 0, clears ring buffer), builds `EngineModel` + empty `FaultInjector` from seed (default `SIM_SEED=42`), builds the default mission profile, spawns the asyncio tick task. No-op if already running. |
| `stop()` | Cancels the tick task; `is_running` becomes False. |
| `on_frame(cb)` / `remove_callback(cb)` | Register per-tick callbacks (mission route wires in `process_and_store`). Sync and async callbacks both supported. |
| `inject_fault(fault_type, severity=0.7, target_sensor=None, ramp_s=60)` | Appends a `FaultSpec` + runtime to the injector; records in `_active_faults`. Unknown types are ignored (logged). |
| `clear_faults()` | Removes all specs/runtimes/active map. |
| `set_throttle(t)` / `set_altitude(ft)` | Clamp-and-store overrides applied on the next tick (beat the mission profile). |
| `_run_loop()` | Every `1/hz` seconds: profile → (phase, throttle, altitude); apply overrides; `isa_conditions(altitude)` + ambient offset; `engine.step(...)`; `fault_injector.apply(row, t)`; build frame; push to `_recent_frames` (deque, 600 = 60 s @10 Hz) and `_last_frame`; fire callbacks; sleep the remainder. Loop ends when `sim_time >= duration_s` (`is_running` → False). |
| `_build_frame(row, phase, ambient_temp_c)` | Maps engine row → TelemetryFrame dict (arrays for cht/egt, `injected_fault` = comma-joined active names, `fault_severity` = max). |
| Properties | `is_running`, `mission_id`, `frame_id`, `sim_time`. |

### 2.2 `digital_twin.py` — `DigitalTwinService`
**The orchestrator.** `process_frame(frame) → EngineState dict`:

1. `_frame_to_row(frame)` — API frame → flat CSV-keyed row (`cht[0]→cht_c1`, `vibration_rms→vibration_rms_g`, `battery_voltage→battery_v`, …).
2. `_compute_residuals(row)` — via `ml.physics_baseline.expected_sensors/residual_summary`; builds `[{channel, residual, unit}]` (skips `r_oil_t`, units inferred from the channel name). Returns `{}, []` if the ML package is absent.
3. `anomaly_svc.predict_row(row)` — anomaly score + fault class (see §2.3).
4. `health_svc.compute(row, prediction)` — EHI (see §2.4).
5. `fault_svc.predict(row, prediction)` — criticality + action (see §2.5).
6. `rul_svc.estimate(row, prediction, health)` — RUL + RTB (see §2.6).
7. `_build_alerts(...)` — CRITICAL/ADVISORY alerts from EHI < 50/70, fault class with confidence > 0.5 (WARNING if severity < 0.7 else CRITICAL), and RTB alerts.
8. `_sensor_status(row)` — `True` per channel if present and not nan/empty; failures collected into `isolated_sensors`.
9. Assemble the full state dict (field-for-field listed in API_REFERENCE.md §2) incl. `processing_time_ms`.

### 2.3 `anomaly.py` — `AnomalyService`
- `_init_pipeline()`: `ml.inference.build_pipeline(settings.MODEL_DIR)` — the trained bundle if present, else the rule-based `FallbackAnalyzer`.
- `predict_row(row)`: stateful update+predict (uses the pipeline's `FeatureExtractor` window); `predict(row)` re-scores the current window.
- `_warmup_result()`: neutral HEALTHY/0-score output while the feature window warms.
- `_fallback(row)`: `FallbackAnalyzer.predict`; ultra-minimal vibration/RPM heuristic if even that fails; all numpy types coerced JSON-safe via `_to_floats`.

### 2.4 `health_index.py` — `HealthIndexService`
Wraps `ml.health_index.HealthIndexCalculator` (see ML_MODELS.md for the maths).
- `compute(row, prediction, t=None)` → calculator's full result (`ehi`, `category`, `trend`, `delta_5min`, `penalties`, `weights_used`, `data_quality`, `confidence`, `contributors`, `explanation`).
- `reset()` — called at every mission start so a healthy engine doesn't inherit a degraded EMA.
- `_fallback(row, prediction)` — rule-based EHI when ML is missing: `100 × (1 − 0.4·p_anomaly − 0.35·p_fault − 0.25·p_severity)` with the same category thresholds and contributor/explanation structure.

### 2.5 `fault_prediction.py` — `FaultPredictionService`
Stateless enrichment: maps `fault_class` → `criticality` (LUBRICATION_FAILURE 1.0 … SENSOR_DROPOUT 0.30, UNKNOWN 0.50) and → human `action` text ("Inspect oil pump, filter and for leaks; …"). `get_all_fault_types()` powers `GET /api/faults/types`.

### 2.6 `rul.py` — `RULService`
- Thresholds: RTB_CRITICAL ≤ **10 min**, RTB_ADVISORY ≤ **30 min**, endurance bar = **180 min**.
- `estimate(row, prediction, health_result)`: takes `rul_min/lo/hi` + `rul_conf` from the ML pipeline; if absent, `_slope_rul()` extrapolates `time-to-severity-0.9` from the severity slope; maps confidence to HIGH/MEDIUM/LOW; sets `rtb_alert`, `rtb_window_active`, and `progress_pct = rul/180×100` clamped to 0–100.

### 2.7 `report.py` — `ReportService`
`generate(mission_id)` → report dict (see API_REFERENCE.md §6): pulls mission + stats + health timeline from DB, splits anomaly/fault/RUL events, builds the executive summary text, priority-ordered maintenance advisories, sensor summary. Returns `None` for unknown missions (routes raise 404).

### 2.8 `replay.py` — `ReplayService`
`start(mission_id, callback, speed=1.0, start_s, end_s)` spawns a task that streams stored frames through `callback` at `1/speed` s cadence (assumes 1 Hz storage), honouring `MAX_REPLAY_FRAMES`. `stop()` cancels; `is_running`/`mission_id` exposed.

### 2.9 `websocket_handler.py`
- `ConnectionManager` — `connect()` accepts + sends `WELCOME`; `disconnect()` prunes; `broadcast()` fan-outs and drops dead sockets; `_send()` swallows per-client failures.
- `broadcast_frame(state)` — wraps the EngineState in `{type: "TELEMETRY", payload, timestamp}`.
- `broadcast_message(msg)` — arbitrary envelope (fault events, PONG, STATS).
- `ws_handler(ws)` — receive loop → `_handle_command`: `TRIGGER_FAULT`, `CLEAR_FAULTS`, `SET_THROTTLE`, `SET_ALTITUDE`, `PING`→`PONG`, `GET_STATS`→`STATS`; unknown actions logged. See API_REFERENCE.md §8 for the wire contract.

---

## 3. Database — `backend/database.py`

Async SQLite (`aiosqlite`), single connection, `data/aerotwin.db`. Write batching: telemetry rows are buffered and flushed by `flush_telemetry()` (mission stop, app shutdown, and periodic flush during missions).

### Tables

| Table | Purpose | Key columns |
|---|---|---|
| `engines` | Registered engines (seeded with `TAPAS-BH-201-001` / "DRDO Tapas-BH-201") | `engine_id` PK, `name`, `model` |
| `missions` | One row per mission | `mission_id` PK, `engine_id` FK, `name`, `status` (RUNNING/COMPLETED), `started_at`, `ended_at`, `duration_s`, `ambient_offset_c`, `frame_count`, `max_anomaly_score`, `min_health_index`, `faults_observed` (JSON) |
| `telemetry` | Every tick | `mission_id` + `frame_id` UNIQUE, `timestamp`, `sim_time_s`, `phase`, `throttle`, `altitude_ft`, `ambient_temp_c`, `rpm`, `fuel_flow_lph`, `cht`/`egt` (JSON strings), oil/vib/battery/alternator/timing, `injected_fault`, `fault_severity` |
| `fault_injections` | Audit trail of demo injections | `mission_id`, `fault_type`, `severity`, `target_sensor`, `injected_at` |
| `health_snapshots` | Per-tick ML output | UNIQUE(`mission_id`,`frame_id`), `health_index`, `health_category`, `anomaly_score`, `is_anomaly`, `fault_class`, `fault_confidence`, `fault_severity`, `rul_minutes`, `rul_lo`, `rul_hi`, `rtb_alert`, `explanation`/`contributors` (JSON) |

Indexes: `(mission_id, frame_id)` on telemetry and snapshots, `(mission_id, sim_time_s)`, `(mission_id)` on injections.

### Functions

| Function | Notes |
|---|---|
| `init_db()` / `close_db()` / `get_db()` | Connect, schema, seed engine. `get_db()` asserts initialisation (raises "Database not initialized"). |
| `create_mission(...)`, `get_mission(id)`, `update_mission(id, **kw)`, `list_missions(limit)` | Mission CRUD (list = newest first). |
| `insert_telemetry(frame)` / `flush_telemetry()` | Buffered tick writes; commit on flush. |
| `insert_health_snapshot(dict)` | One ML result row per frame. |
| `get_mission_stats(id)` | Aggregates: frame_count, avg/min health, anomaly count, fault_distribution, min_rul. |
| `log_fault_injection(mission_id, fault_type, severity, target_sensor)` | Audit row. |
| `get_health_timeline(id)` | All snapshots for a mission (charts + reports). |
| `get_replay_frames(id, start_s, end_s, limit)` | Time-windowed telemetry for replay/HTTP fallback. |

---

## 4. Schemas — `backend/models.py`

Pydantic models (single source of truth; mirrored in API_REFERENCE.md §9):

- Enums: `MissionPhase`, `FaultType`, `HealthCategory`, `AlertLevel`, `Trend`, `MissionStatus`, `Severity`.
- `TelemetryFrame` — the fundamental data unit (defaults included so partial rows are valid).
- `SensorResidual` (`channel, observed, expected, residual, z_score, unit`).
- `EngineState` — full digital-twin state consumed by dashboards.
- Requests: `MissionCreate`, `FaultInjectionRequest` (`severity` 0–1), `ReplayRequest` (`speed` 0.1–10), `ThrottleRequest`, `AltitudeRequest`.
- Responses: `MissionInfo`, `MissionSummary`, `FaultInjectionResponse`, `ReplayFrame`, `MissionReport`, `WSMessage`/`WSCommand`, `HealthCheck`, `ErrorResponse`.

---

## 5. Configuration — `backend/config.py`

`Settings` (pydantic-settings; env vars / `sih/.env` override, `get_settings()` cached singleton):

| Setting | Default | Meaning |
|---|---|---|
| `HOST` / `PORT` | `0.0.0.0` / `8081` | Bind address |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Comma-separated allow-list |
| `DATABASE_URL` / `DB_PATH` | `sqlite+aiosqlite:///data/aerotwin.db` / `data/aerotwin.db` | SQLite location (relative to `sih/`) |
| `WS_HEARTBEAT_INTERVAL` / `WS_MAX_CONNECTIONS` | 15 / 50 | WS tuning |
| `SIM_HZ` / `SIM_SEED` / `AMBIENT_OFFSET_C` | 10 / 42 / 0.0 | Simulator cadence, determinism, weather |
| `MODEL_DIR` / `USE_FALLBACK` | `ml/models` / True | Trained models dir; allow rule-based fallback |
| `DEFAULT_MISSION_DURATION_S` / `MAX_REPLAY_FRAMES` | 600 / 100 000 | Mission + replay caps |
| `DATA_DIR` / `REPORT_DIR` / `LOG_DIR` | `data` / `data/reports` / `logs` | Paths |
| `ENGINE_ID` / `NUM_CYLINDERS` | `TAPAS-BH-201-001` / 4 | Engine identity |
| `APP_NAME` / `APP_VERSION` / `DEBUG` / `LOG_LEVEL` | AeroTwin Digital Twin API / 1.0.0 / False / INFO | Meta |

---

## 6. Testing hooks

- `tests/` contains pytest suites (`test_fault_injector.py`, `test_engine_physics.py`, …) exercised by `sih/verify_env.py`.
- The simulator is fully deterministic for a fixed `SIM_SEED` — same seed ⇒ identical missions, which makes the ML evaluation reproducible.
