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

    MISSING_PKGS=""
    if ! "$PYTHON_BIN" -c "import tkinter" >/dev/null 2>&1; then
        echo "   ⚠️  Note: Python Tkinter (_tkinter) is not installed."
        MISSING_PKGS="$MISSING_PKGS python3-tk"
    else
        echo "   -> Tkinter GUI support: OK"
    fi

    # Check Ayatana AppIndicator for native system tray support in GNOME / Ubuntu
    if ! "$PYTHON_BIN" -c "import gi; gi.require_version('AyatanaAppIndicator3', '0.1')" >/dev/null 2>&1 && \
       ! "$PYTHON_BIN" -c "import gi; gi.require_version('AppIndicator3', '0.1')" >/dev/null 2>&1; then
        echo "   ⚠️  Note: AppIndicator library is not installed."
        MISSING_PKGS="$MISSING_PKGS python3-gi gir1.2-ayatanaappindicator3-0.1"
    else
        echo "   -> AppIndicator tray support: OK"
    fi

    # Offer automatic package installation on Debian/Ubuntu if interactive
    if [ -n "$MISSING_PKGS" ]; then
        if command -v apt-get >/dev/null 2>&1 && [ -t 0 ]; then
            echo ""
            echo "   💡 Would you like to automatically install missing GUI packages?"
            read -r -p "      Run 'sudo apt install -y$MISSING_PKGS'? [Y/n] " answer
            if [[ -z "$answer" || "$answer" =~ ^[Yy]$ ]]; then
                sudo apt-get update -qq && sudo apt-get install -y $MISSING_PKGS || true
            fi
        else
            echo "      To install manually, run:"
            echo "      Ubuntu/Debian: sudo apt install -y$MISSING_PKGS"
            echo "      Fedora:        sudo dnf install -y python3-tkinter libappindicator-gtk3 python3-gobject"
            echo "      Arch Linux:    sudo pacman -S tk libayatana-appindicator python-gobject"
        fi
    fi
else
    echo "[2/5] Server / headless environment detected (no active DISPLAY). Skipping GUI checks."
fi

# 3. Setup Virtual Environment
echo "[3/5] Setting up Python virtual environment..."
VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "   -> Creating virtual environment in $VENV_DIR (with system-site-packages)..."
    if ! "$PYTHON_BIN" -m venv --system-site-packages "$VENV_DIR" 2>/dev/null; then
        echo "   ⚠️  python3-venv package may be missing. Attempting pip install without venv..."
        VENV_PYTHON="$PYTHON_BIN"
    else
        VENV_PYTHON="$VENV_DIR/bin/python3"
    fi
else
    VENV_PYTHON="$VENV_DIR/bin/python3"
    # Ensure system site packages is enabled in existing pyvenv.cfg
    if [ -f "$VENV_DIR/pyvenv.cfg" ]; then
        sed -i 's/include-system-site-packages = false/include-system-site-packages = true/g' "$VENV_DIR/pyvenv.cfg" 2>/dev/null || true
    fi
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

if [ "$HAS_DISPLAY" -eq 1 ] || [ -d "$HOME/Desktop" ] || [ -d "$HOME/.local/share/applications" ]; then
    # Desktop shortcut
    DESKTOP_PATH="$HOME/Desktop"
    if command -v xdg-user-dir >/dev/null 2>&1; then
        XDG_DESK=$(xdg-user-dir DESKTOP 2>/dev/null || true)
        if [ -n "$XDG_DESK" ] && [ -d "$XDG_DESK" ]; then
            DESKTOP_PATH="$XDG_DESK"
        fi
    fi
    # Local sync folder on Desktop if located elsewhere
    if [ -d "$DESKTOP_PATH" ] && [ "$SYNC_DIR" != "$DESKTOP_PATH/DropFile" ] && [ ! -e "$DESKTOP_PATH/DropFile" ]; then
        ln -s "$SYNC_DIR" "$DESKTOP_PATH/DropFile" 2>/dev/null || true
        echo "   -> Desktop folder symlink created: $DESKTOP_PATH/DropFile"
    fi

    # Application menu entry (.desktop)
    APP_DIR="$HOME/.local/share/applications"
    mkdir -p "$APP_DIR"
    ICON_PATH="$SCRIPT_DIR/icon.png"
    if [ ! -f "$ICON_PATH" ]; then
        ICON_PATH="$SCRIPT_DIR/icon.ico"
    fi

    cat > "$APP_DIR/dropfile.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DropFile
GenericName=File Synchronization Client
Comment=Lightweight Dropbox-style sync client for FileBrowser
Exec=$SCRIPT_DIR/run_linux.sh
Path=$SCRIPT_DIR
Icon=$ICON_PATH
Terminal=false
Categories=Utility;FileTools;Network;
StartupNotify=false
EOF
    chmod +x "$APP_DIR/dropfile.desktop"
    ln -sf "$APP_DIR/dropfile.desktop" "$APP_DIR/DropFile.desktop"
    echo "   -> Application launcher registered: $APP_DIR/dropfile.desktop"

    # Place clickable launcher icon on Desktop
    if [ -d "$DESKTOP_PATH" ]; then
        cp "$APP_DIR/dropfile.desktop" "$DESKTOP_PATH/DropFile.desktop"
        chmod +x "$DESKTOP_PATH/DropFile.desktop"
        gio set "$DESKTOP_PATH/DropFile.desktop" metadata::trusted true 2>/dev/null || true
        echo "   -> Desktop application icon created: $DESKTOP_PATH/DropFile.desktop"
    fi
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
echo "▶ To launch DropFile:"
if [ "$HAS_DISPLAY" -eq 1 ] || [ -d "$HOME/Desktop" ]; then
    echo "  1. Double-click the 'DropFile' icon on your Desktop"
    echo "  2. Or find 'DropFile' in your Applications menu (Super / Win key)"
    echo "  3. Or launch via terminal: ./run_linux.sh"
    echo "     (To open Settings dialog: ./run_linux.sh --settings)"
else
    echo "  ./run_linux.sh --headless       (runs background sync daemon)"
    echo "  systemctl --user start dropfile (starts via systemd)"
fi
echo ""
