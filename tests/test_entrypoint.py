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
            spec.loader.exec_module(mod)

        # Test DropFile.pyw
        pyw_file = root / "DropFile.pyw"
        spec = importlib.util.spec_from_file_location("DropFile", str(pyw_file))
        self.assertIsNotNone(spec)
        mod = importlib.util.module_from_spec(spec)
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


if __name__ == "__main__":
    unittest.main()
