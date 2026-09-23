"""
Platform integration utilities for DropFile.
Cross-platform support for:
- Windows (10, 11)
- macOS (10.15 Catalina, Big Sur, Monterey, Ventura, Sonoma, Sequoia, Tahoe)
- Linux
"""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

APP_NAME = "DropFile"
MACOS_BUNDLE_ID = "com.saidauita.dropfile"
_GLOBAL_MAC_IMP = None


def ensure_macos_tk_compatibility() -> None:
    """
    Ensures Tkinter compatibility on macOS by providing [NSApp macOSVersion].
    On macOS 10.15+, libtk8.6 invokes [NSApp macOSVersion] inside GetRGBA.
    When packaged with PyInstaller or when PyObjC initializes NSApplication,
    the method may not be found, triggering -[NSApplication macOSVersion]: unrecognized selector.
    This function dynamically injects the method into NSApplication both via PyObjC
    and directly into the Objective-C runtime via ctypes.
    """
    if sys.platform != "darwin":
        return

    global _GLOBAL_MAC_IMP

    # 1. PyObjC Category injection
    try:
        import platform
        import objc
        from AppKit import NSApplication

        def _get_ver():
            try:
                parts = [int(p) for p in platform.mac_ver()[0].split(".") if p.isdigit()]
                while len(parts) < 3:
                    parts.append(0)
                if not parts or parts[0] < 10:
                    return 150000
                return parts[0] * 10000 + parts[1] * 100 + parts[2]
            except Exception:
                return 150000

        ver = _get_ver()
        try:
            class NSApplication_TKFix(objc.Category(NSApplication)):
                @objc.typedSelector(b"i@:")
                def macOSVersion(self):
                    return ver
        except Exception:
            pass
    except Exception:
        pass

    # 2. Direct Objective-C runtime injection via ctypes (bulletproof fallback)
    try:
        import ctypes
        import ctypes.util
        import platform

        # Ensure AppKit framework is loaded in the process address space
        try:
            appkit_path = ctypes.util.find_library("AppKit") or "/System/Library/Frameworks/AppKit.framework/AppKit"
            ctypes.cdll.LoadLibrary(appkit_path)
        except Exception:
            pass

        objc_lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc") or "/usr/lib/libobjc.dylib")
        objc_lib.objc_getClass.restype = ctypes.c_void_p
        objc_lib.objc_getClass.argtypes = [ctypes.c_char_p]
        objc_lib.objc_getMetaClass.restype = ctypes.c_void_p
        objc_lib.objc_getMetaClass.argtypes = [ctypes.c_char_p]
        objc_lib.sel_registerName.restype = ctypes.c_void_p
        objc_lib.sel_registerName.argtypes = [ctypes.c_char_p]
        objc_lib.class_addMethod.restype = ctypes.c_bool
        objc_lib.class_addMethod.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_char_p,
        ]
        objc_lib.class_replaceMethod.restype = ctypes.c_void_p
        objc_lib.class_replaceMethod.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_char_p,
        ]

        parts = [int(p) for p in platform.mac_ver()[0].split(".") if p.isdigit()]
        while len(parts) < 3:
            parts.append(0)
        ver = parts[0] * 10000 + parts[1] * 100 + parts[2]
        if not parts or parts[0] < 10:
            ver = 150000

        IMP_FUNC = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

        def _macos_version_imp(self_ptr, cmd_ptr):
            return ver

        _GLOBAL_MAC_IMP = IMP_FUNC(_macos_version_imp)
        imp_ptr = ctypes.cast(_GLOBAL_MAC_IMP, ctypes.c_void_p)
        sel = objc_lib.sel_registerName(b"macOSVersion")

        # Add to instance methods on NSApplication
        cls = objc_lib.objc_getClass(b"NSApplication")
        if cls and sel:
            if not objc_lib.class_addMethod(cls, sel, imp_ptr, b"i@:"):
                objc_lib.class_replaceMethod(cls, sel, imp_ptr, b"i@:")

        # Add to class methods on NSApplication metaclass
        meta_cls = objc_lib.objc_getMetaClass(b"NSApplication")
        if meta_cls and sel:
            if not objc_lib.class_addMethod(meta_cls, sel, imp_ptr, b"i@:"):
                objc_lib.class_replaceMethod(meta_cls, sel, imp_ptr, b"i@:")

    except Exception as e:
        print(f"[platform_utils] Note on macOS Tkinter compatibility: {e}")


# Windows-specific import
try:
    import winreg
except ImportError:
    winreg = None


def get_desktop_dir() -> Path:
    """Returns the desktop directory path, respecting XDG user dirs on Linux."""
    if sys.platform.startswith("linux"):
        try:
            res = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and res.stdout.strip():
                p = Path(res.stdout.strip())
                if p.exists():
                    return p
        except Exception:
            pass
    return Path.home() / "Desktop"


def create_desktop_shortcut(target_folder: Path | str, shortcut_name: str = "DropFile", force: bool = False) -> bool:
    """Creates a shortcut or symlink on the user's Desktop pointing to target_folder."""
    target = Path(target_folder).resolve()
    desktop = get_desktop_dir()

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
        if not force and shortcut_path.exists():
            return True
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
        # Linux symlink on Desktop + application menu entry
        if desktop.exists():
            link_path = desktop / shortcut_name
            if not link_path.exists() and not link_path.is_symlink():
                try:
                    os.symlink(target, link_path)
                    print(f"[platform_utils] Created Linux Desktop symlink: {link_path} -> {target}")
                except Exception as e:
                    print(f"[platform_utils] Note on Desktop symlink: {e}")
        create_linux_app_menu_entry()
        return True


