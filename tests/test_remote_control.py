"""
Unit tests for DropFile Remote Control & Emergency Actions.
"""

import json
import time
import unittest
from unittest.mock import MagicMock, patch

from remote_control import (
    ACTION_KILL_PROCESS,
    ACTION_LIST_PROCESSES,
    ACTION_REBOOT,
    COMMAND_FRESHNESS_SECONDS,
    RemoteControlManager,
    compute_signature,
    create_command_packet,
    execute_action,
    get_control_remote_dir,
    verify_command_packet,
)


class TestRemoteControlProtocol(unittest.TestCase):
    def setUp(self):
        self.pin = "secret123"
        self.target = "Office-PC"
        self.sender = "Home-Laptop"

    def test_get_control_remote_dir(self):
        self.assertEqual(get_control_remote_dir("/DropFile"), "/DropFile/.dropfile_control")
        self.assertEqual(get_control_remote_dir("/"), "/.dropfile_control")

    def test_create_and_verify_valid_command(self):
        packet = create_command_packet(
            target_device=self.target,
            sender_device=self.sender,
            action=ACTION_KILL_PROCESS,
            payload={"process_name": "happ.exe"},
            secret_pin=self.pin,
        )

        self.assertEqual(packet["target"], self.target)
        self.assertEqual(packet["sender"], self.sender)
        self.assertEqual(packet["action"], ACTION_KILL_PROCESS)
        self.assertEqual(packet["payload"], {"process_name": "happ.exe"})
        self.assertTrue(len(packet["signature"]) > 20)

        # Verification on target
        ok, err = verify_command_packet(
            packet=packet,
            local_device_name=self.target,
            local_pin=self.pin,
            allow_reboot=True,
            allow_process_list=True,
            whitelist=["happ.exe"],
            strict_whitelist=True,
        )
        self.assertTrue(ok)
        self.assertEqual(err, "")

    def test_verify_wrong_pin(self):
        packet = create_command_packet(
            target_device=self.target,
            sender_device=self.sender,
            action=ACTION_KILL_PROCESS,
            payload={"process_name": "happ.exe"},
            secret_pin="wrong_pin",
        )

        ok, err = verify_command_packet(
            packet=packet,
            local_device_name=self.target,
            local_pin=self.pin,
        )
        self.assertFalse(ok)
        self.assertIn("Authentication failed", err)

    def test_verify_target_mismatch(self):
        packet = create_command_packet(
            target_device="Other-PC",
            sender_device=self.sender,
            action=ACTION_KILL_PROCESS,
            payload={"process_name": "happ.exe"},
            secret_pin=self.pin,
        )

        ok, err = verify_command_packet(
            packet=packet,
            local_device_name=self.target,
            local_pin=self.pin,
        )
        self.assertFalse(ok)
        self.assertIn("Target mismatch", err)

    def test_verify_expired_command(self):
        packet = create_command_packet(
            target_device=self.target,
            sender_device=self.sender,
            action=ACTION_KILL_PROCESS,
            payload={"process_name": "happ.exe"},
            secret_pin=self.pin,
        )
        # Artificially age timestamp
        packet["timestamp"] = time.time() - (COMMAND_FRESHNESS_SECONDS + 50)
        # Recompute signature for the old timestamp
        payload_str = json.dumps(packet["payload"], sort_keys=True, separators=(",", ":"))
        packet["signature"] = compute_signature(
            self.pin, packet["id"], self.target, packet["action"], payload_str, packet["timestamp"]
        )

        ok, err = verify_command_packet(
            packet=packet,
            local_device_name=self.target,
            local_pin=self.pin,
        )
        self.assertFalse(ok)
        self.assertIn("Command expired", err)

    def test_verify_tampered_payload(self):
        packet = create_command_packet(
            target_device=self.target,
            sender_device=self.sender,
            action=ACTION_KILL_PROCESS,
            payload={"process_name": "happ.exe"},
            secret_pin=self.pin,
        )
        # Tamper payload
        packet["payload"]["process_name"] = "malicious.exe"

        ok, err = verify_command_packet(
            packet=packet,
            local_device_name=self.target,
            local_pin=self.pin,
        )
        self.assertFalse(ok)
        self.assertIn("Authentication failed", err)

    def test_verify_reboot_policy(self):
        packet = create_command_packet(
            target_device=self.target,
            sender_device=self.sender,
            action=ACTION_REBOOT,
            payload={"delay": 5},
            secret_pin=self.pin,
        )

        # When reboot disallowed
        ok, err = verify_command_packet(
            packet=packet,
            local_device_name=self.target,
            local_pin=self.pin,
            allow_reboot=False,
        )
        self.assertFalse(ok)
        self.assertIn("Reboot action is disabled", err)

        # When reboot allowed
        ok, err = verify_command_packet(
            packet=packet,
            local_device_name=self.target,
            local_pin=self.pin,
            allow_reboot=True,
        )
        self.assertTrue(ok)

    def test_verify_strict_whitelist_policy(self):
        packet = create_command_packet(
            target_device=self.target,
            sender_device=self.sender,
            action=ACTION_KILL_PROCESS,
            payload={"process_name": "notepad.exe"},
            secret_pin=self.pin,
        )

        # Strict whitelist rejecting notepad
        ok, err = verify_command_packet(
            packet=packet,
            local_device_name=self.target,
            local_pin=self.pin,
            whitelist=["happ.exe", "chrome.exe"],
            strict_whitelist=True,
        )
        self.assertFalse(ok)
        self.assertIn("not in the allowed whitelist", err)

        # Non-strict whitelist allowing notepad
        ok, err = verify_command_packet(
            packet=packet,
            local_device_name=self.target,
            local_pin=self.pin,
            whitelist=["happ.exe", "chrome.exe"],
            strict_whitelist=False,
        )
        self.assertTrue(ok)

    @patch("remote_control.kill_process_by_name")
    def test_execute_kill_action(self, mock_kill):
        mock_kill.return_value = (True, "Process killed")
        res = execute_action(ACTION_KILL_PROCESS, {"process_name": "happ.exe"})
        self.assertTrue(res["success"])
        self.assertEqual(res["target_process"], "happ.exe")
        mock_kill.assert_called_once_with("happ.exe")

    @patch("remote_control.reboot_system")
    def test_execute_reboot_action(self, mock_reboot):
        mock_reboot.return_value = (True, "Reboot initiated")
        res = execute_action(ACTION_REBOOT, {"delay": 5})
        self.assertTrue(res["success"])
        mock_reboot.assert_called_once_with(delay_seconds=5)

    @patch("remote_control.list_system_processes")
    def test_execute_list_processes_action(self, mock_list):
        mock_list.return_value = [{"name": "happ.exe", "pid": "123", "memory": "50 MB"}]
        res = execute_action(ACTION_LIST_PROCESSES, {})
        self.assertTrue(res["success"])
        self.assertEqual(len(res["processes"]), 1)
        self.assertEqual(res["processes"][0]["name"], "happ.exe")


