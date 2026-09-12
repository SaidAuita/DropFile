#!/bin/bash
# ==============================================================================
# DropFile — Установщик для macOS (10.15 Catalina ... Tahoe / Sequoia)
# Запуск двойным кликом в Finder.
# ==============================================================================

set -e

# Переход в директорию скрипта
cd "$(dirname "$0")"
SCRIPT_DIR="$(pwd)"

echo "=================================================================="
echo "          DropFile — Установка клиента для macOS                 "
echo "=================================================================="
echo ""

# 1. Поиск Python 3
echo "[1/5] Проверка окружения Python 3..."
PYTHON_BIN=""

for cand in "python3" "/usr/local/bin/python3" "/opt/homebrew/bin/python3" "/Library/Frameworks/Python.framework/Versions/Current/bin/python3"; do
    if command -v "$cand" >/dev/null 2>&1; then
        VER=$("$cand" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
        if [ -n "$VER" ]; then
            PYTHON_BIN="$cand"
            echo "   -> Найден Python $VER ($cand)"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo ""
    echo "❌ Ошибка: Python 3 не обнаружен на вашей системе."
    echo "Для установки Python 3 на macOS выполните в Терминале:"
    echo "   xcode-select --install"
    echo "или скачайте официальный инсталлятор с https://www.python.org/downloads/macos/"
    echo ""
    read -p "Нажмите Enter для выхода..."
    exit 1
fi

# 2. Создание виртуального окружения venv
echo ""
echo "[2/5] Подготовка изолированного окружения (.venv)..."
if [ ! -d ".venv" ]; then
    "$PYTHON_BIN" -m venv .venv
    echo "   -> Окружение .venv создано."
else
    echo "   -> Используется существующее окружение .venv."
fi

# Активация venv
source .venv/bin/activate
VENV_PY="$SCRIPT_DIR/.venv/bin/python3"

# 3. Установка зависимостей
echo ""
echo "[3/5] Установка зависимостей (requests, pystray, pillow, watchdog, pyobjc)..."
pip install --upgrade pip >/dev/null 2>&1 || true
pip install -r requirements-mac.txt

# 4. Создание приложения DropFile.app в ~/Applications
echo ""
echo "[4/5] Создание нативного приложения DropFile.app..."
"$VENV_PY" mac_bundle.py

# 5. Создание симлинка на рабочем столе
DESKTOP_PATH="$HOME/Desktop/DropFile"
SYNC_DIR="$HOME/Desktop/DropFile_Sync"
mkdir -p "$SYNC_DIR"
if [ ! -e "$DESKTOP_PATH" ]; then
    ln -s "$SYNC_DIR" "$DESKTOP_PATH" 2>/dev/null || true
    echo "   -> Создан ярлык на Рабочем столе: $DESKTOP_PATH"
fi

echo ""
echo "=================================================================="
echo "🎉 Установка успешно завершена!"
echo "Приложение установлено в: $HOME/Applications/DropFile.app"
echo "Иконка будет доступна в верхней строке меню (menu bar)."
echo "=================================================================="
echo ""

read -p "Запустить DropFile прямо сейчас? [Y/n]: " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
    echo "Запуск DropFile..."
    open "$HOME/Applications/DropFile.app"
fi

echo "Готово! Окно можно закрыть."
exit 0
