"""
Configuration manager for DropFile.
Supports portable mode (local config.json) or user AppData storage.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

DEFAULT_CONFIG = {
    "server_url": "",
    "username": "",
    "password": "",
    "remote_path": "/DropFile",
    "local_path": str(Path.home() / "Desktop" / "DropFile"),
    "poll_interval": 30,
    "start_with_windows": False,
    "notify_on_sync": True,
    "conflict_action": "keep_both",  # "keep_both" creates conflicted copies
    "ignore_patterns": [
        "~$*",
        "*.tmp",
        "*.crdownload",
        "desktop.ini",
        "Thumbs.db",
        ".dropfile*",
        ".DS_Store",
        "*.swp",
    ],
}


def get_app_dir() -> Path:
    """Returns the directory where application data (config, db, logs) should be stored."""
    # Check if local config.json exists (portable mode)
    script_dir = Path(__file__).resolve().parent
    if (script_dir / "config.json").exists():
        return script_dir

    # Use %APPDATA%/DropFile on Windows or ~/.dropfile on Linux/macOS
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        target = base / "DropFile"
    else:
        target = Path.home() / ".dropfile"

    target.mkdir(parents=True, exist_ok=True)
    return target


class Config:
    def __init__(self, config_dir: Path = None):
        self.config_dir = config_dir or get_app_dir()
        self.config_file = self.config_dir / "config.json"
        self._data: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Loads configuration from file or initializes with defaults."""
        data = dict(DEFAULT_CONFIG)
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    data.update(loaded)
            except Exception as e:
                print(f"[Config] Error loading config, using defaults: {e}")
        self._data = data

    def save(self) -> None:
        """Saves current configuration to file."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[Config] Error saving config: {e}")

    def export_config(self, target_path: Path | str) -> bool:
        """Exports current configuration to a backup JSON file."""
        try:
            target = Path(target_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[Config] Export error: {e}")
            return False

    def import_config(self, source_path: Path | str) -> bool:
        """Imports configuration from a backup JSON file and saves to active config."""
        try:
            source = Path(source_path)
            if not source.exists() or not source.is_file():
                return False
            with open(source, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                return False
            self._data.update(loaded)
            self.save()
            return True
        except Exception as e:
            print(f"[Config] Import error: {e}")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    @property
    def server_url(self) -> str:
        return self._data.get("server_url", "").rstrip("/")

    @server_url.setter
    def server_url(self, value: str) -> None:
        self._data["server_url"] = value.strip().rstrip("/")

    @property
    def username(self) -> str:
        return self._data.get("username", "")

    @username.setter
    def username(self, value: str) -> None:
        self._data["username"] = value.strip()

    @property
    def password(self) -> str:
        return self._data.get("password", "")

    @password.setter
    def password(self, value: str) -> None:
        self._data["password"] = value

    @property
    def remote_path(self) -> str:
        p = self._data.get("remote_path", "/DropFile").strip()
        if not p.startswith("/"):
            p = "/" + p
        return p.rstrip("/")

    @remote_path.setter
    def remote_path(self, value: str) -> None:
        p = value.strip()
        if not p.startswith("/"):
            p = "/" + p
        self._data["remote_path"] = p.rstrip("/")

    @property
    def local_path(self) -> Path:
        return Path(self._data.get("local_path", DEFAULT_CONFIG["local_path"]))

    @local_path.setter
    def local_path(self, value: str | Path) -> None:
        self._data["local_path"] = str(Path(value).resolve())

    @property
    def poll_interval(self) -> int:
        return max(5, int(self._data.get("poll_interval", 30)))

    @poll_interval.setter
    def poll_interval(self, value: int) -> None:
        self._data["poll_interval"] = max(5, int(value))

    @property
    def start_with_windows(self) -> bool:
        return bool(self._data.get("start_with_windows", False))

    @start_with_windows.setter
    def start_with_windows(self, value: bool) -> None:
        self._data["start_with_windows"] = bool(value)

    @property
    def notify_on_sync(self) -> bool:
        return bool(self._data.get("notify_on_sync", True))

    @notify_on_sync.setter
    def notify_on_sync(self, value: bool) -> None:
        self._data["notify_on_sync"] = bool(value)

    @property
    def ignore_patterns(self) -> list:
        return self._data.get("ignore_patterns", DEFAULT_CONFIG["ignore_patterns"])
