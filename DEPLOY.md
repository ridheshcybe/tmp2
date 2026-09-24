# DEPLOY.md — Running and Deploying AeroTwin

> **LIVE NOW:** https://aerotwin-up6k.onrender.com (Render free tier,
> auto-deploys on push to `feature/awwwards-overnight-showcase`).
> Verified 2026-09-23: health, dashboard, docs, mission lifecycle, fault
> injection and WebSocket streaming all confirmed working in production.
>
> Hardening fixes in this branch (all smoke-tested in Docker + production):
> backend ships `ml`/`simulator` packages so real ML code runs (was silent
> fallback), the frame→DB→WebSocket pipeline actually stores data, missions
> auto-complete and flush their tail frames, WebSockets survive garbage
> input and slow clients, error responses no longer leak internals.

---

## Part 1 — Run it locally (this always works)

### One-time setup

**WHERE:** `D:\tmp` (repo root), PowerShell or double-click.

```powershell
.\setup.bat
```

Creates `venv\` and installs the backend dependencies (FastAPI, numpy,
scikit-learn, …). The frontend needs nothing — it is standard-library Python.
Takes 2–5 minutes.

### Every day after that

```powershell
.\run.bat
```

Starts, then opens the dashboard automatically:

| Service | URL | What it is |
|---|---|---|
| **Dashboard** | http://localhost:8000/index.html | Full AeroTwin cockpit (cutaway, KPIs, faults) |
| **Showcase** | http://localhost:8000/showcase.html | The cinematic single-page showcase |
| Backend API | http://127.0.0.1:8081/health | FastAPI + simulator + ML |
| API docs | http://127.0.0.1:8081/docs | Swagger UI |

The dashboard (`:8000`) proxies `/api` to the backend (`:8081`) — you never talk
to `:8081` directly except for `/docs`.

### Stop

```
venv\Scripts\python sih\start_app.py stop
```

(or just close the terminals / Ctrl+C and re-run `run.bat` later — `start_app.py`
skips anything already running, so re-running is always safe).

### If something didn't start

Logs live in `sih\.backend.log` and `sih\.frontend.log`. Check status any time:

```
venv\Scripts\python sih\start_app.py status
```

---

## Part 2 — Share it from your PC right now (ngrok, free, 2 minutes)

Your machine is **already wired for this**: `run.bat` auto-starts an ngrok tunnel
when ngrok is installed *and* authenticated — and yours is. It only failed once
because the installed agent (3.3.1) is older than the minimum your ngrok account
accepts (3.20.0): `ERR_NGROK_121`.

### Fix (once)

**WHERE:** any terminal.

```powershell
ngrok update
```

(or download the current version from https://ngrok.com/download and replace the
binary — your authtoken config at `%LOCALAPPDATA%\ngrok\ngrok.yml` is kept).

### Then

```powershell
.\run.bat
```

The startup banner **prints the public URL directly** (`PUBLIC : https://…ngrok-free.app`);
it is also available at `curl http://127.0.0.1:4040/api/tunnels` while running.

Share `https://<random>.ngrok-free.app/index.html` (dashboard) or
`/showcase.html`. Because `serve.py` detects the tunnel automatically, the
**phone-pairing QR works from any phone on any network** — the QR re-reads the
current tunnel URL on every generation, so even the free tier's rotating URLs
always land in a freshly drawn QR. Free ngrok shows each visitor a one-time
interstitial ("Visit Site").

**Optional — pin a stable URL:** reserve a static domain at
https://dashboard.ngrok.com (free), set it once, and the tunnel URL never
changes again:

```powershell
setx AEROTWIN_NGROK_DOMAIN "your-name.ngrok-free.dev"   # permanent env var
```

> While the tunnel is up, set `AEROTWIN_KEY` to a secret string to require it in
> the pairing QR, so only someone who scanned *your* QR can drive the relays.

---

## Part 3 — Put it on the internet 24/7 free (Render, recommended)

No credit card. The service sleeps after 15 min idle (~50 s wake) and includes
750 free instance-hours/month. The repo already contains the three files needed:
`Dockerfile`, `.dockerignore`, `render.yaml`.

### 3.1 — Push to GitHub

**WHERE:** github.com + your terminal.

1. Create a **private** repo at https://github.com/new — do **not** add a README.
2. From `D:\tmp`:

```bash
git remote add origin https://github.com/<YOUR_USER>/aerotwin.git
git push -u origin feature/awwwards-overnight-showcase
```

(Backups in this workspace are excluded from the Docker build by `.dockerignore`,
so push size is the only cost.)

### 3.2 — Service already created ✅