def remove_desktop_shortcut(shortcut_name: str = "DropFile") -> bool:
    """Removes the Desktop shortcut or symlink if it exists."""
    desktop = get_desktop_dir()
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

    elif sys.platform.startswith("linux"):
        autostart_dir = Path.home() / ".config" / "autostart"
        desktop_file = autostart_dir / "dropfile.desktop"
        if enable:
            autostart_dir.mkdir(parents=True, exist_ok=True)
            if getattr(sys, "frozen", False):
                exec_cmd = f'"{Path(sys.executable).resolve()}"'
            else:
                target = Path(script_path or (Path(__file__).resolve().parent / "DropFile.pyw")).resolve()
                exec_cmd = f'"{sys.executable}" "{target}"'
            icon_path = Path(__file__).resolve().parent / "icon.ico"
            content = f"""[Desktop Entry]
Type=Application
Name=DropFile
Comment=DropFile Cloud Synchronization
Exec={exec_cmd}
Icon={icon_path}
Terminal=false
Categories=Utility;FileTools;
StartupNotify=false
X-GNOME-Autostart-enabled=true
"""
            try:
                desktop_file.write_text(content, encoding="utf-8")
                print(f"[platform_utils] Linux autostart enabled: {desktop_file}")
                return True
            except Exception as e:
                print(f"[platform_utils] Error setting Linux autostart: {e}")
                return False
        else:
            if desktop_file.exists():
                try:
                    desktop_file.unlink()
                    print(f"[platform_utils] Linux autostart disabled: {desktop_file}")
                except Exception as e:
                    print(f"[platform_utils] Error removing Linux autostart: {e}")
            return True
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
    elif sys.platform.startswith("linux"):
        desktop_file = Path.home() / ".config" / "autostart" / "dropfile.desktop"
        return desktop_file.exists()
    return False


def open_folder_in_file_manager(folder_path: Path | str) -> None:
    """Opens a folder in Finder on macOS, File Explorer on Windows, or default manager on Linux."""
    folder_str = str(folder_path).strip()
    is_network = folder_str.startswith(("\\\\", "//", "smb://"))

    if is_network:
        # Network path handling (UNC / SMB)
        clean = folder_str.replace("\\", "/").strip().lstrip("/")
        if clean.lower().startswith("smb:/"):
            clean = clean.split("smb:/")[-1].lstrip("/")
        parts = [p.strip() for p in clean.split("/") if p.strip()]
        host = parts[0] if parts else ""
        share_name = parts[1] if len(parts) > 1 else ""

        if sys.platform.startswith("win"):
            unc = f"\\\\{host}\\{share_name}" if share_name else f"\\\\{host}"
            try:
                os.startfile(unc)
            except Exception:
                subprocess.run(["explorer.exe", unc])
        elif sys.platform == "darwin":
            vol_path = Path(f"/Volumes/{share_name}") if share_name else None
            if vol_path and vol_path.is_dir():
                subprocess.run(["open", str(vol_path)])
            else:
                smb_url = f"smb://{host}/{share_name}" if share_name else f"smb://{host}"
                subprocess.run(["open", smb_url])
        else:
            smb_url = f"smb://{clean}"
            # Clean up accidental literal backslash directories if created earlier
            try:
                for base in [Path.home() / "Desktop" / "DropFile", Path.home() / "DropFile", Path.cwd()]:
                    if base.is_dir():
                        for child in base.iterdir():
                            if child.name.startswith("\\") and child.is_dir() and not any(child.iterdir()):
                                child.rmdir()
            except Exception:
                pass
            # Try installed GUI file managers directly to handle GVFS / KIO smb URLs reliably
            opened = False
            for fm in ["thunar", "nautilus", "caja", "nemo", "dolphin", "pcmanfm"]:
                fm_bin = shutil.which(fm)
                if fm_bin:
                    try:
                        subprocess.Popen([fm_bin, smb_url])
                        opened = True
                        break
                    except Exception:
                        pass
            if not opened:
                try:
                    subprocess.Popen(["gio", "open", smb_url])
                except Exception:
                    subprocess.Popen(["xdg-open", smb_url])
        return

    # Regular local path handling
    p = Path(folder_path).expanduser().resolve()
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    if sys.platform == "darwin":
        subprocess.run(["open", str(p)])
    elif sys.platform.startswith("win"):
        os.startfile(str(p))
    else:
        # Launch non-blocking on Linux
        opened = False
        for fm in ["thunar", "nautilus", "caja", "nemo", "dolphin", "pcmanfm"]:
            fm_bin = shutil.which(fm)
            if fm_bin:
                try:
                    subprocess.Popen([fm_bin, str(p)])
                    opened = True
                    break
                except Exception:
                    pass
        if not opened:
            subprocess.Popen(["xdg-open", str(p)])


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

    # Windows: PowerShell
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

    # Linux: Wayland wl-copy, X11 xclip, X11 xsel
    if sys.platform.startswith("linux"):
        if os.environ.get("WAYLAND_DISPLAY"):
            try:
                p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
                p.communicate(text.encode("utf-8"))
                if p.returncode == 0:
                    return True
            except Exception:
                pass
        try:
            p = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
            p.communicate(text.encode("utf-8"))
            if p.returncode == 0:
                return True
        except Exception:
            pass
        try:
            p = subprocess.Popen(["xsel", "-b", "-i"], stdin=subprocess.PIPE)
            p.communicate(text.encode("utf-8"))
            if p.returncode == 0:
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


