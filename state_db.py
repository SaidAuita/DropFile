"""
State database for DropFile.
Tracks file metadata (mtime, size, hash) to enable accurate bidirectional synchronization,
change detection, and conflict prevention.
"""

import hashlib
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def compute_file_hash(filepath: Path | str, chunk_size: int = 65536) -> str:
    """Computes SHA-256 hash of a file."""
    p = Path(filepath)
    if not p.is_file():
        return ""
    hasher = hashlib.sha256()
    try:
        with open(p, "rb") as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return ""


class FileRecord:
    def __init__(
        self,
        rel_path: str,
        local_mtime: float = 0.0,
        local_size: int = 0,
        remote_mtime: str = "",
        remote_size: int = 0,
        content_hash: str = "",
        is_dir: bool = False,
        last_sync_time: float = 0.0,
    ):
        # Normalize relative path to forward slashes without leading slash
        self.rel_path = rel_path.replace("\\", "/").lstrip("/")
        self.local_mtime = float(local_mtime)
        self.local_size = int(local_size)
        self.remote_mtime = str(remote_mtime)
        self.remote_size = int(remote_size)
        self.content_hash = content_hash
        self.is_dir = bool(is_dir)
        self.last_sync_time = float(last_sync_time)

    def to_tuple(self) -> Tuple:
        return (
            self.rel_path,
            self.local_mtime,
            self.local_size,
            self.remote_mtime,
            self.remote_size,
            self.content_hash,
            1 if self.is_dir else 0,
            self.last_sync_time,
        )


class StateDatabase:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS file_states (
                    rel_path TEXT PRIMARY KEY,
                    local_mtime REAL,
                    local_size INTEGER,
                    remote_mtime TEXT,
                    remote_size INTEGER,
                    content_hash TEXT,
                    is_dir INTEGER,
                    last_sync_time REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rel_path TEXT,
                    action TEXT,
                    direction TEXT,
                    status TEXT,
                    message TEXT,
                    timestamp REAL
                )
                """
            )
            conn.commit()

    def get_record(self, rel_path: str) -> Optional[FileRecord]:
        clean_path = rel_path.replace("\\", "/").lstrip("/")
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM file_states WHERE rel_path = ?", (clean_path,)
            )
            row = cursor.fetchone()
            if row:
                return FileRecord(
                    rel_path=row["rel_path"],
                    local_mtime=row["local_mtime"],
                    local_size=row["local_size"],
                    remote_mtime=row["remote_mtime"],
                    remote_size=row["remote_size"],
                    content_hash=row["content_hash"],
                    is_dir=bool(row["is_dir"]),
                    last_sync_time=row["last_sync_time"],
                )
            return None

    def get_all_records(self) -> Dict[str, FileRecord]:
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM file_states")
            records = {}
            for row in cursor.fetchall():
                records[row["rel_path"]] = FileRecord(
                    rel_path=row["rel_path"],
                    local_mtime=row["local_mtime"],
                    local_size=row["local_size"],
                    remote_mtime=row["remote_mtime"],
                    remote_size=row["remote_size"],
                    content_hash=row["content_hash"],
                    is_dir=bool(row["is_dir"]),
                    last_sync_time=row["last_sync_time"],
                )
            return records

    def upsert_record(self, record: FileRecord) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO file_states (
                    rel_path, local_mtime, local_size, remote_mtime,
                    remote_size, content_hash, is_dir, last_sync_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(rel_path) DO UPDATE SET
                    local_mtime = excluded.local_mtime,
                    local_size = excluded.local_size,
                    remote_mtime = excluded.remote_mtime,
                    remote_size = excluded.remote_size,
                    content_hash = excluded.content_hash,
                    is_dir = excluded.is_dir,
                    last_sync_time = excluded.last_sync_time
                """,
                record.to_tuple(),
            )
            conn.commit()

    def delete_record(self, rel_path: str) -> None:
        clean_path = rel_path.replace("\\", "/").strip("/.")
        with self._lock, self._get_connection() as conn:
            conn.execute("DELETE FROM file_states WHERE rel_path = ?", (clean_path,))
            conn.commit()

    def delete_record_and_children(self, rel_path: str) -> int:
        """Deletes record for rel_path and any child records whose path starts with rel_path + '/'."""
        clean_path = rel_path.replace("\\", "/").strip("/.")
        if not clean_path:
            return 0
        prefix = clean_path + "/%"
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM file_states WHERE rel_path = ? OR rel_path LIKE ?",
                (clean_path, prefix),
            )
            conn.commit()
            return cur.rowcount

    def is_tracked(self, rel_path: str) -> bool:
        """Returns True if rel_path itself or any child records exist in file_states."""
        clean_path = rel_path.replace("\\", "/").strip("/.")
        if not clean_path:
            return False
        prefix = clean_path + "/%"
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                "SELECT 1 FROM file_states WHERE rel_path = ? OR rel_path LIKE ? LIMIT 1",
                (clean_path, prefix),
            )
            return cur.fetchone() is not None

    def log_sync(
        self,
        rel_path: str,
        action: str,
        direction: str,
        status: str,
        message: str = "",
        timestamp: float = 0.0,
    ) -> None:
        import time

        ts = timestamp or time.time()
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO sync_history (rel_path, action, direction, status, message, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (rel_path, action, direction, status, message, ts),
            )
            # Keep only last 1000 history entries
            conn.execute(
                """
                DELETE FROM sync_history WHERE id NOT IN (
                    SELECT id FROM sync_history ORDER BY id DESC LIMIT 1000
                )
                """
            )
            conn.commit()

    def get_recent_history(self, limit: int = 50) -> List[dict]:
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM sync_history ORDER BY id DESC LIMIT ?", (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def clear_history(self) -> None:
        """Clears all entries from the sync history table."""
        with self._lock, self._get_connection() as conn:
            conn.execute("DELETE FROM sync_history")
            conn.commit()

    def cleanup_old_history(self, retention_days: int = 30) -> int:
        """Deletes sync history older than retention_days. If retention_days <= 0, preserves all."""
        if retention_days <= 0:
            return 0
        cutoff = time.time() - (retention_days * 86400)
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("DELETE FROM sync_history WHERE timestamp < ?", (cutoff,))
            conn.commit()
            return cur.rowcount

    def clear_all(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute("DELETE FROM file_states")
            conn.execute("DELETE FROM sync_history")
            conn.commit()
