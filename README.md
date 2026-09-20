# AeroTwin Workspace

This workspace (`C:\Users\admin\Downloads\tmp`) holds **two systems** and the
shared assets they use. Everything else (one-off experiments, recovered
snapshots, dead placeholder code) has been consolidated or moved into
`archive_cleanup_2026-09-20.zip`.

## Documentation

Full documentation lives in [`docs/`](docs/README.md):

| Doc | Covers |
|---|---|
| [docs/README.md](docs/README.md) | Architecture index — how a telemetry frame flows end to end |
| [docs/API_REFERENCE.md](docs/API_REFERENCE.md) | Every REST endpoint + WebSocket protocol + schemas |
| [docs/BACKEND.md](docs/BACKEND.md) | Every backend service function, the database, config |
| [docs/ML_MODELS.md](docs/ML_MODELS.md) | Every AI model: anomaly, classifier, severity, RUL, health index, training |
| [docs/SIMULATOR.md](docs/SIMULATOR.md) | Engine physics, all 8 fault modes, mission profiles |
| [docs/FRONTEND.md](docs/FRONTEND.md) | Every page, the shared API client, serve.py proxy, pairing |

## The two systems

### 1. Standalone frontend — `src/frontend/`

A self-contained page set, served by `run.bat` (→ `python serve.py`,
http://localhost:8000):

* `index.html` — **the main page: the AeroTwin dashboard shell** (header,
  navigation sidebar, KPI cards, fault sliders, telemetry JSON drawer).
  Its canvas hosts the **cutaway box**, which fills the viewport and runs
  the cutaway simulator from the first frame (the `⛶` button shrinks it to
  a corner box; the `×` or "Hide cutaway" toggle empties it and releases
  its GPU context). The dashboard is wired live to the sih backend via
  `aerotwin-api.js` (REST proxy + WebSocket).
* `telemetry.html`, `diagnostics.html`, `faults.html`, `blackbox.html` —
  the sidebar pages: live telemetry charts, per-cylinder diagnostics, the
  fault-injection lab, and mission blackbox logs (see docs/FRONTEND.md).
* `cutaway.html` — the STL cutaway simulator: section plane, per-part
  tooltips, system cut slider, phone pairing, camera hand-tracking. This is
  the page embedded in the dashboard's cutaway box, and the page the test
  harnesses instrument.
* `phone.html` — the phone-side page for camera hand-tracking pairing.
* `serve.py` — stdlib static server; reports the LAN IP for phone pairing and
  serves an HTTPS listener for camera access.
* `_*.js` / `src/backend/_*.py` — browser-automation test harnesses (spliced
  into `cutaway.html` by the verify scripts; not loaded in normal use).

`src/frontend` is the **source of truth** for the viewer.

### 2. SIH digital twin — `sih/`

The full AeroTwin digital-twin project (React cockpit in `sih/frontend`,
Node backend in `sih/backend`, simulator, ML). See `sih/README.md`.
Launch with `sih\run_demo.bat`; services can also be managed with
`python sih/start_app.py start|stop|status`.

The cockpit hosts the same cutaway simulator from
`sih/frontend/public/cutaway/` (and the built copy in
`sih/frontend/dist/cutaway/`), driven over postMessage by
`aerotwin-bridge.js`. There the simulator file keeps the name `index.html`,
because the dashboard loads `/cutaway/index.html` directly.

## Keeping the cutaway copies in sync

`src/frontend/cutaway.html` owns the simulator. When it changes, sync it as
the sih cutaway viewer (note the name change):

    cp src/frontend/cutaway.html sih/frontend/public/cutaway/index.html

cp src/frontend/cutaway.html sih/frontend/dist/cutaway/index.html

and keep `phone.html` + the STL files identical in all three places. The
AeroTwin dashboard (`index.html`) is standalone-only; the sih cockpit has
its own React dashboard.

## Root launchers

* `run.bat` — serve the standalone viewer.
* `setup.bat` — create the local venv (the viewer is stdlib-only; SIH manages
  its own dependencies).
* `train.bat` — delegate to SIH training (`sih/train.bat`).
