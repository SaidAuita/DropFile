"""
Windows integration utilities for DropFile.
Re-exports cross-platform implementations from platform_utils.py for backward compatibility.
"""

from platform_utils import (
    APP_NAME,
    copy_to_clipboard,
    create_desktop_shortcut,
    ensure_macos_tk_compatibility,
    is_autostart_enabled,
    is_windows_autostart_enabled,
    open_folder_in_explorer,
    open_folder_in_file_manager,
    remove_desktop_shortcut,
    restart_dropfile,
    set_autostart,
    set_windows_autostart,
    spawn_settings_process,
    acquire_single_instance_lock,
    release_single_instance_lock,
    send_instance_command,
    stop_running_instance,
    create_network_shortcut,
    get_available_drive_letters,
    map_network_drive,
    detect_network_environment,
    get_default_lan_server_host,
    detect_lan_server_host,
    normalize_lan_host,
    format_lan_share_path,
)



