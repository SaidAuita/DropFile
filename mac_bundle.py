"""
Helper script to package DropFile into a native macOS Application Bundle (.app).
Creates:
~/Applications/DropFile.app
with embedded icon, launcher script, and LSUIElement=1 (menu bar background agent).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


from version import __version__


def create_mac_app(
    target_dir: Path = None,
    python_path: Path = None,
    source_dir: Path = None,
) -> Path:
    if source_dir is None:
        source_dir = Path(__file__).resolve().parent

    if target_dir is None:
        target_dir = Path.home() / "Applications"
    target_dir.mkdir(parents=True, exist_ok=True)

    if python_path is None:
        # Keep current Python path WITHOUT resolving symlinks so virtualenv (.venv)
        # paths and site-packages are preserved.
        python_path = Path(sys.executable)

    app_dir = target_dir / "DropFile.app"
    if app_dir.exists():
        shutil.rmtree(app_dir)

    contents_dir = app_dir / "Contents"
    macos_dir = contents_dir / "MacOS"
    resources_dir = contents_dir / "Resources"

    macos_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)

    # 1. Launcher shell script
    launcher_script = macos_dir / "DropFile"
    entrypoint = source_dir / "DropFile.pyw"

    launcher_content = f"""#!/bin/bash
export LANG="en_US.UTF-8"
export LC_ALL="en_US.UTF-8"

PROJECT_DIR="{source_dir.as_posix()}"
LOG_DIR="$HOME/Library/Application Support/DropFile"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/dropfile.log"

# Select Python executable with virtual environment priority
if [ -f "$PROJECT_DIR/.venv/bin/activate" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
    PYTHON_EXEC="$PROJECT_DIR/.venv/bin/python3"
elif [ -x "{python_path.as_posix()}" ]; then
    PYTHON_EXEC="{python_path.as_posix()}"
else
    PYTHON_EXEC="python3"
fi

# In interactive terminal output directly; under LaunchServices redirect to log
if [ -t 1 ]; then
    exec "$PYTHON_EXEC" "$PROJECT_DIR/DropFile.pyw" "$@"
else
    exec "$PYTHON_EXEC" "$PROJECT_DIR/DropFile.pyw" "$@" >> "$LOG_FILE" 2>&1
fi
"""
    with open(launcher_script, "w", newline="\n", encoding="utf-8") as f:
        f.write(launcher_content)

    try:
        os.chmod(launcher_script, 0o755)
    except Exception:
        pass

    # 2. Generate icons if Pillow is available
    try:
        from icons import create_tray_icon
        icon_png = resources_dir / "AppIcon.png"
        img = create_tray_icon("idle", size=512)
        img.save(str(icon_png), format="PNG")

        # If on macOS with iconutil, convert to .icns
        iconset_dir = resources_dir / "AppIcon.iconset"
        iconset_dir.mkdir(exist_ok=True)
        sizes = [16, 32, 64, 128, 256, 512]
        for s in sizes:
            img_s = create_tray_icon("idle", size=s)
            img_s.save(str(iconset_dir / f"icon_{s}x{s}.png"), format="PNG")
            img_2x = create_tray_icon("idle", size=s * 2)
            fname_2x = f"icon_{s}x{s}" + "@2x.png"
            img_2x.save(str(iconset_dir / fname_2x), format="PNG")

        icns_file = resources_dir / "AppIcon.icns"
        subprocess.run(["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_file)], capture_output=True)
        shutil.rmtree(iconset_dir, ignore_errors=True)
    except Exception as e:
        print(f"[mac_bundle] Note on icon generation: {e}")

    # 3. Info.plist
    # LSUIElement = 1 makes DropFile run as a status bar item without taking space in the Dock
    info_plist = contents_dir / "Info.plist"
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>DropFile</string>
    <key>CFBundleDisplayName</key>
    <string>DropFile</string>
    <key>CFBundleIdentifier</key>
    <string>com.saidauita.dropfile</string>
    <key>CFBundleVersion</key>
    <string>{__version__}</string>
    <key>CFBundleShortVersionString</key>
    <string>{__version__}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleSignature</key>
    <string>????</string>
    <key>CFBundleExecutable</key>
    <string>DropFile</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
</dict>
</plist>
"""
    with open(info_plist, "w", newline="\n", encoding="utf-8") as f:
        f.write(plist_content)
    print(f"[mac_bundle] Successfully created macOS Application: {app_dir}")
    return app_dir


if __name__ == "__main__":
    create_mac_app()
