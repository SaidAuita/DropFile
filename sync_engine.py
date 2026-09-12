"""
DropFile Synchronization Engine.
Coordinates local watchdog filesystem events with remote FileBrowser polling.
Implements bidirectional sync, loop prevention, debouncing, and conflict handling.
"""

import fnmatch
import os
import platform
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional, Set

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from config import Config
from fb_client import FileBrowserClient, RemoteItem
from state_db import FileRecord, StateDatabase, compute_file_hash


class SyncEngine:
    def __init__(
        self,
        config: Config,
        state_db: StateDatabase,
        client: FileBrowserClient,
        on_status_change: Optional[Callable[[str, str], None]] = None,
        on_notify: Optional[Callable[[str, str], None]] = None,
    ):
        self.config = config
        self.state_db = state_db
        self.client = client
        self.on_status_change = on_status_change  # (status_text, state: "idle"|"syncing"|"error"|"paused")
        self.on_notify = on_notify  # (title, message)

        self._running = False
        self._paused = False
        self._sync_lock = threading.Lock()
        self._observer: Optional[Observer] = None
        self._poll_thread: Optional[threading.Thread] = None

        # Suppression set to prevent echo loops when downloading remote files
        self._suppressed_paths: Dict[str, float] = {}  # rel_path -> timestamp until suppressed
        self._suppress_lock = threading.Lock()

        # Debounce dictionary for local file events: rel_path -> last event timestamp
        self._pending_local_events: Dict[str, float] = {}
        self._pending_lock = threading.Lock()
        self._debounce_seconds = 2.0

        self.last_sync_time: float = 0.0
        self.current_state = "idle"
        self.status_message = "Готов к работе"

    def set_status(self, message: str, state: str) -> None:
        self.status_message = message
        self.current_state = state
        if self.on_status_change:
            try:
                self.on_status_change(message, state)
            except Exception as e:
                print(f"[SyncEngine] Status callback error: {e}")

    def notify(self, title: str, message: str) -> None:
        if self.config.notify_on_sync and self.on_notify:
            try:
                self.on_notify(title, message)
            except Exception as e:
                print(f"[SyncEngine] Notify callback error: {e}")

    def is_ignored(self, path: Path | str) -> bool:
        """Checks if a file or directory matches any ignore pattern."""
        name = Path(path).name
        for pattern in self.config.ignore_patterns:
            if fnmatch.fnmatch(name, pattern):
                return True
        return False

    def _suppress(self, rel_path: str, duration: float = 3.0) -> None:
        clean = rel_path.replace("\\", "/").lstrip("/")
        with self._suppress_lock:
            self._suppressed_paths[clean] = time.time() + duration

    def _is_suppressed(self, rel_path: str) -> bool:
        clean = rel_path.replace("\\", "/").lstrip("/")
        with self._suppress_lock:
            exp = self._suppressed_paths.get(clean, 0.0)
            if time.time() < exp:
                return True
            if clean in self._suppressed_paths:
                del self._suppressed_paths[clean]
            return False

    def is_file_ready(self, filepath: Path) -> bool:
        """Checks if file is completely written and accessible."""
        if not filepath.exists() or not filepath.is_file():
            return False
        try:
            with open(filepath, "rb"):
                return True
        except (IOError, PermissionError):
            return False

    def start(self) -> None:
        """Starts local filesystem watcher and periodic remote polling thread."""
        if self._running:
            return

        self._running = True
        self.config.local_path.mkdir(parents=True, exist_ok=True)

        # Start Watchdog
        handler = LocalFolderHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.config.local_path), recursive=True)
        self._observer.start()

        # Start background polling / processing thread
        self._poll_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._poll_thread.start()

        self.set_status("Синхронизация запущена", "idle")
        print("[SyncEngine] Started.")

    def stop(self) -> None:
        """Stops the sync engine."""
        self._running = False
        if self._observer:
            try:
                self._observer.stop()
                self._observer.join(timeout=3)
            except Exception:
                pass
        self.set_status("Остановлено", "paused")
        print("[SyncEngine] Stopped.")

    def pause(self) -> None:
        self._paused = True
        self.set_status("Синхронизация приостановлена", "paused")

    def resume(self) -> None:
        self._paused = False
        self.set_status("Синхронизация возобновлена", "idle")
        self.trigger_sync_now()

    def is_paused(self) -> bool:
        return self._paused

    def trigger_sync_now(self) -> None:
        """Schedules an immediate full sync."""
        threading.Thread(target=self.reconcile_all, daemon=True).start()

    def on_local_event(self, local_abs_path: str, event_type: str) -> None:
        """Called by watchdog when a file change is detected locally."""
        if not self._running or self._paused:
            return

        try:
            rel = os.path.relpath(local_abs_path, str(self.config.local_path)).replace("\\", "/")
        except ValueError:
            return

        if self.is_ignored(local_abs_path):
            return

        if self._is_suppressed(rel):
            return

        with self._pending_lock:
            self._pending_local_events[rel] = time.time()

    def _worker_loop(self) -> None:
        """Main background loop handling debounced local events and periodic polling."""
        last_poll = 0.0

        # Perform initial sync on startup
        time.sleep(1.0)
        if self.config.server_url and self.config.username:
            self.reconcile_all()
        else:
            self.set_status("Требуется настройка подключения", "paused")

        while self._running:
            try:
                now = time.time()

                # Process debounced local changes
                to_process = []
                with self._pending_lock:
                    for rel, timestamp in list(self._pending_local_events.items()):
                        if now - timestamp >= self._debounce_seconds:
                            to_process.append(rel)
                            del self._pending_local_events[rel]

                for rel in to_process:
                    if not self._paused:
                        self._sync_single_local_file(rel)

                # Periodic remote polling
                if not self._paused and (now - last_poll >= self.config.poll_interval):
                    self.reconcile_all()
                    last_poll = time.time()

            except Exception as e:
                print(f"[SyncEngine] Worker loop exception: {e}")

            time.sleep(0.5)

    def _sync_single_local_file(self, rel_path: str) -> None:
        """Uploads a local file or handles its local deletion."""
        if not self.config.server_url or not self.config.username:
            return

        local_file = self.config.local_path / rel_path
        clean_rel = rel_path.replace("\\", "/").lstrip("/")

        with self._sync_lock:
            if not local_file.exists():
                # File was deleted locally
                rec = self.state_db.get_record(clean_rel)
                if rec:
                    self.set_status(f"Удаление: {clean_rel}", "syncing")
                    remote_file_path = f"{self.config.remote_path}/{clean_rel}"
                    ok = self.client.delete_resource(remote_file_path)
                    if ok:
                        self.state_db.delete_record(clean_rel)
                        self.state_db.log_sync(clean_rel, "delete", "local->remote", "success")
                        print(f"[SyncEngine] Deleted remotely: {clean_rel}")
                    else:
                        self.state_db.log_sync(clean_rel, "delete", "local->remote", "error", "Remote delete failed")
                    self.set_status("Синхронизировано", "idle")
                return

            if local_file.is_dir():
                return

            # Wait if file is still being written
            if not self.is_file_ready(local_file):
                # Re-queue
                with self._pending_lock:
                    self._pending_local_events[clean_rel] = time.time()
                return

            try:
                stat = local_file.stat()
                local_mtime = stat.st_mtime
                local_size = stat.st_size
            except Exception:
                return

            # Check if content actually differs from state DB
            rec = self.state_db.get_record(clean_rel)
            if rec and abs(rec.local_mtime - local_mtime) < 0.01 and rec.local_size == local_size:
                # No change
                return

            # Compute hash
            content_hash = compute_file_hash(local_file)
            if rec and rec.content_hash and rec.content_hash == content_hash:
                # Content identical, update mtime in DB
                rec.local_mtime = local_mtime
                self.state_db.upsert_record(rec)
                return

            self.set_status(f"Выгрузка: {clean_rel}", "syncing")
            remote_dest = f"{self.config.remote_path}/{clean_rel}"
            ok = self.client.upload_file(local_file, remote_dest)

            if ok:
                meta = self.client.get_resource(remote_dest)
                remote_mtime = meta.get("modified", "") if meta else str(datetime.utcnow())
                remote_size = meta.get("size", local_size) if meta else local_size

                new_rec = FileRecord(
                    rel_path=clean_rel,
                    local_mtime=local_mtime,
                    local_size=local_size,
                    remote_mtime=remote_mtime,
                    remote_size=remote_size,
                    content_hash=content_hash,
                    is_dir=False,
                    last_sync_time=time.time(),
                )
                self.state_db.upsert_record(new_rec)
                self.state_db.log_sync(clean_rel, "upload", "local->remote", "success")
                self.notify("DropFile: Загрузка завершена", f"Файл {local_file.name} отправлен на сервер.")
                print(f"[SyncEngine] Successfully uploaded: {clean_rel}")
            else:
                self.state_db.log_sync(clean_rel, "upload", "local->remote", "error", "Upload failed")
                self.set_status("Ошибка выгрузки файла", "error")
                return

            self.set_status("Синхронизировано", "idle")

    def reconcile_all(self) -> None:
        """Performs a full bidirectional comparison between local folder and remote FileBrowser."""
        if not self._running or self._paused:
            return

        if not self.config.server_url or not self.config.username:
            self.set_status("Требуется настройка подключения", "paused")
            return

        with self._sync_lock:
            self.set_status("Проверка удаленных изменений...", "syncing")

            # 1. Test / ensure connection
            ok, msg = self.client.test_connection()
            if not ok:
                self.set_status(f"Нет связи с сервером ({msg[:40]})", "error")
                return

            # Ensure remote root exists
            self.client.ensure_remote_dir_exists(self.config.remote_path)

            # 2. Fetch remote tree
            remote_items = self.client.list_recursive(self.config.remote_path)
            remote_dict: Dict[str, RemoteItem] = {}

            root_prefix = self.config.remote_path.strip("/")
            for item in remote_items:
                if item.is_dir:
                    continue
                # Normalize relative path
                clean_p = item.path.strip("/")
                if clean_p.startswith(root_prefix):
                    rel = clean_p[len(root_prefix):].lstrip("/")
                else:
                    rel = clean_p
                if rel and not self.is_ignored(rel):
                    remote_dict[rel] = item

            # 3. Scan local files
            local_dict: Dict[str, Path] = {}
            if self.config.local_path.exists():
                for root, _, files in os.walk(self.config.local_path):
                    for file in files:
                        full_path = Path(root) / file
                        if self.is_ignored(full_path):
                            continue
                        rel = str(full_path.relative_to(self.config.local_path)).replace("\\", "/")
                        local_dict[rel] = full_path

            # 4. Process all tracked files from State DB
            state_records = self.state_db.get_all_records()

            all_rel_paths = set(remote_dict.keys()) | set(local_dict.keys()) | set(state_records.keys())

            downloads_count = 0
            uploads_count = 0

            for rel in all_rel_paths:
                if self._paused or not self._running:
                    break

                in_remote = rel in remote_dict
                in_local = rel in local_dict
                in_state = rel in state_records

                # Case A: File exists both locally and remotely
                if in_remote and in_local:
                    r_item = remote_dict[rel]
                    l_file = local_dict[rel]
                    rec = state_records.get(rel)

                    l_stat = l_file.stat()
                    l_mtime = l_stat.st_mtime
                    l_size = l_stat.st_size

                    # Check if remote modified
                    remote_changed = (
                        not rec
                        or rec.remote_mtime != r_item.modified
                        or rec.remote_size != r_item.size
                    )

                    # Check if local modified
                    local_changed = (
                        not rec
                        or abs(rec.local_mtime - l_mtime) > 0.01
                        or rec.local_size != l_size
                    )

                    if remote_changed and not local_changed:
                        # Safe to download remote update
                        self._download_remote_file(rel, r_item, l_file)
                        downloads_count += 1
                    elif local_changed and not remote_changed:
                        # Safe to upload local update
                        self._upload_local_file(rel, l_file, r_item.path)
                        uploads_count += 1
                    elif remote_changed and local_changed:
                        # Conflict! Check hash first
                        l_hash = compute_file_hash(l_file)
                        if rec and rec.content_hash == l_hash and rec.remote_size == r_item.size:
                            # False alarm: local was identical
                            self._download_remote_file(rel, r_item, l_file)
                        else:
                            # Real conflict: create conflicted copy of local file, download remote
                            self._handle_conflict(rel, l_file, r_item)
                            downloads_count += 1

                # Case B: File is on remote, but NOT on local disk
                elif in_remote and not in_local:
                    rec = state_records.get(rel)
                    r_item = remote_dict[rel]

                    if in_state:
                        # File was previously synced, but user deleted it locally -> Delete remotely
                        self.set_status(f"Удаление на сервере: {rel}", "syncing")
                        ok = self.client.delete_resource(r_item.path)
                        if ok:
                            self.state_db.delete_record(rel)
                            self.state_db.log_sync(rel, "delete", "local->remote", "success")
                    else:
                        # New remote file from another computer -> Download it
                        target = self.config.local_path / rel
                        self._download_remote_file(rel, r_item, target)
                        downloads_count += 1

                # Case C: File is on local, but NOT on remote
                elif in_local and not in_remote:
                    rec = state_records.get(rel)
                    l_file = local_dict[rel]

                    if in_state:
                        # File was deleted remotely on the server -> Delete locally
                        self.set_status(f"Удаление локально: {rel}", "syncing")
                        self._suppress(rel, duration=3.0)
                        try:
                            l_file.unlink()
                            self.state_db.delete_record(rel)
                            self.state_db.log_sync(rel, "delete", "remote->local", "success")
                        except Exception as e:
                            print(f"[SyncEngine] Error removing local file {rel}: {e}")
                    else:
                        # New local file added by user -> Upload it
                        remote_dest = f"{self.config.remote_path}/{rel}"
                        self._upload_local_file(rel, l_file, remote_dest)
                        uploads_count += 1

                # Case D: In state DB, but neither on local nor on remote
                elif in_state:
                    self.state_db.delete_record(rel)

            self.last_sync_time = time.time()
            if downloads_count > 0 or uploads_count > 0:
                self.notify(
                    "DropFile: Синхронизировано",
                    f"Загружено: {downloads_count}, Отправлено: {uploads_count}",
                )

            self.set_status("Синхронизировано", "idle")

    def _download_remote_file(self, rel: str, r_item: RemoteItem, target: Path) -> bool:
        self.set_status(f"Загрузка: {rel}", "syncing")
        self._suppress(rel, duration=5.0)

        ok = self.client.download_file(r_item.path, target)
        if ok and target.exists():
            stat = target.stat()
            content_hash = compute_file_hash(target)
            rec = FileRecord(
                rel_path=rel,
                local_mtime=stat.st_mtime,
                local_size=stat.st_size,
                remote_mtime=r_item.modified,
                remote_size=r_item.size,
                content_hash=content_hash,
                is_dir=False,
                last_sync_time=time.time(),
            )
            self.state_db.upsert_record(rec)
            self.state_db.log_sync(rel, "download", "remote->local", "success")
            print(f"[SyncEngine] Successfully downloaded: {rel}")
            return True
        else:
            self.state_db.log_sync(rel, "download", "remote->local", "error", "Download failed")
            return False

    def _upload_local_file(self, rel: str, local_file: Path, remote_dest: str) -> bool:
        if not self.is_file_ready(local_file):
            return False

        self.set_status(f"Выгрузка: {rel}", "syncing")
        ok = self.client.upload_file(local_file, remote_dest)
        if ok:
            stat = local_file.stat()
            meta = self.client.get_resource(remote_dest)
            remote_mtime = meta.get("modified", "") if meta else str(datetime.utcnow())
            remote_size = meta.get("size", stat.st_size) if meta else stat.st_size

            rec = FileRecord(
                rel_path=rel,
                local_mtime=stat.st_mtime,
                local_size=stat.st_size,
                remote_mtime=remote_mtime,
                remote_size=remote_size,
                content_hash=compute_file_hash(local_file),
                is_dir=False,
                last_sync_time=time.time(),
            )
            self.state_db.upsert_record(rec)
            self.state_db.log_sync(rel, "upload", "local->remote", "success")
            print(f"[SyncEngine] Successfully uploaded: {rel}")
            return True
        else:
            self.state_db.log_sync(rel, "upload", "local->remote", "error", "Upload failed")
            return False

    def _handle_conflict(self, rel: str, local_file: Path, r_item: RemoteItem) -> None:
        """Handles simultaneous local & remote edits by creating a conflicted copy."""
        computer_name = platform.node() or "PC"
        timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        stem = local_file.stem
        suffix = local_file.suffix
        conflict_name = f"{stem} (Конфликт {computer_name} {timestamp_str}){suffix}"
        conflict_path = local_file.parent / conflict_name

        try:
            shutil.copy2(local_file, conflict_path)
            self.notify(
                "DropFile: Обнаружен конфликт",
                f"Создана копия: {conflict_name}",
            )
            self.state_db.log_sync(
                rel,
                "conflict",
                "both",
                "resolved",
                f"Created conflicted copy {conflict_name}",
            )
        except Exception as e:
            print(f"[SyncEngine] Error creating conflict copy: {e}")

        # Now download remote file over current local file
        self._download_remote_file(rel, r_item, local_file)


class LocalFolderHandler(FileSystemEventHandler):
    def __init__(self, engine: SyncEngine):
        super().__init__()
        self.engine = engine

    def on_created(self, event):
        if not event.is_directory:
            self.engine.on_local_event(event.src_path, "created")

    def on_modified(self, event):
        if not event.is_directory:
            self.engine.on_local_event(event.src_path, "modified")

    def on_deleted(self, event):
        if not event.is_directory:
            self.engine.on_local_event(event.src_path, "deleted")

    def on_moved(self, event):
        if not event.is_directory:
            self.engine.on_local_event(event.src_path, "deleted")
            self.engine.on_local_event(event.dest_path, "created")
