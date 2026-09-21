"""
Build Drops Synchronization Engine for DropFile.
Monitors configured project build directories for new zip/archive builds,
verifies file write completion (debounce & lock checks), safely copies builds
to dedicated project target folders (e.g. SMB network shares like \\\\host\\Exchange\\Build\\Project\\),
and automatically rotates versions keeping only the last N builds.
"""

import fnmatch
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from config import Config
from i18n import t


class BuildSyncEngine:
    def __init__(
        self,
        config: Config,
        state_db: Optional[Any] = None,
        on_notify: Optional[Callable[[str, str], None]] = None,
        on_status_change: Optional[Callable[[str], None]] = None,
        poll_interval: float = 4.0,
        debounce_seconds: float = 3.0,
    ):
        self.config = config
        self.state_db = state_db
        self.on_notify = on_notify
        self.on_status_change = on_status_change
        self.poll_interval = poll_interval
        self.debounce_seconds = debounce_seconds

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._lock = threading.Lock()

        # Track file state in sources: {task_id: {file_path_str: {"size": int, "mtime": float, "last_changed": float, "synced": bool}}}
        self._tracked_files: Dict[str, Dict[str, Dict[str, Any]]] = {}

        # Status tracking
        self.current_status: str = "Idle"

    def start(self) -> None:
        """Starts background build sync worker thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._wake_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                daemon=True,
                name="DropFile-BuildSyncWorker",
            )
            self._thread.start()
            print("[BuildSync] Engine started.")

    def stop(self, timeout: float = 3.0) -> None:
        """Stops background build sync worker thread gracefully."""
        self._stop_event.set()
        self._wake_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
        print("[BuildSync] Engine stopped.")

    def trigger_sync_now(self) -> None:
        """Immediately wakes up worker thread to perform a sync scan."""
        self._wake_event.set()

    def reload_tasks(self) -> None:
        """Signals tasks have changed in configuration."""
        with self._lock:
            active_task_ids = {t.get("id") for t in self.config.build_sync_tasks if t.get("id")}
            for tid in list(self._tracked_files.keys()):
                if tid not in active_task_ids:
                    del self._tracked_files[tid]
        self.trigger_sync_now()

    def _set_status(self, status: str) -> None:
        self.current_status = status
        if self.on_status_change:
            try:
                self.on_status_change(status)
            except Exception:
                pass

    def _is_file_ready(self, filepath: Path, prev_info: Optional[Dict[str, Any]], now: float) -> tuple[bool, Dict[str, Any]]:
        """
        Checks whether a file has finished being written and is unlocked.
        Returns (is_ready, current_info).
        """
        try:
            st = filepath.stat()
            cur_size = st.st_size
            cur_mtime = st.st_mtime
        except Exception:
            return False, {}

        # If empty file, not ready yet
        if cur_size == 0:
            return False, {"size": 0, "mtime": cur_mtime, "last_changed": now, "synced": False}

        if prev_info is None:
            # First time seeing this file: start debounce timer
            return False, {"size": cur_size, "mtime": cur_mtime, "last_changed": now, "synced": False}

        # Check if size or mtime changed since last check
        if cur_size != prev_info.get("size") or cur_mtime != prev_info.get("mtime"):
            return False, {"size": cur_size, "mtime": cur_mtime, "last_changed": now, "synced": False}

        # Size and mtime have been stable. Has enough debounce time passed?
        time_stable = now - prev_info.get("last_changed", now)
        if time_stable < self.debounce_seconds:
            return False, prev_info

        # Try opening the file exclusively to ensure compiler/archiver has closed it
        try:
            with open(filepath, "rb") as f:
                # Read 1 byte to ensure read permission and lock availability
                f.read(1)
        except (PermissionError, OSError):
            # File is still locked by another process
            return False, prev_info

        return True, prev_info

    def _copy_with_atomic_rename(self, src: Path, dest_dir: Path) -> Path:
        """
        Copies src into dest_dir using a temporary file first,
        then atomically renames to final destination.
        """
        dest_dir.mkdir(parents=True, exist_ok=True)
        final_dest = dest_dir / src.name
        temp_dest = dest_dir / f".tmp_{time.time_ns()}_{src.name}"

        try:
            shutil.copy2(src, temp_dest)
            if final_dest.exists():
                try:
                    final_dest.unlink()
                except Exception:
                    pass
            temp_dest.replace(final_dest)
            return final_dest
        finally:
            if temp_dest.exists():
                try:
                    temp_dest.unlink()
                except Exception:
                    pass

    def _rotate_versions(self, target_dir: Path, pattern: str, keep_versions: int, project_name: str) -> int:
        """
        Keeps only the newest `keep_versions` files in target_dir matching `pattern`.
        Deletes older files and logs event.
        Returns count of deleted files.
        """
        if keep_versions <= 0 or not target_dir.is_dir():
            return 0

        matching_files: List[Path] = []
        try:
            for item in target_dir.iterdir():
                if item.is_file() and not item.name.startswith((".tmp", "~$")):
                    if fnmatch.fnmatch(item.name.lower(), pattern.lower()):
                        matching_files.append(item)
        except Exception as e:
            print(f"[BuildSync] Error scanning target folder {target_dir} for rotation: {e}")
            return 0

        if len(matching_files) <= keep_versions:
            return 0

        # Sort by mtime descending (newest first)
        def get_sort_key(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except Exception:
                return 0.0

        matching_files.sort(key=get_sort_key, reverse=True)

        to_remove = matching_files[keep_versions:]
        deleted_count = 0
        for old_file in to_remove:
            try:
                old_file.unlink()
                deleted_count += 1
                print(f"[BuildSync] Rotated (deleted) old build: {old_file.name} in {project_name}")
                if self.state_db:
                    try:
                        self.state_db.log_sync(
                            rel_path=f"Build/{project_name}/{old_file.name}",
                            action="BUILD_ROTATE",
                            direction="LOCAL",
                            status="CLEANED",
                            message=f"Removed older build (retained {keep_versions} newest)",
                        )
                    except Exception:
                        pass
            except Exception as e:
                print(f"[BuildSync] Could not delete old build {old_file}: {e}")

        return deleted_count

    def process_task(self, task: Dict[str, Any]) -> int:
        """
        Scans source directory for a given task, copies newly ready builds, and rotates old ones.
        Returns count of newly copied files.
        """
        if not task.get("enabled", True):
            return 0

        task_id = str(task.get("id") or task.get("name") or "task")
        name = str(task.get("name") or "Build")
        source_dir_str = str(task.get("source_dir", "")).strip()
        target_dir_str = str(task.get("target_dir", "")).strip()
        pattern = str(task.get("pattern", "*.zip")).strip() or "*.zip"
        keep_versions = max(1, int(task.get("keep_versions", 5)))

        if not source_dir_str or not target_dir_str:
            return 0

        source_dir = Path(source_dir_str)
        if not source_dir.is_dir():
            return 0

        target_dir = Path(target_dir_str)

        task_cache = self._tracked_files.setdefault(task_id, {})
        now = time.time()
        copied_count = 0

        try:
            entries = list(source_dir.iterdir())
        except Exception as e:
            print(f"[BuildSync] Error listing source dir {source_dir}: {e}")
            return 0

        current_file_keys = set()
        for item in entries:
            if not item.is_file():
                continue
            if item.name.startswith((".", "~$")):
                continue
            if not fnmatch.fnmatch(item.name.lower(), pattern.lower()):
                continue

            file_key = str(item.resolve())
            current_file_keys.add(file_key)

            prev_info = task_cache.get(file_key)
            is_ready, cur_info = self._is_file_ready(item, prev_info, now)
            task_cache[file_key] = cur_info

            # If already marked as synced and file hasn't changed, skip
            if prev_info and prev_info.get("synced") and cur_info.get("size") == prev_info.get("size") and cur_info.get("mtime") == prev_info.get("mtime"):
                continue

            if not is_ready:
                continue

            # Check if target already has this exact file with same size and mtime
            target_dest = target_dir / item.name
            if target_dest.exists():
                try:
                    t_st = target_dest.stat()
                    s_st = item.stat()
                    if t_st.st_size == s_st.st_size and abs(t_st.st_mtime - s_st.st_mtime) < 1.0:
                        # Already synced
                        cur_info["synced"] = True
                        continue
                except Exception:
                    pass

            # Proceed to copy
            print(f"[BuildSync] Ready to sync build: {item.name} -> {target_dir}")
            self._set_status(f"Copying {item.name}...")
            try:
                self._copy_with_atomic_rename(item, target_dir)
                cur_info["synced"] = True
                copied_count += 1
                print(f"[BuildSync] Successfully copied {item.name} to {target_dir}")

                # Log to state_db
                if self.state_db:
                    try:
                        self.state_db.log_sync(
                            rel_path=f"Build/{name}/{item.name}",
                            action="BUILD_SYNC",
                            direction="UPLOAD",
                            status="SUCCESS",
                            message=f"Copied to {target_dir}",
                        )
                    except Exception as e:
                        print(f"[BuildSync] DB log error: {e}")

                # Version rotation
                self._rotate_versions(target_dir, pattern, keep_versions, name)

                # Send user notification
                if self.on_notify:
                    try:
                        self.on_notify(
                            t("notify_build_synced_title"),
                            t("notify_build_synced_msg", name=name, file=item.name, target=str(target_dir), versions=keep_versions),
                        )
                    except Exception as e:
                        print(f"[BuildSync] Notification error: {e}")

            except Exception as e:
                print(f"[BuildSync] Failed copying {item.name} to {target_dir}: {e}")
                if self.state_db:
                    try:
                        self.state_db.log_sync(
                            rel_path=f"Build/{name}/{item.name}",
                            action="BUILD_SYNC",
                            direction="UPLOAD",
                            status="ERROR",
                            message=f"Copy failed: {e}",
                        )
                    except Exception:
                        pass

        # Cleanup removed files from cache
        for old_k in list(task_cache.keys()):
            if old_k not in current_file_keys:
                del task_cache[old_k]

        return copied_count

    def _run_loop(self) -> None:
        """Worker thread main loop."""
        print("[BuildSync] Background worker loop started.")
        while not self._stop_event.is_set():
            if self.config.build_sync_enabled:
                tasks = list(self.config.build_sync_tasks)
                total_copied = 0
                for task in tasks:
                    if self._stop_event.is_set():
                        break
                    try:
                        total_copied += self.process_task(task)
                    except Exception as e:
                        print(f"[BuildSync] Error processing task {task.get('name')}: {e}")

                if total_copied > 0:
                    self._set_status(t("build_sync_status_done"))
                else:
                    self._set_status(t("build_sync_status_idle"))
            else:
                self._set_status(t("build_sync_status_disabled"))

            # Sleep or wait until explicitly awakened
            self._wake_event.wait(timeout=self.poll_interval)
            self._wake_event.clear()

        self._set_status(t("build_sync_status_disabled"))
        print("[BuildSync] Background worker loop ended.")
