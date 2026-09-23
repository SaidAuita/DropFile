"""
GUI dialogs for Build Drops Synchronization in DropFile.
Features modern clean Tkinter styling, responsive Treeview,
task add/edit modal dialogs, and instant validation.
"""

import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Dict, List, Optional
import threading
import uuid

from config import Config
from i18n import t
from platform_utils import get_default_lan_server_host


class BuildTaskEditDialog(tk.Toplevel):
    """Modal dialog for creating or editing a Build Sync Task."""

    def __init__(
        self,
        parent: tk.Misc,
        task_data: Optional[Dict[str, Any]] = None,
        default_target_base: str = "",
        on_save_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        super().__init__(parent)
        self.task_data = task_data or {}
        self.default_target_base = default_target_base
        self.on_save_callback = on_save_callback
        self.result: Optional[Dict[str, Any]] = None

        is_edit = bool(self.task_data.get("id"))
        title_text = t("build_sync_task_dlg_title_edit") if is_edit else t("build_sync_task_dlg_title_add")
        self.title(title_text)

        self.transient(parent)
        self.grab_set()
        self.resizable(True, True)

        font_family = "Segoe UI" if sys.platform.startswith("win") else "Helvetica"
        self.font_family = font_family

        self.configure(bg="#F3F3F3")
        self._build_ui()

        # Keyboard shortcuts
        self.bind("<Return>", lambda e: self._on_save())
        self.bind("<Escape>", lambda e: self.destroy())

        # Geometry & centering
        self.geometry("600x500")
        self.minsize(520, 440)
        self.update_idletasks()
        try:
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            w = self.winfo_width()
            h = self.winfo_height()
            x = max(0, px + (pw - w) // 2)
            y = max(0, py + (ph - h) // 2)
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

        self.focus_force()

    def _build_ui(self) -> None:
        # Bottom Buttons (packed first with side="bottom" so they are ALWAYS fixed and visible at the bottom)
        row_bottom = tk.Frame(self, bg="#F3F3F3", padx=16, pady=12)
        row_bottom.pack(fill="x", side="bottom")

        btn_save = ttk.Button(row_bottom, text=f"✔ {t('btn_save_apply')}", style="Accent.TButton", command=self._on_save)
        btn_save.pack(side="right", padx=(8, 0))

        btn_cancel = ttk.Button(row_bottom, text=t("btn_close"), command=self.destroy)
        btn_cancel.pack(side="right")

        tk.Frame(self, height=1, bg="#E5E5E5").pack(fill="x", side="bottom")

        # Main Card (fills available space above the bottom bar)
        card = tk.Frame(self, bg="#FFFFFF", padx=16, pady=16)
        card.pack(fill="both", expand=True, padx=12, pady=12)

        # 1. Project Name
        lbl_name = tk.Label(card, text=t("build_sync_lbl_name"), bg="#FFFFFF", font=(self.font_family, 9, "bold"), anchor="w")
        lbl_name.pack(fill="x", pady=(0, 2))

        self.entry_name = ttk.Entry(card, font=(self.font_family, 9))
        self.entry_name.insert(0, self.task_data.get("name", ""))
        self.entry_name.pack(fill="x", pady=(0, 8))
        self.entry_name.bind("<KeyRelease>", self._on_name_change)

        # 2. Source Build Directory
        lbl_src = tk.Label(card, text=t("build_sync_lbl_source"), bg="#FFFFFF", font=(self.font_family, 9, "bold"), anchor="w")
        lbl_src.pack(fill="x", pady=(0, 2))

        row_src = tk.Frame(card, bg="#FFFFFF")
        row_src.pack(fill="x", pady=(0, 8))

        self.entry_source = ttk.Entry(row_src, font=(self.font_family, 9))
        self.entry_source.insert(0, self.task_data.get("source_dir", ""))
        self.entry_source.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_browse_src = ttk.Button(row_src, text=t("folders_browse_btn"), command=self._browse_source)
        btn_browse_src.pack(side="right")

        # 3. Pattern
        lbl_pat = tk.Label(card, text=t("build_sync_lbl_pattern"), bg="#FFFFFF", font=(self.font_family, 9, "bold"), anchor="w")
        lbl_pat.pack(fill="x", pady=(0, 2))

        self.entry_pattern = ttk.Entry(card, font=(self.font_family, 9))
        self.entry_pattern.insert(0, self.task_data.get("pattern", "*.zip"))
        self.entry_pattern.pack(fill="x", pady=(0, 8))

        # 4. Target Server Folder
        lbl_tgt = tk.Label(card, text=t("build_sync_lbl_target"), bg="#FFFFFF", font=(self.font_family, 9, "bold"), anchor="w")
        lbl_tgt.pack(fill="x", pady=(0, 2))

        row_tgt = tk.Frame(card, bg="#FFFFFF")
        row_tgt.pack(fill="x", pady=(0, 2))

        self.entry_target = ttk.Entry(row_tgt, font=(self.font_family, 9))
        tgt_val = self.task_data.get("target_dir", "")
        self.entry_target.insert(0, tgt_val)
        self.entry_target.pack(side="left", fill="x", expand=True, padx=(0, 6))

        btn_browse_tgt = ttk.Button(row_tgt, text=t("folders_browse_btn"), command=self._browse_target)
        btn_browse_tgt.pack(side="right")

        lbl_hint = tk.Label(card, text=t("build_sync_lbl_target_hint"), bg="#FFFFFF", fg="#5F6368", font=(self.font_family, 8), anchor="w")
        lbl_hint.pack(fill="x", pady=(0, 8))

        # 5. Keep N versions & Enabled checkbox
        row_opt = tk.Frame(card, bg="#FFFFFF")
        row_opt.pack(fill="x", pady=(0, 10))

        lbl_keep = tk.Label(row_opt, text=t("build_sync_lbl_keep"), bg="#FFFFFF", font=(self.font_family, 9), anchor="w")
        lbl_keep.pack(side="left", padx=(0, 6))

        self.spin_keep = ttk.Spinbox(row_opt, from_=1, to=50, width=5, font=(self.font_family, 9))
        self.spin_keep.set(str(self.task_data.get("keep_versions", 5)))
        self.spin_keep.pack(side="left", padx=(0, 20))

        self.var_enabled = tk.BooleanVar(value=bool(self.task_data.get("enabled", True)))
        chk_enabled = ttk.Checkbutton(row_opt, text=t("build_sync_chk_task_enable"), variable=self.var_enabled)
        chk_enabled.pack(side="left")

    def _on_name_change(self, event=None) -> None:
        """If target is empty and default target base exists, suggest path."""
        if not self.entry_target.get().strip() and self.default_target_base:
            name = self.entry_name.get().strip()
            if name:
                safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name)
                suggested = str(Path(self.default_target_base) / safe_name)
                self.entry_target.insert(0, suggested)

    def _browse_source(self) -> None:
        chosen = filedialog.askdirectory(parent=self, title=t("build_sync_lbl_source"))
        if chosen:
            self.entry_source.delete(0, "end")
            self.entry_source.insert(0, str(Path(chosen)))
            if not self.entry_name.get().strip():
                # Auto-fill project name from parent or folder name
                p = Path(chosen)
                suggested = p.parent.name if p.name.lower() in ("build", "build_dev", "bin", "publish", "out") else p.name
                self.entry_name.delete(0, "end")
                self.entry_name.insert(0, suggested)
                self._on_name_change()

    def _browse_target(self) -> None:
        chosen = filedialog.askdirectory(parent=self, title=t("build_sync_lbl_target"))
        if chosen:
            self.entry_target.delete(0, "end")
            self.entry_target.insert(0, str(Path(chosen)))

    def _on_save(self) -> None:
        name = self.entry_name.get().strip()
        source = self.entry_source.get().strip()
        target = self.entry_target.get().strip()
        pattern = self.entry_pattern.get().strip() or "*.zip"

        if not name:
            messagebox.showwarning(t("error_title"), t("build_sync_err_name"), parent=self)
            self.entry_name.focus_set()
            return

        if not source:
            messagebox.showwarning(t("error_title"), t("build_sync_err_source"), parent=self)
            self.entry_source.focus_set()
            return

        if not target:
            messagebox.showwarning(t("error_title"), t("build_sync_err_target"), parent=self)
            self.entry_target.focus_set()
            return

        try:
            keep_v = max(1, int(self.spin_keep.get()))
        except Exception:
            keep_v = 5

        task_id = self.task_data.get("id") or str(uuid.uuid4())[:8]

        self.result = {
            "id": task_id,
            "name": name,
            "source_dir": source,
            "pattern": pattern,
            "target_dir": target,
            "keep_versions": keep_v,
            "enabled": self.var_enabled.get(),
        }

        if self.on_save_callback:
            self.on_save_callback(self.result)

        self.destroy()


class BuildSyncDialog:
    """Management window for Build Drops Synchronization tasks."""
    _INSTANCE: Optional["BuildSyncDialog"] = None

    @classmethod
    def show_or_focus(
        cls,
        parent: Optional[tk.Misc] = None,
        config: Optional[Config] = None,
        on_save_callback: Optional[Callable[[], None]] = None,
        build_engine: Optional[Any] = None,
    ) -> "BuildSyncDialog":
        if cls._INSTANCE is not None:
            try:
                if cls._INSTANCE.window is None or not cls._INSTANCE.window.winfo_exists():
                    cls._INSTANCE = None
                else:
                    cls._INSTANCE.window.deiconify()
                    cls._INSTANCE.window.lift()
                    cls._INSTANCE.window.focus_force()
                    return cls._INSTANCE
            except Exception:
                cls._INSTANCE = None

        if config is None:
            config = Config()

        inst = cls(
            parent=parent,
            config=config,
            on_save_callback=on_save_callback,
            build_engine=build_engine,
        )
        cls._INSTANCE = inst
        if getattr(inst, "_owns_root", False):
            try:
                inst.window.mainloop()
            except Exception:
                pass
            finally:
                cls._INSTANCE = None
        return inst

    def __init__(
        self,
        parent: Optional[tk.Misc] = None,
        config: Optional[Config] = None,
        on_save_callback: Optional[Callable[[], None]] = None,
        build_engine: Optional[Any] = None,
    ):
        self.config = config or Config()
        self.on_save_callback = on_save_callback
        self.build_engine = build_engine
        self._owns_root = False
        self.window: Optional[tk.Misc] = None

        if parent is not None:
            try:
                if parent.winfo_exists():
                    self.window = tk.Toplevel(parent)
                else:
                    self.window = tk.Tk()
                    self._owns_root = True
            except Exception:
                self.window = tk.Tk()
                self._owns_root = True
        else:
            try:
                if tk._default_root is not None and tk._default_root.winfo_exists():
                    self.window = tk.Toplevel(tk._default_root)
                else:
                    self.window = tk.Tk()
                    self._owns_root = True
            except Exception:
                self.window = tk.Tk()
                self._owns_root = True

        self.__class__._INSTANCE = self

        self.window.title(f"{t('app_name')} — {t('build_sync_title')}")
        if parent and hasattr(self.window, "transient"):
            try:
                self.window.transient(parent)
            except Exception:
                pass
        self.window.resizable(True, True)
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        font_family = "Segoe UI" if sys.platform.startswith("win") else "Helvetica"
        self.font_family = font_family

        self.window.configure(bg="#F3F3F3")
        self._tasks: List[Dict[str, Any]] = [dict(t) for t in self.config.build_sync_tasks]

        # Set window icon
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

        self._build_ui()
        self._refresh_tree()

        self.window.geometry("720x500")
        self.window.minsize(580, 400)
        self.window.update_idletasks()
        if parent:
            try:
                pw = parent.winfo_width()
                ph = parent.winfo_height()
                px = parent.winfo_rootx()
                py = parent.winfo_rooty()
                w = self.window.winfo_width()
                h = self.window.winfo_height()
                x = max(0, px + (pw - w) // 2)
                y = max(0, py + (ph - h) // 2)
                self.window.geometry(f"{w}x{h}+{x}+{y}")
            except Exception:
                pass
        else:
            try:
                sw = self.window.winfo_screenwidth()
                sh = self.window.winfo_screenheight()
                w = 720
                h = 500
                x = max(0, (sw - w) // 2)
                y = max(0, (sh - h) // 2)
                self.window.geometry(f"{w}x{h}+{x}+{y}")
            except Exception:
                pass

        try:
            self.window.lift()
            self.window.focus_force()
        except Exception:
            pass

    def winfo_exists(self) -> bool:
        return bool(self.window and self.window.winfo_exists())

    def lift(self) -> None:
        if self.window:
            try:
                self.window.lift()
            except Exception:
                pass

    def focus_force(self) -> None:
        if self.window:
            try:
                self.window.focus_force()
            except Exception:
                pass

    def destroy(self) -> None:
        self._on_close()

    def _on_close(self) -> None:
        self.__class__._INSTANCE = None
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
            self.window = None

    def _get_default_target_base(self) -> str:
        """Determines default base destination path (e.g. \\\\host\\Exchange\\Build)."""
        saved_host = getattr(self.config, "lan_server_host", "").strip()
        host = get_default_lan_server_host(saved_host)
        ex_path = getattr(self.config, "exchange_path", "")
        if host:
            return f"\\\\{host}\\Exchange\\Build"
        if ex_path:
            return str(Path(ex_path) / "Build")
        return ""

    def _build_ui(self) -> None:
        # Top Header
        header = tk.Frame(self.window, bg="#FFFFFF", padx=16, pady=12)
        header.pack(fill="x", side="top")

        lbl_title = tk.Label(
            header,
            text=f"📦 {t('build_sync_title')}",
            font=(self.font_family, 12, "bold"),
            bg="#FFFFFF",
            fg="#1A1A1A",
            anchor="w",
        )
        lbl_title.pack(fill="x")

        lbl_sub = tk.Label(
            header,
            text=t("build_sync_sub"),
            font=(self.font_family, 9),
            bg="#FFFFFF",
            fg="#5F6368",
            wraplength=660,
            justify="left",
            anchor="w",
        )
        lbl_sub.pack(fill="x", pady=(2, 0))

        tk.Frame(self.window, height=1, bg="#E5E5E5").pack(fill="x", side="top")

        # Global Enable Bar
        bar_enable = tk.Frame(self.window, bg="#F3F3F3", padx=16, pady=8)
        bar_enable.pack(fill="x", side="top")

        self.var_global_enable = tk.BooleanVar(value=bool(self.config.build_sync_enabled))
        chk_global = ttk.Checkbutton(
            bar_enable,
            text=t("build_sync_global_enable"),
            variable=self.var_global_enable,
            command=self._on_global_enable_toggle,
        )
        chk_global.pack(side="left")

        # Center Card: Treeview & Buttons
        content_card = tk.Frame(self.window, bg="#FFFFFF", padx=12, pady=10)
        content_card.pack(fill="both", expand=True, padx=14, pady=8)

        # Action Buttons Row above Tree
        row_tools = tk.Frame(content_card, bg="#FFFFFF")
        row_tools.pack(fill="x", pady=(0, 8))

        btn_add = ttk.Button(row_tools, text=t("build_sync_btn_add"), command=self._add_task)
        btn_add.pack(side="left", padx=(0, 6))

        btn_edit = ttk.Button(row_tools, text=t("build_sync_btn_edit"), command=self._edit_selected_task)
        btn_edit.pack(side="left", padx=(0, 6))

        btn_delete = ttk.Button(row_tools, text=t("build_sync_btn_delete"), command=self._delete_selected_task)
        btn_delete.pack(side="left", padx=(0, 6))

        btn_sync_now = ttk.Button(row_tools, text=t("build_sync_btn_sync_now"), command=self._trigger_sync_now)
        btn_sync_now.pack(side="right")

        # Treeview with scrollbar
        tree_frame = tk.Frame(content_card, bg="#FFFFFF")
        tree_frame.pack(fill="both", expand=True)

        columns = ("status", "name", "source", "pattern", "target", "keep")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")

        self.tree.heading("status", text=t("build_sync_col_status"))
        self.tree.heading("name", text=t("build_sync_col_name"))
        self.tree.heading("source", text=t("build_sync_col_source"))
        self.tree.heading("pattern", text=t("build_sync_col_pattern"))
        self.tree.heading("target", text=t("build_sync_col_target"))
        self.tree.heading("keep", text=t("build_sync_col_keep"))

        self.tree.column("status", width=70, anchor="center")
        self.tree.column("name", width=120, anchor="w")
        self.tree.column("source", width=180, anchor="w")
        self.tree.column("pattern", width=60, anchor="center")
        self.tree.column("target", width=180, anchor="w")
        self.tree.column("keep", width=60, anchor="center")

        v_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=v_scroll.set)

        self.tree.pack(side="left", fill="both", expand=True)
        v_scroll.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", lambda e: self._edit_selected_task())

        # Bottom Bar
        tk.Frame(self.window, height=1, bg="#E5E5E5").pack(fill="x", side="bottom")
        bottom_bar = tk.Frame(self.window, bg="#F3F3F3", padx=16, pady=10)
        bottom_bar.pack(fill="x", side="bottom")

        btn_save = ttk.Button(bottom_bar, text=t("btn_save_apply"), style="Accent.TButton", command=self._save_and_close)
        btn_save.pack(side="right", padx=(8, 0))

        btn_close = ttk.Button(bottom_bar, text=t("btn_close"), command=self.destroy)
        btn_close.pack(side="right")

    def _refresh_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        for task in self._tasks:
            status_text = "✔ Вкл" if task.get("enabled", True) else "○ Выкл"
            self.tree.insert(
                "",
                "end",
                iid=task["id"],
                values=(
                    status_text,
                    task.get("name", ""),
                    task.get("source_dir", ""),
                    task.get("pattern", "*.zip"),
                    task.get("target_dir", ""),
                    f"{task.get('keep_versions', 5)}",
                ),
            )

    def _on_global_enable_toggle(self) -> None:
        self.config.build_sync_enabled = self.var_global_enable.get()
        self.config.save()
        if self.build_engine:
            self.build_engine.reload_tasks()

    def _add_task(self) -> None:
        base_target = self._get_default_target_base()

        def on_saved(new_task: Dict[str, Any]):
            self._tasks.append(new_task)
            # Auto-enable global toggle if currently disabled
            if not self.var_global_enable.get():
                self.var_global_enable.set(True)
            self._refresh_tree()
            self._persist_changes()

        BuildTaskEditDialog(self.window, default_target_base=base_target, on_save_callback=on_saved)

    def _edit_selected_task(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        task_id = selected[0]
        task_match = next((t for t in self._tasks if t["id"] == task_id), None)
        if not task_match:
            return

        def on_saved(updated_task: Dict[str, Any]):
            for idx, t_item in enumerate(self._tasks):
                if t_item["id"] == task_id:
                    self._tasks[idx] = updated_task
                    break
            self._refresh_tree()
            self._persist_changes()

        BuildTaskEditDialog(self.window, task_data=task_match, default_target_base=self._get_default_target_base(), on_save_callback=on_saved)

    def _delete_selected_task(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        task_id = selected[0]
        task_match = next((t for t in self._tasks if t["id"] == task_id), None)
        if not task_match:
            return

        if messagebox.askyesno(t("delete_confirm_title"), f"Удалить проект «{task_match.get('name')}» из синхронизации?", parent=self.window):
            self._tasks = [t for t in self._tasks if t["id"] != task_id]
            self._refresh_tree()
            self._persist_changes()

    def _trigger_sync_now(self) -> None:
        self._persist_changes()
        ipc_handled = False
        try:
            from DropFile import send_ipc_query
            res = send_ipc_query("BUILD_SYNC_NOW", timeout=1.5)
            if res and res.startswith("OK"):
                ipc_handled = True
        except Exception:
            pass

        # If background daemon handled it via IPC, good.
        # Otherwise, if we have a local engine instance, trigger its thread or run immediate sync pass!
        if not ipc_handled and self.build_engine:
            if hasattr(self.build_engine, "_thread") and self.build_engine._thread and self.build_engine._thread.is_alive():
                self.build_engine.trigger_sync_now()
            else:
                def run_manual():
                    try:
                        total = 0
                        for task in self.config.build_sync_tasks:
                            total += self.build_engine.process_task(task)
                        print(f"[BuildSync] Manual sync completed: {total} files copied.")
                    except Exception as e:
                        print(f"[BuildSync] Error during manual sync: {e}")
                threading.Thread(target=run_manual, daemon=True).start()

        messagebox.showinfo(t("build_sync_title"), "Синхронизация сборок запущена в фоновом режиме.", parent=self.window)

    def _persist_changes(self) -> None:
        self.config.build_sync_enabled = self.var_global_enable.get()
        self.config.build_sync_tasks = self._tasks
        self.config.save()
        if self.build_engine:
            self.build_engine.reload_tasks()
        # Broadcast IPC reload and build sync to running DropFile background instance
        try:
            from DropFile import send_ipc_query
            send_ipc_query("RELOAD_CONFIG", timeout=1.0)
            if self.config.build_sync_enabled:
                send_ipc_query("BUILD_SYNC_NOW", timeout=1.0)
        except Exception:
            pass
        if self.on_save_callback:
            try:
                self.on_save_callback()
            except Exception:
                pass

    def _save_and_close(self) -> None:
        self._persist_changes()
        self.destroy()

