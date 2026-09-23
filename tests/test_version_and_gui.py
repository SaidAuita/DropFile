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

    def test_speed_monitor_header_subrow_layout(self):
        from gui_speed_chart import SpeedMonitorCard
        card = SpeedMonitorCard(self.root, auto_start=False)
        # Verify status pill and disk pill exist and share the same subrow right-aligned parent frame
        self.assertEqual(card.lbl_status_pill.master, card.lbl_disk_pill.master)
        self.assertNotEqual(card.lbl_status_pill.master, card.lbl_iface.master)
        # Simulate disk telemetry update
        card.lbl_disk_pill.pack(side="left", padx=(6, 0))
        # Verify both are packed
        self.assertEqual(card.lbl_status_pill.winfo_manager(), "pack")
    def test_speed_monitor_bottom_stats_one_row(self):
        from gui_speed_chart import SpeedMonitorCard
        card = SpeedMonitorCard(self.root, auto_start=False)
        # Verify both total labels are present and share parent stats_row container
        self.assertIsNotNone(card.lbl_tot_rx_val)
        self.assertIsNotNone(card.lbl_tot_tx_val)
        self.assertEqual(card.lbl_tot_rx_title.master.master, card.lbl_tot_tx_title.master.master)
        # Verify redundant speed labels are None
        self.assertIsNone(card.lbl_cur_rx_val)
        self.assertIsNone(card.lbl_cur_tx_val)


class TestServerExchangeDetection(unittest.TestCase):
    def test_find_server_exchange_path_mocked(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from config import find_server_exchange_path

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_server = Path(tmpdir) / "speed_server"
            mock_server.mkdir()

            with patch("pathlib.Path.home", return_value=Path(tmpdir)):
                detected = find_server_exchange_path()
                self.assertIsNotNone(detected)
                self.assertEqual(detected.resolve(), mock_server.resolve())

    def test_settings_dialog_has_autodetect_exchange_button(self):
        from gui_settings import SettingsDialog
        self.assertTrue(hasattr(SettingsDialog, "_autodetect_exchange_folder"))


class TestLanServerDetection(unittest.TestCase):
    def test_detect_network_environment_work(self):
        from platform_utils import detect_network_environment
        with patch("socket.gethostbyname_ex", return_value=("pc", [], ["192.168.0.15", "10.0.0.1"])):
            is_work, is_home = detect_network_environment()
            self.assertTrue(is_work)
            self.assertFalse(is_home)

    def test_detect_network_environment_home(self):
        from platform_utils import detect_network_environment
        with patch("socket.gethostbyname_ex", return_value=("pc", [], ["192.168.1.50"])):
            is_work, is_home = detect_network_environment()
            self.assertFalse(is_work)
            self.assertTrue(is_home)

    def test_get_default_lan_server_host(self):
        from platform_utils import get_default_lan_server_host
        with patch("platform_utils.detect_network_environment", return_value=(True, False)):
            self.assertEqual(get_default_lan_server_host(), "192.168.0.22")
            # Keenetic domain should be ignored in favor of local work server
            self.assertEqual(get_default_lan_server_host("photo.buka3033.keenetic.link"), "192.168.0.22")
            # Valid local custom IP should be preserved
            self.assertEqual(get_default_lan_server_host("192.168.0.100"), "192.168.0.100")

        with patch("platform_utils.detect_network_environment", return_value=(False, True)):
            self.assertEqual(get_default_lan_server_host(), "192.168.1.4")
            self.assertEqual(get_default_lan_server_host("photo.buka3033.keenetic.link"), "192.168.1.4")

    def test_detect_lan_server_host_work_priority(self):
        from platform_utils import detect_lan_server_host
        with patch("platform_utils.detect_network_environment", return_value=(True, False)):
            # If socket fails, fallback to work server
            with patch("socket.socket") as mock_sock:
                mock_s = MagicMock()
                mock_s.connect_ex.return_value = 1
                mock_sock.return_value = mock_s
                res = detect_lan_server_host("photo.buka3033.keenetic.link", ["photo.buka3033.keenetic.link"])
                self.assertEqual(res, "192.168.0.22")

            # If 192.168.0.22 responds on port 445
            with patch("socket.socket") as mock_sock:
                mock_s = MagicMock()
                def fake_connect(addr):
                    host, port = addr
                    if host == "192.168.0.22" and port == 445:
                        return 0
                    return 1
                mock_s.connect_ex.side_effect = fake_connect
                mock_sock.return_value = mock_s
                res = detect_lan_server_host()
                self.assertEqual(res, "192.168.0.22")

    def test_normalize_lan_host(self):
        from platform_utils import normalize_lan_host
        self.assertEqual(normalize_lan_host("192.168.0.22"), "192.168.0.22")
        self.assertEqual(normalize_lan_host("192.168.0.22/Exchange"), "192.168.0.22")
        self.assertEqual(normalize_lan_host("smb://192.168.0.22/Exchange"), "192.168.0.22")
        self.assertEqual(normalize_lan_host(r"\\192.168.0.22\Exchange"), "192.168.0.22")
        self.assertEqual(normalize_lan_host(r"\\192.168.0.22/Exchange\Exchange"), "192.168.0.22")

    def test_format_lan_share_path_mac_and_windows(self):
        from platform_utils import format_lan_share_path
        # macOS testing
        with patch("sys.platform", "darwin"):
            self.assertEqual(format_lan_share_path("192.168.0.22", "Exchange"), "smb://192.168.0.22/Exchange")
            self.assertEqual(format_lan_share_path("192.168.0.22/Exchange", "Exchange"), "smb://192.168.0.22/Exchange")
            self.assertEqual(format_lan_share_path(r"\\192.168.0.22\Exchange", "Exchange"), "smb://192.168.0.22/Exchange")
            self.assertEqual(format_lan_share_path("smb://192.168.0.22/Exchange", "Exchange"), "smb://192.168.0.22/Exchange")

        # Windows testing
        with patch("sys.platform", "win32"):
            self.assertEqual(format_lan_share_path("192.168.0.22", "Exchange"), r"\\192.168.0.22\Exchange")
            self.assertEqual(format_lan_share_path("192.168.0.22/Exchange", "Exchange"), r"\\192.168.0.22\Exchange")
            self.assertEqual(format_lan_share_path("smb://192.168.0.22/Exchange", "Exchange"), r"\\192.168.0.22\Exchange")

    def test_map_network_drive_macos(self):
        from platform_utils import map_network_drive
        with patch("sys.platform", "darwin"):
            with patch("subprocess.run") as mock_sub:
                mock_sub.return_value = MagicMock(returncode=0, stdout="", stderr="")
                with patch("pathlib.Path.is_dir", return_value=False):
                    ok, msg = map_network_drive("192.168.0.22/Exchange")
                    self.assertTrue(ok)
                    self.assertIn("/Volumes/Exchange", msg)


if __name__ == "__main__":
    unittest.main()

