FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 1) Backend dependencies first (better layer caching)
COPY sih/backend/requirements.txt sih/backend/requirements.txt
RUN pip install --no-cache-dir -r sih/backend/requirements.txt

# 2) App code — backend + dashboard + the packages the backend imports at
#    runtime (ml.* / simulator.* resolve via PYTHONPATH below).  sih/ml also
#    carries sih/ml/models, so a locally-trained model bundle (train.bat /
#    `python -m ml.train`) is baked into the image automatically; without it
#    the app runs in rule-based fallback mode.
COPY sih/backend sih/backend
COPY src/frontend src/frontend
COPY sih/ml sih/ml
COPY sih/simulator sih/simulator
# Test config (harmless at runtime; enables `docker run <img> pytest` CI)
COPY sih/pytest.ini sih/pytest.ini

# Non-root runtime user; writable dirs for the SQLite DB and logs
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /app/sih/data /app/sih/logs \
 && chown -R appuser:appuser /app

USER appuser

WORKDIR /app/sih

# Import layout:
#   /app/sih + /app/sih/backend       -> backend.*, services.*
#   /app/sih/ml + /app/sih/simulator  -> ml.* / simulator.* (backend runtime deps)
# NOTE: the sih/ root itself is deliberately NOT on the path — it would let a
# stale `models/` directory shadow backend.models.
ENV PYTHONPATH="/app/sih:/app/sih/backend:/app/sih/ml:/app/sih/simulator" \
    AEROTWIN_SERVE_FRONTEND=1 \
    AEROTWIN_FRONTEND_DIR=/app/src/frontend \
    CORS_ORIGINS="https://aerotwin.onrender.com"

# Render injects $PORT (default 10000); locally this defaults to 8081.
EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8081'), timeout=4)"

CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8081}"]
