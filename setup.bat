@echo off
REM ============================================================
REM  AeroTwin setup - run this FIRST on a fresh machine.
REM
REM  Creates a clean virtual environment, installs the backend
REM  dependencies (FastAPI, numpy, scikit-learn, ...) and the
REM  frontend needs nothing: serve.py is standard library only.
REM ============================================================
setlocal

cd /d "%~dp0"

echo [1/4] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found on PATH. Install Python 3.10+ from https://www.python.org/downloads/
    pause
    exit /b 1
)
python --version

echo.
echo [2/4] Creating virtual environment...
if exist venv\Scripts\python.exe (
    REM Verify the venv interpreter actually runs - a venv moved or
    REM copied from another machine/user can point at a missing base
    REM interpreter and must be rebuilt.
    venv\Scripts\python.exe --version >nul 2>&1
    if errorlevel 1 (
        echo [WARN] Existing venv is broken - rebuilding it...
        rmdir /s /q venv
    ) else (
        echo Virtual environment already exists.
    )
)
if not exist venv\Scripts\python.exe (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Could not create the virtual environment.
        pause
        exit /b 1
    )
)

echo.
echo [3/4] Installing dependencies (sih\backend\requirements.txt)...
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r sih\backend\requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency installation failed. Check the messages above.
    pause
    exit /b 1
)

echo.
echo [4/4] Verifying the backend imports...
venv\Scripts\python.exe -c "import fastapi, uvicorn, aiosqlite, numpy, sklearn, pandas" 2>nul
if errorlevel 1 (
    echo [WARN] Some backend imports are missing - re-run:  venv\Scripts\python -m pip install -r sih\backend\requirements.txt
) else (
    echo All backend dependencies verified.
)

echo.
echo ------------------------------------------------------------
echo Setup complete.
echo NEXT: run.bat  (starts the backend on 8081 + the frontend
echo       dashboard on http://localhost:8000^)
echo Optional: train.bat  (generates the ML model artifacts)
echo ------------------------------------------------------------
pause
