"""
DropFile — Background Dropbox-like file synchronization utility.
Main entry point. Runs silently in the background with system tray integration.
"""

import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

# Add project directory to sys.path and set cwd
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
try:
    os.chdir(BASE_DIR)
except Exception:
    pass

# If running as frozen PyInstaller executable, clean PyInstaller internal variables
# from os.environ so any spawned subprocesses run as fresh root instances without parent checks
if getattr(sys, "frozen", False):
    for k in list(os.environ.keys()):
        if k.startswith(("_PYI", "PYI", "_MEI")):
            os.environ.pop(k, None)
    if hasattr(sys, "_MEIPASS"):
        try:
            os.add_dll_directory(sys._MEIPASS)
        except Exception:
            pass

from platform_utils import (
    acquire_single_instance_lock,
    create_desktop_shortcut,
    ensure_macos_tk_compatibility,
    install_systemd_user_service,
    release_single_instance_lock,
    restart_dropfile,
    spawn_settings_process,
    uninstall_systemd_user_service,
)

# Ensure macOS Tkinter [NSApp macOSVersion] selector compatibility
ensure_macos_tk_compatibility()

# Configure macOS Cocoa activation policy: hide Dock icon for background tray agent.
# In --settings mode, do NOT touch NSApplication here so Tkinter can initialize TKApplication naturally.
if sys.platform == "darwin" and "--settings" not in sys.argv:
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
        ns_app = NSApplication.sharedApplication()
        ns_app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    except Exception:
        pass

from config import Config, get_app_dir
from fb_client import FileBrowserClient

def _alert_missing_tkinter() -> None:
    """Alerts the user when Tkinter is missing on the system."""
    msg = (
        "DropFile Settings dialog requires Python Tkinter (_tkinter).\n\n"
        "To fix on Homebrew, run in Terminal:\n"
        "  brew install python-tk\n\n"
        "Or install official Python with built-in Tkinter from:\n"
        "  https://www.python.org/downloads/macos/"
    )
    print(f"\n[DropFile Warning] {msg}\n", file=sys.stderr)
    if sys.platform == "darwin":
        try:
            import subprocess
            s_msg = msg.replace('"', '\\"').replace("'", "")
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'display alert "DropFile — Tkinter Required" message "{s_msg}" as critical',
                ],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass

try:
    from gui_settings import SettingsDialog
except Exception:
    SettingsDialog = None

from state_db import StateDatabase
from sync_engine import SyncEngine
try:
    from tray import DropFileTray
except Exception:
    DropFileTray = None
from version import __version__

SINGLE_INSTANCE_PORT = 49195
INSTANCE_SOCKET: Optional[socket.socket] = None
_CLEANUP_CALLBACK: Optional[Callable[[], None]] = None
_ENGINE_REF: Optional[Any] = None
_CURRENT_STATUS: str = "Ready"


def release_instance_socket() -> None:
    """Closes the single-instance lock socket and OS mutex immediately to allow restart handover."""
    global INSTANCE_SOCKET
    if INSTANCE_SOCKET:
        try:
            INSTANCE_SOCKET.close()
        except Exception:
            pass
        INSTANCE_SOCKET = None
    release_single_instance_lock()


_SHOW_SETTINGS_FN: Optional[Callable[[], None]] = None
_ACTIVE_SETTINGS_PROC: Optional[Any] = None
_TRAY_REF: Optional[Any] = None
_IS_HEADLESS: bool = False



def trigger_show_settings(tab: Optional[str] = None) -> None:
    """Safely opens settings dialog or brings existing one to front without spawning duplicate processes."""
    global _ACTIVE_SETTINGS_PROC, _SHOW_SETTINGS_FN
    if sys.platform != "win32":
        if _ACTIVE_SETTINGS_PROC is not None:
            if _ACTIVE_SETTINGS_PROC.poll() is None:
                return
            _ACTIVE_SETTINGS_PROC = None
        _ACTIVE_SETTINGS_PROC = spawn_settings_process(tab=tab)
    else:
        if _SHOW_SETTINGS_FN is not None:
            threading.Thread(target=lambda: _SHOW_SETTINGS_FN(initial_tab=tab), daemon=True).start()
        else:
            if _ACTIVE_SETTINGS_PROC is not None:
                if _ACTIVE_SETTINGS_PROC.poll() is None:
                    return
                _ACTIVE_SETTINGS_PROC = None
            _ACTIVE_SETTINGS_PROC = spawn_settings_process(tab=tab)


