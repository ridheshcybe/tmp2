@echo off
echo Starting AeroTwin Digital Twin System...
python E:\projects\sih\start_app.py start
timeout /t 5 >nul
echo System is live at http://localhost:3000