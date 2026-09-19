"""
Asynchronous File System Watcher for DropSync Server.
Uses Linux native inotify / watchdog with debounced write detection.
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set


class FileSystemWatcher:
    def __init__(
        self,
        root_dir: Path,
        ignore_patterns: Optional[List[str]] = None,
        debounce_delay: float = 1.0,
        on_change_callback: Optional[Callable[[str], None]] = None,
        on_delete_callback: Optional[Callable[[str], None]] = None,
    ):
        self.root_dir = root_dir.resolve()
        self.ignore_patterns = ignore_patterns or []
        self.debounce_delay = debounce_delay
        self.on_change = on_change_callback
        self.on_delete = on_delete_callback

        # Set of paths currently being modified locally by DropSync sync engine
        # to prevent recursive echo feedback loops.
        self._suppressed_paths: Set[str] = set()
        self._suppress_lock = threading.Lock()

        # Debounce tracking: {rel_path: timestamp}
        self._pending_changes: Dict[str, float] = {}
        self._debounce_lock = threading.Lock()

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._observer: Optional[Any] = None

    def suppress_path(self, rel_path: str, duration: float = 3.0) -> None:
        """Suppresses watcher notifications for a path (e.g. while downloading a file from peer)."""
        norm_path = rel_path.replace("\\", "/").strip("/")
        with self._suppress_lock:
            self._suppressed_paths.add(norm_path)

        def unsuppress():
            time.sleep(duration)
            with self._suppress_lock:
                self._suppressed_paths.discard(norm_path)

        threading.Thread(target=unsuppress, daemon=True).start()

    def is_ignored(self, rel_path: str) -> bool:
        norm_path = rel_path.replace("\\", "/").strip("/")
        parts = norm_path.split("/")

        # Ignore hidden/internal dropsync folders
        for part in parts:
            if part.startswith(".dropsync") or part == ".git":
                return True

        filename = parts[-1]
        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(norm_path, pattern):
                return True
        return False

    def _notify_change_debounced(self, rel_path: str) -> None:
        norm_path = rel_path.replace("\\", "/").strip("/")
        with self._suppress_lock:
            if norm_path in self._suppressed_paths:
                return

        if self.is_ignored(norm_path):
            return

        with self._debounce_lock:
            self._pending_changes[norm_path] = time.time()

    def _notify_delete(self, rel_path: str) -> None:
        norm_path = rel_path.replace("\\", "/").strip("/")
        with self._suppress_lock:
            if norm_path in self._suppressed_paths:
                return

        if self.is_ignored(norm_path):
            return

        with self._debounce_lock:
            self._pending_changes.pop(norm_path, None)

        if self.on_delete:
            try:
                self.on_delete(norm_path)
            except Exception as e:
                print(f"[Watcher] Error in on_delete callback for {norm_path}: {e}")

    def _debounce_worker(self) -> None:
        """Background thread checking debounced writes."""
        while self._running:
            time.sleep(0.2)
            now = time.time()
            to_emit: List[str] = []

            with self._debounce_lock:
                for path, last_time in list(self._pending_changes.items()):
                    if now - last_time >= self.debounce_delay:
                        to_emit.append(path)
                        del self._pending_changes[path]

            for path in to_emit:
                # Verify file still exists and is accessible
                full_path = self.root_dir / path
                if full_path.is_file():
                    if self.on_change:
                        try:
                            self.on_change(path)
                        except Exception as e:
                            print(f"[Watcher] Error in on_change callback for {path}: {e}")

    def start(self) -> None:
        """Starts the watcher using watchdog or inotify fallback."""
        if self._running:
            return
        self._running = True

        # Start debounce loop
        self._thread = threading.Thread(target=self._debounce_worker, daemon=True, name="WatcherDebounce")
        self._thread.start()

        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer

            watcher_self = self

            class WatchdogHandler(FileSystemEventHandler):
                def on_modified(self, event):
                    if not event.is_directory:
                        try:
                            rel = Path(event.src_path).resolve().relative_to(watcher_self.root_dir)
                            watcher_self._notify_change_debounced(str(rel))
                        except Exception:
                            pass

                def on_created(self, event):
                    if not event.is_directory:
                        try:
                            rel = Path(event.src_path).resolve().relative_to(watcher_self.root_dir)
                            watcher_self._notify_change_debounced(str(rel))
                        except Exception:
                            pass

                def on_deleted(self, event):
                    if not event.is_directory:
                        try:
                            rel = Path(event.src_path).resolve().relative_to(watcher_self.root_dir)
                            watcher_self._notify_delete(str(rel))
                        except Exception:
                            pass

                def on_moved(self, event):
                    if not event.is_directory:
                        try:
                            rel_src = Path(event.src_path).resolve().relative_to(watcher_self.root_dir)
                            watcher_self._notify_delete(str(rel_src))
                        except Exception:
                            pass
                        try:
                            rel_dest = Path(event.dest_path).resolve().relative_to(watcher_self.root_dir)
                            watcher_self._notify_change_debounced(str(rel_dest))
                        except Exception:
                            pass

            self._observer = Observer()
            self._observer.schedule(WatchdogHandler(), str(self.root_dir), recursive=True)
            self._observer.start()
            print(f"[Watcher] Started watchdog observer on {self.root_dir}")

        except ImportError:
            print(f"[Watcher] Watchdog not installed, falling back to polling scanner.")
            threading.Thread(target=self._fallback_polling_loop, daemon=True, name="WatcherPolling").start()

    def _fallback_polling_loop(self) -> None:
        """Fallback polling watcher if watchdog/inotify is missing."""
        known_files: Dict[str, float] = {}
        while self._running:
            time.sleep(2.0)
            current_files: Dict[str, float] = {}
            try:
                for root, _, files in os.walk(str(self.root_dir)):
                    for f in files:
                        p = Path(root) / f
                        try:
                            rel = str(p.relative_to(self.root_dir)).replace("\\", "/")
                            if not self.is_ignored(rel):
                                mtime = p.stat().st_mtime
                                current_files[rel] = mtime
                                if rel not in known_files or known_files[rel] != mtime:
                                    self._notify_change_debounced(rel)
                        except Exception:
                            pass

                # Check deleted
                for rel in list(known_files.keys()):
                    if rel not in current_files:
                        self._notify_delete(rel)

                known_files = current_files
            except Exception as e:
                print(f"[Watcher] Error in fallback polling: {e}")

    def stop(self) -> None:
        self._running = False
        if self._observer:
            try:
                self._observer.stop()
                self._observer.join(timeout=2.0)
            except Exception:
                pass
            self._observer = None