The service exists: **aerotwin** → `https://aerotwin-up6k.onrender.com`
(free plan, Singapore region, Python runtime, autoDeploy on commit).

Environment variables (managed via the Render MCP):

```
AEROTWIN_SERVE_FRONTEND = 1
CORS_ORIGINS            = https://aerotwin-up6k.onrender.com
AEROTWIN_FRONTEND_DIR   = /opt/render/project/src/src/frontend
```

> Optional manual step (30 s, dashboard-only): Service → Settings →
> **Health Check Path** → `/health` → Save. The REST API cannot modify
> service settings, so this one toggle stays manual.

#### Public-demo protection (built in)

- **Rate limiting** (always on): `/api/*` → 120 req/min per IP, everything
  else 600 req/min; `/health` is exempt. Over the limit → `429` +
  `Retry-After`. Tune with `RATE_LIMIT_API_PER_MIN` /
  `RATE_LIMIT_GENERAL_PER_MIN`, or `TRUSTED_PROXY_CIDRS` behind proxies.
- **API key gate** (opt-in): set `AEROTWIN_API_KEY=<secret>` to enable.
  Reads stay open by default (`AEROTWIN_KEY_OPEN_READ=1`); mutations and
  WebSocket handshakes require `X-API-Key: <secret>` (or `?key=<secret>`).
  Open pages as `/index.html?key=<secret>` — the dashboard forwards the key
  to every mutating call and the WS automatically. Private mode:
  `AEROTWIN_KEY_OPEN_READ=0` locks reads too.

#### CI & models

- GitHub Actions (`.github/workflows/ci.yml`) runs the Python suite and a
  Docker build + endpoint/mission smoke test on every push.
- Trained models are baked into the repo (`sih/ml/models/`), so
  `/health` reports `ml_models: "loaded"` in production. Retrain with
  `python -m ml.train --runs-per-fault 3 --healthy-runs 6 --step 10`.

To redeploy manually: Render dashboard → aerotwin → **Manual Deploy**, or
just push a commit to the branch. First build takes ~6–10 min
(scikit-learn is the big install); wake from idle ~50 s.

> Note: `render.yaml` in the repo is documentation-only (the live service was
> created outside Blueprints and uses the Python runtime, not Docker). Don't
> run a Blueprint sync from it — it would try to create a second service.
> Optional cleanup in the dashboard: set **Health Check Path** to `/health`.

### 3.3 — What you get

| Check | URL |
|---|---|
| Dashboard | `https://aerotwin-up6k.onrender.com/index.html` |
| Showcase | `https://aerotwin-up6k.onrender.com/showcase.html` |
| Health | `https://aerotwin-up6k.onrender.com/health` |
| API docs | `https://aerotwin-up6k.onrender.com/docs` |

Free-tier behavior to expect:
- **Sleeps** after 15 min without traffic; next visit wakes it in ~50 s.
- **Ephemeral disk** — telemetry history resets on redeploy (SQLite only).
- `/health` reports `ml_models: "fallback"` — expected; rule-based scoring is
  active and the demo is fully functional. Train locally with `train.bat` only
  if you want the trained models bundled.
- Keep it awake with a free https://uptimerobot.com monitor pinging `/health`
  every 10 minutes.

### How one container serves everything

`Dockerfile` runs only the FastAPI backend and mounts the static dashboard into
it via `AEROTWIN_SERVE_FRONTEND=1` (patch already in `sih/backend/main.py`), so
pages, REST, and the WebSocket all share one origin. The dashboard's WebSocket
auto-upgrades to same-origin `wss://` on https (patch in
`src/frontend/aerotwin-api.js`). Phone-pairing no longer needs serve.py: the backend hosts the same relay, so it works on any deploy.

---

## Part 4 — Backup link: Hugging Face Spaces (no card, ever)

Same Docker image, one extra env var.

1. https://huggingface.co → **New Space** → SDK **Docker** → Public → Create.
2. Add the repo files (clone the Space, copy the project in, or upload a zip).
3. Top of the Space's `README.md`:

   ```yaml
   ---
   title: AeroTwin Digital Twin
   emoji: ✈️
   colorFrom: yellow
   colorTo: black
   sdk: docker
   app_port: 7860
   pinned: true
   ---
   ```

4. In the `Dockerfile`, add `ENV PORT=7860` above `CMD` (HF routes that port).
5. Space **Settings → Variables**: `CORS_ORIGINS = https://<user>-aerotwin.hf.space`.

Builds in ~5 min → `https://<user>-aerotwin.hf.space/index.html`. Free Spaces
sleep after ~48 h without visits.

---

