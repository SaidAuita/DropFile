"""
Modern Tkinter Settings and Activity Log dialog for DropFile.
Allows configuring server credentials, local & remote folders,
connection testing, autostart, and viewing synchronization logs.
"""

import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional

from config import Config
from fb_client import FileBrowserClient
from state_db import StateDatabase
from win_utils import (
    create_desktop_shortcut,
    is_windows_autostart_enabled,
    open_folder_in_explorer,
    set_windows_autostart,
)


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
        self.window.title("DropFile — Настройки и состояние")
        self.window.geometry("580x520")
        self.window.minsize(520, 480)

        # Use clean ttk styling
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Colors
        bg_color = "#F8F9FA"
        accent_color = "#1A73E8"
        self.window.configure(bg=bg_color)

        style.configure("TNotebook", background=bg_color)
        style.configure("TNotebook.Tab", padding=[16, 8], font=("Segoe UI", 9, "bold"))
        style.configure("TFrame", background=bg_color)
        style.configure("TLabel", background=bg_color, font=("Segoe UI", 9))
        style.configure("Header.TLabel", font=("Segoe UI", 11, "bold"), foreground="#202124")
        style.configure("Accent.TButton", font=("Segoe UI", 9, "bold"))

        notebook = ttk.Notebook(self.window)
        notebook.pack(fill="both", expand=True, padx=12, pady=12)

        # Tab 1: Connection
        tab_conn = ttk.Frame(notebook, padding=16)
        notebook.add(tab_conn, text="  Подключение  ")
        self._build_connection_tab(tab_conn)

        # Tab 2: Folders
        tab_folders = ttk.Frame(notebook, padding=16)
        notebook.add(tab_folders, text="  Папки  ")
        self._build_folders_tab(tab_folders)

        # Tab 3: Settings
        tab_settings = ttk.Frame(notebook, padding=16)
        notebook.add(tab_settings, text="  Параметры  ")
        self._build_settings_tab(tab_settings)

        # Tab 4: History / Log
        tab_log = ttk.Frame(notebook, padding=12)
        notebook.add(tab_log, text="  Журнал синхронизации  ")
        self._build_log_tab(tab_log)

        # Bottom button bar
        bottom_bar = ttk.Frame(self.window, padding=(12, 0, 12, 12))
        bottom_bar.pack(fill="x", side="bottom")

        btn_save = ttk.Button(
            bottom_bar, text="Сохранить и применить", style="Accent.TButton", command=self._save_and_close
        )
        btn_save.pack(side="right", padx=(6, 0))

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
        ttk.Label(parent, text="Сервер FileBrowser (HTTPS)", style="Header.TLabel").pack(
            anchor="w", pady=(0, 10)
        )

        ttk.Label(parent, text="Адрес сервера:").pack(anchor="w", pady=(4, 2))
        self.entry_url = ttk.Entry(parent, width=50)
        self.entry_url.insert(0, self.config.server_url)
        self.entry_url.pack(fill="x", pady=(0, 8))

        ttk.Label(parent, text="Имя пользователя:").pack(anchor="w", pady=(4, 2))
        self.entry_user = ttk.Entry(parent, width=50)
        self.entry_user.insert(0, self.config.username)
        self.entry_user.pack(fill="x", pady=(0, 8))

        ttk.Label(parent, text="Пароль:").pack(anchor="w", pady=(4, 2))
        self.entry_pwd = ttk.Entry(parent, width=50, show="•")
        self.entry_pwd.insert(0, self.config.password)
        self.entry_pwd.pack(fill="x", pady=(0, 12))

        # Test Connection button & status
        test_frame = ttk.Frame(parent)
        test_frame.pack(fill="x", pady=(8, 0))

        self.btn_test = ttk.Button(test_frame, text="⚡ Проверить соединение", command=self._test_connection)
        self.btn_test.pack(side="left")

        self.lbl_test_status = ttk.Label(
            test_frame, text="", font=("Segoe UI", 9, "bold"), foreground="#5F6368"
        )
        self.lbl_test_status.pack(side="left", padx=(12, 0), fill="x", expand=True)

    def _test_connection(self) -> None:
        self.lbl_test_status.config(text="Проверка связи...", foreground="#1A73E8")
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
            self.lbl_test_status.config(text="✔ Подключено успешно!", foreground="#28A745")
        else:
            self.lbl_test_status.config(text=f"✖ {msg}", foreground="#DC3545")

    def _build_folders_tab(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Каталоги для обмена файлами", style="Header.TLabel").pack(
            anchor="w", pady=(0, 10)
        )

        ttk.Label(parent, text="Локальная папка на этом компьютере:").pack(anchor="w", pady=(4, 2))
        local_row = ttk.Frame(parent)
        local_row.pack(fill="x", pady=(0, 6))

        self.entry_local = ttk.Entry(local_row)
        self.entry_local.insert(0, str(self.config.local_path))
        self.entry_local.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_browse = ttk.Button(local_row, text="Обзор...", command=self._browse_local_folder)
        btn_browse.pack(side="right")

        # Local folder helper buttons
        btns_row = ttk.Frame(parent)
        btns_row.pack(fill="x", pady=(0, 16))

        btn_open = ttk.Button(
            btns_row, text="📂 Открыть папку", command=lambda: open_folder_in_explorer(self.entry_local.get())
        )
        btn_open.pack(side="left", padx=(0, 6))

        btn_shortcut = ttk.Button(
            btns_row, text="🔗 Создать ярлык на Рабочем столе", command=self._create_shortcut
        )
        btn_shortcut.pack(side="left")

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(8, 12))

        ttk.Label(parent, text="Удаленная папка на сервере (FileBrowser):").pack(anchor="w", pady=(4, 2))
        self.entry_remote = ttk.Entry(parent)
        self.entry_remote.insert(0, self.config.remote_path)
        self.entry_remote.pack(fill="x", pady=(0, 4))
        ttk.Label(
            parent,
            text="Пример: /Exchange или / (корневой каталог). Папка будет создана автоматически, если ее нет.",
            font=("Segoe UI", 8),
            foreground="#5F6368",
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
            )
        else:
            messagebox.showerror("Ошибка", "Не удалось создать ярлык.")

    def _build_settings_tab(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Параметры синхронизации", style="Header.TLabel").pack(
            anchor="w", pady=(0, 12)
        )

        # Poll interval
        poll_frame = ttk.Frame(parent)
        poll_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(poll_frame, text="Период проверки удаленных изменений (секунды):").pack(
            side="left", padx=(0, 8)
        )
        self.spin_poll = ttk.Spinbox(poll_frame, from_=5, to=3600, width=8)
        self.spin_poll.set(self.config.poll_interval)
        self.spin_poll.pack(side="left")

        # Autostart checkbox
        self.var_autostart = tk.BooleanVar(value=is_windows_autostart_enabled())
        chk_auto = ttk.Checkbutton(
            parent, text="Запускать DropFile автоматически при старте Windows", variable=self.var_autostart
        )
        chk_auto.pack(anchor="w", pady=(4, 6))

        # Notifications checkbox
        self.var_notify = tk.BooleanVar(value=self.config.notify_on_sync)
        chk_notify = ttk.Checkbutton(
            parent, text="Показывать всплывающие уведомления при передаче файлов", variable=self.var_notify
        )
        chk_notify.pack(anchor="w", pady=(4, 12))

        ttk.Label(parent, text="Игнорируемые файлы (шаблоны через запятую):").pack(anchor="w", pady=(4, 2))
        self.entry_ignore = ttk.Entry(parent)
        self.entry_ignore.insert(0, ", ".join(self.config.ignore_patterns))
        self.entry_ignore.pack(fill="x", pady=(0, 4))

    def _build_log_tab(self, parent: ttk.Frame) -> None:
        header_row = ttk.Frame(parent)
        header_row.pack(fill="x", pady=(0, 6))
        ttk.Label(header_row, text="Последние действия:", style="Header.TLabel").pack(side="left")

        btn_refresh = ttk.Button(header_row, text="Обновить", command=self._refresh_logs)
        btn_refresh.pack(side="right")

        # Treeview
        cols = ("time", "action", "direction", "file", "status")
        self.tree_log = ttk.Treeview(parent, columns=cols, show="headings", height=12)

        self.tree_log.heading("time", text="Время")
        self.tree_log.heading("action", text="Действие")
        self.tree_log.heading("direction", text="Направление")
        self.tree_log.heading("file", text="Файл")
        self.tree_log.heading("status", text="Статус")

        self.tree_log.column("time", width=110, anchor="center")
        self.tree_log.column("action", width=70, anchor="center")
        self.tree_log.column("direction", width=90, anchor="center")
        self.tree_log.column("file", width=180, anchor="w")
        self.tree_log.column("status", width=70, anchor="center")

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

    def _save_and_close(self) -> None:
        # Save to config object
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

        # Update ignore patterns
        raw_patterns = [p.strip() for p in self.entry_ignore.get().split(",") if p.strip()]
        if raw_patterns:
            self.config.set("ignore_patterns", raw_patterns)

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
