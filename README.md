<div align="center">

# 📂 DropFile

**Lightweight Dropbox-style background file synchronization client for [FileBrowser](https://github.com/filebrowser/filebrowser) on Windows.**

[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011%20(64--bit)-blue.svg)](#)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Backend](https://img.shields.io/badge/Backend-FileBrowser-2F80ED.svg)](https://github.com/filebrowser/filebrowser)
[![Release](https://img.shields.io/badge/Release-v1.05-orange.svg)](https://github.com/SaidAuita/DropFile)
[![Languages](https://img.shields.io/badge/Languages-10%20Locales-blueviolet.svg)](#)
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
- 🌍 **Multi-Language Interface (10 Languages)**:
  - English (default), Russian, German, French, Spanish, Italian, Portuguese, Polish, Simplified Chinese, Japanese.
  - Switch languages anytime in Settings or configuration.
- 👥 **Team Collaboration & Scaling**:
  - Flexible multi-user deployment: personal isolated folders or shared team exchange directories.
- 🛡️ **Echo Loop Suppression & Smart Conflict Handling**:
  - Automatic suppression prevents download echo loops.
  - Event debouncing ensures files are completely written before upload begins.
  - Conflicted copy creation `(Conflict PC YYYY-MM-DD)` protects your data if files are modified concurrently on different machines.
- 🕒 **Informative System Tray**:
  - 🟢 **Idle / Up to date**: All files are synchronized.
  - 🔄 **Syncing**: Transferring files to or from the server.
  - 🔴 **Error**: Network or authentication issue.
  - ⏸️ **Paused**: Synchronization temporarily paused.
- 🔗 **Instant Public Share Links in System Tray**:
  - Automatically creates a public share link (`/share/{hash}`) via FileBrowser API for the most recently uploaded file or folder.
  - One-click copy actions right in the tray context menu: *"🔗 Copy link: «filename»"* and *"📋 Copy filename"*.
  - Native toast notifications confirm when the link is copied to the clipboard, ready to send.
- 💾 **Settings Backup & Restore**:
  - One-click export of your full configuration to a JSON backup file and instant restoration.
  - Great for updating the app, reinstalling, or syncing configuration across multiple PCs.
- ⚙️ **Modern GUI Settings Dialog**:
  - Built-in connection tester button (*"⚡ Test Connection"*).
  - Configurable local directory and remote server path (default: `/DropFile`).
  - One-click Desktop shortcut creation.
  - Configurable poll intervals and customizable ignore patterns (`~$*`, `*.tmp`, etc.).
  - Detailed synchronization activity log with filterable actions.
- 📦 **Standalone Windows Executable (`DropFile.exe`)**:
  - Single self-contained `.exe` binary: zero setup, no Python or Git required for end users.
  - Built-in multi-resolution icon and silent windowless execution.
- 🔄 **In-App Auto-Update & Update Checker**:
  - Check for updates anytime with one click in Settings (`[🔍 Check for Updates]`) or via the System Tray context menu.
  - Automated binary hot-swap and seamless background restart for `.exe` builds, or `git pull` for source installs.
- 🧹 **Automatic File & Log Cleanup**:
  - Configurable auto-cleanup for files older than *N* days (default: 30 days, or 0 = keep forever) to keep storage clean.
  - Manual one-click file cleanup on demand directly from settings.
  - History log retention policy and one-click log clearing with confirmation.
- 🚀 **Silent Windows Startup**:
  - Clean background execution via `DropFile.exe` or `DropFile.pyw` without flashing console windows.
  - One-click autostart toggle with Windows registry integration.

---

## 👥 Team Collaboration & Multi-User Setup

DropFile easily scales from a single user to an entire department or company. Depending on your organization's workflow, choose between two deployment strategies:

### Option A: Isolated Personal User Folders (Personal Workspaces)
*Best when team members need individual storage without seeing each other's files.*

1. **On the FileBrowser Server**:
   - Create separate user accounts for each employee (e.g., `user_alex`, `user_elena`) in the FileBrowser admin panel.
   - Assign each user their own scope directory (e.g., `/srv/users/alex` and `/srv/users/elena`), or leave root scope and use distinct subfolders.
2. **On Each Employee's Computer**:
   - Install DropFile and log in with that employee's unique FileBrowser credentials.
   - Leave the Remote Folder as `/DropFile` (or set to `/Alex`, `/Elena`).
3. **Collaboration Workflow**:
   - Employees work independently with their personal files.
   - When someone needs to share a document or archive with colleagues or external clients, they right-click the DropFile tray icon and select **"🔗 Copy share link"** to immediately paste a public download link into Slack, Teams, Telegram, or email.

---

### Option B: Shared Team Exchange Folder (Department DropBox)
*Best for design teams, prepress, developers, or project groups who need a common drop zone.*

1. **On the FileBrowser Server**:
   - Create a common directory (e.g., `/Exchange` or `/TeamShare`).
   - Grant all participating employees read/write access to this directory in FileBrowser permissions.
2. **On Each Employee's Computer**:
   - Set **Remote directory in FileBrowser** to `/Exchange` (or the department path).
   - Point **Local folder** to their local workspace (e.g., `C:\Work\DropFile` or Desktop shortcut).
3. **Collaboration Workflow**:
    - **Intelligent Conflict Prevention**: DropFile compares SHA-256 hashes of file contents before declaring conflicts. Files with identical content (even with different timestamps or pre-existing copies) never spawn duplicates.
    - **Simultaneous Edit Protection**: If two team members genuinely modify a file with different content, DropFile protects both versions: `filename (Conflict ComputerName YYYY-MM-DD_HH-MM-SS).ext` (or choose *Newer file wins* in Settings).
    - **One-Click Deduplication**: The built-in *🔍 Deduplicate Copies* tool scans the sync folder and removes redundant conflict files whose SHA-256 matches the original file.
    - **Disk Space Management**: Set **Auto-cleanup files older than 30 days** in Settings across team PCs so temporary exchange files do not consume infinite disk space.

---

## 🚀 Quick Start

### Option 1: Standalone Executable (Recommended for Clients & Team Members)
*Zero installation — no Python or Git required!*
1. Download `DropFile.exe` from the latest [GitHub Release](https://github.com/SaidAuita/DropFile/releases).
2. Run `DropFile.exe`.
3. On first run, the Settings dialog opens automatically:
   - **Server URL**: Your FileBrowser address (e.g., `https://files.yourdomain.com` or `http://10.0.0.10:8080`).
   - **Username** & **Password**: Your FileBrowser login credentials.
   - **Local Folder**: Folder on your PC (defaults to `Desktop\DropFile`).
   - **Remote Folder**: Target folder in FileBrowser (defaults to `/DropFile`).
   - **Interface Language**: Select your language (10 locales available).
4. Click **"⚡ Test Connection"**, then click **"Save and Apply"**.
5. DropFile will run silently in your System Tray and begin syncing!

### Option 2: Run from Source / Build from Source
#### Prerequisites
* Windows 10 or 11 (64-bit)
* Python 3.10 or newer
* A running [FileBrowser](https://github.com/filebrowser/filebrowser) server

#### Setup
```bash
git clone https://github.com/SaidAuita/DropFile.git
cd DropFile
pip install -r requirements.txt
```
Launch with `python DropFile.pyw` or double-click `run.bat`.

#### Compiling Standalone `.exe`
Double-click `build_exe.bat` or execute:
```bash
python build_exe.py
```
The compiled single-file binary will be placed at `dist\DropFile.exe`.

### 🔄 In-App Auto-Updates
- Click **"🔍 Check for Updates"** in the Settings dialog header, or right-click the System Tray icon and select **"🔄 Check for updates..."**.
- If an update is found on GitHub Releases, DropFile prompts you to update.
- When confirmed, it downloads the new release, performs a clean binary swap (or `git pull`), and seamlessly restarts the app in the background.

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
├── updater.py           # Auto-updater (GitHub Releases API, semver, hot-swap & restart)
├── i18n.py              # Internationalization module (10 languages)
├── state_db.py          # SQLite database (state.db) tracking hashes & history
├── gui_settings.py      # Modern Tkinter settings & log viewer
├── tray.py              # Windows system tray integration (pystray)
├── icons.py             # Dynamic tray status icon & multi-res .ico generator
├── win_utils.py         # Windows integration (registry autostart, desktop shortcuts, hot restart)
├── version.py           # Application version definition
├── build_exe.py         # PyInstaller standalone .exe builder
├── build_exe.bat        # One-click Windows .exe compilation script
├── icon.ico             # Embedded multi-resolution application icon (16-256px)
├── run.bat              # Quick launch batch script
├── update.bat           # Self-updater batch script
├── start_silent.vbs     # Silent background VBS launcher
├── requirements.txt     # Python dependencies
├── LICENSE              # MIT License
└── tests/               # Unit test suite (27 tests)
    ├── test_entrypoint.py
    ├── test_fb_client.py
    ├── test_i18n.py
    ├── test_state_db.py
    ├── test_sync_engine.py
    └── test_updater.py
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
- 🌍 **Поддержка 10 языков интерфейса**: русский, английский (по умолчанию), немецкий, французский, испанский, итальянский, португальский, польский, китайский, японский.
- 👥 **Готовность к командной работе**: изоляция личных папок сотрудников или общая папка обмена отдела.
- 🔗 **Мгновенные публичные ссылки для обмена в трее**:
  - Автоматически создает публичную ссылку (`/share/{hash}`) через API FileBrowser для последнего выгруженного файла или папки.
  - Копирование ссылки или имени файла в буфер обмена прямо из контекстного меню трея в один клик (*«🔗 Скопировать ссылку: «файл»»*).
  - Уведомление о готовности ссылки для моментальной отправки в мессенджеры или почту.
- 💾 **Резервная копия и восстановление настроек**:
  - Экспорт и импорт всех настроек в файл `.json` в один клик. Удобно при обновлениях программы или переносе конфигурации на новый ПК.
- 🛡️ **Защита от зацикливания и конфликтов**: дебаунсинг записи, подавление эхо и создание копий `(Conflict PC YYYY-MM-DD)`.
- 🕒 **Информативный трей**: цветовая индикация (зеленый / синий / красный / желтый) и контекстное меню.
- ⚙️ **Графический интерфейс настроек**: проверка соединения в один клик, выбор папок, создание ярлыка, настройка исключений и журнал событий.
- 📦 **Автономная сборка Windows (`DropFile.exe`)**:
  - Единый исполняемый `.exe` файл без необходимости ставить Python или Git на рабочих местах пользователей.
  - Встроенная мультииконка высокого разрешения и работа в фоне без консольных окон.
- 🔄 **Встроенное автообновление и проверка новых версий**:
  - Кнопка **«🔍 Проверить обновления»** в шапке окна настроек и пункт в контекстном меню системного трея.
  - Автоматическая загрузка нового релиза с GitHub, безопасная горячая замена бинарника и бесшовный перезапуск в фоне.
- 🧹 **Автоочистка старых файлов и журнала**:
  - Автоматическое удаление файлов старше *N* дней (по умолчанию 30 дней, 0 = отключено), защищающее диск от переполнения.
  - Кнопка ручной очистки устаревших файлов по требованию прямо из настроек.
  - Настройка срока хранения истории и кнопка быстрой очистки журнала с подтверждением.
- 🚀 **Бесшумный автозапуск**: скрытый запуск без мигающих черных окон и автозагрузка вместе с Windows.

---

### 👥 Настройка для командной работы и масштабирование

DropFile отлично подходит как для личного использования, так и для работы команды (отдел дизайна, допечатная подготовка, разработка, офис). Доступны два основных сценария развертывания:

#### Сценарий 1: Персональные изолированные папки (личные рабочие места)
*Подходит, если у каждого сотрудника должно быть свое изолированное хранилище.*

1. **На сервере FileBrowser**:
   - В панели администратора FileBrowser создаются учетные записи для каждого сотрудника (`user_ivan`, `user_elena`).
   - Каждому пользователю задается своя корневая папка (например, `/srv/users/ivan`, `/srv/users/elena`), либо выделяется подпапка.
2. **На компьютере сотрудника**:
   - Устанавливается DropFile с индивидуальным логином и паролем.
   - Удаленная папка задается как `/DropFile` (или `/Ivan`, `/Elena`).
3. **Сценарий обмена**:
   - Файлы сотрудников не смешиваются.
   - Когда нужно передать файл коллеге или заказчику, сотрудник нажимает правой кнопкой на значок DropFile в трее и выбирает **«🔗 Скопировать ссылку»**. Готовая ссылка с прямым доступом сразу вставляется в мессенджер или почту.

---

#### Сценарий 2: Общая папка обмена отдела (командный DropBox)
*Подходит для мгновенного обмена рабочими макетами, архивами и проектами внутри команды.*

1. **На сервере FileBrowser**:
   - Создается единый каталог (например, `/Exchange` или `/TeamFiles`).
   - Всем сотрудникам отдела открывается доступ на чтение и запись к этому каталогу.
2. **На компьютерах сотрудников**:
   - В DropFile в поле **«Удаленный каталог в FileBrowser»** все указывают одинаковый путь: `/Exchange`.
   - Локальная папка настраивается в удобное место на диске (например, ярлык на Рабочем столе).
3. **Сценарий обмена**:
   - **Умное предотвращение конфликтов (проверка SHA-256 хэша)**: DropFile сравнивает хэши содержимого файлов перед фиксацией конфликта. Файлы с одинаковым содержимым (даже при разнице в датах или первичном подключении) никогда не дублируются.
   - **Защита от реальных конфликтов**: если двое сотрудников внесли разные изменения в один и тот же файл, DropFile сохранит обе версии: `Имя (Conflict ИмяПК ГГГГ-ММ-ДД_ЧЧ-ММ-СС).расширение` (или можно выбрать *«Побеждает более новый»* в Настройках).
   - **Встроенная дедупликация в 1 клик**: кнопка *«🔍 Очистить дубликаты»* в Настройках сканирует папку и удаляет избыточные файлы конфликтов, чей хэш на 100% совпадает с оригиналом.
   - **Автоматическая гигиена диска**: включите на компьютерах опцию **«Автоочистка файлов старше 30 дней»**, чтобы завершенные рабочие обмены не забивали диск до бесконечности.

### 🚀 Быстрый старт

#### Вариант 1: Готовый `.exe` (Рекомендуется для пользователей)
1. Скачайте файл `DropFile.exe` из раздела [GitHub Releases](https://github.com/SaidAuita/DropFile/releases).
2. Запустите `DropFile.exe` (установка Python или Git не требуется).
3. В появившемся окне настроек укажите адрес сервера FileBrowser, логин и пароль, затем нажмите **«Сохранить и применить»**.
4. Программа свернется в системный трей и начнет синхронизацию.

#### Вариант 2: Запуск из исходников и самостоятельная сборка `.exe`
```bash
git clone https://github.com/SaidAuita/DropFile.git
cd DropFile
pip install -r requirements.txt
```
Запуск: `python DropFile.pyw` (или скрипт `run.bat`).

Для сборки автономного исполняемого файла дважды кликните `build_exe.bat` или выполните:
```bash
python build_exe.py
```
Готовый автономный файл появится в каталоге `dist\DropFile.exe`.

#### 🔄 Обновление
- Нажмите **«🔍 Проверить обновления»** в окне настроек или выберите **«🔄 Проверить обновления...»** в трее.
- При наличии новой версии на GitHub DropFile скачает обновление, выполнит безопасную замену бинарника и автоматически перезапустится в фоне.

---

## 🛠️ Другие проекты

* **[RyzenQuiet PRO](https://github.com/SaidAuita/RyzenQuietPro)** — Элегантный и легковесный аппаратный HUD и оптимизатор планов электропитания для Windows с переключением AMD Ryzen CPB и телеметрией энергопотребления GPU в реальном времени.
* **[ComfyUI Photoshop Plugin (PH-CU-S)](https://github.com/SaidAuita/ComfyUI_PH-CU-S)** — Мощный плагин для Photoshop на базе ComfyUI, обеспечивающий прямую интеграцию с локальными генеративными моделями.
* **[Free Automation Tools & Utilities](https://ph-cu-s.com/tools)** — Бесплатные открытые скрипты, расширения и утилиты для Adobe Illustrator, InDesign, Photoshop и рабочих процессов Windows.

---

## 📄 License / Лицензия

Distributed under the open-source [MIT License](LICENSE).
