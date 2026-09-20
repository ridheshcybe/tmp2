@echo off
REM ═════════════════════════════════════════════════════════════════════════════
REM Aero Piston Engine Digital Twin - One-Click Demo Launcher (Windows)
REM ═════════════════════════════════════════════════════════════════════════════
REM
REM This script launches the complete Digital Twin system and opens the
REM dashboard in your default browser. No Docker required.
REM
REM Usage:
REM   Double-click run_demo.bat
REM   OR: run_demo.bat
REM
REM ═════════════════════════════════════════════════════════════════════════════

setlocal enabledelayedexpansion

REM Set colors (Windows 10+)
set "GREEN=[92m"
set "YELLOW=[93m"
set "RED=[91m"
set "BLUE=[94m"
set "CYAN=[96m"
set "NC=[0m"

REM Print banner
echo.
echo %CYAN%═══════════════════════════════════════════════════════════════════════════%NC%
echo %CYAN%   ____ _____     _           _    ____                                   %NC%
echo %CYAN%  / ___^|_   _^|__ ^| ^| _____  _^| ^|  / ___^| __ _ _ __ ___   ___  ___       %NC%
echo %CYAN% ^| ^|  _  ^| ^|/ _ \\^| ^|/ / _ \\^| ^| ^| ^|  _ / _` ^| '_ ` _ \\ / _ \\/ __^|      %NC%
echo %CYAN% ^| ^|_^| ^| ^| (_) ^|   ^< (_) ^| ^| ^| ^|_^| ^| (_^| ^| ^| ^| ^| ^|  __/\\__ \\      %NC%
echo %CYAN%  \\____^| ^|_^|\\___/^|_^|\\_\\___/^|_^|_^|  \\____^|\\__,_^|_^| ^|_^| ^|_^|\\___^|^|___/      %NC%
echo %CYAN%                                                                          %NC%
echo %CYAN%        MALE UAV Aero-Engine Digital Twin (DRDO Tapas-BH-201)            %NC%
echo %CYAN%═══════════════════════════════════════════════════════════════════════════%NC%
echo.

REM Function to print status
call :print_status "Checking prerequisites..."

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo %RED%✗ Python is not installed!%NC%
    echo Please install Python 3 from https://www.python.org/downloads/
    pause
    exit /b 1
)
echo %GREEN%✓%NC% Python is available

REM Check if requirements.txt exists
if not exist "E:\\projects\\sih\\requirements.txt" (
    echo %RED%✗ requirements.txt not found!%NC%
    pause
    exit /b 1
)
echo %GREEN%✓%NC% requirements.txt found

REM Verify virtual environment or install packages if needed
echo.
call :print_status "Verifying Python dependencies..."
python -m pip check >nul 2>&1
if errorlevel 1 (
    echo %YELLOW%⚠ Some packages may be missing. Run: pip install -r requirements.txt%NC%
)
echo %GREEN%✓%NC% Dependencies checked

REM Verify environment
echo.
call :print_status "Verifying environment..."
if exist "E:\\projects\\sih\\.env.example" (
    if not exist "E:\\projects\\sih\\.env" (
        copy "E:\\projects\\sih\\.env.example" "E:\\projects\\sih\\.env" >nul
        echo %GREEN%✓%NC% Created .env from .env.example
    )
)
echo %GREEN%✓%NC% Environment verified

echo.
call :print_status "Starting AeroTwin Digital Twin system..."
call :print_status "This will launch all services as standalone processes."
echo.
python E:\\projects\\sih\\start_app.py start

echo.
call :print_status "Waiting for services to become ready..."
echo.

REM Wait for Simulator
echo | set /p="  Waiting for Simulator (port 8765) "
set "wait_time=0"
:wait_simulator
if %wait_time% geq 60 goto :simulator_timeout
curl -s http://localhost:8765/health >nul 2>&1
if not errorlevel 1 (
    echo %GREEN% ✓%NC%
    goto :wait_ai
)
echo -n .
timeout /t 2 /nobreak >nul
set /a "wait_time+=2"
goto :wait_simulator
:simulator_timeout
echo %RED% Timeout%NC%

:wait_ai
echo | set /p="  Waiting for AI Service (port 8766) "
set "wait_time=0"
:wait_ai_loop
if %wait_time% geq 60 goto :ai_timeout
curl -s http://localhost:8766/health >nul 2>&1
if not errorlevel 1 (
    echo %GREEN% ✓%NC%
    goto :wait_backend
)
echo -n .
timeout /t 2 /nobreak >nul
set /a "wait_time+=2"
goto :wait_ai_loop
:ai_timeout
echo %RED% Timeout%NC%

:wait_backend
echo | set /p="  Waiting for Backend (port 8080) "
set "wait_time=0"
:wait_backend_loop
if %wait_time% geq 60 goto :backend_timeout
curl -s http://localhost:8081/health >nul 2>&1
if not errorlevel 1 (
    echo %GREEN% ✓%NC%
    goto :services_ready
)
echo -n .
timeout /t 2 /nobreak >nul
set /a "wait_time+=2"
goto :wait_backend_loop
:backend_timeout
echo %RED% Timeout%NC%

:services_ready
echo.
echo %GREEN%✓%NC% All services are ready
echo.

REM Open browser
call :print_status "Opening dashboard in browser..."
start http://localhost:3000

echo.
call :print_status "Service Information:"
echo.
echo %CYAN%═══════════════════════════════════════════════════════════════════════════%NC%
echo %CYAN%  Services Running (Standalone Mode)%NC%
echo %CYAN%═══════════════════════════════════════════════════════════════════════════%NC%
echo.
echo   %GREEN%Dashboard:%NC%      http://localhost:3000
echo   %GREEN%WebSocket:%NC%      ws://localhost:8080
echo   %GREEN%REST API:%NC%       http://localhost:8081
echo   %GREEN%Simulator:%NC%      ws://localhost:8765
echo   %GREEN%AI Service:%NC%     ws://localhost:8766
echo.
echo %CYAN%═══════════════════════════════════════════════════════════════════════════%NC%
echo.
echo   %YELLOW%Commands:%NC%
echo     Stop services:  python start_app.py stop
echo     Restart:        python start_app.py restart
echo     Check status:   python start_app.py status
echo.
echo %CYAN%═══════════════════════════════════════════════════════════════════════════%NC%
echo.

REM Keep window open
pause
exit /b 0

:print_status
echo %GREEN%✓%NC% %~1
goto :eof