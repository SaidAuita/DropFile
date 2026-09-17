"""
DropFile Synchronization Engine.
Coordinates local watchdog filesystem events with remote FileBrowser polling.
Implements bidirectional sync, loop prevention, debouncing, and conflict handling.
"""

import fnmatch
import json
import os
import platform
import re
import shutil
import socket
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from config import Config
from fb_client import FileBrowserClient, RemoteItem
from i18n import t
from remote_control import RemoteControlManager
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
        self._sync_lock = threading.RLock()
        self._observer: Optional[Observer] = None
        self._poll_thread: Optional[threading.Thread] = None

        # Suppression set to prevent echo loops when downloading remote files
        self._suppressed_paths: Dict[str, float] = {}  # rel_path -> timestamp until suppressed
        self._suppress_lock = threading.Lock()

        # Debounce dictionary for local file events: rel_path -> last event timestamp
        self._pending_local_events: Dict[str, float] = {}
        # Debounce dictionary for local directory events: rel_path -> (timestamp, event_type)
        self._pending_local_dir_events: Dict[str, Tuple[float, str]] = {}
        self._pending_lock = threading.Lock()
        self._debounce_seconds = 2.0

        self.last_sync_time: float = 0.0
        self.current_state = "idle"
        self.status_message = t("status_ready")

        self.active_server_index = self.config.primary_server_index
        self._last_primary_probe_time: float = 0.0

        self._last_servers_sync_status: Dict[str, Any] = {}

        # Distributed sync leader coordination
        self.hostname = socket.gethostname()
        self.client_id = f"{self.hostname}_{uuid.uuid4().hex[:6]}"
        self.is_sync_leader = False
        self.leader_info: Dict[str, Any] = {}

        # Remote control & emergency actions across all server routes
        rc_routes = self._get_all_remote_control_routes()
        self.remote_control = RemoteControlManager(
            client=self.client,
            remote_path=self.active_remote_path,
            secondary_routes=rc_routes[1:] if len(rc_routes) > 1 else None,
        )
        self._last_rc_poll: float = 0.0
        self._last_rc_heartbeat: float = 0.0

        try:
            self._last_cfg_mtime = self.config.config_file.stat().st_mtime if self.config.config_file.exists() else 0.0
        except Exception:
            self._last_cfg_mtime = 0.0

    @property
    def active_remote_path(self) -> str:
        """Returns the remote directory path for the currently active server."""
        if self.active_server_index == 2:
            return self.config.backup_remote_path
        return self.config.remote_path

    def get_active_server_label(self) -> str:
        """Returns server indicator label (e.g. '[Сервер 1]' or '[Сервер 2]' or '[Сервер 1 ⇄ 2]') if backup server is enabled."""
        if self.config.backup_server_enabled:
            if self.config.sync_backup_server:
                return f"[{t('server_badge')} 1 ⇄ 2]"
            return f"[{t('server_badge')} {self.active_server_index}]"
        return ""

    def get_server_credentials(self, index: int) -> Tuple[str, str, str, str]:
        """Returns (url, username, password, remote_path) for server 1 or 2."""
        if index == 2:
            url = self.config.backup_server_url
            user = self.config.backup_username or self.config.username
            pwd = self.config.backup_password or self.config.password
            rem = self.config.backup_remote_path
            return url, user, pwd, rem
        else:
            return self.config.server_url, self.config.username, self.config.password, self.config.remote_path

    def _get_secondary_client(self) -> Optional[Tuple[FileBrowserClient, str]]:
        """Returns (FileBrowserClient, remote_path) for the secondary/backup server if enabled."""
        if not self.config.backup_server_enabled:
            return None
        sec_idx = 2 if self.active_server_index == 1 else 1
        url, user, pwd, rem = self.get_server_credentials(sec_idx)
        if not url or not user:
            return None
        timeout = self.client.timeout if self.client else 15
        return FileBrowserClient(base_url=url, username=user, password=pwd, timeout=timeout), rem

    def _get_all_remote_control_routes(self) -> List[Tuple[FileBrowserClient, str]]:
        """Returns (client, remote_path) pairs for all configured and accessible servers."""
        routes: List[Tuple[FileBrowserClient, str]] = []
        timeout = self.client.timeout if self.client else 15
        # Route for Server 1
        if self.config.server_url and self.config.username:
            if self.client and self.client.base_url == self.config.server_url:
                c1 = self.client
            else:
                c1 = FileBrowserClient(
                    base_url=self.config.server_url,
                    username=self.config.username,
                    password=self.config.password,
                    timeout=timeout,
                )
            routes.append((c1, self.config.remote_path))

        # Route for Server 2 (backup)
        if self.config.backup_server_enabled and self.config.backup_server_url:
            b_user = self.config.backup_username or self.config.username
            b_pwd = self.config.backup_password or self.config.password
            if self.client and self.client.base_url == self.config.backup_server_url:
                c2 = self.client
            else:
                c2 = FileBrowserClient(
                    base_url=self.config.backup_server_url,
                    username=b_user,
                    password=b_pwd,
                    timeout=timeout,
                )
            routes.append((c2, self.config.backup_remote_path))

        if not routes and self.client:
            routes.append((self.client, self.active_remote_path))
        return routes

    @property
    def leader_lock_remote_path(self) -> str:
        """Returns the remote path for the distributed leader lock file."""
        return f"{self.config.remote_path.rstrip('/')}/.dropfile_leader.json"

    def acquire_or_renew_sync_leader(self) -> Tuple[bool, Dict[str, Any]]:
        """
        Acquires or renews the distributed leader lock on the primary server.
        Ensures only ONE client in the network actively mirrors servers.
        Lock expires after 180 seconds if client goes offline.
        Returns (is_leader: bool, leader_dict: dict).
        """
        if not self.config.backup_server_enabled or not self.config.sync_backup_server:
            self.is_sync_leader = False
            self.leader_info = {}
            return False, {}

        lock_path = self.leader_lock_remote_path
        now = time.time()
        lease_duration = 180.0  # 3 minutes lease

        current_lock: Optional[Dict[str, Any]] = None
        try:
            raw_text = self.client.read_text_file(lock_path)
            if raw_text:
                current_lock = json.loads(raw_text)
        except Exception:
            current_lock = None

        can_claim = False
        if not current_lock:
            can_claim = True
        else:
            expires_at = float(current_lock.get("expires_at", 0.0))
            holder_id = current_lock.get("client_id", "")
            if holder_id == self.client_id:
                # Renew our existing lock
                can_claim = True
            elif now > expires_at:
                # Stale lock expired (previous leader PC turned off)
                can_claim = True

        if can_claim:
            new_lock = {
                "client_id": self.client_id,
                "hostname": self.hostname,
                "acquired_at": now,
                "expires_at": now + lease_duration,
            }
            try:
                ok = self.client.write_text_file(lock_path, json.dumps(new_lock, ensure_ascii=False))
                if ok:
                    self.is_sync_leader = True
                    self.leader_info = new_lock
                    return True, new_lock
            except Exception as e:
                print(f"[SyncEngine] Error writing leader lock: {e}")

        self.is_sync_leader = False
        self.leader_info = current_lock or {}
        return False, self.leader_info

    def release_sync_leader(self) -> None:
        """Releases the leader lock so another client can immediately take over."""
        if not self.is_sync_leader:
            return
        try:
            lock_path = self.leader_lock_remote_path
            self.client.delete_resource(lock_path)
            print(f"[SyncEngine] Released leader lock: {self.client_id}")
        except Exception as e:
            print(f"[SyncEngine] Error releasing leader lock: {e}")
        finally:
            self.is_sync_leader = False
            self.leader_info = {}

    def apply_server_connection(self, index: int) -> None:
        """Configures client with credentials of server index (1 or 2)."""
        url, user, pwd, _ = self.get_server_credentials(index)
        if self.client:
            self.client.base_url = url
            self.client.username = user
            self.client.password = pwd
            self.client.token = None
        self.active_server_index = index
        if hasattr(self, "remote_control") and self.remote_control:
            self.remote_control.client = self.client
            self.remote_control.remote_path = self.active_remote_path
            self.remote_control.set_routes(self._get_all_remote_control_routes())

    def compare_servers_status(self) -> Dict[str, Any]:
        """
        Inspects Server 1 and Server 2, comparing file counts and newest file modification times.
        Returns status dictionary and caches it in self._last_servers_sync_status.
        """
        if not self.config.backup_server_enabled:
            res = {
                "enabled": False,
                "state": "disabled",
                "badge": "⚪ " + t("servers_sync_disabled"),
                "summary": t("servers_sync_disabled"),
                "server1": {"online": False, "url": self.config.server_url, "file_count": 0, "latest_file": "", "latest_mtime": 0.0, "latest_time_str": "", "error": ""},
                "server2": {"online": False, "url": self.config.backup_server_url, "file_count": 0, "latest_file": "", "latest_mtime": 0.0, "latest_time_str": "", "error": ""},
                "last_checked": time.time(),
            }
            self._last_servers_sync_status = res
            return res

        def parse_iso_mtime(iso_val: str) -> float:
            if not iso_val:
                return 0.0
            try:
                clean_iso = iso_val.replace("Z", "+00:00")
                return datetime.fromisoformat(clean_iso).timestamp()
            except Exception:
                return 0.0

        # Inspect Server 1
        url1, u1, p1, r1 = self.get_server_credentials(1)
        s1_info = {"online": False, "url": url1, "file_count": 0, "latest_file": "", "latest_mtime": 0.0, "latest_time_str": "", "error": ""}
        if url1 and u1:
            try:
                c1 = FileBrowserClient(base_url=url1, username=u1, password=p1, timeout=8)
                ok1, msg1 = c1.test_connection()
                if ok1:
                    s1_info["online"] = True
                    items1 = c1.list_recursive(r1)
                    files1 = [it for it in items1 if not it.is_dir and not self.is_ignored(it.path)]
                    s1_info["file_count"] = len(files1)
                    if files1:
                        newest1 = max(files1, key=lambda it: parse_iso_mtime(it.modified))
                        s1_info["latest_mtime"] = parse_iso_mtime(newest1.modified)
                        s1_info["latest_file"] = newest1.name
                        if s1_info["latest_mtime"] > 0:
                            s1_info["latest_time_str"] = datetime.fromtimestamp(s1_info["latest_mtime"]).strftime("%d.%m.%Y %H:%M")
                else:
                    s1_info["error"] = msg1
            except Exception as e:
                s1_info["error"] = str(e)

        # Inspect Server 2
        url2, u2, p2, r2 = self.get_server_credentials(2)
        s2_info = {"online": False, "url": url2, "file_count": 0, "latest_file": "", "latest_mtime": 0.0, "latest_time_str": "", "error": ""}
        if url2 and u2:
            try:
                c2 = FileBrowserClient(base_url=url2, username=u2, password=p2, timeout=8)
                ok2, msg2 = c2.test_connection()
                if ok2:
                    s2_info["online"] = True
                    items2 = c2.list_recursive(r2)
                    files2 = [it for it in items2 if not it.is_dir and not self.is_ignored(it.path)]
                    s2_info["file_count"] = len(files2)
                    if files2:
                        newest2 = max(files2, key=lambda it: parse_iso_mtime(it.modified))
                        s2_info["latest_mtime"] = parse_iso_mtime(newest2.modified)
                        s2_info["latest_file"] = newest2.name
                        if s2_info["latest_mtime"] > 0:
                            s2_info["latest_time_str"] = datetime.fromtimestamp(s2_info["latest_mtime"]).strftime("%d.%m.%Y %H:%M")
                else:
                    s2_info["error"] = msg2
            except Exception as e:
                s2_info["error"] = str(e)

        # Determine comparison state
        if not s1_info["online"] and not s2_info["online"]:
            state = "both_offline"
            badge = "🔴 " + t("servers_sync_both_offline")
            summary = t("servers_sync_both_offline")
        elif not s1_info["online"]:
            state = "server1_offline"
            badge = "🔴 " + t("servers_sync_s1_offline")
            summary = t("servers_sync_s1_offline")
        elif not s2_info["online"]:
            state = "server2_offline"
            badge = "🔴 " + t("servers_sync_s2_offline")
            summary = t("servers_sync_s2_offline")
        else:
            c1 = s1_info["file_count"]
            c2 = s2_info["file_count"]
            mt1 = s1_info["latest_mtime"]
            mt2 = s2_info["latest_mtime"]

            if c1 == c2 and abs(mt1 - mt2) < 3.0:
                state = "synced"
                badge = t("servers_sync_synced", count=c1)
                summary = t("servers_sync_synced", count=c1)
            elif mt1 > mt2 + 3.0:
                state = "server1_newer"
                badge = t("servers_sync_s1_newer")
                summary = f"{t('servers_sync_s1_newer')} ({c1} vs {c2})"
            elif mt2 > mt1 + 3.0:
                state = "server2_newer"
                badge = t("servers_sync_s2_newer")
                summary = f"{t('servers_sync_s2_newer')} ({c2} vs {c1})"
            elif c1 != c2:
                state = "diff_count"
                badge = t("servers_sync_diff_count", c1=c1, c2=c2)
                summary = t("servers_sync_diff_count", c1=c1, c2=c2)
            else:
                state = "synced"
                badge = t("servers_sync_synced", count=c1)
                summary = t("servers_sync_synced", count=c1)

        # Determine coordinator (leader) info
        leader_stat = {
            "is_self": self.is_sync_leader,
            "hostname": self.leader_info.get("hostname", ""),
            "client_id": self.leader_info.get("client_id", ""),
            "expires_at": float(self.leader_info.get("expires_at", 0.0)),
        }
        if self.config.backup_server_enabled and self.config.sync_backup_server:
            if not leader_stat["hostname"] or time.time() > leader_stat["expires_at"]:
                try:
                    raw_txt = self.client.read_text_file(self.leader_lock_remote_path)
                    if raw_txt:
                        l_data = json.loads(raw_txt)
                        leader_stat["hostname"] = l_data.get("hostname", "")
                        leader_stat["client_id"] = l_data.get("client_id", "")
                        leader_stat["expires_at"] = float(l_data.get("expires_at", 0.0))
                        leader_stat["is_self"] = (leader_stat["client_id"] == self.client_id)
                        self.is_sync_leader = leader_stat["is_self"]
                        self.leader_info = l_data
                except Exception:
                    pass

        res = {
            "enabled": True,
            "state": state,
            "badge": badge,
            "summary": summary,
            "server1": s1_info,
            "server2": s2_info,
            "leader": leader_stat,
            "last_checked": time.time(),
        }
        self._last_servers_sync_status = res
        return res

    def get_last_servers_sync_status(self) -> Dict[str, Any]:
        """Returns the cached server sync comparison without blocking. If not yet available, returns placeholder."""
        cached = getattr(self, "_last_servers_sync_status", None)
        if cached:
            return cached

        if not self.config.backup_server_enabled:
            return {
                "enabled": False,
                "state": "disabled",
                "badge": "⚪ " + t("servers_sync_disabled"),
                "summary": t("servers_sync_disabled"),
                "server1": {"online": False, "file_count": 0, "latest_mtime": 0.0, "latest_file": "", "latest_time_str": "-", "error": ""},
                "server2": {"online": False, "file_count": 0, "latest_mtime": 0.0, "latest_file": "", "latest_time_str": "-", "error": ""},
                "leader": {"is_self": False, "hostname": "", "client_id": "", "expires_at": 0.0},
                "last_checked": 0.0,
            }

        return {
            "enabled": True,
            "state": "checking",
            "badge": "⏳ " + t("servers_sync_status_title"),
            "summary": t("servers_sync_status_title"),
            "server1": {"online": False, "file_count": 0, "latest_mtime": 0.0, "latest_file": "", "latest_time_str": "-", "error": ""},
            "server2": {"online": False, "file_count": 0, "latest_mtime": 0.0, "latest_file": "", "latest_time_str": "-", "error": ""},
            "leader": {"is_self": False, "hostname": "", "client_id": "", "expires_at": 0.0},
            "last_checked": 0.0,
        }


    def sync_servers_mirror(self) -> Tuple[int, int]:
        """
        Synchronizes files between primary server, secondary server, and local folder.
        Ensures both servers have identical files.
        Returns (synced_count, error_count).
        """
        if not self.config.backup_server_enabled:
            return 0, 0

        url1, u1, p1, r1 = self.get_server_credentials(1)
        url2, u2, p2, r2 = self.get_server_credentials(2)
        if not url1 or not u1 or not url2 or not u2:
            return 0, 0

        with self._sync_lock:
            synced_count = 0
            error_count = 0

            try:
                c1 = FileBrowserClient(base_url=url1, username=u1, password=p1, timeout=15)
                c2 = FileBrowserClient(base_url=url2, username=u2, password=p2, timeout=15)

                ok1, _ = c1.test_connection()
                ok2, _ = c2.test_connection()

                if not ok1 or not ok2:
                    self.compare_servers_status()
                    return 0, 1

                c1.ensure_remote_dir_exists(r1)
                c2.ensure_remote_dir_exists(r2)

                items1 = c1.list_recursive(r1)
                items2 = c2.list_recursive(r2)

                files1: Dict[str, RemoteItem] = {}
                prefix1 = r1.strip("/")
                for it in items1:
                    clean_p = it.path.strip("/")
                    rel = clean_p[len(prefix1):].strip("/.") if clean_p.lower().startswith(prefix1.lower()) else clean_p.strip("/.")
                    if rel and not it.is_dir and not self.is_ignored(rel):
                        files1[rel] = it

                files2: Dict[str, RemoteItem] = {}
                prefix2 = r2.strip("/")
                for it in items2:
                    clean_p = it.path.strip("/")
                    rel = clean_p[len(prefix2):].strip("/.") if clean_p.lower().startswith(prefix2.lower()) else clean_p.strip("/.")
                    if rel and not it.is_dir and not self.is_ignored(rel):
                        files2[rel] = it

                def parse_iso(iso_str: str) -> float:
                    try:
                        return datetime.fromisoformat(iso_str.replace("Z", "+00:00")).timestamp()
                    except Exception:
                        return 0.0

                # A. Push files from Server 1 -> Server 2 (if missing or older on Server 2)
                for rel, it1 in files1.items():
                    it2 = files2.get(rel)
                    local_target = self.config.local_path / rel

                    need_push = False
                    if not it2:
                        need_push = True
                    else:
                        mt1 = parse_iso(it1.modified)
                        mt2 = parse_iso(it2.modified)
                        if mt1 > mt2 + 3.0 and it1.size != it2.size:
                            need_push = True

                    if need_push:
                        if not local_target.exists() or local_target.stat().st_size != it1.size:
                            local_target.parent.mkdir(parents=True, exist_ok=True)
                            c1.download_file(f"{r1}/{rel}", local_target)

                        if local_target.exists():
                            if c2.upload_file(local_target, f"{r2}/{rel}"):
                                synced_count += 1
                            else:
                                error_count += 1

                # B. Push files from Server 2 -> Server 1 (if missing or older on Server 1)
                for rel, it2 in files2.items():
                    it1 = files1.get(rel)
                    local_target = self.config.local_path / rel

                    need_push = False
                    if not it1:
                        if self.state_db.is_tracked(rel) and not local_target.exists():
                            c2.delete_resource(f"{r2}/{rel}")
                        else:
                            need_push = True
                    else:
                        mt1 = parse_iso(it1.modified)
                        mt2 = parse_iso(it2.modified)
                        if mt2 > mt1 + 3.0 and it1.size != it2.size:
                            need_push = True

                    if need_push:
                        local_target.parent.mkdir(parents=True, exist_ok=True)
                        if c2.download_file(f"{r2}/{rel}", local_target):
                            if c1.upload_file(local_target, f"{r1}/{rel}"):
                                synced_count += 1
                                stat = local_target.stat()
                                rec = FileRecord(
                                    rel_path=rel,
                                    local_mtime=stat.st_mtime,
                                    local_size=stat.st_size,
                                    remote_mtime=it2.modified,
                                    remote_size=it2.size,
                                    content_hash=compute_file_hash(local_target),
                                    is_dir=False,
                                    last_sync_time=time.time(),
                                )
                                self.state_db.upsert_record(rec)
                            else:
                                error_count += 1

            except Exception as e:
                print(f"[SyncEngine] sync_servers_mirror error: {e}")
                error_count += 1
            finally:
                self.compare_servers_status()

            return synced_count, error_count

    def set_status(self, message: str, state: str) -> None:
        if self.config.backup_server_enabled:
            badge = self.get_active_server_label()
            if badge and badge not in message and state in ("idle", "syncing"):
                message = f"{message} {badge}"
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

        # Start Watchdog with graceful fallback to PollingObserver (crucial for macOS VMs)
        handler = LocalFolderHandler(self)
        try:
            self._observer = Observer()
            self._observer.schedule(handler, str(self.config.local_path), recursive=True)
            self._observer.start()
        except Exception as e:
            print(f"[SyncEngine] Native observer failed ({e}), falling back to PollingObserver...")
            try:
                from watchdog.observers.polling import PollingObserver
                self._observer = PollingObserver()
                self._observer.schedule(handler, str(self.config.local_path), recursive=True)
                self._observer.start()
            except Exception as e2:
                print(f"[SyncEngine] PollingObserver fallback failed: {e2}")
                self._observer = None

        # Start background polling / processing thread
        self._poll_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._poll_thread.start()

        self.set_status(t("status_started"), "idle")
        print("[SyncEngine] Started.")

    def stop(self) -> None:
        """Stops the sync engine."""
        self._running = False
        self.release_sync_leader()
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

    def on_local_directory_event(self, local_abs_path: str, event_type: str) -> None:
        """Called by watchdog when a directory event (create/delete) is detected locally."""
        if not self._running or self._paused:
            return

        try:
            rel = os.path.relpath(local_abs_path, str(self.config.local_path)).replace("\\", "/")
        except ValueError:
            return

        clean_rel = rel.strip("/.")
        if not clean_rel or self.is_ignored(local_abs_path):
            return

        if self._is_suppressed(clean_rel):
            return

        with self._pending_lock:
            self._pending_local_dir_events[clean_rel] = (time.time(), event_type)

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
                    self.apply_server_connection(self.config.primary_server_index)
                    self.trigger_sync_now()
        except Exception as e:
            print(f"[SyncEngine] Error checking config reload: {e}")

    def _worker_loop(self) -> None:
        """Main background loop handling debounced local events and periodic polling."""
        last_poll = 0.0
        last_cleanup = 0.0

        # Perform initial sync on startup
        time.sleep(1.0)
        url, user, pwd, _ = self.get_server_credentials(self.active_server_index)
        if not url or not user:
            # Fallback to primary if active server credentials not set
            if self.active_server_index != self.config.primary_server_index:
                self.apply_server_connection(self.config.primary_server_index)
                url, user, pwd, _ = self.get_server_credentials(self.active_server_index)

        if url and user:
            self.apply_server_connection(self.active_server_index)
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

                # Process debounced local directory changes
                dir_events_to_process = []
                with self._pending_lock:
                    for rel, (timestamp, ev_type) in list(self._pending_local_dir_events.items()):
                        if now - timestamp >= self._debounce_seconds:
                            dir_events_to_process.append((rel, ev_type))
                            del self._pending_local_dir_events[rel]

                for rel, ev_type in dir_events_to_process:
                    if not self._paused:
                        self._sync_single_local_directory(rel, ev_type)

                # Process debounced local file changes
                to_process = []
                with self._pending_lock:
                    for rel, timestamp in list(self._pending_local_events.items()):
                        if now - timestamp >= self._debounce_seconds:
                            to_process.append(rel)
                            del self._pending_local_events[rel]

                for rel in to_process:
                    if not self._paused:
                        self._sync_single_local_file(rel)

                # Periodic Remote Control polling & heartbeat
                if self.config.remote_control_enabled and not self._paused:
                    if now - self._last_rc_poll >= 5.0:
                        self._last_rc_poll = now
                        self._process_remote_control()

                    if now - self._last_rc_heartbeat >= 60.0:
                        self._last_rc_heartbeat = now
                        self._publish_remote_heartbeat()

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

    def _process_remote_control(self) -> None:
        """Checks for incoming remote control commands targeted at this computer."""
        try:
            results = self.remote_control.poll_and_dispatch(
                local_device_name=self.config.remote_control_device_name,
                local_pin=self.config.remote_control_pin,
                allow_reboot=self.config.remote_control_allow_reboot,
                allow_process_list=self.config.remote_control_allow_process_list,
                whitelist=self.config.remote_control_whitelist,
                strict_whitelist=self.config.remote_control_strict_whitelist,
            )
            for res in results:
                action = res.get("action", "")
                success = res.get("success", False)
                msg = res.get("message") or res.get("error", "")
                sender = res.get("sender", "unknown")
                print(f"[SyncEngine] Remote action '{action}' executed: success={success}, msg={msg} (From: {sender})")
                if self.on_notify:
                    title = f"DropFile: {t('remote_notify_title')}"
                    body = f"{action}: {msg} (From: {sender})"
                    self.on_notify(title, body)
        except Exception as e:
            print(f"[SyncEngine] _process_remote_control error: {e}")

    def _publish_remote_heartbeat(self) -> None:
        """Publishes heartbeat of this computer to .dropfile_control."""
        try:
            device_info = {
                "device_name": self.config.remote_control_device_name,
                "hostname": self.hostname,
                "platform": sys.platform,
                "allow_reboot": self.config.remote_control_allow_reboot,
                "allow_process_list": self.config.remote_control_allow_process_list,
                "whitelist": self.config.remote_control_whitelist,
            }
            self.remote_control.publish_heartbeat(device_info)
        except Exception as e:
            print(f"[SyncEngine] _publish_remote_heartbeat error: {e}")

    def get_remote_devices(self) -> List[Dict[str, Any]]:
        """Returns list of online devices detected on the FileBrowser server."""
        if hasattr(self, "remote_control") and self.remote_control:
            return self.remote_control.get_online_devices()
        return []

    def send_remote_command(
        self,
        target_device: str,
        action: str,
        payload: Dict[str, Any],
        pin: str,
        timeout: int = 60,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Sends a remote command to target_device and waits for execution response."""
        sender = self.config.remote_control_device_name
        return self.remote_control.send_command_and_wait(
            target_device=target_device,
            sender_device=sender,
            action=action,
            payload=payload,
            secret_pin=pin,
            timeout_seconds=timeout,
            status_callback=status_callback,
        )

    def _sync_single_local_directory(self, rel_path: str, event_type: str) -> None:
        """Handles local directory creation or deletion."""
        if not self.config.server_url or not self.config.username:
            return

        clean_rel = rel_path.replace("\\", "/").strip("/.")
        if not clean_rel:
            return

        local_dir = self.config.local_path / clean_rel

        with self._sync_lock:
            if event_type == "deleted" or not local_dir.exists():
                # Directory was deleted locally
                if self.state_db.is_tracked(clean_rel):
                    self.set_status(t("status_deleting_remote", file=clean_rel), "syncing")
                    remote_dest = f"{self.active_remote_path}/{clean_rel}"
                    ok = self.client.delete_resource(remote_dest)
                    if ok:
                        self.state_db.delete_record_and_children(clean_rel)
                        self.state_db.log_sync(
                            clean_rel,
                            "delete",
                            "local->remote",
                            "success",
                            "Directory deleted locally",
                        )
                        print(f"[SyncEngine] Deleted remote directory: {clean_rel}")
                    else:
                        self.state_db.log_sync(
                            clean_rel,
                            "delete",
                            "local->remote",
                            "error",
                            "Remote directory delete failed",
                        )

                    # Mirror delete to secondary server if dual sync enabled
                    if self.config.backup_server_enabled and self.config.sync_backup_server:
                        sec = self._get_secondary_client()
                        if sec:
                            sec_client, sec_rem = sec
                            try:
                                sec_client.delete_resource(f"{sec_rem}/{clean_rel}")
                            except Exception:
                                pass

                    self.set_status(t("status_synced"), "idle")

            elif event_type == "created" and local_dir.is_dir():
                # Directory was created locally
                remote_dest = f"{self.active_remote_path}/{clean_rel}"
                ok = self.client.create_directory(remote_dest)
                if ok:
                    rec = FileRecord(
                        rel_path=clean_rel,
                        is_dir=True,
                        last_sync_time=time.time(),
                    )
                    self.state_db.upsert_record(rec)
                    self.state_db.log_sync(clean_rel, "create_dir", "local->remote", "success")
                    print(f"[SyncEngine] Created remote directory: {clean_rel}")

                    # Mirror create to secondary server if dual sync enabled
                    if self.config.backup_server_enabled and self.config.sync_backup_server:
                        sec = self._get_secondary_client()
                        if sec:
                            sec_client, sec_rem = sec
                            try:
                                sec_client.create_directory(f"{sec_rem}/{clean_rel}")
                            except Exception:
                                pass


    def _sync_single_local_file(self, rel_path: str) -> None:
        """Uploads a local file or handles its local deletion."""
        if not self.config.server_url or not self.config.username:
            return

        local_file = self.config.local_path / rel_path
        clean_rel = rel_path.replace("\\", "/").strip("/.")

        with self._sync_lock:
            if not local_file.exists():
                # File or directory was deleted locally
                if self.state_db.is_tracked(clean_rel):
                    self.set_status(t("status_deleting_remote", file=clean_rel), "syncing")
                    remote_file_path = f"{self.active_remote_path}/{clean_rel}"
                    ok = self.client.delete_resource(remote_file_path)
                    if ok:
                        self.state_db.delete_record_and_children(clean_rel)
                        self.state_db.log_sync(clean_rel, "delete", "local->remote", "success")
                        print(f"[SyncEngine] Deleted remotely: {clean_rel}")
                    else:
                        self.state_db.log_sync(clean_rel, "delete", "local->remote", "error", "Remote delete failed")

                    # Mirror delete to secondary server if dual sync enabled
                    if self.config.backup_server_enabled and self.config.sync_backup_server:
                        sec = self._get_secondary_client()
                        if sec:
                            sec_client, sec_rem = sec
                            try:
                                sec_client.delete_resource(f"{sec_rem}/{clean_rel}")
                            except Exception:
                                pass

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
            remote_dest = f"{self.active_remote_path}/{clean_rel}"
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

                # Mirror upload to secondary server if dual sync enabled
                if self.config.backup_server_enabled and self.config.sync_backup_server:
                    sec = self._get_secondary_client()
                    if sec:
                        sec_client, sec_rem = sec
                        try:
                            sec_client.upload_file(local_file, f"{sec_rem}/{clean_rel}")
                        except Exception as e:
                            print(f"[SyncEngine] Mirror upload error: {e}")

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

        # Ensure active server settings are configured on client
        url, user, pwd, _ = self.get_server_credentials(self.active_server_index)
        if not url or not user:
            if self.active_server_index != self.config.primary_server_index:
                self.apply_server_connection(self.config.primary_server_index)
                url, user, pwd, _ = self.get_server_credentials(self.active_server_index)
            if not url or not user:
                self.set_status(t("status_need_config"), "paused")
                return

        with self._sync_lock:
            # 0. Check if primary server has recovered if we are currently running on backup server
            if self.config.backup_server_enabled and self.active_server_index != self.config.primary_server_index:
                now = time.time()
                if now - self._last_primary_probe_time >= 60.0:
                    self._last_primary_probe_time = now
                    prim_idx = self.config.primary_server_index
                    p_url, p_user, p_pwd, _ = self.get_server_credentials(prim_idx)
                    if p_url and p_user:
                        probe_client = FileBrowserClient(base_url=p_url, username=p_user, password=p_pwd, timeout=6)
                        p_ok, _ = probe_client.test_connection()
                        if p_ok:
                            print(f"[SyncEngine] Primary server {prim_idx} recovered! Switching back.")
                            self.apply_server_connection(prim_idx)
                            self.notify(
                                t("notify_failback_title"),
                                t("notify_failback_msg", idx=prim_idx),
                            )

            self.set_status(t("status_checking"), "syncing")

            # 1. Test / ensure connection
            ok, msg = self.client.test_connection()
            if not ok:
                # If active server failed, try backup server failover!
                if self.config.backup_server_enabled:
                    alt_idx = 2 if self.active_server_index == 1 else 1
                    alt_url, alt_user, alt_pwd, _ = self.get_server_credentials(alt_idx)
                    if alt_url and alt_user:
                        alt_client = FileBrowserClient(base_url=alt_url, username=alt_user, password=alt_pwd, timeout=8)
                        alt_ok, alt_msg = alt_client.test_connection()
                        if alt_ok:
                            old_idx = self.active_server_index
                            print(f"[SyncEngine] Server {old_idx} unreachable ({msg}). Failover switching to Server {alt_idx}...")
                            self.apply_server_connection(alt_idx)
                            self.notify(
                                t("notify_failover_title"),
                                t("notify_failover_msg", from_idx=old_idx, to_idx=alt_idx),
                            )
                            ok = True

                if not ok:
                    self.set_status(t("status_conn_error", msg=msg[:40]), "error")
                    return

            active_remote = self.active_remote_path

            # Ensure remote root exists
            self.client.ensure_remote_dir_exists(active_remote)

            # 2. Fetch remote tree
            remote_items = self.client.list_recursive(active_remote)
            remote_files: Dict[str, RemoteItem] = {}
            remote_dirs: Dict[str, RemoteItem] = {}

            root_prefix = active_remote.strip("/")

            for item in remote_items:
                clean_p = item.path.strip("/")
                if clean_p.lower().startswith(root_prefix.lower()):
                    rel = clean_p[len(root_prefix):].strip("/.")
                else:
                    rel = clean_p.strip("/.")
                if not rel or self.is_ignored(rel):
                    continue

                if item.is_dir:
                    remote_dirs[rel] = item
                else:
                    remote_files[rel] = item

            # 3. Scan local filesystem
            local_dirs: Set[str] = set()
            local_files: Dict[str, Path] = {}
            if self.config.local_path.exists():
                for root, dirs, files in os.walk(self.config.local_path):
                    # Filter ignored directories in-place so os.walk does not descend into them
                    dirs[:] = [d for d in dirs if not self.is_ignored(Path(root) / d)]
                    for d in dirs:
                        full_d = Path(root) / d
                        rel_d = str(full_d.relative_to(self.config.local_path)).replace("\\", "/").strip("/.")
                        if rel_d:
                            local_dirs.add(rel_d)
                    for file in files:
                        full_path = Path(root) / file
                        if self.is_ignored(full_path):
                            continue
                        rel = str(full_path.relative_to(self.config.local_path)).replace("\\", "/").strip("/.")
                        if rel:
                            local_files[rel] = full_path

            # 4. Load state records
            state_records = self.state_db.get_all_records()
            state_dirs = {r.rel_path: r for r in state_records.values() if r.is_dir}
            state_files = {r.rel_path: r for r in state_records.values() if not r.is_dir}

            # -----------------------------------------------------------------
            # PHASE 1: Reconcile Directories (Bidirectional)
            # -----------------------------------------------------------------
            deleted_dir_prefixes: Set[str] = set()
            all_dir_paths = sorted(
                set(remote_dirs.keys()) | local_dirs | set(state_dirs.keys()),
                key=lambda p: (len(p.split("/")), p)
            )

            for d in all_dir_paths:
                if self._paused or not self._running:
                    break

                # If parent directory was already deleted, skip child
                if any(d == p or d.startswith(p + "/") for p in deleted_dir_prefixes):
                    continue

                in_remote = d in remote_dirs
                in_local = d in local_dirs
                in_state = d in state_dirs or self.state_db.is_tracked(d)

                # Case D1: Directory on remote, but NOT on local disk
                if in_remote and not in_local:
                    if in_state:
                        # User deleted directory locally -> delete on remote
                        self.set_status(t("status_deleting_remote", file=d), "syncing")
                        remote_dir_path = f"{active_remote}/{d}"
                        ok = self.client.delete_resource(remote_dir_path)

                        if ok:
                            self.state_db.delete_record_and_children(d)
                            self.state_db.log_sync(d, "delete", "local->remote", "success", "Directory deleted locally")
                            deleted_dir_prefixes.add(d)
                            print(f"[SyncEngine] Deleted remote directory (deleted locally): {d}")
                        else:
                            self.state_db.log_sync(d, "delete", "local->remote", "error", "Remote directory delete failed")
                    else:
                        # New directory from another computer -> create locally
                        local_target_dir = self.config.local_path / d
                        local_target_dir.mkdir(parents=True, exist_ok=True)
                        rec = FileRecord(rel_path=d, is_dir=True, last_sync_time=time.time())
                        self.state_db.upsert_record(rec)
                        self.state_db.log_sync(d, "create_dir", "remote->local", "success")
                        print(f"[SyncEngine] Created local directory: {d}")

                # Case D2: Directory on local, but NOT on remote
                elif in_local and not in_remote:
                    if in_state:
                        # Directory was deleted remotely on the server!
                        local_dir_path = self.config.local_path / d
                        # Check if local folder contains any untracked (new) files
                        has_untracked_files = any(
                            (rel == d or rel.startswith(d + "/")) and rel not in state_records
                            for rel in local_files.keys()
                        )
                        if not has_untracked_files:
                            # Safe to delete local directory
                            self.set_status(t("status_deleting_local", file=d), "syncing")
                            self._suppress(d, duration=5.0)
                            try:
                                shutil.rmtree(str(local_dir_path), ignore_errors=True)
                                self.state_db.delete_record_and_children(d)
                                self.state_db.log_sync(d, "delete", "remote->local", "success", "Directory deleted remotely")
                                deleted_dir_prefixes.add(d)
                                print(f"[SyncEngine] Deleted local directory (deleted remotely): {d}")
                            except Exception as e:
                                print(f"[SyncEngine] Error removing local directory {d}: {e}")
                        else:
                            # Keep untracked files and re-upload directory to server
                            remote_dir_path = f"{active_remote}/{d}"
                            self.client.create_directory(remote_dir_path)
                            rec = FileRecord(rel_path=d, is_dir=True, last_sync_time=time.time())
                            self.state_db.upsert_record(rec)
                    else:
                        # New directory created locally -> create on remote
                        remote_dir_path = f"{active_remote}/{d}"
                        self.client.create_directory(remote_dir_path)

                        rec = FileRecord(rel_path=d, is_dir=True, last_sync_time=time.time())
                        self.state_db.upsert_record(rec)
                        self.state_db.log_sync(d, "create_dir", "local->remote", "success")
                        print(f"[SyncEngine] Created remote directory: {d}")

                # Case D3: Directory on both local and remote
                elif in_local and in_remote:
                    if d not in state_dirs:
                        rec = FileRecord(rel_path=d, is_dir=True, last_sync_time=time.time())
                        self.state_db.upsert_record(rec)

                # Case D4: Tracked in state_db but exists neither locally nor remotely
                elif in_state:
                    self.state_db.delete_record(d)

            # -----------------------------------------------------------------
            # PHASE 2: Reconcile Files
            # -----------------------------------------------------------------
            # Refresh state records after directory phase
            state_records = self.state_db.get_all_records()
            state_files = {r.rel_path: r for r in state_records.values() if not r.is_dir}

            all_rel_paths = (
                set(remote_files.keys()) | set(local_files.keys()) | set(state_files.keys())
            )

            downloads_count = 0
            uploads_count = 0

            for rel in all_rel_paths:
                if self._paused or not self._running:
                    break

                # If the file belongs to a directory that was deleted in Phase 1, skip it!
                if any(rel == p or rel.startswith(p + "/") for p in deleted_dir_prefixes):
                    continue

                in_remote = rel in remote_files
                in_local = rel in local_files
                in_state = rel in state_files

                # Case A: File exists both locally and remotely
                if in_remote and in_local:
                    r_item = remote_files[rel]
                    l_file = local_files[rel]
                    rec = state_files.get(rel)

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
                    rec = state_files.get(rel)
                    r_item = remote_files[rel]

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
                    rec = state_files.get(rel)
                    l_file = local_files[rel]

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
                        remote_dest = f"{active_remote}/{rel}"
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

            # If dual server sync (backup server mirroring) is enabled, coordinate via Leader Lock!
            if self.config.backup_server_enabled and self.config.sync_backup_server:
                is_leader, leader_info = self.acquire_or_renew_sync_leader()
                if is_leader:
                    self.sync_servers_mirror()
                else:
                    host = leader_info.get("hostname", "other PC")
                    print(f"[SyncEngine] Dual sync: coordinator is '{host}'. Running as follower (monitoring only).")
                    threading.Thread(target=self.compare_servers_status, daemon=True).start()
            elif self.config.backup_server_enabled:
                threading.Thread(target=self.compare_servers_status, daemon=True).start()

            self.set_status(t("status_synced"), "idle")

    def pull_missing_files(self) -> Tuple[int, int]:
        """
        Forces downloading of all files from remote FileBrowser that are missing locally.
        Clears stale state DB records for missing files to prevent accidental deletion,
        ensures remote folders are created locally, and downloads missing items.
        Returns (downloaded_count, error_count).
        """
        if not self.config.server_url or not self.config.username:
            return 0, 0

        downloaded = 0
        errors = 0

        with self._sync_lock:
            self.set_status(t("status_checking"), "syncing")
            ok, msg = self.client.test_connection()
            if not ok:
                self.set_status(t("status_conn_error", msg=msg[:40]), "error")
                return 0, 1

            active_remote = self.active_remote_path
            self.client.ensure_remote_dir_exists(active_remote)
            remote_items = self.client.list_recursive(active_remote)
            root_prefix = active_remote.strip("/")


            # 1. First pass: ensure all directories exist locally and track them
            for item in remote_items:
                clean_p = item.path.strip("/")
                if clean_p.lower().startswith(root_prefix.lower()):
                    rel = clean_p[len(root_prefix):].strip("/.")
                else:
                    rel = clean_p.strip("/.")
                if not rel or self.is_ignored(rel):
                    continue

                if item.is_dir:
                    (self.config.local_path / rel).mkdir(parents=True, exist_ok=True)
                    rec = FileRecord(rel_path=rel, is_dir=True, last_sync_time=time.time())
                    self.state_db.upsert_record(rec)

            # 2. Second pass: download missing files or files needing update
            for item in remote_items:
                if item.is_dir:
                    continue

                clean_p = item.path.strip("/")
                if clean_p.lower().startswith(root_prefix.lower()):
                    rel = clean_p[len(root_prefix):].lstrip("/")
                else:
                    rel = clean_p
                if not rel or self.is_ignored(rel):
                    continue

                local_target = self.config.local_path / rel
                need_download = False

                if not local_target.exists():
                    # File is missing locally! Clear any old state record so it's not marked as deleted
                    self.state_db.delete_record(rel)
                    need_download = True
                else:
                    # Local file exists: check if size or hash differs from remote
                    rec = self.state_db.get_record(rel)
                    if rec:
                        if rec.remote_mtime != item.modified or rec.remote_size != item.size:
                            need_download = True
                    else:
                        stat = local_target.stat()
                        if stat.st_size != item.size:
                            need_download = True

                if need_download:
                    local_target.parent.mkdir(parents=True, exist_ok=True)
                    success = self._download_remote_file(rel, item, local_target)
                    if success:
                        downloaded += 1
                    else:
                        errors += 1

            self.set_status(t("status_synced"), "idle")
            if downloaded > 0:
                self.notify(
                    t("notify_pull_done_title"),
                    t("notify_pull_done_msg", count=downloaded),
                )

        return downloaded, errors

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

            # Mirror upload to secondary server if dual sync enabled
            if self.config.backup_server_enabled and self.config.sync_backup_server:
                sec = self._get_secondary_client()
                if sec:
                    sec_client, sec_rem = sec
                    try:
                        sec_client.upload_file(local_file, f"{sec_rem}/{rel}")
                    except Exception as e:
                        print(f"[SyncEngine] Mirror upload error: {e}")

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
            share_url = f"{self.client.base_url}/files{remote_dest}"

        self.last_uploaded_item = {
            "name": local_file.name,
            "rel_path": rel_path,
            "remote_path": remote_dest,
            "share_url": share_url or f"{self.client.base_url}/files{remote_dest}",
        }
        self._notify_share_ready(self.last_uploaded_item, notify=True)

    def _init_last_uploaded_from_history(self) -> None:
        """Restores last_uploaded_item from the most recent upload in sync_history."""
        self._history_loaded = True
        base_url = self.client.base_url or self.config.server_url
        if not base_url:
            return
        if not self.client.username and self.config.username:
            self.client.username = self.config.username
        if not self.client.password and self.config.password:
            self.client.password = self.config.password

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
                    remote_dest = f"{self.active_remote_path}/{clean_rel}"
                    share_url = self.client.get_or_create_share_link(remote_dest)
                    self.last_uploaded_item = {
                        "name": name,
                        "rel_path": clean_rel,
                        "remote_path": remote_dest,
                        "share_url": share_url or f"{base_url}/files{remote_dest}",
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

        temp_conflict_name = f".df_conflict_{os.getpid()}_{local_file.name}.tmp"
        temp_conflict = local_file.parent / temp_conflict_name
        parent_rel = Path(rel).parent
        if str(parent_rel) in (".", "/"):
            clean_temp_rel = temp_conflict_name
        else:
            clean_temp_rel = f"{str(parent_rel).replace(chr(92), '/').strip('/')}/{temp_conflict_name}"
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
                            if self.client.base_url and self.client.username:
                                remote_dest = f"{self.active_remote_path}/{rel_dup}"
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
        if event.is_directory:
            self.engine.on_local_directory_event(event.src_path, "created")
        else:
            self.engine.on_local_event(event.src_path, "created")

    def on_modified(self, event):
        if not event.is_directory:
            self.engine.on_local_event(event.src_path, "modified")

    def on_deleted(self, event):
        if event.is_directory:
            self.engine.on_local_directory_event(event.src_path, "deleted")
        else:
            self.engine.on_local_event(event.src_path, "deleted")

    def on_moved(self, event):
        if event.is_directory:
            self.engine.on_local_directory_event(event.src_path, "deleted")
            self.engine.on_local_directory_event(event.dest_path, "created")
        else:
            self.engine.on_local_event(event.src_path, "deleted")
            self.engine.on_local_event(event.dest_path, "created")
