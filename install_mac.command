#!/bin/bash
# ==============================================================================
# DropFile — Installer for macOS (10.15 Catalina ... Tahoe / Sequoia)
# Launch by double-clicking in Finder or running in Terminal.
# ==============================================================================

set -e

# Change directory to script location
cd "$(dirname "$0")"
SCRIPT_DIR="$(pwd)"

echo "=================================================================="
echo "          DropFile — Client Installer for macOS                  "
echo "=================================================================="
echo ""

# 1. Locate Python 3
echo "[1/5] Checking Python 3 environment..."
PYTHON_BIN=""

CANDIDATES=(
    "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.10/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/Current/bin/python3"
    "/usr/local/bin/python3"
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

# Second pass fallback: any Python 3
if [ -z "$PYTHON_BIN" ]; then
    for cand in "${CANDIDATES[@]}"; do
        if command -v "$cand" >/dev/null 2>&1; then
            VER=$("$cand" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
            if [ -n "$VER" ]; then
                PYTHON_BIN="$cand"
                echo "   -> Found Python $VER ($cand)"
                echo "   ⚠️  Notice: Tkinter not detected in $cand. If Settings dialog doesn't appear, install python-tk (e.g. 'brew install python-tk')."
                break
            fi
        fi
    done
fi

if [ -z "$PYTHON_BIN" ]; then
    echo ""
    echo "❌ Error: Python 3 was not found on your system."
    echo ""
    echo "To quickly install Python 3, run in Terminal:"
    echo "1) Official installer in 1 command (recommended for macOS 10.15+):"
    echo "   curl -O https://www.python.org/ftp/python/3.11.9/python-3.11.9-macos11.pkg && sudo installer -pkg python-3.11.9-macos11.pkg -target /"
    echo "   \"/Applications/Python 3.11/Install Certificates.command\""
    echo ""
    echo "2) Via Apple Developer Command Line Tools:"
    echo "   xcode-select --install"
    echo ""
    echo "3) Or via Homebrew:"
    echo "   brew install python python-tk"
    echo ""
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
    # Python virtual environments contain hardcoded paths and cannot be relocated;
    # detect if folder was moved from another location and recreate .venv cleanly
    if [ -f ".venv/bin/activate" ]; then
        if ! grep -Fq "$SCRIPT_DIR" ".venv/bin/activate" 2>/dev/null; then
            echo "   -> Folder location changed. Recreating .venv for new path..."
            rm -rf ".venv" 2>/dev/null || true
        fi
    else
        rm -rf ".venv" 2>/dev/null || true
    fi
fi

if [ ! -d ".venv" ]; then
    "$PYTHON_BIN" -m venv .venv
    echo "   -> Created .venv environment."
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

# 4. Build DropFile.app in /Applications (System Applications)
echo ""
echo "[4/5] Building native DropFile.app bundle in /Applications..."
APP_DEST="/Applications"
if [ -w "$APP_DEST" ]; then
    "$VENV_PY" mac_bundle.py --target "$APP_DEST"
    chmod -R 755 "$APP_DEST/DropFile.app" 2>/dev/null || true
    chmod +x "$APP_DEST/DropFile.app/Contents/MacOS/DropFile" 2>/dev/null || true
    chmod +x "$SCRIPT_DIR/DropFile.pyw" 2>/dev/null || true
    xattr -cr "$APP_DEST/DropFile.app" 2>/dev/null || true
    /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP_DEST/DropFile.app" 2>/dev/null || true
else
    echo "   -> Administrator privileges required to install into /Applications. Requesting sudo..."
    sudo "$VENV_PY" mac_bundle.py --target "$APP_DEST"
    sudo chmod -R 755 "$APP_DEST/DropFile.app" 2>/dev/null || true
    sudo chmod +x "$APP_DEST/DropFile.app/Contents/MacOS/DropFile" 2>/dev/null || true
    chmod +x "$SCRIPT_DIR/DropFile.pyw" 2>/dev/null || true
    sudo xattr -cr "$APP_DEST/DropFile.app" 2>/dev/null || true
    /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP_DEST/DropFile.app" 2>/dev/null || true
fi

# Clean up older user-level bundle from ~/Applications if it exists
if [ -d "$HOME/Applications/DropFile.app" ]; then
    rm -rf "$HOME/Applications/DropFile.app" 2>/dev/null || true
fi

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
echo "Application installed to: /Applications/DropFile.app"
echo "The icon will appear in the menu bar at the top right."
echo "=================================================================="
echo ""

read -p "Launch DropFile right now? [Y/n]: " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
    echo "Launching DropFile..."
    if ! open "/Applications/DropFile.app" 2>/dev/null; then
        echo "Notice: LaunchServices open returned an issue; starting directly..."
        "/Applications/DropFile.app/Contents/MacOS/DropFile" >/dev/null 2>&1 &
    fi
fi

echo "Done! You can close this window."
exit 0
