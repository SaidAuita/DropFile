"""
System tray interface for DropFile using pystray.
Provides tray icons with real-time status indication, context menu,
notifications, and settings invocation.
"""

import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any, Callable, Optional

import pystray
from pystray import MenuItem as item

from config import Config
try:
    from gui_settings import SettingsDialog
except Exception:
    SettingsDialog = None
from i18n import t
from icons import create_tray_icon
from platform_utils import (
    copy_to_clipboard,
    open_folder_in_file_manager as open_folder_in_explorer,
    spawn_settings_process,
)
from sync_engine import SyncEngine
from version import __version__


class DropFileTray:
    def __init__(
        self,
        config: Config,
        engine: SyncEngine,
        settings_dialog: Optional[Any] = None,
        on_cleanup_callback: Optional[Callable[[], None]] = None,
    ):
        self.config = config
        self.engine = engine
        self.settings_dialog = settings_dialog
        self.on_cleanup_callback = on_cleanup_callback
        if self.settings_dialog is not None and not getattr(self.settings_dialog, "engine", None):
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

    def _pull_missing(self, icon=None, item=None) -> None:
        def worker():
            downloaded, errors = self.engine.pull_missing_files()
            if downloaded > 0:
                self.send_notification(
                    t("pull_missing_done_title"),
                    t("pull_missing_done_msg", count=downloaded),
                )
            else:
                self.send_notification(
                    t("pull_missing_none_title"),
                    t("pull_missing_none_msg"),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _get_servers_sync_label(self) -> str:
        if not self.config.backup_server_enabled or not self.config.sync_backup_server:
            return ""
        st = self.engine.get_last_servers_sync_status()
        summary = st.get("summary", "")
        return t("tray_servers_sync_menu", status=summary)

    def _sync_servers_mirror_tray(self, icon=None, item=None) -> None:
        def worker():
            self.send_notification("DropFile", t("servers_sync_checking"))
            synced, errs = self.engine.sync_servers_mirror()
            st = self.engine.get_last_servers_sync_status()
            self.send_notification(t("servers_sync_status_title"), st.get("summary", ""))
            self.refresh_menu()

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_pause(self, icon, item) -> None:
        if self.engine.is_paused():
            self.engine.resume()
        else:
            self.engine.pause()

    def _open_settings(self, icon=None, item=None) -> None:
        try:
            if sys.platform == "darwin":
                if getattr(self, "_settings_proc", None) is not None:
                    if self._settings_proc.poll() is None:
                        return
                    self._settings_proc = None
                self._settings_proc = spawn_settings_process()
            else:
                if self.settings_dialog is not None:
                    threading.Thread(target=self.settings_dialog.show, daemon=True).start()
                else:
                    if getattr(self, "_settings_proc", None) is not None:
                        if self._settings_proc.poll() is None:
                            return
                        self._settings_proc = None
                    self._settings_proc = spawn_settings_process()
        except Exception as e:
            print(f"[Tray] Error opening settings: {e}")

    def _check_updates_from_tray(self, icon, item) -> None:
        """Checks for updates from the tray and notifies user or opens update prompt."""
        self.send_notification("DropFile", t("update_checking"))

        def worker():
            from updater import check_for_updates
            has_update, info = check_for_updates()
            if info.get("error"):
                if info.get("not_found"):
                    self.send_notification(
                        t("update_latest_title"),
                        t("update_latest_msg", version=__version__),
                    )
                else:
                    self.send_notification(
                        t("update_error_title"),
                        str(info.get("error")),
                    )
                return

            if not has_update:
                self.send_notification(
                    t("update_latest_title"),
                    t("update_latest_msg", version=__version__),
                )
                return

            # Update available: open settings dialog with update prompt
            remote_ver = info.get("version", "")
            self.send_notification(
                t("update_avail_title"),
                f"DropFile v{remote_ver} is available! Opening update dialog...",
            )
            self._open_settings()

        threading.Thread(target=worker, daemon=True).start()

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
            item(
                lambda text: self._get_servers_sync_label(),
                None,
                enabled=False,
                visible=lambda item: bool(self.config.backup_server_enabled and self.config.sync_backup_server),
            ),
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
                lambda text: f"⚡ {t('servers_sync_btn_sync')}",
                self._sync_servers_mirror_tray,
                visible=lambda item: bool(self.config.backup_server_enabled and self.config.sync_backup_server),
            ),
            item(lambda text: t("tray_pull_missing"), self._pull_missing),
            item(
                lambda text: t("tray_resume") if self.engine.is_paused() else t("tray_pause"),
                self._toggle_pause,
            ),
            pystray.Menu.SEPARATOR,
            item(lambda text: t("tray_settings"), self._open_settings),
            item(lambda text: t("tray_check_updates"), self._check_updates_from_tray),
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

        # Show initial notification that DropFile is active in the tray
        if self.config.notify_on_sync:
            def notify_ready():
                import time
                time.sleep(1.2)
                try:
                    self.send_notification("DropFile", t("tray_running_notify", version=__version__))
                except Exception:
                    pass
            threading.Thread(target=notify_ready, daemon=True).start()

        # Run tray loop
        self._icon.run()
