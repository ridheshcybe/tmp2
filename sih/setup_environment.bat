@echo off
REM ============================================================
REM SIH Project Setup Wizard (Windows Batch Script)
REM This script MUST be run FIRST when setting up the environment.
REM ============================================================
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

echo Installing dependencies...
"%VENV_PIP_PATH%" install -r sih\backend\requirements.txt >nul 2>&1
REM Install necessary simulation libraries
"%VENV_PIP_PATH%" install numpy scikit-learn pandas websockets >nul 2>&1
echo [SUCCESS] Python dependencies installed/verified.

REM 2. Check Node Dependencies
echo.
echo [STEP 2/3] Checking and installing Node.js dependencies...
IF EXIST sih\frontend\package.json (
    echo Running npm install in sih/frontend...
    cd sih\frontend
    npm install
    cd ..
    echo [SUCCESS] Node dependencies installed/verified in frontend.
) ELSE (
    echo [WARN] sih/frontend/package.json not found. Skipping Node dependency check.
)

REM 3. Final Check
echo.
echo [STEP 3/3] Setup Complete!
echo ----------------------------------------------------------------
echo The environment is ready.
echo NEXT STEP: Run call run_training.bat to generate the initial model artifact.
echo Then, run call run_system.bat for live demonstration.
echo ----------------------------------------------------------------

:cleanup
echo.
echo Setup script finished.
pause
