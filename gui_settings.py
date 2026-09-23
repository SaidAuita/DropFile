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
from tkinter import filedialog, messagebox, simpledialog, ttk
import tkinter.font as tkfont
from typing import Any, Callable, Optional

from platform_utils import list_system_processes

from config import Config
from fb_client import FileBrowserClient
from i18n import SUPPORTED_LANGUAGES, get_current_language, set_current_language, t
from state_db import StateDatabase
from updater import apply_update, check_for_updates
from version import __version__, __build__, get_build_number, get_full_version
from win_utils import (
    create_desktop_shortcut,
    create_network_shortcut,
    get_available_drive_letters,
    is_windows_autostart_enabled,
    map_network_drive,
    open_folder_in_explorer,
    remove_desktop_shortcut,
    restart_dropfile,
    set_windows_autostart,
    get_default_lan_server_host,
    detect_lan_server_host,
)
from gui_speed_chart import SpeedChartWidget, SpeedMonitorCard, SpeedMonitorWindow
from urllib.parse import urlparse
import secrets

try:
    from dropsync_server import (
        __version__ as ds_version,
        __build__ as ds_build,
        control_service as ds_control_service,
        get_default_config_path as ds_get_default_config_path,
        get_service_status as ds_get_service_status,
        get_state_summary as ds_get_state_summary,
        load_dropsync_config as ds_load_config,
        save_dropsync_config as ds_save_config,
    )
