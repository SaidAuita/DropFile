#!/bin/bash
# ==============================================================================
# DropFile — Installer for macOS (10.15 Catalina ... Tahoe / Sequoia)
# Launch by double-clicking in Finder or running in Terminal.
# ==============================================================================

set -e

# Change directory to script location
cd "$(dirname "$0")"
SCRIPT_DIR="$(pwd)"

# Strip macOS Gatekeeper quarantine and grant execute permissions
xattr -cr "$SCRIPT_DIR" 2>/dev/null || true
chmod +x "$SCRIPT_DIR"/*.command 2>/dev/null || true
chmod +x "$SCRIPT_DIR"/DropFile.pyw 2>/dev/null || true

echo "=================================================================="
echo "          DropFile — Client Installer for macOS                  "
echo "=================================================================="
echo ""

# 1. Locate Python 3
echo "[1/5] Checking Python 3 environment..."
PYTHON_BIN=""

CANDIDATES=(
    "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.10/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/Current/bin/python3"
    "/usr/local/bin/python3.13"
    "/usr/local/bin/python3.12"
    "/usr/local/bin/python3.11"
    "/usr/local/bin/python3.10"
    "/usr/local/bin/python3"
    "/opt/homebrew/bin/python3.13"
    "/opt/homebrew/bin/python3.12"
    "/opt/homebrew/bin/python3.11"
    "/opt/homebrew/bin/python3.10"
    "/opt/homebrew/bin/python3"
    "python3"
)

# First pass: find Python with Tkinter support
for cand in "${CANDIDATES[@]}"; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c "import sys, tkinter" >/dev/null 2>&1; then
            VER=$("$cand" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
            PYTHON_BIN="$cand"
            echo "   -> Found Python $VER with Tkinter ($cand)"
            break
        fi
    fi
done

# If no Python has Tkinter, attempt Homebrew auto-install or official Python
if [ -z "$PYTHON_BIN" ]; then
    echo "   ⚠️  No Python with Tkinter (_tkinter) found."
    
    BREW_BIN=""
    for b in "brew" "/usr/local/bin/brew" "/opt/homebrew/bin/brew"; do
        if command -v "$b" >/dev/null 2>&1; then
            BREW_BIN="$b"
            break
        fi
    done

    if [ -n "$BREW_BIN" ]; then
        echo "   -> Homebrew detected at $BREW_BIN."
        echo "   -> Installing python-tk via Homebrew..."
        "$BREW_BIN" install python-tk || true

        # Re-check candidates
        for cand in "${CANDIDATES[@]}"; do
            if command -v "$cand" >/dev/null 2>&1; then
                if "$cand" -c "import sys, tkinter" >/dev/null 2>&1; then
                    VER=$("$cand" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
                    PYTHON_BIN="$cand"
                    echo "   -> Found Python $VER with Tkinter ($cand)"
                    break
                fi
            fi
        done
    fi
fi

# If still no Python with Tkinter, prompt to install official Python or fallback
if [ -z "$PYTHON_BIN" ]; then
    for cand in "${CANDIDATES[@]}"; do
        if command -v "$cand" >/dev/null 2>&1; then
            VER=$("$cand" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
            if [ -n "$VER" ]; then
                PYTHON_BIN="$cand"
                break
            fi
        fi
    done

    echo ""
    echo "=================================================================="
    echo "⚠️  Tkinter is required for the Settings GUI, but was not found."
    echo "Current Python: $PYTHON_BIN ($VER)"
    echo "=================================================================="
    read -p "Install official Python 3.12 (with built-in Tkinter) now? [Y/n]: " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
        echo "Downloading official Python 3.12 installer..."
        curl -fSL -o /tmp/python-3.12.8-macos11.pkg https://www.python.org/ftp/python/3.12.8/python-3.12.8-macos11.pkg
        echo "Installing Python 3.12 (administrator password may be requested)..."
        sudo installer -pkg /tmp/python-3.12.8-macos11.pkg -target /
        rm -f /tmp/python-3.12.8-macos11.pkg
        "/Applications/Python 3.12/Install Certificates.command" 2>/dev/null || true
        PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
        echo "   -> Successfully configured: $PYTHON_BIN"
    fi
fi

if [ -z "$PYTHON_BIN" ]; then
    echo ""
    echo "❌ Error: Python 3 was not found on your system."
    read -p "Press Enter to exit..."
    exit 1
fi

# Clear quarantine flags and ensure execution permissions in current folder
xattr -cr "$SCRIPT_DIR" 2>/dev/null || true
chmod +x "$SCRIPT_DIR"/*.command 2>/dev/null || true
chmod +x "$SCRIPT_DIR"/DropFile.pyw 2>/dev/null || true

# 2. Virtual environment (.venv)
echo ""
echo "[2/5] Setting up isolated environment (.venv)..."
if [ -d ".venv" ]; then
    RECREATE_VENV=0
    # Recreate if folder relocated
    if [ ! -f ".venv/bin/activate" ] || ! grep -Fq "$SCRIPT_DIR" ".venv/bin/activate" 2>/dev/null; then
        echo "   -> Folder location changed. Recreating .venv for new path..."
        RECREATE_VENV=1
    # Recreate if .venv lacks Tkinter but PYTHON_BIN now has it
    elif ! .venv/bin/python3 -c "import tkinter" >/dev/null 2>&1; then
        echo "   -> Existing .venv lacks Tkinter. Recreating .venv with $PYTHON_BIN..."
        RECREATE_VENV=1
    fi

    if [ "$RECREATE_VENV" -eq 1 ]; then
        rm -rf ".venv" 2>/dev/null || true
    fi
fi

if [ ! -d ".venv" ]; then
    "$PYTHON_BIN" -m venv .venv
    echo "   -> Created .venv environment using $PYTHON_BIN."
else
    echo "   -> Using existing .venv environment."
fi

# Activate venv
source .venv/bin/activate
VENV_PY="$SCRIPT_DIR/.venv/bin/python3"

# 3. Install dependencies
echo ""
echo "[3/5] Installing dependencies (requests, pystray, pillow, watchdog, pyobjc)..."
pip install --upgrade pip >/dev/null 2>&1 || true
pip install -r requirements-mac.txt

# 4. Build DropFile.app bundle
echo ""
echo "[4/5] Building native DropFile.app bundle..."
APP_DEST="/Applications"
if [ ! -w "$APP_DEST" ]; then
    APP_DEST="$HOME/Applications"
fi
mkdir -p "$APP_DEST"
echo "   -> Target directory: $APP_DEST"

"$VENV_PY" mac_bundle.py --target "$APP_DEST"
chmod -R 755 "$APP_DEST/DropFile.app" 2>/dev/null || true
chmod +x "$APP_DEST/DropFile.app/Contents/MacOS/DropFile" 2>/dev/null || true
chmod +x "$SCRIPT_DIR/DropFile.pyw" 2>/dev/null || true
chmod +x "$SCRIPT_DIR"/*.command 2>/dev/null || true
xattr -cr "$APP_DEST/DropFile.app" 2>/dev/null || true
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP_DEST/DropFile.app" 2>/dev/null || true

# 5. Setup sync folder and Desktop shortcut
echo ""
echo "[5/5] Setting up sync directory and Desktop shortcut..."
DESKTOP_PATH="$HOME/Desktop/DropFile"
SYNC_DIR="$HOME/Desktop/DropFile_Sync"
mkdir -p "$SYNC_DIR"
if [ ! -e "$DESKTOP_PATH" ]; then
    ln -s "$SYNC_DIR" "$DESKTOP_PATH" 2>/dev/null || true
    echo "   -> Created Desktop shortcut: $DESKTOP_PATH"
fi

echo ""
echo "=================================================================="
echo "🎉 Installation completed successfully!"
echo "Application installed to: $APP_DEST/DropFile.app"
echo "The icon will appear in the menu bar at the top right."
echo "=================================================================="
echo ""

read -p "Launch DropFile right now? [Y/n]: " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
    echo "Launching DropFile..."
    if ! open "$APP_DEST/DropFile.app" 2>/dev/null; then
        echo "Notice: LaunchServices open returned an issue; starting directly..."
        "$APP_DEST/DropFile.app/Contents/MacOS/DropFile" >/dev/null 2>&1 &
    fi
fi

echo "Done! You can close this window."
exit 0
