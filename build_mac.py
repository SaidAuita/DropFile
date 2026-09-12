"""
DropFile — Native macOS Standalone Application Builder using PyInstaller.
Creates:
  dist/DropFile.app (Standalone native macOS Application bundle)
  dist/DropFile-macOS.zip (Portable zip archive for distribution)

Requirements:
  - macOS (10.15 Catalina or newer)
  - Python 3.9+ with Tkinter and dependencies from requirements-mac.txt
  - PyInstaller
"""

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from version import __version__


def build_mac_app() -> Path:
    root_dir = Path(__file__).resolve().parent
    dist_dir = root_dir / "dist"
    app_dir = dist_dir / "DropFile.app"
    zip_path = dist_dir / "DropFile-macOS.zip"

    print("==================================================================")
    print(f"       DropFile v{__version__} — Native macOS Application Builder")
    print("==================================================================")

    # 1. Ensure PyInstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("[build_mac] Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 2. Generate icons if Pillow and iconutil are available
    resources_dir = root_dir / "build_resources"
    resources_dir.mkdir(exist_ok=True)
    icns_file = resources_dir / "AppIcon.icns"

    try:
        from icons import create_tray_icon

        iconset_dir = resources_dir / "AppIcon.iconset"
        iconset_dir.mkdir(exist_ok=True)
        sizes = [16, 32, 64, 128, 256, 512]
        for s in sizes:
            img = create_tray_icon("idle", size=s)
            img.save(str(iconset_dir / f"icon_{s}x{s}.png"), format="PNG")
            img_2x = create_tray_icon("idle", size=s * 2)
            img_2x.save(str(iconset_dir / f"icon_{s}x{s}@2x.png"), format="PNG")

        if shutil.which("iconutil"):
            subprocess.run(
                ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_file)],
                check=True,
                capture_output=True,
            )
            print(f"[build_mac] Generated native icon: {icns_file}")
            shutil.rmtree(iconset_dir, ignore_errors=True)
    except Exception as e:
        print(f"[build_mac] Note on icon generation: {e}")

    # 3. Assemble PyInstaller command
    entrypoint = root_dir / "DropFile.pyw"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--name=DropFile",
        "--osx-bundle-identifier=com.saidauita.dropfile",
        f"--add-data=config.example.json{os.pathsep}.",
        f"--add-data=icon.ico{os.pathsep}.",
        "--hidden-import=pystray._darwin",
        "--hidden-import=PIL",
        "--hidden-import=AppKit",
        "--hidden-import=Foundation",
        "--hidden-import=objc",
    ]

    if icns_file.exists():
        cmd.append(f"--icon={icns_file}")

    cmd.append(str(entrypoint))

    print(f"[build_mac] Running PyInstaller...")
    subprocess.check_call(cmd, cwd=str(root_dir))

    # 4. Enhance Info.plist with native agent properties
    info_plist_path = app_dir / "Contents" / "Info.plist"
    if info_plist_path.exists():
        try:
            with open(info_plist_path, "rb") as f:
                plist = plistlib.load(f)

            plist["CFBundleName"] = "DropFile"
            plist["CFBundleDisplayName"] = "DropFile"
            plist["CFBundleVersion"] = __version__
            plist["CFBundleShortVersionString"] = __version__
            plist["CFBundleIdentifier"] = "com.saidauita.dropfile"
            plist["LSUIElement"] = True  # Agent app: status bar only, no Dock icon!
            plist["NSHighResolutionCapable"] = True
            plist["LSMinimumSystemVersion"] = "10.15"

            if icns_file.exists():
                plist["CFBundleIconFile"] = "AppIcon"
                dest_icns = app_dir / "Contents" / "Resources" / "AppIcon.icns"
                dest_icns.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(icns_file, dest_icns)

            with open(info_plist_path, "wb") as f:
                plistlib.dump(plist, f)

            print("[build_mac] Configured Info.plist (LSUIElement=True, version synced).")
        except Exception as e:
            print(f"[build_mac] Error updating Info.plist: {e}")

    # 5. Fix permissions and remove quarantine attributes
    try:
        subprocess.run(["chmod", "-R", "755", str(app_dir)], check=False)
        subprocess.run(["xattr", "-cr", str(app_dir)], check=False)
    except Exception:
        pass

    # 6. Create distribution ZIP
    if zip_path.exists():
        zip_path.unlink()

    print("[build_mac] Packaging portable zip archive...")
    try:
        shutil.make_archive(
            str(dist_dir / "DropFile-macOS"),
            "zip",
            root_dir=str(dist_dir),
            base_dir="DropFile.app",
        )
        print(f"[build_mac] Created distribution archive: {zip_path}")
    except Exception as e:
        print(f"[build_mac] Error creating zip: {e}")

    print("")
    print("==================================================================")
    print("🎉 Native macOS Application built successfully!")
    print(f"App bundle: {app_dir}")
    print(f"Distribution zip: {zip_path}")
    print("You can now move DropFile.app to /Applications and run it standalone!")
    print("==================================================================")
    return app_dir


if __name__ == "__main__":
    build_mac_app()
