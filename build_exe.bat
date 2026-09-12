@echo off
chcp 65001 >nul
title DropFile - Build Windows Standalone Executable (.exe)

echo ======================================================
echo       DropFile Standalone Executable Builder
echo ======================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not found in PATH! Please install Python 3.10+
    pause
    exit /b 1
)

python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing PyInstaller...
    pip install pyinstaller
)

python build_exe.py
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed! Check messages above.
    pause
    exit /b 1
)

echo.
echo [SUCCESS] Standalone executable is ready in dist\DropFile.exe
echo.
pause
