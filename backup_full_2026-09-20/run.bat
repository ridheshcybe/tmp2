@echo off
echo Activating virtual environment...
call venv\Scripts\activate.bat
cd /d src\frontend
echo Starting HTTP server on port 8000...
echo.
echo Open your browser to http://localhost:8000 to view the mechanical/forensic simulation.
echo Press Ctrl+C to stop the server.
python -m http.server 8000

