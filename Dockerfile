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
