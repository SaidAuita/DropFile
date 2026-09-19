"""
Configuration manager for DropFile.
Supports portable mode (local config.json) or user AppData storage.
"""

import json
import os
import socket
import sys
from pathlib import Path
from typing import Any, Dict

DEFAULT_CONFIG = {
    "server_url": "",
    "username": "",
    "password": "",
    "remote_path": "/DropFile",
    "local_path": str(Path.home() / "Desktop" / "DropFile"),
    "exchange_path": str(Path.home() / "Desktop" / "DropFile" / "Exchange"),
    "output_path": str(Path.home() / "Desktop" / "DropFile" / "Output"),
    "output_remote_path": "/Output",
    "auto_copy_share_link": True,
    "backup_server_enabled": False,
    "backup_server_url": "",
    "backup_username": "",
    "backup_password": "",
    "backup_remote_path": "/DropFile",
    "primary_server_index": 1,  # 1 or 2
    "sync_backup_server": False,  # Two-way sync / mirroring between primary and backup servers
    "poll_interval": 30,
    "start_with_windows": False,
    "notify_on_sync": True,
    "desktop_shortcut": True,
    "language": "en",  # Default interface language (10 languages supported)
    "file_retention_days": 30,  # File auto-cleanup in days (0 = disabled)
    "log_retention_days": 30,  # History log retention in days (0 = keep forever)
    "conflict_action": "keep_both",  # "keep_both" creates conflicted copies
    "remote_control_enabled": False,  # Remote control & emergency actions
    "remote_control_device_name": "",  # Name of this PC (defaults to hostname if empty)
    "remote_control_pin": "",  # Secret PIN/password for authenticating commands
    "remote_control_allow_reboot": True,  # Allow remote system reboot
    "remote_control_allow_process_list": True,  # Allow remote process listing
    "remote_control_whitelist": [  # Default whitelisted apps
        "happ.exe",
        "sing-box.exe",
        "v2rayn.exe",
        "telegram.exe",
        "chrome.exe",
    ],
    "remote_control_strict_whitelist": False,  # If True, only whitelist apps can be killed
    "remote_control_allow_launch": True,  # Allow remote launching of pre-defined applications
    "remote_control_launch_apps": [],  # Pre-defined apps: [{"name": "...", "path": "...", "args": "..."}]
    "ignore_patterns": [
        "~$*",
        "*.tmp",
        "*.crdownload",
        "desktop.ini",
        "Thumbs.db",
        ".dropfile*",
        "*dropfile_control*",
        "*dropfile_leader*",
        ".DS_Store",
        "*.swp",
        "speed_server*",
        "Exchange*",
        "exchange*",
    ],
}



