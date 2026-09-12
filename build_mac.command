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
read -p "Install DropFile.app to ~/Applications now? [Y/n]: " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
    mkdir -p "$HOME/Applications"
    rm -rf "$HOME/Applications/DropFile.app"
    cp -R dist/DropFile.app "$HOME/Applications/"
    chmod -R 755 "$HOME/Applications/DropFile.app"
    xattr -cr "$HOME/Applications/DropFile.app" 2>/dev/null || true
    /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$HOME/Applications/DropFile.app" 2>/dev/null || true
    echo "Installed to $HOME/Applications/DropFile.app"
    
    echo ""
    read -p "Launch DropFile right now? [Y/n]: " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
        open "$HOME/Applications/DropFile.app"
    fi
fi

echo ""
echo "Done! You can close this Terminal window."
exit 0
