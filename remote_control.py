"""
DropFile Remote Control & Emergency Actions Protocol.
Provides secure, out-of-band management of remote computers over FileBrowser synchronization.
Supports:
- kill_process (closing hung or unwanted apps like HAPP, RustDesk, etc.)
- reboot (emergency system reboot)
- list_processes (querying active processes when GUI hangs)
- device discovery (heartbeat via device_{hostname}.json)

Security:
- No arbitrary shell commands (strictly whitelisted actions).
- HMAC-SHA256 signature verification over (cmd_id, target, action, payload, timestamp).
- Freshness window (timestamp <= 180s) prevents replay attacks.
- Configurable process whitelist and optional strict whitelist mode.
"""

import hashlib
import hmac
import json
import os
import platform
import socket
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from fb_client import FileBrowserClient
from platform_utils import kill_process_by_name, list_system_processes, reboot_system

ACTION_KILL_PROCESS = "kill_process"
ACTION_REBOOT = "reboot"
ACTION_LIST_PROCESSES = "list_processes"
VALID_ACTIONS = {ACTION_KILL_PROCESS, ACTION_REBOOT, ACTION_LIST_PROCESSES}

COMMAND_FRESHNESS_SECONDS = 180.0  # 3 minutes expiration window
CONTROL_DIR_NAME = ".dropfile_control"


def get_control_remote_dir(remote_root: str) -> str:
    """Returns the remote path for the control directory, e.g. /DropFile/.dropfile_control."""
    clean = remote_root.strip("/")
    return f"/{clean}/{CONTROL_DIR_NAME}" if clean else f"/{CONTROL_DIR_NAME}"


def compute_signature(secret_pin: str, cmd_id: str, target: str, action: str, payload_str: str, timestamp: float) -> str:
    """
    Computes HMAC-SHA256 signature for a command packet.
    """
    secret_bytes = secret_pin.strip().encode("utf-8")
    msg = f"{cmd_id}:{target.strip().lower()}:{action.strip()}:{payload_str}:{int(timestamp)}".encode("utf-8")
    return hmac.new(secret_bytes, msg, hashlib.sha256).hexdigest()


def create_command_packet(
    target_device: str,
    sender_device: str,
    action: str,
    payload: Dict[str, Any],
    secret_pin: str,
) -> Dict[str, Any]:
    """
    Builds a signed command dictionary ready for transmission.
    """
    cmd_id = uuid.uuid4().hex[:8]
    ts = time.time()
    payload_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    sig = compute_signature(secret_pin, cmd_id, target_device, action, payload_str, ts)
    return {
        "id": cmd_id,
        "target": target_device.strip(),
        "sender": sender_device.strip(),
        "action": action.strip(),
        "payload": payload,
        "timestamp": ts,
        "signature": sig,
    }


def verify_command_packet(
    packet: Dict[str, Any],
    local_device_name: str,
    local_pin: str,
    allow_reboot: bool = True,
    allow_process_list: bool = True,
    whitelist: Optional[List[str]] = None,
    strict_whitelist: bool = False,
) -> Tuple[bool, str]:
    """
    Validates the authenticity and authorization of an incoming command packet.
    Returns (is_valid: bool, error_message: str).
    """
    if not isinstance(packet, dict):
        return False, "Invalid packet structure"

    target = str(packet.get("target", "")).strip()
    if target.lower() != local_device_name.strip().lower():
        return False, f"Target mismatch: got '{target}', expected '{local_device_name}'"

    action = str(packet.get("action", "")).strip()
    if action not in VALID_ACTIONS:
        return False, f"Unsupported action: '{action}'"

    cmd_id = str(packet.get("id", "")).strip()
    if not cmd_id:
        return False, "Missing command ID"

    try:
        ts = float(packet.get("timestamp", 0.0))
    except (ValueError, TypeError):
        return False, "Invalid timestamp"

    now = time.time()
    if abs(now - ts) > COMMAND_FRESHNESS_SECONDS:
        return False, f"Command expired (skew: {abs(now - ts):.1f}s > {COMMAND_FRESHNESS_SECONDS}s)"

    payload = packet.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}
    payload_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    given_sig = str(packet.get("signature", "")).strip()
    expected_sig = compute_signature(local_pin, cmd_id, target, action, payload_str, ts)

    if not hmac.compare_digest(given_sig, expected_sig):
        return False, "Authentication failed: invalid PIN or signature"

    # Action-specific policy checks
    if action == ACTION_REBOOT and not allow_reboot:
        return False, "Reboot action is disabled in target computer settings"

    if action == ACTION_LIST_PROCESSES and not allow_process_list:
        return False, "Process listing is disabled in target computer settings"

    if action == ACTION_KILL_PROCESS:
        proc_name = str(payload.get("process_name", "")).strip()
        if not proc_name:
            return False, "Missing process_name parameter"

        if strict_whitelist:
            clean_wl = [w.strip().lower() for w in (whitelist or []) if w.strip()]
            proc_clean = proc_name.lower()
            proc_base = proc_clean[:-4] if proc_clean.endswith(".exe") else proc_clean
            matched = any(proc_clean == w or proc_base == (w[:-4] if w.endswith(".exe") else w) for w in clean_wl)
            if not matched:
                return False, f"Process '{proc_name}' is not in the allowed whitelist"

    return True, ""


