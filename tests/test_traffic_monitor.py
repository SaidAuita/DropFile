"""
Unit tests for DropFile TrafficMonitor, Speed Chart metrics, and LAN Share utilities.
"""

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from traffic_monitor import (
    TrafficMonitor,
    format_bytes,
    format_speed,
    get_current_speeds_bps,
    get_history,
    get_totals,
    record_rx,
    record_tx,
)
from platform_utils import (
    create_network_shortcut,
    get_available_drive_letters,
    map_network_drive,
)


class TestTrafficMonitor(unittest.TestCase):
    def setUp(self):
        self.mon = TrafficMonitor(history_seconds=10)

    def test_record_and_totals(self):
        self.mon.record_rx(1024)
        self.mon.record_rx(2048)
        self.mon.record_tx(4096)

        tot_rx, tot_tx = self.mon.get_totals()
        self.assertEqual(tot_rx, 3072)
        self.assertEqual(tot_tx, 4096)

    def test_speed_calculation(self):
        # Record 10,000 bytes RX and 5,000 bytes TX
        self.mon.record_rx(10_000)
        self.mon.record_tx(5_000)

        rx_bps, tx_bps = self.mon.get_current_speeds_bps()
        # In this 1-second bucket, 10,000 bytes = 80,000 bps
        self.assertGreater(rx_bps, 0)
        self.assertGreater(tx_bps, 0)
        self.assertAlmostEqual(rx_bps, 80_000, delta=1000)
        self.assertAlmostEqual(tx_bps, 40_000, delta=1000)

    def test_history_length_and_structure(self):
        for _ in range(5):
            self.mon.record_rx(500)
            self.mon.record_tx(250)
            time.sleep(0.01)

        history = self.mon.get_history(seconds=10)
        self.assertEqual(len(history), 10)
        # Each entry is (rx_bps, tx_bps, timestamp)
        for rx, tx, ts in history:
            self.assertIsInstance(rx, float)
            self.assertIsInstance(tx, float)
            self.assertIsInstance(ts, float)

    def test_format_speed_ru_and_en(self):
        # 0 bps
        self.assertEqual(format_speed(0, lang="ru"), "0 бит/с")
        self.assertEqual(format_speed(0, lang="en"), "0 bps")

        # 500 kbps
        self.assertIn("кбит/с", format_speed(500_000, lang="ru"))
        self.assertIn("kbps", format_speed(500_000, lang="en"))

        # 2.5 Mbps
        self.assertIn("Мбит/с", format_speed(2_500_000, lang="ru"))
        self.assertIn("Mbps", format_speed(2_500_000, lang="en"))

        # 1.2 Gbps
        self.assertIn("Гбит/с", format_speed(1_200_000_000, lang="ru"))
        self.assertIn("Gbps", format_speed(1_200_000_000, lang="en"))

    def test_format_bytes_ru_and_en(self):
        self.assertEqual(format_bytes(500, lang="ru"), "500 Б")
        self.assertEqual(format_bytes(500, lang="en"), "500 B")

        self.assertIn("КБ", format_bytes(50_000, lang="ru"))
        self.assertIn("KB", format_bytes(50_000, lang="en"))

        self.assertIn("МБ", format_bytes(50_000_000, lang="ru"))
        self.assertIn("MB", format_bytes(50_000_000, lang="en"))

        self.assertIn("ГБ", format_bytes(5_000_000_000, lang="ru"))
        self.assertIn("GB", format_bytes(5_000_000_000, lang="en"))

    def test_global_singleton_convenience_functions(self):
        record_rx(100)
        record_tx(200)
        tot_rx, tot_tx = get_totals()
        self.assertGreaterEqual(tot_rx, 100)
        self.assertGreaterEqual(tot_tx, 200)
        speeds = get_current_speeds_bps()
        self.assertEqual(len(speeds), 2)

    def test_format_eta(self):
        from traffic_monitor import format_eta
        # None and negative
        self.assertEqual(format_eta(None, "ru"), "—")
        self.assertEqual(format_eta(-1, "ru"), "—")
        # 0 seconds
        self.assertEqual(format_eta(0, "ru"), "< 1 сек")
        self.assertEqual(format_eta(0, "en"), "< 1s")
        # Under a minute
        self.assertEqual(format_eta(45, "ru"), "~45 сек")
        self.assertEqual(format_eta(45, "en"), "~45s")
        # Minutes and seconds
        self.assertEqual(format_eta(75, "ru"), "~1 мин 15 сек")
        self.assertEqual(format_eta(75, "en"), "~1m 15s")
        # Minutes only
        self.assertEqual(format_eta(120, "ru"), "~2 мин")
        self.assertEqual(format_eta(120, "en"), "~2m")
        # Hours
        self.assertEqual(format_eta(3665, "ru"), "~1 ч 1 мин")
        self.assertEqual(format_eta(3665, "en"), "~1h 1m")

    def test_client_transfer_helpers(self):
        from traffic_monitor import get_client_transfer, set_client_transfer
        set_client_transfer(None)
        self.assertIsNone(get_client_transfer())
        sample = {
            "direction": "tx",
            "file_name": "video.mp4",
            "total_bytes": 1000,
            "transferred_bytes": 250,
            "percent": 25.0,
            "eta_seconds": 15,
        }
        set_client_transfer(sample)
        self.assertEqual(get_client_transfer(), sample)
        set_client_transfer(None)



class TestLanShareUtilities(unittest.TestCase):
    def test_get_available_drive_letters(self):
        letters = get_available_drive_letters()
        self.assertIsInstance(letters, list)
        # Should contain uppercase single letters
        for letter in letters:
            self.assertEqual(len(letter), 1)
            self.assertTrue(letter.isupper())
            # Free letter should not be an active drive
            self.assertFalse(os.path.exists(f"{letter}:\\"))

    @patch("platform_utils.os.path.exists", return_value=False)
    @patch("platform_utils.subprocess.run")
    def test_map_network_drive_success(self, mock_run, mock_exists):
        mock_run.return_value = MagicMock(returncode=0, stdout="The command completed successfully.")
        ok, msg = map_network_drive(r"\\192.168.1.4\DropSync", drive_letter="Z")
        self.assertTrue(ok)
        self.assertIn("Z:", msg)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("net", cmd)
        self.assertIn("use", cmd)
        self.assertIn("Z:", cmd)
        self.assertIn(r"\\192.168.1.4\DropSync", cmd)

    @patch("platform_utils.os.path.exists", return_value=False)
    @patch("platform_utils.subprocess.run")
    def test_map_network_drive_failure(self, mock_run, mock_exists):
        mock_run.return_value = MagicMock(returncode=2, stderr="System error 67 has occurred. The network name cannot be found.")
        ok, msg = map_network_drive(r"\\invalid_server\Share", drive_letter="Y")
        self.assertFalse(ok)
        self.assertIn("System error 67", msg)

    def test_create_network_shortcut_signature(self):
        # On non-Windows or without pywin32, it falls back to PowerShell or URL file
        # We test with a dry mock or execution
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            ok, msg = create_network_shortcut(r"\\192.168.1.4\Exchange", "Test Shortcut")
            self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
