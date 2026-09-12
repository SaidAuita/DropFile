"""
Platform integration utilities for DropFile.
Cross-platform support for:
- Windows (10, 11)
- macOS (10.15 Catalina, Big Sur, Monterey, Ventura, Sonoma, Sequoia, Tahoe)
- Linux
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

APP_NAME = "DropFile"
MACOS_BUNDLE_ID = "com.saidauita.dropfile"

# Windows-specific import
try:
    import winreg
except ImportError:
    winreg = None


def create_desktop_shortcut(target_folder: Path | str, shortcut_name: str = "DropFile") -> bool:
    """Creates a shortcut or symlink on the user's Desktop pointing to target_folder."""
    target = Path(target_folder).resolve()
    desktop = Path.home() / "Desktop"

    if sys.platform == "darwin":
        link_path = desktop / shortcut_name
        if not link_path.exists():
            try:
                os.symlink(target, link_path)
                print(f"[platform_utils] Created macOS Desktop symlink: {link_path} -> {target}")
                return True
            except Exception as e:
                print(f"[platform_utils] Error creating Desktop symlink: {e}")
                return False
        return True

    elif sys.platform.startswith("win"):
        lnk_name = f"{shortcut_name}.lnk" if not shortcut_name.endswith(".lnk") else shortcut_name
        shortcut_path = desktop / lnk_name
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
                creationflags=0x08000000,
            )
            return True
        except Exception as e:
            print(f"[platform_utils] Error creating desktop shortcut: {e}")
            return False
    else:
        # Linux symlink
        link_path = desktop / shortcut_name
        if not link_path.exists():
            try:
                os.symlink(target, link_path)
                return True
            except Exception:
                pass
        return False


def remove_desktop_shortcut(shortcut_name: str = "DropFile") -> bool:
    """Removes the Desktop shortcut or symlink if it exists."""
    desktop = Path.home() / "Desktop"
    candidates = [
        desktop / shortcut_name,
        desktop / f"{shortcut_name}.lnk",
    ]
    removed = False
    for path in candidates:
        if path.is_symlink() or path.exists():
            try:
                path.unlink()
                removed = True
                print(f"[platform_utils] Removed shortcut: {path}")
            except Exception as e:
                print(f"[platform_utils] Error removing shortcut {path}: {e}")
    return removed


def set_autostart(enable: bool, script_path: Optional[Path | str] = None) -> bool:
    """Enables or disables autostart on system boot/login."""
    if sys.platform == "darwin":
        plist_path = Path.home() / "Library" / "LaunchAgents" / f"{MACOS_BUNDLE_ID}.plist"
        if enable:
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            if getattr(sys, "frozen", False):
                exec_args = [str(Path(sys.executable).resolve())]
            else:
                target = Path(script_path or (Path(__file__).resolve().parent / "DropFile.pyw")).resolve()
                exec_args = [sys.executable, str(target)]

            args_xml = "\n".join(f"        <string>{a}</string>" for a in exec_args)
            plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{MACOS_BUNDLE_ID}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>/dev/null</string>
    <key>StandardErrorPath</key>
    <string>/dev/null</string>
