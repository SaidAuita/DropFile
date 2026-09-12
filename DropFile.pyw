"""
DropFile — Background Dropbox-like file synchronization utility.
Main entry point. Runs silently in the background with system tray integration.
"""

import os
import socket
import sys
import threading
from pathlib import Path

# Add project directory to sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import Config, get_app_dir
from fb_client import FileBrowserClient
from gui_settings import SettingsDialog
from state_db import StateDatabase
from sync_engine import SyncEngine
from tray import DropFileTray
from win_utils import create_desktop_shortcut

SINGLE_INSTANCE_PORT = 49195


def ensure_single_instance() -> socket.socket:
    """Ensures only one instance of DropFile runs at a time."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
        s.listen(1)
        return s
    except socket.error:
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

    # 7. Initialize Settings Dialog
    settings_dialog = SettingsDialog(
        config=config,
        state_db=state_db,
        client=client,
        on_save_callback=on_settings_saved,
    )

    # Prompt user with settings dialog if server URL or username is not configured
    if not config.server_url or not config.username:
        threading.Thread(target=settings_dialog.show, daemon=True).start()

    # 8. Start System Tray
    tray = DropFileTray(
        config=config,
        engine=engine,
        settings_dialog=settings_dialog,
    )

    try:
        tray.run()
    except KeyboardInterrupt:
        engine.stop()


if __name__ == "__main__":
    main()