def get_app_dir() -> Path:
    """Returns the directory where application data (config, db, logs) should be stored."""
    # Check if local config.json exists (portable mode next to executable or script)
    if getattr(sys, "frozen", False):
        script_dir = Path(sys.executable).resolve().parent
    else:
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
        # Ensure speed_server* and Exchange* are always included in ignore_patterns to isolate DropSync Server
        patterns = data.get("ignore_patterns")
        if isinstance(patterns, list):
            if not any(p in ("speed_server*", "speed_server", "*speed_server*") for p in patterns):
                patterns.append("speed_server*")
            if not any(p in ("Exchange*", "exchange*", "Exchange", "exchange") for p in patterns):
                patterns.append("Exchange*")
            data["ignore_patterns"] = patterns
        self._data = data
        try:
            from i18n import set_current_language
            set_current_language(self.language)
        except Exception:
            pass

    def reset_ignore_patterns(self) -> list:
        """Resets ignore patterns to factory defaults and returns them."""
        defaults = list(DEFAULT_CONFIG["ignore_patterns"])
        self._data["ignore_patterns"] = defaults
        return defaults


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

            # Cross-platform local_path adaptation for seamless PC <-> Mac exchange
            import re
            imported_local = str(loaded.get("local_path", "")).strip()
            if sys.platform == "win32":
                if imported_local.startswith(("/Users/", "/home/", "/Volumes/")) or (imported_local.startswith("/") and not imported_local.startswith("//")):
                    loaded["local_path"] = str(Path.home() / "Desktop" / "DropFile")
            else:
                if re.match(r"^[a-zA-Z]:", imported_local) or "\\" in imported_local:
                    loaded["local_path"] = str(Path.home() / "Desktop" / "DropFile")

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
    def backup_server_enabled(self) -> bool:
        return bool(self._data.get("backup_server_enabled", False))

    @backup_server_enabled.setter
    def backup_server_enabled(self, value: bool) -> None:
        self._data["backup_server_enabled"] = bool(value)

    @property
    def backup_server_url(self) -> str:
        return self._data.get("backup_server_url", "").rstrip("/")

    @backup_server_url.setter
    def backup_server_url(self, value: str) -> None:
        self._data["backup_server_url"] = value.strip().rstrip("/")

    @property
    def backup_username(self) -> str:
        return self._data.get("backup_username", "")

    @backup_username.setter
    def backup_username(self, value: str) -> None:
        self._data["backup_username"] = value.strip()

    @property
    def backup_password(self) -> str:
        return self._data.get("backup_password", "")

    @backup_password.setter
    def backup_password(self, value: str) -> None:
        self._data["backup_password"] = value

    @property
    def backup_remote_path(self) -> str:
        p = self._data.get("backup_remote_path")
        if not p:
            return self.remote_path
        p = str(p).strip()
        if not p.startswith("/"):
            p = "/" + p
        return p.rstrip("/")

    @backup_remote_path.setter
    def backup_remote_path(self, value: str) -> None:
        p = value.strip()
        if not p.startswith("/"):
            p = "/" + p
        self._data["backup_remote_path"] = p.rstrip("/")

    @property
    def primary_server_index(self) -> int:
        idx = int(self._data.get("primary_server_index", 1))
        return 2 if idx == 2 else 1

    @primary_server_index.setter
    def primary_server_index(self, value: int) -> None:
        idx = int(value)
        self._data["primary_server_index"] = 2 if idx == 2 else 1

    @property
    def sync_backup_server(self) -> bool:
        return bool(self._data.get("sync_backup_server", False))

    @sync_backup_server.setter
    def sync_backup_server(self, value: bool) -> None:
        self._data["sync_backup_server"] = bool(value)

    @property
    def local_path(self) -> Path:
        raw = self._data.get("local_path", DEFAULT_CONFIG["local_path"])
        p_str = str(raw).strip()
        import re
        # Cross-platform sanity checks:
        # If running on macOS or Linux and config contains Windows drive letter (e.g. D:\DropFile)
        # fallback to native Desktop/DropFile
        if sys.platform != "win32":
            if re.match(r"^[a-zA-Z]:", p_str) or "\\" in p_str:
                default_path = Path.home() / "Desktop" / "DropFile"
                self._data["local_path"] = str(default_path)
                return default_path
        # If running on Windows and config contains Unix/Mac style path (/Users/..., /home/..., or leading /)
        if sys.platform == "win32":
            if p_str.startswith(("/Users/", "/home/", "/Volumes/")) or (p_str.startswith("/") and not p_str.startswith("//")):
                default_path = Path.home() / "Desktop" / "DropFile"
                self._data["local_path"] = str(default_path)
                return default_path
        return Path(p_str)


    @local_path.setter
    def local_path(self, value: str | Path) -> None:
        p = Path(value).expanduser()
        self._data["local_path"] = str(p.resolve())

    @property
    def exchange_path(self) -> Path:
        raw = self._data.get("exchange_path")
        if not raw:
            p = self.local_path / "Exchange"
            self._data["exchange_path"] = str(p)
            return p
        return Path(str(raw).strip())

    @exchange_path.setter
    def exchange_path(self, value: str | Path) -> None:
        p = Path(value).expanduser()
        self._data["exchange_path"] = str(p.resolve())

    @property
    def output_path(self) -> Path:
        raw = self._data.get("output_path")
        if not raw:
            p = self.local_path / "Output"
            self._data["output_path"] = str(p)
            return p
        return Path(str(raw).strip())

    @output_path.setter
    def output_path(self, value: str | Path) -> None:
        p = Path(value).expanduser()
        self._data["output_path"] = str(p.resolve())

    @property
    def output_remote_path(self) -> str:
        p = str(self._data.get("output_remote_path", "/Output")).strip()
        if not p.startswith("/"):
            p = "/" + p
        return p.rstrip("/") or "/"

    @output_remote_path.setter
    def output_remote_path(self, value: str) -> None:
        p = str(value).strip()
        if not p.startswith("/"):
            p = "/" + p
        self._data["output_remote_path"] = p.rstrip("/") or "/"

    @property
    def auto_copy_share_link(self) -> bool:
        return bool(self._data.get("auto_copy_share_link", True))

    @auto_copy_share_link.setter
    def auto_copy_share_link(self, value: bool) -> None:
        self._data["auto_copy_share_link"] = bool(value)

    def ensure_directories(self) -> None:
        """Ensures that Exchange and Output local directories exist."""
        try:
            self.exchange_path.mkdir(parents=True, exist_ok=True)
            self.output_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"[Config] Error creating directories: {e}")

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

    @property
    def remote_control_enabled(self) -> bool:
        return bool(self._data.get("remote_control_enabled", False))

    @remote_control_enabled.setter
    def remote_control_enabled(self, value: bool) -> None:
        self._data["remote_control_enabled"] = bool(value)

    @property
    def remote_control_device_name(self) -> str:
        val = str(self._data.get("remote_control_device_name", "")).strip()
        if not val:
            try:
                val = socket.gethostname()
            except Exception:
                val = "MyPC"
        return val

    @remote_control_device_name.setter
    def remote_control_device_name(self, value: str) -> None:
        self._data["remote_control_device_name"] = str(value).strip()

    @property
    def remote_control_pin(self) -> str:
        return str(self._data.get("remote_control_pin", "")).strip()

    @remote_control_pin.setter
    def remote_control_pin(self, value: str) -> None:
        self._data["remote_control_pin"] = str(value).strip()

    @property
    def remote_control_allow_reboot(self) -> bool:
        return bool(self._data.get("remote_control_allow_reboot", True))

    @remote_control_allow_reboot.setter
    def remote_control_allow_reboot(self, value: bool) -> None:
        self._data["remote_control_allow_reboot"] = bool(value)

    @property
    def remote_control_allow_process_list(self) -> bool:
        return bool(self._data.get("remote_control_allow_process_list", True))

    @remote_control_allow_process_list.setter
    def remote_control_allow_process_list(self, value: bool) -> None:
        self._data["remote_control_allow_process_list"] = bool(value)

    @property
    def remote_control_whitelist(self) -> list:
        wl = self._data.get("remote_control_whitelist")
        if isinstance(wl, list):
            return wl
        return list(DEFAULT_CONFIG["remote_control_whitelist"])

    @remote_control_whitelist.setter
    def remote_control_whitelist(self, value: list) -> None:
        if isinstance(value, list):
            self._data["remote_control_whitelist"] = [str(x).strip() for x in value if str(x).strip()]
        else:
            self._data["remote_control_whitelist"] = []

    @property
    def remote_control_strict_whitelist(self) -> bool:
        return bool(self._data.get("remote_control_strict_whitelist", False))

    @remote_control_strict_whitelist.setter
    def remote_control_strict_whitelist(self, value: bool) -> None:
        self._data["remote_control_strict_whitelist"] = bool(value)

    @property
    def remote_control_allow_launch(self) -> bool:
        return bool(self._data.get("remote_control_allow_launch", True))

    @remote_control_allow_launch.setter
    def remote_control_allow_launch(self, value: bool) -> None:
        self._data["remote_control_allow_launch"] = bool(value)

    @property
    def remote_control_launch_apps(self) -> list:
        apps = self._data.get("remote_control_launch_apps")
        if isinstance(apps, list):
            return apps
        return []

    @remote_control_launch_apps.setter
    def remote_control_launch_apps(self, value: list) -> None:
        clean = []
        if isinstance(value, list):
            for it in value:
                if isinstance(it, dict):
                    name = str(it.get("name", "")).strip()
                    path = str(it.get("path", "")).strip()
                    args = str(it.get("args", "")).strip()
                    if name and path:
                        clean.append({"name": name, "path": path, "args": args})
        self._data["remote_control_launch_apps"] = clean

