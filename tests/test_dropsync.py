"""
Unit and integration tests for DropSync Server.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from dropsync_server.config import Config
from dropsync_server.protocol import (
    MSG_FILE_CHUNK,
    MSG_FILE_OFFER,
    pack_binary_chunk,
    pack_json_message,
    unpack_binary_chunk,
    unpack_json_message,
)
from dropsync_server.state_db import StateDatabase
from dropsync_server.watcher import FileSystemWatcher
from dropsync_server.engine import DropSyncEngine


class TestDropSync(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="dropsync_test_"))

    def tearDown(self):
        try:
            shutil.rmtree(self.test_dir)
        except Exception:
            pass

    def test_config_defaults_and_properties(self):
        cfg_path = self.test_dir / "config.json"
        config = Config(cfg_path)
        self.assertEqual(config.role, "server")
        self.assertEqual(config.listen_port, 8443)
        self.assertTrue(len(config.auth_token) > 10)

        # Test overrides and save
        config.node_name = "test-node"
        config.listen_port = 9000
        config.save()

        # Reload
        config2 = Config(cfg_path)
        self.assertEqual(config2.node_name, "test-node")
        self.assertEqual(config2.listen_port, 9000)

    def test_protocol_json_packing(self):
        packed = pack_json_message(MSG_FILE_OFFER, {"rel_path": "doc.pdf", "size": 1024})
        unpacked = unpack_json_message(packed)
        self.assertEqual(unpacked["type"], MSG_FILE_OFFER)
        self.assertEqual(unpacked["rel_path"], "doc.pdf")
        self.assertEqual(unpacked["size"], 1024)

    def test_protocol_binary_chunk_packing(self):
        header = {"rel_path": "photo.jpg", "offset": 0, "total_size": 5, "is_last": True}
        raw_payload = b"HELLO"
        frame = pack_binary_chunk(header, raw_payload)

        unpacked_header, unpacked_payload = unpack_binary_chunk(frame)
        self.assertIsNotNone(unpacked_header)
        self.assertEqual(unpacked_header["rel_path"], "photo.jpg")
        self.assertEqual(unpacked_header["is_last"], True)
        self.assertEqual(unpacked_payload, raw_payload)

    def test_state_database(self):
        db_path = self.test_dir / "state.db"
        db = StateDatabase(db_path)

        # Create a test file
        f_path = self.test_dir / "test.txt"
        f_path.write_text("Hello DropSync!", encoding="utf-8")
        h = StateDatabase.calculate_file_hash(f_path)
        self.assertTrue(len(h) == 64)

        db.upsert_file("test.txt", f_path.stat().st_size, f_path.stat().st_mtime, h, deleted=0)
        row = db.get_file("test.txt")
        self.assertIsNotNone(row)
        self.assertEqual(row["hash"], h)
        self.assertEqual(row["deleted"], 0)

        manifest = db.get_manifest()
        self.assertIn("test.txt", manifest)

        db.mark_deleted("test.txt")
        manifest2 = db.get_manifest()
        self.assertTrue(manifest2["test.txt"]["deleted"])

    def test_watcher_ignores(self):
        watcher = FileSystemWatcher(self.test_dir, ignore_patterns=["~$*", "*.tmp"])
        self.assertTrue(watcher.is_ignored("~$document.docx"))
        self.assertTrue(watcher.is_ignored("data/cache.tmp"))
        self.assertTrue(watcher.is_ignored(".dropsync/state.db"))
        self.assertFalse(watcher.is_ignored("important/report.pdf"))


class TestAsyncEngine(unittest.IsolatedAsyncioTestCase):
    async def test_engine_initialization(self):
        test_dir = Path(tempfile.mkdtemp(prefix="dropsync_async_"))
        try:
            cfg = Config(test_dir / "config.json")
            cfg.sync_dir = test_dir / "data"
            cfg.role = "server"
            cfg.listen_port = 19443

            engine = DropSyncEngine(cfg)
            # Verify engine initializes components without error
            self.assertIsNotNone(engine.state_db)
            self.assertIsNotNone(engine.watcher)
            self.assertIsNotNone(engine.transport)
        finally:
            try:
                shutil.rmtree(test_dir)
            except Exception:
                pass

    async def test_end_to_end_sync(self):
        base_dir = Path(tempfile.mkdtemp(prefix="dropsync_e2e_"))
        try:
            token = "secret-test-token-123"
            port = 19876

            # Server Node
            srv_cfg = Config(base_dir / "server_config.json")
            srv_cfg.node_name = "server-node"
            srv_cfg.role = "server"
            srv_cfg.sync_dir = base_dir / "server_data"
            srv_cfg.listen_port = port
            srv_cfg.auth_token = token
            srv_cfg.debounce_delay = 0.2

            # Client Node
            cli_cfg = Config(base_dir / "client_config.json")
            cli_cfg.node_name = "client-node"
            cli_cfg.role = "client"
            cli_cfg.sync_dir = base_dir / "client_data"
            cli_cfg.remote_url = f"ws://127.0.0.1:{port}"
            cli_cfg.auth_token = token
            cli_cfg.debounce_delay = 0.2

            srv_engine = DropSyncEngine(srv_cfg)
            cli_engine = DropSyncEngine(cli_cfg)

            await srv_engine.start()
            await cli_engine.start()

            # Wait for connection handshake
            await asyncio.sleep(0.5)

            # 1. Create file on Server
            test_file = srv_cfg.sync_dir / "notes.txt"
            test_file.write_text("DropSync integration test content 123", encoding="utf-8")

            # Trigger local change event
            srv_engine._handle_local_change("notes.txt")

            # Wait for transfer and verification
            for _ in range(30):
                if (cli_cfg.sync_dir / "notes.txt").exists():
                    break
                await asyncio.sleep(0.1)

            dest_file = cli_cfg.sync_dir / "notes.txt"
            self.assertTrue(dest_file.exists())
            self.assertEqual(dest_file.read_text(encoding="utf-8"), "DropSync integration test content 123")

            # 2. Update file on Client (Bi-directional test)
            dest_file.write_text("Updated content from client!", encoding="utf-8")
            cli_engine._handle_local_change("notes.txt")

            for _ in range(30):
                if test_file.read_text(encoding="utf-8") == "Updated content from client!":
                    break
                await asyncio.sleep(0.1)

            self.assertEqual(test_file.read_text(encoding="utf-8"), "Updated content from client!")

            # 3. Delete file on Server
            test_file.unlink()
            srv_engine._handle_local_delete("notes.txt")

            for _ in range(30):
                if not dest_file.exists():
                    break
                await asyncio.sleep(0.1)

            self.assertFalse(dest_file.exists())

            await cli_engine.stop()
            await srv_engine.stop()
        finally:
            try:
                shutil.rmtree(base_dir)
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
