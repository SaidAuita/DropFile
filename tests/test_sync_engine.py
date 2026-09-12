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

    def test_handle_conflict_identical_hash_no_copy(self):
        from fb_client import RemoteItem
        from state_db import compute_file_hash

        sync_folder = self.temp_dir / "sync_identical"
        sync_folder.mkdir()
        self.config.local_path = sync_folder

        local_file = sync_folder / "report.pdf"
        local_file.write_bytes(b"Exact same content on local and remote")

        r_item = RemoteItem(
            path="/DropFile/report.pdf",
            name="report.pdf",
            size=len(b"Exact same content on local and remote"),
            modified="2026-09-12T10:00:00Z",
            is_dir=False,
        )

        # Mock download_file to simulate remote returning identical content
        def mock_download(remote_path, target_dest):
            Path(target_dest).write_bytes(b"Exact same content on local and remote")
            return True

        self.client.download_file = mock_download

        res = self.engine._handle_conflict("report.pdf", local_file, r_item)
        self.assertEqual(res, "identical")

        # Verify NO conflict copies were created in directory
        all_files = list(sync_folder.glob("*"))
        self.assertEqual(len(all_files), 1)
        self.assertEqual(all_files[0].name, "report.pdf")

        # Verify state_db was updated
        rec = self.db.get_record("report.pdf")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.content_hash, compute_file_hash(local_file))

    def test_handle_conflict_different_hash_creates_copy(self):
        from fb_client import RemoteItem

        sync_folder = self.temp_dir / "sync_diff"
        sync_folder.mkdir()
        self.config.local_path = sync_folder
        self.config.conflict_action = "keep_both"

        local_file = sync_folder / "report.pdf"
        local_file.write_bytes(b"Local unique edits by user A")

        r_item = RemoteItem(
            path="/DropFile/report.pdf",
            name="report.pdf",
            size=len(b"Remote unique edits by user B"),
            modified="2026-09-12T10:00:00Z",
            is_dir=False,
        )

        # Mock download_file to simulate remote returning different content
        def mock_download(remote_path, target_dest):
            Path(target_dest).write_bytes(b"Remote unique edits by user B")
            return True

        self.client.download_file = mock_download

        res = self.engine._handle_conflict("report.pdf", local_file, r_item)
        self.assertEqual(res, "conflict")

        # Verify conflict copy was created
        all_names = [f.name for f in sync_folder.glob("*")]
        self.assertTrue(any("Conflict" in name for name in all_names))
        # Primary file now has remote content
        self.assertEqual(local_file.read_bytes(), b"Remote unique edits by user B")

    def test_handle_conflict_newer_wins(self):
        import time
        from fb_client import RemoteItem

        sync_folder = self.temp_dir / "sync_newer"
        sync_folder.mkdir()
        self.config.local_path = sync_folder
        self.config.conflict_action = "newer_wins"

        local_file = sync_folder / "notes.txt"
        local_file.write_bytes(b"Old local content")

        # Remote is timestamped in the future (newer)
        r_item = RemoteItem(
            path="/DropFile/notes.txt",
            name="notes.txt",
            size=len(b"Newer remote content"),
            modified="2030-01-01T00:00:00Z",
            is_dir=False,
        )

        def mock_download(remote_path, target_dest):
            Path(target_dest).write_bytes(b"Newer remote content")
            return True

        self.client.download_file = mock_download

        res = self.engine._handle_conflict("notes.txt", local_file, r_item)
        self.assertEqual(res, "downloaded")

        # No conflict copies
        all_names = [f.name for f in sync_folder.glob("*")]
        self.assertEqual(len(all_names), 1)
        self.assertEqual(local_file.read_bytes(), b"Newer remote content")

    def test_deduplicate_conflict_copies(self):
        sync_folder = self.temp_dir / "sync_dedup"
        sync_folder.mkdir()
        self.config.local_path = sync_folder

        base_file = sync_folder / "presentation.pptx"
        base_file.write_bytes(b"Presentation slide content 1234567890")

        # Create duplicate conflict copy with same hash
        dup_file1 = sync_folder / "presentation (Conflict PC 2026-09-12_10-00-00).pptx"
        dup_file1.write_bytes(b"Presentation slide content 1234567890")

        dup_file2 = sync_folder / "presentation (Conflict Redmi 2026-09-12_11-00-00) (Conflict said-PC 2026-09-12_12-00-00).pptx"
        dup_file2.write_bytes(b"Presentation slide content 1234567890")

        # Another file with DIFFERENT content in conflict copy (real conflict, should NOT be deleted)
        doc = sync_folder / "doc.txt"
        doc.write_bytes(b"Base document")
        real_conflict = sync_folder / "doc (Conflict PC 2026-09-12_10-00-00).txt"
        real_conflict.write_bytes(b"Different conflict document")

        # Mock remote delete
        self.client.delete_resource = lambda path: True

        removed, freed = self.engine.deduplicate_conflict_copies()
        self.assertEqual(removed, 2)
        self.assertEqual(freed, len(b"Presentation slide content 1234567890") * 2)

        # Duplicates deleted
        self.assertFalse(dup_file1.exists())
        self.assertFalse(dup_file2.exists())

        # Base and real conflict preserved
        self.assertTrue(base_file.exists())
        self.assertTrue(doc.exists())
        self.assertTrue(real_conflict.exists())


if __name__ == "__main__":
    unittest.main()
