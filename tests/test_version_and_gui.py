"""
Unit tests for version tracking, build number, and password visibility toggles.
"""

import unittest
from unittest.mock import MagicMock, patch

from version import __version__, __build__, get_build_number, get_full_version


class TestVersionAndBuild(unittest.TestCase):
    def test_version_format(self):
        self.assertTrue(len(__version__.split(".")) >= 2)
        self.assertTrue(bool(__build__))

    def test_get_build_number(self):
        bn = get_build_number()
        self.assertTrue(isinstance(bn, str))
        self.assertTrue(len(bn) > 0)

    def test_get_full_version(self):
        fv = get_full_version()
        self.assertIn(__version__, fv)
        self.assertIn("build", fv)


class TestPasswordToggles(unittest.TestCase):
    def test_password_visibility_toggle_methods(self):
        from gui_settings import SettingsDialog

        # Verify toggle methods exist on SettingsDialog
        self.assertTrue(hasattr(SettingsDialog, "_toggle_pwd1_visibility"))
        self.assertTrue(hasattr(SettingsDialog, "_toggle_pwd2_visibility"))

        # Test toggle logic on a mock instance
        mock_dlg = MagicMock(spec=SettingsDialog)
        mock_dlg.entry_pwd = MagicMock()
        mock_dlg.btn_toggle_pwd1 = MagicMock()
        mock_dlg._pwd1_visible = False

        SettingsDialog._toggle_pwd1_visibility(mock_dlg)
        self.assertTrue(mock_dlg._pwd1_visible)
        mock_dlg.entry_pwd.config.assert_called_with(show="")
        mock_dlg.btn_toggle_pwd1.config.assert_called_with(text="🔒")

        SettingsDialog._toggle_pwd1_visibility(mock_dlg)
        self.assertFalse(mock_dlg._pwd1_visible)
        mock_dlg.entry_pwd.config.assert_called_with(show="•")
        mock_dlg.btn_toggle_pwd1.config.assert_called_with(text="👁")


class TestTrayBuildDisplay(unittest.TestCase):
    def test_tray_menu_has_build_header(self):
        from tray import DropFileTray

        mock_config = MagicMock()
        mock_config.backup_server_enabled = False
        mock_config.sync_backup_server = False
        mock_config.notify_on_sync = True

        mock_engine = MagicMock()
        mock_engine.is_paused.return_value = False
        mock_engine.get_last_uploaded_item.return_value = None

        tray = DropFileTray(config=mock_config, engine=mock_engine)
        menu = tray._build_menu()

        # Check menu items
        items = list(menu.items)
        self.assertTrue(len(items) > 0)
        top_item = items[0]
        # Text callable or string
        text = top_item.text(top_item) if callable(top_item.text) else str(top_item.text)
        self.assertIn(__version__, text)
        self.assertIn("build", text)
        self.assertFalse(top_item.enabled)


class TestTrayIcons(unittest.TestCase):
    def test_create_tray_icon_states(self):
        from icons import create_tray_icon

        for state in ["idle", "syncing", "error", "paused"]:
            for sz in [16, 24, 32, 64]:
                img = create_tray_icon(state, size=sz)
                self.assertEqual(img.size, (sz, sz))
                self.assertEqual(img.mode, "RGBA")

    def test_syncing_icon_has_green_arrows(self):
        from icons import create_tray_icon

        img = create_tray_icon("syncing", size=64)
        # Check that vibrant green arrow pixels exist at arrow tip coordinates
        # Up arrow tip around (21, 10), Down arrow tip around (43, 54)
        up_pixel = img.getpixel((21, 10))
        down_pixel = img.getpixel((43, 54))
        self.assertTrue(up_pixel[1] > 200, f"Up arrow should be green, got {up_pixel}")
        self.assertTrue(down_pixel[1] > 200, f"Down arrow should be green, got {down_pixel}")


class TestSpeedMonitorTransferUI(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_transfer_ui_idle_state(self):
        from gui_speed_chart import SpeedMonitorCard
        card = SpeedMonitorCard(self.root, auto_start=False)
        card._update_transfer_ui(None)
        self.assertIn("✓", card.lbl_file_name.cget("text"))
        self.assertEqual(card.lbl_file_pct.cget("text"), "")
        self.assertEqual(card.lbl_transfer_bytes.cget("text"), "")

    def test_transfer_ui_single_file(self):
        from gui_speed_chart import SpeedMonitorCard
        card = SpeedMonitorCard(self.root, auto_start=False)
        sample = {
            "direction": "tx",
            "file_name": "document.pdf",
            "total_bytes": 1000,
            "transferred_bytes": 500,
            "percent": 50.0,
            "batch_total": 1,
            "batch_current": 1,
            "eta_seconds": 10,
        }
        card._update_transfer_ui(sample)
        self.assertIn("document.pdf", card.lbl_file_name.cget("text"))
        self.assertEqual(card.lbl_file_pct.cget("text"), "50 %")
        self.assertNotEqual(card.batch_container.winfo_manager(), "pack")

    def test_transfer_ui_batch_mode_total_commander_style(self):
        from gui_speed_chart import SpeedMonitorCard
        card = SpeedMonitorCard(self.root, auto_start=False)
        sample = {
            "direction": "tx",
            "file_name": "AAA__00111_.png",
            "rel_path": "Azbuka/AAA__00111_.png",
            "total_bytes": 1000000,
            "transferred_bytes": 0,
            "percent": 0.0,
            "batch_total": 366,
            "batch_current": 110,
            "batch_bytes_total": 598300000,
            "batch_bytes_transferred": 183300000,
            "batch_percent": 31.0,
            "eta_seconds": 60,
        }
        card._update_transfer_ui(sample)
        self.assertIn("AAA__00111_.png", card.lbl_file_name.cget("text"))
        self.assertEqual(card.lbl_file_pct.cget("text"), "0 %")
        self.assertEqual(card.lbl_batch_files.cget("text"), "110 / 366")
        self.assertEqual(card.lbl_batch_pct.cget("text"), "31 %")
        self.assertEqual(card.batch_container.winfo_manager(), "pack")


if __name__ == "__main__":
    unittest.main()

