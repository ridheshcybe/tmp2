# DEPLOY.md — Deploy AeroTwin for Free, Step by Step

> **What you are deploying:** the AeroTwin digital-twin dashboard + its FastAPI backend
> (`/api`, live WebSocket telemetry, simulator, ML with rule-based fallback).
>
> **Who this is for:** you, from your Windows machine, with $0 and (where possible) no credit card.
>
> **Read this first:** pick **one** option below.
>
> | Option | Cost | URL lifetime | Needs card? | Best for |
> |---|---|---|---|---|
> | **A. ngrok quick demo** | Free | While your PC is awake | No | Tomorrow's presentation, 5-minute setup |
> | **B. Render (recommended)** | Free tier | Always-on URL (sleeps after 15 min idle) | No | A real link you can share for weeks |
> | **C. Hugging Face Spaces** | Free | URL sleeps after ~48h inactivity | No | Backup public link, zero-card guarantee |
> | **D. Oracle Always-Free VM** | Free forever | Permanent | **Yes** (for identity check only) | Long-term hosting you fully control |

---

## 0. Understand the architecture (2 minutes)

```
┌──────────────────────────────────────────────────────────┐
│  ONE service does everything when deployed to the cloud   │
│                                                            │
│  FastAPI backend (sih/backend/main.py)                     │
│   • /api/*            REST (engine, mission, faults...)   │
│   • /ws/telemetry/…   live WebSocket telemetry             │
│   • /health           health probe                         │
│   • / (dashboard)     the static pages in src/frontend/    │
└──────────────────────────────────────────────────────────┘
```

- The dashboard (`src/frontend/*.html`) is plain HTML/JS — it is **served by the backend itself** after Step 1 below. You do **not** need `serve.py` in the cloud (`serve.py` is the LAN/phone-pairing server; its pairing QR stays a local-network feature).
- The **Node gateway** (`sih/backend/src/server.ts`) and the **React cockpit** (`sih/frontend/`) are alternate/secondary implementations. **Skip them** for deployment — the FastAPI backend + standalone dashboard is the complete demo.
- SQLite (`sih/backend/data/aerotwin.db`) is created automatically. On free tiers the disk is **ephemeral** — telemetry history resets on redeploy. Fine for demos.
- ML models: no training needed. `config.py` has `USE_FALLBACK=True`, so `/health` will report `ml_models: "fallback"` (rule-based scoring). That is expected and the demo works fully.

---

## 1. ONE-TIME PREP: two small patches (do these once, locally)

These two changes are required for **every** cloud option (A–D). They are safe and
do not change local behavior.

### WHERE: your local terminal (project root)

### Patch 1 — serve the dashboard from FastAPI

Append this block to the **very end** of `sih/backend/main.py`
(it must come after all `app.include_router(...)` calls so API routes win):

```python
# ══════════════════════════════════════════════════════════════════════════════
#  Optional: serve the standalone dashboard from this same origin (cloud deploys)
# ══════════════════════════════════════════════════════════════════════════════

import os as _os

if _os.environ.get("AEROTWIN_SERVE_FRONTEND", "").strip() == "1":
    from pathlib import Path as _Path

    _frontend_dir = _Path(
        _os.environ.get(
            "AEROTWIN_FRONTEND_DIR",
            str(_Path(__file__).resolve().parents[2] / "src" / "frontend"),
        )
    )
    if _frontend_dir.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=str(_frontend_dir), html=True),
            name="dashboard",
        )
        logger.info(f"Serving dashboard from {_frontend_dir}")
```

### Patch 2 — make the WebSocket work on https

In `src/frontend/aerotwin-api.js`, replace the `wsUrl()` function:

```js
    function wsUrl() {
        // Cloud/https deployments serve the API on this same origin (no :8081).
        if (location.protocol === "https:") {
            return "wss://" + location.host + "/ws/telemetry/" + ENGINE_ID;
        }
        const host = location.hostname || "127.0.0.1";
        return "ws://" + host + ":" + BACKEND_WS_PORT + "/ws/telemetry/" + ENGINE_ID;
    }
```

