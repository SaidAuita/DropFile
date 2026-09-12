@echo off
cd /d "%~dp0"
echo Starting DropFile in console debug mode...
python.exe DropFile.pyw
echo.
echo Process terminated. Press any key to close this window...
pause >nul
