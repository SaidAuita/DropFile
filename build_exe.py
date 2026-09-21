"""
Build script to compile DropFile into a standalone Windows .exe executable using PyInstaller.
Produces a single, standalone, windowless (no console popup) DropFile.exe with embedded icon.
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from icons import create_app_icon_ico
from version import __version__, get_full_version


def build():
    root = Path(__file__).resolve().parent
    icon_path = root / "icon.ico"

    print(f"=== Building DropFile v{get_full_version()} Standalone Windows Executable ===")

    # 1. Ensure icon.ico exists
    if not icon_path.exists():
        print("Generating multi-resolution icon.ico...")
        create_app_icon_ico(icon_path)
    else:
        print(f"Using existing icon: {icon_path}")

    # 2. Prepare PyInstaller command
    pyinstaller_cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconsole",
        "--onefile",
        "--clean",
        f"--name=DropFile",
        f"--icon={icon_path}",
        f"--add-data={icon_path};.",
        "--hidden-import=pystray._win32",
        "--hidden-import=PIL",
        "--hidden-import=PIL.Image",
        "--hidden-import=PIL.ImageDraw",
        "--hidden-import=_sqlite3",
        "--hidden-import=sqlite3",
        "--collect-all=sqlite3",
        "--collect-all=requests",
        "--collect-submodules=pystray",
        "--collect-all=dropsync_server",
        "--hidden-import=traffic_monitor",
        "--hidden-import=gui_speed_chart",
        "--hidden-import=build_sync",
        "--hidden-import=gui_build_sync",
    ]

    # Explicitly bundle sqlite3.dll if found in Python DLLs directory
    dlls_dir = Path(sys.executable).parent / "DLLs"
    sqlite_dll = dlls_dir / "sqlite3.dll"
    if sqlite_dll.exists():
        pyinstaller_cmd.append(f"--add-binary={sqlite_dll};.")

    pyinstaller_cmd.append(str(root / "DropFile.pyw"))

    print("Running PyInstaller...")
    print("Command:", " ".join(pyinstaller_cmd))

    res = subprocess.run(pyinstaller_cmd, cwd=str(root))
    if res.returncode != 0:
        print("Build FAILED!")
        sys.exit(res.returncode)

    dist_exe = root / "dist" / "DropFile.exe"
    if dist_exe.exists():
        size_mb = dist_exe.stat().st_size / (1024 * 1024)
        print("=" * 60)
        print(f"BUILD SUCCESSFUL!")
        print(f"Output executable: {dist_exe}")
        print(f"Size: {size_mb:.2f} MB")
        print("=" * 60)

        # Stop running instances before copying to deploy targets so files are not locked
        try:
            subprocess.run(["taskkill", "/F", "/IM", "DropFile.exe"], capture_output=True)
            time.sleep(0.5)
        except Exception:
            pass

        for deploy_target in [root.parent / "DropFile.exe", Path("D:/DropFile_exe/DropFile.exe")]:
            if deploy_target.parent.exists():
                try:
                    shutil.copy2(dist_exe, deploy_target)
                    print(f"Copied updated binary to: {deploy_target}")
                except Exception as e:
                    print(f"File locked ({deploy_target}): {e}")

    else:
        print("Build completed, but dist/DropFile.exe was not found!")
        sys.exit(1)


if __name__ == "__main__":
    build()
