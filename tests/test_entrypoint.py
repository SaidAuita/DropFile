"""
Unit test for testing that DropFile entrypoint and all root modules load cleanly without NameError or ImportError.
"""

import importlib.util
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestEntrypoint(unittest.TestCase):
    def test_import_all_modules(self):
        root = Path(__file__).resolve().parent.parent
        for py_file in root.glob("*.py"):
            mod = importlib.import_module(py_file.stem)
            self.assertIsNotNone(mod)

        # Test DropFile.pyw
        pyw_file = root / "DropFile.pyw"
        spec = importlib.util.spec_from_file_location("DropFile", str(pyw_file))
        self.assertIsNotNone(spec)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["DropFile"] = mod
        spec.loader.exec_module(mod)
        self.assertTrue(hasattr(mod, "main"))
        self.assertTrue(hasattr(mod, "ensure_single_instance"))
        self.assertTrue(hasattr(mod, "release_instance_socket"))

    def test_desktop_shortcut_config(self):
        import tempfile, shutil
        from config import Config
        temp_dir = Path(tempfile.mkdtemp())
        try:
            cfg = Config(temp_dir)
            self.assertTrue(cfg.desktop_shortcut)
            cfg.desktop_shortcut = False
            self.assertFalse(cfg.desktop_shortcut)
            cfg.save()
            cfg2 = Config(temp_dir)
            self.assertFalse(cfg2.desktop_shortcut)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_settings_dialog_lifecycle(self):
        import tempfile, shutil
        import _tkinter
        from config import Config
        from fb_client import FileBrowserClient
        from gui_settings import SettingsDialog
        from state_db import StateDatabase

        temp_dir = Path(tempfile.mkdtemp())
        try:
            cfg = Config(temp_dir)
            db = StateDatabase(temp_dir / "state.db")
            cl = FileBrowserClient("http://mock", "user", "pwd")
            dlg = SettingsDialog(cfg, db, cl)

            # Initially window is None -> not alive
            self.assertFalse(dlg._is_window_alive())

            # Simulate destroyed Tk object throwing TclError
            class MockDestroyedTk:
                def winfo_exists(self):
                    raise _tkinter.TclError('can\'t invoke "winfo" command: application has been destroyed')
                def destroy(self):
                    raise _tkinter.TclError('application has been destroyed')

            dlg.window = MockDestroyedTk()
            # _is_window_alive must return False without crashing
            self.assertFalse(dlg._is_window_alive())

            # _on_close must safely destroy and set window to None
            dlg._on_close()
            self.assertIsNone(dlg.window)
            self.assertFalse(dlg._is_window_alive())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_sync_engine_config_reload(self):
        import tempfile, shutil, time, json
        from config import Config
        from fb_client import FileBrowserClient
        from state_db import StateDatabase
        from sync_engine import SyncEngine

        temp_dir = Path(tempfile.mkdtemp())
        try:
            cfg = Config(temp_dir)
            cfg.save()
            db = StateDatabase(temp_dir / "state.db")
            cl = FileBrowserClient("http://mock", "user", "pwd")
            engine = SyncEngine(cfg, db, cl)

            # Modify config.json on disk and advance mtime to guarantee detection
            import os
            with open(cfg.config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["username"] = "updated_user"
            with open(cfg.config_file, "w", encoding="utf-8") as f:
                json.dump(data, f)
            future_mtime = getattr(engine, "_last_cfg_mtime", 0.0) + 10.0
            os.utime(cfg.config_file, (future_mtime, future_mtime))

            # Check config reload
            engine._check_config_reload()
            self.assertEqual(engine.config.username, "updated_user")
            self.assertEqual(engine.client.username, "updated_user")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_spawn_settings_process_signature(self):
        from platform_utils import spawn_settings_process
        from win_utils import spawn_settings_process as win_spawn
        self.assertTrue(callable(spawn_settings_process))
        self.assertTrue(callable(win_spawn))

    def test_single_instance_lock(self):
        from platform_utils import acquire_single_instance_lock, release_single_instance_lock
        release_single_instance_lock()
        lock1 = acquire_single_instance_lock()
        if not lock1:
            # Another DropFile process is running on the local system and holding the lock
            self.assertFalse(lock1)
            return

        if sys.platform.startswith("win"):
            lock2 = acquire_single_instance_lock()
            self.assertFalse(lock2)

        release_single_instance_lock()
        lock3 = acquire_single_instance_lock()
        self.assertTrue(lock3)
        release_single_instance_lock()

    def test_send_instance_command_and_socket_collision(self):
        import socket
        from platform_utils import send_instance_command
        # Test command sending to port where nothing is listening (graceful False)
        res = send_instance_command(b"TEST\n", port=49199, timeout=0.2)
        self.assertFalse(res)

        # Test command sending to active listener
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 49199))
        server.listen(1)
        try:
            # In thread or before accept
            send_res = send_instance_command(b"HELLO\n", port=49199, timeout=0.5)
            self.assertTrue(send_res)
            conn, _ = server.accept()
            data = conn.recv(1024)
            conn.close()
            self.assertIn(b"HELLO", data)
        finally:
            server.close()

    def test_ensure_single_instance_exits_on_socket_in_use(self):
        import socket
        from unittest.mock import patch
        import DropFile

        # Check if port is already bound by an active instance or bind our own blocker
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        already_bound = False
        try:
            blocker.bind(("127.0.0.1", DropFile.SINGLE_INSTANCE_PORT))
            blocker.listen(1)
        except OSError:
            already_bound = True

        try:
            # ensure_single_instance must call _handle_duplicate_instance which raises SystemExit
            with self.assertRaises(SystemExit):
                with patch("DropFile.acquire_single_instance_lock", return_value=True):
                    with patch("DropFile.spawn_settings_process"):
                        DropFile.ensure_single_instance()
        finally:
            if not already_bound:
                blocker.close()
            DropFile.release_single_instance_lock()

    def test_dual_server_config(self):
        import tempfile, shutil
        from config import Config
        temp_dir = Path(tempfile.mkdtemp())
        try:
            cfg = Config(temp_dir)
            self.assertFalse(cfg.backup_server_enabled)
            self.assertEqual(cfg.backup_server_url, "")
            self.assertEqual(cfg.backup_username, "")
            self.assertEqual(cfg.backup_password, "")
            self.assertEqual(cfg.backup_remote_path, "/DropFile")
            self.assertEqual(cfg.primary_server_index, 1)

            cfg.backup_server_enabled = True
            cfg.backup_server_url = "https://backup.example.com/"
            cfg.backup_username = "backup_user"
            cfg.backup_password = "secret_password"
            cfg.backup_remote_path = "Exchange/Backup"
            cfg.primary_server_index = 2

            self.assertTrue(cfg.backup_server_enabled)
            self.assertEqual(cfg.backup_server_url, "https://backup.example.com")
            self.assertEqual(cfg.backup_username, "backup_user")
            self.assertEqual(cfg.backup_password, "secret_password")
            self.assertEqual(cfg.backup_remote_path, "/Exchange/Backup")
            self.assertEqual(cfg.primary_server_index, 2)

            cfg.save()
            cfg2 = Config(temp_dir)
            self.assertTrue(cfg2.backup_server_enabled)
            self.assertEqual(cfg2.backup_server_url, "https://backup.example.com")
            self.assertEqual(cfg2.backup_username, "backup_user")
            self.assertEqual(cfg2.primary_server_index, 2)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_cross_platform_config_exchange(self):
        import tempfile, shutil, json
        from config import Config, DEFAULT_CONFIG
        temp_dir = Path(tempfile.mkdtemp())
        try:
            # 1. Mac export -> Windows import
            mac_config_data = dict(DEFAULT_CONFIG)
            mac_config_data["server_url"] = "https://my.server.com"
            mac_config_data["username"] = "said_mac"
            mac_config_data["local_path"] = "/Users/said/Desktop/DropFile"
            mac_config_data["backup_server_enabled"] = True
            mac_config_data["backup_server_url"] = "https://backup.server.com"

            export_file = temp_dir / "mac_export.json"
            with open(export_file, "w", encoding="utf-8") as f:
                json.dump(mac_config_data, f)

            cfg = Config(temp_dir)
            ok = cfg.import_config(export_file)
            self.assertTrue(ok)
            self.assertEqual(cfg.username, "said_mac")
            self.assertEqual(cfg.server_url, "https://my.server.com")
            self.assertTrue(cfg.backup_server_enabled)

            if sys.platform == "win32":
                self.assertFalse(str(cfg.local_path).startswith("/Users/"))
                self.assertEqual(cfg.local_path, Path.home() / "Desktop" / "DropFile")

            # 2. Windows export -> Mac import
            win_config_data = dict(DEFAULT_CONFIG)
            win_config_data["server_url"] = "https://win.server.com"
            win_config_data["local_path"] = r"D:\DropFile\Sync"
            win_export_file = temp_dir / "win_export.json"
            with open(win_export_file, "w", encoding="utf-8") as f:
                json.dump(win_config_data, f)

            cfg_win = Config(temp_dir)
            ok_win = cfg_win.import_config(win_export_file)
            self.assertTrue(ok_win)
            if sys.platform != "win32":
                self.assertFalse(":" in str(cfg_win.local_path))
                self.assertEqual(cfg_win.local_path, Path.home() / "Desktop" / "DropFile")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_sync_engine_failover(self):
        import tempfile, shutil
        from config import Config
        from fb_client import FileBrowserClient
        from state_db import StateDatabase
        from sync_engine import SyncEngine
        from i18n import set_current_language

        temp_dir = Path(tempfile.mkdtemp())
        try:
            cfg = Config(temp_dir)
            cfg.server_url = "https://primary.server.com"
            cfg.username = "primary_user"
            cfg.password = "primary_pwd"
            cfg.remote_path = "/PrimaryRemote"

            cfg.backup_server_enabled = True
            cfg.backup_server_url = "https://backup.server.com"
            cfg.backup_username = "backup_user"
            cfg.backup_password = "backup_pwd"
            cfg.backup_remote_path = "/BackupRemote"
            cfg.primary_server_index = 1

            db = StateDatabase(temp_dir / "state.db")
            client = FileBrowserClient("https://primary.server.com", "primary_user", "primary_pwd")
            engine = SyncEngine(cfg, db, client)

            self.assertEqual(engine.active_server_index, 1)
            self.assertEqual(engine.active_remote_path, "/PrimaryRemote")
            self.assertIn("1", engine.get_active_server_label())

            engine.apply_server_connection(2)
            self.assertEqual(engine.active_server_index, 2)
            self.assertEqual(engine.client.base_url, "https://backup.server.com")
            self.assertEqual(engine.client.username, "backup_user")
            self.assertEqual(engine.active_remote_path, "/BackupRemote")
            self.assertIn("2", engine.get_active_server_label())

            set_current_language("ru")
            engine.set_status("Синхронизировано", "idle")
            self.assertIn("[Сервер 2]", engine.status_message)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_sync_engine_automatic_failover(self):
        import tempfile, shutil
        from unittest.mock import patch
        from config import Config
        from fb_client import FileBrowserClient
        from state_db import StateDatabase
        from sync_engine import SyncEngine

        temp_dir = Path(tempfile.mkdtemp())
        try:
            cfg = Config(temp_dir)
            cfg.server_url = "https://primary.server.com"
            cfg.username = "primary_user"
            cfg.password = "primary_pwd"
            cfg.remote_path = "/DropFile"

            cfg.backup_server_enabled = True
            cfg.backup_server_url = "https://backup.server.com"
            cfg.backup_username = "backup_user"
            cfg.backup_password = "backup_pwd"
            cfg.backup_remote_path = "/DropFile"
            cfg.primary_server_index = 1

            db = StateDatabase(temp_dir / "state.db")
            client = FileBrowserClient(cfg.server_url, cfg.username, cfg.password)
            engine = SyncEngine(cfg, db, client)
            engine._running = True

            def mock_test_connection(client_self, *args, **kwargs):
                if client_self.base_url == "https://primary.server.com":
                    return False, "Primary connection refused"
                elif client_self.base_url == "https://backup.server.com":
                    return True, "Connected to backup"
                return False, "Unknown"

            with patch.object(FileBrowserClient, "test_connection", autospec=True, side_effect=mock_test_connection):
                with patch.object(FileBrowserClient, "ensure_remote_dir_exists", return_value=True):
                    with patch.object(FileBrowserClient, "list_recursive", return_value=[]):
                        engine.reconcile_all()


            self.assertEqual(engine.active_server_index, 2)
            self.assertEqual(engine.client.base_url, "https://backup.server.com")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_dual_server_i18n(self):
        from i18n import t, set_current_language
        for lang in ("en", "ru"):
            set_current_language(lang)
            self.assertTrue(bool(t("conn_server1_title")))
            self.assertTrue(bool(t("conn_server2_title")))
            self.assertTrue(bool(t("conn_backup_enable")))
            self.assertTrue(bool(t("conn_test_btn1")))
            self.assertTrue(bool(t("conn_test_btn2")))
            self.assertTrue(bool(t("server_badge")))


if __name__ == "__main__":
    unittest.main()

