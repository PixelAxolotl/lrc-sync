@echo off
REM Launch lrc-sync as a single native desktop window.
set HF_ENDPOINT=https://huggingface.co
cd /d "%~dp0"

where pythonw >nul 2>nul
if errorlevel 1 exit /b 1

start "" pythonw desktop.py %*
