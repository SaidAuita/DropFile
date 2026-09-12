"""
Unit tests for FileBrowser Client logic and parsing.
"""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fb_client import FileBrowserClient, RemoteItem


class TestFBClient(unittest.TestCase):
    def setUp(self):
        self.client = FileBrowserClient(base_url="https://example.com:8080/files")

    def test_encode_path(self):
        p1 = self.client._encode_path("/Exchange/My Folder/File #1.txt")
        self.assertEqual(p1, "/Exchange/My%20Folder/File%20%231.txt")

        p2 = self.client._encode_path("Exchange/test.pdf")
        self.assertEqual(p2, "/Exchange/test.pdf")

        p3 = self.client._encode_path("/")
        self.assertEqual(p3, "/")

    def test_parse_recursive_items(self):
        mock_tree = {
            "path": "/Exchange",
            "name": "Exchange",
            "isDir": True,
            "items": [
                {
                    "path": "/Exchange/sub",
                    "name": "sub",
                    "isDir": True,
                    "items": [
                        {
                            "path": "/Exchange/sub/doc.txt",
                            "name": "doc.txt",
                            "size": 100,
                            "modified": "2026-09-12T00:00:00Z",
                            "isDir": False,
                        }
                    ],
                },
                {
                    "path": "/Exchange/photo.jpg",
                    "name": "photo.jpg",
                    "size": 5000,
                    "modified": "2026-09-12T01:00:00Z",
                    "isDir": False,
                },
            ],
        }

        items = []
        self.client._parse_items_recursive(mock_tree, items)
        self.assertEqual(len(items), 3)

        paths = [it.path for it in items]
        self.assertIn("/Exchange/sub", paths)
        self.assertIn("/Exchange/sub/doc.txt", paths)
        self.assertIn("/Exchange/photo.jpg", paths)


if __name__ == "__main__":
    unittest.main()