> **Both patches are already applied in this repo and smoke-tested**: `/health` returns JSON,
`/index.html` and `/cutaway.html` serve 200, `/api/faults/types` answers through the same
origin. One nuance: bare `/` still returns the API's JSON info (API routes intentionally win),
so open **`/index.html`** for the dashboard.

### Verify locally, then commit

```bash
# from repo root — start backend WITH the dashboard mounted
cd sih
AEROTWIN_SERVE_FRONTEND=1 PYTHONPATH="$PWD:$PWD/backend" \
  ../venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8081
```

Open http://127.0.0.1:8081/index.html — you should see the **dashboard served by the backend**,
the engine telemetry live (WebSocket connected), and http://127.0.0.1:8081/health
returning JSON. Stop with Ctrl+C.

```bash
git add sih/backend/main.py src/frontend/aerotwin-api.js
git commit -m "feat(deploy): serve dashboard from FastAPI + same-origin wss on https"
```

```bash
git add sih/backend/main.py src/frontend/aerotwin-api.js
git commit -m "feat(deploy): serve dashboard from FastAPI + same-origin wss on https"
```

---

## 2. Option A — ngrok quick demo (5 minutes, zero infra)

**WHERE: your local terminal + one ngrok account in the browser.**
Your link dies when your PC sleeps, and the URL changes each run. Perfect for a live presentation day.

1. **Install ngrok** (if not already): download from https://ngrok.com/download, unzip, put `ngrok.exe` somewhere on PATH.
2. **Get a free authtoken**: sign up at https://dashboard.ngrok.com → *Getting Started → Your Authtoken* → copy it.
3. **Configure once:**

   ```bash
   ngrok config add-authtoken <YOUR_TOKEN>
   ```

4. **Start the backend with the dashboard mounted** (from Step 1):

   ```cmd
   cd sih
   set AEROTWIN_SERVE_FRONTEND=1
   ..\venv\Scripts\python -m uvicorn backend.main:app --host 0.0.0.0 --port 8081
   ```

5. **Open a second terminal and tunnel it:**

   ```bash
   ngrok http 8081
   ```

6. Share the `https://xxxx.ngrok-free.app` URL that appears. Everything works through it: dashboard, REST, and **WebSocket** (ngrok supports `wss`).
   Open `https://xxxx.ngrok-free.app/index.html`.

> Note: free ngrok shows an interstitial warning page once per visitor — click *Visit Site*.

---

## 3. Option B — Render free tier (RECOMMENDED: real always-on URL)

**WHERE: GitHub.com (web UI) + render.com (web UI) + your local terminal for pushing.**

### Step 3.1 — Push the repo to GitHub

1. Create a new **private** repo on https://github.com/new (e.g. `aerotwin`). Do **not** initialize with a README.
2. Locally (repo root):

   ```bash
   git remote add origin https://github.com/<YOUR_USER>/aerotwin.git
   git push -u origin feature/awwwards-overnight-showcase
   ```

   > The repo contains old `backup_*/` folders and zips; the Dockerfile below copies
   > only the two directories that matter, so the image stays small. If the push is
   > slow because of the backups, that's cosmetic — let it finish once.

### Step 3.2 — Add the deploy files (WHERE: local, project root)

**`Dockerfile`** (create at repo root):

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# 1) Backend dependencies first (better layer caching)
COPY sih/backend/requirements.txt sih/backend/requirements.txt
RUN pip install --no-cache-dir -r sih/backend/requirements.txt

# 2) App code — backend + dashboard only
COPY sih/backend sih/backend
COPY src/frontend src/frontend

WORKDIR /app/sih

# start_app.py's exact import layout: PYTHONPATH = sih + sih/backend
ENV PYTHONPATH="/app/sih:/app/sih/backend" \
    AEROTWIN_SERVE_FRONTEND=1 \
    AEROTWIN_FRONTEND_DIR=/app/src/frontend \
    CORS_ORIGINS="https://REPLACE-ME.onrender.com"

