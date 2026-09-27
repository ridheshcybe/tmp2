@echo off
echo Setting up environment...
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
) else (
    echo Virtual environment already exists.
)
echo Activating virtual environment...
call venv\Scripts\activate.bat
echo Upgrading pip...
pip install --upgrade pip
echo Installing dependencies...
if exist src\sih_requirements.txt (
    pip install -r src\sih_requirements.txt
)
if exist src\sih_backend_requirements.txt (
    pip install -r src\sih_backend_requirements.txt
)
if exist src\sih_ml_requirements.txt (
    pip install -r src\sih_ml_requirements.txt
)
echo Setup complete.
pause
