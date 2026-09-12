"""
System tray interface for DropFile using pystray.
Provides tray icons with real-time status indication, context menu,
notifications, and settings invocation.
"""

import threading
import webbrowser
from typing import Callable, Optional

import pystray
from pystray import MenuItem as item

from config import Config
from gui_settings import SettingsDialog
from icons import create_tray_icon
from sync_engine import SyncEngine
from win_utils import open_folder_in_explorer


class DropFileTray:
    def __init__(self, config: Config, engine: SyncEngine, settings_dialog: SettingsDialog):
        self.config = config
        self.engine = engine
        self.settings_dialog = settings_dialog

        self.current_state = "idle"
        self.current_status_text = "DropFile: Готов к работе"
        self._icon: Optional[pystray.Icon] = None
        self._lock = threading.Lock()

        # Connect engine callbacks
        self.engine.on_status_change = self.update_status
        self.engine.on_notify = self.send_notification

    def update_status(self, text: str, state: str) -> None:
        """Called by sync engine to update tray icon and menu status."""
        self.current_status_text = f"Статус: {text}"
        self.current_state = state

        if self._icon:
            try:
                self._icon.title = f"DropFile — {text}"
                self._icon.icon = create_tray_icon(state)
                self._icon.update_menu()
            except Exception as e:
                print(f"[Tray] Error updating icon: {e}")

    def send_notification(self, title: str, message: str) -> None:
        """Sends native desktop notification via tray icon."""
        if self._icon and self.config.notify_on_sync:
            try:
                self._icon.notify(message, title)
            except Exception as e:
                print(f"[Tray] Notification error: {e}")

    def _open_local_folder(self, icon, item) -> None:
        open_folder_in_explorer(self.config.local_path)

    def _sync_now(self, icon, item) -> None:
        self.engine.trigger_sync_now()

    def _toggle_pause(self, icon, item) -> None:
        if self.engine.is_paused():
            self.engine.resume()
        else:
            self.engine.pause()

    def _open_settings(self, icon, item) -> None:
        # Launch Tkinter window in a separate thread if not already open
        threading.Thread(target=self.settings_dialog.show, daemon=True).start()

    def _open_web(self, icon, item) -> None:
        url = self.config.server_url
        if not url:
            self._open_settings(icon, item)
            return
        if not url.endswith("/"):
            url += "/"
        # Navigate to files folder
        web_url = f"{url}files{self.config.remote_path}"
        webbrowser.open(web_url)

    def _exit_app(self, icon, item) -> None:
        print("[Tray] Exiting DropFile...")
        self.engine.stop()
        icon.stop()

    def _build_menu(self) -> pystray.Menu:
        pause_label = (
            "▶ Возобновить синхронизацию" if self.engine.is_paused() else "⏸ Приостановить синхронизацию"
        )
        return pystray.Menu(
            item(lambda text: self.current_status_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            item("📁 Открыть папку DropFile", self._open_local_folder, default=True),
            item("🔄 Синхронизировать сейчас", self._sync_now),
            item(lambda text: pause_label, self._toggle_pause),
            pystray.Menu.SEPARATOR,
            item("⚙ Настройки...", self._open_settings),
            item("🌐 Открыть в браузере (FileBrowser)", self._open_web),
            pystray.Menu.SEPARATOR,
            item("❌ Выход", self._exit_app),
        )

    def run(self) -> None:
        """Runs the pystray mainloop (blocking)."""
        initial_img = create_tray_icon(self.current_state)
        self._icon = pystray.Icon(
            name="DropFile",
            icon=initial_img,
            title="DropFile — Синхронизация файлов",
            menu=self._build_menu(),
        )

        # Start the sync engine
        self.engine.start()

        # Run tray loop
        self._icon.run()
