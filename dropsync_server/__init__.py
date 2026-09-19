"""
DropSync Server — High-Performance Linux-to-Linux Bi-Directional File Synchronization Daemon.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__version__ = "1.0.0"
__build__ = "88"
__author__ = "SaidAuita"


def get_default_config_path() -> Path:
    """Returns ~/.dropsync/dropsync.json (or local if configured)."""
    app_dir = Path.home() / ".dropsync"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir / "dropsync.json"


def load_dropsync_config(custom_path: Optional[Path] = None) -> Dict[str, Any]:
    """Loads configuration dictionary or default template."""
    from .config import DEFAULT_CONFIG
    cfg_file = custom_path or get_default_config_path()
    data = dict(DEFAULT_CONFIG)
    if cfg_file.exists():
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                data.update(loaded)
        except Exception as e:
            print(f"[DropSync] Error reading {cfg_file}: {e}")
    return data


def save_dropsync_config(data: Dict[str, Any], custom_path: Optional[Path] = None) -> bool:
    """Saves configuration dictionary to file."""
    cfg_file = custom_path or get_default_config_path()
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[DropSync] Error saving {cfg_file}: {e}")
        return False


def get_service_status() -> Dict[str, Any]:
    """
    Checks systemd service status on Linux, or local process status.
    Returns: {
        'platform': str,
        'installed': bool,
        'active': bool,
        'status_label': str,
        'sub_text': str
    }
    """
    is_linux = sys.platform.startswith("linux")
    result = {
        "platform": sys.platform,
        "installed": False,
        "active": False,
        "status_label": "Unknown",
        "sub_text": "",
    }

    if not is_linux:
        result["status_label"] = "Windows / macOS"
        result["sub_text"] = "GUI Mode / Standalone"
        return result

    # Check system systemd service
    try:
        res = subprocess.run(
            ["systemctl", "is-active", "dropsync.service"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        status_out = res.stdout.strip()
        if status_out == "active":
            result["installed"] = True
            result["active"] = True
            result["status_label"] = "🟢 Active (Running 24/7)"
            result["sub_text"] = "systemd: dropsync.service"
            return result
        elif status_out in ("inactive", "failed", "deactivating"):
            result["installed"] = True
            result["active"] = False
            result["status_label"] = f"🔴 Stopped ({status_out})"
            result["sub_text"] = "systemd: dropsync.service"
            return result
    except Exception:
        pass

    # Check user systemd service
    try:
        res = subprocess.run(
            ["systemctl", "--user", "is-active", "dropsync.service"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        status_out = res.stdout.strip()
        if status_out == "active":
            result["installed"] = True
            result["active"] = True
            result["status_label"] = "🟢 Active (User session)"
            result["sub_text"] = "systemd --user: dropsync.service"
            return result
    except Exception:
        pass

    result["installed"] = False
    result["active"] = False
    result["status_label"] = "⚪ Service not installed"
    result["sub_text"] = "Run with python3 -m dropsync_server.main"
    return result


def control_service(action: str) -> Tuple[bool, str]:
    """
    Executes service action: restart, start, stop.
    Returns (success, message).
    """
    if action not in ("restart", "start", "stop"):
        return False, f"Invalid action: {action}"

    if not sys.platform.startswith("linux"):
        return False, "systemd service control is only available on Linux"

    # Try systemctl
    try:
        res = subprocess.run(
            ["systemctl", action, "dropsync.service"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            return True, f"Service {action} successful"
        
        # If permission denied, try pkexec or sudo if available
        err_msg = res.stderr.strip() or res.stdout.strip()
        if "Access denied" in err_msg or "interactive authentication" in err_msg or res.returncode != 0:
            # Try pkexec or user systemd
            user_res = subprocess.run(
                ["systemctl", "--user", action, "dropsync.service"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if user_res.returncode == 0:
                return True, f"User service {action} successful"
            return False, f"Systemd error: {err_msg}"
    except Exception as e:
        return False, f"Failed to execute command: {e}"

    return True, f"Service {action} completed"


def get_state_summary(sync_dir_path: Optional[Path | str] = None) -> Dict[str, Any]:
    """
    Reads local state.db for the given sync directory.
    Returns counts and recent sync logs.
    """
    summary: Dict[str, Any] = {
        "active_files": 0,
        "trash_files": 0,
        "logs": [],
        "db_found": False,
    }

    if not sync_dir_path:
        cfg = load_dropsync_config()
        sync_dir_path = cfg.get("sync_dir", "")

    if not sync_dir_path:
        return summary

    sync_path = Path(sync_dir_path).expanduser().resolve()
    db_file = sync_path / ".dropsync" / "state.db"
    if not db_file.exists():
        return summary

    try:
        from .state_db import StateDatabase
        db = StateDatabase(db_file)
        manifest = db.get_manifest()
        summary["active_files"] = sum(1 for f in manifest.values() if not f.get("deleted", 0))
        summary["trash_files"] = sum(1 for f in manifest.values() if f.get("deleted", 0))
        summary["logs"] = db.get_recent_logs(limit=25)
        summary["db_found"] = True
    except Exception as e:
        print(f"[DropSync] Error reading state db: {e}")

    return summary
