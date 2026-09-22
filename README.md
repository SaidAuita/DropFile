<div align="center">

# 📂 DropFile

**Lightweight Dropbox-style background file synchronization client for [FileBrowser](https://github.com/filebrowser/filebrowser) on Windows, macOS & Linux.**

[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-blue.svg)](#)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![Backend](https://img.shields.io/badge/Backend-FileBrowser-2F80ED.svg)](https://github.com/filebrowser/filebrowser)
[![Release](https://img.shields.io/badge/Release-v1.30.1-orange.svg)](https://github.com/SaidAuita/DropFile/releases)


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
- Runs silently in the background (**Windows System Tray**, **macOS Menu Bar**, **Linux Desktop Tray**, or **Linux Headless Server Daemon**).
- Creates a dedicated sync folder on your Desktop (or any chosen location).
- Instantly uploads local changes to your FileBrowser instance and automatically downloads remote changes.
- Requires no WebDAV, SMB, or third-party cloud services: everything communicates over the standard **HTTPS / HTTP REST API** of FileBrowser.
- Bypasses strict corporate firewalls (port 443), reverse proxies (Nginx, Traefik, Caddy), tunnels (Cloudflare Tunnel, Tailscale, Keenetic Cloud), or direct IP setups.

---

## ✨ Features

- 🚀 **Two-Folder Architecture: `Exchange` vs `Output`**:
  - **`Exchange` (High-Speed Server ⇄ Server DropSync)**:
    - Powered by a dedicated high-performance WebSocket streaming engine (`dropsync_server`) with delta hashing (SHA-256) and chunked transfer.
    - Keeps server exchange folders (e.g. Work Server ⇄ Home Server / NAS) perfectly synchronized in real time with zero WebDAV or heavy HTTP overhead.
    - Native LAN/SMB network share integration (`\\server\Exchange` or mapped drive `Z:`).
    - Lightweight Linux headless daemon (`dropsync.service`) running on servers.
  - **`Output` (Client Deliverables & Public Sharing via FileBrowser)**:
    - Dedicated staging folder for sharing finished files with external clients and customers.
    - Generates instant public download links (`/share/{hash}`) via FileBrowser REST API.
    - One-click tray context menu actions: *"🔗 Copy link: «filename»"* and *"📋 Copy filename"*.
    - Completely isolates client-facing downloads from continuous internal server sync.
- 📈 **Keenetic-Style Real-Time Traffic & Speed Monitor**:
  - Dual-area live speed charts (Green for Download/Rx, Blue for Upload/Tx) with dynamic peak auto-scaling.
  - Interactive mode switch: monitor remote **DropSync Server ⇄ Server** traffic or **Local PC Client** network throughput.
- 🗂️ **Total Commander Style Dual-Level Progress Bars for Batches & Folders**:
  - **Single file transfer**: Sleek progress bar with filename, transfer percentage, transferred volume, and live ETA.
  - **Folder / Batch transfer**: Dual progress bars (Top: current file progress `0 %`, Bottom: overall batch progress `31 %`), batch file counter (`110 / 366`), total batch volume (`183,3 МБ / 598,3 МБ`), and total remaining time ETA (`⏱ Remaining: ~1 min`).
- 📦 **Automated Project Build Drops Synchronization & Version Rotation**:
  - Automatically monitors multiple local project build directories (e.g. `Build_DEV/`, `bin/`, `out/`, `publish/`) for newly compiled archives (`*.zip`, `*.7z`, etc.).
  - Safely copies finished builds to dedicated project folders on your server or network share (e.g. `\\192.168.1.4\Exchange\Build\ProjectName\`).
  - **Version Retention ($N$ builds)**: Keeps only the last $N$ builds (default 5, configurable per project), automatically pruning older builds from the server share.
  - **Pre-Existing Build Auto-Sync**: Existing archives are detected and synchronized immediately upon startup/configuration in chronological order.
  - **Debounce & Exclusive Lock Verification**: Verifies size stability and exclusive write locks to ensure compiler has finished before initiating file transfer.
  - **Atomic Safe Transfer**: Uses temporary file write (`.tmp_*`) and atomic rename to guarantee file integrity across network shares.
- 🔄 **Bidirectional Automatic Synchronization**:
  - Real-time local filesystem monitoring via `watchdog` (drop files into the folder and they are instantly uploaded).
  - Background periodic remote polling detects new or modified files on the server and downloads them seamlessly.
- 🌐 **Dual-Server Synchronization & Mirroring (Server 1 ⇄ 2)**:
  - Configure both Primary and Backup FileBrowser servers with automatic failover and failback.
  - Optional full bidirectional server mirroring: keeps Server 1 and Server 2 exchange folders identical.
  - **Distributed Leader Election (Lock lease)**: When multiple PCs run in the same local network, an active coordinator (Leader) is automatically elected via `.dropfile_leader.json` lock. Only 1 PC mirrors the servers to avoid redundant network load, while all other clients operate safely in follower mode.
  - Live status indicator showing server availability, total file counts, coordinator status, and which server has newer files.
  - One-click server comparison check and manual instant synchronization from Settings or the System Tray.
- 🌍 **Multi-Language Interface (10 Languages)**:
  - English (default), Russian, German, French, Spanish, Italian, Portuguese, Polish, Simplified Chinese, Japanese.
  - Switch languages anytime in Settings or configuration.
- 👥 **Team Collaboration & Scaling**:
  - Flexible multi-user deployment: personal isolated folders or shared team exchange directories.
- 🛡️ **Echo Loop Suppression & Smart Conflict Handling**:
  - Automatic suppression prevents download echo loops.
  - Event debouncing ensures files are completely written before upload begins.
  - Conflicted copy creation `(Conflict PC YYYY-MM-DD)` protects your data if files are modified concurrently on different machines.
- 🕒 **Informative System Tray & Status Indicator**:
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
- 💻 **Complete Cross-Platform Support (Windows, macOS & Linux)**:
  - **Windows 10/11**: Standalone single-file `.exe` binary, Windows System Tray integration, and Registry autostart.
  - **macOS (10.15 ... 15+)**: Native `/Applications/DropFile.app` status bar application (`LSUIElement=1`, zero Dock clutter), LaunchAgent autostart.
  - **Linux**: Desktop AppIndicator tray, Headless Server Daemon with `systemd` user service, XDG Autostart, full CLI management (`--status`, `--sync-now`, `--pause`, `--stop`), and standalone PyInstaller binary.
- 📱 **DropFile Mobile (Android Companion App)**:
  - Native companion app for Android ([Complete Guide & Setup](android/README.md)) for 1-tap photo, video, and file sending into `/Exchange/Mobile`.
  - Seamless Android Share sheet integration (`ACTION_SEND` / `ACTION_SEND_MULTIPLE`) from Gallery, Camera, Files, and messaging apps.
  - **No White IP required**: works over Keenetic KeenDNS Cloud proxy, Cloudflare Tunnel, Tailscale, or direct public IP.
  - 1-click configuration import (`dropfile_mobile_config.json`) and built-in diagnostic log viewer.
  - Direct APK download without Google Play: [DropFile-Mobile.apk](https://github.com/SaidAuita/DropFile/releases/latest/download/DropFile-Mobile.apk).


- 🔄 **In-App Auto-Update & Update Checker**:
  - Check for updates anytime with one click in Settings (`[🔍 Check for Updates]`) or via the System Tray / Menu Bar context menu.
  - Automated binary hot-swap and seamless background restart for `.exe` builds, or `git pull` for source installs.
- 🧹 **Automatic File & Log Cleanup**:
  - Configurable auto-cleanup for files older than *N* days (default: 30 days, or 0 = keep forever) to keep storage clean.
  - Manual one-click file cleanup on demand directly from settings.
  - History log retention policy and one-click log clearing with confirmation.
- ⚡ **Remote Control & Emergency Actions**:
  - Remote process list viewer with real-time memory usage and application grouping.
  - Emergency process termination (with strict whitelist enforcement option).
  - Pre-defined application launcher with no arbitrary shell command access.
  - Seamless "Kill hung app -> Quick re-launch" workflow with automatic status refresh.
  - Remote PC reboot with cryptographic HMAC-SHA256 PIN authentication.
- 🚀 **Silent Background Execution**:
  - Clean background execution without flashing console windows.
  - One-click autostart toggle on all supported operating systems.

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

## 🛠️ Network Client Setup & Deployment Guide

How do you set up DropFile on an employee or team member's computer in your network?

### 1. Fast Local Network Exchange (DropSync SMB / Drive `Z:`)
*Best for everyday team workflows when users just need to drop files into the shared exchange.*
- **Is auto-detection enough?** **Yes!** For standard setups on the same local network:
  1. Open DropFile Settings ➔ **Folders** tab.
  2. Click **"🔍 Auto-detect"** in the LAN / SMB section. DropFile scans your network and resolves the local server (e.g., `\\192.168.1.100\Exchange`).
  3. Click **"📁 Mount Drive"** to automatically assign drive letter `Z:` in Windows Explorer, or click **"🔗 Create Shortcut"** for a Desktop icon.
  4. Done! Any files dropped into drive `Z:` are instantly synchronized across servers and workstations in real time via WebSocket DropSync.
- **What if auto-detection fails?** (e.g. firewalls blocking port scans, isolated subnets, or separate VLANs):
  - **Manual IP entry**: In the **"LAN / SMB Server"** box, simply type the server's IP address or hostname (e.g., `192.168.1.100` or `nas.local`). The UNC path updates to `\\192.168.1.100\Exchange`. Then click **"Mount Drive"**.
  - **Manual Browse**: Click the **"Browse..."** button next to the Exchange path and pick any existing network share or local directory.
  - **Direct config**: Set `"exchange_path": "Z:\\"` (or `"\\\\192.168.1.100\\Exchange"`) directly in `config.json`.

---

### 2. Client Public Links & Remote Sync (FileBrowser `Output` Folder)
*Required when an employee needs to send download links to external clients or sync while working remotely.*
1. Open Settings ➔ **Connection** tab:
   - **Server URL**: Enter the FileBrowser address (e.g., `http://192.168.1.100:8080` or your public domain `https://cloud.example.com`).
   - **Username & Password**: Enter the employee's FileBrowser user credentials.
   - Click **"⚡ Test Connection"** to verify.
2. In the **Folders** tab, verify the **`Output`** directory.
3. When files are saved into `Output`, right-click the DropFile tray icon to copy an instant public share link (`/share/{hash}`) ready to send.

---

### 3. ⚡ Zero-Setup Portable Deployment for Admins (5-Second Rollout)
You don't need to manually configure every PC:
1. Grab the generic template from [`examples/portable_setup/config.json`](examples/portable_setup/config.json).
2. Edit it with your company's server URL, credentials, and drive paths.
3. Place `config.json` in the same directory as `DropFile.exe` (on a network share or USB drive).
4. When the user launches `DropFile.exe`, it runs in portable mode, reads `config.json` automatically, and connects with zero prompts!

Alternatively, configure one PC, click **"Export Settings"** in the Settings tab, and let other users click **"Import Settings"**.

---

## ⚡ Remote Control & Emergency Management

DropFile includes a secure out-of-band remote management system that operates over the standard FileBrowser REST API. It requires no open inbound firewall ports, no VPNs, and no dynamic DNS — commands are delivered via encrypted, HMAC-SHA256 signed control packets (`.dropfile_control/`) with a strict 3-minute freshness window.

### 🌟 Key Capabilities:
- 📋 **Remote Process Viewer**: List all running processes on a remote machine with CPU/Memory stats and intelligent grouping.
- 🛑 **Remote Process Termination**: Terminate hung applications (e.g. `happ.exe`, `rustdesk`) remotely, with optional strict whitelist enforcement.
- 🚀 **Pre-defined Remote Application Launching**: Launch pre-configured applications remotely without giving the controller arbitrary shell command access.
- 🔄 **Remote Reboot**: Trigger an orderly system reboot of remote machines with PIN confirmation.
- 🔄 **Kill & Restart Workflow**: Terminate a frozen application and immediately re-launch it directly within the Remote Processes dialog — the process list automatically refreshes 2 seconds later to verify the restart.

### 🛡️ Security Architecture
- **No Arbitrary Command / Shell Execution**: Senders never specify file paths or command lines. They only send registered application names (e.g., `RustDesk`, `Calendar`).
- **Target-Managed Executable Whitelist**: Only applications explicitly registered on the target computer in `Settings -> Remote Control` can be launched.
- **HMAC-SHA256 Authorization**: Every action packet requires the target computer's secret PIN and is protected against tampering and replay attacks.

### 🐧 Note for Linux: How to Find Executable Paths & Command Names
On Linux, executable binaries and scripts are typically located in `/usr/bin/`, `/usr/local/bin/`, or managed via Flatpak/Snap. When adding an application to the Remote Launch list on a Linux machine:

| Application | Name (Identifier) | Executable Path | Arguments (Optional) |
|---|---|---|---|
| **RustDesk** | `RustDesk` | `/usr/bin/rustdesk` *(or `rustdesk`)* | *(empty)* or `--minimized` |
| **GNOME Calendar** | `Calendar` | `/usr/bin/gnome-calendar` | *(empty)* |
| **KDE Calendar** | `Calendar` | `/usr/bin/korganizer` | *(empty)* |
| **Telegram Desktop** | `Telegram` | `/usr/bin/telegram-desktop` | `-startintray` |
| **Flatpak App** | `Calendar` | `/usr/bin/flatpak` | `run org.gnome.Calendar` |

**Useful terminal commands to find any application's path on Linux:**
```bash
# 1. Find binary location via which or type:
which rustdesk
# Output: /usr/bin/rustdesk

which gnome-calendar
# Output: /usr/bin/gnome-calendar

# 2. Inspect command from desktop launcher (.desktop):
grep -E '^Exec=' /usr/share/applications/*calendar*.desktop
# Output: Exec=gnome-calendar %U
```

---

## 🚀 Installation & Quick Start

DropFile is available for **Windows**, **macOS**, and **Linux**. Choose your platform:

### 🪟 1. Windows Setup (10 & 11)

#### Method A: Standalone Executable (Recommended for Clients & End-Users)
*Zero setup — no Python or Git required!*
1. Download **`DropFile.exe`** from the latest [GitHub Release](https://github.com/SaidAuita/DropFile/releases).
2. Run `DropFile.exe`.
3. On first launch, the Settings dialog opens automatically:
   - **Server URL**: Your FileBrowser address (e.g., `https://files.yourdomain.com` or `http://10.0.0.10:8080`).
   - **Username** & **Password**: Your FileBrowser credentials.
   - **Local Folder**: Folder on your PC (defaults to `Desktop\DropFile`).
   - **Remote Folder**: Target directory in FileBrowser (defaults to `/DropFile`).
   - **Language**: Select interface language (10 languages available).
4. Click **"⚡ Test Connection"**, then click **"Save and Apply"**.
5. DropFile will run silently in your System Tray and begin syncing automatically!

#### Method B: Run or Build from Source (Windows)
```bash
git clone https://github.com/SaidAuita/DropFile.git
cd DropFile
pip install -r requirements.txt
python DropFile.pyw    # or double-click run.bat
```
To compile your own standalone executable:
```bash
python build_exe.py    # or double-click build_exe.bat
```
The compiled binary will be placed at `dist\DropFile.exe`.

---

### 🍏 2. macOS Setup (Catalina 10.15 ... Sequoia / Tahoe)

*Automated 1-click installer for macOS:*
1. Clone the repository into your home directory:
   ```bash
   cd ~
   git clone https://github.com/SaidAuita/DropFile.git
   cd DropFile
   ```
   *(Or download the ZIP archive from GitHub and unzip it into `~/DropFile`)*
2. Double-click **`install_mac.command`** in Finder (or run `./install_mac.command` in Terminal).
   - Automatically configures an isolated virtual environment (`.venv`) and installs required packages (including native PyObjC Cocoa support).
   - Builds and installs **`/Applications/DropFile.app`** with `LSUIElement=1` (runs natively in the top menu bar near the clock without Dock clutter).
   - Creates a Desktop sync shortcut (`~/Desktop/DropFile`).
3. Click the DropFile cloud icon in your top macOS menu bar -> select **"Settings"** to enter your server credentials.

> 📖 **Full macOS Installation Guide**: See [`doc/mac_install.md`](doc/mac_install.md) for step-by-step commands to install Python 3 via curl or Homebrew, LaunchAgent autostart setup, and troubleshooting.

---

### 🐧 3. Linux Setup (Ubuntu, Debian, Mint, Fedora, Arch)

DropFile supports Linux both on **Desktop workstations** (with system tray & GUI) and **Headless Servers / NAS / mini-PCs** (running as a background systemd daemon).

#### Method A: Automated Script Installer (Desktop & Server)
1. Clone the repository:
   ```bash
   cd ~
   git clone https://github.com/SaidAuita/DropFile.git
   cd DropFile
   ```
2. Run the automated Linux installer:
   ```bash
   chmod +x install_linux.sh run_linux.sh
   ./install_linux.sh
   ```
   - Creates an isolated `.venv` and installs all dependencies (`requirements-linux.txt`).
   - Prepares the sync folder (`~/Desktop/DropFile` or `~/DropFile`).
   - On Desktop: creates Desktop shortcut and registers application launcher in `~/.local/share/applications/dropfile.desktop`.
   - On Server: creates systemd user service (`~/.config/systemd/user/dropfile.service`).

3. Start DropFile:
   ```bash
   ./run_linux.sh              # Desktop GUI mode (runs in system tray)
   ./run_linux.sh --settings   # Open GUI Settings dialog
   ./run_linux.sh --headless   # Server / Headless mode (runs sync daemon)
   ```

#### Method B: Headless Server Daemon with `systemd` (Recommended for Servers)
To run DropFile continuously as a background service on your server or mini-PC:
```bash
# Enable on system boot and start service immediately:
systemctl --user enable --now dropfile.service

# Check service status:
systemctl --user status dropfile.service

# View live synchronization logs:
journalctl --user -u dropfile.service -f

# Stop service:
systemctl --user stop dropfile.service
```

#### Method C: Command-Line Management (CLI)
Control a running DropFile background instance from any terminal:
```bash
./run_linux.sh --status       # Query sync status via IPC socket
./run_linux.sh --sync-now     # Trigger instant file check and sync
./run_linux.sh --pause        # Pause file synchronization
./run_linux.sh --resume       # Resume file synchronization
./run_linux.sh --stop         # Stop running background instance
./run_linux.sh --help         # Show all command-line options
```

#### Method D: Standalone Linux Executable (PyInstaller)
Compile DropFile into a single standalone binary `dist/dropfile` that requires zero setup or Python packages:
```bash
pip install pyinstaller
python3 build_linux.py
```
> 📖 **Full Linux Guide**: See [`README_LINUX.md`](README_LINUX.md) for complete details.

---

## 📦 Project Build Drops Synchronization

**DropFile** includes a specialized background engine designed for developers and automated build pipelines that frequently create application builds, installers, or test archives (e.g. `*.zip`, `*.7z`, `*.exe`, `*.tar.gz`) across multiple software repositories.

```
Local PC:                                  Network Share / Exchange Server:
[Project 1 / Build_DEV] --(auto-sync)-->  \\192.168.1.4\Exchange\Build\Project_1\ (keeps last 5)
[Project 2 / Build_DEV] --(auto-sync)-->  \\192.168.1.4\Exchange\Build\Project_2\ (keeps last 5)
```

### Key Capabilities:
1. **Multi-Project Directory Monitoring**:
   - Add any number of independent build source directories to monitor (e.g. `C:\_CODE\AI Code Pro\Build_DEV`, `C:\_CODE\ID Code Pro\Build_DEV`).
   - Configure custom file patterns per task (e.g. `*.zip`, `*.7z`, `*.exe`, `App_*.zip`).
2. **Dedicated Project Target Directories**:
   - Each project automatically syncs to its own dedicated subfolder on your network share or exchange server (e.g. `\\192.168.1.4\Exchange\Build\AI_Code_Pro\`).
   - Keeps builds neatly separated and ready for remote testers or secondary machines.
3. **Automated Version Rotation & Pruning**:
   - Specify `keep_versions` per project (default: 5).
   - Only the newest $N$ builds are kept on the server. Older builds are automatically rotated and deleted to prevent server disk clutter, while ensuring that the latest versions remain accessible.
4. **Instant Synchronization of Pre-Existing Archives**:
   - Build files created before setting up DropFile or before app launch are immediately recognized and copied on the very first pass.
   - When more than $N$ pre-existing builds exist locally, DropFile intelligently sorts them chronologically and copies only the newest $N$ versions to save network bandwidth.
5. **Debounce & Exclusive Lock Verification**:
   - Guarantees that files are not transferred while an archiver or compiler is still writing.
   - Requires size stability and verifies exclusive read access before initiating file transfer.
6. **Atomic Safe Transfer**:
   - Copies files using temporary `.tmp_*` filenames and performs an atomic rename upon completion, ensuring no partially-copied files appear on the network share.
7. **Interactive GUI & Background Control**:
   - Access the dedicated **«Build Drops Synchronization»** window from the System Tray or Settings dialog.
   - Add, edit, or delete tasks with instant path auto-suggestion.
   - Click **«Sync Now»** for instant on-demand synchronization across all tasks.
   - Global toggle to enable/disable all build synchronization without deleting configured tasks.

---

### 🔄 Updates

#### 1. In-App Auto-Update (One-Click)
- Click **"🔍 Check for Updates"** in the Settings dialog header, or right-click the System Tray / Menu Bar icon and select **"🔄 Check for updates..."**.
- If an update is found on GitHub, DropFile prompts you to update.
- When confirmed, it downloads the new release, performs a clean binary swap (or `git pull`), and seamlessly restarts the app in the background.

#### 2. Manual Update via Terminal (macOS, Linux & Source Installs)
If you installed DropFile via `git clone`, you can update at any time directly in the Terminal:
```bash
cd ~/DropFile
git pull origin main
```
> 💡 **Troubleshooting Git Merge Conflicts**: If you made local modifications and git warns that *«Your local changes would be overwritten by merge»*, safely stash your local edits and pull the clean release:
> ```bash
> cd ~/DropFile
> git stash
> git pull origin main
> ```

> 🍏 **Note for macOS users**: You do **NOT** need to recompile or rebuild `/Applications/DropFile.app` after running `git pull`! The application bundle operates as a native launcher that directly runs the updated code from `~/DropFile`. Simply restart the app (`Quit` in the menu bar and reopen `/Applications/DropFile.app`).

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
├── DropFile.pyw         # Main entry point (silent background launcher, CLI & headless daemon)
├── config.py            # Configuration manager (portable config.json, %APPDATA%, macOS & Linux)
├── config.example.json  # Configuration template
├── fb_client.py         # FileBrowser REST API client (JWT auth, listings, upload/download)
├── sync_engine.py       # Bidirectional sync engine, inotify/watchdog, debounce & echo suppression
├── updater.py           # Auto-updater (GitHub Releases API, semver, hot-swap & restart)
├── i18n.py              # Internationalization module (10 languages)
├── state_db.py          # SQLite database (state.db) tracking hashes & history
├── gui_settings.py      # Modern Tkinter settings & log viewer (Windows, macOS, Linux)
├── tray.py              # System tray integration (pystray for Windows, macOS & Linux)
├── platform_utils.py    # Cross-platform utilities (autostart, single instance lock, shortcuts)
├── icons.py             # Dynamic tray status icon & multi-res .ico generator
├── version.py           # Application version definition
│
├── # 🪟 Windows Build & Launch:
├── build_exe.py         # PyInstaller standalone .exe builder
├── build_exe.bat        # One-click Windows .exe compilation script
├── run.bat              # Quick launch batch script
├── start_silent.vbs     # Silent background VBS launcher
│
├── # 🍏 macOS Build & Launch:
├── install_mac.command  # 1-click installer: creates .venv and /Applications/DropFile.app
├── run_mac.command      # Portable macOS runner
├── package_mac_app.py   # Native macOS .app bundle packager (LSUIElement status bar)
├── doc/mac_install.md   # Detailed macOS installation guide
│
├── # 🐧 Linux Build & Launch:
├── install_linux.sh     # 1-click Linux installer: sets up .venv, desktop entry & systemd unit
├── run_linux.sh         # Portable Linux runner (GUI, CLI & headless daemon)
├── dropfile.service     # Systemd user service unit template
├── build_linux.py       # PyInstaller standalone Linux binary builder
├── requirements-linux.txt # Linux Python dependencies
├── README_LINUX.md      # Comprehensive Linux installation & service guide
│
├── requirements.txt     # Windows Python dependencies
├── LICENSE              # MIT License
└── tests/               # Cross-platform unit test suite
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
- Работает незаметно в фоне (**системный трей Windows**, **строка меню macOS**, **трей Linux** или **серверный headless-демон systemd**).
- Создает удобную папку обмена на Рабочем столе (или в любом указанном каталоге).
- Мгновенно выгружает локальные файлы на сервер FileBrowser и автоматически скачивает удаленные изменения.
- Не требует WebDAV, SMB или сторонних облачных сервисов: обмен идет через стандартный **HTTPS / HTTP REST API** самого FileBrowser.
- Успешно работает через любые корпоративные фаерволы (порт 443), прокси (Nginx, Caddy, Traefik), туннели (Cloudflare Tunnel, Keenetic Cloud, Tailscale) или прямое подключение по белому/локальному IP.

### 🌟 Основные возможности
- 🚀 **Разделение концепции: папка `Exchange` и папка `Output`**:
  - **`Exchange` (Высокоскоростная синхронизация Сервер ⇄ Сервер через DropSync)**:
    - Работает на выделенном движке потоковой передачи по WebSocket (`dropsync_server`) с дельта-хэшированием (SHA-256) и поблочной передачей.
    - Обеспечивает мгновенную синхронизацию между серверами (например, Рабочий сервер ⇄ Домашний сервер / NAS) без накладных расходов WebDAV или тяжелых HTTP-запросов.
    - Прямая интеграция с локальными сетевыми ресурсами SMB (`\\server\Exchange` или подключенный диск `Z:`).
    - Автономный легковесный демон для Linux (`dropsync.service`).
  - **`Output` (Публикация ссылок для клиентов через FileBrowser)**:
    - Выделенная папка для передачи готовых макетов, архивов и файлов заказчикам.
    - Мгновенная генерация публичных ссылок для скачивания (`/share/{hash}`) через REST API FileBrowser.
    - Копирование ссылки или имени файла в один клик прямо из контекстного меню системного трея (*«🔗 Скопировать ссылку: «файл»»*).
    - Полная изоляция клиентских файлов от непрерывного внутреннего обмена между серверами.
- 📈 **Монитор сетевой скорости и трафика в стиле роутеров Keenetic**:
  - Интерактивный двухсегментный график скорости (зеленая зона — прием/Rx, синяя зона — передача/Tx) с автомасштабированием пиков.
  - Переключение режимов мониторинга: трафик удаленного **DropSync сервера** или **Локального ПК**.
- 🗂️ **Двухуровневый индикатор передачи папок в стиле Total Commander**:
  - **Одиночный файл**: компактный прогресс-бар с именем файла, процентами, объемом и временем ETA.
  - **Передача папки / пакета файлов**: два независимых прогресс-бара (верхний — текущий файл `0 %`, нижний — весь пакет `31 %`), счетчик обработанных файлов (`110 / 366`), суммарный объем данных (`183,3 МБ / 598,3 МБ`) и общее расчетное время до завершения (`⏱ Осталось: ~1 мин`).
- 📦 **Автоматическая синхронизация сборок проектов и ротация версий**:
  - Автоматический мониторинг локальных папок сборок нескольких проектов (например, `Build_DEV/`, `bin/`, `publish/`) для готовых архивов (`*.zip`, `*.7z` и др.).
  - Безопасное копирование готовых релизов в персональные папки на сервере обмена (например, `\\192.168.1.4\Exchange\Build\ProjectName\`).
  - **Ротация версий ($N$ сборок)**: Хранение только последних $N$ версий билдов (по умолчанию 5, настраивается отдельно для каждого проекта) с автоматическим удалением устаревших версий с сервера.
  - **Мгновенный подхват существующих архивов**: Файлы, уже созданные до старта или настройки задачи, автоматически синхронизируются на сервер в хронологическом порядке.
  - **Защита от недописанных файлов (Debounce и Lock)**: Проверка стабильности размера и блокировок перед передачей гарантирует, что файл скопируется только после полного завершения записи архиватором.
  - **Атомарное копирование**: Передача через временный файл (`.tmp_*`) с последующим переименованием исключает появление поврежденных архивов на сервере.
- 🔄 **Двусторонняя автоматическая синхронизация**: локальный мониторинг через `watchdog` и фоновый периодический опрос сервера.
- 🌐 **Синхронизация и зеркалирование двух серверов (Сервер 1 ⇄ 2)**:
  - Поддержка основного и резервного сервера FileBrowser с автоматическим переключением (failover) и возвратом (failback).
  - Опциональное двустороннее зеркалирование: поддержание идентичного состава файлов на Сервере 1 и Сервере 2.
  - **Распределенная блокировка и координатор (Leader Election)**: При работе нескольких ПК в сети автоматически выбирается один координатор (Лидер) через серверный lock-файл `.dropfile_leader.json` (аренда на 3 мин). Только один клиент зеркалирует серверы во избежание дублирования трафика, остальные ПК работают в режиме мониторинга.
  - Наглядная индикация статуса синхронизации серверов: количество файлов, дата последнего изменения, статус координатора и где файлы новее.
  - Кнопки быстрой проверки статуса и принудительной синхронизации серверов в окне настроек и меню трея.
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
- 💻 **Полная кроссплатформенность (Windows, macOS и Linux)**:
  - **Windows 10/11**: Автономный `.exe` без необходимости ставить Python, интеграция с системным треем и автозагрузка через реестр.
  - **macOS (10.15 ... 15+)**: Нативное приложение `/Applications/DropFile.app` для строки меню (`LSUIElement=1`, без иконки в Dock), автозагрузка через LaunchAgent.
  - **Linux**: Трей AppIndicator для десктопов, серверный headless-демон со службой `systemd`, XDG Autostart, консольное управление (CLI: `--status`, `--sync-now`, `--pause`, `--stop`) и автономный бинарник PyInstaller.
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
- ⚡ **Удаленное управление и аварийные действия**:
  - Диспетчер процессов удаленного ПК с группировкой и мониторингом памяти.
  - Аварийное снятие зависших процессов и программ (с опцией строгого белого списка).
  - Удаленный запуск доверенных приложений без риска выполнения произвольных shell-команд.
  - Быстрый сценарий «Снять процесс -> Перезапустить» прямо из окна процессов с автообновлением.
  - Удаленная перезагрузка компьютера с авторизацией по PIN-коду и HMAC-SHA256 подписью.
- 📱 **DropFile Mobile (Мобильное приложение для Android)**:
  - Нативное мобильное приложение-компаньон для Android ([Полное руководство и настройка](android/README.md)) для быстрой отправки фото, видео и файлов в папку `/Exchange/Mobile`.
  - Интеграция в системное меню «Поделиться» (Share Sheet) любого приложения (Галерея, Проводник, Telegram, WhatsApp).
  - **Белый IP НЕ требуется**: работает через облако Keenetic KeenDNS (`*.keenetic.link`), Cloudflare Tunnel, Tailscale или прямой IP.
  - Импорт файла настроек `dropfile_mobile_config.json` в 1 клик и встроенный просмотрщик логов для диагностики.
  - Прямая ссылка на установку APK без Google Play: [DropFile-Mobile.apk](https://github.com/SaidAuita/DropFile/releases/latest/download/DropFile-Mobile.apk).

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

---

### 🛠️ Руководство по настройке клиента у пользователя сети

Как настроить DropFile на компьютере сотрудника в локальной сети и что делать при возникновении вопросов?

#### 1. Быстрый обмен в локальной сети (DropSync SMB / Сетевой диск `Z:`)
*Основной сценарий, если сотрудникам нужно просто скидывать и забирать файлы из общего обмена.*
- **Достаточно ли автоопределения?** **Да, в 95% случаев!**
  1. В окне Настроек перейдите на вкладку **«Папки» (Folders)**.
  2. В блоке SMB нажмите кнопку **«🔍 Автоопределение»**. Программа опросит сеть и подставит рабочий адрес сервера (например, `\\192.168.1.100\Exchange`).
  3. Нажмите кнопку **«📁 Подключить диск»** (назначает букву `Z:` в Проводнике) или **«🔗 Создать ярлык»** (на Рабочем столе).
  4. Всё готово! Пользователь просто копирует файлы на диск `Z:`, а серверный демон DropSync автоматически транслирует их по WebSocket на второй сервер или коллегам.
- **Что делать, если автоопределение не сработало?** (например, фаервол блокирует сканирование, компьютеры находятся в разных подсетях или VLAN):
  - **Ручной ввод IP/имени**: В поле **«Сервер LAN / SMB»** сотрите текст и вручную впишите IP-адрес или сетевое имя сервера (например, `192.168.1.100` или `nas.local`). Строка UNC-пути автоматически обновится на `\\192.168.1.100\Exchange`. После этого нажмите «Подключить диск».
  - **Кнопка «Обзор»**: Нажмите кнопку «Обзор» у поля Exchange и укажите уже подключенную сетевую папку или диск вручную через стандартный диалог Windows.
  - **Через `config.json`**: В файле конфигурации укажите `"exchange_path": "Z:\\"` или `"\\\\192.168.1.100\\Exchange"`.

---

#### 2. Ссылки для клиентов и работа вне офиса (Папка `Output` через FileBrowser)
*Требуется, если сотруднику нужно генерировать публичные ссылки для заказчиков или синхронизировать файлы при работе из дома.*
1. В Настройках перейдите на вкладку **«Подключение»**:
   - **Адрес сервера (URL)**: введите адрес FileBrowser (например, `http://192.168.1.100:8080` в офисе или внешний домен/туннель `https://cloud.example.com` для удаленки).
   - **Логин и пароль**: учетная запись пользователя в FileBrowser.
   - Нажмите **«⚡ Проверить подключение»**.
2. Во вкладке **«Папки»** проверьте путь к папке **`Output`**.
3. Теперь при сохранении файла в `Output` в меню трея в 1 клик доступно действие: *«🔗 Скопировать ссылку на файл»* (`/share/{hash}`).

---

#### 3. ⚡ Развертывание за 5 секунд (Portable-пакет для администратора)
Чтобы не настраивать каждый компьютер вручную:
1. Возьмите готовый шаблон [`examples/portable_setup/config.json`](examples/portable_setup/config.json).
2. Заполните в нем IP-адреса, учетные записи и пути вашей организации.
3. Положите файл `config.json` в одну папку рядом с `DropFile.exe` (в сетевой папке инсталлятора или на флешке).
4. Пользователю достаточно запустить `DropFile.exe` — программа автоматически подхватит все настройки в portable-режиме без лишних вопросов!

Также доступен вариант: настроить один ПК, нажать **«Экспорт настроек»** во вкладке «Настройки», и на других ПК нажать **«Импорт настроек»**.

---

### ⚡ Удаленное управление и аварийные действия

В DropFile встроена безопасная система удаленного управления и экстренного администрирования компьютеров, работающая поверх стандартного FileBrowser REST API. Ей не требуются открытые входящие порты, "белые" IP-адреса или VPN — пакеты управления передаются через скрытый каталог `.dropfile_control/`, шифруются и авторизуются HMAC-SHA256 подписью с временным окном жизни 3 минуты.

#### 🌟 Основные возможности:
- 📋 **Диспетчер удаленных процессов**: просмотр списка активных процессов на удаленном компьютере с группировкой по программам, сортировкой по памяти и поисковым фильтром.
- 🛑 **Удаленное завершение зависших программ**: закрытие зависших процессов (например, `happ.exe`, `rustdesk`) с поддержкой строгого белого списка.
- 🚀 **Удаленный запуск заранее определенных приложений**: запуск доверенных программ без передачи путей или произвольных команд через сеть.
- 🔄 **Удаленная перезагрузка ПК**: отправка команды безопасной перезагрузки с подтверждением PIN-кодом.
- 🔄 **Быстрый сценарий «Снять процесс ➔ Перезапустить»**: прямо в окне просмотра процессов можно завершить зависшую программу и тут же запустить её из выпадающего списка. Список процессов автоматически обновится через 2 секунды, подтвердив успешный запуск!

#### 🛡️ Архитектура безопасности
- **Защита от инъекций команд и путей**: контроллер никогда не передает shell-команды или пути к файлам. Он отправляет только зарегистрированное имя (например, `RustDesk`, `Календарь`).
- **Локальный белый список**: реальный путь к исполняемому файлу настраивается и хранится исключительно локально на целевом ПК (`Настройки -> Удаленное управление`).
- **HMAC-SHA256 авторизация**: выполнение команд требует знания секретного PIN-кода целевого компьютера.

#### 🐧 Примечание для Linux: как находить запускаемые приложения и пути
В Linux исполняемые файлы обычно находятся в каталогах `/usr/bin/`, `/usr/local/bin/` либо запускаются через Flatpak. При добавлении приложения для удаленного запуска в настройках на Linux-компьютере:

| Приложение | Имя (Название) | Путь к исполняемому файлу | Параметры запуска (необязательно) |
|---|---|---|---|
| **RustDesk** | `RustDesk` | `/usr/bin/rustdesk` *(или `rustdesk`)* | *(пусто)* или `--minimized` *(запуск в трей)* |
| **GNOME Календарь** | `Calendar` *(или `Календарь`)* | `/usr/bin/gnome-calendar` | *(пусто)* |
| **KDE Календарь** | `Calendar` | `/usr/bin/korganizer` | *(пусто)* |
| **Telegram Desktop** | `Telegram` | `/usr/bin/telegram-desktop` | `-startintray` |
| **Flatpak-приложение** | `Calendar` | `/usr/bin/flatpak` | `run org.gnome.Calendar` |

**Полезные команды терминала Linux для быстрого поиска пути:**
```bash
# 1. Найти путь к бинарному файлу через which или type:
which rustdesk
# Выведет: /usr/bin/rustdesk

which gnome-calendar
# Выведет: /usr/bin/gnome-calendar

# 2. Узнать точную команду из системного .desktop-ярлыка:
grep -E '^Exec=' /usr/share/applications/*calendar*.desktop
# Выведет: Exec=gnome-calendar %U
```

---

### 🚀 Установка и быстрый старт

DropFile доступен для **Windows**, **macOS** и **Linux**. Выберите вашу систему:

### 🪟 1. Установка на Windows (10 и 11)

#### Способ A: Готовый автономный .exe (Рекомендуется для пользователей)
*Установка Python или Git не требуется!*
1. Скачайте файл **`DropFile.exe`** из раздела [GitHub Releases](https://github.com/SaidAuita/DropFile/releases).
2. Запустите `DropFile.exe`.
3. При первом запуске откроется окно настроек:
   - **URL сервера**: адрес FileBrowser (например, `https://files.yourdomain.com` или `http://192.168.1.10:8080`).
   - **Логин** и **Пароль**: учетные данные FileBrowser.
   - **Локальная папка**: каталог на компьютере (по умолчанию `Рабочий стол\DropFile`).
   - **Удаленная папка**: целевая папка в FileBrowser (по умолчанию `/DropFile`).
   - **Язык**: выбор языка интерфейса (доступно 10 языков).
4. Нажмите кнопку **«⚡ Проверить соединение»**, затем **«Сохранить и применить»**.
5. Программа свернется в системный трей и начнет синхронизацию.

#### Способ B: Запуск из исходников и самостоятельная сборка .exe (Windows)
```bash
git clone https://github.com/SaidAuita/DropFile.git
cd DropFile
pip install -r requirements.txt
python DropFile.pyw    # или дважды кликните run.bat
```
Для сборки автономного исполняемого файла дважды кликните `build_exe.bat` или выполните:
```bash
python build_exe.py
```
Готовый автономный файл появится в каталоге `dist\DropFile.exe`.

---

### 🍏 2. Установка на macOS (Catalina 10.15 ... Sequoia / Tahoe)

*Быстрая автоматическая установка в 1 клик:*
1. Склонируйте репозиторий в домашнюю папку в Терминале:
   ```bash
   cd ~
   git clone https://github.com/SaidAuita/DropFile.git
   cd DropFile
   ```
   *(Либо скачайте ZIP-архив с GitHub и распакуйте в `~/DropFile`)*
2. Дважды кликните по файлу **`install_mac.command`** в Finder (или выполните `./install_mac.command` в Терминале):
   - Установщик автоматически создаст изолированное виртуальное окружение (`.venv`) и установит зависимости (включая нативный Cocoa / PyObjC).
   - Соберёт и установит приложение **`/Applications/DropFile.app`** со свойством `LSUIElement=1` (работает в верхнем статус-баре около часов, без лишней иконки в Dock).
   - Создаст удобный ярлык рабочей папки на Рабочем столе (`~/Desktop/DropFile`).
3. В строке меню macOS (вверху экрана около часов) появится иконка облака DropFile. Нажмите её, выберите **«Параметры»**, введите адрес сервера FileBrowser, логин и пароль.

> 📖 **Полное пошаговое руководство по macOS**: см. файл [`doc/mac_install.md`](doc/mac_install.md) (быстрые команды установки Python 3 через `curl` или Homebrew, проверка работы Tkinter, автозапуск через LaunchAgent и решение возможных проблем).

---

### 🐧 3. Установка на Linux (Ubuntu, Debian, Mint, Fedora, Arch)

DropFile поддерживает Linux как на **рабочих станциях Desktop** (с иконкой в системном трее и графическим интерфейсом), так и на **серверах, NAS и мини-ПК** (в виде фонового headless-демона systemd).

#### Способ A: Автоматический скрипт-установщик (Десктоп и Сервер)
1. Склонируйте репозиторий:
   ```bash
   cd ~
   git clone https://github.com/SaidAuita/DropFile.git
   cd DropFile
   ```
2. Запустите автоматический установщик:
   ```bash
   chmod +x install_linux.sh run_linux.sh
   ./install_linux.sh
   ```
   - Создает виртуальное окружение `.venv` и устанавливает зависимости (`requirements-linux.txt`).
   - Создает папку обмена (`~/Desktop/DropFile` или `~/DropFile`).
   - На Desktop: создает ярлык на Рабочем столе и регистрирует приложение в системном меню (`~/.local/share/applications/dropfile.desktop`).
   - На Сервере: регистрирует пользовательскую службу systemd (`~/.config/systemd/user/dropfile.service`).

3. Запустите DropFile:
   ```bash
   ./run_linux.sh              # Режим Desktop с системным треем
   ./run_linux.sh --settings   # Открыть окно настроек
   ./run_linux.sh --headless   # Фоновый серверный режим (без GUI)
   ```

#### Способ B: Фоновый серверный демон systemd (Рекомендуется для серверов)
Для непрерывной фоновой синхронизации на сервере или мини-ПК:
```bash
# Включить автозапуск при старте системы и запустить службу прямо сейчас:
systemctl --user enable --now dropfile.service

# Проверить статус службы:
systemctl --user status dropfile.service

# Просмотр журнала синхронизации в реальном времени:
journalctl --user -u dropfile.service -f

# Остановить службу:
systemctl --user stop dropfile.service
```

#### Способ C: Управление через командную строку (CLI)
Управляйте работающим фоновым процессом DropFile из любого терминала или bash-скрипта:
```bash
./run_linux.sh --status       # Запрос статуса синхронизации через IPC сокет
./run_linux.sh --sync-now     # Мгновенно проверить и синхронизировать файлы
./run_linux.sh --pause        # Приостановить синхронизацию
./run_linux.sh --resume       # Возобновить синхронизацию
./run_linux.sh --stop         # Корректно остановить фоновый процесс
./run_linux.sh --help         # Справка по всем доступным параметрам
```

#### Способ D: Автономный исполняемый файл Linux (PyInstaller)
Скомпилируйте единый бинарный файл `dist/dropfile`, не требующий установки Python и библиотек у пользователей:
```bash
pip install pyinstaller
python3 build_linux.py
```
> 📖 **Полная документация по Linux**: см. подробное руководство в [`README_LINUX.md`](README_LINUX.md).

---

## 📦 Синхронизация сборок проектов и ротация версий

В **DropFile** встроен специализированный фоновый модуль для разработчиков и систем автоматической сборки проектов, у которых периодически формируются исполняемые файлы, дистрибутивы и архивы сборок (например, `*.zip`, `*.7z`, `*.exe`, `*.tar.gz`) в нескольких рабочих каталогах.

```
Локальный ПК:                              Сетевой диск / Сервер обмена:
[Проект 1 / Build_DEV] --(авто-синхр.)--> \\192.168.1.4\Exchange\Build\Project_1\ (хранит последние 5)
[Проект 2 / Build_DEV] --(авто-синхр.)--> \\192.168.1.4\Exchange\Build\Project_2\ (хранит последние 5)
```

### Ключевые возможности:
1. **Мониторинг нескольких каталогов сборок**:
   - Добавляйте произвольное количество заданий для разных проектов (например, `C:\_CODE\AI Code Pro\Build_DEV`, `C:\_CODE\ID Code Pro\Build_DEV`).
   - Для каждого задания настраивается индивидуальная маска файлов (по умолчанию `*.zip`, либо `*.7z`, `App_*.zip` и т.д.).
2. **Персональные папки на сервере обмена**:
   - Каждый проект отправляется в свой отдельный каталог на сервере или сетевой папке SMB (например, `\\192.168.1.4\Exchange\Build\AI_Code_Pro\`).
   - Билды разных проектов не перемешиваются и готовы для загрузки тестировщиками или удаленными машинами.
3. **Автоматическая ротация версий ($N$ сборок)**:
   - Для каждого проекта задается параметр `keep_versions` (по умолчанию 5).
   - На сервере сохраняются только $N$ самых свежих сборок. Старые версии автоматически удаляются при появлении новых, предотвращая переполнение дискового пространства.
4. **Мгновенный подхват ранее созданных архивов**:
   - Файлы сборок, созданные до настройки DropFile или до запуска программы, автоматически определяются и передаются на сервер на первом же проходе.
   - Если в локальной папке уже накопилось больше $N$ версий, программа автоматически сортирует их по времени изменения и копирует только последние $N$ версий, не тратя трафик на устаревшие файлы.
5. **Защита от записи (Debounce и Exclusive Lock)**:
   - Исключена передача поврежденных файлов, пока компилятор или архиватор продолжает формировать билд.
   - Движок контролирует стабилизацию размера файла и проверяет эксклюзивный доступ перед началом копирования.
6. **Атомарное безопасное копирование**:
   - Файлы копируются под временными именами `.tmp_*` и атомарно переименовываются по завершении, гарантируя целостность архивов на сервере.
7. **Интерфейс управления и фоновый контроль**:
   - Отдельное окно **«Синхронизация сборок»**, доступное из системного трея или окна настроек.
   - Удобное добавление/редактирование заданий с автоподстановкой путей.
   - Кнопка **«Синхронизировать сейчас»** для мгновенного запуска проверки по всем проектам.
   - Глобальный тумблер включения/выключения синхронизации сборок.

---

### 🔄 Обновление

#### Способ 1: Автоматическое обновление из программы (в 1 клик)
- Нажмите кнопку **«🔍 Проверить обновления»** в шапке окна настроек или пункт **«🔄 Проверить обновления...»** в меню системного трея / строки меню macOS.
- При наличии новой версии DropFile скачает обновление, выполнит безопасную замену файлов и автоматически перезапустится в фоне.

#### Способ 2: Ручное обновление через Терминал (macOS, Linux и запуск из исходников)
Если вы устанавливали DropFile через `git clone`, обновиться можно в любой момент прямо в Терминале:
```bash
cd ~/DropFile
git pull origin main
```
> 💡 **Решение конфликтов при обновлении**: если в папке остались локальные изменения и Git выдаёт ошибку *«Your local changes would be overwritten by merge»*, спрячьте локальные правки в stash и скачайте чистый релиз:
> ```bash
> cd ~/DropFile
> git stash
> git pull origin main
> ```

> 🍏 **Важно для пользователей macOS**: после выполнения `git pull` заново собирать файл приложения **НЕ требуется**! Приложение `/Applications/DropFile.app` устроено как нативный лаунчер, который сразу запускает обновленный код из папки `~/DropFile`. Достаточно просто перезапустить программу через верхнюю строку меню (`Выход` -> снова открыть `/Applications/DropFile.app`).

---

## 🛠️ Другие проекты

* **[RyzenQuiet PRO](https://github.com/SaidAuita/RyzenQuietPro)** — Элегантный и легковесный аппаратный HUD и оптимизатор планов электропитания для Windows с переключением AMD Ryzen CPB и телеметрией энергопотребления GPU в реальном времени.
* **[ComfyUI Photoshop Plugin (PH-CU-S)](https://github.com/SaidAuita/ComfyUI_PH-CU-S)** — Мощный плагин для Photoshop на базе ComfyUI, обеспечивающий прямую интеграцию с локальными генеративными моделями.
* **[Free Automation Tools & Utilities](https://ph-cu-s.com/tools)** — Бесплатные открытые скрипты, расширения и утилиты для Adobe Illustrator, InDesign, Photoshop и рабочих процессов Windows.

---

## 📄 License / Лицензия

Distributed under the open-source [MIT License](LICENSE).
