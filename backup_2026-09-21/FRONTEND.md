# AeroTwin — Frontend Reference

Two frontends exist:

1. **Standalone** (`src/frontend/`) — plain HTML/JS, served by `serve.py` on `:8000`. This is what `run.bat` opens and what this document covers.
2. **React cockpit** (`sih/frontend/`) — Vite + React dashboard; its `CutawayTwinView` hosts the synced cutaway copy from `sih/frontend/public/cutaway/` and drives it through `aerotwin-bridge.js` (separate protocol, documented in that file).

## 1. Pages

| Page | Role |
|---|---|
| `index.html` | **Main dashboard.** AeroTwin chrome (header, nav sidebar, KPI cards, fault sliders, JSON drawer) with the **cutaway box as the main view** — `#cutawayBox` ships fullscreen (`cutawayFull` class) with the simulator iframe preloaded (`src="cutaway.html"`). Header controls: `⛶` expands/shrinks the box, `×` closes it (empties the iframe, releasing the second WebGL context). Fault sliders deep-link into `faults.html` with that fault preselected; RPM preset pills postMessage into the simulator. KPIs + JSON drawer render live `aerotwin-api.js` frames. |
| `cutaway.html` | The STL cutaway simulator (the old viewer, renamed): engine block/piston STLs, hand-control counting (`_hand.js` camera gesture tracking), phone pairing UI + QR. Hosted inside the dashboard's iframe and inside the React cockpit. |
| `telemetry.html` | **Telemetry Overview** — RPM/MAP/fuel/oil sparklines, altitude/throttle/oil-temp/vibration strip, 4-cyl CHT & EGT multi-line charts, EHI bar, anomaly score, RUL/RTB readouts. |
| `diagnostics.html` | **Cylinder Diagnostics** — per-cylinder cards with CHT/EGT bars + sparklines, NOMINAL/HOT/CRIT badges, thermal-spread chart with the 40 °C alert line. |
| `faults.html` | **Fault Injection Lab** — fault-type cards (labels from `GET /api/faults/types`), per-type severity sliders → `injectFault()`, active-faults banner from sim status, mission start/stop, live detection readout; reads `?fault=<TYPE>` deep-links. |
| `blackbox.html` | **Blackbox Logs** — missions table from the DB, per-mission report JSON + CSV download links, health-index timeline SVG with 60 %/30 % warning/critical lines. |
| `phone.html` | Phone companion: camera hand-tracking (counts extended fingers via MediaPipe-style landmarks), pairs to the desktop over WebRTC to drive the cutaway camera gesture control. |

Shared chrome: identical Tailwind CDN config (Space Grotesk / Inter / Material Symbols, the `background/surface/primary/secondary/tertiary` palette) and the same sidebar with per-page active states.

## 2. `aerotwin-api.js` — the shared client (`window.AEROTWIN_API`)

Loaded by every page. Connection ladder **WS → REST poll → demo generator**, with the mode always visible in each page's header chip (`LIVE` / `POLLING` / `DEMO MODE`).

### Data plane
| Member | Description |
|---|---|
| `flatten(state)` | Rich backend `EngineState` → flat frame the pages render (mirrors the React app's `adapters.ts`): numeric KPIs, `cht/egt` arrays, health/anomaly/fault/RUL fields, `sensor_status`, `residuals`, plus the untouched `raw` state. |
| `start()` | Opens `ws://<host>:8081/ws/telemetry/TAPAS-BH-201-001` (direct WS — browser to backend, no proxy). Falls back to REST polling after 3 s if the socket never opens; WS drops degrade to polling, and to the demo generator if REST also fails. Reconnect timer every 5 s. |
| `onFrame(fn)` / `onStatus(fn)` | Subscriptions; `onFrame` immediately replays the current frame. |
| `frame` / `status` / `history` | Latest flat frame, connection state (`live|polling|offline`), 240-frame ring buffer for charts. |

### Command surface (all REST, same-origin via proxy)
| Method | Backend call |
|---|---|
| `injectFault(type, severity, targetSensor?)` | `POST /api/faults/inject` |
| `clearFaults()` | `POST /api/faults/clear` |
| `faultTypes()` | `GET /api/faults/types` |
| `simStatus()` | `GET /api/simulation/status` |
| `setThrottle(v)` / `setAltitude(ft)` | `POST /api/simulation/throttle|altitude` |
| `startMission(name?, durationS?)` / `stopMission(id)` | `POST /api/missions/start` · `/api/missions/{id}/stop` |
| `missions(limit?)` / `mission(id)` / `missionSummary(id)` | `GET /api/missions...` |
| `healthTimeline(id)` / `report(id)` | `GET /api/reports/{id}/health-timeline` · `/api/reports/{id}` |
| `health()` | `GET /health` |
| `setDemoFault(type, severity)` | Feeds the offline demo generator a fault so the fault lab still demonstrates something without a backend; `isOffline()` reports demo mode. |

The demo generator (`demoFrame()`) synthesises a plausible cruise frame (wobbling 2400 RPM, 15 000 ft) and models OVERHEAT/VIBRATION/OIL fault families so pages stay alive in a pitch with zero infrastructure — frames are honestly labelled DEMO.

## 3. `serve.py` — static server + same-origin proxy

Standard-library only (`ThreadingHTTPServer`). Extras over `python -m http.server`:

- **REST proxy**: `GET|POST /api/*` and `GET /health` are forwarded to `127.0.0.1:8081` (urllib, 5 s timeout). Backend HTTP errors pass through with their status; an unreachable backend returns a clean 503 JSON (`"backend unreachable - is the sih backend running on 127.0.0.1:8081?"`). This is why the pages never hit CORS: the backend's allow-list covers only the React dev origins.
- **`GET /__lanip`** → `{"ip", "scheme", "port"}` — the page's own LAN address so it can build the phone-pairing QR (a browser cannot see the host's LAN IP itself).
- **WebRTC signaling relay** for phone pairing: `POST /__pair` `{offer}` → `{token}` (parks an offer under a one-time token, TTL 15 min), `GET /__pair/{token}` → `{offer}` (the phone fetches it), `POST /__pair/{token}/answer` `{answer}` (the phone posts its answer), `GET /__pair/{token}/answer` → `{state: waiting|answered, answer?}` (the desktop polls). All in-memory; sessions die with the server.
- **HTTPS listener** on `:8443` with a self-signed cert (`ensure_cert()` generates `cert.pem`/`key.pem` via openssl once) — phones refuse camera access over plain HTTP, so `phone.html` is served over TLS.
- Usage: `python serve.py [http-port=8000] [https-port=8443]`.

