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
| `setThrottle(v)` / `setAltitude(ft)` | `POST /api/simulation/throttle|altitude` (auto-starts an interactive session when none is running) |
| `releaseThrottle()` | `POST /api/simulation/throttle/release` — hands control back to the mission profile |
| `startMission(name?, durationS?)` / `stopMission(id)` | `POST /api/missions/start` · `/api/missions/{id}/stop` |
| `missions(limit?)` / `mission(id)` / `missionSummary(id)` | `GET /api/missions...` |
| `healthTimeline(id)` / `report(id)` | `GET /api/reports/{id}/health-timeline` · `/api/reports/{id}` |
| `health()` | `GET /health` |
| `setDemoFault(type, severity)` | Feeds the offline demo generator a fault so the fault lab still demonstrates something without a backend; `isOffline()` reports demo mode. |

The demo generator (`demoFrame()`) synthesises a plausible cruise frame (wobbling 2400 RPM, 15 000 ft) and models OVERHEAT/VIBRATION/OIL fault families so pages stay alive in a pitch with zero infrastructure — frames are honestly labelled DEMO.

## 3. `serve.py` — static server + same-origin proxy

Standard-library only (`ThreadingHTTPServer`). Extras over `python -m http.server`:

- **REST proxy**: `GET|POST /api/*` and `GET /health` are forwarded to `127.0.0.1:8081` (urllib, 5 s timeout). Backend HTTP errors pass through with their status; an unreachable backend returns a clean 503 JSON (`"backend unreachable - is the sih backend running on 127.0.0.1:8081?"`). This is why the pages never hit CORS: the backend's allow-list covers only the React dev origins.
- **`GET /__lanip`** → `{"ip", "scheme", "port"}` — the page's own LAN address so it can build the phone-pairing QR (a browser cannot see the host's LAN IP itself). When a public origin is available (see below) the response also carries `"public"` — the pages prefer it, so the QR works from any network — and, to local requests only, the relay access `"key"` when one is configured.
- **Worldwide pairing (ngrok)**: serve.py polls ngrok's local API (`127.0.0.1:4040/api/tunnels`) every 5 s; when an HTTPS tunnel to the frontend is up, the pairing QR carries its public URL instead of the LAN address, so **any phone on Earth can pair**, not just phones on the same Wi-Fi. `AEROTWIN_PUBLIC_ORIGIN` overrides the discovered URL. `start_app.py` starts the tunnel automatically when the ngrok binary and an authtoken are present (`NGROK_AUTHTOKEN` env var or `ngrok config add-authtoken` run once; `AEROTWIN_NGROK_DOMAIN` pins a reserved domain).
- **`GET /__ice`** → `{"iceServers": [...], "turn": bool}` — the STUN/TURN list both WebRTC peers load before pairing. Default is Google STUN; setting `AEROTWIN_TURN_URL` (+ `_USER`, `_CRED`) adds a TURN relay, which is what keeps the camera video alive when the phone is on mobile data behind carrier CGNAT — the one case STUN alone cannot pair.
- **Access key**: with `AEROTWIN_KEY` set, every phone-side relay call (`POST /__pair` (offer parking, except from this machine), `GET /__pair/{token}`, `POST /__pair/{token}/answer`, `POST /__ctl`, and `/__ice` from non-local callers) must present the key — `?key=` on the URL or the `x-aerotwin-key` header. The QR link carries it automatically, so a legitimately scanned phone still pairs with zero human steps while strangers on the internet get a 403. Set it whenever the tunnel is up.
- **WebRTC signaling relay** for phone pairing: `POST /__pair` `{offer}` → `{token}` (parks an offer under a one-time token, TTL 15 min), `GET /__pair/{token}` → `{offer}` (the phone fetches it), `POST /__pair/{token}/answer` `{answer}` (the phone posts its answer), `GET /__pair/{token}/answer` → `{state: waiting|answered, answer?}` (the desktop polls). All in-memory; sessions die with the server.
- **HTTPS listener** on `:8443` with a self-signed cert (`ensure_cert()` generates `cert.pem`/`key.pem` via openssl once) — phones refuse camera access over plain HTTP, so `phone.html` is served over TLS. (The ngrok URL is already HTTPS, so tunnel-paired phones skip this entirely.)
- Usage: `python serve.py [http-port=8000] [https-port=8443]`.

## 4. Phone pairing & WebRTC (`phone.html` + cutaway pairing UI)

Flow (one human step): desktop parks its WebRTC offer on serve.py under a one-time token → renders a QR whose link is `phone.html#p=<token>` → the phone scans it → `phone.html` fetches the offer, starts the camera, posts its answer back to the relay → the desktop's poll picks the answer up and the video connects. **No code is displayed, typed, copied or pasted on either side** — the QR link is the whole handshake. The desktop side lives in the pairing section of `cutaway.html` (`startPhonePair()` / `pollForAnswer()` / `acceptPhoneReply()`); signalling details are inline there.

**From any network, not just the LAN.** With the ngrok tunnel up (`start_app.py` starts it when ngrok + `NGROK_AUTHTOKEN` are available), the QR carries the tunnel's public URL — a phone on mobile data on the other side of the planet scans the same QR and pairs the same way: every phone-side call (offer fetch, answer POST, `/__ctl` command fallback) is same-origin to `phone.html` and rides the tunnel. Both peers now also load `/__ice`, so a configured TURN relay covers the camera video on strict carrier NATs. `AEROTWIN_KEY` gates the exposed relay endpoints; the QR link carries the key (`phone.html?key=…#p=…`) so the human flow is unchanged. LAN pairing keeps working exactly as before when no tunnel is running.