class TestRemoteControlManager(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        self.manager = RemoteControlManager(self.mock_client, "/DropFile")
        self.pin = "pass789"
        self.local_pc = "Office-PC"

    def test_publish_heartbeat(self):
        info = {"device_name": "Office-PC", "platform": "win32"}
        self.mock_client.write_text_file.return_value = True

        ok = self.manager.publish_heartbeat(info)
        self.assertTrue(ok)
        self.mock_client.write_text_file.assert_called_once()
        call_path, call_data = self.mock_client.write_text_file.call_args[0]
        self.assertIn("device_office-pc.json", call_path)
        parsed = json.loads(call_data)
        self.assertEqual(parsed["device_name"], "Office-PC")
        self.assertIn("last_seen", parsed)

    def test_poll_and_dispatch_incoming_command(self):
        # Create a valid command packet
        packet = create_command_packet(
            target_device=self.local_pc,
            sender_device="Home-PC",
            action=ACTION_KILL_PROCESS,
            payload={"process_name": "happ.exe"},
            secret_pin=self.pin,
        )
        cmd_id = packet["id"]
        cmd_filename = f"cmd_{self.local_pc.lower()}_{cmd_id}.json"
        cmd_path = f"/DropFile/.dropfile_control/{cmd_filename}"

        mock_item = MagicMock()
        mock_item.name = cmd_filename
        mock_item.path = cmd_path
        mock_item.is_dir = False

        self.mock_client.list_recursive.return_value = [mock_item]
        self.mock_client.read_text_file.return_value = json.dumps(packet)
        self.mock_client.write_text_file.return_value = True
        self.mock_client.delete_resource.return_value = True

        with patch("remote_control.kill_process_by_name", return_value=(True, "happ.exe terminated")):
            results = self.manager.poll_and_dispatch(
                local_device_name=self.local_pc,
                local_pin=self.pin,
                allow_reboot=True,
                allow_process_list=True,
                whitelist=["happ.exe"],
                strict_whitelist=False,
            )

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["success"])
        self.assertEqual(results[0]["id"], cmd_id)

        # Verify response was written and command file was deleted
        self.mock_client.write_text_file.assert_called_once()
        res_call_path, res_call_data = self.mock_client.write_text_file.call_args[0]
        self.assertIn(f"res_{self.local_pc.lower()}_{cmd_id}.json", res_call_path)
        self.mock_client.delete_resource.assert_called_once_with(cmd_path)

    def test_send_command_and_wait(self):
        self.mock_client.write_text_file.return_value = True

        # Simulate remote PC returning a response packet on second read_text_file call
        res_payload = {
            "id": "abc12345",
            "target": "Office-PC",
            "success": True,
            "message": "Process happ.exe terminated successfully.",
        }
        self.mock_client.read_text_file.side_effect = [None, json.dumps(res_payload)]
        self.mock_client.delete_resource.return_value = True

        ok, msg, res = self.manager.send_command_and_wait(
            target_device="Office-PC",
            sender_device="Home-PC",
            action=ACTION_KILL_PROCESS,
            payload={"process_name": "happ.exe"},
            secret_pin=self.pin,
            timeout_seconds=5,
        )

        self.assertTrue(ok)
        self.assertIn("Process happ.exe terminated", msg)
        self.assertTrue(res.get("success"))


if __name__ == "__main__":
    unittest.main()
