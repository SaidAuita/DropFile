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

# Add project directory to sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# If running as frozen PyInstaller executable, clean _MEIPASS2 from os.environ
# and register MEIPASS directory with Windows DLL search path for sqlite3 and other extensions
if getattr(sys, "frozen", False):
    os.environ.pop("_MEIPASS2", None)
    if hasattr(sys, "_MEIPASS"):
        try:
            os.add_dll_directory(sys._MEIPASS)
        except Exception:
            pass

from config import Config, get_app_dir
from fb_client import FileBrowserClient
from gui_settings import SettingsDialog
from state_db import StateDatabase
from sync_engine import SyncEngine
from tray import DropFileTray
from version import __version__
from win_utils import create_desktop_shortcut, restart_dropfile

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


def ensure_single_instance() -> socket.socket:
    """Ensures only one instance of DropFile runs at a time with retry for restart handover."""
    global INSTANCE_SOCKET
    for attempt in range(4):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
            s.listen(1)
            INSTANCE_SOCKET = s
            return s
        except socket.error:
            try:
                s.close()
            except Exception:
                pass
            if attempt < 3:
                time.sleep(0.5)
                continue
            print("[DropFile] Another instance of DropFile is already running. Exiting.")
            sys.exit(0)


def main():
    # 1. Single instance lock
    _instance_sock = ensure_single_instance()

    # 2. Load configuration
    config = Config()

    # 3. Ensure local sync folder and desktop shortcut exist
    local_folder = config.local_path
    local_folder.mkdir(parents=True, exist_ok=True)
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
        threading.Thread(target=settings_dialog.show, daemon=True).start()

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


if __name__ == "__main__":
    main()
