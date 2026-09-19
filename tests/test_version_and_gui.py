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


if __name__ == "__main__":
    unittest.main()