def execute_action(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes an authorized action on the local machine and returns result dictionary.
    """
    if action == ACTION_KILL_PROCESS:
        proc_name = str(payload.get("process_name", "")).strip()
        success, msg = kill_process_by_name(proc_name)
        return {
            "success": success,
            "message": msg,
            "action": action,
            "target_process": proc_name,
        }

    elif action == ACTION_REBOOT:
        delay = int(payload.get("delay", 5))
        success, msg = reboot_system(delay_seconds=delay)
        return {
            "success": success,
            "message": msg,
            "action": action,
            "delay": delay,
        }

    elif action == ACTION_LIST_PROCESSES:
        procs = list_system_processes()
        return {
            "success": True,
            "message": f"Retrieved {len(procs)} active processes.",
            "action": action,
            "processes": procs,
        }

    return {"success": False, "message": f"Unknown action: {action}"}


class RemoteControlManager:
    """
    Coordinates remote control polling, device registration, and command exchange
    via FileBrowser REST API across one or more configured server routes.
    """
    def __init__(
        self,
        client: FileBrowserClient,
        remote_path: str,
        secondary_routes: Optional[List[Tuple[FileBrowserClient, str]]] = None,
    ):
        self.client = client
        self.remote_path = remote_path
        self._secondary_routes = list(secondary_routes or [])
        self._last_heartbeat_time = 0.0
        self._executed_cmd_cache: Dict[str, Dict[str, Any]] = {}

    @property
    def control_dir(self) -> str:
        return get_control_remote_dir(self.remote_path)

    @property
    def routes(self) -> List[Tuple[FileBrowserClient, str]]:
        """Returns all configured routes [(client, remote_path), ...]."""
        res = []
        if self.client and self.remote_path:
            res.append((self.client, self.remote_path))
        for c, p in self._secondary_routes:
            if c and p and not any(r[0] == c and r[1] == p for r in res):
                res.append((c, p))
        return res

    def set_routes(self, routes: List[Tuple[FileBrowserClient, str]]) -> None:
        """Updates primary and secondary routes."""
        if routes:
            self.client, self.remote_path = routes[0]
            self._secondary_routes = list(routes[1:])
        else:
            self._secondary_routes = []

    def ensure_control_dir(self) -> bool:
        """Ensures that the remote .dropfile_control directory exists on all available routes."""
        ok_any = False
        for client, remote_path in self.routes:
            try:
                ctrl_dir = get_control_remote_dir(remote_path)
                if client.ensure_remote_dir_exists(ctrl_dir):
                    ok_any = True
            except Exception:
                pass
        return ok_any

    def publish_heartbeat(self, device_info: Dict[str, Any]) -> bool:
        """
        Publishes device presence heartbeat in .dropfile_control/device_{name}.json
        across all configured server routes.
        """
        name = device_info.get("device_name", "").strip()
        if not name:
            return False

        filename = f"device_{name.lower()}.json"
        payload = dict(device_info)
        payload["last_seen"] = time.time()
        payload_str = json.dumps(payload, indent=2, ensure_ascii=False)

        success_count = 0
        for client, remote_path in self.routes:
            try:
                ctrl_dir = get_control_remote_dir(remote_path)
                client.ensure_remote_dir_exists(ctrl_dir)
                remote_file = f"{ctrl_dir}/{filename}"
                if client.write_text_file(remote_file, payload_str):
                    success_count += 1
            except Exception as e:
                print(f"[RemoteControl] Heartbeat error for route {getattr(client, 'base_url', '')}: {e}")

        if success_count > 0:
            self._last_heartbeat_time = time.time()
            return True
        return False

    def get_online_devices(self) -> List[Dict[str, Any]]:
        """
        Fetches all registered devices from .dropfile_control/device_*.json across all routes.
        Merges results and marks device online if seen within 5 minutes on any route.
        """
        devices_by_name: Dict[str, Dict[str, Any]] = {}
        now = time.time()

        for client, remote_path in self.routes:
            try:
                ctrl_dir = get_control_remote_dir(remote_path)
                items = client.list_recursive(ctrl_dir)
                for it in items:
                    if it.name.startswith("device_") and it.name.endswith(".json"):
                        raw = client.read_text_file(it.path)
                        if raw:
                            try:
                                info = json.loads(raw)
                                dev_name = str(info.get("device_name", "")).strip().lower()
                                if not dev_name:
                                    continue
                                last_seen = float(info.get("last_seen", 0.0))
                                is_online = (now - last_seen) < 300.0

                                if dev_name not in devices_by_name or last_seen > devices_by_name[dev_name].get("last_seen", 0.0):
                                    info["is_online"] = is_online
                                    devices_by_name[dev_name] = info
                                elif is_online:
                                    devices_by_name[dev_name]["is_online"] = True
                            except Exception:
                                pass
            except Exception as e:
                print(f"[RemoteControl] Error listing online devices from {getattr(client, 'base_url', '')}: {e}")

        return list(devices_by_name.values())

    def poll_and_dispatch(
        self,
        local_device_name: str,
        local_pin: str,
        allow_reboot: bool,
        allow_process_list: bool,
        whitelist: List[str],
        strict_whitelist: bool,
    ) -> List[Dict[str, Any]]:
        """
        Target machine check: scans .dropfile_control/ across all routes for cmd_{local_device_name}_*.json,
        validates, executes (deduplicating across routes so an action is run once),
        writes response to all routes, and cleans up the command file.
        Returns list of executed command results.
        """
        executed_results = []
        if not local_device_name or not local_pin:
            return executed_results

        # Clean old cached command results older than 5 minutes
        now = time.time()
        self._executed_cmd_cache = {
            k: v for k, v in self._executed_cmd_cache.items()
            if now - v.get("timestamp", 0.0) < 300.0
        }

        target_prefix = f"cmd_{local_device_name.lower()}_"

        for client, remote_path in self.routes:
            try:
                ctrl_dir = get_control_remote_dir(remote_path)
                items = client.list_recursive(ctrl_dir)

                for it in items:
                    if it.is_dir:
                        continue
                    file_lower = it.name.lower()
                    if file_lower.startswith(target_prefix) and file_lower.endswith(".json"):
                        raw = client.read_text_file(it.path)
                        if not raw:
                            continue

                        try:
                            packet = json.loads(raw)
                        except Exception:
                            client.delete_resource(it.path)
                            continue

                        cmd_id = packet.get("id", "unknown")
                        sender = packet.get("sender", "unknown")
                        action = packet.get("action", "unknown")
                        res_filename = f"res_{local_device_name.lower()}_{cmd_id}.json"

                        # Check if already executed on another route during this or recent polling cycle
                        if cmd_id in self._executed_cmd_cache:
                            cached_res = self._executed_cmd_cache[cmd_id]
                            try:
                                client.write_text_file(f"{ctrl_dir}/{res_filename}", json.dumps(cached_res, indent=2))
                                client.delete_resource(it.path)
                            except Exception:
                                pass
                            continue

                        is_valid, err_msg = verify_command_packet(
                            packet=packet,
                            local_device_name=local_device_name,
                            local_pin=local_pin,
                            allow_reboot=allow_reboot,
                            allow_process_list=allow_process_list,
                            whitelist=whitelist,
                            strict_whitelist=strict_whitelist,
                        )

                        if not is_valid:
                            result_packet = {
                                "id": cmd_id,
                                "target": local_device_name,
                                "sender": sender,
                                "action": action,
                                "success": False,
                                "error": err_msg,
                                "timestamp": time.time(),
                            }
                        else:
                            result_data = execute_action(action, packet.get("payload", {}))
                            result_packet = {
                                "id": cmd_id,
                                "target": local_device_name,
                                "sender": sender,
                                "action": action,
                                "timestamp": time.time(),
                                **result_data,
                            }

                        self._executed_cmd_cache[cmd_id] = result_packet

                        # Broadcast response to ALL available routes
                        for r_client, r_rem in self.routes:
                            try:
                                r_ctrl = get_control_remote_dir(r_rem)
                                r_client.ensure_remote_dir_exists(r_ctrl)
                                r_client.write_text_file(f"{r_ctrl}/{res_filename}", json.dumps(result_packet, indent=2))
                            except Exception:
                                pass

                        # Remove command file from current route
                        try:
                            client.delete_resource(it.path)
                        except Exception:
                            pass
                        executed_results.append(result_packet)

            except Exception as e:
                print(f"[RemoteControl] poll_and_dispatch error for route {getattr(client, 'base_url', '')}: {e}")

        return executed_results

    def send_command_and_wait(
        self,
        target_device: str,
        sender_device: str,
        action: str,
        payload: Dict[str, Any],
        secret_pin: str,
        timeout_seconds: int = 60,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Sender machine: writes cmd_{target}_{id}.json across ALL configured server routes,
        waits for res_{target}_{id}.json across ALL routes, parses result,
        cleans up cmd/res files from all routes, and returns (success, msg, res_dict).
        """
        packet = create_command_packet(
            target_device=target_device,
            sender_device=sender_device,
            action=action,
            payload=payload,
            secret_pin=secret_pin,
        )
        cmd_id = packet["id"]
        cmd_filename = f"cmd_{target_device.lower()}_{cmd_id}.json"
        res_filename = f"res_{target_device.lower()}_{cmd_id}.json"

        if status_callback:
            status_callback("Uploading command across available routes...")

        cmd_json = json.dumps(packet, indent=2)
        routes_written: List[Tuple[FileBrowserClient, str]] = []

        for client, remote_path in self.routes:
            try:
                ctrl_dir = get_control_remote_dir(remote_path)
                client.ensure_remote_dir_exists(ctrl_dir)
                cmd_file = f"{ctrl_dir}/{cmd_filename}"
                if client.write_text_file(cmd_file, cmd_json):
                    routes_written.append((client, remote_path))
            except Exception as e:
                print(f"[RemoteControl] Failed to upload command to route {getattr(client, 'base_url', '')}: {e}")

        if not routes_written:
            return False, "Failed to send command to any configured server.", {}

        if status_callback:
            count = len(routes_written)
            status_callback(f"Command sent via {count} route(s). Waiting for '{target_device}'...")

        start_time = time.time()
        poll_interval = 1.5

        while time.time() - start_time < timeout_seconds:
            time.sleep(poll_interval)
            elapsed = int(time.time() - start_time)
            if status_callback:
                status_callback(f"Waiting for '{target_device}'... ({elapsed}s / {timeout_seconds}s)")

            # Check for response across ALL routes
            for client, remote_path in self.routes:
                try:
                    ctrl_dir = get_control_remote_dir(remote_path)
                    res_file = f"{ctrl_dir}/{res_filename}"
                    raw_res = client.read_text_file(res_file)
                    if raw_res:
                        try:
                            res_packet = json.loads(raw_res)
                            # Response found! Clean up result and command files across all routes
                            for r_client, r_rem in self.routes:
                                try:
                                    r_ctrl = get_control_remote_dir(r_rem)
                                    r_client.delete_resource(f"{r_ctrl}/{res_filename}")
                                    r_client.delete_resource(f"{r_ctrl}/{cmd_filename}")
                                except Exception:
                                    pass

                            success = bool(res_packet.get("success", False))
                            msg = res_packet.get("message") or res_packet.get("error", "No message")
                            return success, msg, res_packet
                        except Exception as e:
                            return False, f"Failed to parse response from remote PC: {e}", {}
                except Exception:
                    pass

        # Timeout reached: clean up orphaned command files from all routes
        for client, remote_path in self.routes:
            try:
                ctrl_dir = get_control_remote_dir(remote_path)
                client.delete_resource(f"{ctrl_dir}/{cmd_filename}")
            except Exception:
                pass

        return False, f"Timeout: Remote computer '{target_device}' did not respond within {timeout_seconds} seconds across any server.", {}
