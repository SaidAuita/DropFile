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
import zipfile
import tempfile
import shutil

from version import __version__
from platform_utils import restart_dropfile

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
                mac_url = None
                mac_size = 0
                for asset in data.get("assets", []):
                    name = asset.get("name", "").lower()
                    if name == "dropfile.exe" or name.endswith(".exe"):
                        exe_url = asset.get("browser_download_url")
                        exe_size = asset.get("size", 0)
                    elif ("mac" in name or "darwin" in name) and name.endswith(".zip"):
                        mac_url = asset.get("browser_download_url")
                        mac_size = asset.get("size", 0)

                newer = is_remote_newer(remote_ver, __version__)
                info = {
                    "version": remote_ver,
                    "tag_name": tag_name,
                    "title": release_title,
                    "notes": release_notes,
                    "html_url": html_url,
                    "exe_asset_url": exe_url,
                    "exe_size": exe_size,
                    "mac_asset_url": mac_url,
                    "mac_size": mac_size,
                    "source_zip_url": f"https://github.com/{GITHUB_REPO}/archive/refs/tags/{tag_name}.zip",
                }
                if newer:
                    return True, info

                # Check if there is a newer tag than the latest release
                fallback_res = _check_via_tags_atom(timeout=timeout) or _check_via_git(timeout=timeout)
                if fallback_res:
                    fb_tag, fb_ver = fallback_res
                    if is_remote_newer(fb_ver, remote_ver) and is_remote_newer(fb_ver, __version__):
                        return True, {
                            "version": fb_ver,
                            "tag_name": fb_tag,
                            "title": f"DropFile v{fb_ver}",
                            "notes": f"New update DropFile v{fb_ver} is available on GitHub.",
                            "html_url": f"https://github.com/{GITHUB_REPO}/releases/tag/{fb_tag}",
                            "exe_asset_url": f"https://github.com/{GITHUB_REPO}/releases/download/{fb_tag}/DropFile.exe",
                            "mac_asset_url": f"https://github.com/{GITHUB_REPO}/releases/download/{fb_tag}/DropFile-macOS.zip",
                            "source_zip_url": f"https://github.com/{GITHUB_REPO}/archive/refs/tags/{fb_tag}.zip",
                            "exe_size": 0,
                            "mac_size": 0,
                        }

                return False, info
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
        source_zip = f"https://github.com/{GITHUB_REPO}/archive/refs/tags/{tag_name}.zip"
        info = {
            "version": remote_ver,
            "tag_name": tag_name,
            "title": f"DropFile v{remote_ver}",
            "notes": f"New update DropFile v{remote_ver} is available on GitHub.",
            "html_url": f"https://github.com/{GITHUB_REPO}/releases/tag/{tag_name}",
            "exe_asset_url": exe_url,
            "mac_asset_url": mac_zip_url,
            "source_zip_url": source_zip,
            "exe_size": 0,
            "mac_size": 0,
        }
        return newer, info

    res_dict = {"error": last_error or "Unable to check updates"}
    if is_404:
        res_dict["not_found"] = True
    return False, res_dict