def send_ipc_query(cmd: str, timeout: float = 2.0) -> Optional[str]:
    """Sends an IPC command to the running DropFile instance and returns the reply string."""
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(("127.0.0.1", SINGLE_INSTANCE_PORT))
        payload = cmd.encode("utf-8") if cmd.endswith("\n") else (cmd + "\n").encode("utf-8")
        s.sendall(payload)
        response = s.recv(2048).decode("utf-8", errors="ignore").strip()
        s.close()
        return response
    except Exception:
        if s:
            try:
                s.close()
            except Exception:
                pass
        return None


def _handle_duplicate_instance() -> None:
    """Signals existing instance and terminates the duplicate process immediately."""
    try:
        notify_s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        notify_s.settimeout(2.0)
        notify_s.connect(("127.0.0.1", SINGLE_INSTANCE_PORT))
        if "--settings" in sys.argv:
            tab = None
            if "--tab" in sys.argv:
                try:
                    idx = sys.argv.index("--tab")
                    if idx + 1 < len(sys.argv):
                        tab = sys.argv[idx + 1]
                except Exception:
                    pass
            payload = f"SHOW_SETTINGS:{tab}\n" if tab else "SHOW_SETTINGS\n"
            notify_s.sendall(payload.encode("utf-8"))
        elif "--folder" in sys.argv or "--open" in sys.argv:
            notify_s.sendall(b"OPEN_FOLDER\n")
        else:
            notify_s.sendall(b"LAUNCH_ACTION\n")
        notify_s.close()
    except Exception as e:
        print(f"[DropFile] Note: could not send notification to existing instance: {e}")

    if sys.platform == "darwin":
        try:
            import subprocess
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    'display notification "DropFile is already running in the top menu bar." with title "DropFile"',
                ],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            pass

    print("[DropFile] Another instance of DropFile is already running. Exiting duplicate.")
    if "unittest" in sys.modules or "pytest" in sys.modules:
        sys.exit(0)
    else:
        os._exit(0)


