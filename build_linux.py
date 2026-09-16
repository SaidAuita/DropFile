"""
Build script to compile DropFile into a standalone Linux executable using PyInstaller.
Produces a single binary executable in dist/dropfile.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from version import __version__


def build():
    root = Path(__file__).resolve().parent
    icon_path = root / "icon.ico"

    print(f"=== Building DropFile v{__version__} Linux Standalone Executable ===")

    # Prepare PyInstaller command
    pyinstaller_cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconsole",
        "--onefile",
        "--clean",
        "--name=dropfile",
        f"--add-data={icon_path}:." if icon_path.exists() else None,
        "--hidden-import=pystray._appindicator",
        "--hidden-import=pystray._xorg",
        "--hidden-import=PIL",
        "--hidden-import=PIL.Image",
        "--hidden-import=PIL.ImageDraw",
        "--hidden-import=sqlite3",
        "--collect-all=requests",
        "--collect-submodules=pystray",
        str(root / "DropFile.pyw"),
    ]

    pyinstaller_cmd = [arg for arg in pyinstaller_cmd if arg is not None]

    print("Running PyInstaller...")
    print("Command:", " ".join(pyinstaller_cmd))

    res = subprocess.run(pyinstaller_cmd, cwd=str(root))
    if res.returncode != 0:
        print("❌ Build failed!")
        sys.exit(res.returncode)

    dist_bin = root / "dist" / "dropfile"
    if dist_bin.exists():
        dist_bin.chmod(0o755)
        size_mb = dist_bin.stat().st_size / (1024 * 1024)
        print(f"\n[OK] Build successful! Standalone binary: {dist_bin} ({size_mb:.1f} MB)")
        print(f"To run: ./dist/dropfile --headless or ./dist/dropfile")
    else:
        print("Build completed, but binary not found in dist/")


if __name__ == "__main__":
    build()
