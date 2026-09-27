# AeroTwin — API Reference

Base URL: `http://localhost:8081` (the sih FastAPI backend).
The standalone frontend calls these **same-origin** through `serve.py`'s proxy (`:8000/api/...` → `:8081/api/...`), so CORS never applies there.

Interactive, always-up-to-date docs: **`/docs`** (Swagger UI) · **`/redoc`** (ReDoc) · machine-readable **`/openapi.json`**.

Conventions:
- All bodies are JSON. All timestamps are ISO-8601 UTC with `Z` suffix.
- Errors are uniform: `{"error": "...", "detail": "...", "status_code": N}`.
- `engine_id` path parameters are currently informational — the singleton simulator serves whatever engine is running (default `TAPAS-BH-201-001`).

---

## 1. System

### `GET /`
API banner.

```json
{ "name": "AeroTwin Digital Twin API", "version": "1.0.0", "docs": "/docs", "health": "/health" }
```

### `GET /health`
Liveness + component status. Used by `run.bat` to detect an already-running backend and by the frontend's "Force Sync" button.

| Field | Meaning |
|---|---|
| `status` | `"ok"` |
| `version` | App version from settings |
| `uptime_s` | Seconds since process start |
| `components.ml_models` | `loaded` (bundle.json found) · `fallback` (models missing, rules active) · `error` |
| `components.simulator` | `running` \| `idle` |
| `components.websocket_clients` | Connected WS client count |
| `components.database` | `"sqlite"` |

---

## 2. Engine — `/api/engine`

Read-side of the digital twin. All endpoints return **503** `{"detail": "Simulation not running"}` when no mission is active. The twin state is cached per `frame_id` — repeated polls between frames are free.

### `GET /api/engine/{engine_id}/state`
The complete EngineState — the single richest read. This is also the payload of every WS `TELEMETRY` message.

Returns: `engine_id`, `mission_id`, `timestamp`, `frame_id`, plus:

| Group | Fields |
|---|---|
| Observed | `observed` — the raw TelemetryFrame (see §9) |
| Physics | `expected` — map of channel → expected healthy value; `residuals` — `[{channel, residual, unit}]` |
| Health | `health_index` (0–100), `health_category` (NORMAL/WATCH/WARNING/CRITICAL/EMERGENCY), `health_trend` (stable/declining/improving), `health_delta_5min`, `health_confidence` (HIGH/MEDIUM/LOW), `health_explanation` (human-readable lines), `health_contributors` (`[{component, penalty, label}]`) |
| Anomaly | `anomaly_score` (0–100), `is_anomaly` |
| Fault | `fault_class`, `fault_confidence` (0–1), `fault_severity` (0–1), `fault_criticality` (0–1), `fault_action` (maintenance text) |
| RUL | `rul_minutes`, `rul_lo`, `rul_hi` (68% interval), `rul_confidence`, `rul_trend`, `rtb_alert` (NONE/RTB_ADVISORY/RTB_CRITICAL), `rtb_window_active`, `progress_pct` |
| Sensors | `sensor_status` (`{channel: bool}`), `isolated_sensors` (list) |
| Meta | `alerts` (`[{level, message, type}]`), `processing_time_ms` |

### `GET /api/engine/{engine_id}/telemetry?limit=100`
Last `limit` (default 100, max 600) raw telemetry frames from the simulator's in-memory ring buffer. Empty (not 404) before any frames exist. Response: `{"engine_id", "frames": [TelemetryFrame...], "count"}`.

### `GET /api/engine/{engine_id}/health`
Health slice only: `health_index`, `category`, `trend`, `delta_5min`, `confidence`, `contributors`, `explanation`.

### `GET /api/engine/{engine_id}/faults`
Fault slice only: `fault_class`, `confidence`, `severity`, `criticality`, `action`, `anomaly_score`, `is_anomaly`.

### `GET /api/engine/{engine_id}/rul`
RUL slice only: `rul_minutes`, `rul_lo`, `rul_hi`, `confidence`, `trend`, `rtb_alert`, `rtb_window_active`, `progress_pct`.

---

## 3. Missions — `/api/missions`

A *mission* is one simulated flight run: it creates a DB record, starts the simulator tick loop, and pipes every frame through ML → SQLite → WebSocket.

### `POST /api/missions/start`
Starts a mission. Request (`MissionCreate`):

```json
{
  "engine_id": "TAPAS-BH-201-001",   // optional, default shown
  "duration_s": 600,                 // optional, default 600
  "ambient_offset_c": 0.0,           // optional hot-weather offset (ISA + N °C)
  "name": "Demo flight",             // optional label
  "profile": "default"               // default | test_flight | manual
}
```

`profile` selects the mission plan: `default` is the ~99-minute full mission, `test_flight` the compressed ~2.5-minute idle→takeoff→cruise→landing demo, and `manual` the interactive idle-parked session (engine holds ground idle until a throttle command arrives — the dashboard presets/slider and the phone controller fly from there).

Response:
```json
{ "mission_id": "<uuid4>", "engine_id": "...", "status": "RUNNING",
  "duration_s": 600, "started_at": "2026-09-20T10:00:00Z" }
```

