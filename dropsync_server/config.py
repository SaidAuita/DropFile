"""
Configuration manager for DropSync Server.
Supports JSON config files, environment variables, and command-line overrides.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_CONFIG: Dict[str, Any] = {
    "node_name": "node-1",
    "role": "server",  # "server" (listens for incoming connections) or "client" (connects to remote server)
    "sync_dir": str(Path.home() / "DropSyncShare"),
    "listen_host": "0.0.0.0",
    "listen_port": 8443,
    "remote_url": "wss://remote-server:8443",
    "auth_token": "",  # Pre-shared secret key (Bearer token)
    "chunk_size": 1048576,  # 1 MB chunk streaming
    "poll_interval": 0,  # 0 = pure inotify event-driven, >0 = periodic scan interval in seconds as fallback
    "debounce_delay": 1.0,  # Seconds to wait after last write before syncing file
    "ssl_enabled": False,
    "ssl_cert": "",
    "ssl_key": "",
    "ssl_verify": False,  # Useful for self-signed certificates
    "trash_enabled": True,
    "trash_dir": ".dropsync_trash",
    "trash_retention_days": 30,
    "conflict_policy": "keep_both",  # "keep_both" or "newer_wins"
    "ignore_patterns": [
        "~$*",
        "*.tmp",
        "*.crdownload",
        "*.swp",
        ".DS_Store",
        "Thumbs.db",
        "desktop.ini",
        ".dropsync*",
        ".dropfile*",
    ],
}



class Config:
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or self._default_config_path()
        self._data: Dict[str, Any] = dict(DEFAULT_CONFIG)
        self.load()

    @staticmethod
    def _default_config_path() -> Path:
        """Determines config file location (~/.dropsync/dropsync.json or local)."""
        app_dir = Path.home() / ".dropsync"
        app_dir.mkdir(parents=True, exist_ok=True)
        return app_dir / "dropsync.json"

    def load(self) -> None:
        """Loads configuration from JSON file or generates defaults."""
        data = dict(DEFAULT_CONFIG)
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    data.update(loaded)
            except Exception as e:
                print(f"[Config] Error loading {self.config_path}: {e}")
        else:
            # Generate a secure random auth token by default if brand new
            data["auth_token"] = secrets.token_urlsafe(32)

        self._data = data
        self._validate()

    def save(self) -> None:
        """Saves current configuration to file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[Config] Error saving {self.config_path}: {e}")

    def _validate(self) -> None:
        """Validates configuration parameters."""
        # Ensure sync_dir is a Path and exists
        sync_path = Path(self._data.get("sync_dir", DEFAULT_CONFIG["sync_dir"])).expanduser().resolve()
        sync_path.mkdir(parents=True, exist_ok=True)
        self._data["sync_dir"] = str(sync_path)

        if not self._data.get("auth_token"):
            self._data["auth_token"] = secrets.token_urlsafe(32)

    # Properties
    @property
    def node_name(self) -> str:
        return str(self._data.get("node_name", "node-1"))

    @node_name.setter
    def node_name(self, val: str) -> None:
        self._data["node_name"] = str(val)

    @property
    def role(self) -> str:
        return str(self._data.get("role", "server")).lower()

    @role.setter
    def role(self, val: str) -> None:
        self._data["role"] = str(val).lower()

    @property
    def sync_dir(self) -> Path:
        return Path(self._data["sync_dir"])

    @sync_dir.setter
    def sync_dir(self, val: str | Path) -> None:
        p = Path(val).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        self._data["sync_dir"] = str(p)

    @property
    def listen_host(self) -> str:
        return str(self._data.get("listen_host", "0.0.0.0"))

    @property
    def listen_port(self) -> int:
        return int(self._data.get("listen_port", 8443))

    @listen_port.setter
    def listen_port(self, val: int) -> None:
        self._data["listen_port"] = int(val)

    @property
    def remote_url(self) -> str:
        return str(self._data.get("remote_url", ""))

    @remote_url.setter
    def remote_url(self, val: str) -> None:
        self._data["remote_url"] = str(val)

    @property
    def auth_token(self) -> str:
        return str(self._data.get("auth_token", ""))

    @auth_token.setter
    def auth_token(self, val: str) -> None:
        self._data["auth_token"] = str(val)

    @property
    def chunk_size(self) -> int:
        return int(self._data.get("chunk_size", 1048576))

    @property
    def debounce_delay(self) -> float:
        return float(self._data.get("debounce_delay", 1.0))

    @debounce_delay.setter
    def debounce_delay(self, val: float) -> None:
        self._data["debounce_delay"] = float(val)

    @property
    def poll_interval(self) -> int:
        return int(self._data.get("poll_interval", 0))

    @property
    def ssl_enabled(self) -> bool:
        return bool(self._data.get("ssl_enabled", False))

    @property
    def ssl_cert(self) -> str:
        return str(self._data.get("ssl_cert", ""))

    @property
    def ssl_key(self) -> str:
        return str(self._data.get("ssl_key", ""))

    @property
    def ssl_verify(self) -> bool:
        return bool(self._data.get("ssl_verify", False))

    @property
    def trash_enabled(self) -> bool:
        return bool(self._data.get("trash_enabled", True))

    @property
    def trash_dir(self) -> Path:
        return self.sync_dir / str(self._data.get("trash_dir", ".dropsync_trash"))

    @property
    def conflict_policy(self) -> str:
        return str(self._data.get("conflict_policy", "keep_both"))

    @property
    def ignore_patterns(self) -> List[str]:
        return list(self._data.get("ignore_patterns", DEFAULT_CONFIG["ignore_patterns"]))