# Render injects $PORT; locally defaults to 8081
EXPOSE 8081
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8081}"]
```

**`.dockerignore`** (create at repo root — keeps the build context small):

```
backup_full_2026-09-20
backup_2026-09-21
brag-output*
archive_cleanup_2026-09-20.zip
backup_full_2026-09-20.zip
node_modules
venv
.git
sih/frontend/node_modules
```

**`render.yaml`** (create at repo root — Render Blueprint):

```yaml
services:
  - type: web
    name: aerotwin
    runtime: docker
    plan: free
    healthCheckPath: /health
    envVars:
      - key: AEROTWIN_SERVE_FRONTEND
        value: "1"
      # Set this to your real URL after the first deploy:
      - key: CORS_ORIGINS
        value: https://aerotwin.onrender.com
```

Commit and push:

```bash
git add Dockerfile .dockerignore render.yaml
git commit -m "feat(deploy): add Dockerfile + Render blueprint for free hosting"
git push
```

### Step 3.3 — Create the service on Render (WHERE: render.com web UI)

1. Go to https://dashboard.render.com → sign in **with GitHub** (no card needed).
2. **New → Web Service** → connect your `aerotwin` repo → pick the `feature/awwwards-overnight-showcase` branch.
3. Render reads `render.yaml` automatically. Confirm:
   - Runtime: **Docker**
   - Instance type: **Free**
   - Health check path: `/health`
4. Click **Create Web Service**. First build takes ~3–6 min (scikit-learn install).
5. Note your URL (e.g. `https://aerotwin.onrender.com`). Update `CORS_ORIGINS` in
   `render.yaml` (or in Render → Environment) to exactly that URL and redeploy.
   The dashboard lives at `https://aerotwin.onrender.com/index.html`.

### Step 3.4 — Know the free-tier behavior

- Sleeps after **15 min** with no traffic; the next visit takes **~50 s** to wake.
  Optional: ping `/health` every 10 min with a free UptimeRobot monitor to keep it awake.
- 750 free instance-hours/month — one service runs free all month.
- Disk is ephemeral: saved telemetry/reports reset on each redeploy.

---

## 4. Option C — Hugging Face Spaces (no card, ever)

**WHERE: huggingface.co (web UI) + local terminal.** Uses the same Dockerfile.