def spawn_settings_process(
    script_path: Optional[Path | str] = None,
    tab: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
) -> Optional[subprocess.Popen]:
    """Spawns the Settings dialog in an independent process running on the main thread."""
    try:
        kwargs = {}
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

        if getattr(sys, "frozen", False):
            current_exe = Path(sys.executable).resolve()
            cmd = [str(current_exe), "--settings"]
        else:
            if script_path is None:
                script_path = Path(__file__).resolve().parent / "DropFile.pyw"
            target = Path(script_path).resolve()
            if sys.platform.startswith("linux"):
                venv_py = target.parent / ".venv" / "bin" / "python3"
                py_runner = str(venv_py) if venv_py.exists() else sys.executable
            else:
                py_runner = sys.executable
            cmd = [py_runner, str(target), "--settings"]
            kwargs["cwd"] = str(target.parent)

        if tab:
            cmd.extend(["--tab", str(tab)])
        if extra_args:
            cmd.extend(extra_args)

        return subprocess.Popen(cmd, **kwargs)
    except Exception as e:
        print(f"[platform_utils] Error spawning settings process: {e}")
        return None


def spawn_build_sync_process(
    script_path: Optional[Path | str] = None,
) -> Optional[subprocess.Popen]:
    """Spawns the Build Sync dialog in an independent process running on the main thread."""
    try:
        kwargs = {}
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

        if getattr(sys, "frozen", False):
            current_exe = Path(sys.executable).resolve()
            cmd = [str(current_exe), "--build-sync"]
        else:
            if script_path is None:
                script_path = Path(__file__).resolve().parent / "DropFile.pyw"
            target = Path(script_path).resolve()
            if sys.platform.startswith("linux"):
                venv_py = target.parent / ".venv" / "bin" / "python3"
                py_runner = str(venv_py) if venv_py.exists() else sys.executable
            else:
                py_runner = sys.executable
            cmd = [py_runner, str(target), "--build-sync"]
            kwargs["cwd"] = str(target.parent)

        return subprocess.Popen(cmd, **kwargs)
    except Exception as e:
        print(f"[platform_utils] Error spawning build sync process: {e}")
        return None



def send_instance_command(cmd: bytes, port: int = 49195, timeout: float = 1.5) -> bool:
    """Sends a binary command (e.g. b'QUIT\\n', b'SHOW_SETTINGS\\n') to the running DropFile instance via IPC."""
    import socket
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(("127.0.0.1", port))
        payload = cmd if cmd.endswith(b"\n") else cmd + b"\n"
        s.sendall(payload)
        s.close()
        return True
    except Exception:
        if s:
            try:
                s.close()
            except Exception:
                pass
        return False


def _force_kill_other_dropfile_processes(port: int = 49195) -> None:
    """Terminates other running DropFile processes (excluding current process)."""
    current_pid = os.getpid()
    if sys.platform == "darwin":
        import signal
        try:
            # 1. Kill any process holding port
            res = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip():
                for p_str in res.stdout.strip().splitlines():
                    try:
                        p = int(p_str.strip())
                        if p != current_pid:
                            os.kill(p, signal.SIGKILL)
                    except Exception:
                        pass

            # 2. Kill other DropFile.pyw processes
            res2 = subprocess.run(["pgrep", "-f", "DropFile.pyw"], capture_output=True, text=True)
            if res2.returncode == 0 and res2.stdout.strip():
                for p_str in res2.stdout.strip().splitlines():
                    try:
                        p = int(p_str.strip())
                        if p != current_pid:
                            os.kill(p, signal.SIGKILL)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[platform_utils] macOS process cleanup error: {e}")

    elif sys.platform.startswith("win"):
        try:
            if getattr(sys, "frozen", False):
                parent_pid = os.getppid() if hasattr(os, "getppid") else 0
                cmd = ["taskkill", "/f", "/fi", f"PID ne {current_pid}"]
                if parent_pid and parent_pid > 0:
                    cmd.extend(["/fi", f"PID ne {parent_pid}"])
                cmd.extend(["/im", "DropFile.exe"])
                subprocess.run(
                    cmd,
                    capture_output=True,
                    creationflags=0x08000000,
                )
        except Exception:
            pass

    elif sys.platform.startswith("linux"):
        import signal
        try:
            res = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip():
                for p_str in res.stdout.strip().splitlines():
                    try:
                        p = int(p_str.strip())
                        if p != current_pid:
                            os.kill(p, signal.SIGKILL)
                    except Exception:
                        pass
            res2 = subprocess.run(["pgrep", "-f", "DropFile.pyw"], capture_output=True, text=True)
            if res2.returncode == 0 and res2.stdout.strip():
                for p_str in res2.stdout.strip().splitlines():
                    try:
                        p = int(p_str.strip())
                        if p != current_pid:
                            os.kill(p, signal.SIGKILL)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[platform_utils] Linux process cleanup error: {e}")


def stop_running_instance(port: int = 49195, timeout: float = 3.0) -> bool:
    """
    Stops any running DropFile instance gracefully via IPC.
    Falls back to OS process termination if it does not exit within timeout.
    """
    import socket
    import time

    # 1. Try graceful IPC QUIT
    send_instance_command(b"QUIT\n", port=port, timeout=1.0)

    # 2. Wait for socket to become free
    start_t = time.time()
    while time.time() - start_t < timeout:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            s.connect(("127.0.0.1", port))
            s.close()
            time.sleep(0.15)
        except Exception:
            # Port is free! Allow brief settling time for OS mutex/flock handles
            time.sleep(0.3)
            return True

    # 3. Force kill if still holding the port or running
    _force_kill_other_dropfile_processes(port=port)
    time.sleep(0.4)
    return True


