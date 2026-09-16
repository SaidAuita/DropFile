#!/bin/bash
# ==============================================================================
# DropFile — Installer for Linux (Ubuntu, Debian, Mint, Fedora, Arch, etc.)
# Supports both Desktop (GUI & Tray) and Server / Headless (systemd daemon).
# ==============================================================================

set -e

# Change directory to script location
cd "$(dirname "$0")"
SCRIPT_DIR="$(pwd)"

chmod +x "$SCRIPT_DIR"/*.sh 2>/dev/null || true
chmod +x "$SCRIPT_DIR"/DropFile.pyw 2>/dev/null || true
ln -sf DropFile.pyw "$SCRIPT_DIR/dropfile.py" 2>/dev/null || true
ln -sf DropFile.pyw "$SCRIPT_DIR/DropFile.py" 2>/dev/null || true

echo "=================================================================="
echo "          DropFile — Client Installer for Linux                   "
echo "=================================================================="
echo ""

# 1. Locate Python 3
echo "[1/5] Checking Python 3..."
PYTHON_BIN=""

CANDIDATES=(
    "python3"
    "/usr/bin/python3"
    "/usr/local/bin/python3"
)

for cand in "${CANDIDATES[@]}"; do
    if command -v "$cand" >/dev/null 2>&1; then
        VER=$("$cand" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
        MAJOR=$("$cand" -c "import sys; print(sys.version_info.major)" 2>/dev/null || true)
        MINOR=$("$cand" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || true)
        if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 8 ]; then
            PYTHON_BIN="$cand"
            echo "   -> Found Python $VER ($cand)"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "❌ Error: Python 3.8+ is required. Please install Python 3:"
    echo "   Ubuntu/Debian: sudo apt update && sudo apt install -y python3 python3-pip python3-venv"
    echo "   Fedora:        sudo dnf install -y python3 python3-pip"
    echo "   Arch Linux:    sudo pacman -S python python-pip"
    exit 1
fi

# Check optional desktop dependencies (Tkinter, AppIndicator)
HAS_DISPLAY=0
if [ -n "$DISPLAY" ] || [ -n "$WAYLAND_DISPLAY" ]; then
    HAS_DISPLAY=1
fi

if [ "$HAS_DISPLAY" -eq 1 ]; then
    echo "[2/5] Checking desktop GUI components..."
    if ! "$PYTHON_BIN" -c "import tkinter" >/dev/null 2>&1; then
        echo "   ⚠️  Note: Python Tkinter (_tkinter) is not installed."
        echo "      To enable GUI Settings dialog, run:"
        echo "      Ubuntu/Debian: sudo apt install -y python3-tk"
        echo "      Fedora:        sudo dnf install -y python3-tkinter"
        echo "      Arch Linux:    sudo pacman -S tk"
    else
        echo "   -> Tkinter GUI support: OK"
    fi
else
    echo "[2/5] Server / headless environment detected (no active DISPLAY). Skipping GUI checks."
fi

# 3. Setup Virtual Environment
echo "[3/5] Setting up Python virtual environment..."
VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "   -> Creating virtual environment in $VENV_DIR..."
    if ! "$PYTHON_BIN" -m venv "$VENV_DIR" 2>/dev/null; then
        echo "   ⚠️  python3-venv package may be missing. Attempting pip install without venv..."
        VENV_PYTHON="$PYTHON_BIN"
    else
        VENV_PYTHON="$VENV_DIR/bin/python3"
    fi
else
    VENV_PYTHON="$VENV_DIR/bin/python3"
fi

echo "   -> Upgrading pip and installing dependencies..."
"$VENV_PYTHON" -m pip install --upgrade pip --quiet 2>/dev/null || true

if [ -f "$SCRIPT_DIR/requirements-linux.txt" ]; then
    "$VENV_PYTHON" -m pip install -r "$SCRIPT_DIR/requirements-linux.txt" --quiet
elif [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    "$VENV_PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt" --quiet
fi
echo "   -> Dependencies installed successfully."

# 4. Create Desktop shortcut and Application menu entry (if Desktop is available)
echo "[4/5] Configuring system integration..."
SYNC_DIR="$HOME/Desktop/DropFile"
if [ ! -d "$HOME/Desktop" ]; then
    SYNC_DIR="$HOME/DropFile"
fi
mkdir -p "$SYNC_DIR"
echo "   -> Local sync folder ready: $SYNC_DIR"

if [ "$HAS_DISPLAY" -eq 1 ]; then
    # Desktop shortcut
    DESKTOP_PATH="$HOME/Desktop"
    if command -v xdg-user-dir >/dev/null 2>&1; then
        XDG_DESK=$(xdg-user-dir DESKTOP 2>/dev/null || true)
        if [ -n "$XDG_DESK" ] && [ -d "$XDG_DESK" ]; then
            DESKTOP_PATH="$XDG_DESK"
        fi
    fi
    if [ -d "$DESKTOP_PATH" ] && [ ! -e "$DESKTOP_PATH/DropFile" ]; then
        ln -s "$SYNC_DIR" "$DESKTOP_PATH/DropFile" 2>/dev/null || true
        echo "   -> Desktop symlink created: $DESKTOP_PATH/DropFile"
    fi

    # Application menu entry (.desktop)
    APP_DIR="$HOME/.local/share/applications"
    mkdir -p "$APP_DIR"
    RUNNER_BIN="$VENV_PYTHON"
    MAIN_SCRIPT="$SCRIPT_DIR/DropFile.pyw"
    ICON_PATH="$SCRIPT_DIR/icon.ico"

    cat > "$APP_DIR/dropfile.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DropFile
GenericName=File Synchronization Client
Comment=Lightweight Dropbox-style sync client for FileBrowser
Exec=$RUNNER_BIN $MAIN_SCRIPT
Icon=$ICON_PATH
Terminal=false
Categories=Utility;FileTools;Network;
StartupNotify=false
EOF
    chmod +x "$APP_DIR/dropfile.desktop"
    echo "   -> Application launcher registered: $APP_DIR/dropfile.desktop"
fi

# 5. Systemd user service installation
echo "[5/5] Checking systemd service support..."
if command -v systemctl >/dev/null 2>&1; then
    SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
    mkdir -p "$SYSTEMD_USER_DIR"
    SERVICE_FILE="$SYSTEMD_USER_DIR/dropfile.service"

    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=DropFile FileBrowser Synchronization Daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$VENV_PYTHON $SCRIPT_DIR/DropFile.pyw --headless
Restart=always
RestartSec=10
WorkingDirectory=$HOME

[Install]
WantedBy=default.target
EOF

    systemctl --user daemon-reload 2>/dev/null || true
    echo "   -> Systemd user service created: $SERVICE_FILE"
    echo "      To enable autostart on boot (server / background mode), run:"
    echo "        systemctl --user enable --now dropfile.service"
fi

echo ""
echo "=================================================================="
echo "          DropFile installation complete!                        "
echo "=================================================================="
echo ""
echo "▶ To run DropFile now:"
if [ "$HAS_DISPLAY" -eq 1 ]; then
    echo "  ./run_linux.sh                  (launches in system tray)"
    echo "  ./run_linux.sh --settings       (opens Settings dialog)"
else
    echo "  ./run_linux.sh --headless       (runs background sync daemon)"
    echo "  systemctl --user start dropfile (starts via systemd)"
fi
echo ""