1. Create a free account at https://huggingface.co → **New Space** → SDK: **Docker** → Blank → Public (free spaces are public) → Create.
2. Add the two files below **on top of** the repo's files (easiest: clone the space locally and copy your project in, or upload a zip of the repo in the web UI).

   **`README.md` front-matter** (must be at the very top of the Space's README.md):

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

   **`Dockerfile`**: same as Option B, but **add one line** before `CMD`:

   ```dockerfile
   ENV PORT=7860
   ```

3. The Space builds (~5 min) and serves at `https://<user>-aerotwin.hf.space`.
4. Set the Space's `CORS_ORIGINS` env var to that URL (Space → Settings → Variables).

> Free Spaces sleep after ~48h without visits and wake on demand.

---

## 5. Option D — Oracle Cloud Always-Free VM (permanent, fully yours)

**WHERE: cloud.oracle.com (web UI) + SSH terminal.** Genuinely free **forever** (4 ARM cores, 24 GB RAM), but requires a credit/debit card **for identity verification only** (never charged on the Always-Free tier).

1. Sign up at https://cloud.oracle.com → *Start for free*.
2. **Compute → Create Instance**: shape **Ampere A1** (set OCPUs=2, RAM=12 GB) or an Always-Free AMD micro — both qualify. Upload your SSH public key.
3. Open the ports: **Networking → Virtual Cloud Networks → your VCN → Security Lists → Add Ingress Rule**: source `0.0.0.0/0`, TCP ports `80` and `443`.
4. SSH in and install:

   ```bash
   sudo dnf install -y python3.12 git caddy   # caddy = auto-HTTPS reverse proxy
   git clone https://github.com/<YOUR_USER>/aerotwin.git
   cd aerotwin
   python3.12 -m venv venv
   venv/bin/pip install -r sih/backend/requirements.txt
   ```

5. Run the backend on port 8081 (with the Step-1 patches):

   ```bash
   cd sih
   AEROTWIN_SERVE_FRONTEND=1 \
   PYTHONPATH="$PWD:$PWD/backend" \
   ../venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8081
   ```

6. **`/etc/caddy/Caddyfile`** (one domain per line — Caddy fetches HTTPS certs automatically; point a free DNS A-record at the VM's public IP first, e.g. via https://duckdns.org):

   ```
   yourname.duckdns.org {
       reverse_proxy 127.0.0.1:8081
   }
   ```

   ```bash
   sudo systemctl enable --now caddy
   ```

7. Make the backend survive reboots with a systemd unit (`/etc/systemd/system/aerotwin.service`):

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

   ```bash
   sudo systemctl enable --now aerotwin
   ```

---

## 6. Verify the deployment (any option)

Open each of these in a browser (or `curl`):

| Check | URL | Expected |
|---|---|---|
| Backend health | `https://YOUR-URL/health` | `{"status": "ok", "components": {"ml_models": "fallback", ...}}` |
| Dashboard | `https://YOUR-URL/index.html` | AeroTwin dashboard shell renders |
| Live telemetry | open dashboard → watch KPI cards / cutaway | values update continuously (WebSocket badge/behavior — not stuck in polling fallback) |
| API sanity | `https://YOUR-URL/api/engine/TAPAS-BH-201-001` (or any route from `/docs`) | JSON, no CORS error in DevTools |
| API docs | `https://YOUR-URL/docs` | Swagger UI loads |

**If telemetry looks frozen:** DevTools → Network → WS tab. You should see a `wss://YOUR-URL/ws/telemetry/TAPAS-BH-201-001` connection with periodic frames. If it's missing, Patch 2 wasn't applied or you're viewing a cached page — hard-refresh (Ctrl+Shift+R).

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/` shows `{"detail":"Not Found"}` | Dashboard mount missing | Set `AEROTWIN_SERVE_FRONTEND=1`; check Patch 1 is at the **end** of `main.py` |
| Dashboard loads, API 404 | Mount placed before routers | Move the mount block after all `include_router` calls |
| Dashboard loads, no live data | WS on wrong port / blocked | Apply Patch 2; confirm https (wss), hard-refresh |
| CORS errors in console | `CORS_ORIGINS` mismatch | Set it to your exact public origin (scheme + host, no trailing slash). Same-origin deploys don't need it, but set it anyway |
| Render build timeout | Rare — heavy ML deps | Retry; the image is cached after first success |
| Render service wakes slowly | Free tier spin-down | Expected (~50 s); use UptimeRobot to pre-warm |
| `/health` says `ml_models: "fallback"` | Models never trained | Expected on fresh deploys — rule-based fallback is active and demo-safe. Train locally (`train.bat`) and commit `ml/models` only if you need ML scoring |
| Phone-pairing QR does nothing on the public URL | Pairing relay lives in `serve.py` (LAN-only) | Expected. Pairing is a local-network feature; the public demo is the dashboard |

---

## 8. What stays local-only (by design)

- `serve.py` phone pairing + HTTPS camera relay — LAN feature
- `run.bat` / `start_app.py` dual-process layout — replaced by the single mounted service in the cloud
- Node gateway (`sih/backend/src/server.ts`) and React cockpit (`sih/frontend/`) — not deployed; the FastAPI backend + standalone dashboard is the full demo

## 9. Recommended path (TL;DR)

1. Do **Step 1** (two patches) — 10 minutes.
2. Demo coming up within 48 h? → **Option A (ngrok)** today, **Option B (Render)** tonight.
3. Share **Option B's** URL everywhere; keep **Option C** as a backup link if you want belt-and-suspenders.