def _start_instance_command_listener(sock: socket.socket) -> None:
    """Background listener for IPC commands (SHOW_SETTINGS, STATUS, SYNC_NOW, PAUSE, RESUME, QUIT, RESTART)."""
    def listener():
        global _CLEANUP_CALLBACK, _ENGINE_REF, _CURRENT_STATUS
        while sock and sock == INSTANCE_SOCKET:
            try:
                conn, _ = sock.accept()
            except Exception:
                break

            try:
                conn.settimeout(4.0)
                data = conn.recv(1024)
                if not data:
                    continue

                cmd = data.strip().decode("utf-8", errors="ignore")

                if cmd.startswith("SHOW_SETTINGS"):
                    target_tab = None
                    if ":" in cmd:
                        target_tab = cmd.split(":", 1)[1].strip()
                    trigger_show_settings(tab=target_tab)
                    try:
                        conn.sendall(b"OK: Settings triggered\n")
                    except Exception:
                        pass
                elif cmd == "LAUNCH_ACTION":
                    if not _ENGINE_REF or not _ENGINE_REF.config.server_url or not _ENGINE_REF.config.username:
                        trigger_show_settings()
                    else:
                        open_folder_in_file_manager(_ENGINE_REF.config.local_path)
                        if _TRAY_REF:
                            try:
                                _TRAY_REF.send_notification("DropFile", t("tray_already_running_hint"))
                            except Exception:
                                pass
                    try:
                        conn.sendall(b"OK: Launch handled\n")
                    except Exception:
                        pass
                elif cmd == "OPEN_FOLDER":
                    if _ENGINE_REF:
                        open_folder_in_file_manager(_ENGINE_REF.config.local_path)
                    try:
                        conn.sendall(b"OK: Folder opened\n")
                    except Exception:
                        pass
                elif cmd == "RELOAD_CONFIG":
                    if _ENGINE_REF:
                        try:
                            _ENGINE_REF.config.load()
                            _ENGINE_REF.apply_server_connection(_ENGINE_REF.active_server_index)
                            print("[DropFile] Config reloaded via IPC.")
                            conn.sendall(b"OK: Config reloaded\n")
                        except Exception as e:
                            conn.sendall(f"ERR: {e}\n".encode("utf-8"))
                    else:
                        conn.sendall(b"ERR: Engine not active\n")
                elif cmd in ("QUIT", "TERMINATE", "STOP"):
                    print("[DropFile] IPC QUIT received. Shutting down...")
                    try:
                        conn.sendall(b"OK: Shutting down\n")
                    except Exception:
                        pass
                    try:
                        conn.close()
                    except Exception:
                        pass
                    if _CLEANUP_CALLBACK:
                        try:
                            _CLEANUP_CALLBACK()
                        except Exception:
                            pass
                    release_instance_socket()
                    os._exit(0)

                elif cmd == "RESTART":
                    print("[DropFile] IPC RESTART received. Restarting...")
                    try:
                        conn.sendall(b"OK: Restarting\n")
                    except Exception:
                        pass
                    try:
                        conn.close()
                    except Exception:
                        pass
                    if _CLEANUP_CALLBACK:
                        try:
                            _CLEANUP_CALLBACK()
                        except Exception:
                            pass
                    release_instance_socket()
                    restart_dropfile(kill_existing=False)
                    os._exit(0)
                elif cmd == "HAS_TRAY":
                    reply = "NO\n" if _IS_HEADLESS else "YES\n"
                    try:
                        conn.sendall(reply.encode("utf-8"))
                    except Exception:
                        pass
                elif cmd == "STATUS":
                    state = _ENGINE_REF.current_state if _ENGINE_REF else "idle"
                    reply = f"DropFile v{__version__} [{state}]: {_CURRENT_STATUS}\n"
                    try:
                        conn.sendall(reply.encode("utf-8"))
                    except Exception:
                        pass
                elif cmd == "SYNC_NOW":
                    if _ENGINE_REF:
                        _ENGINE_REF.trigger_sync_now()
                        try:
                            conn.sendall(b"OK: Sync triggered\n")
                        except Exception:
                            pass
                    else:
                        try:
                            conn.sendall(b"ERR: Engine not active\n")
                        except Exception:
                            pass
                elif cmd == "PAUSE":
                    if _ENGINE_REF:
                        _ENGINE_REF.pause()
                        try:
                            conn.sendall(b"OK: Sync paused\n")
                        except Exception:
                            pass
                elif cmd == "RESUME":
                    if _ENGINE_REF:
                        _ENGINE_REF.resume()
                        try:
                            conn.sendall(b"OK: Sync resumed\n")
                        except Exception:
                            pass
            except Exception as e:
                print(f"[DropFile IPC] Error handling command: {e}")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    t = threading.Thread(target=listener, daemon=True, name="DropFile-IPC-Listener")
    t.start()


def run_headless(config: Config, engine: SyncEngine) -> None:
    """Runs the sync engine in headless / daemon mode without any GUI or system tray."""
    import signal

    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] DropFile v{__version__} running in headless daemon mode")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Server URL:   {config.server_url or '(not configured)'}")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Local Folder:  {config.local_path}")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Remote Folder: {config.remote_path}")

    stop_event = threading.Event()

    def _sig_handler(sig, frame):
        sig_name = "SIGTERM" if getattr(signal, "SIGTERM", None) == sig else "SIGINT"
        print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Received {sig_name}. Stopping engine gracefully...")
        stop_event.set()

    signal.signal(signal.SIGINT, _sig_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _sig_handler)

    engine.start()
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Sync engine active. Press Ctrl+C or send SIGTERM/SIGINT to stop.")

    try:
        while not stop_event.is_set():
            stop_event.wait(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Shutting down sync engine...")
        try:
            engine.stop()
        except Exception:
            pass
        release_instance_socket()
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] DropFile daemon stopped cleanly.")


