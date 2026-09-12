"""
Modern Tkinter Settings and Activity Log dialog for DropFile.
Features native Windows 10/11 visual styles, high-DPI scaling,
connection testing, backup/restore, autostart, and live logs.
"""

import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional

from config import Config
from fb_client import FileBrowserClient
from state_db import StateDatabase
from version import __version__
from win_utils import (
    create_desktop_shortcut,
    is_windows_autostart_enabled,
    open_folder_in_explorer,
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


class SettingsDialog:
    def __init__(
        self,
        config: Config,
        state_db: StateDatabase,
        client: FileBrowserClient,
        on_save_callback: Optional[Callable[[], None]] = None,
    ):
        self.config = config
        self.state_db = state_db
        self.client = client
        self.on_save_callback = on_save_callback
        self.window: Optional[tk.Tk] = None

    def show(self) -> None:
        if self.window is not None and self.window.winfo_exists():
            self.window.lift()
            self.window.focus_force()
            return

        self.window = tk.Tk()
        self.window.title(f"DropFile v{__version__} — Настройки")
        self.window.geometry("640x580")
        self.window.minsize(580, 520)

        # Apply native Windows visual style
        style = ttk.Style()
        for theme_name in ("vista", "winnative", "clam"):
            if theme_name in style.theme_names():
                try:
                    style.theme_use(theme_name)
                    break
                except Exception:
                    pass

        # Windows 11 Fluent UI color scheme
        bg_window = "#F3F3F3"
        bg_card = "#FFFFFF"
        fg_text = "#1C1C1C"
        fg_muted = "#5F6368"
        accent_blue = "#0067C0"

        self.window.configure(bg=bg_window)

        # Typography configuration
        style.configure("TNotebook", background=bg_window)
        style.configure("TNotebook.Tab", padding=[16, 7], font=("Segoe UI", 9))
        style.configure("TFrame", background=bg_window)
        style.configure("Card.TFrame", background=bg_card)
        style.configure("TLabel", background=bg_window, font=("Segoe UI", 9), foreground=fg_text)
        style.configure("Card.TLabel", background=bg_card, font=("Segoe UI", 9), foreground=fg_text)
        style.configure(
            "Header.TLabel", background=bg_card, font=("Segoe UI", 10, "bold"), foreground="#202124"
        )
        style.configure(
            "Subheader.TLabel", background=bg_card, font=("Segoe UI", 8), foreground=fg_muted
        )
        style.configure("TButton", font=("Segoe UI", 9))
        style.configure("Accent.TButton", font=("Segoe UI", 9, "bold"))
        style.configure("TCheckbutton", background=bg_card, font=("Segoe UI", 9), foreground=fg_text)

        # --- Top Header Bar ---
        header_bar = tk.Frame(self.window, bg="#FFFFFF", padx=20, pady=12)
        header_bar.pack(fill="x", side="top")

        title_row = tk.Frame(header_bar, bg="#FFFFFF")
        title_row.pack(fill="x")

        lbl_app_title = tk.Label(
            title_row,
            text="DropFile",
            font=("Segoe UI", 14, "bold"),
            fg="#1A1A1A",
            bg="#FFFFFF",
        )
        lbl_app_title.pack(side="left")

        # Version Pill Badge
        lbl_version_badge = tk.Label(
            title_row,
            text=f"v{__version__}",
            font=("Segoe UI", 8, "bold"),
            fg=accent_blue,
            bg="#EBF3FB",
            padx=8,
            pady=2,
        )
        lbl_version_badge.pack(side="left", padx=(10, 0))

        lbl_app_subtitle = tk.Label(
            header_bar,
            text="Двусторонняя Dropbox-подобная синхронизация с сервером FileBrowser",
            font=("Segoe UI", 9),
            fg=fg_muted,
            bg="#FFFFFF",
        )
        lbl_app_subtitle.pack(anchor="w", pady=(2, 0))

        # Divider under header
        tk.Frame(self.window, height=1, bg="#E5E5E5").pack(fill="x", side="top")

        # --- Tab Notebook ---
        notebook = ttk.Notebook(self.window)
        notebook.pack(fill="both", expand=True, padx=14, pady=12)

        # Tab 1: Connection
        tab_conn = ttk.Frame(notebook, padding=14, style="Card.TFrame")
        notebook.add(tab_conn, text=" 🌐 Подключение ")
        self._build_connection_tab(tab_conn)

        # Tab 2: Folders
        tab_folders = ttk.Frame(notebook, padding=14, style="Card.TFrame")
        notebook.add(tab_folders, text=" 📁 Папки ")
        self._build_folders_tab(tab_folders)

        # Tab 3: Settings & Backup
        tab_settings = ttk.Frame(notebook, padding=14, style="Card.TFrame")
        notebook.add(tab_settings, text=" ⚙ Параметры ")
        self._build_settings_tab(tab_settings)

        # Tab 4: History / Log
        tab_log = ttk.Frame(notebook, padding=12, style="Card.TFrame")
        notebook.add(tab_log, text=" 📋 Журнал ")
        self._build_log_tab(tab_log)

        # --- Bottom Action Bar ---
        tk.Frame(self.window, height=1, bg="#E5E5E5").pack(fill="x", side="bottom")
        bottom_bar = tk.Frame(self.window, bg=bg_window, padx=16, pady=12)
        bottom_bar.pack(fill="x", side="bottom")

        btn_save = ttk.Button(
            bottom_bar,
            text="Сохранить и применить",
            style="Accent.TButton",
            command=self._save_and_close,
        )
        btn_save.pack(side="right", padx=(8, 0))

        btn_cancel = ttk.Button(bottom_bar, text="Закрыть", command=self.window.destroy)
        btn_cancel.pack(side="right")

        # Center on screen
        self.window.update_idletasks()
        w = self.window.winfo_width()
        h = self.window.winfo_height()
        x = (self.window.winfo_screenwidth() // 2) - (w // 2)
        y = (self.window.winfo_screenheight() // 2) - (h // 2)
        self.window.geometry(f"+{x}+{y}")

        self.window.mainloop()

    def _build_connection_tab(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Параметры сервера FileBrowser", style="Header.TLabel").pack(
            anchor="w", pady=(0, 2)
        )
        ttk.Label(
            parent,
            text="Укажите URL адрес вашего сервера (HTTPS или HTTP) и учетные данные учетной записи.",
            style="Subheader.TLabel",
        ).pack(anchor="w", pady=(0, 14))

        # Server URL
        ttk.Label(parent, text="Адрес сервера (URL):", style="Card.TLabel").pack(anchor="w", pady=(0, 2))
        self.entry_url = ttk.Entry(parent, font=("Segoe UI", 9))
        self.entry_url.insert(0, self.config.server_url)
        self.entry_url.pack(fill="x", pady=(0, 10))

        # Username
        ttk.Label(parent, text="Имя пользователя:", style="Card.TLabel").pack(anchor="w", pady=(0, 2))
        self.entry_user = ttk.Entry(parent, font=("Segoe UI", 9))
        self.entry_user.insert(0, self.config.username)
        self.entry_user.pack(fill="x", pady=(0, 10))

        # Password
        ttk.Label(parent, text="Пароль:", style="Card.TLabel").pack(anchor="w", pady=(0, 2))
        self.entry_pwd = ttk.Entry(parent, font=("Segoe UI", 9), show="•")
        self.entry_pwd.insert(0, self.config.password)
        self.entry_pwd.pack(fill="x", pady=(0, 16))

        # Test Connection button & status indicator
        test_frame = tk.Frame(parent, bg="#FFFFFF")
        test_frame.pack(fill="x")

        self.btn_test = ttk.Button(test_frame, text="⚡ Проверить соединение", command=self._test_connection)
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
        self.lbl_test_status.config(text="Проверка связи с сервером...", fg="#0067C0")
        self.btn_test.config(state="disabled")

        url = self.entry_url.get().strip()
        user = self.entry_user.get().strip()
        pwd = self.entry_pwd.get()

        def worker():
            test_client = FileBrowserClient(base_url=url, username=user, password=pwd, timeout=8)
            ok, msg = test_client.test_connection()
            if self.window and self.window.winfo_exists():
                self.window.after(0, lambda: self._on_test_done(ok, msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_test_done(self, ok: bool, msg: str) -> None:
        self.btn_test.config(state="normal")
        if ok:
            self.lbl_test_status.config(text="✔ Соединение успешно установлено!", fg="#0F7B0F")
        else:
            self.lbl_test_status.config(text=f"✖ {msg}", fg="#C42B1C")

    def _build_folders_tab(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Каталоги для синхронизации", style="Header.TLabel").pack(
            anchor="w", pady=(0, 2)
        )
        ttk.Label(
            parent,
            text="Файлы, добавленные в локальную папку, мгновенно отправляются на сервер и другие ПК.",
            style="Subheader.TLabel",
        ).pack(anchor="w", pady=(0, 14))

        # Local folder
        ttk.Label(parent, text="Локальная папка на этом компьютере:", style="Card.TLabel").pack(
            anchor="w", pady=(0, 2)
        )
        local_row = tk.Frame(parent, bg="#FFFFFF")
        local_row.pack(fill="x", pady=(0, 8))

        self.entry_local = ttk.Entry(local_row, font=("Segoe UI", 9))
        self.entry_local.insert(0, str(self.config.local_path))
        self.entry_local.pack(side="left", fill="x", expand=True, padx=(0, 8))

        btn_browse = ttk.Button(local_row, text="Обзор...", command=self._browse_local_folder)
        btn_browse.pack(side="right")

        # Action helpers for local folder
        btns_row = tk.Frame(parent, bg="#FFFFFF")
        btns_row.pack(fill="x", pady=(0, 16))

        btn_open = ttk.Button(
            btns_row,
            text="📂 Открыть папку в Проводнике",
            command=lambda: open_folder_in_explorer(self.entry_local.get()),
        )
        btn_open.pack(side="left", padx=(0, 8))

        btn_shortcut = ttk.Button(
            btns_row, text="🔗 Создать ярлык на Рабочем столе", command=self._create_shortcut
        )
        btn_shortcut.pack(side="left")

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(4, 14))

        # Remote folder
        ttk.Label(parent, text="Удаленный каталог в FileBrowser:", style="Card.TLabel").pack(
            anchor="w", pady=(0, 2)
        )
        self.entry_remote = ttk.Entry(parent, font=("Segoe UI", 9))
        self.entry_remote.insert(0, self.config.remote_path)
        self.entry_remote.pack(fill="x", pady=(0, 4))
        ttk.Label(
            parent,
            text="Например: /DropFile или /Exchange. Папка создается автоматически, если ее нет.",
            style="Subheader.TLabel",
        ).pack(anchor="w")

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
                "Ярлык создан",
                f"Ярлык 'DropFile' успешно добавлен на ваш Рабочий стол!\nПапка: {path}",
                parent=self.window,
            )
        else:
            messagebox.showerror("Ошибка", "Не удалось создать ярлык.", parent=self.window)

    def _build_settings_tab(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Параметры работы", style="Header.TLabel").pack(anchor="w", pady=(0, 10))

        # Poll interval
        poll_frame = tk.Frame(parent, bg="#FFFFFF")
        poll_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(poll_frame, text="Период проверки удаленных изменений (секунды):", style="Card.TLabel").pack(
            side="left", padx=(0, 10)
        )
        self.spin_poll = ttk.Spinbox(poll_frame, from_=5, to=3600, width=8, font=("Segoe UI", 9))
        self.spin_poll.set(self.config.poll_interval)
        self.spin_poll.pack(side="left")

        # Checkboxes
        self.var_autostart = tk.BooleanVar(value=is_windows_autostart_enabled())
        chk_auto = ttk.Checkbutton(
            parent,
            text="Запускать DropFile автоматически при старте Windows",
            variable=self.var_autostart,
            style="TCheckbutton",
        )
        chk_auto.pack(anchor="w", pady=(4, 6))

        self.var_notify = tk.BooleanVar(value=self.config.notify_on_sync)
        chk_notify = ttk.Checkbutton(
            parent,
            text="Показывать всплывающие уведомления при передаче файлов",
            variable=self.var_notify,
            style="TCheckbutton",
        )
        chk_notify.pack(anchor="w", pady=(4, 10))

        # Ignore patterns
        ttk.Label(parent, text="Игнорируемые файлы (шаблоны через запятую):", style="Card.TLabel").pack(
            anchor="w", pady=(0, 2)
        )
        self.entry_ignore = ttk.Entry(parent, font=("Segoe UI", 9))
        self.entry_ignore.insert(0, ", ".join(self.config.ignore_patterns))
        self.entry_ignore.pack(fill="x", pady=(0, 14))

        # Backup / Restore settings section
        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(2, 12))
        ttk.Label(parent, text="Резервная копия настроек", style="Header.TLabel").pack(
            anchor="w", pady=(0, 2)
        )
        ttk.Label(
            parent,
            text="Сохранение настроек в файл и восстановление (удобно для обновлений и переноса на другой ПК):",
            style="Subheader.TLabel",
        ).pack(anchor="w", pady=(0, 8))

        backup_row = tk.Frame(parent, bg="#FFFFFF")
        backup_row.pack(fill="x")

        btn_export = ttk.Button(
            backup_row, text="💾 Сохранить в файл...", command=self._export_settings
        )
        btn_export.pack(side="left", padx=(0, 8))

        btn_import = ttk.Button(
            backup_row, text="📥 Загрузить из файла...", command=self._import_settings
        )
        btn_import.pack(side="left")

    def _build_log_tab(self, parent: ttk.Frame) -> None:
        header_row = tk.Frame(parent, bg="#FFFFFF")
        header_row.pack(fill="x", pady=(0, 8))
        ttk.Label(header_row, text="Последние действия синхронизации:", style="Header.TLabel").pack(
            side="left"
        )

        btn_refresh = ttk.Button(header_row, text="🔄 Обновить", command=self._refresh_logs)
        btn_refresh.pack(side="right")

        # Treeview
        cols = ("time", "action", "direction", "file", "status")
        self.tree_log = ttk.Treeview(parent, columns=cols, show="headings", height=12)

        self.tree_log.heading("time", text="Время")
        self.tree_log.heading("action", text="Действие")
        self.tree_log.heading("direction", text="Направление")
        self.tree_log.heading("file", text="Файл")
        self.tree_log.heading("status", text="Статус")

        self.tree_log.column("time", width=100, anchor="center")
        self.tree_log.column("action", width=75, anchor="center")
        self.tree_log.column("direction", width=95, anchor="center")
        self.tree_log.column("file", width=220, anchor="w")
        self.tree_log.column("status", width=75, anchor="center")

        scroll = ttk.Scrollbar(parent, orient="vertical", command=self.tree_log.yview)
        self.tree_log.configure(yscrollcommand=scroll.set)

        self.tree_log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self._refresh_logs()

    def _refresh_logs(self) -> None:
        for row in self.tree_log.get_children():
            self.tree_log.delete(row)

        records = self.state_db.get_recent_history(limit=50)
        action_names = {
            "upload": "Выгрузка",
            "download": "Загрузка",
            "delete": "Удаление",
            "conflict": "Конфликт",
        }
        for r in records:
            ts = datetime.fromtimestamp(r["timestamp"]).strftime("%H:%M:%S")
            act = action_names.get(r["action"], r["action"])
            stat = "Успешно" if r["status"] == "success" else r["status"]
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

        self.config.notify_on_sync = self.var_notify.get()
        self.config.start_with_windows = self.var_autostart.get()

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
        self.var_autostart.set(self.config.start_with_windows)
        self.var_notify.set(self.config.notify_on_sync)

        self.entry_ignore.delete(0, tk.END)
        self.entry_ignore.insert(0, ", ".join(self.config.ignore_patterns))

    def _export_settings(self) -> None:
        """Exports current settings to a user-chosen backup JSON file."""
        self._read_form_into_config()
        chosen = filedialog.asksaveasfilename(
            parent=self.window,
            title="Сохранить настройки DropFile",
            defaultextension=".json",
            initialfile="dropfile_backup.json",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
        )
        if not chosen:
            return

        ok = self.config.export_config(chosen)
        if ok:
            messagebox.showinfo(
                "Экспорт завершен",
                f"Настройки успешно сохранены в файл:\n{chosen}",
                parent=self.window,
            )
        else:
            messagebox.showerror("Ошибка", "Не удалось сохранить файл настроек.", parent=self.window)

    def _import_settings(self) -> None:
        """Imports settings from a backup JSON file and updates UI and client."""
        chosen = filedialog.askopenfilename(
            parent=self.window,
            title="Выберите файл настроек DropFile для восстановления",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
        )
        if not chosen:
            return

        ok = self.config.import_config(chosen)
        if ok:
            self._populate_form_fields()
            self.client.base_url = self.config.server_url
            self.client.username = self.config.username
            self.client.password = self.config.password
            self.client.token = None
            set_windows_autostart(self.config.start_with_windows)
            messagebox.showinfo(
                "Импорт завершен",
                "Настройки успешно загружены из файла и применены!",
                parent=self.window,
            )
        else:
            messagebox.showerror(
                "Ошибка",
                "Не удалось прочитать выбранный файл настроек. Проверьте правильность формата JSON.",
                parent=self.window,
            )

    def _save_and_close(self) -> None:
        self._read_form_into_config()
        self.config.save()

        # Update Windows autostart registry
        set_windows_autostart(self.var_autostart.get())

        # Update client
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
