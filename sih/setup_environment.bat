@echo off
REM ============================================================
REM SIH Project Setup Wizard (Windows Batch Script)
REM This script MUST be run FIRST when setting up the environment.
REM All paths resolve from this script's own folder (sih\), so it
REM can be started from anywhere.
REM ============================================================
setlocal
cd /d "%~dp0"

echo ====================================================
echo  === SIH Project Setup Wizard ===
echo ====================================================

REM 1. Check Python Dependencies
echo [STEP 1/3] Checking and installing Python dependencies...
IF NOT EXIST venv (
    echo [WARN] Virtual environment 'venv' not found. Creating it now.
    python -m venv venv
)

REM We must use direct paths instead of 'CALL venv\Scripts\activate.bat'
SET VENV_PIP_PATH=venv\Scripts\pip.exe
SET VENV_PYTHON_PATH=venv\Scripts\python.exe

IF NOT EXIST "%VENV_PIP_PATH%" (
    echo [ERROR] Python interpreter not found at %VENV_PIP_PATH%. Please check your venv structure.
    goto :cleanup
)

echo Installing backend requirements...
"%VENV_PIP_PATH%" install --upgrade pip
"%VENV_PIP_PATH%" install -r backend\requirements.txt
IF ERRORLEVEL 1 (
    echo [ERROR] Dependency installation failed - see the messages above.
    goto :cleanup
)
echo [SUCCESS] Python dependencies installed/verified.

REM 2. Check Node Dependencies
echo.
echo [STEP 2/3] Checking and installing Node.js dependencies...
IF EXIST frontend\package.json (
    echo Running npm install in frontend...
    pushd frontend
    call npm install
    popd
    echo [SUCCESS] Node dependencies installed/verified in frontend.
) ELSE (
    echo [INFO] frontend\package.json not found. Skipping Node dependency check
    echo        (the standalone dashboard in src\frontend needs none^).
)

REM 3. Final Check
echo.
echo [STEP 3/3] Setup Complete!
echo ----------------------------------------------------------------
echo The environment is ready.
echo NEXT STEP: Run train.bat to generate the initial model artifact.
echo Then, run run.bat (repo root^) or run_demo.bat for the live demo.
echo ----------------------------------------------------------------

:cleanup
echo.
echo Setup script finished.
pause