def ensure_single_instance(is_headless: bool = False) -> Optional[socket.socket]:
    """
    Ensures strictly one background instance of DropFile runs at a time.
    Requires BOTH:
    1. OS-level exclusive lock (Win32 Mutex on Windows / fcntl.flock on macOS/Linux).
    2. TCP socket bind on localhost:49195.
    If EITHER fails, another instance is already running.
    If current process is interactive GUI (not is_headless) and existing instance has NO tray,
    the headless daemon is terminated so the GUI can take over.
    """
    global INSTANCE_SOCKET

    # 1. OS-level atomic single-instance lock with retry
    locked = False
    for _ in range(4):
        if acquire_single_instance_lock():
            locked = True
            break
        time.sleep(0.2)

    if not locked:
        if not is_headless:
            tray_status = send_ipc_query("HAS_TRAY", timeout=1.0)
            if tray_status != "YES":
                print("[DropFile] Existing instance is headless or missing tray. Terminating it to start GUI tray...")
                send_ipc_query("QUIT", timeout=1.5)
                time.sleep(0.4)
                for _ in range(5):
                    if acquire_single_instance_lock():
                        locked = True
                        break
                    time.sleep(0.2)
        if not locked:
            _handle_duplicate_instance()

    # 2. Bind IPC command socket listener (strictly exclusive) with retry
    s = None
    for _ in range(4):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if sys.platform != "win32":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
            s.listen(2)
            INSTANCE_SOCKET = s
            _start_instance_command_listener(s)
            return s
        except Exception:
            if s:
                try:
                    s.close()
                except Exception:
                    pass
            time.sleep(0.2)

    if not is_headless:
        tray_status = send_ipc_query("HAS_TRAY", timeout=1.0)
        if tray_status != "YES":
            print("[DropFile] Port bound by headless daemon. Terminating it to take over as GUI...")
            send_ipc_query("QUIT", timeout=1.5)
            time.sleep(0.4)
            for _ in range(5):
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    if sys.platform != "win32":
                        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
                    s.listen(2)
                    INSTANCE_SOCKET = s
                    _start_instance_command_listener(s)
                    return s
                except Exception:
                    if s:
                        try:
                            s.close()
                        except Exception:
                            pass
                    time.sleep(0.2)

    print(f"[DropFile] Socket port {SINGLE_INSTANCE_PORT} already bound. Another instance is running.")
    release_single_instance_lock()
    _handle_duplicate_instance()



