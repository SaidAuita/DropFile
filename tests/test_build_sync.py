"""
Unit tests for DropFile Build Drops Synchronization Engine and Config.
"""

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config
from build_sync import BuildSyncEngine
from state_db import StateDatabase


class TestBuildSync(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.cfg_dir = self.test_dir / "config"
        self.cfg_dir.mkdir(parents=True, exist_ok=True)
        self.config = Config(config_dir=self.cfg_dir)

        self.db_path = self.test_dir / "test_state.db"
        self.state_db = StateDatabase(self.db_path)

        self.source_dir = self.test_dir / "projects" / "ID_Code_Pro" / "Build_DEV"
        self.source_dir.mkdir(parents=True, exist_ok=True)

        self.target_dir = self.test_dir / "server_exchange" / "Build" / "ID_Code_Pro"

        self.notifications = []

        def on_notify(title, msg):
            self.notifications.append((title, msg))

        self.engine = BuildSyncEngine(
            config=self.config,
            state_db=self.state_db,
            on_notify=on_notify,
            poll_interval=0.5,
            debounce_seconds=0.1,  # Short debounce for quick tests
        )

    def tearDown(self):
        self.engine.stop()
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_config_properties(self):
        self.assertFalse(self.config.build_sync_enabled)
        self.assertEqual(self.config.build_sync_tasks, [])

        self.config.build_sync_enabled = True
        tasks = [
            {
                "id": "task1",
                "name": "ID Code Pro",
                "source_dir": str(self.source_dir),
                "pattern": "*.zip",
                "target_dir": str(self.target_dir),
                "keep_versions": 3,
                "enabled": True,
            }
        ]
        self.config.build_sync_tasks = tasks
        self.config.save()

        # Reload from disk
        cfg_reloaded = Config(config_dir=self.cfg_dir)
        self.assertTrue(cfg_reloaded.build_sync_enabled)
        self.assertEqual(len(cfg_reloaded.build_sync_tasks), 1)
        self.assertEqual(cfg_reloaded.build_sync_tasks[0]["name"], "ID Code Pro")
        self.assertEqual(cfg_reloaded.build_sync_tasks[0]["keep_versions"], 3)

    def test_build_sync_and_rotation(self):
        task = {
            "id": "task_id_code",
            "name": "ID Code Pro",
            "source_dir": str(self.source_dir),
            "pattern": "*.zip",
            "target_dir": str(self.target_dir),
            "keep_versions": 2,  # Keep only 2 versions
            "enabled": True,
        }

        # 1. Create first build (pre-existing, mtime in past)
        build1 = self.source_dir / "ID_Code_Pro_v3.02.20.zip"
        build1.write_bytes(b"PK\x03\x04build1_contents")
        os.utime(build1, (time.time() - 10, time.time() - 10))

        # First check copies pre-existing build immediately!
        copied = self.engine.process_task(task)
        self.assertEqual(copied, 1)
        self.assertTrue((self.target_dir / "ID_Code_Pro_v3.02.20.zip").exists())
        self.assertEqual(len(self.notifications), 1)

        # 2. Create second build (pre-existing)
        build2 = self.source_dir / "ID_Code_Pro_v3.02.21.zip"
        build2.write_bytes(b"PK\x03\x04build2_contents")
        os.utime(build2, (time.time() - 5, time.time() - 5))

        copied = self.engine.process_task(task)
        self.assertEqual(copied, 1)
        self.assertTrue((self.target_dir / "ID_Code_Pro_v3.02.21.zip").exists())

        # Target currently has 2 builds
        target_files = sorted([f.name for f in self.target_dir.glob("*.zip")])
        self.assertEqual(len(target_files), 2)

        # 3. Create third build (should trigger rotation, deleting oldest build1)
        build3 = self.source_dir / "ID_Code_Pro_v3.02.22.zip"
        build3.write_bytes(b"PK\x03\x04build3_contents")
        os.utime(build3, (time.time() - 1, time.time() - 1))

        copied = self.engine.process_task(task)
        self.assertEqual(copied, 1)
        self.assertTrue((self.target_dir / "ID_Code_Pro_v3.02.22.zip").exists())

        # Rotation check: target should have exactly 2 files: build2 and build3!
        remaining = sorted([f.name for f in self.target_dir.glob("*.zip")])
        self.assertEqual(len(remaining), 2)
        self.assertIn("ID_Code_Pro_v3.02.21.zip", remaining)
        self.assertIn("ID_Code_Pro_v3.02.22.zip", remaining)
        self.assertNotIn("ID_Code_Pro_v3.02.20.zip", remaining)

        # 4. Verify log history in state_db
        history = self.state_db.get_recent_history(50)
        sync_logs = [h for h in history if h.get("action") == "BUILD_SYNC"]
        rotate_logs = [h for h in history if h.get("action") == "BUILD_ROTATE"]

        self.assertEqual(len(sync_logs), 3)
        self.assertEqual(len(rotate_logs), 1)
        self.assertIn("ID_Code_Pro_v3.02.20.zip", rotate_logs[0]["rel_path"])

    def test_pre_existing_files_sync_immediately(self):
        task = {
            "id": "task_pre_exist",
            "name": "Pre-existing Project",
            "source_dir": str(self.source_dir),
            "pattern": "*.zip",
            "target_dir": str(self.target_dir),
            "keep_versions": 5,
            "enabled": True,
        }
        # Create 3 archives created earlier (in the past)
        for i in range(1, 4):
            b = self.source_dir / f"App_v1.0.{i}.zip"
            b.write_bytes(f"PK_content_{i}".encode("utf-8"))
            os.utime(b, (time.time() - (100 - i * 10), time.time() - (100 - i * 10)))

        # Single first pass must copy all 3 files immediately without waiting
        copied = self.engine.process_task(task)
        self.assertEqual(copied, 3)
        for i in range(1, 4):
            self.assertTrue((self.target_dir / f"App_v1.0.{i}.zip").exists())

    def test_pre_existing_files_exceeding_keep_versions(self):
        task = {
            "id": "task_keep_latest",
            "name": "Keep Latest",
            "source_dir": str(self.source_dir),
            "pattern": "*.zip",
            "target_dir": str(self.target_dir),
            "keep_versions": 2,
            "enabled": True,
        }
        # Create 4 older archives
        for i in range(1, 5):
            b = self.source_dir / f"Build_v{i}.zip"
            b.write_bytes(f"content_{i}".encode("utf-8"))
            os.utime(b, (time.time() - (50 - i * 10), time.time() - (50 - i * 10)))

        # Process task: only latest 2 builds (v3, v4) should be copied to target
        copied = self.engine.process_task(task)
        self.assertEqual(copied, 2)
        target_files = sorted([f.name for f in self.target_dir.glob("*.zip")])
        self.assertEqual(target_files, ["Build_v3.zip", "Build_v4.zip"])

    def test_new_file_still_debounced(self):
        task = {
            "id": "task_debounce",
            "name": "Debounce Test",
            "source_dir": str(self.source_dir),
            "pattern": "*.zip",
            "target_dir": str(self.target_dir),
            "keep_versions": 5,
            "enabled": True,
        }
        # Brand new file created right now (mtime = current time)
        b = self.source_dir / "BrandNew_v1.zip"
        b.write_bytes(b"PK_brand_new")
        now = time.time()
        os.utime(b, (now, now))

        # First check starts debounce: should not copy yet
        copied1 = self.engine.process_task(task)
        self.assertEqual(copied1, 0)
        self.assertFalse((self.target_dir / "BrandNew_v1.zip").exists())

        # Wait past debounce (engine debounce_seconds = 0.1)
        time.sleep(0.15)
        copied2 = self.engine.process_task(task)
        self.assertEqual(copied2, 1)
        self.assertTrue((self.target_dir / "BrandNew_v1.zip").exists())

    def test_disabled_task_skipped(self):
        task = {
            "id": "task_disabled",
            "name": "Disabled Project",
            "source_dir": str(self.source_dir),
            "pattern": "*.zip",
            "target_dir": str(self.target_dir),
            "keep_versions": 5,
            "enabled": False,
        }
        build = self.source_dir / "Disabled_v1.zip"
        build.write_bytes(b"PK\x03\x04content")

        copied = self.engine.process_task(task)
        self.assertEqual(copied, 0)
        self.assertFalse((self.target_dir / "Disabled_v1.zip").exists())

    def test_gui_dialogs_instantiation(self):
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
        except Exception:
            return  # Headless environment without display

        try:
            from gui_build_sync import BuildSyncDialog, BuildTaskEditDialog
            # Test BuildTaskEditDialog
            task_saved = {}
            def on_save(data):
                nonlocal task_saved
                task_saved = data

            dlg_edit = BuildTaskEditDialog(
                parent=root,
                task_data={"name": "TestApp", "source_dir": str(self.source_dir), "target_dir": str(self.target_dir)},
                on_save_callback=on_save,
            )
            dlg_edit._on_save()
            self.assertEqual(task_saved.get("name"), "TestApp")

            # Test BuildSyncDialog
            dlg_main = BuildSyncDialog(
                parent=root,
                config=self.config,
                build_engine=self.engine,
            )
            self.assertIsNotNone(dlg_main.tree)
            dlg_main.destroy()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
