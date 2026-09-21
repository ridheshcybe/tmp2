@echo off
REM ============================================================
REM  Aero Piston Engine Digital Twin - One-Click Demo Launcher
REM
REM  Starts the two real services (sih FastAPI backend on 8081,
REM  standalone dashboard on 8000) and opens the dashboard.
REM  Paths resolve from this script's location - no hardcoded drives.
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo   ============================================================
echo    AeroTwin - MALE UAV Aero-Engine Digital Twin
echo    (DRDO Tapas-BH-201) - one-click demo
echo   ============================================================
echo.

REM ---- check Python ----
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not on PATH.
    pause
    exit /b 1
)

REM ---- check dependencies are importable (setup_environment.bat installs them)
python -c "import fastapi, uvicorn, aiosqlite, numpy" >nul 2>&1
if errorlevel 1 (
    echo [WARN] Backend dependencies missing - run setup_environment.bat first.
    echo        Trying anyway...
)

REM ---- create .env from the example on first run ----
if exist .env.example (
    if not exist .env (
        copy .env.example .env >nul
        echo [OK] Created .env from .env.example
    )
)

echo.
echo [START] Launching services...
python start_app.py start
if errorlevel 1 (
    echo.
    echo [ERROR] start_app.py failed - see the messages above.
    pause
    exit /b 1
)

echo.
echo [INFO] Waiting for the backend to answer...
set /a tries=0
:wait_backend
timeout /t 2 /nobreak >nul
curl -s http://127.0.0.1:8081/health >nul 2>&1
if not errorlevel 1 goto backend_up
set /a tries+=1
if %tries% lss 15 goto wait_backend
echo [WARN] Backend did not answer within 30 s - check sih\.backend.log

:backend_up
echo.
echo   ============================================================
echo     Services Running
echo   ------------------------------------------------------------
echo     Dashboard : http://localhost:8000/index.html
echo     REST API  : http://localhost:8000/api/...  (proxied)
echo     Backend   : http://127.0.0.1:8081
echo   ------------------------------------------------------------
echo     Stop      : python start_app.py stop
echo     Status    : python start_app.py status
echo   ============================================================
echo.
start "" http://localhost:8000/index.html
pause
