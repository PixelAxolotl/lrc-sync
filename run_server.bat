@echo off
REM Launcher for lrc-sync web UI - runs python server.py
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python not found on PATH. Install Python 3.10+ and try again.
    pause
    exit /b 1
)

python server.py %*
if errorlevel 1 (
    echo Server exited with error code %errorlevel%.
)

pause
