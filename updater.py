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


def _check_via_tags_atom(timeout: int = 8) -> Optional[Tuple[str, str]]:
    """
    Fetches GitHub tags Atom feed (no API rate limits, HTTP 200).
    Returns (tag_name, version_str) or None.
    """
    import xml.etree.ElementTree as ET

    url = f"https://github.com/{GITHUB_REPO}/tags.atom"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"DropFile-Client/{__version__}",
            "Accept": "application/atom+xml, text/xml, */*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            root = ET.fromstring(resp.read())
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        candidates = []
        for entry in root.findall("atom:entry", ns):
            title = entry.find("atom:title", ns)
            if title is not None and title.text:
                tag = title.text.strip()
                m = re.search(r"(?:v|V)?([\d.]+)", tag)
                if m:
                    candidates.append((tag, m.group(1)))
        if candidates:
            candidates.sort(key=lambda item: parse_version_string(item[1]), reverse=True)
            return candidates[0]
    except Exception:
        pass
    return None


def _check_via_web_redirect(timeout: int = 8) -> Optional[Tuple[str, str]]:
    """
    Checks latest release via HTTP 302 redirect from github.com/releases/latest (no API rate limits).
    Returns (tag_name, version_str) or None.
    """
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    url = f"https://github.com/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"DropFile-Client/{__version__}"},
    )
    opener = urllib.request.build_opener(NoRedirect)
    try:
        resp = opener.open(req, timeout=timeout)
        loc = resp.headers.get("Location")
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location")
    except Exception:
        loc = None

    if loc:
        m = re.search(r"/tag/(?:v|V)?([\d.]+)", loc)
        if m:
            tag = loc.split("/")[-1]
            return tag, m.group(1)
    return None


