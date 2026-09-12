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
        self.lbl_conn_url.config(text=t("conn_url_label"))
        self.lbl_conn_user.config(text=t("conn_user_label"))
        self.lbl_conn_pwd.config(text=t("conn_pwd_label"))
        self.btn_test.config(text=t("conn_test_btn"))

        # Folders Tab
        self.lbl_folders_hdr.config(text=t("folders_header"))
        self.lbl_folders_sub.config(text=t("folders_sub"))
        self.lbl_folders_local.config(text=t("folders_local_label"))
        self.btn_browse.config(text=t("folders_browse_btn"))
        self.btn_open.config(text=t("folders_open_btn"))
        self.btn_shortcut.config(text=t("folders_shortcut_btn"))
        self.lbl_folders_remote.config(text=t("folders_remote_label"))
        self.lbl_folders_hint.config(text=t("folders_remote_hint"))

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

    def _build_connection_tab(self, parent: ttk.Frame) -> None:
        self.lbl_conn_hdr = ttk.Label(parent, text=t("conn_header"), style="Header.TLabel")
        self.lbl_conn_hdr.pack(anchor="w", pady=(0, 2))

        self.lbl_conn_sub = ttk.Label(
            parent,
            text=t("conn_sub"),
            style="Subheader.TLabel",
        )
        self.lbl_conn_sub.pack(anchor="w", pady=(0, 12))

        # Server URL
        self.lbl_conn_url = ttk.Label(parent, text=t("conn_url_label"), style="Card.TLabel")
        self.lbl_conn_url.pack(anchor="w", pady=(0, 2))
        self.entry_url = ttk.Entry(parent, font=("Segoe UI", 9))
        self.entry_url.insert(0, self.config.server_url)
        self.entry_url.pack(fill="x", pady=(0, 8))

        # Username
        self.lbl_conn_user = ttk.Label(parent, text=t("conn_user_label"), style="Card.TLabel")
        self.lbl_conn_user.pack(anchor="w", pady=(0, 2))
        self.entry_user = ttk.Entry(parent, font=("Segoe UI", 9))
        self.entry_user.insert(0, self.config.username)
        self.entry_user.pack(fill="x", pady=(0, 8))

        # Password
        self.lbl_conn_pwd = ttk.Label(parent, text=t("conn_pwd_label"), style="Card.TLabel")
        self.lbl_conn_pwd.pack(anchor="w", pady=(0, 2))
        self.entry_pwd = ttk.Entry(parent, font=("Segoe UI", 9), show="•")
        self.entry_pwd.insert(0, self.config.password)
        self.entry_pwd.pack(fill="x", pady=(0, 14))

        # Test Connection button & status indicator
        test_frame = tk.Frame(parent, bg="#FFFFFF")
        test_frame.pack(fill="x", pady=(0, 6))

        self.btn_test = ttk.Button(test_frame, text=t("conn_test_btn"), command=self._test_connection)
        self.btn_test.pack(side="left")

        self.lbl_test_status = tk.Label(
            test_frame,
            text="",
            font=("Segoe UI", 9, "bold"),
            fg="#5F6368",
            bg="#FFFFFF",
        )
        self.lbl_test_status.pack(side="left", padx=(14, 0), fill="x", expand=True, anchor="w")

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
        self.config.local_path = self.entry_local.get().strip()
        self.config.remote_path = self.entry_remote.get().strip()

        try:
            self.config.poll_interval = int(self.spin_poll.get())
        except Exception:
            pass

        try:
            self.config.file_retention_days = int(self.spin_file_retention.get())
        except Exception:
            pass

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

        self.config.notify_on_sync = self.var_notify.get()
        self.config.start_with_windows = self.var_autostart.get()
        if hasattr(self, "var_shortcut"):
            self.config.desktop_shortcut = self.var_shortcut.get()

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
            if self.client:
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
        self._read_form_into_config()
        self.config.save()

        # Update Windows autostart registry
        set_windows_autostart(self.var_autostart.get())

        # Update desktop shortcut
        if self.config.desktop_shortcut:
            create_desktop_shortcut(self.config.local_path)
        else:
            remove_desktop_shortcut()

        # Update client
        if self.client:
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
        self._read_form_into_config()
        self.config.save()

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

