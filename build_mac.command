#!/bin/bash
# ==============================================================================
# DropFile — Build Standalone Native macOS Application (.app)
# ==============================================================================

set -e
cd "$(dirname "$0")"

# Remove quarantine attributes
xattr -cr . 2>/dev/null || true

# Activate virtual environment if present
if [ -d ".venv" ] && [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

python3 build_mac.py

echo ""
echo "Select installation destination:"
echo "  1) /Applications (System Applications — Recommended)"
echo "  2) ~/Applications (User Applications: $HOME/Applications)"
echo "  3) Keep in dist/ only (Do not copy)"
echo ""
read -p "Install location [1]: " DEST_CHOICE
DEST_CHOICE="${DEST_CHOICE:-1}"

TARGET_DIR=""
if [ "$DEST_CHOICE" = "1" ]; then
    TARGET_DIR="/Applications"
elif [ "$DEST_CHOICE" = "2" ]; then
    TARGET_DIR="$HOME/Applications"
else
    echo "Skipping installation step. You can find the app in dist/DropFile.app"
fi

if [ -n "$TARGET_DIR" ]; then
    echo ""
    echo "Installing DropFile.app to $TARGET_DIR/..."
    mkdir -p "$TARGET_DIR" 2>/dev/null || true
    
    # Remove older version if present
    rm -rf "$TARGET_DIR/DropFile.app" 2>/dev/null || sudo rm -rf "$TARGET_DIR/DropFile.app" 2>/dev/null || true
    
    # Copy new application bundle
    if cp -R dist/DropFile.app "$TARGET_DIR/" 2>/dev/null; then
        echo "   -> Copied successfully."
    else
        echo "   -> Admin privileges required to install to $TARGET_DIR. Requesting sudo..."
        sudo cp -R dist/DropFile.app "$TARGET_DIR/"
    fi
    
    TARGET_APP="$TARGET_DIR/DropFile.app"
    chmod -R 755 "$TARGET_APP" 2>/dev/null || sudo chmod -R 755 "$TARGET_APP" 2>/dev/null || true
    xattr -cr "$TARGET_APP" 2>/dev/null || sudo xattr -cr "$TARGET_APP" 2>/dev/null || true
    /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$TARGET_APP" 2>/dev/null || true
    
    echo ""
    echo "=================================================================="
    echo "🎉 Successfully installed to: $TARGET_APP"
    echo "=================================================================="
    echo ""
    read -p "Launch DropFile right now? [Y/n]: " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
        echo "Launching DropFile..."
        open "$TARGET_APP"
    fi
fi

echo ""
echo "Done! You can close this Terminal window."
exit 0