def _download_file_with_progress(
    candidate_urls: list,
    dest_path: Path,
    progress_callback: Optional[Callable[[int], None]] = None,
    min_size: int = 1024,
    header_check: Optional[bytes] = None,
) -> Tuple[bool, str]:
    """Downloads a file from candidate URLs with progress tracking and validation."""
    browser_headers = {
        "User-Agent": f"Mozilla/5.0 DropFile/{__version__} (compatible)",
        "Accept": "*/*",
    }
    chunk_size = 128 * 1024
    last_error = ""

    for candidate in candidate_urls:
        if not candidate:
            continue
        try:
            print(f"[Updater] Attempting download from: {candidate[:50]}...")
            downloaded = 0
            total_size = 0
            stream_opened = False

            try:
                import requests
                session = requests.Session()
                resp = None
                for trust_env in [True, False]:
                    session.trust_env = trust_env
                    try:
                        resp = session.get(
                            candidate,
                            headers=browser_headers,
                            stream=True,
                            timeout=(5, 15),
                        )
                        if resp.status_code == 200:
                            stream_opened = True
                            break
                    except Exception:
                        continue

                if stream_opened and resp is not None:
                    total_size = int(resp.headers.get("content-length", 0))
                    with open(dest_path, "wb") as f_out:
                        for chunk in resp.iter_content(chunk_size=chunk_size):
                            if chunk:
                                f_out.write(chunk)
                                downloaded += len(chunk)
                                if total_size > 0 and progress_callback:
                                    percent = int(downloaded * 100 / total_size)
                                    progress_callback(min(99, percent))
                else:
                    code_str = resp.status_code if resp else "timeout"
                    last_error = f"HTTP {code_str} from {candidate[:35]}"
                    continue

            except ImportError:
                req = urllib.request.Request(candidate, headers=browser_headers)
                resp = None
                try:
                    resp = urllib.request.urlopen(req, timeout=12)
                except Exception:
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    resp = opener.open(req, timeout=15)

                with resp:
                    total_size = int(resp.headers.get("content-length", 0))
                    with open(dest_path, "wb") as f_out:
                        while True:
                            chunk = resp.read(chunk_size)
                            if not chunk:
                                break
                            f_out.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0 and progress_callback:
                                percent = int(downloaded * 100 / total_size)
                                progress_callback(min(99, percent))

            # Validate size and file signature
            if dest_path.exists() and dest_path.stat().st_size >= min_size:
                if header_check:
                    with open(dest_path, "rb") as chk:
                        magic = chk.read(len(header_check))
                        if magic != header_check:
                            last_error = f"Invalid file signature (expected {header_check.hex()})"
                            dest_path.unlink(missing_ok=True)
                            continue
                print(f"[Updater] Download verified ({dest_path.stat().st_size} bytes)")
                return True, ""
            else:
                last_error = "Downloaded file is incomplete or too small"
                dest_path.unlink(missing_ok=True)

        except Exception as e:
            last_error = str(e)
            print(f"[Updater] Candidate {candidate[:40]} failed: {e}")
            dest_path.unlink(missing_ok=True)

    return False, last_error or "All download candidates failed"


def _apply_update_windows_exe(
    release_info: Dict[str, Any],
    progress_callback: Optional[Callable[[int], None]] = None,
    on_before_restart: Optional[Callable[[], None]] = None,
) -> Tuple[bool, str]:
    """Updates standalone DropFile.exe on Windows via helper batch script."""
    exe_url = release_info.get("exe_asset_url")
    if not exe_url:
        return False, "Release does not contain DropFile.exe binary."

    current_exe = Path(sys.executable).resolve()
    current_dir = current_exe.parent
    update_temp_exe = current_dir / "DropFile.update.exe"
    swap_bat = current_dir / "apply_update.bat"

    candidate_urls = [
        f"https://gh-proxy.com/{exe_url}",
        f"https://ghproxy.net/{exe_url}",
        f"https://gh.ddlc.top/{exe_url}",
        exe_url,
    ]

    ok, err = _download_file_with_progress(
        candidate_urls,
        update_temp_exe,
        progress_callback=progress_callback,
        min_size=1000000,
        header_check=b"MZ",
    )
    if not ok:
        return False, f"Failed to download update: {err}"

    if progress_callback:
        progress_callback(100)

    bat_script = f"""@echo off
chcp 65001 >nul
set _PYI_PARENT_PROCESS_LEVEL=
set _MEIPASS2=
taskkill /f /im DropFile.exe >nul 2>&1
timeout /t 1 /nobreak >nul
:retry
copy /y "{update_temp_exe.name}" "{current_exe.name}" >nul 2>&1
if errorlevel 1 (
    taskkill /f /im DropFile.exe >nul 2>&1
    timeout /t 1 /nobreak >nul
    goto retry
)
del /f /q "{update_temp_exe.name}" >nul 2>&1
start "" "{current_exe.name}"
del /f /q "%~f0" >nul 2>&1
"""
    swap_bat.write_text(bat_script, encoding="utf-8")

    if on_before_restart:
        try:
            on_before_restart()
        except Exception as e:
            print(f"[Updater] on_before_restart error: {e}")

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
    os._exit(0)


