"""
DropFile Synchronization Engine.
Coordinates local watchdog filesystem events with remote FileBrowser polling.
Implements bidirectional sync, loop prevention, debouncing, and conflict handling.
"""

import fnmatch
import os
import platform
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional, Set, Tuple

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from config import Config
from fb_client import FileBrowserClient, RemoteItem
from i18n import t
from state_db import FileRecord, StateDatabase, compute_file_hash


class SyncEngine:
    def __init__(
        self,
        config: Config,
        state_db: StateDatabase,
        client: FileBrowserClient,
        on_status_change: Optional[Callable[[str, str], None]] = None,
        on_notify: Optional[Callable[[str, str], None]] = None,
        on_share_ready: Optional[Callable[[Dict[str, str]], None]] = None,
    ):
        self.config = config
        self.state_db = state_db
        self.client = client
        self.on_status_change = on_status_change  # (status_text, state: "idle"|"syncing"|"error"|"paused")
        self.on_notify = on_notify  # (title, message)
        self.on_share_ready = on_share_ready  # (last_item_dict)

        self.last_uploaded_item: Optional[Dict[str, str]] = None
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
        self.status_message = t("status_ready")
        try:
            self._last_cfg_mtime = self.config.config_file.stat().st_mtime if self.config.config_file.exists() else 0.0
        except Exception:
            self._last_cfg_mtime = 0.0

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

        self.set_status(t("status_started"), "idle")
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
        self.set_status(t("status_stopped"), "paused")
        print("[SyncEngine] Stopped.")

    def pause(self) -> None:
        self._paused = True
        self.set_status(t("status_paused"), "paused")

    def resume(self) -> None:
        self._paused = False
        self.set_status(t("status_resumed"), "idle")
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

    def _check_config_reload(self) -> None:
        """Checks if config.json was modified on disk and reloads configuration dynamically."""
        try:
            cfg_file = self.config.config_file
            if cfg_file.exists():
                mtime = cfg_file.stat().st_mtime
                if mtime > getattr(self, "_last_cfg_mtime", 0.0):
                    self._last_cfg_mtime = mtime
                    print("[SyncEngine] config.json modification detected, reloading...")
                    self.config.load()
                    if self.client:
                        self.client.base_url = self.config.server_url
                        self.client.username = self.config.username
                        self.client.password = self.config.password
                        self.client.token = None
                    self.trigger_sync_now()
        except Exception as e:
            print(f"[SyncEngine] Error checking config reload: {e}")

    def _worker_loop(self) -> None:
        """Main background loop handling debounced local events and periodic polling."""
        last_poll = 0.0
        last_cleanup = 0.0

        # Perform initial sync on startup
        time.sleep(1.0)
        if self.config.server_url and self.config.username:
            self._init_last_uploaded_from_history()
            try:
                self.state_db.cleanup_old_history(self.config.log_retention_days)
                self.cleanup_old_files(self.config.file_retention_days)
            except Exception as e:
                print(f"[SyncEngine] Startup cleanup error: {e}")
            last_cleanup = time.time()
            self.reconcile_all()
        else:
            self.set_status(t("status_need_config"), "paused")

        while self._running:
            try:
                self._check_config_reload()
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

                # Periodic cleanup of old sync history and files every 6 hours
                if now - last_cleanup >= 21600:
                    try:
                        self.state_db.cleanup_old_history(self.config.log_retention_days)
                        self.cleanup_old_files(self.config.file_retention_days)
                        self.deduplicate_conflict_copies()
                    except Exception as e:
                        print(f"[SyncEngine] Periodic cleanup error: {e}")
                    last_cleanup = now

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
                    self.set_status(t("status_deleting_remote", file=clean_rel), "syncing")
                    remote_file_path = f"{self.config.remote_path}/{clean_rel}"
                    ok = self.client.delete_resource(remote_file_path)
                    if ok:
                        self.state_db.delete_record(clean_rel)
                        self.state_db.log_sync(clean_rel, "delete", "local->remote", "success")
                        print(f"[SyncEngine] Deleted remotely: {clean_rel}")
                    else:
                        self.state_db.log_sync(clean_rel, "delete", "local->remote", "error", "Remote delete failed")
                    self.set_status(t("status_synced"), "idle")
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

            self.set_status(t("status_uploading", file=clean_rel), "syncing")
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
                self._record_uploaded_item(local_file, clean_rel, remote_dest)
                self.notify(t("notify_upload_done_title"), t("notify_upload_done_msg", name=local_file.name))
                print(f"[SyncEngine] Successfully uploaded: {clean_rel}")
            else:
                self.state_db.log_sync(clean_rel, "upload", "local->remote", "error", "Upload failed")
                self.set_status(t("status_upload_error"), "error")
                return

            self.set_status(t("status_synced"), "idle")

    def reconcile_all(self) -> None:
        """Performs a full bidirectional comparison between local folder and remote FileBrowser."""
        if not self._running or self._paused:
            return

        if not self.config.server_url or not self.config.username:
            self.set_status(t("status_need_config"), "paused")
            return

        with self._sync_lock:
            self.set_status(t("status_checking"), "syncing")

            # 1. Test / ensure connection
            ok, msg = self.client.test_connection()
            if not ok:
                self.set_status(t("status_conn_error", msg=msg[:40]), "error")
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

                    # Smart verification: if rec exists and local timestamp/size changed, verify content hash
                    if rec and local_changed:
                        l_hash = compute_file_hash(l_file)
                        if rec.content_hash and l_hash == rec.content_hash:
                            # False alarm: local content did NOT change (timestamp was merely touched)
                            local_changed = False
                            rec.local_mtime = l_mtime
                            self.state_db.upsert_record(rec)

                    if remote_changed and not local_changed:
                        # Safe to download remote update
                        self._download_remote_file(rel, r_item, l_file)
                        downloads_count += 1
                    elif local_changed and not remote_changed:
                        # Safe to upload local update
                        self._upload_local_file(rel, l_file, r_item.path)
                        uploads_count += 1
                    elif remote_changed and local_changed:
                        # Potential conflict or initial sync for pre-existing files!
                        # Check actual content hashes before creating any duplicate!
                        res = self._handle_conflict(rel, l_file, r_item)
                        if res in ("downloaded", "conflict"):
                            downloads_count += 1
                        elif res == "uploaded":
                            uploads_count += 1

                # Case B: File is on remote, but NOT on local disk
                elif in_remote and not in_local:
                    rec = state_records.get(rel)
                    r_item = remote_dict[rel]

                    if in_state:
                        # File was previously synced, but user deleted it locally -> Delete remotely
                        self.set_status(t("status_deleting_remote", file=rel), "syncing")
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
                        self.set_status(t("status_deleting_local", file=rel), "syncing")
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
                    t("notify_sync_title"),
                    t("notify_sync_msg", down=downloads_count, up=uploads_count),
                )

            self.set_status(t("status_synced"), "idle")

    def _download_remote_file(self, rel: str, r_item: RemoteItem, target: Path) -> bool:
        self.set_status(t("status_downloading", file=rel), "syncing")
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

        self.set_status(t("status_uploading", file=rel), "syncing")
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
            self._record_uploaded_item(local_file, rel, remote_dest)
            print(f"[SyncEngine] Successfully uploaded: {rel}")
            return True
        else:
            self.state_db.log_sync(rel, "upload", "local->remote", "error", "Upload failed")
            return False

    def get_last_uploaded_item(self) -> Optional[Dict[str, str]]:
        """Returns the last uploaded item dict, restoring from history if needed."""
        if self.last_uploaded_item is not None:
            return self.last_uploaded_item
        if not getattr(self, "_history_loaded", False):
            self._init_last_uploaded_from_history()
        return self.last_uploaded_item

    def _notify_share_ready(self, item_info: Dict[str, str], notify: bool = True) -> None:
        if not self.on_share_ready:
            return
        try:
            import inspect
            sig = inspect.signature(self.on_share_ready)
            if len(sig.parameters) >= 2:
                self.on_share_ready(item_info, notify)
            else:
                self.on_share_ready(item_info)
        except Exception as e:
            print(f"[SyncEngine] on_share_ready callback error: {e}")

    def _record_uploaded_item(self, local_file: Path, rel_path: str, remote_dest: str) -> None:
        """Stores details and share URL of the most recently uploaded file or folder."""
        try:
            share_url = self.client.get_or_create_share_link(remote_dest)
        except Exception as e:
            print(f"[SyncEngine] Error obtaining share link: {e}")
            share_url = f"{self.config.server_url}/files{remote_dest}"

        self.last_uploaded_item = {
            "name": local_file.name,
            "rel_path": rel_path,
            "remote_path": remote_dest,
            "share_url": share_url or f"{self.config.server_url}/files{remote_dest}",
        }
        self._notify_share_ready(self.last_uploaded_item, notify=True)

    def _init_last_uploaded_from_history(self) -> None:
        """Restores last_uploaded_item from the most recent upload in sync_history."""
        self._history_loaded = True
        if not self.config.server_url or not self.config.username:
            return

        try:
            with self.state_db._get_connection() as conn:
                cur = conn.execute(
                    "SELECT rel_path FROM sync_history WHERE action = 'upload' AND direction = 'local->remote' AND status = 'success' ORDER BY id DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row:
                    rel = row["rel_path"]
                    clean_rel = rel.replace("\\", "/").lstrip("/")
                    name = Path(clean_rel).name
                    remote_dest = f"{self.config.remote_path}/{clean_rel}"
                    share_url = self.client.get_or_create_share_link(remote_dest)
                    self.last_uploaded_item = {
                        "name": name,
                        "rel_path": clean_rel,
                        "remote_path": remote_dest,
                        "share_url": share_url or f"{self.config.server_url}/files{remote_dest}",
                    }
                    self._notify_share_ready(self.last_uploaded_item, notify=False)
                    print(f"[SyncEngine] Restored last uploaded item: {name} -> {self.last_uploaded_item['share_url']}")
        except Exception as e:
            print(f"[SyncEngine] Error restoring last uploaded item from history: {e}")

    def cleanup_old_files(self, retention_days: Optional[int] = None) -> int:
        """Removes files older than retention_days both locally and remotely.

        If retention_days is None, uses self.config.file_retention_days.
        If retention_days <= 0, cleanup is disabled and returns 0.
        """
        if retention_days is None:
            retention_days = self.config.file_retention_days

        if retention_days <= 0:
            return 0

        cutoff = time.time() - (retention_days * 86400)
        cleaned_count = 0

        with self._sync_lock:
            # 1. Gather all tracked files from state DB
            state_records = self.state_db.get_all_records()
            all_rel_paths = set(state_records.keys())

            # 2. Gather all existing local files
            if self.config.local_path.exists():
                for root, _, files in os.walk(self.config.local_path):
                    for file in files:
                        full_path = Path(root) / file
                        if self.is_ignored(full_path):
                            continue
                        rel = str(full_path.relative_to(self.config.local_path)).replace("\\", "/")
                        all_rel_paths.add(rel)

            for rel in all_rel_paths:
                if self._paused or not self._running:
                    break

                if self.is_ignored(rel):
                    continue

                clean_rel = rel.replace("\\", "/").lstrip("/")
                local_file = self.config.local_path / clean_rel
                rec = state_records.get(clean_rel)

                # Determine file age timestamp safely
                age_ts = 0.0
                if local_file.exists():
                    try:
                        st = local_file.stat()
                        local_created = getattr(st, "st_ctime", st.st_mtime)
                        age_ts = max(st.st_mtime, local_created)
                    except Exception:
                        pass

                if rec and rec.last_sync_time > 0:
                    age_ts = rec.last_sync_time if age_ts == 0.0 else min(age_ts, rec.last_sync_time)

                if age_ts <= 0.0 or age_ts >= cutoff:
                    continue

                # File is older than retention period -> purge it
                remote_dest = f"{self.config.remote_path}/{clean_rel}"

                # 1. Delete local file
                if local_file.exists():
                    self._suppress(clean_rel, duration=5.0)
                    try:
                        local_file.unlink()
                    except Exception as e:
                        print(f"[SyncEngine] Auto-cleanup: could not delete local file {clean_rel}: {e}")
                        continue

                # 2. Delete remote file in FileBrowser
                if self.config.server_url and self.config.username:
                    try:
                        self.client.delete_resource(remote_dest)
                    except Exception as e:
                        print(f"[SyncEngine] Auto-cleanup: remote delete error for {remote_dest}: {e}")

                # 3. Remove record from state DB and log
                self.state_db.delete_record(clean_rel)
                self.state_db.log_sync(
                    clean_rel,
                    "delete",
                    "cleanup",
                    "success",
                    f"Автоочистка (старше {retention_days} дн.)",
                )
                cleaned_count += 1

                # If this was the last uploaded item in memory, reset it
                if self.last_uploaded_item and self.last_uploaded_item.get("rel_path") == clean_rel:
                    self.last_uploaded_item = None

            # 3. Clean up any empty local subdirectories
            if self.config.local_path.exists():
                for root, dirs, files in os.walk(self.config.local_path, topdown=False):
                    if Path(root) != self.config.local_path and not dirs and not files:
                        try:
                            os.rmdir(root)
                        except Exception:
                            pass

        if cleaned_count > 0:
            print(f"[SyncEngine] Auto-cleanup: removed {cleaned_count} file(s) older than {retention_days} days.")
            self.notify(
                t("notify_cleanup_title"),
                t("notify_cleanup_msg", days=retention_days, count=cleaned_count),
            )
            # Update tray menu in case last item was removed
            if self.on_share_ready:
                item = self.get_last_uploaded_item()
                self._notify_share_ready(item or {}, notify=False)

        return cleaned_count

    def _handle_conflict(self, rel: str, local_file: Path, r_item: RemoteItem) -> str:
        """Handles potential conflict between local and remote file versions.

        1. Compares file sizes and content hashes (using temporary download).
        2. If hashes match: NO conflict, files are identical. Updates state_db without creating duplicate.
        3. If hashes differ: Genuine conflict.
           - If conflict_action == 'newer_wins': keeps the newer file.
           - If conflict_action == 'keep_both': creates a conflict copy of the local file and keeps remote.

        Returns:
            "identical": if contents matched and no duplicate was needed.
            "downloaded": if remote was kept/downloaded over local.
            "uploaded": if local was uploaded over remote.
            "conflict": if a conflicted copy was created.
            "error": if an error occurred.
        """
        if not local_file.exists():
            return "error"

        try:
            l_stat = local_file.stat()
            l_mtime = l_stat.st_mtime
            l_size = l_stat.st_size
        except Exception:
            return "error"

        l_hash = compute_file_hash(local_file)

        # 1. Download remote file to an isolated temporary file to inspect its content
        temp_conflict = local_file.parent / f".df_conflict_{os.getpid()}_{local_file.name}.tmp"
        clean_temp_rel = str(temp_conflict.relative_to(self.config.local_path)).replace("\\", "/")
        self._suppress(clean_temp_rel, duration=10.0)

        ok = self.client.download_file(r_item.path, temp_conflict)
        if not ok or not temp_conflict.exists():
            print(f"[SyncEngine] Conflict check: could not fetch remote {rel}")
            return "error"

        r_hash = compute_file_hash(temp_conflict)

        # 2. Check if content is 100% identical
        if l_hash == r_hash and l_hash != "":
            # Both files have the EXACT SAME content! No conflict, no duplicate needed.
            try:
                temp_conflict.unlink()
            except Exception:
                pass

            rec = FileRecord(
                rel_path=rel,
                local_mtime=l_mtime,
                local_size=l_size,
                remote_mtime=r_item.modified,
                remote_size=r_item.size,
                content_hash=l_hash,
                is_dir=False,
                last_sync_time=time.time(),
            )
            self.state_db.upsert_record(rec)
            print(f"[SyncEngine] Conflict avoided for {rel}: contents are identical (hash {l_hash[:8]}).")
            return "identical"

        # 3. Content is different: Genuine conflict!
        conflict_mode = getattr(self.config, "conflict_action", "keep_both")

        if conflict_mode == "newer_wins":
            # Determine which is newer: remote or local
            r_ts = 0.0
            try:
                dt = datetime.fromisoformat(r_item.modified.replace("Z", "+00:00"))
                r_ts = dt.timestamp()
            except Exception:
                pass

            if r_ts > l_mtime:
                # Remote is newer: replace local with remote
                self._suppress(rel, duration=5.0)
                shutil.move(str(temp_conflict), str(local_file))
                rec = FileRecord(
                    rel_path=rel,
                    local_mtime=local_file.stat().st_mtime,
                    local_size=local_file.stat().st_size,
                    remote_mtime=r_item.modified,
                    remote_size=r_item.size,
                    content_hash=r_hash,
                    is_dir=False,
                    last_sync_time=time.time(),
                )
                self.state_db.upsert_record(rec)
                self.state_db.log_sync(rel, "conflict_resolve", "remote->local", "success", "Remote newer, replaced local")
                print(f"[SyncEngine] Conflict resolved (newer wins): {rel} updated from remote.")
                return "downloaded"
            else:
                # Local is newer: upload local to remote
                try:
                    temp_conflict.unlink()
                except Exception:
                    pass
                self._upload_local_file(rel, local_file, r_item.path)
                self.state_db.log_sync(rel, "conflict_resolve", "local->remote", "success", "Local newer, overwritten remote")
                print(f"[SyncEngine] Conflict resolved (newer wins): {rel} uploaded to remote.")
                return "uploaded"

        # Default: "keep_both" (Create conflict copy of local file and keep remote)
        # Avoid creating nested conflict copies if file is ALREADY a conflict copy!
        if re.search(r"\(Conflict\s", local_file.name, flags=re.IGNORECASE):
            # Already a conflict file: do not nest! Just replace local with remote
            self._suppress(rel, duration=5.0)
            try:
                shutil.move(str(temp_conflict), str(local_file))
            except Exception as e:
                print(f"[SyncEngine] Error replacing nested conflict file: {e}")
            stat = local_file.stat()
            rec = FileRecord(
                rel_path=rel,
                local_mtime=stat.st_mtime,
                local_size=stat.st_size,
                remote_mtime=r_item.modified,
                remote_size=r_item.size,
                content_hash=r_hash,
                is_dir=False,
                last_sync_time=time.time(),
            )
            self.state_db.upsert_record(rec)
            return "downloaded"

        computer_name = platform.node() or "PC"
        timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        stem = local_file.stem
        suffix = local_file.suffix
        conflict_name = f"{stem} (Conflict {computer_name} {timestamp_str}){suffix}"
        conflict_path = local_file.parent / conflict_name

        try:
            shutil.copy2(local_file, conflict_path)
            self.notify(
                t("notify_conflict_title"),
                t("notify_conflict_msg", name=conflict_name),
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

        # Replace local file with downloaded remote file
        self._suppress(rel, duration=5.0)
        try:
            shutil.move(str(temp_conflict), str(local_file))
        except Exception as e:
            print(f"[SyncEngine] Error replacing local file with remote: {e}")

        stat = local_file.stat()
        rec = FileRecord(
            rel_path=rel,
            local_mtime=stat.st_mtime,
            local_size=stat.st_size,
            remote_mtime=r_item.modified,
            remote_size=r_item.size,
            content_hash=r_hash,
            is_dir=False,
            last_sync_time=time.time(),
        )
        self.state_db.upsert_record(rec)
        print(f"[SyncEngine] Created conflicted copy: {conflict_name} (local and remote hashes differed).")
        return "conflict"

    def deduplicate_conflict_copies(self) -> Tuple[int, int]:
        """Scans local folder for conflict copies (e.g. '* (Conflict *)*')
        whose content hash matches the base file. Safely deletes them locally and remotely.
        Returns: (removed_count, freed_bytes)
        """
        pattern = r"\s+\((?:Conflict|копия|.*?PC|\?)[^)]*\)"
        removed_count = 0
        freed_bytes = 0

        with self._sync_lock:
            if not self.config.local_path.exists():
                return 0, 0

            for root, _, files in os.walk(self.config.local_path):
                for file in files:
                    clean_file = file
                    base_name = re.sub(pattern, "", clean_file, flags=re.IGNORECASE).strip()
                    if base_name == clean_file:
                        continue

                    full_dup = Path(root) / clean_file
                    full_base = Path(root) / base_name

                    if not full_base.exists() or not full_dup.exists():
                        continue

                    try:
                        dup_size = full_dup.stat().st_size
                        base_size = full_base.stat().st_size
                        if dup_size != base_size:
                            continue

                        h_dup = compute_file_hash(full_dup)
                        h_base = compute_file_hash(full_base)

                        if h_dup and h_dup == h_base:
                            # 100% duplicate! Remove it locally
                            rel_dup = str(full_dup.relative_to(self.config.local_path)).replace("\\", "/")
                            self._suppress(rel_dup, duration=5.0)
                            full_dup.unlink()
                            freed_bytes += dup_size
                            removed_count += 1

                            # Remove remotely
                            if self.config.server_url and self.config.username:
                                remote_dest = f"{self.config.remote_path}/{rel_dup}"
                                try:
                                    self.client.delete_resource(remote_dest)
                                except Exception as e:
                                    print(f"[SyncEngine] Dedup remote delete error: {e}")

                            # Remove from DB
                            self.state_db.delete_record(rel_dup)
                            self.state_db.log_sync(
                                rel_dup,
                                "delete",
                                "dedup",
                                "success",
                                f"Удален дубликат (хэш совпадает с {base_name})",
                            )
                            print(f"[SyncEngine] Deduplicated: {clean_file} -> {base_name} ({dup_size} bytes)")
                    except Exception as e:
                        print(f"[SyncEngine] Error deduplicating {file}: {e}")

        if removed_count > 0:
            print(f"[SyncEngine] Deduplication: removed {removed_count} redundant duplicate(s), freed {freed_bytes} bytes.")
        return removed_count, freed_bytes


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