def restart_dropfile(script_path: Optional[Path | str] = None, kill_existing: bool = True) -> bool:
    """
    Spawns a new independent instance of DropFile.
    If kill_existing is True, ensures any running background instance is terminated first.
    """
    if kill_existing:
        stop_running_instance()
        time.sleep(0.3)

    if sys.platform == "darwin":
        try:
            if getattr(sys, "frozen", False):
                app_bundle = None
                for parent in Path(sys.executable).parents:
                    if parent.suffix == ".app":
                        app_bundle = parent
                        break
                if app_bundle:
                    subprocess.Popen(["open", "-n", str(app_bundle)], close_fds=True)
                else:
                    subprocess.Popen([sys.executable], close_fds=True)
            else:
                target = Path(script_path or (Path(__file__).resolve().parent / "DropFile.pyw")).resolve()
                subprocess.Popen([sys.executable, str(target)], cwd=str(target.parent), close_fds=True)
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

    elif sys.platform.startswith("linux"):
        try:
            env = os.environ.copy()
            if getattr(sys, "frozen", False):
                current_exe = Path(sys.executable).resolve()
                subprocess.Popen(
                    [str(current_exe)],
                    cwd=str(current_exe.parent),
                    env=env,
                    close_fds=True,
                    start_new_session=True,
                )
            else:
                target = Path(script_path or (Path(__file__).resolve().parent / "DropFile.pyw")).resolve()
                venv_py = target.parent / ".venv" / "bin" / "python3"
                py_runner = str(venv_py) if venv_py.exists() else sys.executable
                subprocess.Popen(
                    [py_runner, str(target)],
                    cwd=str(target.parent),
                    env=env,
                    close_fds=True,
                    start_new_session=True,
                )
            return True
        except Exception as e:
            print(f"[platform_utils] Linux restart error: {e}")
            return False

    return False



def create_linux_app_menu_entry(script_path: Optional[Path | str] = None) -> bool:
    """Creates a .desktop file in ~/.local/share/applications for system app menu integration."""
    if not sys.platform.startswith("linux"):
        return False
    apps_dir = Path.home() / ".local" / "share" / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    target_file = apps_dir / "dropfile.desktop"
    if getattr(sys, "frozen", False):
        exec_cmd = f'"{Path(sys.executable).resolve()}"'
    else:
        target = Path(script_path or (Path(__file__).resolve().parent / "DropFile.pyw")).resolve()
        venv_py = target.parent / ".venv" / "bin" / "python3"
        py_runner = str(venv_py) if venv_py.exists() else sys.executable
        exec_cmd = f'"{py_runner}" "{target}"'
    icon_path = Path(__file__).resolve().parent / "icon.ico"
    content = f"""[Desktop Entry]
Type=Application
Name=DropFile
GenericName=File Synchronization Client
Comment=Lightweight Dropbox-style sync client for FileBrowser
Exec={exec_cmd}
Icon={icon_path}
Terminal=false
Categories=Utility;FileTools;Network;
StartupNotify=false
"""
    try:
        target_file.write_text(content, encoding="utf-8")
        target_file.chmod(0o755)
        return True
    except Exception as e:
        print(f"[platform_utils] Error creating app menu entry: {e}")
        return False


def install_systemd_user_service(script_path: Optional[Path | str] = None) -> bool:
    """Generates and enables a systemd user service for running DropFile in background daemon mode."""
    if not sys.platform.startswith("linux"):
        return False
    service_dir = Path.home() / ".config" / "systemd" / "user"
    service_dir.mkdir(parents=True, exist_ok=True)
    service_file = service_dir / "dropfile.service"
    if getattr(sys, "frozen", False):
        exec_cmd = f"{Path(sys.executable).resolve()} --headless"
    else:
        target = Path(script_path or (Path(__file__).resolve().parent / "DropFile.pyw")).resolve()
        exec_cmd = f"{sys.executable} {target} --headless"

    content = f"""[Unit]
Description=DropFile FileBrowser Synchronization Daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={exec_cmd}
Restart=always
RestartSec=10
WorkingDirectory={Path.home()}

[Install]
WantedBy=default.target
"""
    try:
        service_file.write_text(content, encoding="utf-8")
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        subprocess.run(["systemctl", "--user", "enable", "dropfile.service"], capture_output=True)
        print(f"[platform_utils] Systemd user service installed: {service_file}")
        return True
    except Exception as e:
        print(f"[platform_utils] Error installing systemd service: {e}")
        return False


def uninstall_systemd_user_service() -> bool:
    """Disables and removes the systemd user service."""
    if not sys.platform.startswith("linux"):
        return False
    service_file = Path.home() / ".config" / "systemd" / "user" / "dropfile.service"
    try:
        subprocess.run(["systemctl", "--user", "stop", "dropfile.service"], capture_output=True)
        subprocess.run(["systemctl", "--user", "disable", "dropfile.service"], capture_output=True)
        if service_file.exists():
            service_file.unlink()
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        print("[platform_utils] Systemd user service uninstalled.")
        return True
    except Exception as e:
        print(f"[platform_utils] Error uninstalling systemd service: {e}")
        return False


# Aliases for backward compatibility with win_utils naming
set_windows_autostart = set_autostart
is_windows_autostart_enabled = is_autostart_enabled
open_folder_in_explorer = open_folder_in_file_manager

_SINGLE_INSTANCE_HANDLE = None