def _apply_update_via_git(
    repo_dir: Path,
    on_before_restart: Optional[Callable[[], None]] = None,
) -> Tuple[bool, str]:
    """Updates repository via 'git pull origin main'."""
    try:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0

        # 1. Stash changes if any
        status_res = subprocess.run(
            ["git", "-c", "core.fileMode=false", "status", "--porcelain"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=flags,
        )
        if status_res.stdout.strip():
            subprocess.run(
                ["git", "-c", "core.fileMode=false", "stash"],
                cwd=str(repo_dir),
                capture_output=True,
                timeout=10,
                creationflags=flags,
            )

        # 2. Pull latest main branch
        res = subprocess.run(
            ["git", "-c", "core.fileMode=false", "-c", "http.proxy=", "-c", "https.proxy=", "pull", "origin", "main"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=flags,
        )
        if res.returncode != 0:
            return False, f"git pull error: {res.stderr or res.stdout}"

        # 3. Ensure permissions on macOS / Linux
        if sys.platform == "darwin" or sys.platform.startswith("linux"):
            for cmd_script in repo_dir.glob("*.command"):
                try:
                    os.chmod(cmd_script, 0o755)
                except Exception:
                    pass
            for py_script in repo_dir.glob("*.py*"):
                try:
                    os.chmod(py_script, 0o755)
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


def _apply_update_via_source_zip(
    repo_dir: Path,
    release_info: Dict[str, Any],
    progress_callback: Optional[Callable[[int], None]] = None,
    on_before_restart: Optional[Callable[[], None]] = None,
) -> Tuple[bool, str]:
    """Downloads source code archive from GitHub and updates project files."""
    tag = release_info.get("tag_name") or f"v{release_info.get('version', '')}"
    zip_url = release_info.get("source_zip_url") or f"https://github.com/{GITHUB_REPO}/archive/refs/tags/{tag}.zip"
    main_url = f"https://github.com/{GITHUB_REPO}/archive/refs/heads/main.zip"

    candidate_urls = [
        f"https://gh-proxy.com/{zip_url}",
        f"https://ghproxy.net/{zip_url}",
        f"https://gh.ddlc.top/{zip_url}",
        zip_url,
        f"https://gh-proxy.com/{main_url}",
        main_url,
    ]

    with tempfile.TemporaryDirectory() as tmp_dir:
        temp_zip = Path(tmp_dir) / "update_source.zip"
        ok, err = _download_file_with_progress(
            candidate_urls,
            temp_zip,
            progress_callback=progress_callback,
            min_size=10240,
            header_check=b"PK",
        )
        if not ok:
            return False, f"Failed to download update archive: {err}"

        if progress_callback:
            progress_callback(100)

        try:
            with zipfile.ZipFile(temp_zip, "r") as zf:
                namelist = zf.namelist()
                if not namelist:
                    return False, "Downloaded update archive is empty."

                # GitHub source zip has a root folder: e.g. DropFile-1.17/ or DropFile-main/
                top_dir = namelist[0].split("/")[0] if "/" in namelist[0] else ""
                prefix = f"{top_dir}/" if top_dir else ""

                protected = {
                    "config.json",
                    "config.local.json",
                    "state.db",
                    "state.db-journal",
                    "state.db-wal",
                    "state.db-shm",
                }

                for member in namelist:
                    if member.endswith("/"):
                        continue
                    rel_name = member[len(prefix):] if member.startswith(prefix) else member
                    if not rel_name:
                        continue

                    # Don't overwrite configuration, databases, logs or virtualenvs
                    if rel_name in protected or rel_name.startswith((".git/", ".venv/", "venv/", "logs/")):
                        continue

                    target_file = repo_dir / rel_name
                    target_file.parent.mkdir(parents=True, exist_ok=True)

                    with zf.open(member) as src, open(target_file, "wb") as dst:
                        dst.write(src.read())

                    if rel_name.endswith((".command", ".sh", ".pyw")):
                        try:
                            os.chmod(target_file, 0o755)
                        except Exception:
                            pass

        except Exception as e:
            return False, f"Error extracting update archive: {e}"

        if on_before_restart:
            try:
                on_before_restart()
            except Exception:
                pass

        restart_dropfile()
        os._exit(0)


def _apply_update_macos(
    release_info: Dict[str, Any],
    progress_callback: Optional[Callable[[int], None]] = None,
    on_before_restart: Optional[Callable[[], None]] = None,
) -> Tuple[bool, str]:
    """macOS updater handling git repo, source zip, or native .app bundle without cmd.exe."""
    is_frozen = getattr(sys, "frozen", False)
    repo_dir = Path(__file__).resolve().parent

    # 1. Check if git repository exists in repo_dir or parent directories
    if (repo_dir / ".git").is_dir():
        return _apply_update_via_git(repo_dir, on_before_restart)

    for parent in list(repo_dir.parents)[:3]:
        if (parent / ".git").is_dir():
            return _apply_update_via_git(parent, on_before_restart)

    # 2. Check if running inside a macOS .app bundle
    app_bundle = None
    for p in [repo_dir] + list(Path(sys.executable).parents):
        if p.suffix == ".app":
            app_bundle = p
            break

    mac_asset_url = release_info.get("mac_asset_url")
    if is_frozen and app_bundle and mac_asset_url:
        candidate_urls = [
            f"https://gh-proxy.com/{mac_asset_url}",
            f"https://ghproxy.net/{mac_asset_url}",
            f"https://gh.ddlc.top/{mac_asset_url}",
            mac_asset_url,
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_zip = Path(tmp_dir) / "DropFile-macOS.zip"
            ok, err = _download_file_with_progress(
                candidate_urls,
                temp_zip,
                progress_callback=progress_callback,
                min_size=10240,
                header_check=b"PK",
            )
            if not ok:
                return False, f"Failed to download macOS bundle update: {err}"

            if progress_callback:
                progress_callback(100)

            # Unpack into temp directory
            extract_dir = Path(tmp_dir) / "extracted"
            extract_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(temp_zip, "r") as zf:
                zf.extractall(extract_dir)

            new_app = None
            if (extract_dir / "DropFile.app").exists():
                new_app = extract_dir / "DropFile.app"
            else:
                for f in extract_dir.glob("**/DropFile.app"):
                    new_app = f
                    break

            if not new_app:
                return False, "Downloaded macOS archive does not contain DropFile.app"

            # Create standalone bash swap script
            swap_sh = Path(tmp_dir) / "apply_mac_update.sh"
            swap_content = f"""#!/bin/bash
sleep 1
rm -rf "{app_bundle}"
cp -R "{new_app}" "{app_bundle}"
chmod -R 755 "{app_bundle}"
xattr -cr "{app_bundle}" 2>/dev/null || true
open -n "{app_bundle}"
rm -f "$0"
"""
            swap_sh.write_text(swap_content, encoding="utf-8")
            os.chmod(swap_sh, 0o755)

            if on_before_restart:
                try:
                    on_before_restart()
                except Exception:
                    pass

            subprocess.Popen(["/bin/bash", str(swap_sh)], close_fds=True)
            os._exit(0)

    # 3. If bundle has embedded python app directory (Contents/Resources/app):
    if app_bundle and (app_bundle / "Contents" / "Resources" / "app").exists():
        app_code_dir = app_bundle / "Contents" / "Resources" / "app"
        return _apply_update_via_source_zip(app_code_dir, release_info, progress_callback, on_before_restart)

    # 4. Standard source update
    return _apply_update_from_source(release_info, progress_callback, on_before_restart)


def _apply_update_from_source(
    release_info: Dict[str, Any],
    progress_callback: Optional[Callable[[int], None]] = None,
    on_before_restart: Optional[Callable[[], None]] = None,
) -> Tuple[bool, str]:
    """Updates non-frozen source installations (via Git pull or GitHub source zip)."""
    repo_dir = Path(__file__).resolve().parent

    # If repo_dir does not contain DropFile.pyw, search nearby
    if not (repo_dir / "DropFile.pyw").exists():
        for cand in [Path.cwd(), Path(sys.executable).parent, Path(sys.executable).parent.parent]:
            if (cand / "DropFile.pyw").exists():
                repo_dir = cand
                break

    if (repo_dir / ".git").is_dir():
        return _apply_update_via_git(repo_dir, on_before_restart)

    return _apply_update_via_source_zip(repo_dir, release_info, progress_callback, on_before_restart)


def apply_update(
    release_info: Dict[str, Any],
    progress_callback: Optional[Callable[[int], None]] = None,
    on_before_restart: Optional[Callable[[], None]] = None,
) -> Tuple[bool, str]:
    """
    Downloads and installs the update cross-platform:
    - Windows frozen .exe: downloads DropFile.exe and launches swap helper batch.
    - macOS: updates via git, downloads DropFile-macOS.zip bundle, or unpacks release source zip.
    - Source / Linux: updates via 'git pull origin main' or downloads release source zip.
    """
    if sys.platform.startswith("win"):
        if getattr(sys, "frozen", False):
            return _apply_update_windows_exe(release_info, progress_callback, on_before_restart)
        else:
            return _apply_update_from_source(release_info, progress_callback, on_before_restart)
    elif sys.platform == "darwin":
        return _apply_update_macos(release_info, progress_callback, on_before_restart)
    else:
        # Linux / Unix
        return _apply_update_from_source(release_info, progress_callback, on_before_restart)
