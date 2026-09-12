"""
DropFile In-App Auto-Updater.
Supports:
- Checking GitHub Releases for latest versions
- Semantic version comparison
- Automatic update for standalone .exe builds (via background swap helper)
- Automatic update for source/git installations (via git pull)
- Progress reporting and safe application restart
"""

import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple
import urllib.request
import json

from version import __version__
from win_utils import restart_dropfile

GITHUB_REPO = "SaidAuita/DropFile"
API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def parse_version_string(ver_str: str) -> Tuple[int, ...]:
    """Extracts integer tuple from version string like 'v1.05' or '1.05.1' -> (1, 5)."""
    clean = re.sub(r"[^\d.]", "", ver_str)
    parts = []
    for p in clean.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts) if parts else (0,)


def is_remote_newer(remote_tag: str, current_ver: str = __version__) -> bool:
    """Returns True if remote_tag is strictly newer than current_ver."""
    r_tuple = parse_version_string(remote_tag)
    c_tuple = parse_version_string(current_ver)
    # Pad tuples to same length
    max_len = max(len(r_tuple), len(c_tuple))
    r_tuple += (0,) * (max_len - len(r_tuple))
    c_tuple += (0,) * (max_len - len(c_tuple))
    return r_tuple > c_tuple


def check_for_updates(timeout: int = 8) -> Tuple[bool, Dict[str, Any]]:
    """
    Checks GitHub Releases for new updates.
    Returns (has_update, details_dict).
    details_dict contains:
      - 'version': remote version string (e.g. '1.06')
      - 'tag_name': raw tag name ('v1.06')
      - 'title': release name
      - 'notes': release description / changelog
      - 'html_url': browser link
      - 'exe_asset_url': download url for DropFile.exe (if found)
      - 'exe_size': asset size in bytes
      - 'error': error message (if check failed)
    """
    req = urllib.request.Request(
        API_URL,
        headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": f"DropFile-Client/{__version__}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False, {"error": f"HTTP {resp.status}"}
            data = json.loads(resp.read().decode("utf-8"))

        tag_name = data.get("tag_name", "")
        remote_ver = tag_name.lstrip("vV")
        release_notes = data.get("body", "")
        release_title = data.get("name") or f"DropFile v{remote_ver}"
        html_url = data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases")

        # Find .exe asset
        exe_url = None
        exe_size = 0
        for asset in data.get("assets", []):
            name = asset.get("name", "").lower()
            if name == "dropfile.exe" or name.endswith(".exe"):
                exe_url = asset.get("browser_download_url")
                exe_size = asset.get("size", 0)
                break

        newer = is_remote_newer(remote_ver, __version__)

        info = {
            "version": remote_ver,
            "tag_name": tag_name,
            "title": release_title,
            "notes": release_notes,
            "html_url": html_url,
            "exe_asset_url": exe_url,
            "exe_size": exe_size,
        }

        return newer, info

    except urllib.error.HTTPError as e:
        if e.code == 404:
            # No releases published yet
            return False, {"error": "No releases found on GitHub", "not_found": True}
        return False, {"error": f"HTTP error {e.code}: {e.reason}"}
    except Exception as e:
        return False, {"error": str(e)}


def apply_update(
    release_info: Dict[str, Any],
    progress_callback: Optional[Callable[[int], None]] = None,
    on_before_restart: Optional[Callable[[], None]] = None,
) -> Tuple[bool, str]:
    """
    Downloads and installs the update:
    - If running as frozen .exe: downloads new DropFile.exe and launches swap helper batch.
    - If running from source (git): executes 'git pull origin main' and restarts.
    """
    is_frozen = getattr(sys, "frozen", False)

    if is_frozen:
        exe_url = release_info.get("exe_asset_url")
        if not exe_url:
            return False, "Release does not contain DropFile.exe binary."

        current_exe = Path(sys.executable).resolve()
        current_dir = current_exe.parent
        update_temp_exe = current_dir / "DropFile.update.exe"
        swap_bat = current_dir / "apply_update.bat"

        try:
            # Download new executable with progress
            req = urllib.request.Request(
                exe_url,
                headers={"User-Agent": f"DropFile-Client/{__version__}"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                total_size = int(resp.headers.get("content-length", 0))
                downloaded = 0
                chunk_size = 64 * 1024

                with open(update_temp_exe, "wb") as f_out:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f_out.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0 and progress_callback:
                            percent = int(downloaded * 100 / total_size)
                            progress_callback(percent)

            if progress_callback:
                progress_callback(100)

            # Create standalone swap batch script
            bat_script = f"""@echo off
chcp 65001 >nul
set _PYI_PARENT_PROCESS_LEVEL=
set _MEIPASS2=
timeout /t 1 /nobreak >nul
:retry
copy /y "{update_temp_exe.name}" "{current_exe.name}" >nul 2>&1
if errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto retry
)
del /f /q "{update_temp_exe.name}" >nul 2>&1
start "" "{current_exe.name}"
del /f /q "%~f0" >nul 2>&1
"""
            swap_bat.write_text(bat_script, encoding="utf-8")

            # Clean shutdown of current app
            if on_before_restart:
                try:
                    on_before_restart()
                except Exception as e:
                    print(f"[Updater] on_before_restart error: {e}")

            # Spawn swap batch detached and silent with sanitized environment
            flags = 0
            if sys.platform.startswith("win"):
                flags = 0x08000000 | 0x00000008  # CREATE_NO_WINDOW | DETACHED_PROCESS

            env = os.environ.copy()
            for k in list(env.keys()):
                if k.startswith(("_PYI", "PYI", "_MEI")):
                    env.pop(k, None)
            if hasattr(sys, "_MEIPASS"):
                paths = env.get("PATH", "").split(os.pathsep)
                cleaned = [p for p in paths if not p.lower().startswith(sys._MEIPASS.lower())]
                env["PATH"] = os.pathsep.join(cleaned)

            subprocess.Popen(
                ["cmd.exe", "/c", str(swap_bat)],
                cwd=str(current_dir),
                env=env,
                creationflags=flags,
                close_fds=True,
            )

            # Terminate current process immediately
            os._exit(0)

        except Exception as e:
            if update_temp_exe.exists():
                try:
                    update_temp_exe.unlink()
                except Exception:
                    pass
            return False, f"Failed to download update: {e}"

    else:
        # Running from source (git clone)
        repo_dir = Path(__file__).resolve().parent
        git_dir = repo_dir / ".git"

        if git_dir.exists():
            try:
                # Run git pull
                res = subprocess.run(
                    ["git", "-c", "http.proxy=", "-c", "https.proxy=", "pull", "origin", "main"],
                    cwd=str(repo_dir),
                    capture_output=True,
                    text=True,
                    timeout=20,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0,
                )
                if res.returncode != 0:
                    return False, f"git pull error: {res.stderr or res.stdout}"

                if on_before_restart:
                    try:
                        on_before_restart()
                    except Exception:
                        pass

                restart_dropfile()
                os._exit(0)

            except Exception as e:
                return False, f"Git update error: {e}"
        else:
            return False, "Not running as .exe and not a git repository. Please download latest release manually."
