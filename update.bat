@echo off
chcp 65001 >nul
cd /d "%~dp0"
title DropFile Updater

echo =========================================================
echo               DropFile - Обновление клиента
echo =========================================================
echo.

echo [1/4] Завершение запущенных процессов DropFile...
taskkill /f /im pythonw.exe 2>nul
timeout /t 1 >nul

set HTTPS_PROXY=
set HTTP_PROXY=

echo [2/4] Загрузка обновлений с GitHub...
git pull origin main
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Ошибка при загрузке обновлений.
    echo Проверьте подключение к сети или состояние репозитория.
    pause
    exit /b %ERRORLEVEL%
)

echo [3/4] Проверка и обновление зависимостей...
python -m pip install -r requirements.txt --quiet --upgrade

echo [4/4] Запуск обновленного DropFile в фоне...
start "" pythonw.exe DropFile.pyw

echo.
echo =========================================================
echo      Обновление успешно установлено!
echo =========================================================
timeout /t 3 >nul