</dict>
</plist>
"""
            try:
                plist_path.write_text(plist_content, encoding="utf-8")
                subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True)
                print(f"[platform_utils] macOS LaunchAgent installed: {plist_path}")
                return True
            except Exception as e:
                print(f"[platform_utils] Error setting macOS autostart: {e}")
                return False
        else:
            if plist_path.exists():
                try:
                    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
                except Exception:
                    pass
                try:
                    plist_path.unlink()
                    print(f"[platform_utils] macOS LaunchAgent removed: {plist_path}")
                except Exception:
                    pass
            return True

    elif sys.platform.startswith("win") and winreg:
        run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        if getattr(sys, "frozen", False):
            cmd_line = f'"{Path(sys.executable).resolve()}"'
        else:
            if script_path is None:
                script_path = Path(__file__).resolve().parent / "DropFile.pyw"
            py_exe = Path(sys.executable)
            pyw_exe = py_exe.parent / "pythonw.exe"
            runner = pyw_exe if pyw_exe.exists() else py_exe
            cmd_line = f'"{runner}" "{Path(script_path).resolve()}"'

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
            ) as key:
                if enable:
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd_line)
                    print(f"[platform_utils] Windows autostart enabled: {cmd_line}")
                else:
                    try:
                        winreg.DeleteValue(key, APP_NAME)
                        print("[platform_utils] Windows autostart disabled.")
                    except FileNotFoundError:
                        pass
            return True
        except Exception as e:
            print(f"[platform_utils] Error setting autostart: {e}")
            return False
    return False


def is_autostart_enabled() -> bool:
    """Checks if DropFile is configured to autostart."""
    if sys.platform == "darwin":
        plist_path = Path.home() / "Library" / "LaunchAgents" / f"{MACOS_BUNDLE_ID}.plist"
        return plist_path.exists()
    elif sys.platform.startswith("win") and winreg:
        run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_QUERY_VALUE) as key:
                val, _ = winreg.QueryValueEx(key, APP_NAME)
                return bool(val)
        except Exception:
            return False
    return False


def open_folder_in_file_manager(folder_path: Path | str) -> None:
    """Opens a folder in Finder on macOS or File Explorer on Windows."""
    p = Path(folder_path)
    p.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        subprocess.run(["open", str(p)])
    elif sys.platform.startswith("win"):
        os.startfile(str(p))
    else:
        subprocess.run(["xdg-open", str(p)])


def copy_to_clipboard(text: str) -> bool:
    """Copies text to the system clipboard."""
    if not text:
        return False

    if sys.platform == "darwin":
        try:
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            p.communicate(text.encode("utf-8"))
            return p.returncode == 0
        except Exception as e:
            print(f"[platform_utils] pbcopy error: {e}")
            return False

    # Windows fallback: PowerShell
    if sys.platform.startswith("win"):
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", "$input | Set-Clipboard"],
                input=text,
                text=True,
                check=True,
                capture_output=True,
                creationflags=0x08000000,
            )
            return True
        except Exception:
            pass

    # Cross-platform fallback: Tkinter (non-macOS only)
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text)
        r.update()
        r.destroy()
        return True
    except Exception:
        pass

    return False


def spawn_settings_process(script_path: Optional[Path | str] = None) -> Optional[subprocess.Popen]:
    """Spawns the Settings dialog in an independent process running on the main thread."""
    try:
        kwargs = {}
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

        if getattr(sys, "frozen", False):
            current_exe = Path(sys.executable).resolve()
            return subprocess.Popen([str(current_exe), "--settings"], **kwargs)
        else:
            if script_path is None:
                script_path = Path(__file__).resolve().parent / "DropFile.pyw"
            target = Path(script_path).resolve()
            return subprocess.Popen(
                [sys.executable, str(target), "--settings"],
                cwd=str(target.parent),
                **kwargs,
            )
    except Exception as e:
        print(f"[platform_utils] Error spawning settings process: {e}")
        return None


def restart_dropfile(script_path: Optional[Path | str] = None) -> bool:
    """Spawns a new independent instance of DropFile and returns."""
    if sys.platform == "darwin":
        try:
            if getattr(sys, "frozen", False):
                app_bundle = None
                for parent in Path(sys.executable).parents:
                    if parent.suffix == ".app":
                        app_bundle = parent
                        break
                if app_bundle:
                    subprocess.Popen(["open", "-n", str(app_bundle)])
                else:
                    subprocess.Popen([sys.executable])
            else:
                target = Path(script_path or (Path(__file__).resolve().parent / "DropFile.pyw")).resolve()
                subprocess.Popen([sys.executable, str(target)], cwd=str(target.parent))
            return True
        except Exception as e:
            print(f"[platform_utils] macOS restart error: {e}")
            return False

    elif sys.platform.startswith("win"):
        creation_flags = 0x08000000 | 0x00000008  # CREATE_NO_WINDOW | DETACHED_PROCESS
        env = os.environ.copy()
        for k in list(env.keys()):
            if k.startswith(("_PYI", "PYI", "_MEI")):
                env.pop(k, None)
        if hasattr(sys, "_MEIPASS"):
            paths = env.get("PATH", "").split(os.pathsep)
            cleaned = [p for p in paths if not p.lower().startswith(sys._MEIPASS.lower())]
            env["PATH"] = os.pathsep.join(cleaned)

        try:
            if getattr(sys, "frozen", False):
                current_exe = Path(sys.executable).resolve()
                subprocess.Popen(
                    [str(current_exe)],
                    cwd=str(current_exe.parent),
                    env=env,
                    creationflags=creation_flags,
                    close_fds=True,
                )
            else:
                if script_path is None:
                    script_path = Path(__file__).resolve().parent / "DropFile.pyw"
                py_exe = Path(sys.executable)
                pyw_exe = py_exe.parent / "pythonw.exe"
                runner = pyw_exe if pyw_exe.exists() else py_exe
                target = Path(script_path).resolve()
                subprocess.Popen(
                    [str(runner), str(target)],
                    cwd=str(target.parent),
                    env=env,
                    creationflags=creation_flags,
                    close_fds=True,
                )
            return True
        except Exception as e:
            print(f"[platform_utils] Windows restart error: {e}")
            return False
    return False


# Aliases for backward compatibility with win_utils naming
set_windows_autostart = set_autostart
is_windows_autostart_enabled = is_autostart_enabled
open_folder_in_explorer = open_folder_in_file_manager
