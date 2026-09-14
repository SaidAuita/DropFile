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
    "desktop_shortcut": True,
    "language": "en",  # Default interface language (10 languages supported)
    "file_retention_days": 30,  # File auto-cleanup in days (0 = disabled)
    "log_retention_days": 30,  # History log retention in days (0 = keep forever)
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

    # Use %APPDATA%/DropFile on Windows, ~/Library/Application Support/DropFile on macOS, or ~/.dropfile on Linux
    if sys.platform == "darwin":
        target = Path.home() / "Library" / "Application Support" / "DropFile"
    elif sys.platform.startswith("win"):
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
        try:
            from i18n import set_current_language
            set_current_language(self.language)
        except Exception:
            pass

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
        raw = self._data.get("local_path", DEFAULT_CONFIG["local_path"])
        p_str = str(raw).strip()
        # If running on macOS or Linux and config contains Windows drive letter (e.g. D:\DropFile)
        # fallback to native Desktop/DropFile
        if sys.platform != "win32":
            import re
            if re.match(r"^[a-zA-Z]:", p_str) or "\\" in p_str:
                default_path = Path.home() / "Desktop" / "DropFile"
                self._data["local_path"] = str(default_path)
                return default_path
        return Path(p_str)

    @local_path.setter
    def local_path(self, value: str | Path) -> None:
        p = Path(value).expanduser()
        self._data["local_path"] = str(p.resolve())

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
    def file_retention_days(self) -> int:
        return int(self._data.get("file_retention_days", 30))

    @file_retention_days.setter
    def file_retention_days(self, value: int) -> None:
        self._data["file_retention_days"] = max(0, int(value))

    @property
    def log_retention_days(self) -> int:
        return int(self._data.get("log_retention_days", 30))

    @log_retention_days.setter
    def log_retention_days(self, value: int) -> None:
        self._data["log_retention_days"] = max(0, int(value))

    @property
    def language(self) -> str:
        return self._data.get("language", "en")

    @language.setter
    def language(self, value: str) -> None:
        val = str(value).strip().lower()
        self._data["language"] = val
        try:
            from i18n import set_current_language
            set_current_language(val)
        except Exception:
            pass

    @property
    def ignore_patterns(self) -> list:
        return self._data.get("ignore_patterns", DEFAULT_CONFIG["ignore_patterns"])

    @property
    def conflict_action(self) -> str:
        return self._data.get("conflict_action", "keep_both")

    @conflict_action.setter
    def conflict_action(self, value: str) -> None:
        val = str(value).strip().lower()
        if val in ("keep_both", "newer_wins"):
            self._data["conflict_action"] = val
        else:
            self._data["conflict_action"] = "keep_both"

    @property
    def desktop_shortcut(self) -> bool:
        return bool(self._data.get("desktop_shortcut", True))

    @desktop_shortcut.setter
    def desktop_shortcut(self, value: bool) -> None:
        self._data["desktop_shortcut"] = bool(value)

