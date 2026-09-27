@echo off
REM ============================================================
REM  AeroTwin training - delegates to sih\train.bat with the
REM  repo venv (or system python) and the right PYTHONPATH.
REM ============================================================
setlocal
cd /d "%~dp0"

set "PY=venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo Using interpreter: %PY%
%PY% --version

pushd sih
set PYTHONPATH=%~dp0sih;%~dp0sih\backend
set PYTHONIOENCODING=utf-8
echo Training Anomaly VAE...
"%PY%" -m fusion_ml.anomaly_vae train
echo Training RUL Predictor...
"%PY%" -m fusion_ml.rul_predictor train
popd

echo Training finished.
pause
