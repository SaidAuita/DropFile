"""
Unit tests for dual-server comparison and synchronization features in DropFile.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from config import Config
from fb_client import RemoteItem
from i18n import set_current_language
from state_db import StateDatabase
from sync_engine import SyncEngine


class TestServersSync(unittest.TestCase):
    def setUp(self):
        set_current_language("ru")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.cfg_file = self.root / "config.json"
        self.local_dir = self.root / "DropFile"
        self.local_dir.mkdir(parents=True, exist_ok=True)

        self.cfg = Config(self.root)
        self.cfg.server_url = "https://server1.local"
        self.cfg.username = "user1"
        self.cfg.password = "pass1"
        self.cfg.remote_path = "/DropFile"
        self.cfg.local_path = self.local_dir
        self.cfg.backup_server_enabled = True
        self.cfg.backup_server_url = "https://server2.local"
        self.cfg.backup_username = "user2"
        self.cfg.backup_password = "pass2"
        self.cfg.backup_remote_path = "/DropFile"
        self.cfg.sync_backup_server = True
        self.cfg.save()

        self.state_db = StateDatabase(self.root / "state.db")
        self.mock_client = MagicMock()
        self.engine = SyncEngine(config=self.cfg, state_db=self.state_db, client=self.mock_client)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_config_sync_backup_server_property(self):
        """Test getter, setter, and persistence of sync_backup_server."""
        self.assertTrue(self.cfg.sync_backup_server)

        self.cfg.sync_backup_server = False
        self.assertFalse(self.cfg.sync_backup_server)
        self.cfg.save()

        # Reload from disk
        cfg2 = Config(self.root)
        self.assertFalse(cfg2.sync_backup_server)

    def test_get_active_server_label_dual_sync(self):
        """Test server label when dual sync is active."""
        self.cfg.backup_server_enabled = True
        self.cfg.sync_backup_server = True
        label = self.engine.get_active_server_label()
        self.assertIn("1 ⇄ 2", label)

        self.cfg.sync_backup_server = False
        label2 = self.engine.get_active_server_label()
        self.assertIn("1", label2)
        self.assertNotIn("⇄", label2)

    def test_compare_servers_disabled(self):
        """When backup server is disabled, comparison status is marked disabled."""
        self.cfg.backup_server_enabled = False
        st = self.engine.compare_servers_status()
        self.assertFalse(st["enabled"])
        self.assertEqual(st["state"], "disabled")

    @patch("sync_engine.FileBrowserClient")
    def test_compare_servers_both_online_synced(self, mock_fb_class):
        """When both servers have identical files and timestamps, state is 'synced'."""
        c1 = MagicMock()
        c2 = MagicMock()

        mock_fb_class.side_effect = [c1, c2]

        c1.test_connection.return_value = (True, "OK")
        c2.test_connection.return_value = (True, "OK")

        sample_items1 = [
            RemoteItem(name="doc.pdf", path="/DropFile/doc.pdf", is_dir=False, size=1024, modified="2026-09-14T12:00:00Z"),
        ]
        sample_items2 = [
            RemoteItem(name="doc.pdf", path="/DropFile/doc.pdf", is_dir=False, size=1024, modified="2026-09-14T12:00:00Z"),
        ]
        c1.list_recursive.return_value = sample_items1
        c2.list_recursive.return_value = sample_items2

        st = self.engine.compare_servers_status()
        self.assertEqual(st["state"], "synced")
        self.assertTrue(st["server1"]["online"])
        self.assertTrue(st["server2"]["online"])
        self.assertEqual(st["server1"]["file_count"], 1)
        self.assertEqual(st["server2"]["file_count"], 1)

    @patch("sync_engine.FileBrowserClient")
    def test_compare_servers_server1_newer(self, mock_fb_class):
        """When Server 1 has a newer file, state is 'server1_newer'."""
        c1 = MagicMock()
        c2 = MagicMock()
        mock_fb_class.side_effect = [c1, c2]

        c1.test_connection.return_value = (True, "OK")
        c2.test_connection.return_value = (True, "OK")

        c1.list_recursive.return_value = [
            RemoteItem(name="new.txt", path="/DropFile/new.txt", is_dir=False, size=100, modified="2026-09-14T14:00:00Z"),
        ]
        c2.list_recursive.return_value = [
            RemoteItem(name="old.txt", path="/DropFile/old.txt", is_dir=False, size=80, modified="2026-09-14T10:00:00Z"),
        ]

        st = self.engine.compare_servers_status()
        self.assertEqual(st["state"], "server1_newer")

    @patch("sync_engine.FileBrowserClient")
    def test_compare_servers_offline_detection(self, mock_fb_class):
        """Offline servers are correctly reflected in status."""
        c1 = MagicMock()
        c2 = MagicMock()
        mock_fb_class.side_effect = [c1, c2]

        c1.test_connection.return_value = (True, "OK")
        c1.list_recursive.return_value = []
        c2.test_connection.return_value = (False, "Timeout")

        st = self.engine.compare_servers_status()
        self.assertEqual(st["state"], "server2_offline")

    @patch("sync_engine.FileBrowserClient")
    def test_sync_servers_mirror_reconciles_missing_files(self, mock_fb_class):
        """Mirroring downloads missing file from Server 1 and uploads to Server 2."""
        c1 = MagicMock()
        c2 = MagicMock()
        mock_fb_class.side_effect = [c1, c2, c1, c2]

        c1.test_connection.return_value = (True, "OK")
        c2.test_connection.return_value = (True, "OK")

        # Server 1 has report.docx, Server 2 has nothing
        c1.list_recursive.return_value = [
            RemoteItem(name="report.docx", path="/DropFile/report.docx", is_dir=False, size=2048, modified="2026-09-14T12:00:00Z"),
        ]
        c2.list_recursive.return_value = []

        def fake_download(remote_p, local_p):
            Path(local_p).write_bytes(b"dummy docx" * 200)
            return True

        c1.download_file.side_effect = fake_download
        c2.upload_file.return_value = True

        synced, errors = self.engine.sync_servers_mirror()
        self.assertEqual(errors, 0)
        self.assertEqual(synced, 1)
        c2.upload_file.assert_called()

    def test_acquire_or_renew_sync_leader_new(self):
        """When no remote lock exists, client acquires leadership."""
        self.mock_client.read_text_file.return_value = None
        self.mock_client.write_text_file.return_value = True

        is_leader, info = self.engine.acquire_or_renew_sync_leader()
        self.assertTrue(is_leader)
        self.assertTrue(self.engine.is_sync_leader)
        self.assertEqual(info["client_id"], self.engine.client_id)
        self.mock_client.write_text_file.assert_called_once()

    def test_acquire_or_renew_sync_leader_renew_own(self):
        """When existing lock belongs to this client, it renews successfully."""
        existing = {
            "client_id": self.engine.client_id,
            "hostname": self.engine.hostname,
            "acquired_at": 1000.0,
            "expires_at": 2000.0,
        }
        self.mock_client.read_text_file.return_value = json.dumps(existing)
        self.mock_client.write_text_file.return_value = True

        is_leader, info = self.engine.acquire_or_renew_sync_leader()
        self.assertTrue(is_leader)
        self.assertEqual(info["client_id"], self.engine.client_id)

    def test_acquire_or_renew_sync_leader_other_active(self):
        """When another client holds an active lock, this client becomes follower."""
        import time
        existing = {
            "client_id": "other-uuid-1234",
            "hostname": "other-workstation",
            "acquired_at": time.time(),
            "expires_at": time.time() + 120.0,
        }
        self.mock_client.read_text_file.return_value = json.dumps(existing)

        is_leader, info = self.engine.acquire_or_renew_sync_leader()
        self.assertFalse(is_leader)
        self.assertFalse(self.engine.is_sync_leader)
        self.assertEqual(info["hostname"], "other-workstation")
        self.mock_client.write_text_file.assert_not_called()

    def test_acquire_or_renew_sync_leader_expired_takeover(self):
        """When another client's lock has expired, this client takes over leadership."""
        import time
        stale = {
            "client_id": "crashed-pc-9999",
            "hostname": "old-workstation",
            "acquired_at": time.time() - 500.0,
            "expires_at": time.time() - 200.0,
        }
        self.mock_client.read_text_file.return_value = json.dumps(stale)
        self.mock_client.write_text_file.return_value = True

        is_leader, info = self.engine.acquire_or_renew_sync_leader()
        self.assertTrue(is_leader)
        self.assertTrue(self.engine.is_sync_leader)
        self.assertEqual(info["client_id"], self.engine.client_id)
        self.mock_client.write_text_file.assert_called_once()

    def test_release_sync_leader(self):
        """Releasing leader removes remote lock and resets state."""
        self.engine.is_sync_leader = True
        self.engine.leader_info = {"client_id": self.engine.client_id}
        self.mock_client.delete_resource.return_value = True

        self.engine.release_sync_leader()
        self.assertFalse(self.engine.is_sync_leader)
        self.mock_client.delete_resource.assert_called_once_with(self.engine.leader_lock_remote_path)

    def test_server_2_settings_persistence(self):
        """Verify Server 2 credentials and toggles are saved and reloaded properly."""
        self.cfg.backup_server_enabled = True
        self.cfg.backup_server_url = "http://85.140.57.143:8085"
        self.cfg.backup_username = "admin"
        self.cfg.backup_password = "secure_password"
        self.cfg.backup_remote_path = "/Exchange"
        self.cfg.primary_server_index = 2
        self.cfg.save()

        cfg_loaded = Config(self.root)
        self.assertTrue(cfg_loaded.backup_server_enabled)
        self.assertEqual(cfg_loaded.backup_server_url, "http://85.140.57.143:8085")
        self.assertEqual(cfg_loaded.backup_username, "admin")
        self.assertEqual(cfg_loaded.backup_password, "secure_password")
        self.assertEqual(cfg_loaded.backup_remote_path, "/Exchange")
        self.assertEqual(cfg_loaded.primary_server_index, 2)

    def test_backup_remote_path_fallback(self):
        """If backup_remote_path is not set, it should fallback to remote_path."""
        self.cfg._data.pop("backup_remote_path", None)
        self.cfg.remote_path = "/CustomExchange"
        self.assertEqual(self.cfg.backup_remote_path, "/CustomExchange")


if __name__ == "__main__":
    unittest.main()

