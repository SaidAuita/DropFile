@echo off
cd /d "%~dp0"
echo Starting DropFile in background...
start "" pythonw.exe DropFile.pyw
echo DropFile launched. Check system tray icon near the clock.
timeout /t 3 >nul