## 5. Dashboard ↔ simulator bridge (iframe postMessage)

The dashboard embeds `cutaway.html` in `#cutawayFrame`:

- **RPM presets**: `index.html` posts `{type: "CUTAWAY_SET_RPM", rpm}` on preset clicks (Idle 1.2K / Cruise 2.4K / Takeoff 5.8K) and re-pushes the current RPM when the iframe reloads. With the backend up, presets instead set the mission simulator's throttle (`rpm / 3600`, POST `/api/simulation/throttle`); the iframe only gets the postMessage if the backend call fails. The sim treats host RPM as a **throttle command**: its speed model (`SPEED`) eases the real crank rate toward the commanded value, so the engine visibly spools up and down between presets instead of snapping.
- **Engine state / burst watch**: every frame (and every 5 s sync) the dashboard posts `{type: "CUTAWAY_ENGINE_STATE", rpm, aboutToBurst, overLimit, detail, health}` into the sim. `aboutToBurst` comes from the backend's `anomaly_score >= 0.55`, `overLimit` from `rpm >= 6400` or `rtb_alert === "RTB_CRITICAL"`. The sim's HUD turns amber with "ABOUT TO BURST" in the warn band and red with "OVERSPEED" at the limit; at the limit it protects itself by cutting the commanded throttle to a fast idle until the overspeed clears. `window.panicTest()` drives the backend throttle to 1.0 to demo the whole chain.
- **Interactive kinematics**: grabbing the crankshaft, a piston, a connecting rod or the propeller and dragging cranks the engine by hand — the drag kicks the real crank rate (capped), and the whole hierarchy (pistons via the slider-crank equation, rods, cams at half speed, valves, propeller, flywheel) answers through it. Friction then coasts the rate back to the commanded throttle. Dragging does not open the part panel; a plain click still does.
- **Backend sync (active, not just listening)**: every 5 s the dashboard GETs `/api/simulation/status` (restarting the interactive `manual` session if it died) and `/api/engine/{id}/state` (REST snapshot), then renders the frame and forwards the RPM into the iframe as `CUTAWAY_SET_RPM`, so KPIs and the engine animation follow the backend even when the websocket is down. The sim panel's **Sync** button runs one pass immediately.
- **Engine control bar** (bottom of the canvas, one strip): **ENGINE** presets (Idle / Cruise / Takeoff → commanded throttle, engine spools there), **FLIGHT** transport (Test Flight / Abort + the phase chip + "To Idle"), **MANUAL** throttle stick (drag; the chip shows MANUAL while the stick is in command), and the actions (Pair phone, Fault Test). The throttle floor is 5 % so the engine idles instead of stopping. Abort spools the engine back down to idle via `releaseThrottle()`.
- **KPI fluctuation chips**: each KPI card shows `▲/▼ <delta>` since the previous frame (RPM whole units, temps/oil to 0.1), with a pop animation on change and "hold" when flat.
- **Phone controller**: after pairing (below), `phone.html` becomes a live throttle lever for the dashboard. Commands `{cmd: "throttle"|"preset"|"flight"|"abort"|"release", value}` travel over the WebRTC data channel (relayed by the sim iframe as `PHONE_CMD` postMessages) with a REST fallback through serve.py's `POST /__ctl` queue, which the dashboard polls (`GET /__ctl?since=<cursor>`). The dashboard publishes engine state back (`PHONE_STATE` postMessage → data channel) so the phone shows phase, RPM and throttle live.
- **Phone pairing**: "Pair phone" posts `{type: "CUTAWAY_REQUEST_QR"}`; the simulator makes its own WebRTC invite, parks it on serve.py under a token, and answers `{type: "CUTAWAY_SHOW_QR", dataUrl, caption}` (or `{error}`) with a QR that carries only `phone.html#p=<token>`. The handshake completes itself through the relay; the dashboard just watches for `{type: "CUTAWAY_PAIR_STATE", message, connected}`, which auto-closes the pop-up when connected. There is no paste box and no copyable payload anywhere in the flow.
- **Fullscreen**: `.cutawayFull` stretches the box over the viewport (not the Fullscreen API — the iframe's WebGL context is never interrupted); `Esc` exits; closing the box drops fullscreen.
- **Lifecycle**: closing the box sets the iframe `src` to `about:blank` (releases the second WebGL context); reopening restores `cutaway.html` — toggling no longer restarts the simulator on a mere hide/show.

## 6. React cockpit interop (`sih/frontend`)

- The cockpit hosts `sih/frontend/public/cutaway/*` — kept **byte-identical** to `src/frontend` (`index.html`→`cutaway/index.html`, `cutaway.html`→`cutaway/index.html` source, `phone.html`, STLs). After edits: `cp` the changed files into `public/cutaway/`, and a `vite build` refreshes `dist/cutaway/`.
- `aerotwin-bridge.js` expects these viewer globals/hooks in the hosted page: `#speed`, `TUNE`, `SYSTEMS`, `scene`, `renderer`, `bloomDefault`, `engineBlock`, `applySystemCut`, `pickAt` — all present in the synced cutaway.
- The React app talks to the same backend REST/WS (its own typed client in `src/services/api.ts` and frame mapping in `src/lib/adapters.ts`).
