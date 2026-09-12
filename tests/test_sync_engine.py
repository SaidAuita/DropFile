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


if __name__ == "__main__":
    unittest.main()
