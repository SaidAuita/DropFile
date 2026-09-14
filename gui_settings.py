"""
Modern Tkinter Settings and Activity Log dialog for DropFile.
Features native Windows 10/11 visual styles, high-DPI scaling,
responsive scrollable tabs, connection testing, backup/restore,
autostart, multi-language support (10 languages) with live dynamic switching,
and guaranteed visible bottom action bar.
"""

import os
import sys
import threading
import time

# Ensure macOS Tkinter [NSApp macOSVersion] selector compatibility before importing tkinter
from platform_utils import ensure_macos_tk_compatibility

ensure_macos_tk_compatibility()

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Optional

from config import Config
from fb_client import FileBrowserClient
from i18n import SUPPORTED_LANGUAGES, get_current_language, set_current_language, t
from state_db import StateDatabase
from updater import apply_update, check_for_updates
from version import __version__
from win_utils import (
    create_desktop_shortcut,
    is_windows_autostart_enabled,
    open_folder_in_explorer,
    remove_desktop_shortcut,
    restart_dropfile,
    set_windows_autostart,
)

# Enable modern per-monitor DPI awareness on Windows
if sys.platform.startswith("win"):
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class ScrollableTab(ttk.Frame):
    """
    Card-styled scrollable frame for settings tabs that automatically
    shows a vertical scrollbar only when content overflows visible height.
    """
    def __init__(self, parent, bg="#FFFFFF", padding=(18, 14)):
        super().__init__(parent, style="Card.TFrame")
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0, bg=bg)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.content = ttk.Frame(self.canvas, style="Card.TFrame", padding=padding)

        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self._win_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")

        self.canvas.pack(side="left", fill="both", expand=True)

        self.content.bind("<Configure>", self._on_content_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Mouse wheel support
        self.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _on_content_configure(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._update_scrollbar()

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self._win_id, width=event.width)
        self._update_scrollbar()

    def _update_scrollbar(self):
        req_h = self.content.winfo_reqheight()
        canv_h = self.canvas.winfo_height()
        if canv_h > 40 and req_h > canv_h + 10:
            if not self.scrollbar.winfo_ismapped():
                self.scrollbar.pack(side="right", fill="y")
        else:
            if self.scrollbar.winfo_ismapped():
                self.scrollbar.pack_forget()

    def _on_mousewheel(self, event):
        if self.canvas.winfo_exists() and self.scrollbar.winfo_ismapped():
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class SettingsDialog:
    def __init__(
        self,
        config: Config,
        state_db: StateDatabase,
        client: FileBrowserClient,
        on_save_callback: Optional[Callable[[], None]] = None,
        on_restart_callback: Optional[Callable[[], None]] = None,
        on_cleanup_callback: Optional[Callable[[], None]] = None,
        engine: Optional[Any] = None,
    ):
        self.config = config
        self.state_db = state_db
        self.client = client
        self.on_save_callback = on_save_callback
        self.on_restart_callback = on_restart_callback
        self.on_cleanup_callback = on_cleanup_callback
        self.engine = engine
        self.window: Optional[tk.Tk] = None
        self._show_lock = threading.Lock()
        self._ui_thread: Optional[threading.Thread] = None
        self.lang_codes = list(SUPPORTED_LANGUAGES.keys())

    def _is_window_alive(self) -> bool:
        """Safely checks whether self.window exists without raising TclError."""
        if self.window is None:
            return False
        try:
            return bool(self.window.winfo_exists())
        except Exception:
            return False

    def _safe_destroy(self) -> None:
        """Destroys Tk window on the UI thread and resets references."""
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
            finally:
                self.window = None
                self._ui_thread = None

    def _on_close(self) -> None:
        """Safely destroys the window and ensures self.window is reset to None."""
        if self.window is not None:
            try:
                if self._ui_thread and threading.current_thread() != self._ui_thread:
                    self.window.after(0, self._safe_destroy)
                else:
                    self._safe_destroy()
            except Exception:
                pass

    def show(self) -> None:
        with self._show_lock:
            if self._is_window_alive():
                try:
                    self.window.lift()
                    self.window.focus_force()
                    if sys.platform == "darwin":
                        from AppKit import NSApplication
                        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
                except Exception:
                    pass
                return

            self.window = None
            try:
                self.window = tk.Tk()
                self._ui_thread = threading.current_thread()
            except Exception as e:
                print(f"[SettingsDialog] Error initializing Tk: {e}")
                self.window = None
                self._ui_thread = None
                return

        # On macOS, ensure regular activation policy and activate window now that Tkinter has initialized
        if sys.platform == "darwin":
            try:
                from AppKit import NSApplication, NSApplicationActivationPolicyRegular
                ns_app = NSApplication.sharedApplication()
                ns_app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
                ns_app.activateIgnoringOtherApps_(True)
            except Exception:
                pass

        # Synchronize active i18n language with config
        set_current_language(self.config.language)

        self.window.title(f"{t('app_name')} v{__version__} — {t('tab_settings').strip()}")
        # Set WM_DELETE_WINDOW protocol to cleanly close and reset self.window
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        # Generous dimensions to fit all content cleanly across scaling factors
        self.window.geometry("740x660")
        self.window.minsize(640, 500)

        # Set window icon if icon.ico is available
        ico_path = Path(__file__).resolve().parent / "icon.ico"
        if getattr(sys, "frozen", False):
            candidate = Path(sys.executable).parent / "icon.ico"
            if candidate.exists():
                ico_path = candidate
            elif hasattr(sys, "_MEIPASS"):
                candidate = Path(sys._MEIPASS) / "icon.ico"
                if candidate.exists():
                    ico_path = candidate
        if ico_path.exists() and sys.platform.startswith("win"):
            try:
                self.window.iconbitmap(str(ico_path))
            except Exception:
                pass

        # Apply native visual style (aqua on macOS, vista/winnative on Windows)
        style = ttk.Style()
        theme_candidates = ("aqua", "clam") if sys.platform == "darwin" else ("vista", "winnative", "clam")
        for theme_name in theme_candidates:
            if theme_name in style.theme_names():
                try:
                    style.theme_use(theme_name)
                    break
                except Exception:
                    pass

        # Color scheme
        bg_window = "#F3F3F3"
        bg_card = "#FFFFFF"
        fg_text = "#1C1C1C"
        fg_muted = "#5F6368"
        accent_blue = "#0067C0"

        self.window.configure(bg=bg_window)

        # Typography configuration
        font_family = "Helvetica Neue" if sys.platform == "darwin" else "Segoe UI"
        style.configure("TNotebook", background=bg_window)
        style.configure("TNotebook.Tab", padding=[16, 7], font=(font_family, 9))
        style.configure("TFrame", background=bg_window)
        style.configure("Card.TFrame", background=bg_card)
        style.configure("TLabel", background=bg_window, font=(font_family, 9), foreground=fg_text)
        style.configure("Card.TLabel", background=bg_card, font=(font_family, 9), foreground=fg_text)
        style.configure(
            "Header.TLabel", background=bg_card, font=(font_family, 10, "bold"), foreground="#202124"
        )
        style.configure(
            "Subheader.TLabel", background=bg_card, font=(font_family, 8), foreground=fg_muted
        )
        style.configure("TButton", font=(font_family, 9))
        style.configure("Accent.TButton", font=(font_family, 9, "bold"))
        style.configure("TCheckbutton", background=bg_card, font=(font_family, 9), foreground=fg_text)

        # --- Top Header Bar ---
        header_bar = tk.Frame(self.window, bg="#FFFFFF", padx=20, pady=10)
        header_bar.pack(fill="x", side="top")

        title_row = tk.Frame(header_bar, bg="#FFFFFF")
        title_row.pack(fill="x")

        self.lbl_app_title = tk.Label(
            title_row,
            text=t("app_name"),
            font=("Segoe UI", 14, "bold"),
            fg="#1A1A1A",
            bg="#FFFFFF",
        )
        self.lbl_app_title.pack(side="left")

        # Version Pill Badge
        self.lbl_version_badge = tk.Label(
            title_row,
            text=f"v{__version__}",
            font=("Segoe UI", 8, "bold"),
            fg=accent_blue,
            bg="#EBF3FB",
            padx=8,
            pady=2,
        )
        self.lbl_version_badge.pack(side="left", padx=(10, 0))

        # Check for Updates Button
        self.btn_check_update = ttk.Button(
            title_row,
            text=f"🔍 {t('btn_check_updates')}",
            command=self._check_for_updates_ui,
        )
        self.btn_check_update.pack(side="right")

        self.lbl_app_subtitle = tk.Label(
            header_bar,
            text=t("app_subtitle"),
            font=("Segoe UI", 9),
            fg=fg_muted,
            bg="#FFFFFF",
        )
        self.lbl_app_subtitle.pack(anchor="w", pady=(2, 0))

        # Divider under header
        tk.Frame(self.window, height=1, bg="#E5E5E5").pack(fill="x", side="top")

        # --- Bottom Action Bar ---
        # IMPORTANT: Pack bottom bar FIRST so it is ALWAYS anchored and visible!
        bottom_divider = tk.Frame(self.window, height=1, bg="#E5E5E5")
        bottom_divider.pack(fill="x", side="bottom")

        bottom_bar = tk.Frame(self.window, bg=bg_window, padx=16, pady=10)
        bottom_bar.pack(fill="x", side="bottom")

        # "Save and Restart" button (Primary Accent button)
        self.btn_restart = ttk.Button(
            bottom_bar,
            text=f"🔄 {t('btn_save_restart')}",
            style="Accent.TButton",
            command=self._save_and_restart,
        )
        self.btn_restart.pack(side="right", padx=(8, 0))

        # "Save and Apply" button
        self.btn_save = ttk.Button(
            bottom_bar,
            text=t("btn_save_apply"),
            command=self._save_and_close,
        )
        self.btn_save.pack(side="right", padx=(8, 0))

        # "Close" button
        self.btn_cancel = ttk.Button(bottom_bar, text=t("btn_close"), command=self._on_close)
        self.btn_cancel.pack(side="right")

        # --- Tab Notebook (Expands in remaining space) ---
        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill="both", expand=True, padx=14, pady=(8, 8))

        # Tab 1: Connection (Scrollable)
        self.tab_conn = ScrollableTab(self.notebook, padding=(18, 14))
        self.notebook.add(self.tab_conn, text=t("tab_conn"))
        self._build_connection_tab(self.tab_conn.content)

        # Tab 2: Folders (Scrollable)
        self.tab_folders = ScrollableTab(self.notebook, padding=(18, 14))
        self.notebook.add(self.tab_folders, text=t("tab_folders"))
        self._build_folders_tab(self.tab_folders.content)

        # Tab 3: Settings & Backup (Scrollable)
        self.tab_settings = ScrollableTab(self.notebook, padding=(18, 14))
        self.notebook.add(self.tab_settings, text=t("tab_settings"))
        self._build_settings_tab(self.tab_settings.content)

        # Tab 4: History / Log
        self.tab_log = ttk.Frame(self.notebook, padding=12, style="Card.TFrame")
        self.notebook.add(self.tab_log, text=t("tab_log"))
        self._build_log_tab(self.tab_log)

        # Center on screen
        self.window.update_idletasks()
        w = self.window.winfo_width()
        h = self.window.winfo_height()
        x = max(0, (self.window.winfo_screenwidth() // 2) - (w // 2))
        y = max(0, (self.window.winfo_screenheight() // 2) - (h // 2))
        self.window.geometry(f"+{x}+{y}")

        # Bring window to front
        try:
            self.window.lift()
            self.window.attributes("-topmost", True)
            self.window.after_idle(self.window.attributes, "-topmost", False)
            self.window.focus_force()
        except Exception:
            pass

        try:
            self.window.mainloop()
        except Exception as e:
            print(f"[SettingsDialog] mainloop exception: {e}")
        finally:
            with self._show_lock:
                self.window = None
                self._ui_thread = None

    def _retranslate_ui(self) -> None:
        """Dynamically retranslates all open window elements when language is changed."""
        if not self._is_window_alive():
            return

        self.window.title(f"{t('app_name')} v{__version__} — {t('tab_settings').strip()}")
        self.lbl_app_title.config(text=t("app_name"))
        self.lbl_app_subtitle.config(text=t("app_subtitle"))

        self.notebook.tab(self.tab_conn, text=t("tab_conn"))
        self.notebook.tab(self.tab_folders, text=t("tab_folders"))
        self.notebook.tab(self.tab_settings, text=t("tab_settings"))
        self.notebook.tab(self.tab_log, text=t("tab_log"))

        self.btn_restart.config(text=f"🔄 {t('btn_save_restart')}")
        self.btn_save.config(text=t("btn_save_apply"))
        self.btn_cancel.config(text=t("btn_close"))
        if hasattr(self, "btn_check_update"):
            self.btn_check_update.config(text=f"🔍 {t('btn_check_updates')}")

        # Connection Tab
        self.lbl_conn_hdr.config(text=t("conn_header"))
        self.lbl_conn_sub.config(text=t("conn_sub"))
        if hasattr(self, "lbl_active_server"):
            self.lbl_active_server.config(text=self._get_active_server_display_text())
        if hasattr(self, "lbl_prim_label"):
            self.lbl_prim_label.config(text=t("conn_primary_label"))
        if hasattr(self, "radio_prim1"):
            self.radio_prim1.config(text=t("server_1"))
        if hasattr(self, "radio_prim2"):
            self.radio_prim2.config(text=t("server_2"))
        if hasattr(self, "lbl_s1_hdr"):
            self.lbl_s1_hdr.config(text=f"🌐 {t('conn_server1_title')}")
        self.lbl_conn_url.config(text=t("conn_url_label"))
        self.lbl_conn_user.config(text=t("conn_user_label"))
        self.lbl_conn_pwd.config(text=t("conn_pwd_label"))
        self.btn_test.config(text=t("conn_test_btn1"))
        if hasattr(self, "chk_backup_enable"):
            self.chk_backup_enable.config(text=f"🛡️ {t('conn_backup_enable')}")
        if hasattr(self, "lbl_backup_url"):
            self.lbl_backup_url.config(text=t("conn_url_label"))
        if hasattr(self, "lbl_backup_user"):
            self.lbl_backup_user.config(text=t("conn_user_label"))
        if hasattr(self, "lbl_backup_pwd"):
            self.lbl_backup_pwd.config(text=t("conn_pwd_label"))
        if hasattr(self, "btn_test2"):
            self.btn_test2.config(text=t("conn_test_btn2"))
        if hasattr(self, "chk_sync_backup"):
            self.chk_sync_backup.config(text=f"🔄 {t('conn_sync_backup_enable')}")
        if hasattr(self, "lbl_sync_backup_hint"):
            self.lbl_sync_backup_hint.config(text=t("conn_sync_backup_hint"))
        if hasattr(self, "lbl_sync_warn"):
            self.lbl_sync_warn.config(text=t("conn_sync_backup_warning"))
        if hasattr(self, "lbl_sync_status_title"):
            self.lbl_sync_status_title.config(text=f"📊 {t('servers_sync_status_title')}:")
        if hasattr(self, "btn_check_servers"):
            self.btn_check_servers.config(text=f"🔍 {t('servers_sync_btn_check')}")
        if hasattr(self, "btn_sync_servers_now"):
            self.btn_sync_servers_now.config(text=f"⚡ {t('servers_sync_btn_sync')}")
        if hasattr(self, "engine") and self.engine and hasattr(self, "_update_servers_sync_ui"):
            cached = self.engine.get_last_servers_sync_status()
            self._update_servers_sync_ui(cached)


        # Folders Tab
        self.lbl_folders_hdr.config(text=t("folders_header"))
        self.lbl_folders_sub.config(text=t("folders_sub"))
        self.lbl_folders_local.config(text=t("folders_local_label"))
        self.btn_browse.config(text=t("folders_browse_btn"))
        self.btn_open.config(text=t("folders_open_btn"))
        self.btn_shortcut.config(text=t("folders_shortcut_btn"))
        self.lbl_folders_remote.config(text=t("folders_remote_label"))
        self.lbl_folders_hint.config(text=t("folders_remote_hint"))
        if hasattr(self, "lbl_sync_tools_hdr"):
            self.lbl_sync_tools_hdr.config(text=t("sync_tools_header"))
        if hasattr(self, "lbl_sync_tools_sub"):
            self.lbl_sync_tools_sub.config(text=t("sync_tools_sub"))
        if hasattr(self, "btn_pull_missing"):
            self.btn_pull_missing.config(text=f"📥 {t('btn_pull_missing')}")
        if hasattr(self, "btn_full_sync"):
            self.btn_full_sync.config(text=f"🔄 {t('btn_full_sync')}")

        # Settings Tab
        self.lbl_settings_hdr.config(text=t("settings_header"))
        self.lbl_poll.config(text=t("settings_poll_label"))
        self.lbl_file_ret.config(text=t("settings_file_ret_label"))
        self.lbl_file_ret_hint.config(text=t("settings_disabled_hint"))
        self.btn_clean_now.config(text=t("settings_clean_now_btn"))
        self.lbl_log_ret.config(text=t("settings_log_ret_label"))
        self.lbl_log_ret_hint.config(text=t("settings_forever_hint"))
        if hasattr(self, "lbl_conflict"):
            self.lbl_conflict.config(text=t("settings_conflict_label"))
        if hasattr(self, "combo_conflict"):
            cur_idx = self.combo_conflict.current()
            self.combo_conflict.config(values=[t("settings_conflict_keep_both"), t("settings_conflict_newer_wins")])
            self.combo_conflict.current(cur_idx if cur_idx >= 0 else 0)
        if hasattr(self, "btn_dedup_now"):
            self.btn_dedup_now.config(text=t("settings_dedup_btn"))
        if hasattr(self, "lbl_dedup_hint"):
            self.lbl_dedup_hint.config(text=t("settings_dedup_hint"))
        self.lbl_lang.config(text=t("settings_lang_label"))
        self.chk_auto.config(text=t("settings_autostart"))
        self.chk_notify.config(text=t("settings_notify"))
        if hasattr(self, "chk_shortcut"):
            self.chk_shortcut.config(text=t("settings_desktop_shortcut"))
        self.lbl_ignore.config(text=t("settings_ignore_label"))
        self.lbl_backup_hdr.config(text=t("settings_backup_header"))
        self.lbl_backup_sub.config(text=t("settings_backup_sub"))
        self.btn_export.config(text=t("settings_export_btn"))
        self.btn_import.config(text=t("settings_import_btn"))

        # Log Tab
        self.lbl_log_hdr.config(text=t("log_header"))
        self.btn_clear_log.config(text=t("log_clear_btn"))
        self.btn_refresh_log.config(text=t("log_refresh_btn"))
        self.tree_log.heading("time", text=t("log_col_time"))
        self.tree_log.heading("action", text=t("log_col_action"))
        self.tree_log.heading("direction", text=t("log_col_direction"))
        self.tree_log.heading("file", text=t("log_col_file"))
        self.tree_log.heading("status", text=t("log_col_status"))
        self._refresh_logs()

    def _get_active_server_display_text(self) -> str:
        if self.config.backup_server_enabled and self.config.sync_backup_server:
            return f"[{t('server_badge')} 1 ⇄ 2] — {t('conn_sync_backup_enable')}"
        idx = getattr(self.engine, "active_server_index", self.config.primary_server_index) if self.engine else self.config.primary_server_index
        srv_name = t(f"server_{idx}")
        return t("conn_active_server_status", srv=srv_name)

    def _build_connection_tab(self, parent: ttk.Frame) -> None:
        self.lbl_conn_hdr = ttk.Label(parent, text=t("conn_header"), style="Header.TLabel")
        self.lbl_conn_hdr.pack(anchor="w", pady=(0, 2))

        self.lbl_conn_sub = ttk.Label(
            parent,
            text=t("conn_sub"),
            style="Subheader.TLabel",
        )
        self.lbl_conn_sub.pack(anchor="w", pady=(0, 10))

        # Active server indicator banner
        self.frame_active_badge = tk.Frame(parent, bg="#EBF3FB", padx=10, pady=6)
        self.frame_active_badge.pack(fill="x", pady=(0, 10))
        self.lbl_active_server = tk.Label(
            self.frame_active_badge,
            text=self._get_active_server_display_text(),
            font=("Segoe UI", 9, "bold"),
            fg="#0067C0",
            bg="#EBF3FB",
        )
        self.lbl_active_server.pack(side="left")

        # Preferred primary server selector
        prim_frame = tk.Frame(parent, bg="#FFFFFF")
        prim_frame.pack(fill="x", pady=(0, 12))
        self.lbl_prim_label = ttk.Label(prim_frame, text=t("conn_primary_label"), style="Card.TLabel")
        self.lbl_prim_label.pack(side="left", padx=(0, 12))
        self.var_primary_server = tk.IntVar(value=self.config.primary_server_index)
        self.radio_prim1 = ttk.Radiobutton(
            prim_frame,
            text=t("server_1"),
            variable=self.var_primary_server,
            value=1,
            command=self._on_primary_server_toggle,
        )
        self.radio_prim1.pack(side="left", padx=(0, 12))
        self.radio_prim2 = ttk.Radiobutton(
            prim_frame,
            text=t("server_2"),
            variable=self.var_primary_server,
            value=2,
            command=self._on_primary_server_toggle,
        )
        self.radio_prim2.pack(side="left")

        # ================= Server 1 Card =================
        self.lbl_s1_hdr = ttk.Label(parent, text=f"🌐 {t('conn_server1_title')}", style="Header.TLabel")
        self.lbl_s1_hdr.pack(anchor="w", pady=(0, 4))

        # Server 1 URL
        self.lbl_conn_url = ttk.Label(parent, text=t("conn_url_label"), style="Card.TLabel")
        self.lbl_conn_url.pack(anchor="w", pady=(0, 2))
        self.entry_url = ttk.Entry(parent, font=("Segoe UI", 9))
        self.entry_url.insert(0, self.config.server_url)
        self.entry_url.pack(fill="x", pady=(0, 6))

        # Server 1 Username
        self.lbl_conn_user = ttk.Label(parent, text=t("conn_user_label"), style="Card.TLabel")
        self.lbl_conn_user.pack(anchor="w", pady=(0, 2))
        self.entry_user = ttk.Entry(parent, font=("Segoe UI", 9))
        self.entry_user.insert(0, self.config.username)
        self.entry_user.pack(fill="x", pady=(0, 6))

        # Server 1 Password
        self.lbl_conn_pwd = ttk.Label(parent, text=t("conn_pwd_label"), style="Card.TLabel")
        self.lbl_conn_pwd.pack(anchor="w", pady=(0, 2))
        self.entry_pwd = ttk.Entry(parent, font=("Segoe UI", 9), show="•")
        self.entry_pwd.insert(0, self.config.password)
        self.entry_pwd.pack(fill="x", pady=(0, 8))

        # Test Server 1 button & status indicator
        test_frame1 = tk.Frame(parent, bg="#FFFFFF")
        test_frame1.pack(fill="x", pady=(0, 10))

        self.btn_test = ttk.Button(test_frame1, text=t("conn_test_btn1"), command=self._test_connection)
        self.btn_test.pack(side="left")

        self.lbl_test_status = tk.Label(
            test_frame1,
            text="",
            font=("Segoe UI", 9, "bold"),
            fg="#5F6368",
            bg="#FFFFFF",
        )
        self.lbl_test_status.pack(side="left", padx=(14, 0), fill="x", expand=True, anchor="w")

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(6, 12))

        # ================= Server 2 Card (Backup) =================
        self.var_backup_enabled = tk.BooleanVar(value=self.config.backup_server_enabled)
        self.chk_backup_enable = ttk.Checkbutton(
            parent,
            text=f"🛡️ {t('conn_backup_enable')}",
            variable=self.var_backup_enabled,
            command=self._on_backup_enable_toggle,
        )
        self.chk_backup_enable.pack(anchor="w", pady=(0, 6))

        self.frame_server2_body = tk.Frame(parent, bg="#FFFFFF")
        self.frame_server2_body.pack(fill="x", pady=(0, 4))

        # Server 2 URL
        self.lbl_backup_url = ttk.Label(self.frame_server2_body, text=t("conn_url_label"), style="Card.TLabel")
        self.lbl_backup_url.pack(anchor="w", pady=(0, 2))
        self.entry_backup_url = ttk.Entry(self.frame_server2_body, font=("Segoe UI", 9))
        self.entry_backup_url.insert(0, self.config.backup_server_url)
        self.entry_backup_url.pack(fill="x", pady=(0, 6))

        # Server 2 Username
        self.lbl_backup_user = ttk.Label(self.frame_server2_body, text=t("conn_user_label"), style="Card.TLabel")
        self.lbl_backup_user.pack(anchor="w", pady=(0, 2))
        self.entry_backup_user = ttk.Entry(self.frame_server2_body, font=("Segoe UI", 9))
        self.entry_backup_user.insert(0, self.config.backup_username)
        self.entry_backup_user.pack(fill="x", pady=(0, 6))

        # Server 2 Password
        self.lbl_backup_pwd = ttk.Label(self.frame_server2_body, text=t("conn_pwd_label"), style="Card.TLabel")
        self.lbl_backup_pwd.pack(anchor="w", pady=(0, 2))
        self.entry_backup_pwd = ttk.Entry(self.frame_server2_body, font=("Segoe UI", 9), show="•")
        self.entry_backup_pwd.insert(0, self.config.backup_password)
        self.entry_backup_pwd.pack(fill="x", pady=(0, 8))

        # Test Server 2 button & status indicator
        test_frame2 = tk.Frame(self.frame_server2_body, bg="#FFFFFF")
        test_frame2.pack(fill="x", pady=(0, 6))

        self.btn_test2 = ttk.Button(test_frame2, text=t("conn_test_btn2"), command=self._test_connection_2)
        self.btn_test2.pack(side="left")

        self.lbl_test_status2 = tk.Label(
            test_frame2,
            text="",
            font=("Segoe UI", 9, "bold"),
            fg="#5F6368",
            bg="#FFFFFF",
        )
        self.lbl_test_status2.pack(side="left", padx=(14, 0), fill="x", expand=True, anchor="w")

        ttk.Separator(self.frame_server2_body, orient="horizontal").pack(fill="x", pady=(8, 10))

        # --- Dual Server Synchronization (Mirroring) ---
        self.var_sync_backup = tk.BooleanVar(value=self.config.sync_backup_server)
        self.chk_sync_backup = ttk.Checkbutton(
            self.frame_server2_body,
            text=f"🔄 {t('conn_sync_backup_enable')}",
            variable=self.var_sync_backup,
            command=self._on_sync_backup_toggle,
        )
        self.chk_sync_backup.pack(anchor="w", pady=(0, 2))

        self.lbl_sync_backup_hint = ttk.Label(
            self.frame_server2_body,
            text=t("conn_sync_backup_hint"),
            style="Subheader.TLabel",
        )
        self.lbl_sync_backup_hint.pack(anchor="w", pady=(0, 4))

        # Warning callout banner
        self.frame_sync_warn = tk.Frame(self.frame_server2_body, bg="#FFF4CE", relief="solid", bd=1, padx=8, pady=6)
        self.frame_sync_warn.pack(fill="x", pady=(0, 8))
        self.lbl_sync_warn = tk.Label(
            self.frame_sync_warn,
            text=t("conn_sync_backup_warning"),
            font=("Segoe UI", 8),
            bg="#FFF4CE",
            fg="#794B02",
            justify="left",
            wraplength=520,
            anchor="w",
        )
        self.lbl_sync_warn.pack(fill="x")

        # Status & Comparison Card
        self.frame_sync_status = tk.Frame(self.frame_server2_body, bg="#F8F9FA", relief="solid", bd=1, padx=10, pady=8)
        self.frame_sync_status.pack(fill="x", pady=(0, 6))

        # Title & Badge row
        hdr_box = tk.Frame(self.frame_sync_status, bg="#F8F9FA")
        hdr_box.pack(fill="x", pady=(0, 4))
        self.lbl_sync_status_title = tk.Label(
            hdr_box,
            text=f"📊 {t('servers_sync_status_title')}:",
            font=("Segoe UI", 9, "bold"),
            bg="#F8F9FA",
            fg="#202124",
        )
        self.lbl_sync_status_title.pack(side="left")

        self.lbl_sync_status_badge = tk.Label(
            hdr_box,
            text="...",
            font=("Segoe UI", 9, "bold"),
            bg="#F8F9FA",
            fg="#0067C0",
        )
        self.lbl_sync_status_badge.pack(side="left", padx=(8, 0))

        # Server 1 details line
        self.lbl_s1_detail = tk.Label(
            self.frame_sync_status,
            text="",
            font=("Segoe UI", 8),
            bg="#F8F9FA",
            fg="#5F6368",
            anchor="w",
        )
        self.lbl_s1_detail.pack(fill="x", pady=(1, 1))

        # Server 2 details line
        self.lbl_s2_detail = tk.Label(
            self.frame_sync_status,
            text="",
            font=("Segoe UI", 8),
            bg="#F8F9FA",
            fg="#5F6368",
            anchor="w",
        )
        self.lbl_s2_detail.pack(fill="x", pady=(1, 1))

        # Coordinator / Leader details line
        self.lbl_leader_detail = tk.Label(
            self.frame_sync_status,
            text="",
            font=("Segoe UI", 8),
            bg="#F8F9FA",
            fg="#5F6368",
            anchor="w",
        )
        self.lbl_leader_detail.pack(fill="x", pady=(1, 6))

        # Action buttons
        btn_box = tk.Frame(self.frame_sync_status, bg="#F8F9FA")
        btn_box.pack(fill="x")

        self.btn_check_servers = ttk.Button(
            btn_box,
            text=f"🔍 {t('servers_sync_btn_check')}",
            command=self._on_check_servers_status,
        )
        self.btn_check_servers.pack(side="left", padx=(0, 6))

        self.btn_sync_servers_now = ttk.Button(
            btn_box,
            text=f"⚡ {t('servers_sync_btn_sync')}",
            command=self._on_sync_servers_now,
        )
        self.btn_sync_servers_now.pack(side="left")

        self.lbl_sync_action_status = tk.Label(
            btn_box,
            text="",
            font=("Segoe UI", 8, "italic"),
            bg="#F8F9FA",
            fg="#5F6368",
        )
        self.lbl_sync_action_status.pack(side="left", padx=(10, 0))

        self._on_backup_enable_toggle()

        # Initial status populate & check
        if getattr(self, "engine", None):
            cached = self.engine.get_last_servers_sync_status()
            self._update_servers_sync_ui(cached)
            if self.config.backup_server_enabled:
                self.window.after(300, self._on_check_servers_status)
        else:
            self._update_servers_sync_ui({"enabled": False, "state": "disabled", "badge": "⚪ " + t("servers_sync_disabled")})

    def _on_sync_backup_toggle(self) -> None:
        if self.var_sync_backup.get():
            ans = messagebox.askyesno(
                t("conn_sync_backup_confirm_title"),
                t("conn_sync_backup_confirm_msg"),
                parent=self.window,
            )
            if not ans:
                self.var_sync_backup.set(False)
                return

        self.config.sync_backup_server = self.var_sync_backup.get()
        is_enabled = self.var_sync_backup.get() and self.var_backup_enabled.get()
        if hasattr(self, "lbl_active_server"):
            self.lbl_active_server.config(text=self._get_active_server_display_text())
        if hasattr(self, "btn_sync_servers_now"):
            self.btn_sync_servers_now.config(state="normal" if is_enabled else "disabled")
        if not self.config.sync_backup_server and getattr(self, "engine", None):
            try:
                self.engine.release_sync_leader()
            except Exception:
                pass
        if is_enabled and getattr(self, "engine", None):
            self.window.after(100, self._on_check_servers_status)
        elif not is_enabled and hasattr(self, "lbl_leader_detail"):
            self.lbl_leader_detail.config(text="")

    def _on_primary_server_toggle(self) -> None:
        """Invoked when user switches between Server 1 and Server 2 as preferred."""
        prim_idx = self.var_primary_server.get()
        self.config.primary_server_index = prim_idx
        if prim_idx == 2:
            self.var_backup_enabled.set(True)
            self.config.backup_server_enabled = True
        self._on_backup_enable_toggle()
        if hasattr(self, "lbl_active_server"):
            self.lbl_active_server.config(text=self._get_active_server_display_text())

    def _on_backup_enable_toggle(self) -> None:
        is_server2_active = self.var_backup_enabled.get() or (getattr(self, "var_primary_server", tk.IntVar(value=1)).get() == 2)
        state = "normal" if is_server2_active else "disabled"
        if hasattr(self, "entry_backup_url"):
            self.entry_backup_url.config(state=state)
        if hasattr(self, "entry_backup_user"):
            self.entry_backup_user.config(state=state)
        if hasattr(self, "entry_backup_pwd"):
            self.entry_backup_pwd.config(state=state)
        if hasattr(self, "btn_test2"):
            self.btn_test2.config(state=state)
        if hasattr(self, "chk_sync_backup"):
            self.chk_sync_backup.config(state=state)
        if hasattr(self, "btn_check_servers"):
            self.btn_check_servers.config(state=state)
        if hasattr(self, "btn_sync_servers_now"):
            s_state = "normal" if (is_server2_active and getattr(self, "var_sync_backup", tk.BooleanVar()).get()) else "disabled"
            self.btn_sync_servers_now.config(state=s_state)
        if hasattr(self, "lbl_active_server"):
            self.lbl_active_server.config(text=self._get_active_server_display_text())
        if not is_server2_active and hasattr(self, "lbl_sync_status_badge"):
            self._update_servers_sync_ui({"enabled": False, "state": "disabled", "badge": "⚪ " + t("servers_sync_disabled")})

    def _update_servers_sync_ui(self, st: dict) -> None:
        if not self._is_window_alive():
            return
        if not hasattr(self, "lbl_sync_status_badge"):
            return

        state = st.get("state", "disabled")
        badge = st.get("badge", "")

        color_map = {
            "synced": "#0F7B0F",
            "server1_newer": "#B25E00",
            "server2_newer": "#B25E00",
            "diff_count": "#B25E00",
            "server1_offline": "#C42B1C",
            "server2_offline": "#C42B1C",
            "both_offline": "#C42B1C",
            "disabled": "#5F6368",
        }
        fg_color = color_map.get(state, "#5F6368")

        self.lbl_sync_status_badge.config(text=badge, fg=fg_color)

        s1 = st.get("server1", {})
        s2 = st.get("server2", {})

        if s1.get("online"):
            cnt1 = s1.get("file_count", 0)
            f1 = s1.get("latest_file", "")
            t1 = s1.get("latest_time_str", "")
            if cnt1 > 0 and f1:
                self.lbl_s1_detail.config(text=t("servers_sync_srv_info", idx=1, count=cnt1, file=f1, time=t1))
            else:
                self.lbl_s1_detail.config(text=t("servers_sync_srv_none", idx=1))
        elif s1.get("url"):
            self.lbl_s1_detail.config(text=t("servers_sync_srv_offline", idx=1))
        else:
            self.lbl_s1_detail.config(text="")

        if s2.get("online"):
            cnt2 = s2.get("file_count", 0)
            f2 = s2.get("latest_file", "")
            t2 = s2.get("latest_time_str", "")
            if cnt2 > 0 and f2:
                self.lbl_s2_detail.config(text=t("servers_sync_srv_info", idx=2, count=cnt2, file=f2, time=t2))
            else:
                self.lbl_s2_detail.config(text=t("servers_sync_srv_none", idx=2))
        elif s2.get("url"):
            self.lbl_s2_detail.config(text=t("servers_sync_srv_offline", idx=2))
        else:
            self.lbl_s2_detail.config(text="")

        if hasattr(self, "lbl_leader_detail"):
            leader = st.get("leader", {})
            if not self.config.sync_backup_server or not self.config.backup_server_enabled:
                self.lbl_leader_detail.config(text="")
            elif leader.get("is_self"):
                self.lbl_leader_detail.config(text=t("servers_sync_leader_self"), fg="#0F7B0F")
            elif leader.get("hostname") and time.time() <= float(leader.get("expires_at", 0)):
                self.lbl_leader_detail.config(text=t("servers_sync_leader_other", host=leader.get("hostname")), fg="#5F6368")
            else:
                self.lbl_leader_detail.config(text=t("servers_sync_leader_none"), fg="#5F6368")

        if hasattr(self, "btn_check_servers"):
            b_state = "normal" if self.var_backup_enabled.get() else "disabled"
            self.btn_check_servers.config(state=b_state)
        if hasattr(self, "btn_sync_servers_now"):
            s_state = "normal" if (self.var_backup_enabled.get() and getattr(self, "var_sync_backup", tk.BooleanVar()).get()) else "disabled"
            self.btn_sync_servers_now.config(state=s_state)

    def _on_check_servers_status(self) -> None:
        if not hasattr(self, "lbl_sync_status_badge"):
            return
        self.lbl_sync_status_badge.config(text=t("servers_sync_checking"), fg="#0067C0")
        if hasattr(self, "btn_check_servers"):
            self.btn_check_servers.config(state="disabled")
        if hasattr(self, "btn_sync_servers_now"):
            self.btn_sync_servers_now.config(state="disabled")

        def worker():
            engine = getattr(self, "engine", None)
            if engine:
                res = engine.compare_servers_status()
            else:
                db_path = self.config.config_dir / "state.db"
                sdb = StateDatabase(db_path)
                cli = FileBrowserClient(base_url=self.config.server_url, username=self.config.username, password=self.config.password)
                eng = SyncEngine(config=self.config, state_db=sdb, client=cli)
                res = eng.compare_servers_status()
            if self._is_window_alive():
                self.window.after(0, lambda: self._update_servers_sync_ui(res))

        threading.Thread(target=worker, daemon=True).start()

    def _on_sync_servers_now(self) -> None:
        if not hasattr(self, "btn_sync_servers_now"):
            return
        self._read_form_into_config()
        self.config.save()

        self.btn_check_servers.config(state="disabled")
        self.btn_sync_servers_now.config(state="disabled")
        if hasattr(self, "lbl_sync_action_status"):
            self.lbl_sync_action_status.config(text=t("status_checking"), fg="#0067C0")

        def worker():
            engine = getattr(self, "engine", None)
            if not engine:
                db_path = self.config.config_dir / "state.db"
                sdb = StateDatabase(db_path)
                cli = FileBrowserClient(base_url=self.config.server_url, username=self.config.username, password=self.config.password)
                engine = SyncEngine(config=self.config, state_db=sdb, client=cli)

            synced, errs = engine.sync_servers_mirror()
            res = engine.get_last_servers_sync_status()

            def on_done():
                if self._is_window_alive():
                    self._update_servers_sync_ui(res)
                    if hasattr(self, "lbl_sync_action_status"):
                        txt = f"✓ {synced} synced" if errs == 0 else f"✓ {synced} synced, {errs} errors"
                        col = "#0F7B0F" if errs == 0 else "#C42B1C"
                        self.lbl_sync_action_status.config(text=txt, fg=col)
                    self._refresh_logs()

            if self._is_window_alive():
                self.window.after(0, on_done)

        threading.Thread(target=worker, daemon=True).start()

    def _test_connection(self) -> None:
        self.lbl_test_status.config(text=t("conn_testing"), fg="#0067C0")
        self.btn_test.config(state="disabled")

        url = self.entry_url.get().strip()
        user = self.entry_user.get().strip()
        pwd = self.entry_pwd.get()

        def worker():
            test_client = FileBrowserClient(base_url=url, username=user, password=pwd, timeout=8)
            ok, msg = test_client.test_connection()
            if self._is_window_alive():
                self.window.after(0, lambda: self._on_test_done(ok, msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_test_done(self, ok: bool, msg: str) -> None:
        self.btn_test.config(state="normal")
        if ok:
            self.lbl_test_status.config(text=t("conn_success"), fg="#0F7B0F")
        else:
            self.lbl_test_status.config(text=t("conn_fail", msg=msg), fg="#C42B1C")

    def _test_connection_2(self) -> None:
        if not hasattr(self, "lbl_test_status2"):
            return
        self.lbl_test_status2.config(text=t("conn_testing"), fg="#0067C0")
        self.btn_test2.config(state="disabled")

        url = self.entry_backup_url.get().strip()
        user = self.entry_backup_user.get().strip() or self.entry_user.get().strip()
        pwd = self.entry_backup_pwd.get() or self.entry_pwd.get()

        def worker():
            test_client = FileBrowserClient(base_url=url, username=user, password=pwd, timeout=8)
            ok, msg = test_client.test_connection()
            if self._is_window_alive():
                self.window.after(0, lambda: self._on_test_2_done(ok, msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_test_2_done(self, ok: bool, msg: str) -> None:
        if hasattr(self, "btn_test2"):
            self.btn_test2.config(state="normal" if self.var_backup_enabled.get() else "disabled")
        if hasattr(self, "lbl_test_status2"):
            if ok:
                self.lbl_test_status2.config(text=t("conn_success"), fg="#0F7B0F")
            else:
                self.lbl_test_status2.config(text=t("conn_fail", msg=msg), fg="#C42B1C")


    def _build_folders_tab(self, parent: ttk.Frame) -> None:
        self.lbl_folders_hdr = ttk.Label(parent, text=t("folders_header"), style="Header.TLabel")
        self.lbl_folders_hdr.pack(anchor="w", pady=(0, 2))

        self.lbl_folders_sub = ttk.Label(
            parent,
            text=t("folders_sub"),
            style="Subheader.TLabel",
        )
        self.lbl_folders_sub.pack(anchor="w", pady=(0, 12))

        # Local folder
        self.lbl_folders_local = ttk.Label(parent, text=t("folders_local_label"), style="Card.TLabel")
        self.lbl_folders_local.pack(anchor="w", pady=(0, 2))

        local_row = tk.Frame(parent, bg="#FFFFFF")
        local_row.pack(fill="x", pady=(0, 6))

        self.entry_local = ttk.Entry(local_row, font=("Segoe UI", 9))
        self.entry_local.insert(0, str(self.config.local_path))
        self.entry_local.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_browse = ttk.Button(local_row, text=t("folders_browse_btn"), command=self._browse_local_folder)
        self.btn_browse.pack(side="right")

        # Action helpers for local folder
        btns_row = tk.Frame(parent, bg="#FFFFFF")
        btns_row.pack(fill="x", pady=(0, 12))

        self.btn_open = ttk.Button(
            btns_row,
            text=t("folders_open_btn"),
            command=lambda: open_folder_in_explorer(self.entry_local.get()),
        )
        self.btn_open.pack(side="left", padx=(0, 8))

        self.btn_shortcut = ttk.Button(
            btns_row, text=t("folders_shortcut_btn"), command=self._create_shortcut
        )
        self.btn_shortcut.pack(side="left")

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(4, 12))

        # Remote folder
        self.lbl_folders_remote = ttk.Label(parent, text=t("folders_remote_label"), style="Card.TLabel")
        self.lbl_folders_remote.pack(anchor="w", pady=(0, 2))

        self.entry_remote = ttk.Entry(parent, font=("Segoe UI", 9))
        self.entry_remote.insert(0, self.config.remote_path)
        self.entry_remote.pack(fill="x", pady=(0, 4))

        self.lbl_folders_hint = ttk.Label(
            parent,
            text=t("folders_remote_hint"),
            style="Subheader.TLabel",
        )
        self.lbl_folders_hint.pack(anchor="w")

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(14, 12))

        # --- Server Synchronization Tools ---
        self.lbl_sync_tools_hdr = ttk.Label(parent, text=t("sync_tools_header"), style="Header.TLabel")
        self.lbl_sync_tools_hdr.pack(anchor="w", pady=(0, 2))

        self.lbl_sync_tools_sub = ttk.Label(
            parent,
            text=t("sync_tools_sub"),
            style="Subheader.TLabel",
        )
        self.lbl_sync_tools_sub.pack(anchor="w", pady=(0, 10))

        sync_btns_row = tk.Frame(parent, bg="#FFFFFF")
        sync_btns_row.pack(fill="x", pady=(0, 8))

        # Button: Pull Missing Files
        self.btn_pull_missing = ttk.Button(
            sync_btns_row,
            text=f"📥 {t('btn_pull_missing')}",
            command=self._pull_missing_files_ui,
        )
        self.btn_pull_missing.pack(side="left", padx=(0, 8))

        # Button: Full Resync
        self.btn_full_sync = ttk.Button(
            sync_btns_row,
            text=f"🔄 {t('btn_full_sync')}",
            command=self._full_sync_ui,
        )
        self.btn_full_sync.pack(side="left")

        self.lbl_sync_status = tk.Label(parent, text="", font=("Segoe UI", 9), bg="#FFFFFF", anchor="w")
        self.lbl_sync_status.pack(fill="x", pady=(4, 0))

    def _pull_missing_files_ui(self) -> None:
        """Triggers pulling missing files from server in background and updates UI."""
        self._read_form_into_config()
        self.config.save()

        if self.client:
            self.client.base_url = self.config.server_url
            self.client.username = self.config.username
            self.client.password = self.config.password

        self.btn_pull_missing.config(state="disabled")
        self.btn_full_sync.config(state="disabled")
        self.lbl_sync_status.config(text=t("pull_missing_progress"), fg="#0067C0")

        def worker():
            engine = getattr(self, "engine", None)
            if not engine:
                db_path = self.config.config_dir / "state.db"
                state_db = StateDatabase(db_path)
                client = FileBrowserClient(
                    base_url=self.config.server_url,
                    username=self.config.username,
                    password=self.config.password,
                )
                engine = SyncEngine(config=self.config, state_db=state_db, client=client)

            downloaded, errors = engine.pull_missing_files()

            def on_done():
                if self._is_window_alive():
                    self.btn_pull_missing.config(state="normal")
                    self.btn_full_sync.config(state="normal")
                    if downloaded > 0:
                        self.lbl_sync_status.config(
                            text=t("pull_missing_done_msg", count=downloaded),
                            fg="#0F7B0F",
                        )
                        messagebox.showinfo(
                            t("pull_missing_done_title"),
                            t("pull_missing_done_msg", count=downloaded),
                            parent=self.window,
                        )
                    else:
                        self.lbl_sync_status.config(
                            text=t("pull_missing_none_msg"),
                            fg="#505050",
                        )
                        messagebox.showinfo(
                            t("pull_missing_none_title"),
                            t("pull_missing_none_msg"),
                            parent=self.window,
                        )
                    self._refresh_logs()

            if self._is_window_alive():
                self.window.after(0, on_done)

        threading.Thread(target=worker, daemon=True).start()

    def _full_sync_ui(self) -> None:
        """Triggers full bidirectional synchronization."""
        self._read_form_into_config()
        self.config.save()

        if self.client:
            self.client.base_url = self.config.server_url
            self.client.username = self.config.username
            self.client.password = self.config.password

        self.btn_pull_missing.config(state="disabled")
        self.btn_full_sync.config(state="disabled")
        self.lbl_sync_status.config(text=t("status_checking"), fg="#0067C0")

        def worker():
            engine = getattr(self, "engine", None)
            if not engine:
                db_path = self.config.config_dir / "state.db"
                state_db = StateDatabase(db_path)
                client = FileBrowserClient(
                    base_url=self.config.server_url,
                    username=self.config.username,
                    password=self.config.password,
                )
                engine = SyncEngine(config=self.config, state_db=state_db, client=client)

            engine.reconcile_all()

            def on_done():
                if self._is_window_alive():
                    self.btn_pull_missing.config(state="normal")
                    self.btn_full_sync.config(state="normal")
                    self.lbl_sync_status.config(text=t("status_synced"), fg="#0F7B0F")
                    self._refresh_logs()

            if self._is_window_alive():
                self.window.after(0, on_done)

        threading.Thread(target=worker, daemon=True).start()

    def _browse_local_folder(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.entry_local.get())
        if chosen:
            self.entry_local.delete(0, tk.END)
            self.entry_local.insert(0, chosen)

    def _create_shortcut(self) -> None:
        path = self.entry_local.get().strip()
        if not path:
            return
        Path(path).mkdir(parents=True, exist_ok=True)
        ok = create_desktop_shortcut(path)
        if ok:
            messagebox.showinfo(
                t("shortcut_success_title"),
                t("shortcut_success_msg", path=path),
                parent=self.window,
            )
        else:
            messagebox.showerror(t("shortcut_fail_title"), t("shortcut_fail_msg"), parent=self.window)

    def _build_settings_tab(self, parent: ttk.Frame) -> None:
        self.lbl_settings_hdr = ttk.Label(parent, text=t("settings_header"), style="Header.TLabel")
        self.lbl_settings_hdr.pack(anchor="w", pady=(0, 8))

        # 1. Poll interval
        poll_row = tk.Frame(parent, bg="#FFFFFF")
        poll_row.pack(fill="x", pady=(0, 5))
        self.lbl_poll = ttk.Label(poll_row, text=t("settings_poll_label"), style="Card.TLabel")
        self.lbl_poll.pack(side="left", padx=(0, 8))

        self.spin_poll = ttk.Spinbox(poll_row, from_=5, to=3600, width=6, font=("Segoe UI", 9))
        self.spin_poll.set(self.config.poll_interval)
        self.spin_poll.pack(side="left")

        # 2. File retention (Auto-cleanup of old files)
        file_ret_row = tk.Frame(parent, bg="#FFFFFF")
        file_ret_row.pack(fill="x", pady=(0, 5))
        self.lbl_file_ret = ttk.Label(file_ret_row, text=t("settings_file_ret_label"), style="Card.TLabel")
        self.lbl_file_ret.pack(side="left", padx=(0, 8))

        self.spin_file_retention = ttk.Spinbox(
            file_ret_row, from_=0, to=365, width=5, font=("Segoe UI", 9)
        )
        self.spin_file_retention.set(self.config.file_retention_days)
        self.spin_file_retention.pack(side="left", padx=(0, 6))

        self.lbl_file_ret_hint = ttk.Label(file_ret_row, text=t("settings_disabled_hint"), style="Subheader.TLabel")
        self.lbl_file_ret_hint.pack(side="left", padx=(0, 10))

        self.btn_clean_now = ttk.Button(
            file_ret_row, text=t("settings_clean_now_btn"), command=self._trigger_file_cleanup_now
        )
        self.btn_clean_now.pack(side="left")

        # 3. History log retention
        log_ret_row = tk.Frame(parent, bg="#FFFFFF")
        log_ret_row.pack(fill="x", pady=(0, 5))
        self.lbl_log_ret = ttk.Label(log_ret_row, text=t("settings_log_ret_label"), style="Card.TLabel")
        self.lbl_log_ret.pack(side="left", padx=(0, 8))

        self.spin_retention = ttk.Spinbox(log_ret_row, from_=0, to=365, width=5, font=("Segoe UI", 9))
        self.spin_retention.set(self.config.log_retention_days)
        self.spin_retention.pack(side="left", padx=(0, 6))

        self.lbl_log_ret_hint = ttk.Label(log_ret_row, text=t("settings_forever_hint"), style="Subheader.TLabel")
        self.lbl_log_ret_hint.pack(side="left")

        # 4. Conflict resolution
        conflict_row = tk.Frame(parent, bg="#FFFFFF")
        conflict_row.pack(fill="x", pady=(0, 4))
        self.lbl_conflict = ttk.Label(conflict_row, text=t("settings_conflict_label"), style="Card.TLabel")
        self.lbl_conflict.pack(side="left", padx=(0, 8))

        self.combo_conflict = ttk.Combobox(
            conflict_row,
            values=[t("settings_conflict_keep_both"), t("settings_conflict_newer_wins")],
            state="readonly",
            font=("Segoe UI", 9),
        )
        self.combo_conflict.current(1 if self.config.conflict_action == "newer_wins" else 0)
        self.combo_conflict.pack(side="left", fill="x", expand=True)

        # 4b. Deduplication button row (below conflict selector for full visibility)
        dedup_row = tk.Frame(parent, bg="#FFFFFF")
        dedup_row.pack(fill="x", pady=(2, 6))
        self.btn_dedup_now = ttk.Button(
            dedup_row, text=t("settings_dedup_btn"), command=self._trigger_dedup_now
        )
        self.btn_dedup_now.pack(side="left", padx=(0, 8))

        self.lbl_dedup_hint = ttk.Label(
            dedup_row, text=t("settings_dedup_hint"), style="Subheader.TLabel"
        )
        self.lbl_dedup_hint.pack(side="left", fill="x", expand=True)

        # 5. Interface Language selector with live switching
        lang_row = tk.Frame(parent, bg="#FFFFFF")
        lang_row.pack(fill="x", pady=(0, 2))
        self.lbl_lang = ttk.Label(lang_row, text=t("settings_lang_label"), style="Card.TLabel")
        self.lbl_lang.pack(side="left", padx=(0, 8))

        self.lang_codes = list(SUPPORTED_LANGUAGES.keys())
        lang_display_names = [SUPPORTED_LANGUAGES[k] for k in self.lang_codes]
        self.combo_lang = ttk.Combobox(
            lang_row,
            values=lang_display_names,
            state="readonly",
            font=("Segoe UI", 9),
            width=24,
        )
        cur_lang = self.config.language
        if cur_lang in self.lang_codes:
            self.combo_lang.current(self.lang_codes.index(cur_lang))
        else:
            self.combo_lang.current(0)
        self.combo_lang.pack(side="left", padx=(0, 8))
        self.combo_lang.bind("<<ComboboxSelected>>", self._on_lang_selected)

        # Live language hint label
        self.lbl_lang_hint = tk.Label(
            parent,
            text="",
            font=("Segoe UI", 8, "italic"),
            fg="#0F7B0F",
            bg="#FFFFFF",
            anchor="w",
        )
        self.lbl_lang_hint.pack(fill="x", pady=(0, 6))

        # Checkboxes
        self.var_autostart = tk.BooleanVar(value=is_windows_autostart_enabled())
        self.chk_auto = ttk.Checkbutton(
            parent,
            text=t("settings_autostart"),
            variable=self.var_autostart,
            style="TCheckbutton",
        )
        self.chk_auto.pack(anchor="w", pady=(1, 4))

        self.var_notify = tk.BooleanVar(value=self.config.notify_on_sync)
        self.chk_notify = ttk.Checkbutton(
            parent,
            text=t("settings_notify"),
            variable=self.var_notify,
            style="TCheckbutton",
        )
        self.chk_notify.pack(anchor="w", pady=(1, 4))

        self.var_shortcut = tk.BooleanVar(value=self.config.desktop_shortcut)
        self.chk_shortcut = ttk.Checkbutton(
            parent,
            text=t("settings_desktop_shortcut"),
            variable=self.var_shortcut,
            style="TCheckbutton",
        )
        self.chk_shortcut.pack(anchor="w", pady=(1, 6))

        # Ignore patterns
        self.lbl_ignore = ttk.Label(parent, text=t("settings_ignore_label"), style="Card.TLabel")
        self.lbl_ignore.pack(anchor="w", pady=(0, 2))

        self.entry_ignore = ttk.Entry(parent, font=("Segoe UI", 9))
        self.entry_ignore.insert(0, ", ".join(self.config.ignore_patterns))
        self.entry_ignore.pack(fill="x", pady=(0, 8))

        # Backup / Restore settings section
        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(4, 8))
        self.lbl_backup_hdr = ttk.Label(parent, text=t("settings_backup_header"), style="Header.TLabel")
        self.lbl_backup_hdr.pack(anchor="w", pady=(0, 2))

        self.lbl_backup_sub = ttk.Label(
            parent,
            text=t("settings_backup_sub"),
            style="Subheader.TLabel",
        )
        self.lbl_backup_sub.pack(anchor="w", pady=(0, 6))

        backup_row = tk.Frame(parent, bg="#FFFFFF")
        backup_row.pack(fill="x", pady=(0, 4))

        self.btn_export = ttk.Button(
            backup_row, text=t("settings_export_btn"), command=self._export_settings
        )
        self.btn_export.pack(side="left", padx=(0, 8))

        self.btn_import = ttk.Button(
            backup_row, text=t("settings_import_btn"), command=self._import_settings
        )
        self.btn_import.pack(side="left")

    def _on_lang_selected(self, event=None) -> None:
        """Called immediately when user chooses a new language in combobox."""
        idx = self.combo_lang.current()
        if 0 <= idx < len(self.lang_codes):
            selected_lang = self.lang_codes[idx]
            self.config.language = selected_lang
            set_current_language(selected_lang)
            self._retranslate_ui()
            if hasattr(self, "lbl_lang_hint"):
                self.lbl_lang_hint.config(text=t("settings_restart_note"), fg="#0F7B0F")

    def _trigger_file_cleanup_now(self) -> None:
        try:
            days = int(self.spin_file_retention.get())
        except Exception:
            days = self.config.file_retention_days

        if days <= 0:
            messagebox.showinfo(
                t("cleanup_disabled_title"),
                t("cleanup_disabled_msg"),
                parent=self.window,
            )
            return

        ans = messagebox.askyesno(
            t("cleanup_confirm_title"),
            t("cleanup_confirm_msg", days=days),
            parent=self.window,
        )
        if not ans:
            return

        def run_cleanup():
            count = 0
            if getattr(self, "engine", None):
                count = self.engine.cleanup_old_files(retention_days=days)
            messagebox.showinfo(
                t("cleanup_done_title"),
                t("cleanup_done_msg", count=count),
                parent=self.window,
            )

        threading.Thread(target=run_cleanup, daemon=True).start()

    def _trigger_dedup_now(self) -> None:
        if not getattr(self, "engine", None):
            return

        ans = messagebox.askyesno(
            t("dedup_confirm_title"),
            t("dedup_confirm_msg"),
            parent=self.window,
        )
        if not ans:
            return

        def run_dedup():
            count, freed_bytes = self.engine.deduplicate_conflict_copies()
            mb = freed_bytes / (1024 * 1024)
            if count > 0:
                messagebox.showinfo(
                    t("dedup_done_title"),
                    t("dedup_done_msg", count=count, mb=mb),
                    parent=self.window,
                )
            else:
                messagebox.showinfo(
                    t("dedup_none_title"),
                    t("dedup_none_msg"),
                    parent=self.window,
                )
            if self._is_window_alive():
                self.window.after(0, self._refresh_logs)

        threading.Thread(target=run_dedup, daemon=True).start()

    def _build_log_tab(self, parent: ttk.Frame) -> None:
        header_row = tk.Frame(parent, bg="#FFFFFF")
        header_row.pack(fill="x", pady=(0, 8))
        self.lbl_log_hdr = ttk.Label(header_row, text=t("log_header"), style="Header.TLabel")
        self.lbl_log_hdr.pack(side="left")

        self.btn_clear_log = ttk.Button(header_row, text=t("log_clear_btn"), command=self._clear_logs)
        self.btn_clear_log.pack(side="right", padx=(8, 0))

        self.btn_refresh_log = ttk.Button(header_row, text=t("log_refresh_btn"), command=self._refresh_logs)
        self.btn_refresh_log.pack(side="right")

        # Treeview
        cols = ("time", "action", "direction", "file", "status")
        self.tree_log = ttk.Treeview(parent, columns=cols, show="headings", height=12)

        self.tree_log.heading("time", text=t("log_col_time"))
        self.tree_log.heading("action", text=t("log_col_action"))
        self.tree_log.heading("direction", text=t("log_col_direction"))
        self.tree_log.heading("file", text=t("log_col_file"))
        self.tree_log.heading("status", text=t("log_col_status"))

        self.tree_log.column("time", width=100, anchor="center")
        self.tree_log.column("action", width=85, anchor="center")
        self.tree_log.column("direction", width=95, anchor="center")
        self.tree_log.column("file", width=220, anchor="w")
        self.tree_log.column("status", width=85, anchor="center")

        scroll = ttk.Scrollbar(parent, orient="vertical", command=self.tree_log.yview)
        self.tree_log.configure(yscrollcommand=scroll.set)

        self.tree_log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self._refresh_logs()

    def _clear_logs(self) -> None:
        ans = messagebox.askyesno(
            t("log_clear_title"),
            t("log_clear_msg"),
            parent=self.window,
        )
        if ans and self.state_db:
            self.state_db.clear_history()
            self._refresh_logs()

    def _refresh_logs(self) -> None:
        for row in self.tree_log.get_children():
            self.tree_log.delete(row)

        if not self.state_db:
            return

        records = self.state_db.get_recent_history(limit=50)
        action_names = {
            "upload": t("action_upload"),
            "download": t("action_download"),
            "delete": t("action_delete"),
            "conflict": t("action_conflict"),
            "cleanup": t("action_cleanup"),
        }
        for r in records:
            ts = datetime.fromtimestamp(r["timestamp"]).strftime("%H:%M:%S")
            act = action_names.get(r["action"], r["action"])
            stat = t("status_success") if r["status"] == "success" else r["status"]
            self.tree_log.insert("", "end", values=(ts, act, r["direction"], r["rel_path"], stat))

    def _read_form_into_config(self) -> None:
        """Updates the in-memory config object with values from form fields."""
        self.config.server_url = self.entry_url.get().strip()
        self.config.username = self.entry_user.get().strip()
        self.config.password = self.entry_pwd.get()

        if hasattr(self, "var_primary_server"):
            self.config.primary_server_index = self.var_primary_server.get()

        if hasattr(self, "var_backup_enabled"):
            if self.config.primary_server_index == 2:
                self.config.backup_server_enabled = True
            else:
                self.config.backup_server_enabled = self.var_backup_enabled.get()

        if hasattr(self, "var_sync_backup"):
            self.config.sync_backup_server = self.var_sync_backup.get()

        if hasattr(self, "entry_backup_url"):
            self.config.backup_server_url = self.entry_backup_url.get().strip()
        if hasattr(self, "entry_backup_user"):
            self.config.backup_username = self.entry_backup_user.get().strip()
        if hasattr(self, "entry_backup_pwd"):
            self.config.backup_password = self.entry_backup_pwd.get()

        if hasattr(self, "entry_local"):
            self.config.local_path = self.entry_local.get().strip()
        if hasattr(self, "entry_remote"):
            self.config.remote_path = self.entry_remote.get().strip()
            self.config.backup_remote_path = self.entry_remote.get().strip()

        if hasattr(self, "spin_poll"):
            try:
                self.config.poll_interval = int(self.spin_poll.get())
            except Exception:
                pass

        if hasattr(self, "spin_file_retention"):
            try:
                self.config.file_retention_days = int(self.spin_file_retention.get())
            except Exception:
                pass

        if hasattr(self, "spin_retention"):
            try:
                self.config.log_retention_days = int(self.spin_retention.get())
            except Exception:
                pass

        if hasattr(self, "combo_lang"):
            idx = self.combo_lang.current()
            if 0 <= idx < len(self.lang_codes):
                selected_lang = self.lang_codes[idx]
                self.config.language = selected_lang
                set_current_language(selected_lang)

        if hasattr(self, "combo_conflict"):
            idx = self.combo_conflict.current()
            self.config.conflict_action = "newer_wins" if idx == 1 else "keep_both"

        if hasattr(self, "var_notify"):
            self.config.notify_on_sync = self.var_notify.get()
        if hasattr(self, "var_autostart"):
            self.config.start_with_windows = self.var_autostart.get()
        if hasattr(self, "var_shortcut"):
            self.config.desktop_shortcut = self.var_shortcut.get()

        if hasattr(self, "entry_ignore"):
            raw_patterns = [p.strip() for p in self.entry_ignore.get().split(",") if p.strip()]
            if raw_patterns:
                self.config.set("ignore_patterns", raw_patterns)

    def _populate_form_fields(self) -> None:
        """Populates UI fields from the current config object."""
        self.entry_url.delete(0, tk.END)
        self.entry_url.insert(0, self.config.server_url)

        self.entry_user.delete(0, tk.END)
        self.entry_user.insert(0, self.config.username)

        self.entry_pwd.delete(0, tk.END)
        self.entry_pwd.insert(0, self.config.password)

        if hasattr(self, "var_backup_enabled"):
            self.var_backup_enabled.set(self.config.backup_server_enabled)
        if hasattr(self, "var_sync_backup"):
            self.var_sync_backup.set(self.config.sync_backup_server)

        # Set state to normal first so delete/insert succeeds reliably without Tkinter dropping text
        for entry_widget, val in [
            (getattr(self, "entry_backup_url", None), self.config.backup_server_url),
            (getattr(self, "entry_backup_user", None), self.config.backup_username),
            (getattr(self, "entry_backup_pwd", None), self.config.backup_password),
        ]:
            if entry_widget:
                try:
                    entry_widget.config(state="normal")
                    entry_widget.delete(0, tk.END)
                    entry_widget.insert(0, val or "")
                except Exception:
                    pass

        if hasattr(self, "var_primary_server"):
            self.var_primary_server.set(self.config.primary_server_index)
        if hasattr(self, "lbl_active_server"):
            self.lbl_active_server.config(text=self._get_active_server_display_text())
        if hasattr(self, "_on_backup_enable_toggle"):
            self._on_backup_enable_toggle()

        self.entry_local.delete(0, tk.END)
        self.entry_local.insert(0, str(self.config.local_path))


        self.entry_remote.delete(0, tk.END)
        self.entry_remote.insert(0, self.config.remote_path)

        self.spin_poll.set(self.config.poll_interval)
        self.spin_file_retention.set(self.config.file_retention_days)
        self.spin_retention.set(self.config.log_retention_days)

        if hasattr(self, "combo_conflict"):
            self.combo_conflict.current(1 if self.config.conflict_action == "newer_wins" else 0)

        if hasattr(self, "combo_lang") and hasattr(self, "lang_codes"):
            cur_lang = self.config.language
            if cur_lang in self.lang_codes:
                self.combo_lang.current(self.lang_codes.index(cur_lang))

        self.var_autostart.set(self.config.start_with_windows)
        self.var_notify.set(self.config.notify_on_sync)
        if hasattr(self, "var_shortcut"):
            self.var_shortcut.set(self.config.desktop_shortcut)

        self.entry_ignore.delete(0, tk.END)
        self.entry_ignore.insert(0, ", ".join(self.config.ignore_patterns))

    def _export_settings(self) -> None:
        """Exports current settings to a user-chosen backup JSON file."""
        self._read_form_into_config()
        chosen = filedialog.asksaveasfilename(
            parent=self.window,
            title=t("settings_backup_header"),
            defaultextension=".json",
            initialfile="dropfile_backup.json",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
        )
        if not chosen:
            return

        ok = self.config.export_config(chosen)
        if ok:
            messagebox.showinfo(
                t("export_success_title"),
                t("export_success_msg", path=chosen),
                parent=self.window,
            )
        else:
            messagebox.showerror(t("export_fail_title"), t("export_fail_msg"), parent=self.window)

    def _import_settings(self) -> None:
        """Imports settings from a backup JSON file and updates UI and client."""
        chosen = filedialog.askopenfilename(
            parent=self.window,
            title=t("import_dialog_title"),
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
        )
        if not chosen:
            return

        ok = self.config.import_config(chosen)
        if ok:
            set_current_language(self.config.language)
            self._retranslate_ui()
            self._populate_form_fields()
            if self.engine:
                self.engine.apply_server_connection(self.config.primary_server_index)
            elif self.client:
                self.client.base_url = self.config.server_url
                self.client.username = self.config.username
                self.client.password = self.config.password
                self.client.token = None
            set_windows_autostart(self.config.start_with_windows)
            messagebox.showinfo(
                t("import_success_title"),
                t("import_success_msg"),
                parent=self.window,
            )
        else:
            messagebox.showerror(
                t("import_fail_title"),
                t("import_fail_msg"),
                parent=self.window,
            )

    def _save_and_close(self) -> None:
        """Saves configuration and applies to active client/engine without restarting process."""
        try:
            self._read_form_into_config()
            self.config.save()
        except Exception as e:
            messagebox.showerror(t("error_title"), f"Error saving settings: {e}", parent=self.window)
            return

        # Update Windows autostart registry
        set_windows_autostart(self.var_autostart.get())

        # Update desktop shortcut
        if self.config.desktop_shortcut:
            create_desktop_shortcut(self.config.local_path)
        else:
            remove_desktop_shortcut()

        # Update client
        if self.engine:
            self.engine.apply_server_connection(self.config.primary_server_index)
        elif self.client:
            if self.config.primary_server_index == 2:
                self.client.base_url = self.config.backup_server_url
                self.client.username = self.config.backup_username or self.config.username
                self.client.password = self.config.backup_password or self.config.password
            else:
                self.client.base_url = self.config.server_url
                self.client.username = self.config.username
                self.client.password = self.config.password
            self.client.token = None  # Force re-login with updated credentials


        if self.on_save_callback:
            try:
                self.on_save_callback()
            except Exception as e:
                print(f"[SettingsDialog] Error in on_save_callback: {e}")

        if self.window:
            self.window.destroy()
            self.window = None

    def _save_and_restart(self) -> None:
        """Saves configuration and triggers a clean full application restart."""
        try:
            self._read_form_into_config()
            self.config.save()
        except Exception as e:
            messagebox.showerror(t("error_title"), f"Error saving settings: {e}", parent=self.window)
            return

        # Update Windows autostart registry
        set_windows_autostart(self.var_autostart.get())

        # Update desktop shortcut
        if self.config.desktop_shortcut:
            create_desktop_shortcut(self.config.local_path)
        else:
            remove_desktop_shortcut()

        if self.window:
            try:
                self.window.destroy()
            except Exception:
                pass
            self.window = None

        if self.on_restart_callback:
            try:
                self.on_restart_callback()
                return
            except Exception as e:
                print(f"[SettingsDialog] Error calling on_restart_callback: {e}")

        # Fallback direct restart if callback was not passed
        if self.on_cleanup_callback:
            try:
                self.on_cleanup_callback()
            except Exception:
                pass
        restart_dropfile()
        os._exit(0)

    def _check_for_updates_ui(self) -> None:
        """Triggers asynchronous update check against GitHub Releases."""
        if hasattr(self, "btn_check_update"):
            self.btn_check_update.config(state="disabled", text=t("update_checking"))

        def worker():
            has_update, info = check_for_updates()
            if self._is_window_alive():
                self.window.after(0, lambda: self._on_check_update_result(has_update, info))

        threading.Thread(target=worker, daemon=True).start()

    def _on_check_update_result(self, has_update: bool, info: dict) -> None:
        """Processes GitHub release check results and prompts user on UI thread."""
        if not self._is_window_alive():
            return

        if hasattr(self, "btn_check_update"):
            self.btn_check_update.config(state="normal", text=f"🔍 {t('btn_check_updates')}")

        if info.get("error"):
            if info.get("not_found"):
                messagebox.showinfo(
                    t("update_latest_title"),
                    t("update_latest_msg", version=__version__),
                    parent=self.window,
                )
            else:
                messagebox.showerror(
                    t("update_error_title"),
                    t("update_error_msg", msg=info.get("error")),
                    parent=self.window,
                )
            return

        if not has_update:
            messagebox.showinfo(
                t("update_latest_title"),
                t("update_latest_msg", version=__version__),
                parent=self.window,
            )
            return

        remote_ver = info.get("version", "")
        body = (info.get("notes") or "").strip()
        msg = t("update_avail_msg", version=remote_ver)
        if body:
            preview = body[:300] + ("..." if len(body) > 300 else "")
            msg += f"\n\nRelease notes:\n{preview}"

        do_update = messagebox.askyesno(
            t("update_avail_title"),
            msg,
            parent=self.window,
        )
        if do_update:
            self._start_download_and_apply(info)

    def _start_download_and_apply(self, info: dict) -> None:
        """Downloads release binary or runs git pull and triggers self-update restart."""
        if hasattr(self, "btn_check_update"):
            self.btn_check_update.config(state="disabled", text=t("update_downloading"))

        def on_progress(percent: int):
            if self._is_window_alive() and hasattr(self, "btn_check_update"):
                self.window.after(
                    0, lambda: self.btn_check_update.config(text=f"⬇️ {percent}%...")
                )

        def worker():
            def cleanup():
                if hasattr(self, "on_cleanup_callback") and self.on_cleanup_callback:
                    try:
                        self.on_cleanup_callback()
                    except Exception as e:
                        print(f"[SettingsDialog] cleanup error: {e}")

            ok, err = apply_update(
                info,
                progress_callback=on_progress,
                on_before_restart=cleanup,
            )
            if not ok:
                if self._is_window_alive():
                    def show_update_failure():
                        if not self._is_window_alive():
                            return
                        err_text = t("update_error_msg", msg=err)
                        html_url = info.get("html_url")
                        if html_url:
                            prompt_text = f"{err_text}\n\n{t('update_open_browser')}"
                            if messagebox.askyesno(
                                t("update_error_title"),
                                prompt_text,
                                parent=self.window,
                            ):
                                import webbrowser
                                webbrowser.open(html_url)
                        else:
                            messagebox.showerror(
                                t("update_error_title"),
                                err_text,
                                parent=self.window,
                            )
                        if hasattr(self, "btn_check_update"):
                            self.btn_check_update.config(
                                state="normal", text=f"🔍 {t('btn_check_updates')}"
                            )

                    self.window.after(0, show_update_failure)

        threading.Thread(target=worker, daemon=True).start()


if __name__ == "__main__":
    from config import Config
    from fb_client import FileBrowserClient
    from state_db import StateDatabase

    cfg = Config()
    db = StateDatabase(cfg.config_dir / "state.db")
    cl = FileBrowserClient(cfg.server_url, cfg.username, cfg.password)
    dlg = SettingsDialog(cfg, db, cl)
    dlg.show()

