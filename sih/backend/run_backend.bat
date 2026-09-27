@echo off
REM ══════════════════════════════════════════════════════════════════════════════
REM AeroTwin Backend — Windows Startup Script
REM ══════════════════════════════════════════════════════════════════════════════

cd /d "%~dp0"

echo.
echo ============================================================
echo   AeroTwin Digital Twin — FastAPI Backend
echo ============================================================
echo.

REM Create venv if not exists
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate venv
call venv\Scripts\activate.bat

REM Install deps
echo Installing dependencies...
pip install -q -r requirements.txt

REM Set PYTHONPATH for simulator imports
set PYTHONPATH=%CD%\..;%CD%;%PYTHONPATH%

REM Parse arg
if "%1"=="test" (
    echo Running tests...
    python tests\test_api.py
    goto :end
)

if "%1"=="production" (
    echo Starting production server...
    python -m uvicorn main:app --host 0.0.0.0 --port 8081 --workers 4 --log-level warning
    goto :end
)

echo Starting dev server on port 8081...
python -m uvicorn main:app --host 0.0.0.0 --port 8081 --reload --log-level info

:end
pause