def acquire_single_instance_lock() -> bool:
    """
    Acquires an OS-level exclusive single-instance lock.
    Returns True if this is the only instance running, False if another instance already holds the lock.
    - Windows: Uses Win32 Named Mutex 'Local\\DropFile_SingleInstance_Mutex'.
    - macOS / Linux: Uses fcntl.flock on lockfile in app data directory.
    """
    global _SINGLE_INSTANCE_HANDLE
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            CreateMutexW = kernel32.CreateMutexW
            CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
            CreateMutexW.restype = wintypes.HANDLE

            mutex_name = "Local\\DropFile_SingleInstance_Mutex"
            handle = CreateMutexW(None, True, mutex_name)
            last_err = ctypes.get_last_error()
            # ERROR_ALREADY_EXISTS = 183
            if not handle or last_err == 183:
                if handle:
                    kernel32.CloseHandle(handle)
                return False
            _SINGLE_INSTANCE_HANDLE = handle
            return True
        except Exception as e:
            print(f"[platform_utils] Win32 mutex error: {e}")
            return True
    elif sys.platform == "darwin" or sys.platform.startswith("linux"):
        try:
            import fcntl
            if sys.platform == "darwin":
                lock_dir = Path.home() / "Library" / "Application Support" / "DropFile"
            else:
                lock_dir = Path.home() / ".dropfile"
            lock_dir.mkdir(parents=True, exist_ok=True)
            lock_file = lock_dir / "dropfile.instance.lock"
            f = open(lock_file, "a+")
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                f.seek(0)
                f.truncate()
                f.write(f"{os.getpid()}\n")
                f.flush()
            except Exception:
                pass
            _SINGLE_INSTANCE_HANDLE = f
            return True
        except (IOError, BlockingIOError, PermissionError):
            return False
        except Exception as e:
            print(f"[platform_utils] Unix flock lock error: {e}")
            return False
    return True


def release_single_instance_lock() -> None:
    """Releases the single instance lock handle immediately."""
    global _SINGLE_INSTANCE_HANDLE
    if _SINGLE_INSTANCE_HANDLE is None:
        return
    if sys.platform.startswith("win"):
        try:
            import ctypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle(_SINGLE_INSTANCE_HANDLE)
        except Exception:
            pass
        _SINGLE_INSTANCE_HANDLE = None
    else:
        try:
            import fcntl
            fcntl.flock(_SINGLE_INSTANCE_HANDLE.fileno(), fcntl.LOCK_UN)
            _SINGLE_INSTANCE_HANDLE.close()
        except Exception:
            pass
        _SINGLE_INSTANCE_HANDLE = None