Notes: resets the health-index EMA (a fresh mission must not inherit the previous mission's degraded score). Only one simulator exists; starting while running re-wires the frame callback to the new mission. Fault injections require a running mission.

### `POST /api/missions/{mission_id}/stop`
Stops the simulator, flushes buffered telemetry to SQLite, sets status `COMPLETED` and stamps `ended_at`. **404** if the mission id is unknown. Stopping an already-stopped id is a no-op that returns the stored status.

### `GET /api/missions?limit=50`
`{"missions": [MissionInfo...], "count"}` — newest first, each row: `mission_id, engine_id, name, status, started_at, ended_at, duration_s, frame_count, max_anomaly_score, min_health_index, faults_observed`.

### `GET /api/missions/{mission_id}`
Mission row + aggregate `stats`: `frame_count`, `avg_health`, `min_health`, `anomaly_count`, `fault_distribution` (`{class: count}`), `min_rul`. **404** if unknown.

### `GET /api/missions/{mission_id}/summary`
Full mission report (identical shape to `GET /api/reports/{mission_id}` — see §6). **404** if unknown.

---

## 4. Fault injection — `/api/faults`

### `POST /api/faults/inject`
Injects a fault into the running simulation. **400** if no mission is running.

Request (`FaultInjectionRequest`):
```json
{
  "fault_type": "OVERHEATING",      // enum, see below
  "severity": 0.85,                 // 0.0–1.0, default 0.7
  "target_sensor": "egt_c3"         // optional; for SENSOR_DRIFT / SENSOR_DROPOUT
}
```

`fault_type` enum (`FaultType`):
`HEALTHY` · `INJECTOR_DEGRADATION` · `MISFIRE` · `LUBRICATION_FAILURE` · `OVERHEATING` · `SENSOR_DRIFT` · `SENSOR_DROPOUT` · `ABNORMAL_VIBRATION` · `ALTERNATOR_DEGRADATION`

Response: `{"fault_type", "severity", "injected_at", "mission_id"}`.
Side effects: fault is logged to `fault_injections` table; `FAULT_INJECTED` broadcast to all WS clients; effects **ramp in over 60 s** (`ramp_s=60`) from injection time. Unknown fault types are silently ignored by the simulator.

### `POST /api/faults/clear`
Removes all active faults. Response: `{"status": "cleared", "mission_id"}`. Broadcasts `FAULTS_CLEARED`.

### `GET /api/faults/types`
`{"fault_types": [{type, criticality, action}...]}` — the 8 faultable classes with mission-safety criticality (LUBRICATION_FAILURE 1.0, OVERHEATING 0.90, MISFIRE 0.75, ABNORMAL_VIBRATION 0.70, INJECTOR_DEGRADATION 0.65, ALTERNATOR_DEGRADATION 0.50, SENSOR_DRIFT 0.35, SENSOR_DROPOUT 0.30) and the recommended maintenance action text.

---

## 5. Simulation controls — `/api/simulation`

### `GET /api/simulation/status`
```json
{ "is_running": true, "mission_id": "...", "frame_id": 1234,
  "sim_time_s": 123.4, "hz": 10, "active_faults": ["OVERHEATING"],
  "phase": "CRUISE", "profile": "test_flight",
  "throttle": 0.78, "throttle_manual": false }
```

`throttle` is the effective commanded throttle; `throttle_manual` is true while an interactive override is active (dashboard slider, preset, or phone controller).

### `POST /api/simulation/throttle`
Body `{"throttle": 0.0–1.0}` (validated). Overrides the mission profile's throttle from the next tick. **Auto-starts an interactive `manual` session when no mission is running**, so the dashboard slider and the phone controller work the moment a page opens. Response: `{"throttle", "status": "set", "mission_id", "auto_started"}`.

### `POST /api/simulation/throttle/release`
Drops the interactive override and hands throttle control back to the mission profile (in a `manual` session, that parks the engine at ground idle). **400** if not running. Response: `{"status": "released"}`.

### `POST /api/simulation/altitude`
Body `{"altitude_ft": 0–45000}` (validated). Same override semantics as the throttle endpoint, including auto-start. Response: `{"altitude_ft", "status": "set", "mission_id", "auto_started"}`.

---

## 6. Reports — `/api/reports`

### `GET /api/reports/{mission_id}`
Post-mission analysis report. **404** if unknown mission. Contains:

- `mission` — full mission row
- `executive_summary` — plain-text summary (frames, avg/min health, anomaly count, fault classes, min RUL)
- `health_timeline` — up to 500 downsampled health snapshots
- `anomaly_events` — snapshots where `is_anomaly`
- `fault_predictions` — snapshots with a non-HEALTHY class
- `rul_timeline` — snapshots with a RUL value (≤500)
- `maintenance_advisories` — `[{priority, action, reason}]` derived from the fault distribution (CRITICAL lubrication → HIGH overheating → MEDIUM injector/vibration → LOW "none required")
- `sensor_summary` — snapshot count, fault-class distribution, avg health
- `environmental_summary`, `generated_at`

### `GET /api/reports/{mission_id}/download`
Same report as an attachment (`Content-Disposition: attachment; filename=report_<id8>.json`).

### `GET /api/reports/{mission_id}/health-timeline`
`{"mission_id", "count", "data": [snapshot...]}` — the full, untruncated timeline for charting.

---

## 7. Replay — `/api/replay`

### `POST /api/replay/start`
Loads a stored mission for replay. Body (`ReplayRequest`): `{"mission_id", "speed": 1.0 (0.1–10), "start_s": null, "end_s": null}`. Returns `{"mission_id", "frame_count", "speed", "status": "ready", "message"}`. **404** if mission unknown. Streaming itself happens over the WebSocket (frames pushed at `speed`).

### `GET /api/replay/frames/{mission_id}?start_s=&end_s=&limit=5000`
HTTP fallback: `{"mission_id", "count", "data": [frames...]}` pulled straight from the `telemetry` table.

### `GET /api/replay/status`
`{"is_running", "mission_id", "speed"}` of the replay service singleton.

---

## 8. WebSocket — `ws://localhost:8081/ws/telemetry/{engine_id}`

`{engine_id}` is accepted but unused (single simulator). One connection receives everything: live frames, replay frames, fault notifications.

### Server → Client

| `type` | When | Payload |
|---|---|---|
| `WELCOME` | On connect | `{server_time, connected_clients}` |
| `TELEMETRY` | Every processed frame (10 Hz) | full EngineState (same shape as `GET /api/engine/{id}/state`), plus envelope `timestamp` |
| `FAULT_INJECTED` | Fault injected (REST or WS) | `{fault_type, severity, mission_id?}` |
| `FAULTS_CLEARED` | Faults cleared | `{mission_id?}` |
| `PONG` | Reply to `PING` | `{server_time}` |
| `STATS` | Reply to `GET_STATS` | `{is_running, frame_id, sim_time_s, connected_clients}` |

### Client → Server (JSON, `{"action": ...}`)

| Action | Fields | Effect |
|---|---|---|
| `TRIGGER_FAULT` | `fault` (type), `severity` (0–1), `sensor` (optional) | Injects if sim running; broadcasts `FAULT_INJECTED` |
| `CLEAR_FAULTS` | — | Clears; broadcasts `FAULTS_CLEARED` |
| `SET_THROTTLE` | `throttle` 0–1 | Override throttle |
| `SET_ALTITUDE` | `altitude_ft` 0–45000 | Override altitude |
| `PING` | — | Server replies `PONG` (broadcast) |
| `GET_STATS` | — | Server replies `STATS` (broadcast) |

Unknown actions are logged and ignored. Malformed JSON closes the error path and disconnects the client. Dead sockets are pruned on the next broadcast.

---

## 9. Shared schemas

### TelemetryFrame (what the simulator emits / `observed` contains)
`frame_id` int · `timestamp` · `engine_id` · `mission_id` · `sim_time_s` · `phase` (STARTUP/TAKEOFF/CLIMB/CRUISE/ENDURANCE/DESCENT/LANDING) · `throttle` 0–1 · `altitude_ft` · `ambient_temp_c` · `rpm` · `fuel_flow_lph` · `cht[4]` °C · `egt[4]` °C · `oil_pressure_kpa` · `oil_temp_c` · `vibration_rms` g · `battery_voltage` V · `alternator_current` A · `injection_timing` ° · `injected_fault` (string \| null) · `fault_severity` 0–1.

> The SQLite `telemetry` table stores `cht`/`egt` as JSON strings; the CSV-keyed ML row uses `cht_c1..c4`, `egt_c1..c4`, `vibration_rms_g`, `battery_v`, `alternator_a`, `injection_timing_deg` — `DigitalTwinService._frame_to_row()` does that mapping.

### MissionCreate / ReplayRequest / ThrottleRequest / AltitudeRequest
See §3, §5, §7 — all validated by pydantic (`severity` 0–1, `throttle` 0–1, `altitude_ft` 0–45000, `speed` 0.1–10).

### Status / alert vocabularies
- Health categories: NORMAL ≥ 85 · WATCH 70–84 · WARNING 50–69 · CRITICAL 30–49 · EMERGENCY < 30
- Alert levels: NONE · WATCH · ADVISORY · CRITICAL
- RTB: NONE · RTB_ADVISORY (RUL ≤ 30 min) · RTB_CRITICAL (RUL ≤ 10 min)
- Mission status: IDLE · RUNNING · PAUSED · COMPLETED · FAULT_INJECTED (DB uses RUNNING/COMPLETED)

---

## 10. Frontend↔simulator postMessage (within the standalone dashboard)

Not a backend API, but part of the page contract: the AeroTwin dashboard (`index.html`) drives the embedded cutaway simulator (`cutaway.html` iframe) with `iframe.contentWindow.postMessage({type: "CUTAWAY_SET_RPM", rpm}, "*")`. The simulator maps `rpm / 3600` onto its `#speed` slider (widening the slider max if needed) and dispatches a real `input` event. The preset pills (Idle 1.2K / Cruise 2.4K / Takeoff 5.8K) use this.
