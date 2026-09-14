"""
DropFile — Universal macOS Application Bundle Packager.
Creates dist/DropFile-macOS.zip containing DropFile.app with POSIX permissions,
executable launcher script, embedded source code, and configuration metadata.
Runs on any macOS (Catalina through Sequoia / Tahoe) with Python 3.
"""

import io
import os
import plistlib
import sys
import zipfile
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from version import __version__


def package_mac_zip(output_zip: Path = None) -> Path:
    dist_dir = root_dir / "dist"
    dist_dir.mkdir(exist_ok=True)

    if output_zip is None:
        output_zip = dist_dir / "DropFile-macOS.zip"

    print(f"[package_mac] Creating universal macOS bundle for DropFile v{__version__}...")

    # 1. Prepare Info.plist
    info_plist_data = {
        "CFBundleName": "DropFile",
        "CFBundleDisplayName": "DropFile",
        "CFBundleIdentifier": "com.saidauita.dropfile",
        "CFBundleVersion": __version__,
        "CFBundleShortVersionString": __version__,
        "CFBundlePackageType": "APPL",
        "CFBundleSignature": "????",
        "CFBundleExecutable": "DropFile",
        "CFBundleIconFile": "AppIcon",
        "LSUIElement": True,  # Status bar item, no Dock clutter
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "10.15",
    }
    plist_bytes = plistlib.dumps(info_plist_data)

    # 2. Prepare launcher script
    launcher_script = """#!/bin/bash
export LANG="en_US.UTF-8"
export LC_ALL="en_US.UTF-8"

BUNDLE_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
APP_SRC="$BUNDLE_DIR/Contents/Resources/app"
cd "$APP_SRC" || exit 1

LOG_DIR="$HOME/Library/Application Support/DropFile"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/dropfile.log"

# Rotate log file if exceeds 2MB
if [ -f "$LOG_FILE" ]; then
    LOG_SIZE=$(stat -f%z "$LOG_FILE" 2>/dev/null || stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
    if [ "$LOG_SIZE" -gt 2097152 ]; then
        mv "$LOG_FILE" "$LOG_FILE.old" 2>/dev/null || true
    fi
fi

# Detect Python with Tkinter
PYTHON_EXEC=""
CANDIDATES=(
    "$APP_SRC/.venv/bin/python3"
    "$HOME/Desktop/DropFile-main/.venv/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.10/bin/python3"
    "/usr/local/bin/python3"
    "/opt/homebrew/bin/python3"
    "python3"
)

for cand in "${CANDIDATES[@]}"; do
    if [ -x "$cand" ] || command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c "import tkinter" >/dev/null 2>&1; then
            PYTHON_EXEC="$cand"
            break
        fi
    fi
done

if [ -z "$PYTHON_EXEC" ]; then
    PYTHON_EXEC="python3"
fi

echo "=== DropFile launched: $(date) ===" >> "$LOG_FILE"
echo "App src: $APP_SRC" >> "$LOG_FILE"
echo "Python: $PYTHON_EXEC" >> "$LOG_FILE"

if [ -t 1 ]; then
    exec "$PYTHON_EXEC" "$APP_SRC/DropFile.pyw" "$@"
else
    exec "$PYTHON_EXEC" "$APP_SRC/DropFile.pyw" "$@" >> "$LOG_FILE" 2>&1
    EXIT_CODE=$?
    if [ $EXIT_CODE -ne 0 ]; then
        LAST_ERR=$(tail -n 8 "$LOG_FILE" 2>/dev/null | tr '\\n' ' ' | sed 's/"/\\\\"/g' | cut -c 1-250)
        osascript -e "display alert \\"DropFile Error\\" message \\"DropFile exited unexpectedly (code $EXIT_CODE).\\n\\n$LAST_ERR\\n\\nSee log: $LOG_FILE\\" as critical" 2>/dev/null || true
    fi
    exit $EXIT_CODE
fi
"""

    # 3. Files to include in the portable DropFile macOS package
    include_files = [
        "Install.command",
        "Run.command",
        "install_mac.command",
        "run_mac.command",
        "README_MAC.txt",
        "README.md",
        "DropFile.pyw",
        "config.py",
        "config.example.json",
        "fb_client.py",
        "gui_settings.py",
        "i18n.py",
        "icons.py",
        "platform_utils.py",
        "state_db.py",
        "sync_engine.py",
        "updater.py",
        "version.py",
        "win_utils.py",
        "mac_bundle.py",
        "requirements-mac.txt",
        "icon.ico",
    ]

    # 4. Write zip with POSIX permissions and UNIX create_system
    if output_zip.exists():
        output_zip.unlink()

    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        def add_file(archive_path: str, data: bytes, executable: bool = False):
            zinfo = zipfile.ZipInfo(archive_path)
            zinfo.create_system = 3  # 3 = UNIX (ensures macOS/Linux honors executable bits)
            zinfo.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if executable else 0o644
            zinfo.external_attr = (mode << 16) | 0o100000
            zf.writestr(zinfo, data)

        # Add all project source and launcher files into DropFile/ folder
        for fname in include_files:
            fpath = root_dir / fname
            if fpath.exists():
                is_exec = fname.endswith((".command", ".pyw", ".sh"))
                add_file(
                    f"DropFile/{fname}",
                    fpath.read_bytes(),
                    executable=is_exec,
                )

    print(f"[package_mac] Successfully created portable folder package: {output_zip} ({output_zip.stat().st_size} bytes)")
    return output_zip


if __name__ == "__main__":
    package_mac_zip()

