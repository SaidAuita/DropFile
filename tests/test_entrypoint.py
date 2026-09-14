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
            mod_name = py_file.stem
            spec = importlib.util.spec_from_file_location(mod_name, str(py_file))
            self.assertIsNotNone(spec)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)

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


if __name__ == "__main__":
    unittest.main()