except ImportError:
    ds_version = "1.0.0"
    ds_build = "88"
    ds_control_service = lambda action: (False, "DropSync server module not found")
    ds_get_default_config_path = lambda: Path.home() / ".dropsync" / "dropsync.json"
    ds_get_service_status = lambda: {
        "platform": sys.platform,
        "installed": False,
        "active": False,
        "status_label": "Not installed",
        "sub_text": "",
    }
    ds_get_state_summary = lambda p=None: {
        "active_files": 0,
        "trash_files": 0,
        "logs": [],
        "db_found": False,
    }
    ds_load_config = lambda p=None: {}
    ds_save_config = lambda d, p=None: False

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
    shows a vertical scrollbar only when content overflows visible height,
    and provides dynamic responsive text wrapping for registered widgets.
    """
    def __init__(self, parent, bg="#FFFFFF", padding=(18, 14)):
        super().__init__(parent, style="Card.TFrame")
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0, bg=bg)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.content = ttk.Frame(self.canvas, style="Card.TFrame", padding=padding)
        self._wrap_widgets: list[tuple[Any, int]] = []

        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self._win_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")

        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.content.bind("<Configure>", self._on_content_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Mouse wheel support
        self.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def register_autowrap(self, widget: Any, extra_pad: int = 0) -> None:
        """Registers a widget (Label/Checkbutton) to automatically adjust wraplength on canvas resize."""
        self._wrap_widgets.append((widget, extra_pad))
        try:
            cur_w = self.canvas.winfo_width()
            target_w = max(200, (cur_w if cur_w > 80 else 560) - 36 - extra_pad)
            widget.configure(wraplength=target_w)
        except Exception:
            pass

    def _on_content_configure(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._update_scrollbar()

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self._win_id, width=event.width)
        # Dynamically recalculate wraplength for all registered widgets
        usable_w = max(220, event.width - 36)
        for widget, extra_pad in self._wrap_widgets:
            try:
                if widget.winfo_exists():
                    target_w = max(180, usable_w - extra_pad)
                    widget.configure(wraplength=target_w)
            except Exception:
                pass
        self._update_scrollbar()

    def _update_scrollbar(self):
        req_h = self.content.winfo_reqheight()
        canv_h = self.canvas.winfo_height()
        if canv_h > 40 and req_h > canv_h + 10:
            if not self.scrollbar.winfo_ismapped():
                self.scrollbar.pack(side="right", fill="y", before=self.canvas)
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
        build_engine: Optional[Any] = None,
    ):
        self.config = config
        self.state_db = state_db
        self.client = client
        self.on_save_callback = on_save_callback
        self.on_restart_callback = on_restart_callback
        self.on_cleanup_callback = on_cleanup_callback
        self.engine = engine
        self.build_engine = build_engine
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
        if hasattr(self, "speed_card"):
            try:
                self.speed_card.stop()
            except Exception:
                pass
        if hasattr(self, "speed_card_ds"):
            try:
                self.speed_card_ds.stop()
            except Exception:
                pass
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

    def show(self, initial_tab: Optional[str] = None) -> None:
        with self._show_lock:
            if self._is_window_alive():
                try:
                    self.window.lift()
                    self.window.focus_force()
                    if initial_tab == "remote" and hasattr(self, "tab_remote"):
                        self.window.after(0, lambda: self.notebook.select(self.tab_remote))
                    elif initial_tab == "dropsync" and hasattr(self, "tab_dropsync"):
                        self.window.after(0, lambda: self.notebook.select(self.tab_dropsync))
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

        # Dimensions to fit all content cleanly across scaling factors
        self.window.geometry("680x700")
        self.window.minsize(580, 560)

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
        if ico_path.exists():
            if sys.platform.startswith("win"):
                try:
                    self.window.iconbitmap(str(ico_path))
                except Exception:
                    pass
            else:
                try:
                    from PIL import Image, ImageTk
                    img = Image.open(ico_path)
                    photo = ImageTk.PhotoImage(img)
                    self.window.iconphoto(True, photo)
                except Exception:
                    pass

        # Apply native visual style (aqua on macOS, vista/winnative on Windows, clam on Linux)
        style = ttk.Style()
        available_families = set(tkfont.families())
        if sys.platform == "darwin":
            theme_candidates = ("aqua", "clam")
            font_candidates = ("Helvetica Neue", "SF Pro Text", "Helvetica", "Arial")
        elif sys.platform.startswith("win"):
            theme_candidates = ("vista", "winnative", "clam")
            font_candidates = ("Segoe UI", "Tahoma", "Arial")
        else:
            theme_candidates = ("clam", "default")
            font_candidates = ("DejaVu Sans", "Ubuntu", "Noto Sans", "Liberation Sans", "FreeSans", "sans-serif")

        for theme_name in theme_candidates:
            if theme_name in style.theme_names():
                try:
                    style.theme_use(theme_name)
                    break
                except Exception:
                    pass

        font_family = next((f for f in font_candidates if f in available_families), "TkDefaultFont")
        self.font_family = font_family
        self.style = style

        # Color scheme
        bg_window = "#F3F3F3"
        bg_card = "#FFFFFF"
        fg_text = "#1C1C1C"
        fg_muted = "#5F6368"
        accent_blue = "#0067C0"

        self.window.configure(bg=bg_window)

        # Typography configuration
        style.configure("TNotebook", background=bg_window)
        style.configure("TNotebook.Tab", padding=[10, 5], font=(font_family, 9))
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

        # Dynamic Treeview row height calculation to avoid text overlap on Linux / custom DPI
        tree_font = tkfont.Font(family=font_family, size=9)
        tree_linespace = tree_font.metrics("linespace")
        self.tree_row_height = max(28, tree_linespace + 10)

        style.configure(
            "Treeview",
            font=(font_family, 9),
            rowheight=self.tree_row_height,
            background=bg_card,
            fieldbackground=bg_card,
            foreground=fg_text,
        )
        style.configure(
            "Treeview.Heading",
            font=(font_family, 9, "bold"),
            foreground="#202124",
            padding=[4, 4],
        )
        style.map(
            "Treeview",
            background=[("selected", accent_blue)],
            foreground=[("selected", "#FFFFFF")],
        )

        # --- Top Header Bar ---
        header_bar = tk.Frame(self.window, bg="#FFFFFF", padx=20, pady=10)
        header_bar.pack(fill="x", side="top")

        title_row = tk.Frame(header_bar, bg="#FFFFFF")
        title_row.pack(fill="x")

        self.lbl_app_title = tk.Label(
            title_row,
            text=t("app_name"),
            font=(self.font_family, 14, "bold"),
            fg="#1A1A1A",
            bg="#FFFFFF",
        )
        self.lbl_app_title.pack(side="left")

        # Version Pill Badge
        self.lbl_version_badge = tk.Label(
            title_row,
            text=f"v{__version__} (b{get_build_number()})",
            font=(self.font_family, 8, "bold"),
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

        # Speed Monitor Button
        self.btn_speed_monitor = ttk.Button(
            title_row,
            text=f"📈 {t('speed_monitor_btn')}",
            command=self._open_speed_monitor,
        )
        self.btn_speed_monitor.pack(side="right", padx=(0, 6))

        self.lbl_app_subtitle = tk.Label(
            header_bar,
            text=t("app_subtitle"),
            font=(self.font_family, 9),
            fg=fg_muted,
            bg="#FFFFFF",
            justify="left",
            wraplength=600,
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

        # Tab 5: DropSync Server (Scrollable)
        self.tab_dropsync = ScrollableTab(self.notebook, padding=(18, 14))
        self.notebook.add(self.tab_dropsync, text=t("tab_dropsync"))
        self._build_dropsync_tab(self.tab_dropsync.content)
        if initial_tab == "dropsync":
            try:
                self.notebook.select(self.tab_dropsync)
            except Exception:
                pass

        # Tab 6: Remote Control (Scrollable)
        self.tab_remote = ScrollableTab(self.notebook, padding=(18, 14))
        self.notebook.add(self.tab_remote, text=t("tab_remote"))
        self._build_remote_tab(self.tab_remote.content)
        if initial_tab == "remote":
            try:
                self.notebook.select(self.tab_remote)
            except Exception:
                pass


        # Center on screen while preserving dimensions
        self.window.update_idletasks()
        w = max(680, self.window.winfo_width())
        h = max(660, self.window.winfo_height())
        x = max(0, (self.window.winfo_screenwidth() // 2) - (w // 2))
        y = max(0, (self.window.winfo_screenheight() // 2) - (h // 2))
        self.window.geometry(f"{w}x{h}+{x}+{y}")

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

    def _open_speed_monitor(self) -> None:
        """Opens or focuses standalone floating Speed Monitor window."""
        SpeedMonitorWindow.show_or_focus(self.window if self._is_window_alive() else None, lang=self.config.language)

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
        if hasattr(self, "tab_dropsync"):
            self.notebook.tab(self.tab_dropsync, text=t("tab_dropsync"))
        if hasattr(self, "tab_remote"):
            self.notebook.tab(self.tab_remote, text=t("tab_remote"))

        self.btn_restart.config(text=f"🔄 {t('btn_save_restart')}")
        self.btn_save.config(text=t("btn_save_apply"))
        self.btn_cancel.config(text=t("btn_close"))
        if hasattr(self, "btn_check_update"):
            self.btn_check_update.config(text=f"🔍 {t('btn_check_updates')}")
        if hasattr(self, "btn_speed_monitor"):
            self.btn_speed_monitor.config(text=f"📈 {t('speed_monitor_btn')}")

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
        if hasattr(self, "lbl_folders_hdr"):
            self.lbl_folders_hdr.config(text=t("folders_header"))
        if hasattr(self, "lbl_folders_sub"):
            self.lbl_folders_sub.config(text=t("folders_sub"))

        # Card 1: Exchange
        if hasattr(self, "card_exchange"):
            self.card_exchange.config(text=f"  📁 {t('folders_exchange_header')}  ")
        if hasattr(self, "lbl_ex_desc"):
            self.lbl_ex_desc.config(text=t("folders_exchange_desc"))
        if hasattr(self, "lbl_ex_local"):
            self.lbl_ex_local.config(text=t("folders_local_label"))
        if hasattr(self, "btn_browse_exchange"):
            self.btn_browse_exchange.config(text=t("folders_browse_btn"))
        if hasattr(self, "btn_open_exchange"):
            self.btn_open_exchange.config(text=t("folders_open_exchange_btn"))
        if hasattr(self, "btn_shortcut_exchange"):
            self.btn_shortcut_exchange.config(text=t("folders_shortcut_exchange_btn"))
        if hasattr(self, "btn_autodetect_exchange"):
            self.btn_autodetect_exchange.config(text=t("folders_autodetect_exchange_btn"))
        if hasattr(self, "lbl_lan_title"):
            self.lbl_lan_title.config(text=f"🌐 {t('lan_path_exchange_label')} (SMB / Windows Share)")
        if hasattr(self, "btn_lan_detect"):
            self.btn_lan_detect.config(text=t("lan_detected_btn"))
        if hasattr(self, "btn_ex_lan_open"):
            self.btn_ex_lan_open.config(text=t("lan_btn_open"))
        if hasattr(self, "btn_ex_lan_mount"):
            self.btn_ex_lan_mount.config(text=t("lan_btn_mount"))
        if hasattr(self, "btn_ex_lan_shortcut"):
            self.btn_ex_lan_shortcut.config(text=t("lan_btn_shortcut"))
        if hasattr(self, "btn_ex_lan_copy"):
            self.btn_ex_lan_copy.config(text=t("lan_btn_copy"))
        if hasattr(self, "chk_build_sync"):
            self.chk_build_sync.config(text=t("folders_build_sync_chk"))
        if hasattr(self, "btn_build_sync_config"):
            self.btn_build_sync_config.config(text=t("folders_build_sync_btn"))

        # Card 2: Output
        if hasattr(self, "card_output"):
            self.card_output.config(text=f"  📤 {t('folders_output_header')}  ")
        if hasattr(self, "lbl_out_desc"):
            self.lbl_out_desc.config(text=t("folders_output_desc"))
        if hasattr(self, "lbl_out_local"):
            self.lbl_out_local.config(text=t("folders_local_label"))
        if hasattr(self, "btn_browse_output"):
            self.btn_browse_output.config(text=t("folders_browse_btn"))
        if hasattr(self, "btn_open_output"):
            self.btn_open_output.config(text=t("folders_open_output_btn"))
        if hasattr(self, "btn_shortcut_output"):
            self.btn_shortcut_output.config(text=t("folders_shortcut_output_btn"))
        if hasattr(self, "lbl_out_remote"):
            self.lbl_out_remote.config(text=t("folders_remote_label"))
        if hasattr(self, "lbl_out_remote_hint"):
            self.lbl_out_remote_hint.config(text=t("folders_remote_hint"))
        if hasattr(self, "chk_auto_copy_link"):
            self.chk_auto_copy_link.config(text=t("folders_auto_copy_link"))
        if hasattr(self, "btn_pull_missing"):
            self.btn_pull_missing.config(text=f"📥 {t('btn_pull_missing')}")
        if hasattr(self, "btn_full_sync"):
            self.btn_full_sync.config(text=f"🔄 {t('btn_full_sync')}")

        # Speed Cards
        for sc in (getattr(self, "speed_card", None), getattr(self, "speed_card_ds", None)):
            if sc is not None:
                sc.lang = self.config.language
                if hasattr(sc, "lbl_card_title"):
                    sc.lbl_card_title.config(text=f"📈 {t('speed_monitor_title')}")
                if hasattr(sc, "lbl_cur_rx_title"):
                    sc.lbl_cur_rx_title.config(text=t("speed_rx_label"))
                if hasattr(sc, "lbl_cur_tx_title"):
                    sc.lbl_cur_tx_title.config(text=t("speed_tx_label"))
                if hasattr(sc, "lbl_tot_rx_title"):
                    sc.lbl_tot_rx_title.config(text=t("speed_total_rx"))
                if hasattr(sc, "lbl_tot_tx_title"):
                    sc.lbl_tot_tx_title.config(text=t("speed_total_tx"))

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
        if hasattr(self, "lbl_exceptions_hdr"):
            self.lbl_exceptions_hdr.config(text=f"🚫 {t('settings_exceptions_header')}")
        if hasattr(self, "lbl_exceptions_sub"):
            self.lbl_exceptions_sub.config(text=t("settings_exceptions_sub"))
        if hasattr(self, "btn_add_ignore_folder"):
            self.btn_add_ignore_folder.config(text=t("settings_exceptions_add_folder"))
        if hasattr(self, "btn_reset_ignore"):
            self.btn_reset_ignore.config(text=t("settings_exceptions_reset"))
        self.lbl_ignore.config(text=t("settings_exceptions_hint"))
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

        # DropSync Tab
        if hasattr(self, "notebook") and hasattr(self, "tab_dropsync"):
            try:
                self.notebook.tab(self.tab_dropsync, text=t("tab_dropsync"))
            except Exception:
                pass
        if hasattr(self, "lbl_ds_hdr"):
            self.lbl_ds_hdr.config(text=t("dropsync_header"))
        if hasattr(self, "lbl_ds_sub"):
            self.lbl_ds_sub.config(text=t("dropsync_sub"))
        if hasattr(self, "card_ds_status"):
            self.card_ds_status.config(text=f"  ⚡ {t('dropsync_card_status')}  ")
        if hasattr(self, "card_ds_config"):
            self.card_ds_config.config(text=f"  ⚙ {t('dropsync_card_config')}  ")
        if hasattr(self, "card_ds_act"):
            self.card_ds_act.config(text=f"  📊 {t('dropsync_card_activity')}  ")
        if hasattr(self, "lbl_ds_node"):
            self.lbl_ds_node.config(text=t("dropsync_node_label"))
        if hasattr(self, "lbl_ds_role"):
            self.lbl_ds_role.config(text=t("dropsync_role_label"))
        if hasattr(self, "radio_ds_server"):
            self.radio_ds_server.config(text=t("dropsync_role_server"))
        if hasattr(self, "radio_ds_client"):
            self.radio_ds_client.config(text=t("dropsync_role_client"))
        if hasattr(self, "lbl_ds_folder"):
            self.lbl_ds_folder.config(text=t("dropsync_folder_label"))
        if hasattr(self, "lbl_ds_port"):
            self.lbl_ds_port.config(text=t("dropsync_port_label"))
        if hasattr(self, "lbl_ds_remote"):
            self.lbl_ds_remote.config(text=t("dropsync_remote_label"))
        if hasattr(self, "lbl_ds_token"):
            self.lbl_ds_token.config(text=t("dropsync_token_label"))
        if hasattr(self, "btn_ds_restart"):
            self.btn_ds_restart.config(text=t("dropsync_btn_restart"))
        if hasattr(self, "btn_ds_start"):
            self.btn_ds_start.config(text=t("dropsync_btn_start"))
        if hasattr(self, "btn_ds_stop"):
            self.btn_ds_stop.config(text=t("dropsync_btn_stop"))
        if hasattr(self, "btn_ds_save"):
            self.btn_ds_save.config(text=t("dropsync_btn_save"))
        if hasattr(self, "btn_ds_refresh"):
            self.btn_ds_refresh.config(text=t("dropsync_btn_refresh"))
        if hasattr(self, "btn_ds_open"):
            self.btn_ds_open.config(text=t("dropsync_btn_open_folder"))
        if hasattr(self, "lbl_ds_active_files"):
            cnt = getattr(self, "_last_ds_active_count", 0)
            self.lbl_ds_active_files.config(text=f"📄 {t('dropsync_active_files', lang=self.config.language)} {cnt}")
        if hasattr(self, "lbl_ds_trash_files"):
            cnt = getattr(self, "_last_ds_trash_count", 0)
            self.lbl_ds_trash_files.config(text=f"🗑 {t('dropsync_trash_files', lang=self.config.language)} {cnt}")
        if hasattr(self, "speed_card_ds") and self.speed_card_ds:
            self.speed_card_ds.update_language(self.config.language)
        if hasattr(self, "tree_ds_log"):
            self.tree_ds_log.heading("time", text=t("dropsync_log_col_time"))
            self.tree_ds_log.heading("action", text=t("dropsync_log_col_action"))
            self.tree_ds_log.heading("file", text=t("dropsync_log_col_file"))
            self.tree_ds_log.heading("size", text=t("dropsync_log_col_size"))
            self.tree_ds_log.heading("status", text=t("dropsync_log_col_status"))
        if hasattr(self, "_refresh_dropsync_status_and_stats"):
            self._refresh_dropsync_status_and_stats()

        # Remote Control Tab

        if hasattr(self, "lbl_rc_hdr"):
            self.lbl_rc_hdr.config(text=t("remote_header"))
        if hasattr(self, "lbl_rc_sub"):
            self.lbl_rc_sub.config(text=t("remote_sub"))
        if hasattr(self, "card1"):
            self.card1.config(text=f"  💻 {t('remote_receiver_card')}  ")
        if hasattr(self, "chk_rc_enabled"):
            self.chk_rc_enabled.config(text=t("remote_enable_chk"))
        if hasattr(self, "lbl_rc_name"):
            self.lbl_rc_name.config(text=t("remote_device_name_label"))
        if hasattr(self, "lbl_rc_pin_lbl"):
            self.lbl_rc_pin_lbl.config(text=t("remote_pin_label"))
        if hasattr(self, "lbl_rc_pin_val"):
            has_pin = bool(self.config.remote_control_pin)
            self.lbl_rc_pin_val.config(
                text="●●●●●●●● (OK)" if has_pin else f"●●●● ({t('remote_pin_not_set')})",
                bg="#EBF3FB" if has_pin else "#FDE8E8",
                fg="#0067C0" if has_pin else "#C81E1E",
            )
        if hasattr(self, "btn_set_pin"):
            self.btn_set_pin.config(text=f"🔑 {t('remote_btn_set_pin')}")
        if hasattr(self, "chk_rc_reboot"):
            self.chk_rc_reboot.config(text=f"🔄 {t('remote_allow_reboot_chk')}")
        if hasattr(self, "chk_rc_procs"):
            self.chk_rc_procs.config(text=f"📋 {t('remote_allow_procs_chk')}")
        if hasattr(self, "chk_rc_launch"):
            self.chk_rc_launch.config(text=f"🚀 {t('remote_allow_launch_chk')}")
        if hasattr(self, "lbl_rc_wl_hdr"):
            self.lbl_rc_wl_hdr.config(text=t("remote_whitelist_hdr"))
        if hasattr(self, "chk_rc_strict_wl"):
            self.chk_rc_strict_wl.config(text=t("remote_strict_whitelist_chk"))
        if hasattr(self, "btn_rc_add_app"):
            self.btn_rc_add_app.config(text=t("remote_btn_add_app"))
        if hasattr(self, "btn_rc_del_app"):
            self.btn_rc_del_app.config(text=t("remote_btn_del_app"))
        if hasattr(self, "btn_rc_from_running"):
            self.btn_rc_from_running.config(text=f"📋 {t('remote_btn_from_running')}")
        if hasattr(self, "lbl_rc_launch_hdr"):
            self.lbl_rc_launch_hdr.config(text=t("remote_launch_apps_hdr"))
        if hasattr(self, "tree_launch_apps"):
            self.tree_launch_apps.heading("name", text=t("remote_app_name_lbl"))
            self.tree_launch_apps.heading("path", text=t("remote_app_path_lbl"))
            self.tree_launch_apps.heading("args", text=t("remote_app_args_lbl"))
        if hasattr(self, "btn_rc_add_launch"):
            self.btn_rc_add_launch.config(text=t("remote_btn_add_launch_app"))
        if hasattr(self, "btn_rc_del_launch"):
            self.btn_rc_del_launch.config(text=t("remote_btn_del_launch_app"))
        if hasattr(self, "card2"):
            self.card2.config(text=f"  🚀 {t('remote_sender_card')}  ")
        if hasattr(self, "lbl_rc_target_lbl"):
            self.lbl_rc_target_lbl.config(text=t("remote_target_pc_label"))
        if hasattr(self, "btn_rc_refresh_devices"):
            self.btn_rc_refresh_devices.config(text=t("remote_devices_refresh"))
        if hasattr(self, "lbl_rc_act_lbl"):
            self.lbl_rc_act_lbl.config(text=t("remote_action_label"))
        if hasattr(self, "combo_rc_action"):
            cur_act_idx = self.combo_rc_action.current()
            self.rc_action_options = [
                t("remote_act_kill"),
                t("remote_act_reboot"),
                t("remote_act_list"),
                t("remote_act_launch"),
            ]
            self.combo_rc_action.config(values=self.rc_action_options)
            self.combo_rc_action.current(cur_act_idx if cur_act_idx >= 0 else 0)
        if hasattr(self, "lbl_rc_proc_lbl"):
            self.lbl_rc_proc_lbl.config(text=t("remote_process_name_label"))
        if hasattr(self, "lbl_rc_app_lbl"):
            self.lbl_rc_app_lbl.config(text=t("remote_target_app_label"))
        if hasattr(self, "lbl_rc_tpin_lbl"):
            self.lbl_rc_tpin_lbl.config(text=t("remote_target_pin_label"))
        if hasattr(self, "btn_send_rc_cmd"):
            self.btn_send_rc_cmd.config(text=f"🚀 {t('remote_btn_send_cmd')}")

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
            font=(self.font_family, 9, "bold"),
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
        self.entry_url = ttk.Entry(parent, font=(self.font_family, 9))
        self.entry_url.insert(0, self.config.server_url)
        self.entry_url.pack(fill="x", pady=(0, 6))

        # Server 1 Username
        self.lbl_conn_user = ttk.Label(parent, text=t("conn_user_label"), style="Card.TLabel")
        self.lbl_conn_user.pack(anchor="w", pady=(0, 2))
        self.entry_user = ttk.Entry(parent, font=(self.font_family, 9))
        self.entry_user.insert(0, self.config.username)
        self.entry_user.pack(fill="x", pady=(0, 6))

        # Server 1 Password
        self.lbl_conn_pwd = ttk.Label(parent, text=t("conn_pwd_label"), style="Card.TLabel")
        self.lbl_conn_pwd.pack(anchor="w", pady=(0, 2))
        pwd_frame1 = tk.Frame(parent, bg="#FFFFFF")
        pwd_frame1.pack(fill="x", pady=(0, 8))
        self.entry_pwd = ttk.Entry(pwd_frame1, font=(self.font_family, 9), show="•")
        self.entry_pwd.insert(0, self.config.password)
        self.entry_pwd.pack(side="left", fill="x", expand=True)
        self._pwd1_visible = False
        self.btn_toggle_pwd1 = ttk.Button(pwd_frame1, text="👁", width=3, command=self._toggle_pwd1_visibility)
        self.btn_toggle_pwd1.pack(side="right", padx=(6, 0))

        # Test Server 1 button & status indicator
        test_frame1 = tk.Frame(parent, bg="#FFFFFF")
        test_frame1.pack(fill="x", pady=(0, 10))

        self.btn_test = ttk.Button(test_frame1, text=t("conn_test_btn1"), command=self._test_connection)
        self.btn_test.pack(side="left")

        self.lbl_test_status = tk.Label(
            test_frame1,
            text="",
            font=(self.font_family, 9, "bold"),
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
        self.entry_backup_url = ttk.Entry(self.frame_server2_body, font=(self.font_family, 9))
        self.entry_backup_url.insert(0, self.config.backup_server_url)
        self.entry_backup_url.pack(fill="x", pady=(0, 6))

        # Server 2 Username
        self.lbl_backup_user = ttk.Label(self.frame_server2_body, text=t("conn_user_label"), style="Card.TLabel")
        self.lbl_backup_user.pack(anchor="w", pady=(0, 2))
        self.entry_backup_user = ttk.Entry(self.frame_server2_body, font=(self.font_family, 9))
        self.entry_backup_user.insert(0, self.config.backup_username)
        self.entry_backup_user.pack(fill="x", pady=(0, 6))

        # Server 2 Password
        self.lbl_backup_pwd = ttk.Label(self.frame_server2_body, text=t("conn_pwd_label"), style="Card.TLabel")
        self.lbl_backup_pwd.pack(anchor="w", pady=(0, 2))
        pwd_frame2 = tk.Frame(self.frame_server2_body, bg="#FFFFFF")
        pwd_frame2.pack(fill="x", pady=(0, 8))
        self.entry_backup_pwd = ttk.Entry(pwd_frame2, font=(self.font_family, 9), show="•")
        self.entry_backup_pwd.insert(0, self.config.backup_password)
        self.entry_backup_pwd.pack(side="left", fill="x", expand=True)
        self._pwd2_visible = False
        self.btn_toggle_pwd2 = ttk.Button(pwd_frame2, text="👁", width=3, command=self._toggle_pwd2_visibility)
        self.btn_toggle_pwd2.pack(side="right", padx=(6, 0))

        # Test Server 2 button & status indicator
        test_frame2 = tk.Frame(self.frame_server2_body, bg="#FFFFFF")
        test_frame2.pack(fill="x", pady=(0, 6))

        self.btn_test2 = ttk.Button(test_frame2, text=t("conn_test_btn2"), command=self._test_connection_2)
        self.btn_test2.pack(side="left")

        self.lbl_test_status2 = tk.Label(
            test_frame2,
            text="",
            font=(self.font_family, 9, "bold"),
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
            justify="left",
        )
        self.lbl_sync_backup_hint.pack(anchor="w", pady=(0, 4))
        self.tab_conn.register_autowrap(self.lbl_sync_backup_hint)

        # Warning callout banner
        self.frame_sync_warn = tk.Frame(self.frame_server2_body, bg="#FFF4CE", relief="solid", bd=1, padx=8, pady=6)
        self.frame_sync_warn.pack(fill="x", pady=(0, 8))
        self.lbl_sync_warn = tk.Label(
            self.frame_sync_warn,
            text=t("conn_sync_backup_warning"),
            font=(self.font_family, 8),
            bg="#FFF4CE",
            fg="#794B02",
            justify="left",
            anchor="w",
        )
        self.lbl_sync_warn.pack(fill="x")
        self.tab_conn.register_autowrap(self.lbl_sync_warn, extra_pad=24)

        # Status & Comparison Card
        self.frame_sync_status = tk.Frame(self.frame_server2_body, bg="#F8F9FA", relief="solid", bd=1, padx=10, pady=8)
        self.frame_sync_status.pack(fill="x", pady=(0, 6))

        # Title & Badge stacked vertically so neither is ever clipped
        self.lbl_sync_status_title = tk.Label(
            self.frame_sync_status,
            text=f"📊 {t('servers_sync_status_title')}:",
            font=(self.font_family, 9, "bold"),
            bg="#F8F9FA",
            fg="#202124",
            anchor="w",
        )
        self.lbl_sync_status_title.pack(fill="x", pady=(0, 2))

        self.lbl_sync_status_badge = tk.Label(
            self.frame_sync_status,
            text="...",
            font=(self.font_family, 9, "bold"),
            bg="#F8F9FA",
            fg="#0067C0",
            anchor="w",
            justify="left",
        )
        self.lbl_sync_status_badge.pack(fill="x", pady=(0, 4))
        self.tab_conn.register_autowrap(self.lbl_sync_status_badge, extra_pad=24)

        # Server 1 details line
        self.lbl_s1_detail = tk.Label(
            self.frame_sync_status,
            text="",
            font=(self.font_family, 8),
            bg="#F8F9FA",
            fg="#5F6368",
            anchor="w",
            justify="left",
        )
        self.lbl_s1_detail.pack(fill="x", pady=(1, 1))
        self.tab_conn.register_autowrap(self.lbl_s1_detail, extra_pad=24)

        # Server 2 details line
        self.lbl_s2_detail = tk.Label(
            self.frame_sync_status,
            text="",
            font=(self.font_family, 8),
            bg="#F8F9FA",
            fg="#5F6368",
            anchor="w",
            justify="left",
        )
        self.lbl_s2_detail.pack(fill="x", pady=(1, 1))
        self.tab_conn.register_autowrap(self.lbl_s2_detail, extra_pad=24)

        # Coordinator / Leader details line
        self.lbl_leader_detail = tk.Label(
            self.frame_sync_status,
            text="",
            font=(self.font_family, 8),
            bg="#F8F9FA",
            fg="#5F6368",
            anchor="w",
            justify="left",
        )
        self.lbl_leader_detail.pack(fill="x", pady=(1, 6))
        self.tab_conn.register_autowrap(self.lbl_leader_detail, extra_pad=24)

        # Action buttons
        btn_box = tk.Frame(self.frame_sync_status, bg="#F8F9FA")
        btn_box.pack(fill="x", pady=(0, 2))

        self.btn_check_servers = ttk.Button(
            btn_box,
            text=f"🔍 {t('servers_sync_btn_check')}",
            command=self._on_check_servers_status,
        )
        self.btn_check_servers.pack(side="left", padx=(0, 8))

        self.btn_sync_servers_now = ttk.Button(
            btn_box,
            text=f"⚡ {t('servers_sync_btn_sync')}",
            command=self._on_sync_servers_now,
        )
        self.btn_sync_servers_now.pack(side="left")

        # Action status label on its own sub-row below buttons to avoid cramming
        self.lbl_sync_action_status = tk.Label(
            self.frame_sync_status,
            text="",
            font=(self.font_family, 8, "italic"),
            bg="#F8F9FA",
            fg="#5F6368",
            anchor="w",
            justify="left",
        )
        self.lbl_sync_action_status.pack(fill="x", pady=(2, 0))
        self.tab_conn.register_autowrap(self.lbl_sync_action_status, extra_pad=24)

        self._on_backup_enable_toggle()

        # Initial status populate & check
        if getattr(self, "engine", None):
            cached = self.engine.get_last_servers_sync_status()
            if cached:
                self._update_servers_sync_ui(cached)
            else:
                self._update_servers_sync_ui({"enabled": self.config.backup_server_enabled, "state": "idle", "badge": "⚪ " + t("status_ready")})
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
        if hasattr(self, "btn_toggle_pwd2"):
            self.btn_toggle_pwd2.config(state=state)
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
        cur_lang = self.config.language
        s1 = st.get("server1", {})
        s2 = st.get("server2", {})
        cnt1 = s1.get("file_count", 0)
        cnt2 = s2.get("file_count", 0)

        if state == "synced":
            badge = t("servers_sync_synced", lang=cur_lang, count=cnt1)
        elif state == "server1_newer":
            badge = t("servers_sync_s1_newer", lang=cur_lang)
        elif state == "server2_newer":
            badge = t("servers_sync_s2_newer", lang=cur_lang)
        elif state == "diff_count":
            badge = t("servers_sync_diff_count", lang=cur_lang, c1=cnt1, c2=cnt2)
        elif state == "server1_offline":
            badge = "🔴 " + t("servers_sync_s1_offline", lang=cur_lang)
        elif state == "server2_offline":
            badge = "🔴 " + t("servers_sync_s2_offline", lang=cur_lang)
        elif state == "both_offline":
            badge = "🔴 " + t("servers_sync_both_offline", lang=cur_lang)
        elif state == "disabled":
            badge = "⚪ " + t("servers_sync_disabled", lang=cur_lang)
        else:
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

        if s1.get("online"):
            f1 = s1.get("latest_file", "")
            t1 = s1.get("latest_time_str", "")
            if cnt1 > 0 and f1:
                self.lbl_s1_detail.config(text=t("servers_sync_srv_info", lang=cur_lang, idx=1, count=cnt1, file=f1, time=t1))
            else:
                self.lbl_s1_detail.config(text=t("servers_sync_srv_none", lang=cur_lang, idx=1))
        elif s1.get("url"):
            self.lbl_s1_detail.config(text=t("servers_sync_srv_offline", lang=cur_lang, idx=1))
        else:
            self.lbl_s1_detail.config(text="")

        if s2.get("online"):
            f2 = s2.get("latest_file", "")
            t2 = s2.get("latest_time_str", "")
            if cnt2 > 0 and f2:
                self.lbl_s2_detail.config(text=t("servers_sync_srv_info", lang=cur_lang, idx=2, count=cnt2, file=f2, time=t2))
            else:
                self.lbl_s2_detail.config(text=t("servers_sync_srv_none", lang=cur_lang, idx=2))
        elif s2.get("url"):
            self.lbl_s2_detail.config(text=t("servers_sync_srv_offline", lang=cur_lang, idx=2))
        else:
            self.lbl_s2_detail.config(text="")

        if hasattr(self, "lbl_leader_detail"):
            leader = st.get("leader", {})
            if not self.config.sync_backup_server or not self.config.backup_server_enabled:
                self.lbl_leader_detail.config(text="")
            elif leader.get("is_self"):
                self.lbl_leader_detail.config(text=t("servers_sync_leader_self", lang=cur_lang), fg="#0F7B0F")
            elif leader.get("hostname") and time.time() <= float(leader.get("expires_at", 0)):
                self.lbl_leader_detail.config(text=t("servers_sync_leader_other", lang=cur_lang, host=leader.get("hostname")), fg="#5F6368")
            else:
                self.lbl_leader_detail.config(text=t("servers_sync_leader_none", lang=cur_lang), fg="#5F6368")

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

    def _toggle_pwd1_visibility(self) -> None:
        self._pwd1_visible = not getattr(self, "_pwd1_visible", False)
        self.entry_pwd.config(show="" if self._pwd1_visible else "•")
        self.btn_toggle_pwd1.config(text="🔒" if self._pwd1_visible else "👁")

    def _toggle_pwd2_visibility(self) -> None:
        self._pwd2_visible = not getattr(self, "_pwd2_visible", False)
        self.entry_backup_pwd.config(show="" if self._pwd2_visible else "•")
        self.btn_toggle_pwd2.config(text="🔒" if self._pwd2_visible else "👁")

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
            justify="left",
        )
        self.lbl_folders_sub.pack(anchor="w", pady=(0, 12))
        self.tab_folders.register_autowrap(self.lbl_folders_sub)

        # -------------------------------------------------------------
        # CARD 1: Exchange Folder (High-speed server sync via DropSync)
        # -------------------------------------------------------------
        self.card_exchange = tk.LabelFrame(
            parent,
            text=f"  📁 {t('folders_exchange_header')}  ",
            bg="#FFFFFF",
            padx=14,
            pady=10,
        )
        self.card_exchange.pack(fill="x", pady=(0, 14))

        self.lbl_ex_desc = ttk.Label(
            self.card_exchange,
            text=t("folders_exchange_desc"),
            style="Subheader.TLabel",
            justify="left",
        )
        self.lbl_ex_desc.pack(anchor="w", pady=(0, 8))
        self.tab_folders.register_autowrap(self.lbl_ex_desc)

        self.lbl_ex_local = ttk.Label(self.card_exchange, text=t("folders_local_label"), style="Card.TLabel")
        self.lbl_ex_local.pack(anchor="w", pady=(0, 2))

        ex_local_row = tk.Frame(self.card_exchange, bg="#FFFFFF")
        ex_local_row.pack(fill="x", pady=(0, 6))

        self.entry_exchange = ttk.Entry(ex_local_row, font=(self.font_family, 9))
        self.entry_exchange.insert(0, str(getattr(self.config, "exchange_path", self.config.local_path / "Exchange")))
        self.entry_exchange.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_browse_exchange = ttk.Button(
            ex_local_row,
            text=t("folders_browse_btn"),
            command=self._browse_exchange_folder,
        )
        self.btn_browse_exchange.pack(side="right")

        # Action buttons for Exchange folder
        ex_btns_row = tk.Frame(self.card_exchange, bg="#FFFFFF")
        ex_btns_row.pack(fill="x", pady=(0, 10))

        self.btn_open_exchange = ttk.Button(
            ex_btns_row,
            text=t("folders_open_exchange_btn"),
            command=lambda: open_folder_in_explorer(self.entry_exchange.get()),
        )
        self.btn_open_exchange.pack(side="left", padx=(0, 8))

        self.btn_shortcut_exchange = ttk.Button(
            ex_btns_row,
            text=t("folders_shortcut_exchange_btn"),
            command=self._create_exchange_shortcut,
        )
        self.btn_shortcut_exchange.pack(side="left")

        self.btn_autodetect_exchange = ttk.Button(
            ex_btns_row,
            text=t("folders_autodetect_exchange_btn"),
            command=self._autodetect_exchange_folder,
        )
        self.btn_autodetect_exchange.pack(side="left", padx=(8, 0))

        # LAN / SMB Access subsection
        ttk.Separator(self.card_exchange, orient="horizontal").pack(fill="x", pady=(6, 8))

        self.lbl_lan_title = ttk.Label(
            self.card_exchange,
            text=f"🌐 {t('lan_path_exchange_label')} (SMB / Windows Share)",
            style="Card.TLabel",
            font=(self.font_family, 9, "bold"),
        )
        self.lbl_lan_title.pack(anchor="w", pady=(0, 4))

        lan_server_row = tk.Frame(self.card_exchange, bg="#FFFFFF")
        lan_server_row.pack(fill="x", pady=(0, 6))

        initial_lan_host = self._get_initial_lan_host()
        self.entry_lan_server = ttk.Entry(lan_server_row, font=(self.font_family, 9))
        self.entry_lan_server.insert(0, initial_lan_host)
        self.entry_lan_server.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry_lan_server.bind("<KeyRelease>", lambda e: self._update_lan_paths())

        self.btn_lan_detect = ttk.Button(
            lan_server_row,
            text=t("lan_detected_btn"),
            command=self._on_lan_detect_click,
        )
        self.btn_lan_detect.pack(side="right")

        row_ex_path = tk.Frame(self.card_exchange, bg="#F1F5F9", padx=8, pady=5)
        row_ex_path.pack(fill="x", pady=(0, 6))

        self.lbl_unc_exchange = tk.Label(
            row_ex_path,
            text=f"\\\\{initial_lan_host}\\Exchange",
            bg="#F1F5F9",
            fg="#0F172A",
            font=("Consolas", 10),
            anchor="w",
        )
        self.lbl_unc_exchange.pack(side="left", fill="x", expand=True)

        row_ex_lan_btns = tk.Frame(self.card_exchange, bg="#FFFFFF")
        row_ex_lan_btns.pack(fill="x", pady=(0, 4))

        self.btn_ex_lan_open = ttk.Button(
            row_ex_lan_btns,
            text=t("lan_btn_open"),
            command=lambda: self._open_lan_folder("Exchange"),
        )
        self.btn_ex_lan_open.pack(side="left", padx=(0, 6))

        self.btn_ex_lan_mount = ttk.Button(
            row_ex_lan_btns,
            text=t("lan_btn_mount"),
            command=lambda: self._mount_lan_drive("Exchange"),
        )
        self.btn_ex_lan_mount.pack(side="left", padx=(0, 6))

        self.btn_ex_lan_shortcut = ttk.Button(
            row_ex_lan_btns,
            text=t("lan_btn_shortcut"),
            command=lambda: self._create_lan_shortcut("Exchange", "DropFile Exchange"),
        )
        self.btn_ex_lan_shortcut.pack(side="left", padx=(0, 6))

        self.btn_ex_lan_copy = ttk.Button(
            row_ex_lan_btns,
            text=t("lan_btn_copy"),
            command=lambda: self._copy_lan_path("Exchange"),
        )
        self.btn_ex_lan_copy.pack(side="left")

        self.lbl_lan_status = tk.Label(
            self.card_exchange,
            text="",
            bg="#FFFFFF",
            fg="#0F7B0F",
            font=(self.font_family, 8),
            anchor="w",
            justify="left",
        )
        self.lbl_lan_status.pack(fill="x", pady=(4, 0))
        self.tab_folders.register_autowrap(self.lbl_lan_status)

        # Build Drops Synchronization subsection
        ttk.Separator(self.card_exchange, orient="horizontal").pack(fill="x", pady=(10, 8))

        row_build_sync = tk.Frame(self.card_exchange, bg="#FFFFFF")
        row_build_sync.pack(fill="x", pady=(0, 2))

        self.var_build_sync = tk.BooleanVar(value=bool(getattr(self.config, "build_sync_enabled", False)))
        self.chk_build_sync = ttk.Checkbutton(
            row_build_sync,
            text=t("folders_build_sync_chk"),
            variable=self.var_build_sync,
            command=self._on_build_sync_chk_toggle,
        )
        self.chk_build_sync.pack(side="left", fill="x", expand=True)

        self.btn_build_sync_config = ttk.Button(
            row_build_sync,
            text=t("folders_build_sync_btn"),
            command=self._open_build_sync_dialog,
        )
        self.btn_build_sync_config.pack(side="right", padx=(8, 0))

        # -------------------------------------------------------------
        # CARD 2: Output Folder (Public Sharing via File Browser)
        # -------------------------------------------------------------
        self.card_output = tk.LabelFrame(
            parent,
            text=f"  📤 {t('folders_output_header')}  ",
            bg="#FFFFFF",
            padx=14,
            pady=10,
        )
        self.card_output.pack(fill="x", pady=(0, 14))

        self.lbl_out_desc = ttk.Label(
            self.card_output,
            text=t("folders_output_desc"),
            style="Subheader.TLabel",
            justify="left",
        )
        self.lbl_out_desc.pack(anchor="w", pady=(0, 8))
        self.tab_folders.register_autowrap(self.lbl_out_desc)

        self.lbl_out_local = ttk.Label(self.card_output, text=t("folders_local_label"), style="Card.TLabel")
        self.lbl_out_local.pack(anchor="w", pady=(0, 2))

        out_local_row = tk.Frame(self.card_output, bg="#FFFFFF")
        out_local_row.pack(fill="x", pady=(0, 6))

        self.entry_output = ttk.Entry(out_local_row, font=(self.font_family, 9))
        self.entry_output.insert(0, str(getattr(self.config, "output_path", self.config.local_path / "Output")))
        self.entry_output.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry_local = self.entry_output  # Backwards compatibility alias

        self.btn_browse_output = ttk.Button(
            out_local_row,
            text=t("folders_browse_btn"),
            command=self._browse_output_folder,
        )
        self.btn_browse_output.pack(side="right")

        out_btns_row = tk.Frame(self.card_output, bg="#FFFFFF")
        out_btns_row.pack(fill="x", pady=(0, 8))

        self.btn_open_output = ttk.Button(
            out_btns_row,
            text=t("folders_open_output_btn"),
            command=lambda: open_folder_in_explorer(self.entry_output.get()),
        )
        self.btn_open_output.pack(side="left", padx=(0, 8))

        self.btn_shortcut_output = ttk.Button(
            out_btns_row,
            text=t("folders_shortcut_output_btn"),
            command=self._create_output_shortcut,
        )
        self.btn_shortcut_output.pack(side="left")

        # Remote Path in File Browser
        self.lbl_out_remote = ttk.Label(self.card_output, text=t("folders_remote_label"), style="Card.TLabel")
        self.lbl_out_remote.pack(anchor="w", pady=(8, 2))

        self.entry_output_remote = ttk.Entry(self.card_output, font=(self.font_family, 9))
        self.entry_output_remote.insert(0, getattr(self.config, "output_remote_path", "/Output"))
        self.entry_output_remote.pack(fill="x", pady=(0, 4))
        self.entry_remote = self.entry_output_remote  # Backwards compatibility alias

        self.lbl_out_remote_hint = ttk.Label(
            self.card_output,
            text=t("folders_remote_hint"),
            style="Subheader.TLabel",
            justify="left",
        )
        self.lbl_out_remote_hint.pack(anchor="w", pady=(0, 8))
        self.tab_folders.register_autowrap(self.lbl_out_remote_hint)

        # Auto-copy link checkbox
        self.var_auto_copy_link = tk.BooleanVar(value=bool(getattr(self.config, "auto_copy_share_link", True)))
        self.chk_auto_copy_link = ttk.Checkbutton(
            self.card_output,
            text=t("folders_auto_copy_link"),
            variable=self.var_auto_copy_link,
        )
        self.chk_auto_copy_link.pack(anchor="w", pady=(2, 8))

        # Sync helpers for Output folder
        out_sync_row = tk.Frame(self.card_output, bg="#FFFFFF")
        out_sync_row.pack(fill="x", pady=(2, 4))

        self.btn_pull_missing = ttk.Button(
            out_sync_row,
            text=f"📥 {t('btn_pull_missing')}",
            command=self._pull_missing_files_ui,
        )
        self.btn_pull_missing.pack(side="left", padx=(0, 8))

        self.btn_full_sync = ttk.Button(
            out_sync_row,
            text=f"🔄 {t('btn_full_sync')}",
            command=self._full_sync_ui,
        )
        self.btn_full_sync.pack(side="left")

        self.lbl_sync_status = tk.Label(
            self.card_output,
            text="",
            font=(self.font_family, 9),
            bg="#FFFFFF",
            anchor="w",
            justify="left",
        )
        self.lbl_sync_status.pack(fill="x", pady=(4, 0))
        self.tab_folders.register_autowrap(self.lbl_sync_status)

        # -------------------------------------------------------------
        # CARD 3: Speed Monitor
        # -------------------------------------------------------------
        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(4, 12))
        self.speed_card = SpeedMonitorCard(parent, lang=self.config.language, bg="#FFFFFF", auto_start=True)
        self.speed_card.pack(fill="x", pady=(0, 10))

    def _get_initial_lan_host(self) -> str:
        saved = getattr(self.config, "lan_server_host", "").strip()
        return get_default_lan_server_host(saved)

    def _update_lan_paths(self) -> None:
        host = self.entry_lan_server.get().strip() if hasattr(self, "entry_lan_server") else ""
        if not host:
            host = "SERVER"
        if hasattr(self, "lbl_unc_dropsync"):
            self.lbl_unc_dropsync.config(text=f"\\\\{host}\\DropSync")
        if hasattr(self, "lbl_unc_exchange"):
            self.lbl_unc_exchange.config(text=f"\\\\{host}\\Exchange")

    def _on_lan_detect_click(self) -> None:
        if hasattr(self, "lbl_lan_status"):
            self.lbl_lan_status.config(text="🔍 Searching for server in local network...", fg="#0067C0")
        def worker():
            detected = self._detect_lan_server()
            if self._is_window_alive():
                def apply_detected():
                    if hasattr(self, "entry_lan_server"):
                        self.entry_lan_server.delete(0, "end")
                        self.entry_lan_server.insert(0, detected)
                    self.config.lan_server_host = detected
                    try:
                        self.config.save()
                    except Exception:
                        pass
                    self._update_lan_paths()
                    if hasattr(self, "lbl_lan_status"):
                        self.lbl_lan_status.config(text=f"✅ Server found: {detected}", fg="#0F7B0F")
                self.window.after(0, apply_detected)
        threading.Thread(target=worker, daemon=True).start()

    def _detect_lan_server(self) -> str:
        extra_candidates = []
        for url_str in [getattr(self.config, "server_url", ""), getattr(self.config, "backup_server_url", "")]:
            if url_str:
                try:
                    h = urlparse(url_str).hostname
                    if h and h not in ("localhost", "127.0.0.1") and h not in extra_candidates:
                        extra_candidates.append(h)
                except Exception:
                    pass
        saved = getattr(self.config, "lan_server_host", "").strip()
        return detect_lan_server_host(saved_host=saved, extra_candidates=extra_candidates)

    def _get_unc_path(self, share_name: str) -> str:
        host = self.entry_lan_server.get().strip() if hasattr(self, "entry_lan_server") else ""
        if not host:
            host = self._get_initial_lan_host()
        return f"\\\\{host}\\{share_name}"

    def _open_lan_folder(self, share_name: str) -> None:
        unc = self._get_unc_path(share_name)
        open_folder_in_explorer(unc)
        if hasattr(self, "lbl_lan_status"):
            self.lbl_lan_status.config(text=f"📂 {unc}", fg="#0067C0")

    def _mount_lan_drive(self, share_name: str) -> None:
        unc = self._get_unc_path(share_name)
        ok, msg = map_network_drive(unc)
        if ok:
            if hasattr(self, "lbl_lan_status"):
                self.lbl_lan_status.config(text=f"✅ {msg}", fg="#0F7B0F")
            try:
                messagebox.showinfo(t("lan_mount_success_title"), msg)
            except Exception:
                pass
        else:
            if hasattr(self, "lbl_lan_status"):
                self.lbl_lan_status.config(text=f"⚠️ {msg}", fg="#D97706")
            try:
                messagebox.showwarning(t("lan_mount_fail_title"), msg)
            except Exception:
                pass

    def _create_lan_shortcut(self, share_name: str, friendly_name: str) -> None:
        unc = self._get_unc_path(share_name)
        ok, msg = create_network_shortcut(unc, friendly_name)
        if ok:
            if hasattr(self, "lbl_lan_status"):
                self.lbl_lan_status.config(text=f"✅ {t('lan_shortcut_created', name=friendly_name)}", fg="#0F7B0F")
            try:
                messagebox.showinfo("DropFile", t("lan_shortcut_created", name=friendly_name))
            except Exception:
                pass
        else:
            if hasattr(self, "lbl_lan_status"):
                self.lbl_lan_status.config(text=f"⚠️ {msg}", fg="#D97706")

    def _copy_lan_path(self, share_name: str) -> None:
        unc = self._get_unc_path(share_name)
        try:
            self.window.clipboard_clear()
            self.window.clipboard_append(unc)
            if hasattr(self, "lbl_lan_status"):
                self.lbl_lan_status.config(text=f"📋 {t('lan_path_copied')} ({unc})", fg="#0067C0")
        except Exception as e:
            if hasattr(self, "lbl_lan_status"):
                self.lbl_lan_status.config(text=f"⚠️ {e}", fg="#D97706")

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

    def _browse_exchange_folder(self) -> None:
        init_dir = self.entry_exchange.get() if hasattr(self, "entry_exchange") else ""
        chosen = filedialog.askdirectory(initialdir=init_dir)
        if chosen and hasattr(self, "entry_exchange"):
            self.entry_exchange.delete(0, tk.END)
            self.entry_exchange.insert(0, chosen)

    def _create_exchange_shortcut(self) -> None:
        path = self.entry_exchange.get().strip() if hasattr(self, "entry_exchange") else ""
        if not path:
            return
        Path(path).mkdir(parents=True, exist_ok=True)
        ok = create_desktop_shortcut(path, shortcut_name="Exchange", force=True)
        if ok:
            messagebox.showinfo(
                t("shortcut_success_title"),
                t("shortcut_success_msg", path=path),
                parent=self.window,
            )
        else:
            messagebox.showerror(t("shortcut_fail_title"), t("shortcut_fail_msg"), parent=self.window)

    def _autodetect_exchange_folder(self) -> None:
        from config import find_server_exchange_path, ensure_server_exchange_symlink
        found = find_server_exchange_path()
        if found:
            self.entry_exchange.delete(0, tk.END)
            self.entry_exchange.insert(0, str(found))
            self.config.exchange_path = found
            self.config.save()
            if sys.platform.startswith("linux"):
                ensure_server_exchange_symlink(found)
            messagebox.showinfo(
                t("folders_autodetect_title"),
                t("folders_autodetect_success", path=str(found)),
                parent=self.window,
            )
        else:
            messagebox.showwarning(
                t("folders_autodetect_title"),
                t("folders_autodetect_not_found"),
                parent=self.window,
            )

    def _on_build_sync_chk_toggle(self) -> None:
        self.config.build_sync_enabled = self.var_build_sync.get()
        self.config.save()
        if hasattr(self, "build_engine") and self.build_engine:
            self.build_engine.reload_tasks()

    def _open_build_sync_dialog(self) -> None:
        try:
            from gui_build_sync import BuildSyncDialog
            BuildSyncDialog.show_or_focus(
                parent=self.window if self._is_window_alive() else None,
                config=self.config,
                on_save_callback=self._on_build_sync_dialog_save,
                build_engine=getattr(self, "build_engine", None),
            )
        except Exception as e:
            messagebox.showerror(t("error_title"), f"Error opening build sync dialog: {e}", parent=self.window)

    def _on_build_sync_dialog_save(self) -> None:
        if hasattr(self, "var_build_sync"):
            self.var_build_sync.set(bool(self.config.build_sync_enabled))

    def _browse_output_folder(self) -> None:
        init_dir = self.entry_output.get() if hasattr(self, "entry_output") else ""
        chosen = filedialog.askdirectory(initialdir=init_dir)
        if chosen and hasattr(self, "entry_output"):
            self.entry_output.delete(0, tk.END)
            self.entry_output.insert(0, chosen)

    def _create_output_shortcut(self) -> None:
        path = self.entry_output.get().strip() if hasattr(self, "entry_output") else ""
        if not path:
            return
        Path(path).mkdir(parents=True, exist_ok=True)
        ok = create_desktop_shortcut(path, shortcut_name="Output", force=True)
        if ok:
            messagebox.showinfo(
                t("shortcut_success_title"),
                t("shortcut_success_msg", path=path),
                parent=self.window,
            )
        else:
            messagebox.showerror(t("shortcut_fail_title"), t("shortcut_fail_msg"), parent=self.window)

    def _browse_local_folder(self) -> None:
        self._browse_output_folder()

    def _create_shortcut(self) -> None:
        self._create_output_shortcut()

    def _build_settings_tab(self, parent: ttk.Frame) -> None:
        self.lbl_settings_hdr = ttk.Label(parent, text=t("settings_header"), style="Header.TLabel")
        self.lbl_settings_hdr.pack(anchor="w", pady=(0, 8))

        # 1. Poll interval
        poll_row = tk.Frame(parent, bg="#FFFFFF")
        poll_row.pack(fill="x", pady=(0, 5))
        self.lbl_poll = ttk.Label(poll_row, text=t("settings_poll_label"), style="Card.TLabel")
        self.lbl_poll.pack(side="left", padx=(0, 8))

        self.spin_poll = ttk.Spinbox(poll_row, from_=5, to=3600, width=6, font=(self.font_family, 9))
        self.spin_poll.set(self.config.poll_interval)
        self.spin_poll.pack(side="left")

        # 2. File retention (Auto-cleanup of old files)
        file_ret_row = tk.Frame(parent, bg="#FFFFFF")
        file_ret_row.pack(fill="x", pady=(0, 2))
        self.lbl_file_ret = ttk.Label(file_ret_row, text=t("settings_file_ret_label"), style="Card.TLabel")
        self.lbl_file_ret.pack(side="left", padx=(0, 8))

        self.spin_file_retention = ttk.Spinbox(
            file_ret_row, from_=0, to=365, width=5, font=(self.font_family, 9)
        )
        self.spin_file_retention.set(self.config.file_retention_days)
        self.spin_file_retention.pack(side="left", padx=(0, 6))

        self.lbl_file_ret_hint = ttk.Label(file_ret_row, text=t("settings_disabled_hint"), style="Subheader.TLabel")
        self.lbl_file_ret_hint.pack(side="left")

        # Cleanup action button on its own row so it is never clipped
        file_clean_row = tk.Frame(parent, bg="#FFFFFF")
        file_clean_row.pack(fill="x", pady=(2, 6))
        self.btn_clean_now = ttk.Button(
            file_clean_row, text=t("settings_clean_now_btn"), command=self._trigger_file_cleanup_now
        )
        self.btn_clean_now.pack(side="left")

        # 3. History log retention
        log_ret_row = tk.Frame(parent, bg="#FFFFFF")
        log_ret_row.pack(fill="x", pady=(0, 5))
        self.lbl_log_ret = ttk.Label(log_ret_row, text=t("settings_log_ret_label"), style="Card.TLabel")
        self.lbl_log_ret.pack(side="left", padx=(0, 8))

        self.spin_retention = ttk.Spinbox(log_ret_row, from_=0, to=365, width=5, font=(self.font_family, 9))
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
            font=(self.font_family, 9),
        )
        self.combo_conflict.current(1 if self.config.conflict_action == "newer_wins" else 0)
        self.combo_conflict.pack(side="left", fill="x", expand=True)

        # 4b. Deduplication button and description (description on row below with autowrap)
        dedup_row = tk.Frame(parent, bg="#FFFFFF")
        dedup_row.pack(fill="x", pady=(2, 2))
        self.btn_dedup_now = ttk.Button(
            dedup_row, text=t("settings_dedup_btn"), command=self._trigger_dedup_now
        )
        self.btn_dedup_now.pack(side="left")

        self.lbl_dedup_hint = ttk.Label(
            parent, text=t("settings_dedup_hint"), style="Subheader.TLabel", justify="left"
        )
        self.lbl_dedup_hint.pack(fill="x", pady=(0, 6))
        self.tab_settings.register_autowrap(self.lbl_dedup_hint)

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
            font=(self.font_family, 9),
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
            font=(self.font_family, 8, "italic"),
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

        # --- Exceptions & Ignored Items Section ---
        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(6, 8))
        self.lbl_exceptions_hdr = ttk.Label(
            parent, text=f"🚫 {t('settings_exceptions_header')}", style="Header.TLabel"
        )
        self.lbl_exceptions_hdr.pack(anchor="w", pady=(0, 2))

        self.lbl_exceptions_sub = ttk.Label(
            parent,
            text=t("settings_exceptions_sub"),
            style="Subheader.TLabel",
            justify="left",
        )
        self.lbl_exceptions_sub.pack(anchor="w", pady=(0, 6))
        self.tab_settings.register_autowrap(self.lbl_exceptions_sub)

        self.lbl_ignore = ttk.Label(parent, text=t("settings_exceptions_hint"), style="Card.TLabel")
        self.lbl_ignore.pack(anchor="w", pady=(0, 2))
        self.tab_settings.register_autowrap(self.lbl_ignore)

        self.entry_ignore = ttk.Entry(parent, font=(self.font_family, 9))
        self.entry_ignore.insert(0, ", ".join(self.config.ignore_patterns))
        self.entry_ignore.pack(fill="x", pady=(0, 6))

        exceptions_btn_row = tk.Frame(parent, bg="#FFFFFF")
        exceptions_btn_row.pack(fill="x", pady=(0, 8))

        self.btn_add_ignore_folder = ttk.Button(
            exceptions_btn_row,
            text=t("settings_exceptions_add_folder"),
            command=self._add_folder_to_ignore,
        )
        self.btn_add_ignore_folder.pack(side="left", padx=(0, 8))

        self.btn_reset_ignore = ttk.Button(
            exceptions_btn_row,
            text=t("settings_exceptions_reset"),
            command=self._reset_ignore_patterns_ui,
        )
        self.btn_reset_ignore.pack(side="left")


        # Backup / Restore settings section
        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(4, 8))
        self.lbl_backup_hdr = ttk.Label(parent, text=t("settings_backup_header"), style="Header.TLabel")
        self.lbl_backup_hdr.pack(anchor="w", pady=(0, 2))

        self.lbl_backup_sub = ttk.Label(
            parent,
            text=t("settings_backup_sub"),
            style="Subheader.TLabel",
            justify="left",
        )
        self.lbl_backup_sub.pack(anchor="w", pady=(0, 6))
        self.tab_settings.register_autowrap(self.lbl_backup_sub)

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

    def _add_folder_to_ignore(self) -> None:
        """Opens folder dialog to pick a folder to add to exceptions."""
        base_dir = self.config.local_path
        chosen = filedialog.askdirectory(initialdir=str(base_dir), parent=self.window)
        if chosen:
            chosen_path = Path(chosen)
            try:
                rel = chosen_path.relative_to(base_dir)
                pattern = f"{rel.as_posix()}*"
            except ValueError:
                pattern = f"{chosen_path.name}*"

            current = [p.strip() for p in self.entry_ignore.get().split(",") if p.strip()]
            if pattern not in current:
                current.append(pattern)
                self.entry_ignore.delete(0, tk.END)
                self.entry_ignore.insert(0, ", ".join(current))

    def _reset_ignore_patterns_ui(self) -> None:
        """Resets ignore patterns entry to factory defaults."""
        defaults = self.config.reset_ignore_patterns()
        self.entry_ignore.delete(0, tk.END)
        self.entry_ignore.insert(0, ", ".join(defaults))

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

    # -------------------------------------------------------------------------
    # TAB 5: DropSync Server (High-Speed Linux Sync)
    # -------------------------------------------------------------------------
    def _build_dropsync_tab(self, parent: ttk.Frame) -> None:
        self.lbl_ds_hdr = ttk.Label(parent, text=t("dropsync_header"), style="Header.TLabel")
        self.lbl_ds_hdr.pack(anchor="w", pady=(0, 2))

        self.lbl_ds_sub = ttk.Label(parent, text=t("dropsync_sub"), style="Subheader.TLabel", justify="left")
        self.lbl_ds_sub.pack(anchor="w", pady=(0, 12))
        self.tab_dropsync.register_autowrap(self.lbl_ds_sub)

        # --- Card 1: Daemon Service & Build Info ---
        self.card_ds_status = tk.LabelFrame(
            parent,
            text=f"  ⚡ {t('dropsync_card_status')}  ",
            bg="#FFFFFF",
            padx=14,
            pady=10,
        )
        self.card_ds_status.pack(fill="x", pady=(0, 14))

        # Row 1: Build & Version Badge + Service Status Badge + Refresh Button
        row_svc_top = tk.Frame(self.card_ds_status, bg="#FFFFFF")
        row_svc_top.pack(fill="x", pady=(0, 6))

        self.lbl_ds_build_badge = tk.Label(
            row_svc_top,
            text=f"📦 DropSync v{ds_version} (build {ds_build})",
            bg="#EBF3FB",
            fg="#0067C0",
            padx=8,
            pady=3,
            font=(self.font_family, 9, "bold"),
        )
        self.lbl_ds_build_badge.pack(side="left", padx=(0, 8))

        self.lbl_ds_status_badge = tk.Label(
            row_svc_top,
            text="⏳ Checking...",
            bg="#F3F3F3",
            fg="#605E5C",
            padx=8,
            pady=3,
            font=(self.font_family, 9, "bold"),
        )
        self.lbl_ds_status_badge.pack(side="left", padx=(0, 8))

        self.btn_ds_refresh = ttk.Button(
            row_svc_top,
            text=t("dropsync_btn_refresh"),
            command=self._refresh_dropsync_status_and_stats,
        )
        self.btn_ds_refresh.pack(side="right")

        # Row 2: Sub-detail text (systemd info or standalone)
        self.lbl_ds_sub_detail = tk.Label(
            self.card_ds_status,
            text="",
            bg="#FFFFFF",
            fg="#605E5C",
            font=(self.font_family, 8),
            anchor="w",
        )
        self.lbl_ds_sub_detail.pack(fill="x", pady=(0, 6))

        # Row 3: Action Buttons (Restart, Start, Stop)
        row_svc_btns = tk.Frame(self.card_ds_status, bg="#FFFFFF")
        row_svc_btns.pack(fill="x", pady=(0, 2))

        self.btn_ds_restart = ttk.Button(
            row_svc_btns,
            text=t("dropsync_btn_restart"),
            command=lambda: self._action_dropsync_service("restart"),
        )
        self.btn_ds_restart.pack(side="left", padx=(0, 6))

        self.btn_ds_start = ttk.Button(
            row_svc_btns,
            text=t("dropsync_btn_start"),
            command=lambda: self._action_dropsync_service("start"),
        )
        self.btn_ds_start.pack(side="left", padx=(0, 6))

        self.btn_ds_stop = ttk.Button(
            row_svc_btns,
            text=t("dropsync_btn_stop"),
            command=lambda: self._action_dropsync_service("stop"),
        )
        self.btn_ds_stop.pack(side="left", padx=(0, 6))

        self.lbl_ds_action_msg = tk.Label(
            row_svc_btns,
            text="",
            bg="#FFFFFF",
            fg="#0F7B0F",
            font=(self.font_family, 8),
        )
        self.lbl_ds_action_msg.pack(side="left", padx=(8, 0))

        # --- Card 2: Configuration ---
        self.card_ds_config = tk.LabelFrame(
            parent,
            text=f"  ⚙ {t('dropsync_card_config')}  ",
            bg="#FFFFFF",
            padx=14,
            pady=10,
        )
        self.card_ds_config.pack(fill="x", pady=(0, 14))

        # Node Name
        row_node = tk.Frame(self.card_ds_config, bg="#FFFFFF")
        row_node.pack(fill="x", pady=(0, 8))
        self.lbl_ds_node = ttk.Label(row_node, text=t("dropsync_node_label"), style="Card.TLabel", width=28)
        self.lbl_ds_node.pack(side="left")
        self.entry_ds_node = ttk.Entry(row_node)
        self.entry_ds_node.pack(side="left", fill="x", expand=True)

        # Role Radiobuttons
        row_role = tk.Frame(self.card_ds_config, bg="#FFFFFF")
        row_role.pack(fill="x", pady=(0, 8))
        self.lbl_ds_role = ttk.Label(row_role, text=t("dropsync_role_label"), style="Card.TLabel", width=28)
        self.lbl_ds_role.pack(side="left")

        self.var_ds_role = tk.StringVar(value="server")
        self.radio_ds_server = ttk.Radiobutton(
            row_role,
            text=t("dropsync_role_server"),
            variable=self.var_ds_role,
            value="server",
            command=self._on_ds_role_changed,
        )
        self.radio_ds_server.pack(side="left", padx=(0, 14))

        self.radio_ds_client = ttk.Radiobutton(
            row_role,
            text=t("dropsync_role_client"),
            variable=self.var_ds_role,
            value="client",
            command=self._on_ds_role_changed,
        )
        self.radio_ds_client.pack(side="left")

        # Sync Folder
        row_folder = tk.Frame(self.card_ds_config, bg="#FFFFFF")
        row_folder.pack(fill="x", pady=(0, 8))
        self.lbl_ds_folder = ttk.Label(row_folder, text=t("dropsync_folder_label"), style="Card.TLabel", width=28)
        self.lbl_ds_folder.pack(side="left")
        self.entry_ds_folder = ttk.Entry(row_folder)
        self.entry_ds_folder.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.btn_ds_browse_folder = ttk.Button(row_folder, text="📂 ...", width=5, command=self._browse_ds_folder)
        self.btn_ds_browse_folder.pack(side="right")

        # Role-specific container frame (swapped between port and remote url)
        self.frame_role_options = tk.Frame(self.card_ds_config, bg="#FFFFFF")
        self.frame_role_options.pack(fill="x", pady=(0, 8))

        # Port row (Server mode)
        self.row_ds_port = tk.Frame(self.frame_role_options, bg="#FFFFFF")
        self.lbl_ds_port = ttk.Label(self.row_ds_port, text=t("dropsync_port_label"), style="Card.TLabel", width=28)
        self.lbl_ds_port.pack(side="left")
        self.entry_ds_port = ttk.Entry(self.row_ds_port, width=12)
        self.entry_ds_port.pack(side="left")

        # Remote URL row (Client mode)
        self.row_ds_remote = tk.Frame(self.frame_role_options, bg="#FFFFFF")
        self.lbl_ds_remote = ttk.Label(self.row_ds_remote, text=t("dropsync_remote_label"), style="Card.TLabel", width=28)
        self.lbl_ds_remote.pack(side="left")
        self.entry_ds_remote = ttk.Entry(self.row_ds_remote)
        self.entry_ds_remote.pack(side="left", fill="x", expand=True)

        # Auth Token row
        row_token = tk.Frame(self.card_ds_config, bg="#FFFFFF")
        row_token.pack(fill="x", pady=(0, 10))
        self.lbl_ds_token = ttk.Label(row_token, text=t("dropsync_token_label"), style="Card.TLabel", width=28)
        self.lbl_ds_token.pack(side="left")
        self.entry_ds_token = ttk.Entry(row_token, show="•")
        self.entry_ds_token.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_ds_token_eye = ttk.Button(
            row_token,
            text="👁",
            width=3,
            command=self._toggle_ds_token_visibility,
        )
        self.btn_ds_token_eye.pack(side="left", padx=(0, 4))

        self.btn_ds_token_copy = ttk.Button(
            row_token,
            text="📋",
            width=3,
            command=self._copy_ds_token,
        )
        self.btn_ds_token_copy.pack(side="left", padx=(0, 4))

        self.btn_ds_token_gen = ttk.Button(
            row_token,
            text="🎲",
            width=3,
            command=self._generate_ds_token,
        )
        self.btn_ds_token_gen.pack(side="left")

        # Save Button row
        row_save = tk.Frame(self.card_ds_config, bg="#FFFFFF")
        row_save.pack(fill="x", pady=(4, 0))

        self.btn_ds_save = ttk.Button(
            row_save,
            text=t("dropsync_btn_save"),
            style="Accent.TButton",
            command=self._save_dropsync_settings,
        )
        self.btn_ds_save.pack(side="left", padx=(0, 12))

        self.lbl_ds_save_status = tk.Label(
            row_save,
            text="",
            bg="#FFFFFF",
            fg="#0F7B0F",
            font=(self.font_family, 8),
        )
        self.lbl_ds_save_status.pack(side="left")

        # --- Card 3: Sync Activity & State ---
        self.card_ds_act = tk.LabelFrame(
            parent,
            text=f"  📊 {t('dropsync_card_activity')}  ",
            bg="#FFFFFF",
            padx=14,
            pady=10,
        )
        self.card_ds_act.pack(fill="both", expand=True, pady=(0, 6))

        # Metrics row
        row_metrics = tk.Frame(self.card_ds_act, bg="#FFFFFF")
        row_metrics.pack(fill="x", pady=(0, 8))

        self.lbl_ds_active_files = tk.Label(
            row_metrics,
            text=f"📄 {t('dropsync_active_files', lang=self.config.language)} 0",
            bg="#EBF3FB",
            fg="#0067C0",
            padx=10,
            pady=4,
            font=(self.font_family, 9, "bold"),
        )
        self.lbl_ds_active_files.pack(side="left", padx=(0, 10))

        self.lbl_ds_trash_files = tk.Label(
            row_metrics,
            text=f"🗑 {t('dropsync_trash_files', lang=self.config.language)} 0",
            bg="#F3F3F3",
            fg="#605E5C",
            padx=10,
            pady=4,
            font=(self.font_family, 9),
        )
        self.lbl_ds_trash_files.pack(side="left", padx=(0, 10))

        self.lbl_ds_disk_space = tk.Label(
            row_metrics,
            text="",
            bg="#F8FAFC",
            fg="#334155",
            padx=10,
            pady=4,
            font=(self.font_family, 9, "bold"),
        )
        self.lbl_ds_disk_space.pack(side="left", padx=(0, 10))

        self.btn_ds_open = ttk.Button(
            row_metrics,
            text=t("dropsync_btn_open_folder", lang=self.config.language),
            command=self._open_ds_folder,
        )
        self.btn_ds_open.pack(side="right")

        # Sync activity Treeview container
        tree_container = tk.Frame(self.card_ds_act, bg="#FFFFFF")
        tree_container.pack(fill="both", expand=True, pady=(4, 0))

        cols = ("time", "action", "file", "size", "status")
        self.tree_ds_log = ttk.Treeview(tree_container, columns=cols, show="headings", height=8)

        self.tree_ds_log.heading("time", text=t("dropsync_log_col_time"))
        self.tree_ds_log.heading("action", text=t("dropsync_log_col_action"))
        self.tree_ds_log.heading("file", text=t("dropsync_log_col_file"))
        self.tree_ds_log.heading("size", text=t("dropsync_log_col_size"))
        self.tree_ds_log.heading("status", text=t("dropsync_log_col_status"))

        self.tree_ds_log.column("time", width=90, anchor="center")
        self.tree_ds_log.column("action", width=85, anchor="center")
        self.tree_ds_log.column("file", width=250, anchor="w")
        self.tree_ds_log.column("size", width=80, anchor="center")
        self.tree_ds_log.column("status", width=80, anchor="center")

        ds_scroll = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree_ds_log.yview)
        self.tree_ds_log.configure(yscrollcommand=ds_scroll.set)

        self.tree_ds_log.pack(side="left", fill="both", expand=True)
        ds_scroll.pack(side="right", fill="y")

        # --- In-tab Live Speed Chart Card for DropSync ---
        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(14, 12))
        self.speed_card_ds = SpeedMonitorCard(parent, lang=self.config.language, bg="#FFFFFF", auto_start=True)
        self.speed_card_ds.pack(fill="x", pady=(0, 10))

        # Initial data load
        self._load_dropsync_ui_values()
        self._refresh_dropsync_status_and_stats()

    def _on_ds_role_changed(self) -> None:
        role = self.var_ds_role.get()
        if role == "client":
            self.row_ds_port.pack_forget()
            self.row_ds_remote.pack(fill="x")
        else:
            self.row_ds_remote.pack_forget()
            self.row_ds_port.pack(fill="x")

    def _toggle_ds_token_visibility(self) -> None:
        if not hasattr(self, "entry_ds_token") or not hasattr(self, "btn_ds_token_eye"):
            return
        if self.entry_ds_token.cget("show") == "•":
            self.entry_ds_token.config(show="")
            self.btn_ds_token_eye.config(text="🙈")
        else:
            self.entry_ds_token.config(show="•")
            self.btn_ds_token_eye.config(text="👁")

    def _copy_ds_token(self) -> None:
        if not hasattr(self, "entry_ds_token"):
            return
        val = self.entry_ds_token.get().strip()
        if not val:
            return
        self.window.clipboard_clear()
        self.window.clipboard_append(val)
        if hasattr(self, "lbl_ds_save_status"):
            self.lbl_ds_save_status.config(text=f"✓ {t('dropsync_token_copied')}", fg="#0F7B0F")
            self.window.after(3000, lambda: self.lbl_ds_save_status.config(text="") if self._is_window_alive() else None)

    def _generate_ds_token(self) -> None:
        if not hasattr(self, "entry_ds_token"):
            return
        token = secrets.token_hex(24)
        self.entry_ds_token.delete(0, tk.END)
        self.entry_ds_token.insert(0, token)
        self.entry_ds_token.config(show="")
        if hasattr(self, "btn_ds_token_eye"):
            self.btn_ds_token_eye.config(text="🙈")

    def _browse_ds_folder(self) -> None:
        if not hasattr(self, "entry_ds_folder"):
            return
        cur = self.entry_ds_folder.get().strip()
        picked = filedialog.askdirectory(initialdir=cur or str(Path.home()), parent=self.window)
        if picked:
            self.entry_ds_folder.delete(0, tk.END)
            self.entry_ds_folder.insert(0, picked)
            self._refresh_dropsync_status_and_stats()

    def _open_ds_folder(self) -> None:
        if not hasattr(self, "entry_ds_folder"):
            return
        folder_str = self.entry_ds_folder.get().strip()
        if folder_str:
            open_folder_in_explorer(folder_str)

    def _load_dropsync_ui_values(self) -> None:
        try:
            cfg = ds_load_config()
            self.entry_ds_node.delete(0, tk.END)
            self.entry_ds_node.insert(0, str(cfg.get("node_name", "server-1")))

            role = str(cfg.get("role", "server")).lower()
            self.var_ds_role.set(role)

            self.entry_ds_folder.delete(0, tk.END)
            self.entry_ds_folder.insert(0, str(cfg.get("sync_dir", "")))

            self.entry_ds_port.delete(0, tk.END)
            self.entry_ds_port.insert(0, str(cfg.get("listen_port", 8765)))

            self.entry_ds_remote.delete(0, tk.END)
            self.entry_ds_remote.insert(0, str(cfg.get("remote_url", "ws://192.168.1.4:8765/ws")))

            self.entry_ds_token.delete(0, tk.END)
            self.entry_ds_token.insert(0, str(cfg.get("auth_token", "")))

            self._on_ds_role_changed()
        except Exception as e:
            print(f"[SettingsDialog] _load_dropsync_ui_values error: {e}")

    def _save_dropsync_settings(self) -> None:
        try:
            cfg = ds_load_config()
            cfg["node_name"] = self.entry_ds_node.get().strip() or "server-1"
            cfg["role"] = self.var_ds_role.get()
            cfg["sync_dir"] = self.entry_ds_folder.get().strip()
            try:
                cfg["listen_port"] = int(self.entry_ds_port.get().strip() or 8765)
            except ValueError:
                cfg["listen_port"] = 8765
            cfg["remote_url"] = self.entry_ds_remote.get().strip()
            cfg["auth_token"] = self.entry_ds_token.get().strip()

            ok = ds_save_config(cfg)
            if ok:
                if hasattr(self, "lbl_ds_save_status"):
                    self.lbl_ds_save_status.config(text=f"✓ {t('dropsync_saved_title')}", fg="#0F7B0F")
                    self.window.after(4000, lambda: self.lbl_ds_save_status.config(text="") if self._is_window_alive() else None)
                messagebox.showinfo(t("dropsync_saved_title"), t("dropsync_saved_msg"), parent=self.window)
                self._refresh_dropsync_status_and_stats()
            else:
                messagebox.showerror(t("error_title"), "Failed to save DropSync configuration", parent=self.window)
        except Exception as e:
            messagebox.showerror(t("error_title"), f"Error saving DropSync settings: {e}", parent=self.window)

    def _action_dropsync_service(self, action: str) -> None:
        if hasattr(self, "lbl_ds_action_msg"):
            self.lbl_ds_action_msg.config(text=f"Executing {action}...", fg="#0067C0")

        def worker():
            ok, msg = ds_control_service(action)
            time.sleep(0.5)
            if self._is_window_alive():
                def _apply():
                    if hasattr(self, "lbl_ds_action_msg"):
                        self.lbl_ds_action_msg.config(text=msg, fg="#0F7B0F" if ok else "#C42B1C")
                    self._refresh_dropsync_status_and_stats()
                self.window.after(0, _apply)

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_dropsync_status_and_stats(self) -> None:
        sync_dir = self.entry_ds_folder.get().strip() if hasattr(self, "entry_ds_folder") else None

        def worker():
            status_info = ds_get_service_status()
            summary = ds_get_state_summary(sync_dir)

            if not self._is_window_alive():
                return

            def _update():
                if not self._is_window_alive():
                    return
                # Update status badge
                if hasattr(self, "lbl_ds_status_badge"):
                    label = status_info.get("status_label", "Unknown")
                    if status_info.get("active"):
                        self.lbl_ds_status_badge.config(text=label, bg="#DEF7EC", fg="#03543F")
                    elif status_info.get("installed"):
                        self.lbl_ds_status_badge.config(text=label, bg="#FDE8E8", fg="#9B1C1C")
                    else:
                        self.lbl_ds_status_badge.config(text=label, bg="#F3F3F3", fg="#605E5C")

                if hasattr(self, "lbl_ds_sub_detail"):
                    self.lbl_ds_sub_detail.config(text=status_info.get("sub_text", ""))

                # Update metrics
                self._last_ds_active_count = summary.get('active_files', 0)
                self._last_ds_trash_count = summary.get('trash_files', 0)
                cur_lang = self.config.language
                if hasattr(self, "lbl_ds_active_files"):
                    self.lbl_ds_active_files.config(text=f"📄 {t('dropsync_active_files', lang=cur_lang)} {self._last_ds_active_count}")
                if hasattr(self, "lbl_ds_trash_files"):
                    self.lbl_ds_trash_files.config(text=f"🗑 {t('dropsync_trash_files', lang=cur_lang)} {self._last_ds_trash_count}")
                if hasattr(self, "lbl_ds_disk_space"):
                    try:
                        import shutil
                        from pathlib import Path
                        tgt_dir = sync_dir or getattr(self.config, "exchange_path", None)
                        if tgt_dir and Path(tgt_dir).exists():
                            du = shutil.disk_usage(tgt_dir)
                            f_str = format_bytes(du.free, lang=cur_lang)
                            t_str = format_bytes(du.total, lang=cur_lang)
                            u_pct = round(((du.total - du.free) / du.total) * 100.0) if du.total > 0 else 0
                            self.lbl_ds_disk_space.config(text=t("disk_space_free", lang=cur_lang, free=f_str, total=t_str, used_pct=u_pct))
                    except Exception:
                        pass

                # Populate Treeview
                if hasattr(self, "tree_ds_log"):
                    for item in self.tree_ds_log.get_children():
                        self.tree_ds_log.delete(item)

                    def fmt_size(sz: int) -> str:
                        if sz >= 1024 * 1024 * 1024:
                            return f"{sz / (1024*1024*1024):.1f} GB"
                        if sz >= 1024 * 1024:
                            return f"{sz / (1024*1024):.1f} MB"
                        if sz >= 1024:
                            return f"{sz / 1024:.1f} KB"
                        return f"{sz} B"

                    logs = summary.get("logs", [])
                    for r in logs:
                        try:
                            ts = datetime.fromtimestamp(r["timestamp"]).strftime("%H:%M:%S")
                        except Exception:
                            ts = ""
                        act = r.get("action", "")
                        rel_path = r.get("rel_path", "")
                        sz_str = fmt_size(r.get("size", 0))
                        stat = r.get("status", "")
                        self.tree_ds_log.insert("", "end", values=(ts, act, rel_path, sz_str, stat))

            self.window.after(0, _update)

        threading.Thread(target=worker, daemon=True).start()

    def _build_remote_tab(self, parent: ttk.Frame) -> None:
        self.lbl_rc_hdr = ttk.Label(parent, text=t("remote_header"), style="Header.TLabel")
        self.lbl_rc_hdr.pack(anchor="w", pady=(0, 2))

        self.lbl_rc_sub = ttk.Label(parent, text=t("remote_sub"), style="Subheader.TLabel", justify="left")
        self.lbl_rc_sub.pack(anchor="w", pady=(0, 12))
        self.tab_remote.register_autowrap(self.lbl_rc_sub)

        # --- Card 1: Receiver (Этот компьютер) ---
        self.card1 = tk.LabelFrame(parent, text=f"  💻 {t('remote_receiver_card')}  ", bg="#FFFFFF", padx=14, pady=10)
        self.card1.pack(fill="x", pady=(0, 14))

        # Enable checkbox
        self.var_rc_enabled = tk.BooleanVar(value=self.config.remote_control_enabled)
        self.chk_rc_enabled = ttk.Checkbutton(
            self.card1,
            text=t("remote_enable_chk"),
            variable=self.var_rc_enabled,
            style="TCheckbutton",
        )
        self.chk_rc_enabled.pack(anchor="w", pady=(0, 8))

        # Device name row
        row_name = tk.Frame(self.card1, bg="#FFFFFF")
        row_name.pack(fill="x", pady=(0, 8))
        self.lbl_rc_name = ttk.Label(row_name, text=t("remote_device_name_label"), style="Card.TLabel", width=28)
        self.lbl_rc_name.pack(side="left")
        self.entry_rc_name = ttk.Entry(row_name, width=28)
        self.entry_rc_name.insert(0, self.config.remote_control_device_name)
        self.entry_rc_name.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # PIN status & button
        row_pin = tk.Frame(self.card1, bg="#FFFFFF")
        row_pin.pack(fill="x", pady=(0, 8))
        self.lbl_rc_pin_lbl = ttk.Label(row_pin, text=t("remote_pin_label"), style="Card.TLabel", width=28)
        self.lbl_rc_pin_lbl.pack(side="left")
        has_pin = bool(self.config.remote_control_pin)
        pin_status_txt = "●●●●●●●● (OK)" if has_pin else f"●●●● ({t('remote_pin_not_set')})"
        self.lbl_rc_pin_val = tk.Label(
            row_pin,
            text=pin_status_txt,
            bg="#EBF3FB" if has_pin else "#FDE8E8",
            fg="#0067C0" if has_pin else "#C81E1E",
            padx=8,
            pady=2,
            font=(self.font_family, 9, "bold"),
        )
        self.lbl_rc_pin_val.pack(side="left", padx=(0, 10))
        self.btn_set_pin = ttk.Button(row_pin, text=f"🔑 {t('remote_btn_set_pin')}", command=self._prompt_set_pin)
        self.btn_set_pin.pack(side="left")

        # Permissions checkboxes - stacked vertically for clean display without clipping
        frame_perms = tk.Frame(self.card1, bg="#FFFFFF")
        frame_perms.pack(fill="x", pady=(0, 6))

        self.var_rc_reboot = tk.BooleanVar(value=self.config.remote_control_allow_reboot)
        self.chk_rc_reboot = ttk.Checkbutton(
            frame_perms,
            text=f"🔄 {t('remote_allow_reboot_chk')}",
            variable=self.var_rc_reboot,
            style="TCheckbutton",
        )
        self.chk_rc_reboot.pack(anchor="w", pady=(1, 3))

        self.var_rc_procs = tk.BooleanVar(value=self.config.remote_control_allow_process_list)
        self.chk_rc_procs = ttk.Checkbutton(
            frame_perms,
            text=f"📋 {t('remote_allow_procs_chk')}",
            variable=self.var_rc_procs,
            style="TCheckbutton",
        )
        self.chk_rc_procs.pack(anchor="w", pady=(1, 3))

        self.var_rc_launch = tk.BooleanVar(value=self.config.remote_control_allow_launch)
        self.chk_rc_launch = ttk.Checkbutton(
            frame_perms,
            text=f"🚀 {t('remote_allow_launch_chk')}",
            variable=self.var_rc_launch,
            style="TCheckbutton",
        )
        self.chk_rc_launch.pack(anchor="w", pady=(1, 4))

        # Whitelist section: header and strict-mode checkbox on separate rows
        self.lbl_rc_wl_hdr = ttk.Label(self.card1, text=t("remote_whitelist_hdr"), style="Card.TLabel")
        self.lbl_rc_wl_hdr.pack(anchor="w", pady=(8, 3))

        self.var_rc_strict_wl = tk.BooleanVar(value=self.config.remote_control_strict_whitelist)
        self.chk_rc_strict_wl = ttk.Checkbutton(
            self.card1,
            text=t("remote_strict_whitelist_chk"),
            variable=self.var_rc_strict_wl,
            style="TCheckbutton",
        )
        self.chk_rc_strict_wl.pack(anchor="w", pady=(0, 6))

        # Whitelist listbox + scrollbar
        wl_box_frame = tk.Frame(self.card1, bg="#FFFFFF")
        wl_box_frame.pack(fill="x", pady=(0, 6))
        self.listbox_wl = tk.Listbox(wl_box_frame, height=4, font=(self.font_family, 9), selectmode="browse")
        self.listbox_wl.pack(side="left", fill="both", expand=True)
        sb_wl = ttk.Scrollbar(wl_box_frame, orient="vertical", command=self.listbox_wl.yview)
        sb_wl.pack(side="right", fill="y")
        self.listbox_wl.config(yscrollcommand=sb_wl.set)
        for app in self.config.remote_control_whitelist:
            self.listbox_wl.insert(tk.END, app)

        # Whitelist buttons
        wl_btns_frame = tk.Frame(self.card1, bg="#FFFFFF")
        wl_btns_frame.pack(fill="x", pady=(0, 8))
        self.btn_rc_add_app = ttk.Button(wl_btns_frame, text=t("remote_btn_add_app"), command=self._add_whitelist_app)
        self.btn_rc_add_app.pack(side="left", padx=(0, 6))
        self.btn_rc_del_app = ttk.Button(wl_btns_frame, text=t("remote_btn_del_app"), command=self._remove_whitelist_app)
        self.btn_rc_del_app.pack(side="left", padx=(0, 6))
        self.btn_rc_from_running = ttk.Button(wl_btns_frame, text=f"📋 {t('remote_btn_from_running')}", command=self._add_from_running_apps)
        self.btn_rc_from_running.pack(side="left")

        # --- Pre-defined Launch Applications section ---
        row_launch_hdr = tk.Frame(self.card1, bg="#FFFFFF")
        row_launch_hdr.pack(fill="x", pady=(8, 4))
        self.lbl_rc_launch_hdr = ttk.Label(row_launch_hdr, text=t("remote_launch_apps_hdr"), style="Card.TLabel")
        self.lbl_rc_launch_hdr.pack(side="left")

        launch_box_frame = tk.Frame(self.card1, bg="#FFFFFF")
        launch_box_frame.pack(fill="x", pady=(0, 6))

        launch_cols = ("name", "path", "args")
        self.tree_launch_apps = ttk.Treeview(
            launch_box_frame,
            columns=launch_cols,
            show="headings",
            height=3,
            selectmode="browse",
        )
        self.tree_launch_apps.heading("name", text=t("remote_app_name_lbl"))
        self.tree_launch_apps.heading("path", text=t("remote_app_path_lbl"))
        self.tree_launch_apps.heading("args", text=t("remote_app_args_lbl"))

        self.tree_launch_apps.column("name", width=120, minwidth=80, anchor="w")
        self.tree_launch_apps.column("path", width=260, minwidth=140, anchor="w")
        self.tree_launch_apps.column("args", width=100, minwidth=60, anchor="w")

        sb_launch = ttk.Scrollbar(launch_box_frame, orient="vertical", command=self.tree_launch_apps.yview)
        self.tree_launch_apps.configure(yscrollcommand=sb_launch.set)

        self.tree_launch_apps.pack(side="left", fill="both", expand=True)
        sb_launch.pack(side="right", fill="y")

        self._local_launch_apps = list(self.config.remote_control_launch_apps)
        for app in self._local_launch_apps:
            self.tree_launch_apps.insert("", "end", values=(app.get("name", ""), app.get("path", ""), app.get("args", "")))

        launch_btns_frame = tk.Frame(self.card1, bg="#FFFFFF")
        launch_btns_frame.pack(fill="x")
        self.btn_rc_add_launch = ttk.Button(launch_btns_frame, text=t("remote_btn_add_launch_app"), command=self._add_launch_app_dialog)
        self.btn_rc_add_launch.pack(side="left", padx=(0, 6))
        self.btn_rc_del_launch = ttk.Button(launch_btns_frame, text=t("remote_btn_del_launch_app"), command=self._remove_launch_app)
        self.btn_rc_del_launch.pack(side="left")

        # --- Card 2: Remote Controller (Отправить команду на другой ПК) ---
        self.card2 = tk.LabelFrame(parent, text=f"  🚀 {t('remote_sender_card')}  ", bg="#FFFFFF", padx=14, pady=10)
        self.card2.pack(fill="x", pady=(0, 10))

        # Target PC selection: refresh button anchored right, combo expands
        row_target = tk.Frame(self.card2, bg="#FFFFFF")
        row_target.pack(fill="x", pady=(0, 8))
        self.lbl_rc_target_lbl = ttk.Label(row_target, text=t("remote_target_pc_label"), style="Card.TLabel")
        self.lbl_rc_target_lbl.pack(side="left", padx=(0, 8))
        self.btn_rc_refresh_devices = ttk.Button(row_target, text=t("remote_devices_refresh"), command=self._refresh_remote_devices)
        self.btn_rc_refresh_devices.pack(side="right")
        self.combo_target_device = ttk.Combobox(row_target)
        self.combo_target_device.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.combo_target_device.bind("<<ComboboxSelected>>", self._on_target_device_selected)

        # Action selection
        row_act = tk.Frame(self.card2, bg="#FFFFFF")
        row_act.pack(fill="x", pady=(0, 8))
        self.lbl_rc_act_lbl = ttk.Label(row_act, text=t("remote_action_label"), style="Card.TLabel")
        self.lbl_rc_act_lbl.pack(side="left", padx=(0, 8))
        self.rc_action_options = [
            t("remote_act_kill"),
            t("remote_act_reboot"),
            t("remote_act_list"),
            t("remote_act_launch"),
        ]
        self.combo_rc_action = ttk.Combobox(row_act, values=self.rc_action_options, state="readonly")
        self.combo_rc_action.current(0)
        self.combo_rc_action.pack(side="left", fill="x", expand=True)
        self.combo_rc_action.bind("<<ComboboxSelected>>", self._on_rc_action_changed)

        # Process name row (enabled for kill_process)
        self.row_proc_input = tk.Frame(self.card2, bg="#FFFFFF")
        self.row_proc_input.pack(fill="x", pady=(0, 8))
        self.lbl_rc_proc_lbl = ttk.Label(self.row_proc_input, text=t("remote_process_name_label"), style="Card.TLabel")
        self.lbl_rc_proc_lbl.pack(side="left", padx=(0, 8))
        self.entry_rc_target_proc = ttk.Entry(self.row_proc_input)
        self.entry_rc_target_proc.insert(0, "happ.exe")
        self.entry_rc_target_proc.pack(side="left", fill="x", expand=True)

        # Launch app selection row (enabled for launch_app)
        self.row_launch_input = tk.Frame(self.card2, bg="#FFFFFF")
        self.lbl_rc_app_lbl = ttk.Label(self.row_launch_input, text=t("remote_target_app_label"), style="Card.TLabel")
        self.lbl_rc_app_lbl.pack(side="left", padx=(0, 8))
        self.combo_rc_target_app = ttk.Combobox(self.row_launch_input, state="readonly")
        self.combo_rc_target_app.pack(side="left", fill="x", expand=True)

        # Target PIN row
        self.row_target_pin = tk.Frame(self.card2, bg="#FFFFFF")
        self.row_target_pin.pack(fill="x", pady=(0, 10))
        self.lbl_rc_tpin_lbl = ttk.Label(self.row_target_pin, text=t("remote_target_pin_label"), style="Card.TLabel")
        self.lbl_rc_tpin_lbl.pack(side="left", padx=(0, 8))
        self._target_pin_visible = False
        self.btn_toggle_target_pin = ttk.Button(self.row_target_pin, text="👁", width=3, command=self._toggle_target_pin_visibility)
        self.btn_toggle_target_pin.pack(side="right")
        self.entry_rc_target_pin = ttk.Entry(self.row_target_pin, show="●")
        self.entry_rc_target_pin.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # Send command button
        row_send = tk.Frame(self.card2, bg="#FFFFFF")
        row_send.pack(fill="x", pady=(0, 6))
        self.btn_send_rc_cmd = ttk.Button(
            row_send,
            text=f"🚀 {t('remote_btn_send_cmd')}",
            style="Accent.TButton",
            command=self._on_send_remote_command,
        )
        self.btn_send_rc_cmd.pack(side="left")

        # Live status message banner with responsive autowrap
        self.lbl_rc_cmd_status = tk.Label(
            self.card2,
            text="",
            bg="#F3F3F3",
            fg="#202124",
            font=(self.font_family, 9),
            anchor="w",
            justify="left",
            padx=8,
            pady=4,
            relief="sunken",
        )
        self.lbl_rc_cmd_status.pack(fill="x", pady=(6, 0))
        self.tab_remote.register_autowrap(self.lbl_rc_cmd_status, extra_pad=28)

        # Auto-refresh remote devices on initial build in background
        threading.Thread(target=self._refresh_remote_devices, daemon=True).start()

    def _prompt_set_pin(self) -> None:
        top = tk.Toplevel(self.window)
        top.title(t("remote_pin_prompt_title"))
        top.transient(self.window)
        top.grab_set()
        top.resizable(False, False)
        top.configure(bg="#FFFFFF")

        lbl = ttk.Label(top, text=t("remote_pin_prompt_msg"), style="Card.TLabel")
        lbl.pack(padx=16, pady=(16, 8), anchor="w")

        pframe = tk.Frame(top, bg="#FFFFFF")
        pframe.pack(padx=16, pady=(0, 16), fill="x")

        ent = ttk.Entry(pframe, font=(self.font_family, 10), show="●")
        ent.pack(side="left", fill="x", expand=True)
        ent.focus_set()

        pin_visible = False

        def toggle_pin_vis():
            nonlocal pin_visible
            pin_visible = not pin_visible
            ent.config(show="" if pin_visible else "●")
            btn_eye.config(text="🔒" if pin_visible else "👁")

        btn_eye = ttk.Button(pframe, text="👁", width=3, command=toggle_pin_vis)
        btn_eye.pack(side="right", padx=(6, 0))

        btn_frame = tk.Frame(top, bg="#F9FAFB")
        btn_frame.pack(fill="x", side="bottom")

        result = [None]

        def on_ok(event=None):
            result[0] = ent.get()
            top.destroy()

        def on_cancel(event=None):
            top.destroy()

        ent.bind("<Return>", on_ok)
        top.bind("<Escape>", on_cancel)

        # Center on parent window
        top.update_idletasks()
        w = max(380, top.winfo_reqwidth())
        h = top.winfo_reqheight() + 60
        x = self.window.winfo_x() + (self.window.winfo_width() - w) // 2
        y = self.window.winfo_y() + (self.window.winfo_height() - h) // 2
        top.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")

        ttk.Button(btn_frame, text=t("btn_cancel"), command=on_cancel).pack(side="right", padx=12, pady=10)
        ttk.Button(btn_frame, text=t("btn_save"), style="Accent.TButton", command=on_ok).pack(side="right", pady=10)

        self.window.wait_window(top)

        if result[0] is not None:
            clean_pin = result[0].strip()
            self.config.remote_control_pin = clean_pin
            has_pin = bool(clean_pin)
            self.lbl_rc_pin_val.config(
                text="●●●●●●●● (OK)" if has_pin else f"●●●● ({t('remote_pin_not_set')})",
                bg="#EBF3FB" if has_pin else "#FDE8E8",
                fg="#0067C0" if has_pin else "#C81E1E",
            )
            if has_pin:
                messagebox.showinfo(t("remote_header"), t("remote_pin_set_success"), parent=self.window)
            else:
                messagebox.showwarning(t("remote_header"), t("remote_pin_cleared"), parent=self.window)

    def _add_whitelist_app(self) -> None:
        app = simpledialog.askstring(
            t("remote_whitelist_hdr"),
            t("remote_whitelist_prompt_msg"),
            parent=self.window,
        )
        if app and app.strip():
            clean_app = app.strip().lower()
            existing = [self.listbox_wl.get(i).lower() for i in range(self.listbox_wl.size())]
            if clean_app not in existing:
                self.listbox_wl.insert(tk.END, clean_app)

    def _remove_whitelist_app(self) -> None:
        sel = self.listbox_wl.curselection()
        if sel:
            self.listbox_wl.delete(sel[0])

    def _add_from_running_apps(self) -> None:
        procs = list_system_processes()
        if not procs:
            messagebox.showinfo(t("remote_whitelist_hdr"), t("remote_procs_none_detected"), parent=self.window)
            return

        top = tk.Toplevel(self.window)
        top.title(t("remote_procs_select_win_title"))
        top.geometry("420x450")
        top.transient(self.window)
        top.grab_set()

        lbl = ttk.Label(top, text=t("remote_procs_select_win_sub"), style="Header.TLabel")
        lbl.pack(anchor="w", padx=12, pady=(12, 6))

        # Filter
        filter_frame = tk.Frame(top)
        filter_frame.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Label(filter_frame, text=t("remote_procs_filter")).pack(side="left", padx=(0, 6))
        ent_filter = ttk.Entry(filter_frame)
        ent_filter.pack(side="left", fill="x", expand=True)

        list_frame = tk.Frame(top)
        list_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        lb = tk.Listbox(list_frame, font=(self.font_family, 9))
        lb.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=lb.yview)
        sb.pack(side="right", fill="y")
        lb.config(yscrollcommand=sb.set)

        # Unique process names sorted
        unique_names = sorted(list(set(p["name"] for p in procs)), key=lambda x: x.lower())
        for name in unique_names:
            lb.insert(tk.END, name)

        def apply_filter(*args):
            query = ent_filter.get().strip().lower()
            lb.delete(0, tk.END)
            for name in unique_names:
                if query in name.lower():
                    lb.insert(tk.END, name)

        ent_filter.bind("<KeyRelease>", apply_filter)

        def on_select():
            sel = lb.curselection()
            if sel:
                chosen = lb.get(sel[0])
                existing = [self.listbox_wl.get(i).lower() for i in range(self.listbox_wl.size())]
                if chosen.lower() not in existing:
                    self.listbox_wl.insert(tk.END, chosen)
                top.destroy()

        btn_row = tk.Frame(top)
        btn_row.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(btn_row, text=t("remote_procs_btn_add_selected"), style="Accent.TButton", command=on_select).pack(side="right")
        ttk.Button(btn_row, text=t("btn_cancel"), command=top.destroy).pack(side="right", padx=(0, 8))

    def _add_launch_app_dialog(self) -> None:
        top = tk.Toplevel(self.window)
        top.title(t("remote_app_add_title"))
        top.geometry("580x250")
        top.minsize(540, 230)
        top.transient(self.window)
        top.grab_set()

        frm = tk.Frame(top, padx=16, pady=16)
        frm.pack(fill="both", expand=True)

        grid = ttk.Frame(frm)
        grid.pack(fill="both", expand=True)
        grid.columnconfigure(1, weight=1)

        def browse_path():
            import sys
            filetypes = [("Executables", "*.exe;*.bat;*.cmd;*.sh;*.bin"), ("All Files", "*.*")] if sys.platform == "win32" else [("All Files", "*.*")]
            fpath = filedialog.askopenfilename(
                parent=top,
                title=t("remote_app_browse_title"),
                filetypes=filetypes,
            )
            if fpath:
                ent_path.delete(0, tk.END)
                ent_path.insert(0, fpath)
                if not ent_name.get().strip():
                    import os
                    base = os.path.basename(fpath)
                    stem = os.path.splitext(base)[0]
                    ent_name.insert(0, stem)

        # Row 0: App Name
        lbl_name = ttk.Label(grid, text=t("remote_app_name_lbl"))
        lbl_name.grid(row=0, column=0, sticky="w", pady=(0, 10), padx=(0, 10))
        ent_name = ttk.Entry(grid)
        ent_name.grid(row=0, column=1, columnspan=2, sticky="ew", pady=(0, 10))
        ent_name.focus_set()

        # Row 1: Executable Path + Browse Button
        lbl_path = ttk.Label(grid, text=t("remote_app_path_lbl"))
        lbl_path.grid(row=1, column=0, sticky="w", pady=(0, 10), padx=(0, 10))
        ent_path = ttk.Entry(grid)
        ent_path.grid(row=1, column=1, sticky="ew", pady=(0, 10), padx=(0, 6))
        btn_browse = ttk.Button(grid, text=t("remote_app_browse_btn"), command=browse_path)
        btn_browse.grid(row=1, column=2, sticky="e", pady=(0, 10))

        # Row 2: Arguments
        lbl_args = ttk.Label(grid, text=t("remote_app_args_lbl"))
        lbl_args.grid(row=2, column=0, sticky="w", pady=(0, 16), padx=(0, 10))
        ent_args = ttk.Entry(grid)
        ent_args.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(0, 16))

        # Buttons
        btn_row = tk.Frame(frm)
        btn_row.pack(fill="x", side="bottom")

        def on_save():
            name = ent_name.get().strip()
            path = ent_path.get().strip()
            args = ent_args.get().strip()
            if not name or not path:
                messagebox.showwarning(t("remote_app_add_title"), t("remote_app_validation_err"), parent=top)
                return
            new_app = {"name": name, "path": path, "args": args}
            self._local_launch_apps.append(new_app)
            self.tree_launch_apps.insert("", "end", values=(name, path, args))
            top.destroy()

        save_text = t("btn_save")
        cancel_text = t("btn_cancel")

        ttk.Button(btn_row, text=save_text, style="Accent.TButton", command=on_save).pack(side="right")
        ttk.Button(btn_row, text=cancel_text, command=top.destroy).pack(side="right", padx=(0, 8))

    def _remove_launch_app(self) -> None:
        sel = self.tree_launch_apps.selection()
        if not sel:
            return
        item_id = sel[0]
        values = self.tree_launch_apps.item(item_id, "values")
        if values:
            app_name = values[0]
            self._local_launch_apps = [a for a in self._local_launch_apps if a.get("name") != app_name]
        self.tree_launch_apps.delete(item_id)

    def _get_fallback_rc_manager(self):
        """Creates a standalone RemoteControlManager configured with all available server routes."""
        from remote_control import RemoteControlManager
        routes = []
        timeout = (2.0, 5.0)
        if self.config.server_url and self.config.username:
            c1 = FileBrowserClient(
                base_url=self.config.server_url,
                username=self.config.username,
                password=self.config.password,
                timeout=timeout,
            )
            routes.append((c1, self.config.remote_path))
        if self.config.backup_server_enabled and self.config.backup_server_url:
            b_user = self.config.backup_username or self.config.username
            b_pwd = self.config.backup_password or self.config.password
            c2 = FileBrowserClient(
                base_url=self.config.backup_server_url,
                username=b_user,
                password=b_pwd,
                timeout=timeout,
            )
            routes.append((c2, self.config.backup_remote_path))

        if not routes:
            c = FileBrowserClient(
                base_url=self.config.server_url,
                username=self.config.username,
                password=self.config.password,
                timeout=timeout,
            )
            routes.append((c, self.config.remote_path))

        return RemoteControlManager(
            client=routes[0][0],
            remote_path=routes[0][1],
            secondary_routes=routes[1:] if len(routes) > 1 else None,
        )

    def _refresh_remote_devices(self) -> None:
        try:
            devices = []
            if self.engine:
                devices = self.engine.get_remote_devices()
            else:
                rc = self._get_fallback_rc_manager()
                devices = rc.get_online_devices()

            self._remote_devices_cache = {d.get("device_name", "").lower(): d for d in devices if d.get("device_name")}
            my_name = self.config.remote_control_device_name.lower()
            names = []
            for d in devices:
                dev_name = d.get("device_name", "")
                if dev_name and dev_name.lower() != my_name:
                    names.append(dev_name)

            def _apply_devices():
                if hasattr(self, "combo_target_device") and self._is_window_alive():
                    self.combo_target_device["values"] = names
                    if names and not self.combo_target_device.get():
                        self.combo_target_device.set(names[0])
                    self._on_target_device_selected()

            if self._is_window_alive():
                self.window.after(0, _apply_devices)
        except Exception as e:
            print(f"[SettingsDialog] _refresh_remote_devices error: {e}")

    def _on_target_device_selected(self, event=None) -> None:
        if not hasattr(self, "combo_target_device") or not hasattr(self, "combo_rc_target_app"):
            return
        target = self.combo_target_device.get().strip().lower()
        cached = getattr(self, "_remote_devices_cache", {}).get(target, {})
        launch_apps = cached.get("launch_apps", [])
        app_names = [a.get("name", "") for a in launch_apps if a.get("name")]
        self.combo_rc_target_app["values"] = app_names
        if app_names:
            if self.combo_rc_target_app.get() not in app_names:
                self.combo_rc_target_app.set(app_names[0])
        else:
            self.combo_rc_target_app.set("")

    def _on_rc_action_changed(self, event=None) -> None:
        idx = self.combo_rc_action.current()
        if idx == 0:  # kill_process
            self.row_launch_input.pack_forget()
            self.row_proc_input.pack(fill="x", pady=(0, 8), before=self.row_target_pin)
        elif idx == 3:  # launch_app
            self.row_proc_input.pack_forget()
            self.row_launch_input.pack(fill="x", pady=(0, 8), before=self.row_target_pin)
        else:
            self.row_proc_input.pack_forget()
            self.row_launch_input.pack_forget()

    def _toggle_target_pin_visibility(self) -> None:
        self._target_pin_visible = not getattr(self, "_target_pin_visible", False)
        self.entry_rc_target_pin.config(show="" if self._target_pin_visible else "●")
        self.btn_toggle_target_pin.config(text="🔒" if self._target_pin_visible else "👁")

    def _on_send_remote_command(self) -> None:
        target = self.combo_target_device.get().strip()
        if not target:
            messagebox.showwarning(t("remote_header"), t("remote_err_no_target"), parent=self.window)
            return

        pin = self.entry_rc_target_pin.get().strip()
        if not pin:
            messagebox.showwarning(t("remote_header"), t("remote_err_no_pin"), parent=self.window)
            return

        idx = self.combo_rc_action.current()
        if idx == 0:
            action = "kill_process"
            proc_name = self.entry_rc_target_proc.get().strip()
            if not proc_name:
                messagebox.showwarning(t("remote_header"), t("remote_err_no_proc"), parent=self.window)
                return
            payload = {"process_name": proc_name}
        elif idx == 1:
            action = "reboot"
            ans = messagebox.askyesno(
                t("remote_confirm_reboot_title"),
                t("remote_confirm_reboot_msg", target=target),
                parent=self.window,
            )
            if not ans:
                return
            payload = {"delay": 5}
        elif idx == 2:
            action = "list_processes"
            payload = {}
        elif idx == 3:
            action = "launch_app"
            app_name = self.combo_rc_target_app.get().strip()
            if not app_name:
                messagebox.showwarning(t("remote_header"), t("remote_err_no_app"), parent=self.window)
                return
            payload = {"app_name": app_name}
        else:
            action = "list_processes"
            payload = {}

        self.btn_send_rc_cmd.config(state="disabled")
        self.lbl_rc_cmd_status.config(text=t("remote_status_sending", target=target), fg="#0067C0", bg="#EBF3FB")

        def status_cb(msg: str):
            if hasattr(self, "lbl_rc_cmd_status") and self._is_window_alive():
                self.lbl_rc_cmd_status.after(0, lambda: self.lbl_rc_cmd_status.config(text=msg))

        def worker():
            try:
                if self.engine:
                    ok, msg, res_dict = self.engine.send_remote_command(
                        target_device=target,
                        action=action,
                        payload=payload,
                        pin=pin,
                        timeout=60,
                        status_callback=status_cb,
                    )
                else:
                    rc = self._get_fallback_rc_manager()
                    ok, msg, res_dict = rc.send_command_and_wait(
                        target_device=target,
                        sender_device=self.config.remote_control_device_name,
                        action=action,
                        payload=payload,
                        secret_pin=pin,
                        timeout_seconds=60,
                        status_callback=status_cb,
                    )

                def _apply_cmd_result():
                    if not self._is_window_alive():
                        return
                    if ok:
                        self.lbl_rc_cmd_status.config(
                            text=f"✅ {msg}",
                            fg="#0F7B0F",
                            bg="#EDF7ED",
                        )
                        if action == "list_processes":
                            procs = res_dict.get("processes", [])
                            launch_apps = res_dict.get("launch_apps", [])
                            self._show_remote_processes_dialog(target, procs, pin, launch_apps=launch_apps)
                        else:
                            messagebox.showinfo(t("remote_header"), f"✅ {msg}", parent=self.window)
                    else:
                        self.lbl_rc_cmd_status.config(
                            text=f"❌ {msg}",
                            fg="#C81E1E",
                            bg="#FDE8E8",
                        )
                        messagebox.showerror(t("remote_header"), f"❌ {msg}", parent=self.window)
                    self.btn_send_rc_cmd.config(state="normal")

                if self._is_window_alive():
                    self.window.after(0, _apply_cmd_result)
            except Exception as e:
                def _apply_err():
                    if self._is_window_alive():
                        self.lbl_rc_cmd_status.config(text=f"Error: {e}", fg="#C81E1E", bg="#FDE8E8")
                        self.btn_send_rc_cmd.config(state="normal")
                if self._is_window_alive():
                    self.window.after(0, _apply_err)

        threading.Thread(target=worker, daemon=True).start()

    def _show_remote_processes_dialog(self, target_pc: str, processes: list, target_pin: str, launch_apps: list = None) -> None:
        top = tk.Toplevel(self.window)
        top.title(t("remote_procs_title", target=target_pc))
        top.geometry("840x580")
        top.minsize(700, 460)
        top.transient(self.window)

        # Internal mutable process list
        local_procs = list(processes)

        # Determine available launch apps for target PC
        if launch_apps is None:
            cached = getattr(self, "_remote_devices_cache", {}).get(target_pc.lower(), {})
            launch_apps = cached.get("launch_apps", [])
        app_names = [a.get("name", "") for a in launch_apps if a.get("name")]

        def parse_mem_kb(val):
            s = str(val or "").replace(" ", "").replace("\xa0", "").upper()
            if s.endswith("GB"):
                try:
                    return int(float(s[:-2]) * 1024 * 1024)
                except Exception:
                    return 0
            elif s.endswith("MB"):
                try:
                    return int(float(s[:-2])) * 1024
                except Exception:
                    return 0
            elif s.endswith("KB"):
                try:
                    return int(float(s[:-2]))
                except Exception:
                    return 0
            return 0

        def fmt_kb(kb):
            if kb >= 1024 * 1024:
                return f"{kb / (1024 * 1024):.1f} GB"
            elif kb >= 1024:
                return f"{kb // 1024} MB"
            return f"{kb} KB"

        # Ensure toplevel Treeview style uses correct row height and font
        top_style = ttk.Style(top)
        top_style.configure(
            "Treeview",
            font=(self.font_family, 9),
            rowheight=getattr(self, "tree_row_height", 28),
        )
        top_style.configure(
            "Treeview.Heading",
            font=(self.font_family, 9, "bold"),
            padding=[4, 4],
        )

        # Header
        hdr_frame = tk.Frame(top, bg="#FFFFFF", padx=14, pady=10)
        hdr_frame.pack(fill="x")
        lbl_hdr = tk.Label(
            hdr_frame,
            text=f"📋 {t('remote_procs_title', target=target_pc)} ({len(local_procs)} processes)",
            font=(self.font_family, 11, "bold"),
            bg="#FFFFFF",
            fg="#1A1A1A",
        )
        lbl_hdr.pack(side="left")

        # Filter bar with grouping toggle
        filter_frame = tk.Frame(top, padx=14, pady=6)
        filter_frame.pack(fill="x")

        var_group = tk.BooleanVar(value=True)
        chk_group = ttk.Checkbutton(
            filter_frame,
            text=t("remote_procs_group_apps"),
            variable=var_group,
            command=lambda: refresh_view(),
        )
        # Pack chk_group to the right first so it preserves its full width
        chk_group.pack(side="right", padx=(8, 0))

        ttk.Label(filter_frame, text=t("remote_procs_filter")).pack(side="left", padx=(0, 8))
        ent_filter = ttk.Entry(filter_frame, font=(self.font_family, 9))
        ent_filter.pack(side="left", fill="x", expand=True)

        # Bottom actions frame packed with side="bottom" FIRST so it is guaranteed visible
        bot_frame = tk.Frame(top, padx=14, pady=10)
        bot_frame.pack(fill="x", side="bottom")

        # Table frame
        tree_frame = tk.Frame(top, padx=14, pady=4)
        tree_frame.pack(fill="both", expand=True)

        cols = ("name", "pid", "memory")
        tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        tree.heading("name", text=t("remote_procs_col_name"))
        tree.heading("pid", text=t("remote_procs_col_pid"))
        tree.heading("memory", text=t("remote_procs_col_memory"))

        tree.column("name", width=320, anchor="w")
        tree.column("pid", width=120, anchor="center")
        tree.column("memory", width=120, anchor="center")

        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)

        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        item_meta = {}

        def refresh_view(*args):
            q = ent_filter.get().strip().lower()
            for r in tree.get_children():
                tree.delete(r)
            item_meta.clear()

            grouped = var_group.get()
            if grouped:
                groups = {}
                for p in local_procs:
                    p_name = str(p.get("name", "")).strip()
                    if not p_name:
                        continue
                    p_pid = str(p.get("pid", ""))
                    kb = parse_mem_kb(p.get("memory", "0"))
                    if p_name not in groups:
                        groups[p_name] = {
                            "name": p_name,
                            "count": 0,
                            "pids": [],
                            "total_kb": 0,
                        }
                    groups[p_name]["count"] += 1
                    groups[p_name]["pids"].append(p_pid)
                    groups[p_name]["total_kb"] += kb

                sorted_groups = sorted(groups.values(), key=lambda g: (-g["total_kb"], g["name"].lower()))
                for g in sorted_groups:
                    name_display = f"{g['name']} ({g['count']})" if g["count"] > 1 else g["name"]
                    pids_display = f"{g['pids'][0]} (+{g['count']-1})" if g["count"] > 1 else (g["pids"][0] if g["pids"] else "-")
                    mem_display = fmt_kb(g["total_kb"])

                    if q and q not in g["name"].lower() and not any(q in pid for pid in g["pids"]):
                        continue

                    node = tree.insert("", "end", values=(name_display, pids_display, mem_display))
                    item_meta[node] = {
                        "clean_name": g["name"],
                        "count": g["count"],
                        "mem": mem_display,
                        "pid": g["pids"][0] if g["pids"] else "",
                    }

                lbl_hdr.config(text=f"📋 {t('remote_procs_title', target=target_pc)} ({len(groups)} apps / {len(local_procs)} processes)")
            else:
                sorted_procs = sorted(local_procs, key=lambda p: p.get("name", "").lower())
                for p in sorted_procs:
                    p_name = str(p.get("name", "")).strip()
                    p_pid = str(p.get("pid", ""))
                    p_mem = str(p.get("memory", ""))
                    if q and q not in p_name.lower() and q not in p_pid:
                        continue
                    node = tree.insert("", "end", values=(p_name, p_pid, p_mem))
                    item_meta[node] = {
                        "clean_name": p_name,
                        "count": 1,
                        "mem": p_mem,
                        "pid": p_pid,
                    }

                lbl_hdr.config(text=f"📋 {t('remote_procs_title', target=target_pc)} ({len(local_procs)} processes)")

        ent_filter.bind("<KeyRelease>", refresh_view)
        refresh_view()

        def terminate_selected():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning(t("remote_header"), t("remote_procs_select_warn"), parent=top)
                return
            node = sel[0]
            meta = item_meta.get(node)
            if not meta:
                return

            clean_name = meta["clean_name"]
            count = meta["count"]
            mem = meta["mem"]
            pid = meta["pid"]

            if count > 1:
                confirm_msg = t("remote_procs_confirm_kill_group", name=clean_name, count=count, mem=mem, target=target_pc)
            else:
                confirm_msg = t("remote_procs_confirm_kill", name=clean_name, pid=pid, target=target_pc)

            ans = messagebox.askyesno(
                t("remote_header"),
                confirm_msg,
                parent=top,
            )
            if not ans:
                return

            def kill_worker():
                if self.engine:
                    ok, msg, _ = self.engine.send_remote_command(
                        target_device=target_pc,
                        action="kill_process",
                        payload={"process_name": clean_name},
                        pin=target_pin,
                        timeout=60,
                    )
                else:
                    rc = self._get_fallback_rc_manager()
                    ok, msg, _ = rc.send_command_and_wait(
                        target_device=target_pc,
                        sender_device=self.config.remote_control_device_name,
                        action="kill_process",
                        payload={"process_name": clean_name},
                        secret_pin=target_pin,
                        timeout_seconds=60,
                    )

                def _apply_kill_result():
                    if not top.winfo_exists():
                        return
                    if ok:
                        nonlocal local_procs
                        killed_count = sum(1 for p in local_procs if str(p.get("name", "")).strip().lower() == clean_name.lower())
                        local_procs = [p for p in local_procs if str(p.get("name", "")).strip().lower() != clean_name.lower()]
                        refresh_view()
                        done_msg = t("remote_procs_all_killed", name=clean_name, count=killed_count or count)
                        messagebox.showinfo(t("remote_header"), f"✅ {msg}\n\n{done_msg}", parent=top)
                    else:
                        messagebox.showerror(t("remote_header"), f"❌ {msg}", parent=top)

                if top.winfo_exists():
                    top.after(0, _apply_kill_result)

            threading.Thread(target=kill_worker, daemon=True).start()

        # Bottom Bar: Close button on far right
        btn_close = ttk.Button(bot_frame, text=t("btn_close"), command=top.destroy)
        btn_close.pack(side="right", padx=(8, 0))

        # Bottom Bar: Kill Selected button on left
        kill_label = t("remote_procs_btn_kill")
        if not kill_label.startswith("🛑"):
            kill_label = f"🛑 {kill_label}"
        btn_kill = ttk.Button(
            bot_frame,
            text=kill_label,
            style="Accent.TButton",
            command=terminate_selected,
        )
        btn_kill.pack(side="left", padx=(0, 10))

        # Bottom Bar: Refresh button
        def do_refresh_procs():
            btn_refresh.config(state="disabled")
            def refresh_worker():
                if self.engine:
                    ok_ref, msg_ref, res_ref = self.engine.send_remote_command(
                        target_device=target_pc,
                        action="list_processes",
                        payload={},
                        pin=target_pin,
                        timeout=60,
                    )
                else:
                    rc_ref = self._get_fallback_rc_manager()
                    ok_ref, msg_ref, res_ref = rc_ref.send_command_and_wait(
                        target_device=target_pc,
                        sender_device=self.config.remote_control_device_name,
                        action="list_processes",
                        payload={},
                        secret_pin=target_pin,
                        timeout_seconds=60,
                    )
                def _apply_ref():
                    if not top.winfo_exists():
                        return
                    btn_refresh.config(state="normal")
                    if ok_ref:
                        nonlocal local_procs
                        local_procs = res_ref.get("processes", [])
                        refresh_view()
                    else:
                        messagebox.showerror(t("remote_header"), f"❌ {msg_ref}", parent=top)
                if top.winfo_exists():
                    top.after(0, _apply_ref)
            threading.Thread(target=refresh_worker, daemon=True).start()

        btn_refresh = ttk.Button(bot_frame, text=f"🔄 {t('remote_devices_refresh')}", command=do_refresh_procs)
        btn_refresh.pack(side="left", padx=(0, 14))

        # Bottom Bar: Quick Launch application section
        if app_names:
            sep = ttk.Separator(bot_frame, orient="vertical")
            sep.pack(side="left", fill="y", padx=(0, 14))

            ttk.Label(bot_frame, text=t("remote_procs_launch_label")).pack(side="left", padx=(0, 6))
            combo_quick_app = ttk.Combobox(bot_frame, values=app_names, state="readonly", width=18)
            combo_quick_app.set(app_names[0])
            combo_quick_app.pack(side="left", padx=(0, 6))

            def do_quick_launch():
                chosen_app = combo_quick_app.get().strip()
                if not chosen_app:
                    return
                ans = messagebox.askyesno(
                    t("remote_header"),
                    t("remote_procs_launch_confirm", name=chosen_app, target=target_pc),
                    parent=top,
                )
                if not ans:
                    return
                btn_quick_launch.config(state="disabled")
                def launch_worker():
                    if self.engine:
                        ok_ln, msg_ln, _ = self.engine.send_remote_command(
                            target_device=target_pc,
                            action="launch_app",
                            payload={"app_name": chosen_app},
                            pin=target_pin,
                            timeout=60,
                        )
                    else:
                        rc_ln = self._get_fallback_rc_manager()
                        ok_ln, msg_ln, _ = rc_ln.send_command_and_wait(
                            target_device=target_pc,
                            sender_device=self.config.remote_control_device_name,
                            action="launch_app",
                            payload={"app_name": chosen_app},
                            secret_pin=target_pin,
                            timeout_seconds=60,
                        )
                    def _apply_ln():
                        if not top.winfo_exists():
                            return
                        btn_quick_launch.config(state="normal")
                        if ok_ln:
                            messagebox.showinfo(t("remote_header"), f"✅ {msg_ln}", parent=top)
                            top.after(2000, do_refresh_procs)
                        else:
                            messagebox.showerror(t("remote_header"), f"❌ {msg_ln}", parent=top)
                    if top.winfo_exists():
                        top.after(0, _apply_ln)
                threading.Thread(target=launch_worker, daemon=True).start()

            btn_quick_launch = ttk.Button(
                bot_frame,
                text=t("remote_procs_launch_btn"),
                command=do_quick_launch,
            )
            btn_quick_launch.pack(side="left")

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

        if hasattr(self, "entry_exchange"):
            self.config.exchange_path = self.entry_exchange.get().strip()
        if hasattr(self, "entry_lan_server"):
            self.config.lan_server_host = self.entry_lan_server.get().strip()
        if hasattr(self, "var_build_sync"):
            self.config.build_sync_enabled = self.var_build_sync.get()
        if hasattr(self, "entry_output"):
            self.config.output_path = self.entry_output.get().strip()
            self.config.local_path = self.entry_output.get().strip()
        elif hasattr(self, "entry_local"):
            self.config.local_path = self.entry_local.get().strip()
            self.config.output_path = self.entry_local.get().strip()

        if hasattr(self, "entry_output_remote"):
            self.config.output_remote_path = self.entry_output_remote.get().strip()
            self.config.remote_path = self.entry_output_remote.get().strip()
            self.config.backup_remote_path = self.entry_output_remote.get().strip()
        elif hasattr(self, "entry_remote"):
            self.config.remote_path = self.entry_remote.get().strip()
            self.config.backup_remote_path = self.entry_remote.get().strip()

        if hasattr(self, "var_auto_copy_link"):
            self.config.auto_copy_share_link = self.var_auto_copy_link.get()

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
                if not any(p in ("speed_server*", "speed_server", "*speed_server*") for p in raw_patterns):
                    raw_patterns.append("speed_server*")
                self.config.set("ignore_patterns", raw_patterns)


        if hasattr(self, "var_rc_enabled"):
            self.config.remote_control_enabled = self.var_rc_enabled.get()
        if hasattr(self, "entry_rc_name"):
            self.config.remote_control_device_name = self.entry_rc_name.get().strip()
        if hasattr(self, "var_rc_reboot"):
            self.config.remote_control_allow_reboot = self.var_rc_reboot.get()
        if hasattr(self, "var_rc_procs"):
            self.config.remote_control_allow_process_list = self.var_rc_procs.get()
        if hasattr(self, "var_rc_strict_wl"):
            self.config.remote_control_strict_whitelist = self.var_rc_strict_wl.get()
        if hasattr(self, "listbox_wl"):
            self.config.remote_control_whitelist = list(self.listbox_wl.get(0, tk.END))
        if hasattr(self, "var_rc_launch"):
            self.config.remote_control_allow_launch = self.var_rc_launch.get()
        if hasattr(self, "_local_launch_apps"):
            self.config.remote_control_launch_apps = list(self._local_launch_apps)

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

        if hasattr(self, "entry_exchange"):
            self.entry_exchange.delete(0, tk.END)
            self.entry_exchange.insert(0, str(getattr(self.config, "exchange_path", "")))
        if hasattr(self, "entry_lan_server"):
            current_lan = self.config.lan_server_host or self._get_initial_lan_host()
            self.entry_lan_server.delete(0, tk.END)
            self.entry_lan_server.insert(0, current_lan)
            self._update_lan_paths()
        if hasattr(self, "entry_output"):
            self.entry_output.delete(0, tk.END)
            self.entry_output.insert(0, str(getattr(self.config, "output_path", "")))
        elif hasattr(self, "entry_local"):
            self.entry_local.delete(0, tk.END)
            self.entry_local.insert(0, str(self.config.local_path))

        if hasattr(self, "entry_output_remote"):
            self.entry_output_remote.delete(0, tk.END)
            self.entry_output_remote.insert(0, getattr(self.config, "output_remote_path", "/Output"))
        elif hasattr(self, "entry_remote"):
            self.entry_remote.delete(0, tk.END)
            self.entry_remote.insert(0, self.config.remote_path)

        if hasattr(self, "var_auto_copy_link"):
            self.var_auto_copy_link.set(getattr(self.config, "auto_copy_share_link", True))

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

        if hasattr(self, "var_rc_enabled"):
            self.var_rc_enabled.set(self.config.remote_control_enabled)
        if hasattr(self, "entry_rc_name"):
            self.entry_rc_name.delete(0, tk.END)
            self.entry_rc_name.insert(0, self.config.remote_control_device_name)
        if hasattr(self, "var_rc_reboot"):
            self.var_rc_reboot.set(self.config.remote_control_allow_reboot)
        if hasattr(self, "var_rc_procs"):
            self.var_rc_procs.set(self.config.remote_control_allow_process_list)
        if hasattr(self, "var_rc_strict_wl"):
            self.var_rc_strict_wl.set(self.config.remote_control_strict_whitelist)
        if hasattr(self, "listbox_wl"):
            self.listbox_wl.delete(0, tk.END)
            for itm in self.config.remote_control_whitelist:
                self.listbox_wl.insert(tk.END, itm)
        if hasattr(self, "var_rc_launch"):
            self.var_rc_launch.set(self.config.remote_control_allow_launch)
        if hasattr(self, "tree_launch_apps"):
            self._local_launch_apps = list(self.config.remote_control_launch_apps)
            for itm in self.tree_launch_apps.get_children():
                self.tree_launch_apps.delete(itm)
            for app in self._local_launch_apps:
                self.tree_launch_apps.insert("", "end", values=(app.get("name", ""), app.get("path", ""), app.get("args", "")))
        if hasattr(self, "lbl_rc_pin_val"):
            has_pin = bool(self.config.remote_control_pin)
            self.lbl_rc_pin_val.config(
                text="●●●●●●●● (OK)" if has_pin else f"●●●● ({t('remote_pin_not_set')})",
                bg="#EBF3FB" if has_pin else "#FDE8E8",
                fg="#0067C0" if has_pin else "#C81E1E",
            )

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

