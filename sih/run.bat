@echo off
REM ============================================================
REM  SIH AeroTwin - quick launcher (Windows).
REM  Starts the digital-twin backend; paths resolve from this
REM  script's own location, so the repo can live anywhere.
REM ============================================================
setlocal
cd /d "%~dp0"

python start_app.py start
if errorlevel 1 (
    echo.
    echo [ERROR] start_app.py failed - check the messages above.
    pause
    exit /b 1
)

timeout /t 5 >nul
echo System is live.
pause
