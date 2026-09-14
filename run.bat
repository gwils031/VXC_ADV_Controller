@echo off
cd /d "%~dp0"
echo Starting VXC ADV Controller...
python run.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with code %ERRORLEVEL%
    pause
)
