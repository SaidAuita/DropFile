"""
Windows integration utilities for DropFile.
Re-exports cross-platform implementations from platform_utils.py for backward compatibility.
"""

from platform_utils import (
    APP_NAME,
    copy_to_clipboard,
    create_desktop_shortcut,
    is_autostart_enabled,
    is_windows_autostart_enabled,
    open_folder_in_explorer,
    open_folder_in_file_manager,
    remove_desktop_shortcut,
    restart_dropfile,
    set_autostart,
    set_windows_autostart,
)


