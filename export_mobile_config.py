#!/usr/bin/env python3
"""
DropFile Mobile - Configuration Export Utility
Generates a dropfile_mobile_config.json file for instant import into the DropFile Mobile Android app.
"""

import os
import sys
import json
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Export DropFile configuration for DropFile Mobile Android app.")
    parser.add_argument("--url", help="Public/External URL of FileBrowser server (e.g. http://123.45.67.89:8080 or https://fb.domain.com)")
    parser.add_argument("--user", help="Username")
    parser.add_argument("--password", help="Password")
    parser.add_argument("--folder", default="/Exchange/Mobile", help="Target remote folder on FileBrowser (default: /Exchange/Mobile)")
    parser.add_argument("--output", default="dropfile_mobile_config.json", help="Output file path (default: dropfile_mobile_config.json)")
    args = parser.parse_args()

    app_dir = Path(__file__).resolve().parent
    local_config_file = app_dir / "config.json"

    # Default values from existing desktop config if available
    server_url = ""
    username = ""
    password = ""
    target_folder = args.folder

    if local_config_file.exists():
        try:
            with open(local_config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                server_url = data.get("server_url", "")
                username = data.get("username", "")
                password = data.get("password", "")
        except Exception as e:
            print(f"Warning: could not read local config.json: {e}")

    # Command-line arguments override config.json
    if args.url:
        server_url = args.url
    if args.user:
        username = args.user
    if args.password:
        password = args.password

    mobile_config = {
        "server_url": server_url,
        "username": username,
        "password": password,
        "target_folder": target_folder,
        "auto_close": True
    }

    out_path = Path(args.output)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(mobile_config, f, indent=4, ensure_ascii=False)

    print("=" * 65)
    print(f"✅ Файл конфигурации для мобильного успешно создан:")
    print(f"   {out_path.resolve()}")
    print("=" * 65)
    print("Содержимое:")
    print(json.dumps(mobile_config, indent=4, ensure_ascii=False))
    print("=" * 65)
    print("Как импортировать в телефон:")
    print("1. Передайте этот файл на телефон (через Telegram, USB или загрузите в FileBrowser).")
    print("2. В приложении DropFile Mobile откройте «Настройки».")
    print("3. Нажмите «📥 Импортировать файл настроек (.json)» и выберите этот файл.")
    print("=" * 65)

if __name__ == "__main__":
    main()
