@echo off
REM Silent launcher for lrc-sync web UI - starts the server minimized
REM NOTE: uses console python, not pythonw. Detached pythonw has no stdout
REM and uvicorn crashes on startup without it, killing the server silently.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 exit /b 1

start "" /min python server.py --characterlevel %*
exit /b 0
