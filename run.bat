@echo off
REM ============================================================
REM  AeroTwin launcher - backend (FastAPI :8081) + dashboard
REM  (serve.py :8000, which proxies /api to the backend).
REM
REM  Run setup.bat once first. All service lifecycle goes
REM  through sih\start_app.py so start/stop/status stay in sync.
REM ============================================================
setlocal
cd /d "%~dp0"

REM ---- pick a Python interpreter --------------------------------------
REM Absolute path on purpose: the service manager below runs from sih\,
REM so a relative "venv\Scripts\python.exe" would resolve to
REM sih\venv\... which does not exist.
set "PY=%~dp0venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

%PY% --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Run setup.bat first.
    pause
    exit /b 1
)

REM ---- start services (start_app.py skips anything already up) --------
pushd sih
"%PY%" start_app.py start
set START_ERR=%ERRORLEVEL%
popd

if not "%START_ERR%"=="0" (
    echo [ERROR] Service start failed - see sih\.backend.log / sih\.frontend.log
    pause
    exit /b 1
)

REM ---- wait for the backend, then open the dashboard ------------------
echo Waiting for the backend to come up...
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
echo   Dashboard : http://localhost:8000/index.html
echo   Backend   : http://127.0.0.1:8081
echo   Stop      : venv\Scripts\python sih\start_app.py stop   (or: python sih\start_app.py stop^)
echo.
start "" http://localhost:8000/index.html
pause
