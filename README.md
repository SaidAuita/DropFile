<div align="center">

# 📂 DropFile

**Lightweight Dropbox-style background file synchronization client for [FileBrowser](https://github.com/filebrowser/filebrowser) on Windows.**

[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011%20(64--bit)-blue.svg)](#)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Backend](https://img.shields.io/badge/Backend-FileBrowser-2F80ED.svg)](https://github.com/filebrowser/filebrowser)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

<br/>

*[English](#english) &bull; [Русский](#russian)*

</div>

---

<a name="english"></a>
## 📖 Overview

[FileBrowser](https://github.com/filebrowser/filebrowser) is an immensely popular, powerful self-hosted web file manager for personal servers, NAS devices, home mini-PCs, and Docker containers. However, FileBrowser lacks an official desktop client that automatically synchronizes a local folder on your PC like Dropbox, OneDrive, or Google Drive.

**DropFile** bridges this gap:
- Runs silently in the background via the **Windows System Tray**.
- Creates a dedicated sync folder on your Desktop (or any chosen location).
- Instantly uploads local changes to your FileBrowser instance and automatically downloads remote changes.
- Requires no WebDAV, SMB, or third-party cloud services: everything communicates over the standard **HTTPS / HTTP REST API** of FileBrowser.
- Bypasses strict corporate firewalls (port 443), reverse proxies (Nginx, Traefik, Caddy), tunnels (Cloudflare Tunnel, Tailscale, Keenetic Cloud), or direct IP setups.

---

## ✨ Features

- 🔄 **Bidirectional Automatic Synchronization**:
  - Real-time local filesystem monitoring via `watchdog` (drop files into the folder and they are instantly uploaded).
  - Background periodic remote polling detects new or modified files on the server and downloads them seamlessly.
- 🛡️ **Echo Loop Suppression & Smart Conflict Handling**:
  - Automatic suppression prevents download echo loops.
  - Event debouncing ensures files are completely written before upload begins.
  - Conflicted copy creation `(Conflict PC YYYY-MM-DD)` protects your data if files are modified concurrently on different machines.
- 🕒 **Informative System Tray**:
  - 🟢 **Idle / Up to date**: All files are synchronized.
  - 🔄 **Syncing**: Transferring files to or from the server.
  - 🔴 **Error**: Network or authentication issue.
  - ⏸️ **Paused**: Synchronization temporarily paused.
- ⚙️ **Modern GUI Settings Dialog**:
  - Built-in connection tester button (*"⚡ Test Connection"*).
  - Configurable local directory and remote server path (default: `/DropFile`).
  - One-click Desktop shortcut creation.
  - Configurable poll intervals and customizable ignore patterns (`~$*`, `*.tmp`, etc.).
  - Detailed synchronization activity log.
- 🚀 **Silent Windows Startup**:
  - Clean background execution via `DropFile.pyw` / `start_silent.vbs` without flashing console windows.
  - One-click autostart toggle with Windows registry integration.

---

## 🚀 Quick Start

### Prerequisites
* Windows 10 or 11 (64-bit)
* Python 3.10 or newer
* A running [FileBrowser](https://github.com/filebrowser/filebrowser) server with HTTP or HTTPS access

### Installation

Clone the repository:
```bash
git clone https://github.com/SaidAuita/DropFile.git
cd DropFile
```

Install the dependencies:
```bash
pip install -r requirements.txt
```

### Launch & Setup

1. Launch `DropFile.pyw` (or double-click `run.bat`).
2. On first run, the Settings dialog will open automatically:
   - **Server URL**: Your FileBrowser address (e.g., `https://files.yourdomain.com` or `http://10.0.0.10:8080`).
   - **Username** & **Password**: Your FileBrowser login credentials.
   - **Local Folder**: Folder on your PC (defaults to `Desktop\DropFile`).
   - **Remote Folder**: Target folder in FileBrowser (defaults to `/DropFile`, created automatically).
3. Click **"⚡ Test Connection"** to verify connectivity.
4. Click **"Save and Apply"**.
5. You're set! The tray icon will appear and syncing begins immediately.

---

## 🐳 FileBrowser Server Setup (Docker)

If you do not have FileBrowser running yet, deploy it in seconds with Docker:

```bash
docker run -d \
  --name filebrowser \
  -v /data/files:/srv \
  -v /data/filebrowser.db:/database/filebrowser.db \
  -v /data/settings.json:/.filebrowser.json \
  -p 8080:80 \
  --restart unless-stopped \
  filebrowser/filebrowser:latest
```

*Default login: `admin`, password: `admin` (change immediately upon first login).*

---

## 📁 Project Structure

```text
DropFile/
├── DropFile.pyw         # Main entry point (silent background launcher)
├── config.py            # Configuration manager (portable config.json & %APPDATA%)
├── config.example.json  # Configuration template
├── fb_client.py         # FileBrowser REST API client (JWT auth, listings, upload/download)
├── sync_engine.py       # Bidirectional sync engine, debounce & echo suppression
├── state_db.py          # SQLite database (state.db) tracking hashes & history
├── gui_settings.py      # Modern Tkinter settings & log viewer
├── tray.py              # Windows system tray integration (pystray)
├── icons.py             # Dynamic tray status icon renderer (Pillow)
├── win_utils.py         # Windows integration (registry autostart, desktop shortcuts)
├── run.bat              # Quick launch batch script
├── start_silent.vbs     # Silent background VBS launcher
├── requirements.txt     # Python dependencies
├── LICENSE              # MIT License
└── tests/               # Unit test suite
    ├── test_fb_client.py
    ├── test_state_db.py
    └── test_sync_engine.py
```

---

## 🧪 Testing

Run all unit tests:
```bash
python -m unittest discover tests
```

---

## 🛠️ Other Projects

* **[RyzenQuiet PRO](https://github.com/SaidAuita/RyzenQuietPro)** — Sleek, lightweight hardware HUD & power-plan optimizer for Windows with AMD Ryzen CPB toggle and real-time GPU power telemetry.
* **[ComfyUI Photoshop Plugin (PH-CU-S)](https://github.com/SaidAuita/ComfyUI_PH-CU-S)** — Powerful ComfyUI-based Photoshop plugin providing seamless direct integration with local generative AI models.
* **[Free Automation Tools & Utilities](https://ph-cu-s.com/tools)** — Free open-source scripts, extensions, and desktop utilities for Adobe Illustrator, InDesign, Photoshop, and Windows workflows.

---

<a name="russian"></a>
## 🇷🇺 Описание на русском

### 💡 О проекте

[FileBrowser](https://github.com/filebrowser/filebrowser) — популярный веб-менеджер файлов для личных серверов, NAS, домашних мини-ПК и Docker. Однако у FileBrowser нет официального десктопного клиента, который автоматически синхронизировал бы локальную папку на компьютере по принципу Dropbox или OneDrive.

**DropFile** закрывает эту потребность:
- Работает в фоне без лишних окон (в системном трее Windows).
- Создает удобную папку обмена на Рабочем столе.
- Мгновенно выгружает добавленные локально файлы на сервер FileBrowser и скачивает удаленные изменения.
- Не требует WebDAV, SMB или сторонних облачных сервисов: обмен идет через стандартный **HTTPS/HTTP REST API** самого FileBrowser.
- Успешно работает через любые корпоративные фаерволы (порт 443), прокси (Nginx, Caddy, Traefik), туннели (Cloudflare Tunnel, Keenetic Cloud, Tailscale) или прямое подключение по белому/локальному IP.

### 🌟 Основные возможности
- 🔄 **Двусторонняя автоматическая синхронизация**: локальный мониторинг через `watchdog` и фоновый периодический опрос сервера.
- 🛡️ **Защита от зацикливания и конфликтов**: дебаунсинг записи, подавление эхо и создание копий `(Конфликт PC YYYY-MM-DD)`.
- 🕒 **Информативный трей**: цветовая индикация (зеленый / синий / красный / желтый) и контекстное меню.
- ⚙️ **Графический интерфейс настроек**: проверка соединения в один клик, выбор папок, создание ярлыка, настройка исключений и журнал событий.
- 🚀 **Бесшумный автозапуск**: скрытый запуск без мигающих черных окон и автозагрузка вместе с Windows.

---

## 🛠️ Другие проекты

* **[RyzenQuiet PRO](https://github.com/SaidAuita/RyzenQuietPro)** — Элегантный и легковесный аппаратный HUD и оптимизатор планов электропитания для Windows с переключением AMD Ryzen CPB и телеметрией энергопотребления GPU в реальном времени.
* **[ComfyUI Photoshop Plugin (PH-CU-S)](https://github.com/SaidAuita/ComfyUI_PH-CU-S)** — Мощный плагин для Photoshop на базе ComfyUI, обеспечивающий прямую интеграцию с локальными генеративными моделями.
* **[Free Automation Tools & Utilities](https://ph-cu-s.com/tools)** — Бесплатные открытые скрипты, расширения и утилиты для Adobe Illustrator, InDesign, Photoshop и рабочих процессов Windows.

---

## 📄 License / Лицензия

Distributed under the open-source [MIT License](LICENSE).
