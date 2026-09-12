"""
FileBrowser API Client for DropFile.
Interacts with FileBrowser REST API over HTTPS.
Handles authentication (JWT), listing, streaming downloads, uploads, and deletions.
"""

import os
import shutil
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


@dataclass
class RemoteItem:
    path: str  # Remote path, e.g. "/DropFile/folder/doc.txt"
    name: str  # File/folder name
    size: int  # Size in bytes
    modified: str  # ISO timestamp
    is_dir: bool  # True if directory


class FileBrowserClient:
    def __init__(self, base_url: str, username: str = "", password: str = "", timeout: int = 20):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self.token: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "DropFile-Sync/1.0",
            "Accept": "application/json, text/plain, */*",
        })

    def _encode_path(self, path: str) -> str:
        """Encodes remote path for URL, preserving slashes."""
        parts = path.strip("/").split("/")
        encoded_parts = [urllib.parse.quote(part) for part in parts if part]
        return "/" + "/".join(encoded_parts) if encoded_parts else "/"

    def login(self, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """
        Authenticates with FileBrowser and stores JWT token.
        POST /api/login with json {"username": ..., "password": ...}
        """
        user = username if username is not None else self.username
        pwd = password if password is not None else self.password

        url = f"{self.base_url}/api/login"
        payload = {"username": user, "password": pwd}

        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
            if resp.status_code == 200:
                self.token = resp.text.strip().strip('"')
                self.session.headers["X-Auth"] = self.token
                if username is not None:
                    self.username = user
                if password is not None:
                    self.password = pwd
                return True
            else:
                self.token = None
                if "X-Auth" in self.session.headers:
                    del self.session.headers["X-Auth"]
                return False
        except Exception as e:
            print(f"[FileBrowserClient] Login error: {e}")
            self.token = None
            return False

    def ensure_authenticated(self) -> bool:
        """Ensures that client has a valid token, logging in if needed."""
        if self.token:
            return True
        return self.login()

    def test_connection(self) -> Tuple[bool, str]:
        """
        Tests server reachability and login credentials.
        Returns (success: bool, message: str).
        """
        if not self.base_url:
            return False, "URL сервера не указан."

        url = f"{self.base_url}/api/login"
        payload = {"username": self.username, "password": self.password}

        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
            if resp.status_code == 200:
                self.token = resp.text.strip().strip('"')
                self.session.headers["X-Auth"] = self.token
                return True, "Соединение успешно установлено! Авторизация пройдена."
            elif resp.status_code == 403:
                return False, "Ошибка 403: Неверное имя пользователя или пароль."
            elif resp.status_code == 404:
                return False, f"Ошибка 404: API FileBrowser не найден по адресу {self.base_url}."
            else:
                return False, f"Сервер вернул статус {resp.status_code}: {resp.text[:150]}"
        except requests.exceptions.SSLError as e:
            return False, f"Ошибка SSL-сертификата: {e}"
        except requests.exceptions.ConnectionError:
            return False, f"Не удалось подключиться к {self.base_url}. Проверьте интернет и адрес."
        except requests.exceptions.Timeout:
            return False, "Таймаут подключения к серверу (сервер не ответил вовремя)."
        except Exception as e:
            return False, f"Ошибка подключения: {e}"

    def get_resource(self, remote_path: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves directory or file metadata from /api/resources/<path>.
        """
        if not self.ensure_authenticated():
            return None

        encoded = self._encode_path(remote_path)
        url = f"{self.base_url}/api/resources{encoded}"

        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code in (401, 403):
                # Token may have expired, retry once
                if self.login():
                    resp = self.session.get(url, timeout=self.timeout)

            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 404:
                return None
            else:
                print(f"[FileBrowserClient] get_resource {remote_path} returned {resp.status_code}")
                return None
        except Exception as e:
            print(f"[FileBrowserClient] get_resource error for {remote_path}: {e}")
            return None

    def list_recursive(self, remote_root: str) -> List[RemoteItem]:
        """
        Lists all files and directories under remote_root recursively.
        Tries /api/resources/recursive first, falls back to manual recursion.
        """
        if not self.ensure_authenticated():
            return []

        encoded = self._encode_path(remote_root)
        url = f"{self.base_url}/api/resources/recursive{encoded}"

        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code in (401, 403):
                if self.login():
                    resp = self.session.get(url, timeout=self.timeout)

            if resp.status_code == 200:
                data = resp.json()
                items: List[RemoteItem] = []
                if isinstance(data, list):
                    for item in data:
                        items.append(
                            RemoteItem(
                                path=item.get("path", ""),
                                name=item.get("name", ""),
                                size=item.get("size", 0),
                                modified=item.get("modified", ""),
                                is_dir=bool(item.get("isDir", False)),
                            )
                        )
                    return items
                elif isinstance(data, dict):
                    self._parse_items_recursive(data, items)
                    return items
        except Exception as e:
            print(f"[FileBrowserClient] list_recursive failed, falling back: {e}")

        # Fallback to standard recursive walk
        return self._list_walk_fallback(remote_root)

    def _parse_items_recursive(self, node: Dict[str, Any], result: List[RemoteItem]) -> None:
        """Helper to flatten tree from FileBrowser recursive json."""
        if not node:
            return
        
        # Add children
        children = node.get("items", [])
        for item in children:
            item_path = item.get("path", "")
            result.append(
                RemoteItem(
                    path=item_path,
                    name=item.get("name", ""),
                    size=item.get("size", 0),
                    modified=item.get("modified", ""),
                    is_dir=bool(item.get("isDir", False)),
                )
            )
            if item.get("isDir") and "items" in item:
                self._parse_items_recursive(item, result)

    def _list_walk_fallback(self, remote_path: str) -> List[RemoteItem]:
        """Recursive directory walker if /api/resources/recursive is not supported."""
        result: List[RemoteItem] = []
        stack = [remote_path]

        while stack:
            current = stack.pop()
            data = self.get_resource(current)
            if not data:
                continue

            for item in data.get("items", []):
                item_path = item.get("path", "")
                is_dir = bool(item.get("isDir", False))
                result.append(
                    RemoteItem(
                        path=item_path,
                        name=item.get("name", ""),
                        size=item.get("size", 0),
                        modified=item.get("modified", ""),
                        is_dir=is_dir,
                    )
                )
                if is_dir:
                    stack.append(item_path)

        return result

    def create_directory(self, remote_path: str) -> bool:
        """
        Creates a directory on FileBrowser.
        POST /api/resources/<path>/ (trailing slash)
        """
        if not self.ensure_authenticated():
            return False

        clean_path = remote_path.strip("/") + "/"
        encoded = self._encode_path(clean_path)
        if not encoded.endswith("/"):
            encoded += "/"

        url = f"{self.base_url}/api/resources{encoded}"

        try:
            resp = self.session.post(url, timeout=self.timeout)
            if resp.status_code in (401, 403):
                if self.login():
                    resp = self.session.post(url, timeout=self.timeout)
            return resp.status_code in (200, 201)
        except Exception as e:
            print(f"[FileBrowserClient] create_directory error: {e}")
            return False

    def ensure_remote_dir_exists(self, remote_dir: str) -> bool:
        """Ensures that all parent directories for remote_dir exist."""
        clean = remote_dir.strip("/")
        if not clean:
            return True

        parts = clean.split("/")
        current = ""
        for part in parts:
            current += "/" + part
            res = self.get_resource(current)
            if not res:
                self.create_directory(current)
        return True

    def download_file(self, remote_path: str, local_dest: Path | str) -> bool:
        """
        Downloads a remote file directly via GET /api/raw/<path>.
        Uses temporary file with atomic replacement to prevent partial writes.
        """
        if not self.ensure_authenticated():
            return False

        dest = Path(local_dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        temp_dest = dest.with_suffix(dest.suffix + f".tmp.{os.getpid()}")

        encoded = self._encode_path(remote_path)
        url = f"{self.base_url}/api/raw{encoded}"

        try:
            with self.session.get(url, stream=True, timeout=self.timeout * 2) as resp:
                if resp.status_code in (401, 403):
                    if self.login():
                        with self.session.get(url, stream=True, timeout=self.timeout * 2) as resp2:
                            resp = resp2
                if resp.status_code != 200:
                    print(f"[FileBrowserClient] download {remote_path} status: {resp.status_code}")
                    return False

                with open(temp_dest, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)

            # Atomic replace
            shutil.move(str(temp_dest), str(dest))
            return True
        except Exception as e:
            print(f"[FileBrowserClient] download error for {remote_path}: {e}")
            if temp_dest.exists():
                try:
                    temp_dest.unlink()
                except Exception:
                    pass
            return False

    def upload_file(self, local_src: Path | str, remote_path: str) -> bool:
        """
        Uploads a local file to FileBrowser using POST /api/resources/<path>?override=true.
        """
        if not self.ensure_authenticated():
            return False

        src = Path(local_src)
        if not src.is_file():
            return False

        # Ensure parent remote folder exists
        remote_parent = str(Path(remote_path).parent).replace("\\", "/")
        if remote_parent and remote_parent != "/":
            self.ensure_remote_dir_exists(remote_parent)

        encoded = self._encode_path(remote_path)
        url = f"{self.base_url}/api/resources{encoded}?override=true"

        try:
            with open(src, "rb") as f:
                resp = self.session.post(url, data=f, timeout=self.timeout * 3)

            if resp.status_code in (401, 403):
                if self.login():
                    with open(src, "rb") as f:
                        resp = self.session.post(url, data=f, timeout=self.timeout * 3)

            return resp.status_code in (200, 201)
        except Exception as e:
            print(f"[FileBrowserClient] upload error for {src} -> {remote_path}: {e}")
            return False

    def delete_resource(self, remote_path: str) -> bool:
        """
        Deletes a file or directory from FileBrowser via DELETE /api/resources/<path>.
        """
        if not self.ensure_authenticated():
            return False

        encoded = self._encode_path(remote_path)
        url = f"{self.base_url}/api/resources{encoded}"

        try:
            resp = self.session.delete(url, timeout=self.timeout)
            if resp.status_code in (401, 403):
                if self.login():
                    resp = self.session.delete(url, timeout=self.timeout)
            return resp.status_code in (200, 204, 404)
        except Exception as e:
            print(f"[FileBrowserClient] delete error for {remote_path}: {e}")
            return False

    def get_or_create_share_link(self, remote_path: str) -> Optional[str]:
        """
        Retrieves an existing public share link or creates a new one via FileBrowser API.
        Returns the full public URL (e.g. 'https://host.com/share/aBcDeF') or direct web link fallback.
        """
        if not self.ensure_authenticated():
            return None

        clean_path = "/" + remote_path.strip("/")
        encoded = self._encode_path(clean_path)

        # 1. Check if public share link already exists
        url_get = f"{self.base_url}/api/share{encoded}"
        try:
            resp = self.session.get(url_get, timeout=self.timeout)
            if resp.status_code == 200:
                shares = resp.json()
                if isinstance(shares, list) and len(shares) > 0:
                    first_share = shares[0]
                    if isinstance(first_share, dict) and "hash" in first_share:
                        return f"{self.base_url}/share/{first_share['hash']}"
        except Exception as e:
            print(f"[FileBrowserClient] Error checking share for {remote_path}: {e}")

        # 2. Create new public share link
        url_post = f"{self.base_url}/api/share{encoded}"
        try:
            resp = self.session.post(url_post, json={}, timeout=self.timeout)
            if resp.status_code in (401, 403):
                if self.login():
                    resp = self.session.post(url_post, json={}, timeout=self.timeout)

            if resp.status_code in (200, 201):
                data = resp.json()
                if isinstance(data, dict) and "hash" in data:
                    return f"{self.base_url}/share/{data['hash']}"
        except Exception as e:
            print(f"[FileBrowserClient] Error creating share for {remote_path}: {e}")

        # 3. Graceful fallback: direct web link inside FileBrowser files viewer
        return f"{self.base_url}/files{encoded}"