def _check_via_git(repo_dir: Optional[Path] = None, timeout: int = 8) -> Optional[Tuple[str, str]]:
    """
    Checks remote tags using git ls-remote if running from a git clone.
    Returns (tag_name, version_str) or None.
    """
    if repo_dir is None:
        repo_dir = Path(__file__).resolve().parent
    git_dir = repo_dir / ".git"
    if not git_dir.exists():
        return None
    try:
        flags = 0x08000000 if sys.platform.startswith("win") else 0
        res = subprocess.run(
            ["git", "-c", "http.proxy=", "-c", "https.proxy=", "ls-remote", "--tags", "origin"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=flags,
        )
        if res.returncode == 0:
            candidates = []
            for line in res.stdout.splitlines():
                m = re.search(r"refs/tags/((?:v|V)?([\d.]+))(?:[\^]\{\})?$", line.strip())
                if m:
                    raw_tag = m.group(1)
                    v_str = m.group(2)
                    candidates.append((raw_tag, v_str))
            if candidates:
                candidates.sort(key=lambda item: parse_version_string(item[1]), reverse=True)
                return candidates[0]
    except Exception:
        pass
    return None


def check_for_updates(timeout: int = 8) -> Tuple[bool, Dict[str, Any]]:
    """
    Checks GitHub for new updates.
    Uses resilient multi-tier discovery:
    1. GitHub REST API (with asset metadata and changelog)
    2. GitHub Tags Atom Feed (zero rate limits, works without API token)
    3. GitHub Web Redirect (github.com/releases/latest 302 location)
    4. Git Remote Tags (for source/git installations)
    Returns (has_update, details_dict).
    """
    req = urllib.request.Request(
        API_URL,
        headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": f"DropFile-Client/{__version__}",
        },
    )

    is_404 = False
    # Tier 1: GitHub REST API
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                tag_name = data.get("tag_name", "")
                remote_ver = tag_name.lstrip("vV")
                release_notes = data.get("body", "")
                release_title = data.get("name") or f"DropFile v{remote_ver}"
                html_url = data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases")

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
            is_404 = True
            last_error = "No releases found on GitHub"
        else:
            last_error = f"HTTP error {e.code}: {e.reason}"
    except Exception as e:
        last_error = str(e)

    # Tier 2, 3, 4 Fallbacks: Atom Feed, Web 302 Redirect, or Git remote tags
    fallback_res = (
        _check_via_tags_atom(timeout=timeout)
        or _check_via_web_redirect(timeout=timeout)
        or _check_via_git(timeout=timeout)
    )

    if fallback_res:
        tag_name, remote_ver = fallback_res
        newer = is_remote_newer(remote_ver, __version__)
        exe_url = f"https://github.com/{GITHUB_REPO}/releases/download/{tag_name}/DropFile.exe"
        mac_zip_url = f"https://github.com/{GITHUB_REPO}/releases/download/{tag_name}/DropFile-macOS.zip"
        info = {
            "version": remote_ver,
            "tag_name": tag_name,
            "title": f"DropFile v{remote_ver}",
            "notes": f"New update DropFile v{remote_ver} is available on GitHub.",
            "html_url": f"https://github.com/{GITHUB_REPO}/releases/tag/{tag_name}",
            "exe_asset_url": exe_url,
            "mac_asset_url": mac_zip_url,
            "exe_size": 0,
        }
        return newer, info

    res_dict = {"error": last_error or "Unable to check updates"}
    if is_404:
        res_dict["not_found"] = True
    return False, res_dict


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

        # Candidates: direct URL first, then fast proxy mirrors for ISP / DPI circumvention (WinError 10054)
        candidate_urls = [
            exe_url,
            f"https://ghfast.top/{exe_url}",
            f"https://gh-proxy.com/{exe_url}",
        ]

        browser_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "*/*",
        }

        download_success = False
        last_error = ""

        try:
            for candidate in candidate_urls:
                try:
                    print(f"[Updater] Attempting download from: {candidate[:50]}...")
                    try:
                        import requests
                        session = requests.Session()
                        resp = None
                        try:
                            resp = session.get(candidate, headers=browser_headers, stream=True, timeout=15)
                        except Exception:
                            # Fallback without environment proxy in case of proxy tunnel failures
                            session.trust_env = False
                            resp = session.get(candidate, headers=browser_headers, stream=True, timeout=25)

                        if resp.status_code != 200:
                            last_error = f"HTTP {resp.status_code} from {candidate[:35]}"
                            continue

                        total_size = int(resp.headers.get("content-length", 0))
                        downloaded = 0
                        chunk_size = 64 * 1024

                        with open(update_temp_exe, "wb") as f_out:
                            for chunk in resp.iter_content(chunk_size=chunk_size):
                                if chunk:
                                    f_out.write(chunk)
                                    downloaded += len(chunk)
                                    if total_size > 0 and progress_callback:
                                        percent = int(downloaded * 100 / total_size)
                                        progress_callback(min(99, percent))
                    except ImportError:
                        req = urllib.request.Request(candidate, headers=browser_headers)
                        resp = None
                        try:
                            resp = urllib.request.urlopen(req, timeout=15)
                        except Exception:
                            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                            resp = opener.open(req, timeout=25)

                        with resp:
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
                                        progress_callback(min(99, percent))

                    # Verify downloaded file is a valid PE binary (starts with MZ and size > 1MB)
                    if update_temp_exe.exists() and update_temp_exe.stat().st_size > 1000000:
                        with open(update_temp_exe, "rb") as chk:
                            if chk.read(2) == b"MZ":
                                download_success = True
                                print(f"[Updater] Successfully downloaded update ({downloaded} bytes)")
                                break
                            else:
                                last_error = "Downloaded file is corrupted or not a valid Windows executable"
                    else:
                        last_error = "Downloaded file is incomplete"

                except Exception as e:
                    last_error = str(e)
                    print(f"[Updater] Candidate {candidate[:40]} failed: {e}")
                    if update_temp_exe.exists():
                        try:
                            update_temp_exe.unlink()
                        except Exception:
                            pass

            if not download_success:
                return False, f"Failed to download update: {last_error}"

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
                flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0

                # 1. Check if working directory has local changes; stash them to prevent merge conflicts
                status_res = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=str(repo_dir),
                    capture_output=True,
                    text=True,
                    timeout=10,
                    creationflags=flags,
                )
                if status_res.stdout.strip():
                    subprocess.run(
                        ["git", "stash"],
                        cwd=str(repo_dir),
                        capture_output=True,
                        timeout=10,
                        creationflags=flags,
                    )

                # 2. Run git pull
                res = subprocess.run(
                    ["git", "-c", "http.proxy=", "-c", "https.proxy=", "pull", "origin", "main"],
                    cwd=str(repo_dir),
                    capture_output=True,
                    text=True,
                    timeout=30,
                    creationflags=flags,
                )
                if res.returncode != 0:
                    return False, f"git pull error: {res.stderr or res.stdout}"

                # 3. Ensure launcher scripts on macOS have executable permissions
                if sys.platform == "darwin":
                    for cmd_script in repo_dir.glob("*.command"):
                        try:
                            os.chmod(cmd_script, 0o755)
                        except Exception:
                            pass

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
