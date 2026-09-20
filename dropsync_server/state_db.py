"""
SQLite-backed local state database for DropSync Server.
Tracks file index, content hashes, modification times, and deletion tombstones.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class StateDatabase:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextlib.contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    rel_path TEXT PRIMARY KEY,
                    size INTEGER NOT NULL,
                    mtime REAL NOT NULL,
                    hash TEXT NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    action TEXT NOT NULL,
                    rel_path TEXT NOT NULL,
                    size INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    details TEXT DEFAULT ''
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_files_deleted ON files(deleted);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_log_time ON sync_log(timestamp DESC);")
            conn.commit()

    @staticmethod
    def calculate_file_hash(path: Path, chunk_size: int = 65536) -> str:
        """Calculates fast SHA-256 hash in streaming 64KB chunks."""
        hasher = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                while chunk := f.read(chunk_size):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception:
            return ""

    def get_file(self, rel_path: str) -> Optional[Dict[str, Any]]:
        norm_path = rel_path.replace("\\", "/").strip("/")
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT rel_path, size, mtime, hash, deleted, updated_at FROM files WHERE rel_path = ?",
                (norm_path,),
            )
            row = cur.fetchone()
            if row:
                return dict(row)
        return None

    def upsert_file(
        self,
        rel_path: str,
        size: int,
        mtime: float,
        file_hash: str,
        deleted: int = 0,
    ) -> None:
        norm_path = rel_path.replace("\\", "/").strip("/")
        now = time.time()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO files (rel_path, size, mtime, hash, deleted, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(rel_path) DO UPDATE SET
                    size = excluded.size,
                    mtime = excluded.mtime,
                    hash = excluded.hash,
                    deleted = excluded.deleted,
                    updated_at = excluded.updated_at
                """,
                (norm_path, size, mtime, file_hash, deleted, now),
            )
            conn.commit()

    def mark_deleted(self, rel_path: str) -> None:
        norm_path = rel_path.replace("\\", "/").strip("/")
        now = time.time()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE files SET deleted = 1, updated_at = ? WHERE rel_path = ?
                """,
                (now, norm_path),
            )
            conn.commit()

    def has_active_files_in_dir(self, rel_dir: str) -> bool:
        """Returns True if any non-deleted files exist under rel_dir."""
        norm_dir = rel_dir.replace("\\", "/").strip("/")
        pattern = f"{norm_dir}/%" if norm_dir else "%"
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM files WHERE (rel_path = ? OR rel_path LIKE ?) AND deleted = 0 LIMIT 1",
                (norm_dir, pattern),
            )
            return cur.fetchone() is not None

    def has_deleted_files_in_dir(self, rel_dir: str) -> bool:
        """Returns True if any deleted tombstones exist under rel_dir."""
        norm_dir = rel_dir.replace("\\", "/").strip("/")
        pattern = f"{norm_dir}/%" if norm_dir else "%"
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM files WHERE (rel_path = ? OR rel_path LIKE ?) AND deleted = 1 LIMIT 1",
                (norm_dir, pattern),
            )
            return cur.fetchone() is not None

    def has_tracked_files_in_dir(self, rel_dir: str) -> bool:
        """Returns True if any files (active or deleted) were ever tracked in rel_dir."""
        norm_dir = rel_dir.replace("\\", "/").strip("/")
        pattern = f"{norm_dir}/%" if norm_dir else "%"
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM files WHERE rel_path = ? OR rel_path LIKE ? LIMIT 1",
                (norm_dir, pattern),
            )
            return cur.fetchone() is not None

    def mark_dir_deleted(self, rel_dir: str) -> List[str]:
        """Marks all active files under rel_dir as deleted, returning their relative paths."""
        norm_dir = rel_dir.replace("\\", "/").strip("/")
        pattern = f"{norm_dir}/%" if norm_dir else "%"
        now = time.time()
        affected: List[str] = []
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT rel_path FROM files WHERE (rel_path = ? OR rel_path LIKE ?) AND deleted = 0",
                (norm_dir, pattern),
            )
            affected = [row["rel_path"] for row in cur.fetchall()]
            if affected:
                conn.execute(
                    "UPDATE files SET deleted = 1, updated_at = ? WHERE (rel_path = ? OR rel_path LIKE ?) AND deleted = 0",
                    (now, norm_dir, pattern),
                )
                conn.commit()
        return affected

    def get_manifest(self) -> Dict[str, Dict[str, Any]]:
        """Returns the full dictionary of active and deleted files with their hashes."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT rel_path, size, mtime, hash, deleted, updated_at FROM files")
            manifest = {}
            for row in cur.fetchall():
                manifest[row["rel_path"]] = {
                    "size": row["size"],
                    "mtime": row["mtime"],
                    "hash": row["hash"],
                    "deleted": bool(row["deleted"]),
                    "updated_at": row["updated_at"],
                }
            return manifest

    def log_sync(
        self,
        action: str,
        rel_path: str,
        status: str = "SUCCESS",
        size: int = 0,
        details: str = "",
    ) -> None:
        norm_path = rel_path.replace("\\", "/").strip("/")
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO sync_log (timestamp, action, rel_path, size, status, details)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (time.time(), action, norm_path, size, status, details),
            )
            conn.commit()

    def get_recent_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, timestamp, action, rel_path, size, status, details
                FROM sync_log
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]
