@echo off
setlocal
cd /d "%~dp0"
set HF_ENDPOINT=https://huggingface.co

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found.
    exit /b 1
)

python -m PyInstaller --noconfirm --clean --onefile --windowed --name LrcSync ^
  --add-data "static;static" ^
  --add-data "ffmpeg-9.0.2-essentials_build;ffmpeg-9.0.2-essentials_build" ^
  desktop.py
if errorlevel 1 exit /b 1

echo.
echo Built dist\LrcSync.exe
