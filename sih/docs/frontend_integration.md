# Dashboard ↔ Backend Integration

The React dashboard in `frontend/` is the operator surface for the whole
backend: the simulator, the digital twin, the fault injector, the mission store,
the replay store and the report generator. This document records what is wired
to what, how to run it, and which defects the integration exposed.

For architecture and modelling detail see `mvp_architecture.md` and
`health_index_design.md`.

---

## Running it

Two processes. **The backend must be started from the repository root**, so that
`backend` is imported as one package and every module is loaded exactly once
(the original failure mode was a module loaded twice, once as `config` and once
as `backend.config`, which split the WebSocket client registry in two):

```bash
# terminal 1 — backend API + telemetry WebSocket on :8081
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8081
# or: backend/run_backend.sh   /   backend/run_backend.bat

# terminal 2 — dashboard on :3000
cd frontend && npm install && npm run dev
```

Open <http://localhost:3000>. The Vite dev proxy forwards `/api` and `/ws` to
`127.0.0.1:8081` (`frontend/vite.config.ts`); the production nginx config does
the same (`frontend/nginx.conf`), so no port is baked into the bundle.

Useful alternatives: `npm run typecheck`, `npm test`, `npm run build`.
API docs are served by the backend at `http://127.0.0.1:8081/docs`.

---

## What the dashboard covers

Live telemetry arrives over the WebSocket; everything else goes through
`src/services/api.ts`, which is the only module that talks HTTP. Panels read it
through `src/hooks/useApiResource.ts` (fetch + poll + loading + error state).

| View | Panel | Endpoints |
|---|---|---|
| Cockpit | health gauge, RTB HUD, sensor status, strip charts | `WS /ws/telemetry/{engine_id}` |
| Cockpit | `PhysicsResidualsPanel` — observed vs expected vs σ | `WS`, plus `GET /api/engine/{id}/state` |
| Mission | `MissionControlPanel` — start/stop, throttle, altitude | `POST /api/missions/start`, `POST /api/missions/{id}/stop`, `GET /api/simulation/status`, `POST /api/simulation/throttle`, `POST /api/simulation/altitude` |
| Mission | `MissionBrowser` — stored missions, stats, actions | `GET /api/missions`, `GET /api/missions/{id}` |
| Mission, Diagnostics, demo drawer | `FaultConsolePanel` — catalogue, injection, audit trail | `GET /api/faults/types`, `POST /api/faults/inject`, `POST /api/faults/clear`, `GET /api/faults/history` |
| Diagnostics | `MissionReplayToolbar` — load and scrub a stored mission | `POST /api/replay/start`, `GET /api/replay/frames/{id}`, `GET /api/replay/status`, `GET /api/reports/{id}/health-timeline` |
| Reports | `MissionReportPanel` — summary, advisories, timeline, download | `GET /api/reports/{id}`, `GET /api/reports/{id}/health-timeline`, `GET /api/reports/{id}/download` |
| Header | incident log modal | `GET /api/faults/history` |

Replay reconstructs a stored mission by joining the telemetry rows with the
health snapshots on `sim_time_s` (`buildReplayFrames` in `src/lib/adapters.ts`),
then pushes them into the same context the live socket feeds — so a replayed
sortie drives every gauge, chart and 3D view exactly as it drove them live.

---

## Defects this integration exposed

Each of these was found by exercising the real path end to end, and each is
fixed:

**The module could not start.** `backend/models/` (a package) shadowed
`backend/models.py`, making `FaultInjectionRequest` unimportable; `main.py`
imported bare module names while the routes imported `backend.…`, loading two
copies of the app's state. The schemas now live in `backend/models/schemas.py`
and `main.py` imports through the package.

**A healthy engine read `EMERGENCY`.** Two independent causes:

- The rule-based analyser scored residuals against hand-guessed constants
  instead of the fitted healthy baseline already in the repo
  (`ml/health_index.HEALTHY_RESIDUAL_STATS`). With `r_oil_t` modelled at
  σ = 1.5 °C against a real spread of ~22 °C, every healthy frame produced a
  z-score of −52 and a maximum-severity anomaly. It now uses the fitted
  baseline: healthy runs score ~21 anomaly / 0.21 severity with `HEALTHY`
  classification on 99.4 % of frames, while every injected fault still reaches
  100 with the correct class.
- A cold start was scored against a warm-engine baseline. While the cylinder
  heads are below 60 °C the index now holds a WATCH floor of 70 and reports
  `warming_up` with a plain-language explanation, instead of opening every
  mission in EMERGENCY. The flag is on the wire (`EngineState.warming_up`) and
  shown in the header.

**Faults leaked across missions.** Injecting a fault and then starting a new
mission left the fault active, so the new "healthy" mission opened degraded.
`POST /api/missions/start` now clears the fault set.

**Fault names were silently dropped.** An unrecognised fault or sensor channel
was ignored, so a demo button could look like it worked. `inject_fault` now
returns whether it accepted the fault; the REST route answers 400/422 and the
WebSocket replies `FAULT_REJECTED`. The console builds its buttons from
`GET /api/faults/types`, so it can only offer faults the engine has.

**Injections had no audit trail.** The `fault_injections` table was written only
by the REST route and read by nothing. The WebSocket path now logs too, and
`GET /api/faults/history` exposes it — that is what the incident log shows
(previously it fetched `/api/logs/download`, which does not exist).

**Mission summaries were never filled in.** `frame_count`,
`max_anomaly_score` and `min_health_index` stayed at their defaults, so a
finished mission looked empty and the replay/report pickers had nothing to
offer. They are now maintained during the run and finalised from the stored
snapshots on stop.

**The physics residuals panel had nothing to show.** `_compute_residuals`
returned only `channel`/`residual`/`unit`, although `SensorResidual` declares
`observed`, `expected` and `z_score`. All four are now filled (the `max`
channels report the worst cylinder, which is what makes them explainable).

**The replay toolbar called an endpoint that does not exist.** It fetched
`/api/mission/replay?start=…&end=…` and parsed invented fields, so its load
button always failed silently. It now uses the real replay and health-timeline
endpoints.

**Unicode in log lines aborted initialisation.** `ml/inference.py` printed `⚠`
inside `build_pipeline`'s exception handler; on a cp1252 console that raised
`UnicodeEncodeError`, which downgraded the caller to the fallback *and* dropped
the trained bundle's calibration. Warnings are now encoding-safe and the
backend reconfigures stdout/stderr to UTF-8 at startup.

---

## Known gaps

- **Replay streams client-side.** `ReplayService` can push frames over the
  socket, but `POST /api/replay/start` never calls `start()` — it validates the
  mission, reports the frame count and returns. The toolbar therefore plays back
  from `GET /api/replay/frames/{id}`. Wiring the service in would let replay
  drive a second client.
- **The models are still the rule-based fallback.** There is no trained bundle
  in `ml/models`, so `/health` reports `ml_models: fallback` and RUL is `null`
  until one is trained (`train.sh` / `train.bat`). The interface is the same
  either way.
- **Sensor-channel names are not validated.** A `SENSOR_DRIFT`/`SENSOR_DROPOUT`
  target that the generator does not know is accepted and then has no effect;
  the console offers the real channel names but the backend does not check them.
- **Missions stored before this change report `frame_count: 0`.** They are still
  replayable — the UI offers any mission that is not currently running — but
  their list rows show no frame count.
- **`POST /api/replay/stop`, `GET /api/missions/{id}/summary`** and the raw
  `engine` REST endpoints remain available and are exercised by tooling, but no
  panel currently calls them.
