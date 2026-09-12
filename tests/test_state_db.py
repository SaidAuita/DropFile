"""
Unit tests for DropFile State Database.
"""

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from state_db import FileRecord, StateDatabase, compute_file_hash


class TestStateDB(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.db_path = self.test_dir / "test_state.db"
        self.db = StateDatabase(self.db_path)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_upsert_and_get_record(self):
        rec = FileRecord(
            rel_path="documents/report.pdf",
            local_mtime=1700000000.0,
            local_size=1024,
            remote_mtime="2026-09-12T10:00:00Z",
            remote_size=1024,
            content_hash="abcdef123456",
            is_dir=False,
            last_sync_time=time.time(),
        )
        self.db.upsert_record(rec)

        fetched = self.db.get_record("documents/report.pdf")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.rel_path, "documents/report.pdf")
        self.assertEqual(fetched.local_size, 1024)
        self.assertEqual(fetched.content_hash, "abcdef123456")

        # Test Windows backslash normalization
        fetched_win = self.db.get_record(r"documents\report.pdf")
        self.assertIsNotNone(fetched_win)
        self.assertEqual(fetched_win.rel_path, "documents/report.pdf")

    def test_delete_record(self):
        rec = FileRecord(rel_path="to_delete.txt", local_size=50)
        self.db.upsert_record(rec)
        self.assertIsNotNone(self.db.get_record("to_delete.txt"))

        self.db.delete_record("to_delete.txt")
        self.assertIsNone(self.db.get_record("to_delete.txt"))

    def test_history_logging(self):
        self.db.log_sync("file1.txt", "upload", "local->remote", "success")
        self.db.log_sync("file2.txt", "download", "remote->local", "error", "Failed timeout")

        history = self.db.get_recent_history(limit=10)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["rel_path"], "file2.txt")
        self.assertEqual(history[1]["rel_path"], "file1.txt")

    def test_clear_and_cleanup_history(self):
        self.db.log_sync("file1.txt", "upload", "local->remote", "success")
        self.db.log_sync("file2.txt", "download", "remote->local", "success")
        self.assertEqual(len(self.db.get_recent_history()), 2)

        # Manually backdate one entry in sqlite to test cleanup_old_history
        old_time = time.time() - (35 * 86400)
        with self.db._get_connection() as conn:
            conn.execute("UPDATE sync_history SET timestamp = ? WHERE rel_path = 'file1.txt'", (old_time,))
            conn.commit()

        # Retention 30 days should delete file1.txt (35 days old) and keep file2.txt
        deleted = self.db.cleanup_old_history(retention_days=30)
        self.assertEqual(deleted, 1)
        history = self.db.get_recent_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["rel_path"], "file2.txt")

        # Clear history should delete all remaining
        self.db.clear_history()
        self.assertEqual(len(self.db.get_recent_history()), 0)

    def test_compute_file_hash(self):
        sample_file = self.test_dir / "sample.txt"
        sample_file.write_text("Hello DropFile World!", encoding="utf-8")

        h1 = compute_file_hash(sample_file)
        self.assertTrue(len(h1) == 64)

        sample_file.write_text("Hello DropFile World! Modified", encoding="utf-8")
        h2 = compute_file_hash(sample_file)
        self.assertNotEqual(h1, h2)


if __name__ == "__main__":
    unittest.main()
