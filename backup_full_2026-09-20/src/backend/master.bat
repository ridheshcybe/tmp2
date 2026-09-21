@echo off
echo ===================================================
echo SIH Master Script: Setup, Training, and Inference
echo ===================================================
echo.
echo Step 1: Setting up environment...
call src_sih_setup_environment.bat
if errorlevel 1 (
    echo Setup failed. Exiting.
    exit /b %errorlevel%
)
echo.
echo Step 2: Training models...
call src_sih_train.bat
if errorlevel 1 (
    echo Training failed. Exiting.
    exit /b %errorlevel%
)
echo.
echo Step 3: Running inference...
python run_inference.py
if errorlevel 1 (
    echo Inference failed.
    exit /b %errorlevel%
)
echo.
echo All steps completed successfully.
pause
