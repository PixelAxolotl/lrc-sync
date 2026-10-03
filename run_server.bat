@echo off
REM Silent launcher for lrc-sync web UI - runs server.py with no console window
cd /d "%~dp0"

where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" /min pythonw server.py %*
    exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
    start "" /min python server.py %*
    exit /b 0
)

exit /b 1
