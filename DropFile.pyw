"""
DropFile — Background Dropbox-like file synchronization utility.
Main entry point. Runs silently in the background with system tray integration.
"""

import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# Add project directory to sys.path and set cwd
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
try:
    os.chdir(BASE_DIR)
except Exception:
    pass

# If running as frozen PyInstaller executable, clean PyInstaller internal variables
# from os.environ so any spawned subprocesses run as fresh root instances without parent checks
if getattr(sys, "frozen", False):
    for k in list(os.environ.keys()):
        if k.startswith(("_PYI", "PYI", "_MEI")):
            os.environ.pop(k, None)
    if hasattr(sys, "_MEIPASS"):
        try:
            os.add_dll_directory(sys._MEIPASS)
        except Exception:
            pass

from platform_utils import (
    create_desktop_shortcut,
    ensure_macos_tk_compatibility,
    restart_dropfile,
    spawn_settings_process,
)

# Ensure macOS Tkinter [NSApp macOSVersion] selector compatibility
ensure_macos_tk_compatibility()

# Configure macOS Cocoa activation policy: hide Dock icon for background tray agent.
# In --settings mode, do NOT touch NSApplication here so Tkinter can initialize TKApplication naturally.
if sys.platform == "darwin" and "--settings" not in sys.argv:
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
        ns_app = NSApplication.sharedApplication()
        ns_app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    except Exception:
        pass

from config import Config, get_app_dir
from fb_client import FileBrowserClient
from gui_settings import SettingsDialog
from state_db import StateDatabase
from sync_engine import SyncEngine
from tray import DropFileTray
from version import __version__

SINGLE_INSTANCE_PORT = 49195
INSTANCE_SOCKET: Optional[socket.socket] = None


def release_instance_socket() -> None:
    """Closes the single-instance lock socket immediately to allow restart handover."""
    global INSTANCE_SOCKET
    if INSTANCE_SOCKET:
        try:
            INSTANCE_SOCKET.close()
        except Exception:
            pass
        INSTANCE_SOCKET = None


def _start_instance_command_listener(sock: socket.socket) -> None:
    """Background listener for commands (e.g. SHOW_SETTINGS) from second instances."""
    def listener():
        while sock and sock == INSTANCE_SOCKET:
            try:
                conn, _ = sock.accept()
                data = conn.recv(1024)
                conn.close()
                if b"SHOW_SETTINGS" in data:
                    spawn_settings_process()
            except Exception:
                break

    t = threading.Thread(target=listener, daemon=True)
    t.start()


def ensure_single_instance() -> socket.socket:
    """Ensures only one instance of DropFile runs at a time with notification handover."""
    global INSTANCE_SOCKET
    for attempt in range(4):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
            s.listen(2)
            INSTANCE_SOCKET = s
            _start_instance_command_listener(s)
            return s
        except socket.error:
            try:
                s.close()
            except Exception:
                pass
            if attempt < 3:
                time.sleep(0.5)
                continue

            # Another instance is actively running. Notify it to open Settings.
            try:
                notify_s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                notify_s.settimeout(2.0)
                notify_s.connect(("127.0.0.1", SINGLE_INSTANCE_PORT))
                notify_s.sendall(b"SHOW_SETTINGS\n")
                notify_s.close()
            except Exception:
                # If socket couldn't receive command, spawn settings directly
                spawn_settings_process()

            if sys.platform == "darwin":
                try:
                    import subprocess
                    subprocess.run(
                        [
                            "osascript",
                            "-e",
                            'display notification "DropFile is already running in the top menu bar." with title "DropFile"',
                        ],
                        capture_output=True,
                        timeout=5,
                    )
                except Exception:
                    pass

            print("[DropFile] Another instance of DropFile is already running. Showing settings.")
            sys.exit(0)


