@echo off
echo AeroTwin launcher: backend + frontend
echo.

REM ── 1. sih backend (FastAPI on 127.0.0.1:8081) ────────────────────────────
netstat -ano | findstr "127.0.0.1:8081" | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
    echo Starting sih backend on port 8081...
    start "AeroTwin backend" /min cmd /c "cd /d %~dp0sih && set PYTHONPATH=%~dp0sih;%~dp0sih\backend && set PYTHONIOENCODING=utf-8 && python -m uvicorn backend.main:app --host 127.0.0.1 --port 8081"
    REM give it a moment to boot
    timeout /t 4 /nobreak >nul
) else (
    echo Backend already running on 8081.
)

REM ── 2. frontend static server (port 8000, proxies /api to the backend) ───
echo Starting frontend on port 8000...
call venv\Scripts\activate.bat 2>nul
cd /d %~dp0src\frontend
python serve.py

echo.
echo Frontend stopped.