## 4. Phone pairing & WebRTC (`phone.html` + cutaway pairing UI)

Flow (one human step): desktop parks its WebRTC offer on serve.py under a one-time token → renders a QR whose link is `phone.html#p=<token>` → the phone scans it → `phone.html` fetches the offer, starts the camera, posts its answer back to the relay → the desktop's poll picks the answer up and the video connects. **No code is displayed, typed, copied or pasted on either side** — the QR link is the whole handshake. The desktop side lives in the pairing section of `cutaway.html` (`startPhonePair()` / `pollForAnswer()` / `acceptPhoneReply()`); signalling details are inline there.

## 5. Dashboard ↔ simulator bridge (iframe postMessage)

The dashboard embeds `cutaway.html` in `#cutawayFrame`:

- **RPM presets**: `index.html` posts `{type: "CUTAWAY_SET_RPM", rpm}` on preset clicks (Idle 1.2K / Cruise 2.4K / Takeoff 5.8K) and re-pushes the current RPM when the iframe reloads. The simulator maps `rpm / 3600` onto its `#speed` slider (auto-widening the slider max for Takeoff) and dispatches a real `input` event so all downstream readouts update. With the backend up, presets instead set the mission simulator's throttle (`rpm / 3600`, POST `/api/simulation/throttle`); the iframe only gets the postMessage if the backend call fails.
- **Backend sync (active, not just listening)**: every 5 s the dashboard GETs `/api/simulation/status` (restarting a mission if it died) and `/api/engine/{id}/state` (REST snapshot), then renders the frame and forwards the RPM into the iframe as `CUTAWAY_SET_RPM`, so KPIs and the engine animation follow the backend even when the websocket is down. The sim panel's **Sync** button runs one pass immediately.
- **Phone pairing**: "Pair phone" posts `{type: "CUTAWAY_REQUEST_QR"}`; the simulator makes its own WebRTC invite, parks it on serve.py under a token, and answers `{type: "CUTAWAY_SHOW_QR", dataUrl, caption}` (or `{error}`) with a QR that carries only `phone.html#p=<token>`. The handshake completes itself through the relay; the dashboard just watches for `{type: "CUTAWAY_PAIR_STATE", message, connected}`, which auto-closes the pop-up when connected. There is no paste box and no copyable payload anywhere in the flow.
- **Fullscreen**: `.cutawayFull` stretches the box over the viewport (not the Fullscreen API — the iframe's WebGL context is never interrupted); `Esc` exits; closing the box drops fullscreen.
- **Lifecycle**: closing the box sets the iframe `src` to `about:blank` (releases the second WebGL context); reopening restores `cutaway.html` — toggling no longer restarts the simulator on a mere hide/show.

## 6. React cockpit interop (`sih/frontend`)

- The cockpit hosts `sih/frontend/public/cutaway/*` — kept **byte-identical** to `src/frontend` (`index.html`→`cutaway/index.html`, `cutaway.html`→`cutaway/index.html` source, `phone.html`, STLs). After edits: `cp` the changed files into `public/cutaway/`, and a `vite build` refreshes `dist/cutaway/`.
- `aerotwin-bridge.js` expects these viewer globals/hooks in the hosted page: `#speed`, `TUNE`, `SYSTEMS`, `scene`, `renderer`, `bloomDefault`, `engineBlock`, `applySystemCut`, `pickAt` — all present in the synced cutaway.
- The React app talks to the same backend REST/WS (its own typed client in `src/services/api.ts` and frame mapping in `src/lib/adapters.ts`).
