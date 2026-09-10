@echo off
REM RouteMind AI - one-click start for Windows
cd /d "%~dp0backend"

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found on your PATH.
  echo Install Python 3.9 or newer from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during setup.
  pause
  exit /b 1
)

echo Starting RouteMind AI...
echo Control room will open at http://127.0.0.1:8000
echo Press Ctrl+C in this window to stop the server.
echo.
python run.py %*
pause