## Part 5 — Permanent free hosting: Oracle Cloud Always-Free VM

Genuinely free forever (4 ARM cores / 24 GB RAM tier), but signup requires a
card **for identity verification only**.

1. https://cloud.oracle.com → *Start for free*.
2. **Compute → Create Instance** — Ampere A1 (2 OCPU / 12 GB) or an AMD micro;
   both are Always-Free. Add your SSH key.
3. Open traffic: **VCN → Security Lists → Add Ingress** — `0.0.0.0/0`, TCP 80+443.
4. SSH in:

   ```bash
   sudo dnf install -y python3.12 git caddy
   git clone https://github.com/<YOUR_USER>/aerotwin.git && cd aerotwin
   python3.12 -m venv venv && venv/bin/pip install -r sih/backend/requirements.txt
   ```

5. Backend on 8081 with the dashboard mounted:

   ```bash
   cd sih
   AEROTWIN_SERVE_FRONTEND=1 PYTHONPATH="$PWD:$PWD/backend" \
     ../venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8081
   ```

6. **`/etc/caddy/Caddyfile`** (Caddy fetches HTTPS certs automatically; point a
   free https://duckdns.org A-record at the VM's public IP first):

   ```
   yourname.duckdns.org {
       reverse_proxy 127.0.0.1:8081
   }
   ```

   `sudo systemctl enable --now caddy`

7. **`/etc/systemd/system/aerotwin.service`** (survives reboots):

   ```ini
   [Unit]
   Description=AeroTwin backend
   After=network.target

   [Service]
   WorkingDirectory=/home/opc/aerotwin/sih
   Environment=AEROTWIN_SERVE_FRONTEND=1
   Environment=PYTHONPATH=/home/opc/aerotwin/sih:/home/opc/aerotwin/sih/backend
   ExecStart=/home/opc/aerotwin/venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8081
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```

   `sudo systemctl enable --now aerotwin`

On a VM, the SQLite database is persistent — history survives reboots.

---

## Part 6 — Verification checklist (any target)

| Check | Expected |
|---|---|
| `GET /health` | `{"status":"ok","components":{...}}` — `ml_models: "fallback"` is fine |
| `GET /index.html` | Dashboard renders |
| `GET /showcase.html` | Showcase renders, particle canvas animates |
| Dashboard live data | KPIs move continuously; DevTools → Network → WS shows `ws(s)://…/ws/telemetry/TAPAS-BH-201-001` with frames |
| No CORS errors in console | If you see any, set `CORS_ORIGINS` to the exact origin (scheme + host, no trailing slash) |
| `/docs` | Swagger UI loads |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `run.bat` → *"The system cannot find the path specified"* | (Old bug) relative venv path broke after `pushd sih` | **Already fixed** in this repo (`5e7fa7a`) — pull latest |
| ngrok `ERR_NGROK_121` version too old | Agent 3.3.1 < account minimum 3.20.0 | `ngrok update`, re-run `run.bat` |
| Cloud `/` shows `{"detail":"Not Found"}` | Dashboard mount disabled | Set `AEROTWIN_SERVE_FRONTEND=1`; dashboard is at `/index.html` |
| Dashboard up, no live data | WebSocket blocked / old cache | Hard-refresh (Ctrl+Shift+R); confirm Patch 2 (`wss`) present |
| CORS console errors | Origin mismatch | `CORS_ORIGINS` = exact public origin |
| Render wakes slowly | Free tier spin-down | Expected ~50 s; add an UptimeRobot ping |
| Phone QR silent on the public URL | *(was LAN-only)* | **Fixed:** the FastAPI backend now hosts the pairing relay (`/__pair`, `/__lanip`, `/__ctl`, `/__ice`), so the deployed "Pair phone" QR works from any phone |
| `/health` shows `ml_models: "fallback"` | Models never trained on this disk | Expected; demo-safe. `train.bat` locally to produce real models |

## What stays local-only (by design)

- `serve.py` phone pairing + HTTPS camera relay — the *cloud* pairing path
  now runs inside the backend (`sih/backend/pairing_relay.py`), so the
  deployed site pairs phones directly; serve.py remains the LAN/tunnel path
- `run.bat` two-process layout (backend + proxy frontend) — replaced in the
  cloud by the single mounted container
- Node gateway (`sih/backend/src/server.ts`) and React cockpit
  (`sih/frontend/`) — alternate stacks, not needed for any deployment here

## TL;DR

```powershell
ngrok update          # once — your tunnel then auto-starts with run.bat
.\run.bat             # local: http://localhost:8000/index.html
git push              # then Render (Part 3) for a permanent free URL
```
