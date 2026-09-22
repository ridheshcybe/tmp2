# DEPLOY.md — Running and Deploying AeroTwin

> **Already working as of this commit:** `run.bat` starts everything (the
> path bug that caused *"The system cannot find the path specified"* is fixed),
> the dashboard is also served straight from the backend, and the Docker/Render
> files exist. This guide runs from **verified, tested steps** — not theory.

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

The startup banner now lists the tunnel. Get the public URL either from the
console or:

```
curl http://127.0.0.1:4040/api/tunnels
```

Share `https://<random>.ngrok-free.app/index.html` (dashboard) or
`/showcase.html`. Because `serve.py` detects the tunnel automatically, the
**phone-pairing QR now works from any phone on any network** — no LAN required.
Free ngrok shows each visitor a one-time interstitial ("Visit Site").

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

### 3.2 — Create the service

**WHERE:** https://dashboard.render.com

1. Sign in **with GitHub** → **New → Web Service** → pick your repo and the
   `feature/awwwards-overnight-showcase` branch.
2. Render reads `render.yaml`: runtime **Docker**, plan **Free**, health check
   `/health`. Click **Create Web Service** — first build takes ~3–6 min
   (scikit-learn is the big install).
3. Copy your URL (e.g. `https://aerotwin.onrender.com`), then in
   **Environment** set:

   ```
   CORS_ORIGINS = https://aerotwin.onrender.com
   ```

   and redeploy once. (Same-origin pages don't strictly need it, but set it to
   your exact URL anyway — future-proof.)

### 3.3 — What you get

| Check | URL |
|---|---|
| Dashboard | `https://aerotwin.onrender.com/index.html` |
| Showcase | `https://aerotwin.onrender.com/showcase.html` |
| Health | `https://aerotwin.onrender.com/health` |
| API docs | `https://aerotwin.onrender.com/docs` |

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
`src/frontend/aerotwin-api.js`). Phone-pairing stays local-only by design.

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
| Phone QR silent on the public URL | Pairing relay is LAN-only (`serve.py`) | Expected on cloud deploys; for world-pairing use the ngrok path (Part 2) |
| `/health` shows `ml_models: "fallback"` | Models never trained on this disk | Expected; demo-safe. `train.bat` locally to produce real models |

## What stays local-only (by design)

- `serve.py` phone pairing + HTTPS camera relay (ngrok tunnel brings it
  world-reachable — that's Part 2's magic)
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
