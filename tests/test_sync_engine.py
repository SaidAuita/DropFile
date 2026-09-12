"""
Unit tests for SyncEngine helpers, suppression, and ignore patterns.
"""

import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config
from fb_client import FileBrowserClient
from state_db import StateDatabase
from sync_engine import SyncEngine


class TestSyncEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.config = Config(self.temp_dir)
        self.db = StateDatabase(self.temp_dir / "state.db")
        self.client = FileBrowserClient("https://mock.local")
        self.engine = SyncEngine(self.config, self.db, self.client)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ignore_patterns(self):
        self.assertTrue(self.engine.is_ignored("~$document.docx"))
        self.assertTrue(self.engine.is_ignored("cache.tmp"))
        self.assertTrue(self.engine.is_ignored("desktop.ini"))
        self.assertTrue(self.engine.is_ignored("Thumbs.db"))
        self.assertTrue(self.engine.is_ignored(".dropfile_meta"))

        self.assertFalse(self.engine.is_ignored("photo.jpg"))
        self.assertFalse(self.engine.is_ignored("report.pdf"))
        self.assertFalse(self.engine.is_ignored("archive.zip"))

    def test_suppression(self):
        self.engine._suppress("folder/test.txt", duration=1.0)
        self.assertTrue(self.engine._is_suppressed("folder/test.txt"))
        self.assertTrue(self.engine._is_suppressed(r"folder\test.txt"))
        self.assertFalse(self.engine._is_suppressed("folder/other.txt"))

    def test_config_export_and_import(self):
        backup_file = self.temp_dir / "backup.json"
        self.config.server_url = "https://backup-server.local"
        self.config.username = "backup_user"
        ok_export = self.config.export_config(backup_file)
        self.assertTrue(ok_export)
        self.assertTrue(backup_file.exists())

        # Change in-memory
        self.config.server_url = "https://other.local"
        self.config.username = "other_user"

        # Import from backup
        ok_import = self.config.import_config(backup_file)
        self.assertTrue(ok_import)
        self.assertEqual(self.config.server_url, "https://backup-server.local")
        self.assertEqual(self.config.username, "backup_user")

    def test_record_uploaded_item(self):
        test_file = self.temp_dir / "share_test.txt"
        test_file.write_text("hello", encoding="utf-8")
        self.engine._record_uploaded_item(test_file, "share_test.txt", "/DropFile/share_test.txt")
        self.assertIsNotNone(self.engine.last_uploaded_item)
        self.assertEqual(self.engine.last_uploaded_item["name"], "share_test.txt")
        self.assertTrue("share" in self.engine.last_uploaded_item["share_url"] or "files" in self.engine.last_uploaded_item["share_url"])

    def test_get_last_uploaded_item_from_history(self):
        self.config.server_url = "https://mock.local"
        self.config.username = "mock_user"
        self.db.log_sync("archive_test.zip", "upload", "local->remote", "success")
        self.engine.last_uploaded_item = None
        self.engine._history_loaded = False

        item = self.engine.get_last_uploaded_item()
        self.assertIsNotNone(item)
        self.assertEqual(item["name"], "archive_test.zip")
        self.assertEqual(item["rel_path"], "archive_test.zip")


    def test_cleanup_old_files(self):
        import time
        from state_db import FileRecord

        old_file = self.temp_dir / "old_doc.pdf"
        old_file.write_text("old content", encoding="utf-8")

        new_file = self.temp_dir / "new_doc.pdf"
        new_file.write_text("new content", encoding="utf-8")

        old_time = time.time() - (35 * 86400)
        rec_old = FileRecord(rel_path="old_doc.pdf", last_sync_time=old_time, local_size=10)
        self.db.upsert_record(rec_old)

        rec_new = FileRecord(rel_path="new_doc.pdf", last_sync_time=time.time(), local_size=10)
        self.db.upsert_record(rec_new)

        self.config.local_path = self.temp_dir
        self.engine._running = True

        cleaned = self.engine.cleanup_old_files(retention_days=30)
        self.assertEqual(cleaned, 1)

        self.assertFalse(old_file.exists())
        self.assertIsNone(self.db.get_record("old_doc.pdf"))

        self.assertTrue(new_file.exists())
        self.assertIsNotNone(self.db.get_record("new_doc.pdf"))


if __name__ == "__main__":
    unittest.main()
