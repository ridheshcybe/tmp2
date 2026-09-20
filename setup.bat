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
python -m pip install --upgrade pip
echo.
echo The standalone viewer (run.bat) needs no packages - standard library only.
echo SIH dependencies are managed separately: see sih\requirements.txt and sih\README.md.
echo Setup complete.
pause
