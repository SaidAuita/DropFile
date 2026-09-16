#!/bin/bash
# ==============================================================================
# DropFile — Linux Portable Runner
# Usage:
#   ./run_linux.sh              # Start in background (Tray or Headless)
#   ./run_linux.sh --settings   # Open GUI Settings Dialog
#   ./run_linux.sh --headless   # Run in Headless Daemon Mode
#   ./run_linux.sh --status     # Query running instance status
#   ./run_linux.sh --sync-now   # Trigger immediate synchronization
#   ./run_linux.sh --stop       # Stop running instance
# ==============================================================================

cd "$(dirname "$0")"

# If .venv exists, use it
if [ -d ".venv" ] && [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    python3 DropFile.pyw "$@"
else
    python3 DropFile.pyw "$@"
fi
