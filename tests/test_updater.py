"""
Unit tests for DropFile auto-updater module.
Tests version string parsing, semantic version comparison, and release response handling.
"""

import json
import unittest
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from updater import check_for_updates, is_remote_newer, parse_version_string


class TestUpdater(unittest.TestCase):
    def test_parse_version_string(self):
        self.assertEqual(parse_version_string("1.05"), (1, 5))
        self.assertEqual(parse_version_string("v1.06"), (1, 6))
        self.assertEqual(parse_version_string("v1.05.2"), (1, 5, 2))
        self.assertEqual(parse_version_string("2.0.0"), (2, 0, 0))
        self.assertEqual(parse_version_string("invalid"), (0,))
        self.assertEqual(parse_version_string(""), (0,))

    def test_is_remote_newer(self):
        self.assertTrue(is_remote_newer("1.06", "1.05"))
        self.assertTrue(is_remote_newer("v1.06", "1.05"))
        self.assertTrue(is_remote_newer("1.05.1", "1.05"))
        self.assertTrue(is_remote_newer("2.0", "1.05"))
        self.assertTrue(is_remote_newer("1.10", "1.9"))

        # Same or older
        self.assertFalse(is_remote_newer("1.05", "1.05"))
        self.assertFalse(is_remote_newer("v1.05", "1.05"))
        self.assertFalse(is_remote_newer("1.04", "1.05"))
        self.assertFalse(is_remote_newer("1.05", "1.05.1"))
        self.assertFalse(is_remote_newer("1.04.9", "1.05"))

    @patch("urllib.request.urlopen")
    def test_check_for_updates_available(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_payload = {
            "tag_name": "v99.99",
            "name": "DropFile v99.99 Release",
            "body": "Awesome new features!",
            "html_url": "https://github.com/SaidAuita/DropFile/releases/tag/v99.99",
            "assets": [
                {
                    "name": "DropFile.exe",
                    "browser_download_url": "https://github.com/SaidAuita/DropFile/releases/download/v99.99/DropFile.exe",
                    "size": 12345678,
                }
            ],
        }
        mock_response.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        has_update, info = check_for_updates()
        self.assertTrue(has_update)
        self.assertEqual(info["version"], "99.99")
        self.assertEqual(info["exe_size"], 12345678)
        self.assertTrue(info["exe_asset_url"].endswith("DropFile.exe"))

    @patch("urllib.request.urlopen")
    def test_check_for_updates_no_update(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_payload = {
            "tag_name": "v1.01",
            "name": "Older release",
            "body": "Old notes",
            "html_url": "https://github.com/SaidAuita/DropFile/releases/tag/v1.01",
            "assets": [],
        }
        mock_response.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        has_update, info = check_for_updates()
        self.assertFalse(has_update)
        self.assertEqual(info["version"], "1.01")

    @patch("updater._check_via_git", return_value=None)
    @patch("updater._check_via_web_redirect", return_value=None)
    @patch("updater._check_via_tags_atom", return_value=None)
    @patch("urllib.request.urlopen")
    def test_check_for_updates_404_handled(self, mock_urlopen, mock_atom, mock_web, mock_git):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.github.com/...", code=404, msg="Not Found", hdrs={}, fp=None
        )
        has_update, info = check_for_updates()
        self.assertFalse(has_update)
        self.assertTrue(info.get("not_found"))


if __name__ == "__main__":
    unittest.main()
