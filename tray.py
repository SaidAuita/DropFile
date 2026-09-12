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
from i18n import t
from icons import create_tray_icon
from sync_engine import SyncEngine
from version import __version__
from win_utils import copy_to_clipboard, open_folder_in_explorer


class DropFileTray:
    def __init__(self, config: Config, engine: SyncEngine, settings_dialog: SettingsDialog):
        self.config = config
        self.engine = engine
        self.settings_dialog = settings_dialog
        if not getattr(self.settings_dialog, "engine", None):
            self.settings_dialog.engine = engine

        self.current_state = "idle"
        self.current_status_text = f"DropFile v{__version__}: {t('status_ready')}"
        self._icon: Optional[pystray.Icon] = None
        self._lock = threading.Lock()

        # Connect engine callbacks
        self.engine.on_status_change = self.update_status
        self.engine.on_notify = self.send_notification
        self.engine.on_share_ready = self._on_share_ready

    def _on_share_ready(self, item_info: dict, notify: bool = True) -> None:
        """Called when a file has just uploaded and its share link is prepared."""
        if self._icon:
            try:
                self._icon.menu = self._build_menu()
                self._icon.update_menu()
            except Exception as e:
                print(f"[Tray] Error updating menu on share ready: {e}")
        if notify:
            name = item_info.get("name", "File")
            self.send_notification(t("notify_file_uploaded"), t("notify_share_ready", name=name))

    def update_status(self, text: str, state: str) -> None:
        """Called by sync engine to update tray icon and menu status."""
        self.current_status_text = t("tray_status_prefix", text=text)
        self.current_state = state

        if self._icon:
            try:
                self._icon.title = f"DropFile — {text}"
                self._icon.icon = create_tray_icon(state)
                self._icon.menu = self._build_menu()
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

    def _get_last_item(self) -> Optional[dict]:
        return self.engine.get_last_uploaded_item()

    def _is_share_enabled(self) -> bool:
        item = self._get_last_item()
        return bool(item and item.get("name"))

    def _get_share_label(self) -> str:
        item = self._get_last_item()
        if item and item.get("name"):
            raw_name = item["name"]
            short_name = raw_name if len(raw_name) <= 24 else raw_name[:21] + "..."
            return t("tray_copy_link", name=short_name)
        return t("tray_copy_link_empty")

    def _get_name_label(self) -> str:
        item = self._get_last_item()
        if item and item.get("name"):
            raw_name = item["name"]
            short_name = raw_name if len(raw_name) <= 24 else raw_name[:21] + "..."
            return t("tray_copy_name", name=short_name)
        return t("tray_copy_name_empty")

    def _open_local_folder(self, icon, item) -> None:
        open_folder_in_explorer(self.config.local_path)

    def _copy_share_link(self, icon, item) -> None:
        info = self._get_last_item()
        if not info or not info.get("share_url"):
            return
        url = info["share_url"]
        name = info.get("name", "file")
        if copy_to_clipboard(url):
            self.send_notification(t("notify_link_copied_title"), f"{name}\n{url}")

    def _copy_file_name(self, icon, item) -> None:
        info = self._get_last_item()
        if not info or not info.get("name"):
            return
        name = info["name"]
        if copy_to_clipboard(name):
            self.send_notification(t("notify_name_copied_title"), name)

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

    def refresh_menu(self) -> None:
        """Forces tray menu rebuild and update."""
        if self._icon:
            try:
                self._icon.menu = self._build_menu()
                self._icon.update_menu()
            except Exception as e:
                print(f"[Tray] Error refreshing menu: {e}")

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            item(lambda text: self.current_status_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            item(lambda text: t("tray_open_folder"), self._open_local_folder, default=True),
            item(
                lambda text: self._get_share_label(),
                self._copy_share_link,
                enabled=lambda item: self._is_share_enabled(),
            ),
            item(
                lambda text: self._get_name_label(),
                self._copy_file_name,
                enabled=lambda item: self._is_share_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            item(lambda text: t("tray_sync_now"), self._sync_now),
            item(
                lambda text: t("tray_resume") if self.engine.is_paused() else t("tray_pause"),
                self._toggle_pause,
            ),
            pystray.Menu.SEPARATOR,
            item(lambda text: t("tray_settings"), self._open_settings),
            item(lambda text: t("tray_open_web"), self._open_web),
            pystray.Menu.SEPARATOR,
            item(lambda text: t("tray_exit"), self._exit_app),
        )

    def run(self) -> None:
        """Runs the pystray mainloop (blocking)."""
        initial_img = create_tray_icon(self.current_state)
        self._icon = pystray.Icon(
            name="DropFile",
            icon=initial_img,
            title=f"DropFile v{__version__}",
            menu=self._build_menu(),
        )

        # Start the sync engine
        self.engine.start()

        # Run tray loop
        self._icon.run()