def main():
    # 0. Handle CLI utility arguments
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(f"DropFile v{__version__} — Dropbox-style synchronization for FileBrowser\n")
        print("Usage:")
        print("  python3 DropFile.pyw [options]\n")
        print("Options:")
        print("  --headless, --daemon      Run as background daemon (no GUI / no system tray)")
        print("  --settings                Open GUI Settings dialog")
        print("  --status                  Query status of running background instance")
        print("  --sync-now                Trigger immediate synchronization")
        print("  --pause                   Pause synchronization")
        print("  --resume                  Resume synchronization")
        print("  --stop, --quit            Stop running background instance")
        print("  --install-service         Install and enable systemd user service (Linux)")
        print("  --uninstall-service       Uninstall systemd user service (Linux)")
        print("  --version, -v             Display version and exit")
        print("  --help, -h                Display this help message")
        sys.exit(0)

    if "--version" in args or "-v" in args:
        print(f"DropFile v{__version__}")
        sys.exit(0)

    if "--status" in args:
        res = send_ipc_query("STATUS")
        if res:
            print(res)
            sys.exit(0)
        else:
            print("DropFile is not currently running.")
            sys.exit(1)

    if "--sync-now" in args:
        res = send_ipc_query("SYNC_NOW")
        if res:
            print(res)
            sys.exit(0)
        else:
            print("Error: DropFile is not running.")
            sys.exit(1)

    if "--pause" in args:
        res = send_ipc_query("PAUSE")
        if res:
            print(res)
            sys.exit(0)
        else:
            print("Error: DropFile is not running.")
            sys.exit(1)

    if "--resume" in args:
        res = send_ipc_query("RESUME")
        if res:
            print(res)
            sys.exit(0)
        else:
            print("Error: DropFile is not running.")
            sys.exit(1)

    if "--stop" in args or "--quit" in args:
        res = send_ipc_query("QUIT")
        if res:
            print(res)
            sys.exit(0)
        else:
            print("DropFile is not running.")
            sys.exit(0)

    if "--install-service" in args:
        if sys.platform.startswith("linux"):
            if install_systemd_user_service():
                print("To start the service now, run:")
                print("  systemctl --user start dropfile.service")
                print("To view live logs:")
                print("  journalctl --user -u dropfile.service -f")
                sys.exit(0)
            sys.exit(1)
        else:
            print("--install-service is only supported on Linux (systemd).")
            sys.exit(1)

    if "--uninstall-service" in args:
        if sys.platform.startswith("linux"):
            uninstall_systemd_user_service()
            sys.exit(0)
        else:
            print("--uninstall-service is only supported on Linux (systemd).")
            sys.exit(1)

    # Detect headless mode (explicit flag or Linux server without DISPLAY)
    global _IS_HEADLESS
    is_headless = (
        "--headless" in args
        or "--daemon" in args
        or (
            sys.platform.startswith("linux")
            and not os.environ.get("DISPLAY")
            and not os.environ.get("WAYLAND_DISPLAY")
        )
    )
    _IS_HEADLESS = is_headless

    # If invoked with --settings, open Settings UI directly on the main thread
    if "--settings" in sys.argv:
        if SettingsDialog is None:
            _alert_missing_tkinter()
            sys.exit(1)
        config = Config()
        db_path = config.config_dir / "state.db"
        state_db = StateDatabase(db_path)
        client = FileBrowserClient(
            base_url=config.server_url,
            username=config.username,
            password=config.password,
        )
        engine = SyncEngine(config=config, state_db=state_db, client=client)

        initial_tab = None
        if "--tab" in sys.argv:
            try:
                t_idx = sys.argv.index("--tab")
                if t_idx + 1 < len(sys.argv):
                    initial_tab = sys.argv[t_idx + 1]
            except Exception:
                pass

        restart_initiated = False

        def on_settings_process_save():
            nonlocal restart_initiated
            # Notify running background instance via IPC to reload config and trigger sync
            res = send_ipc_query("RELOAD_CONFIG", timeout=1.5)
            has_tray = send_ipc_query("HAS_TRAY", timeout=1.0)
            if res and has_tray == "YES":
                send_ipc_query("SYNC_NOW", timeout=1.5)
            else:
                # Primary daemon was either not running or running without tray! Start/restart full GUI!
                print("[DropFile --settings] No active tray instance detected. Starting DropFile GUI...")
                restart_initiated = True
                restart_dropfile(kill_existing=True)

        def on_settings_process_restart():
            nonlocal restart_initiated
            print("[DropFile --settings] Restart requested. Terminating primary instance and launching new...")
            restart_initiated = True
            restart_dropfile(kill_existing=True)
            os._exit(0)

        settings_dialog = SettingsDialog(
            config=config,
            state_db=state_db,
            client=client,
            engine=engine,
            on_save_callback=on_settings_process_save,
            on_restart_callback=on_settings_process_restart,
            on_cleanup_callback=None,
        )
        settings_dialog.show(initial_tab=initial_tab)

        # After settings window closes, ensure primary background instance is running with tray
        if not restart_initiated:
            has_tray = None
            for _ in range(3):
                has_tray = send_ipc_query("HAS_TRAY", timeout=0.8)
                if has_tray == "YES":
                    break
                time.sleep(0.3)
            if has_tray != "YES":
                print("[DropFile --settings] Active tray instance not running after settings closed. Starting DropFile GUI...")
                restart_dropfile(kill_existing=True)

        sys.exit(0)

    # 1. Single instance lock (with headless handover to GUI)
    _instance_sock = ensure_single_instance(is_headless=is_headless)

    # 2. Load configuration
    config = Config()

    # 3. Ensure local sync folder and optional desktop shortcut exist
    local_folder = config.local_path
    local_folder.mkdir(parents=True, exist_ok=True)
    if config.desktop_shortcut and not is_headless:
        create_desktop_shortcut(local_folder)

    # 4. Initialize Database
    db_path = config.config_dir / "state.db"
    state_db = StateDatabase(db_path)

    # 5. Initialize API Client
    client = FileBrowserClient(
        base_url=config.server_url,
        username=config.username,
        password=config.password,
    )

    # 6. Initialize Sync Engine
    engine = SyncEngine(
        config=config,
        state_db=state_db,
        client=client,
    )
    global _ENGINE_REF, _CLEANUP_CALLBACK, _TRAY_REF
    _ENGINE_REF = engine

    def on_status_change(text: str, state: str):
        global _CURRENT_STATUS
        _CURRENT_STATUS = text
        if is_headless:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{state.upper()}] {text}")

    engine.on_status_change = on_status_change

    # Callback when user updates settings in GUI
    def on_settings_saved():
        print("[DropFile] Settings updated. Re-authenticating and triggering sync...")
        def _bg_auth_and_sync():
            try:
                client.login()
                engine.trigger_sync_now()
            except Exception as e:
                print(f"[DropFile] Re-authentication failed: {e}")
        threading.Thread(target=_bg_auth_and_sync, daemon=True).start()
        try:
            if _TRAY_REF:
                _TRAY_REF.refresh_menu()
        except Exception:
            pass

    # Clean up sockets, engine, and tray before restart or self-update
    def on_cleanup():
        print("[DropFile] Stopping engine and releasing instance socket...")
        release_instance_socket()
        try:
            engine.stop()
        except Exception:
            pass
        try:
            if _TRAY_REF and _TRAY_REF._icon:
                _TRAY_REF._icon.stop()
        except Exception:
            pass

    _CLEANUP_CALLBACK = on_cleanup

    # Callback when user clicks Save and Restart
    def on_restart():
        print("[DropFile] Restart requested. Spawning new process...")
        on_cleanup()
        time.sleep(0.3)
        restart_dropfile(kill_existing=False)
        os._exit(0)

    # If headless mode, run daemon directly without GUI or tray
    if is_headless:
        run_headless(config, engine)
        sys.exit(0)

    # 7. Initialize Settings Dialog
    if SettingsDialog is not None:
        settings_dialog = SettingsDialog(
            config=config,
            state_db=state_db,
            client=client,
            on_save_callback=on_settings_saved,
            on_restart_callback=on_restart,
            on_cleanup_callback=on_cleanup,
            engine=engine,
        )
    else:
        settings_dialog = None

    global _SHOW_SETTINGS_FN
    if settings_dialog is not None:
        _SHOW_SETTINGS_FN = settings_dialog.show

    # Prompt user with settings dialog if server URL or username is not configured
    if not config.server_url or not config.username:
        if SettingsDialog is None:
            _alert_missing_tkinter()
        else:
            trigger_show_settings()

    if DropFileTray is None:
        print("[DropFile] Tray module not available. Running in headless daemon mode...")
        run_headless(config, engine)
        sys.exit(0)

    # 8. Start System Tray
    tray = DropFileTray(
        config=config,
        engine=engine,
        settings_dialog=settings_dialog,
        on_cleanup_callback=on_cleanup,
    )
    _TRAY_REF = tray


    tray_started = False
    for attempt in range(3):
        try:
            tray.run()
            tray_started = True
            break
        except KeyboardInterrupt:
            engine.stop()
            sys.exit(0)
        except Exception as e:
            print(f"[DropFile] Tray run attempt {attempt+1}/3 failed ({e}). Retrying in 1.2s...")
            time.sleep(1.2)

    if not tray_started:
        print("[DropFile] Tray failed after 3 attempts. Falling back to headless daemon mode...")
        run_headless(config, engine)


