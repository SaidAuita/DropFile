#!/bin/bash
# ==============================================================================
# DropFile — Portable runner
# ==============================================================================

cd "$(dirname "$0")"

# Remove quarantine flags
xattr -cr . 2>/dev/null || true

# Check if .venv was moved
if [ -d ".venv" ] && [ -f ".venv/bin/activate" ]; then
    if ! grep -Fq "$(pwd)" ".venv/bin/activate" 2>/dev/null; then
        echo "Notice: DropFile folder was moved. Reconfiguring environment..."
        ./install_mac.command
        exit 0
    fi
    source .venv/bin/activate
    python3 DropFile.pyw "$@"
else
    python3 DropFile.pyw "$@"
fi