def kill_process_by_name(proc_name: str) -> Tuple[bool, str]:
    """
    Terminates running process(es) matching proc_name across Windows, macOS, and Linux.
    Returns (success: bool, message: str).
    """
    clean_name = proc_name.strip()
    if not clean_name:
        return False, "Process name cannot be empty"

    if sys.platform.startswith("win"):
        # On Windows, ensure .exe if needed or try both
        names_to_try = [clean_name]
        if not clean_name.lower().endswith(".exe"):
            names_to_try.append(clean_name + ".exe")

        killed_any = False
        last_msg = ""
        for name in names_to_try:
            try:
                flags = 0x08000000  # CREATE_NO_WINDOW
                res = subprocess.run(
                    ["taskkill", "/F", "/T", "/IM", name],
                    capture_output=True,
                    text=True,
                    creationflags=flags,
                    timeout=10,
                )
                if res.returncode == 0:
                    killed_any = True
                    last_msg = res.stdout.strip()
                elif "not found" not in res.stderr.lower() and "не найден" not in res.stderr.lower():
                    last_msg = res.stderr.strip() or res.stdout.strip()
            except Exception as e:
                last_msg = str(e)

        if killed_any:
            return True, f"Process '{clean_name}' terminated successfully."
        return False, last_msg or f"Process '{clean_name}' not found."
    else:
        # macOS and Linux
        try:
            res = subprocess.run(
                ["pkill", "-9", "-f", clean_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if res.returncode == 0:
                return True, f"Process '{clean_name}' terminated successfully."
            return False, f"Process '{clean_name}' not found or could not be terminated."
        except Exception as e:
            return False, f"Error killing process: {e}"


def reboot_system(delay_seconds: int = 5) -> Tuple[bool, str]:
    """
    Initiates system reboot across Windows, macOS, and Linux.
    Returns (success: bool, message: str).
    """
    delay = max(1, delay_seconds)
    if sys.platform.startswith("win"):
        try:
            flags = 0x08000000  # CREATE_NO_WINDOW
            subprocess.run(
                ["shutdown", "/r", "/t", str(delay), "/f", "/c", "DropFile Remote Reboot"],
                capture_output=True,
                creationflags=flags,
                timeout=10,
            )
            return True, f"System reboot scheduled in {delay} seconds."
        except Exception as e:
            return False, f"Failed to initiate reboot: {e}"
    elif sys.platform == "darwin":
        try:
            # Try AppleScript System Events first
            script = 'tell app "System Events" to restart'
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
            return True, "macOS restart requested via System Events."
        except Exception:
            try:
                subprocess.run(["shutdown", "-r", "now"], capture_output=True, timeout=10)
                return True, "macOS reboot initiated."
            except Exception as e:
                return False, f"Failed to initiate reboot on macOS: {e}"
    else:
        # Linux
        try:
            subprocess.run(["systemctl", "reboot"], capture_output=True, timeout=10)
            return True, "System reboot initiated via systemctl."
        except Exception:
            try:
                subprocess.run(["shutdown", "-r", "now"], capture_output=True, timeout=10)
                return True, "System reboot initiated via shutdown."
            except Exception as e:
                return False, f"Failed to initiate reboot on Linux: {e}"


def list_system_processes() -> List[Dict[str, Any]]:
    """
    Returns a list of running processes with pid, name, and memory usage.
    Zero external dependencies.
    """
    procs: List[Dict[str, Any]] = []
    if sys.platform.startswith("win"):
        try:
            import csv
            import io
            flags = 0x08000000  # CREATE_NO_WINDOW
            res = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                errors="replace",
                creationflags=flags,
                timeout=10,
            )
            if res.returncode == 0:
                reader = csv.reader(io.StringIO(res.stdout))
                for row in reader:
                    if len(row) >= 5:
                        p_name = row[0].strip()
                        p_pid = row[1].strip()
                        p_mem = row[4].replace("\xa0", " ").replace("\u202f", " ").strip()
                        if p_name:
                            procs.append({
                                "pid": p_pid,
                                "name": p_name,
                                "memory": p_mem,
                            })
        except Exception as e:
            print(f"[platform_utils] list_system_processes Windows error: {e}")
    else:
        # Unix (Linux / macOS)
        try:
            res = subprocess.run(
                ["ps", "-eo", "pid,rss,comm"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if res.returncode == 0:
                lines = res.stdout.strip().splitlines()
                for line in lines:
                    parts = line.strip().split(None, 2)
                    if len(parts) >= 3 and parts[0].isdigit():
                        pid = parts[0]
                        rss_kb = int(parts[1]) if parts[1].isdigit() else 0
                        mem_str = f"{rss_kb // 1024} MB" if rss_kb >= 1024 else f"{rss_kb} KB"
                        comm = parts[2]
                        procs.append({
                            "pid": pid,
                            "name": os.path.basename(comm),
                            "memory": mem_str,
                        })
        except Exception as e:
            print(f"[platform_utils] list_system_processes Unix error: {e}")

    # Sort alphabetically by name
    procs.sort(key=lambda x: x.get("name", "").lower())
    return procs


def launch_app_detached(executable_path: str, args: str = "") -> Tuple[bool, str]:
    """
    Launches an executable or application in a detached, independent background process.
    Returns (success: bool, message: str).
    """
    import shlex
    import shutil

    clean_path = str(executable_path or "").strip()
    if not clean_path:
        return False, "Executable path is empty."

    cmd_args = []
    if args and str(args).strip():
        try:
            cmd_args = shlex.split(str(args).strip())
        except Exception:
            cmd_args = str(args).strip().split()

    if sys.platform.startswith("win"):
        try:
            p = Path(clean_path)
            if not p.is_file() and not p.suffix and not Path(clean_path + ".exe").is_file():
                which_path = shutil.which(clean_path) or shutil.which(clean_path + ".exe")
                if not which_path:
                    return False, f"Executable not found: '{clean_path}'"
                clean_path = which_path

            cmd = [clean_path] + cmd_args
            # DETACHED_PROCESS = 0x00000008, CREATE_NEW_PROCESS_GROUP = 0x00000200
            flags = 0x00000008 | 0x00000200
            working_dir = str(Path(clean_path).parent) if Path(clean_path).is_file() else None
            subprocess.Popen(
                cmd,
                cwd=working_dir,
                creationflags=flags,
                close_fds=True,
            )
            return True, f"Application '{Path(clean_path).name}' launched successfully."
        except Exception as e:
            return False, f"Failed to launch '{clean_path}': {e}"
    elif sys.platform == "darwin":
        try:
            if clean_path.endswith(".app") or Path(clean_path).is_dir():
                cmd = ["open", "-a", clean_path]
                if cmd_args:
                    cmd.extend(["--args"] + cmd_args)
            else:
                cmd = [clean_path] + cmd_args

            subprocess.Popen(
                cmd,
                start_new_session=True,
                close_fds=True,
            )
            return True, f"Application '{Path(clean_path).name}' launched successfully."
        except Exception as e:
            return False, f"Failed to launch '{clean_path}': {e}"
    else:
        # Linux
        try:
            which_path = shutil.which(clean_path)
            actual_path = which_path or clean_path
            if not Path(actual_path).is_file() and not which_path:
                return False, f"Executable not found: '{clean_path}'"

            env = dict(os.environ)
            if "DISPLAY" not in env and "WAYLAND_DISPLAY" not in env:
                env["DISPLAY"] = ":0"

            cmd = [actual_path] + cmd_args
            working_dir = str(Path(actual_path).parent) if Path(actual_path).is_file() else None
            subprocess.Popen(
                cmd,
                cwd=working_dir,
                env=env,
                start_new_session=True,
                close_fds=True,
            )
            return True, f"Application '{Path(clean_path).name}' launched successfully."
        except Exception as e:
            return False, f"Failed to launch '{clean_path}': {e}"


def get_available_drive_letters() -> List[str]:
    """Returns a list of available (unmounted) drive letters in descending order (Z down to D)."""
    if not sys.platform.startswith("win"):
        return []
    occupied = set()
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if os.path.exists(f"{letter}:\\"):
            occupied.add(letter)
    # Prefer high drive letters: Z, Y, X, W, V...
    return [c for c in "ZYXWVUTSRQPONMLKJHGFED" if c not in occupied]


def map_network_drive(unc_path: str, drive_letter: Optional[str] = None) -> Tuple[bool, str]:
    """
    Mounts a remote UNC path (e.g. \\\\192.168.1.4\\DropSync) to a Windows drive letter.
    Returns (success, message).
    """
    clean_path = str(unc_path or "").replace("\\", "/").strip().lstrip("/")
    if clean_path.startswith("smb:/"):
        clean_path = clean_path.split("smb:/")[-1].lstrip("/")
    parts = [p.strip() for p in clean_path.split("/") if p.strip()]
    host = parts[0] if parts else ""
    share_name = parts[1] if len(parts) > 1 else "Exchange"

    if sys.platform == "darwin":
        vol_path = Path(f"/Volumes/{share_name}")
        if vol_path.is_dir():
            return True, f"Том /Volumes/{share_name} уже смонтирован."
        smb_url = f"smb://{host}/{share_name}"
        try:
            cmd = ["osascript", "-e", f'tell application "Finder" to mount volume "{smb_url}"']
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0 or vol_path.is_dir():
                return True, f"Диск {share_name} успешно подключен к /Volumes/{share_name}."
            err = res.stderr.strip() or res.stdout.strip()
            return False, f"Ошибка монтирования: {err}"
        except Exception as e:
            return False, f"Ошибка монтирования: {e}"

    if not sys.platform.startswith("win"):
        return False, "Network drive mapping is only supported on Windows and macOS."

    norm_path = f"\\\\{host}\\{share_name}"
    available = get_available_drive_letters()
    target_letter = (drive_letter or "").upper().rstrip(":")
    if not target_letter:
        if not available:
            return False, "No free drive letters available."
        target_letter = available[0]

    drive_str = f"{target_letter}:"

    # If drive already points to this UNC path, report status
    if os.path.exists(f"{drive_str}\\"):
        return True, f"Drive {drive_str} is already mounted to {norm_path}."

    try:
        res = subprocess.run(
            ["net", "use", drive_str, norm_path, "/persistent:yes"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode == 0:
            return True, f"Drive {drive_str} successfully mounted to {norm_path}."
        err_msg = res.stderr.strip() or res.stdout.strip()
        return False, f"net use failed: {err_msg}"
    except Exception as e:
        return False, f"Failed to map drive: {e}"


def create_network_shortcut(unc_path: str, shortcut_name: str = "DropSync Network") -> Tuple[bool, str]:
    """Creates a Desktop shortcut (.lnk) pointing directly to a UNC network path. Returns (success, message)."""
    norm_path = unc_path.replace("/", "\\")
    desktop = get_desktop_dir()

    if sys.platform.startswith("win"):
        lnk_name = f"{shortcut_name}.lnk" if not shortcut_name.endswith(".lnk") else shortcut_name
        shortcut_path = desktop / lnk_name
        ps_script = f"""
        $WshShell = New-Object -ComObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut('{str(shortcut_path)}')
        $Shortcut.TargetPath = '{norm_path}'
        $Shortcut.IconLocation = 'shell32.dll,9'
        $Shortcut.Description = 'DropSync LAN Network Share'
        $Shortcut.Save()
        """
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                check=True,
                capture_output=True,
                timeout=5,
            )
            return True, f"Shortcut '{lnk_name}' created on Desktop."
        except Exception as e:
            print(f"[platform_utils] create_network_shortcut error: {e}")
            return False, f"Failed to create shortcut: {e}"
    elif sys.platform == "darwin":
        clean_path = str(unc_path or "").replace("\\", "/").strip().lstrip("/")
        if clean_path.startswith("smb:/"):
            clean_path = clean_path.split("smb:/")[-1].lstrip("/")
        parts = [p.strip() for p in clean_path.split("/") if p.strip()]
        host = parts[0] if parts else ""
        share_name = parts[1] if len(parts) > 1 else "Exchange"
        smb_uri = f"smb://{host}/{share_name}"

        # Native Apple Internet Location (.inetloc) - mounts and opens in Finder on double-click
        inetloc_path = desktop / f"{shortcut_name}.inetloc"
        plist_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n'
            '<dict>\n'
            f'    <key>URL</key>\n    <string>{smb_uri}</string>\n'
            '</dict>\n'
            '</plist>\n'
        )
        try:
            inetloc_path.write_text(plist_content, encoding="utf-8")
            return True, f"Ярлык '{shortcut_name}' создан на Рабочем столе."
        except Exception as e:
            link_path = desktop / f"{shortcut_name}.command"
            try:
                with open(link_path, "w", encoding="utf-8") as f:
                    f.write(f"#!/bin/bash\nopen '{smb_uri}'\n")
                os.chmod(link_path, 0o755)
                return True, f"Ярлык создан: {link_path}"
            except Exception as ex:
                return False, str(ex)
    else:
        desktop_file = desktop / f"{shortcut_name}.desktop"
        try:
            smb_uri = "smb://" + unc_path.replace("\\", "/").lstrip("/")
            # For Linux desktop environments (XFCE / GNOME / KDE / Cinnamon / MATE),
            # Type=Application with Exec is required for a desktop shortcut to be executable
            # without triggering "Broken .desktop file" (Нерабочий .desktop файл) errors.
            exec_cmd = (
                f'sh -c "if command -v thunar >/dev/null 2>&1; then exec thunar \'{smb_uri}\'; '
                f'elif command -v nautilus >/dev/null 2>&1; then exec nautilus \'{smb_uri}\'; '
                f'elif command -v caja >/dev/null 2>&1; then exec caja \'{smb_uri}\'; '
                f'elif command -v nemo >/dev/null 2>&1; then exec nemo \'{smb_uri}\'; '
                f'elif command -v dolphin >/dev/null 2>&1; then exec dolphin \'{smb_uri}\'; '
                f'elif command -v pcmanfm >/dev/null 2>&1; then exec pcmanfm \'{smb_uri}\'; '
                f'else gio open \'{smb_uri}\' || xdg-open \'{smb_uri}\'; fi"'
            )
            content = f"""[Desktop Entry]
Version=1.0
Type=Application
Name={shortcut_name}
Comment=DropFile LAN Network Share
Exec={exec_cmd}
Icon=folder-remote
Terminal=false
Categories=Network;FileTransfer;
StartupNotify=true
"""
            desktop_file.write_text(content, encoding="utf-8")
            os.chmod(desktop_file, 0o755)

            # Mark desktop entry as trusted for XFCE (Thunar 4.18+) and GNOME (Nautilus)
            try:
                sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
                subprocess.run(
                    ["gio", "set", "-t", "string", str(desktop_file), "metadata::xfce-exe-checksum", sha256],
                    capture_output=True,
                    timeout=2,
                )
                subprocess.run(
                    ["gio", "set", "-t", "string", str(desktop_file), "metadata::trusted", "true"],
                    capture_output=True,
                    timeout=2,
                )
                subprocess.run(
                    ["gio", "set", str(desktop_file), "metadata::trusted", "true"],
                    capture_output=True,
                    timeout=2,
                )
            except Exception:
                pass
            return True, f"Desktop entry created at {desktop_file}"
        except Exception as e:
            return False, str(e)


def detect_network_environment() -> Tuple[bool, bool]:
    """
    Returns (is_work, is_home) based on local IPv4 addresses.
    - is_work: 192.168.0.x subnet
    - is_home: 192.168.1.x subnet
    """
    is_work = False
    is_home = False
    try:
        import socket
        local_ips = socket.gethostbyname_ex(socket.gethostname())[2]
        for ip in local_ips:
            if ip.startswith("192.168.0."):
                is_work = True
            elif ip.startswith("192.168.1."):
                is_home = True
    except Exception:
        pass
    return is_work, is_home


def normalize_lan_host(raw_input: str) -> str:
    """
    Cleans raw host input (e.g. '192.168.0.22/Exchange', 'smb://192.168.0.22/Exchange',
    '\\\\192.168.0.22\\Exchange') into a clean hostname/IP (e.g. '192.168.0.22').
    """
    s = str(raw_input or "").strip()
    if not s:
        return ""
    if s.lower().startswith("smb://"):
        s = s[6:]
    s = s.replace("\\", "/").strip().lstrip("/")
    parts = [p.strip() for p in s.split("/") if p.strip()]
    if not parts:
        return ""
    return parts[0]


def format_lan_share_path(raw_host: str, share_name: str = "Exchange") -> str:
    """
    Formats the network share path for the current OS.
    - macOS: smb://<host>/<share_name>
    - Windows: \\\\<host>\\<share_name>
    - Linux: smb://<host>/<share_name>
    Guarantees no duplicated share names and proper slash direction.
    """
    clean_host = normalize_lan_host(raw_host)
    if not clean_host:
        clean_host = get_default_lan_server_host()

    # Determine if share_name is already in raw_host
    s = str(raw_host or "").replace("\\", "/").strip()
    parts = [p.strip() for p in s.split("/") if p.strip()]
    target_share = share_name
    if len(parts) > 1 and parts[1].lower() == share_name.lower():
        target_share = parts[1]

    if sys.platform == "darwin":
        return f"smb://{clean_host}/{target_share}"
    elif sys.platform.startswith("win"):
        return f"\\\\{clean_host}\\{target_share}"
    else:
        return f"smb://{clean_host}/{target_share}"


def get_default_lan_server_host(saved_host: str = "") -> str:
    """
    Returns default local SMB server host for the current network environment.
    If saved_host is provided and is a valid local name/IP (not an external DDNS/Keenetic domain),
    saved_host is preserved and cleaned.
    """
    is_work, is_home = detect_network_environment()
    default_host = "192.168.0.22" if is_work else "192.168.1.4"

    cleaned = normalize_lan_host(saved_host)
    if cleaned:
        # Ignore external keenetic/public DDNS domains for local SMB shares
        cleaned_lower = cleaned.lower()
        if not (".keenetic." in cleaned_lower or cleaned_lower.endswith(".link")):
            return cleaned

    return default_host


def detect_lan_server_host(saved_host: str = "", extra_candidates: Optional[List[str]] = None) -> str:
    """
    Auto-detects the local SMB server (\\host\\Exchange, smb://host/Exchange)
    by scanning port 445 / 139 with short timeouts.
    Never probes HTTP port 8081 (FileBrowser) to avoid falsely picking Keenetic/remote routers.
    """
    is_work, is_home = detect_network_environment()

    if is_work:
        priority = ["192.168.0.22", "192.168.1.4", "cladovka"]
    elif is_home:
        priority = ["192.168.1.4", "cladovka", "192.168.0.22"]
    else:
        priority = ["192.168.0.22", "192.168.1.4", "cladovka"]

    candidates: List[str] = []
    for h in priority:
        if h not in candidates:
            candidates.append(h)

    cleaned_saved = normalize_lan_host(saved_host)
    if cleaned_saved and cleaned_saved not in candidates:
        cleaned_lower = cleaned_saved.lower()
        if not (".keenetic." in cleaned_lower or cleaned_lower.endswith(".link")):
            candidates.insert(0, cleaned_saved)

    if extra_candidates:
        for ec in extra_candidates:
            ec_s = normalize_lan_host(ec)
            if ec_s and ec_s not in candidates and ec_s not in ("localhost", "127.0.0.1"):
                ec_l = ec_s.lower()
                if not (".keenetic." in ec_l or ec_l.endswith(".link")):
                    candidates.append(ec_s)

    import socket
    for host in candidates:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.35)
            # Only SMB ports 445 / 139 for Windows Share / Exchange
            if s.connect_ex((host, 445)) == 0 or s.connect_ex((host, 139)) == 0:
                s.close()
                return host
            s.close()
        except Exception:
            pass

    return "192.168.0.22" if is_work else "192.168.1.4"