def main():
    # If invoked with --settings, open Settings UI directly on the main thread
    if "--settings" in sys.argv:
        config = Config()
        db_path = config.config_dir / "state.db"
        state_db = StateDatabase(db_path)
        client = FileBrowserClient(
            base_url=config.server_url,
            username=config.username,
            password=config.password,
        )
        engine = SyncEngine(config=config, state_db=state_db, client=client)
        settings_dialog = SettingsDialog(
            config=config,
            state_db=state_db,
            client=client,
            engine=engine,
        )
        settings_dialog.show()
        sys.exit(0)

    # 1. Single instance lock
    _instance_sock = ensure_single_instance()

    # 2. Load configuration
    config = Config()

    # 3. Ensure local sync folder and optional desktop shortcut exist
    local_folder = config.local_path
    local_folder.mkdir(parents=True, exist_ok=True)
    if config.desktop_shortcut:
        create_desktop_shortcut(local_folder)

    # 4. Initialize Database
    db_path = config.config_dir / "state.db"
    state_db = StateDatabase(db_path)

    # 5. Initialize API Client
    client = FileBrowserClient(
        base_url=config.server_url,
        username=config.username,
        password=config.password,
    )

    # 6. Initialize Sync Engine
    engine = SyncEngine(
        config=config,
        state_db=state_db,
        client=client,
    )

    # Callback when user updates settings in GUI
    def on_settings_saved():
        print("[DropFile] Settings updated. Re-authenticating and triggering sync...")
        client.login()
        engine.trigger_sync_now()
        try:
            tray.refresh_menu()
        except Exception:
            pass

    # Clean up sockets, engine, and tray before restart or self-update
    def on_cleanup():
        print("[DropFile] Stopping engine and releasing instance socket...")
        release_instance_socket()
        try:
            engine.stop()
        except Exception:
            pass
        try:
            if 'tray' in locals() and tray._icon:
                tray._icon.stop()
        except Exception:
            pass

    # Callback when user clicks Save and Restart
    def on_restart():
        print("[DropFile] Restart requested. Spawning new process...")
        on_cleanup()
        restart_dropfile()
        os._exit(0)

    # 7. Initialize Settings Dialog
    settings_dialog = SettingsDialog(
        config=config,
        state_db=state_db,
        client=client,
        on_save_callback=on_settings_saved,
        on_restart_callback=on_restart,
        on_cleanup_callback=on_cleanup,
        engine=engine,
    )

    # Prompt user with settings dialog if server URL or username is not configured
    if not config.server_url or not config.username:
        spawn_settings_process()

    # 8. Start System Tray
    tray = DropFileTray(
        config=config,
        engine=engine,
        settings_dialog=settings_dialog,
        on_cleanup_callback=on_cleanup,
    )

    try:
        tray.run()
    except KeyboardInterrupt:
        engine.stop()


def _handle_fatal_exception(exc: BaseException) -> None:
    """Logs fatal exceptions and alerts the user with a native modal dialog."""
    import subprocess
    import traceback
    err_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    print(f"[DropFile FATAL CRASH] {err_text}", file=sys.stderr)

    crash_log = None
    try:
        crash_log = get_app_dir() / "dropfile_crash.log"
        with open(crash_log, "a", encoding="utf-8") as f:
            f.write(f"\n=== Crash: {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            f.write(err_text)
    except Exception:
        try:
            crash_log = Path.home() / "dropfile_crash.log"
            with open(crash_log, "a", encoding="utf-8") as f:
                f.write(f"\n=== Crash: {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                f.write(err_text)
        except Exception:
            pass

    if sys.platform == "darwin":
        try:
            msg_short = str(exc).replace('"', '\\"').replace("'", "")[:200]
            log_str = str(crash_log).replace('"', '\\"') if crash_log else "~/dropfile_crash.log"
            script = f'display alert "DropFile Error" message "DropFile could not start:\n\n{msg_short}\n\nError log: {log_str}" as critical'
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
        except Exception:
            pass
    elif sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"DropFile encountered a fatal startup error:\n\n{str(exc)[:300]}\n\nLog: {crash_log}",
                "DropFile Error",
                0x10,
            )
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        pass
    except BaseException as e:
        _handle_fatal_exception(e)
        sys.exit(1)