def _handle_fatal_exception(exc: BaseException) -> None:
    """Logs fatal exceptions and alerts the user with a native modal dialog."""
    import subprocess
    import traceback
    err_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    print(f"[DropFile FATAL CRASH] {err_text}", file=sys.stderr)

    crash_log = None
    try:
        crash_log = get_app_dir() / "dropfile_crash.log"
        with open(crash_log, "a", encoding="utf-8") as f:
            f.write(f"\n=== Crash: {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            f.write(err_text)
    except Exception:
        try:
            crash_log = Path.home() / "dropfile_crash.log"
            with open(crash_log, "a", encoding="utf-8") as f:
                f.write(f"\n=== Crash: {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                f.write(err_text)
        except Exception:
            pass

    if sys.platform == "darwin":
        try:
            msg_short = str(exc).replace('"', '\\"').replace("'", "")[:200]
            log_str = str(crash_log).replace('"', '\\"') if crash_log else "~/dropfile_crash.log"
            script = f'display alert "DropFile Error" message "DropFile could not start:\n\n{msg_short}\n\nError log: {log_str}" as critical'
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
        except Exception:
            pass
    elif sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"DropFile encountered a fatal startup error:\n\n{str(exc)[:300]}\n\nLog: {crash_log}",
                "DropFile Error",
                0x10,
            )
        except Exception:
            pass
    elif sys.platform.startswith("linux"):
        try:
            msg_short = str(exc).replace('"', '\\"').replace("'", "")[:200]
            subprocess.run(
                ["notify-send", "-u", "critical", "DropFile Error", f"DropFile could not start:\n\n{msg_short}"],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        pass
    except BaseException as e:
        _handle_fatal_exception(e)
        sys.exit(1)
