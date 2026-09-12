"""
Windows integration utilities for DropFile.
Handles:
- Desktop shortcut creation
- Startup with Windows registry management (HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run)
- Windows Explorer integration
"""

import os
import subprocess
import sys
import winreg
from pathlib import Path
from typing import Optional

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "DropFile"


def create_desktop_shortcut(target_folder: Path | str, shortcut_name: str = "DropFile.lnk") -> bool:
    """
    Creates a shortcut on the current user's Desktop pointing to target_folder.
    Uses PowerShell to create WScript.Shell shortcut.
    """
    target = Path(target_folder).resolve()
    desktop = Path.home() / "Desktop"
    shortcut_path = desktop / shortcut_name

    ps_script = f"""
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut('{str(shortcut_path)}')
    $Shortcut.TargetPath = '{str(target)}'
    $Shortcut.IconLocation = 'shell32.dll,3'
    $Shortcut.Description = 'DropFile Sync Folder'
    $Shortcut.Save()
    """

    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            check=True,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0,
        )
        return True
    except Exception as e:
        print(f"[win_utils] Error creating desktop shortcut: {e}")
        return False


def set_windows_autostart(enable: bool, script_path: Optional[Path | str] = None) -> bool:
    """
    Adds or removes DropFile from Windows startup (HKCU\\Run).
    Uses pythonw.exe to run without a command prompt window.
    """
    if not sys.platform.startswith("win"):
        return False

    if script_path is None:
        script_dir = Path(__file__).resolve().parent
        script_path = script_dir / "DropFile.pyw"

    py_exe = Path(sys.executable)
    # Prefer pythonw.exe if available for silent startup
    pyw_exe = py_exe.parent / "pythonw.exe"
    runner = pyw_exe if pyw_exe.exists() else py_exe

    cmd_line = f'"{runner}" "{Path(script_path).resolve()}"'

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
        ) as key:
            if enable:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd_line)
                print(f"[win_utils] Autostart enabled: {cmd_line}")
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                    print("[win_utils] Autostart disabled.")
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        print(f"[win_utils] Error setting autostart: {e}")
        return False


def is_windows_autostart_enabled() -> bool:
    """Checks if DropFile is currently set to start with Windows."""
    if not sys.platform.startswith("win"):
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_QUERY_VALUE) as key:
            val, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def open_folder_in_explorer(folder_path: Path | str) -> None:
    """Opens a folder in Windows File Explorer."""
    p = Path(folder_path)
    p.mkdir(parents=True, exist_ok=True)
    if sys.platform.startswith("win"):
        os.startfile(str(p))
    else:
        subprocess.run(["xdg-open", str(p)])
