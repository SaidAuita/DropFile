"""
Command-Line Interface (CLI) for DropSync Server.
Provides daemon control, configuration generation, and status diagnostics.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path

from .config import Config, DEFAULT_CONFIG
from .engine import DropSyncEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="dropsync",
        description="DropSync — High-Performance Linux-to-Linux Bi-Directional File Sync Daemon",
    )
    parser.add_argument("--config", "-c", type=str, help="Path to dropsync.json configuration file")
    parser.add_argument("--server", action="store_true", help="Run as Server (listen for incoming connections)")
    parser.add_argument("--client", action="store_true", help="Run as Client (connect to remote server)")
    parser.add_argument("--node-name", type=str, help="Human-readable name for this node (e.g. home-server)")
    parser.add_argument("--sync-dir", "-d", type=str, help="Local directory to synchronize")
    parser.add_argument("--port", "-p", type=int, help="Port to listen on in server mode (default: 8443)")
    parser.add_argument("--remote", "-r", type=str, help="Remote peer WebSocket URL (e.g. ws://192.168.1.100:8443)")
    parser.add_argument("--token", "-t", type=str, help="Pre-shared authentication token (Bearer token)")
    parser.add_argument("--init-config", action="store_true", help="Create a default dropsync.json config file")
    parser.add_argument("--status", action="store_true", help="Show current sync database status and logs")
    return parser.parse_args()


async def run_daemon(config: Config) -> None:
    engine = DropSyncEngine(config)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler():
        print("\n[DropSync] Shutdown signal received. Gracefully stopping...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except (NotImplementedError, AttributeError):
            pass

    await engine.start()
    print("[DropSync] Daemon running. Press Ctrl+C to stop.")

    try:
        await stop_event.wait()
    finally:
        await engine.stop()


def main() -> None:
    args = parse_args()

    config_path = Path(args.config) if args.config else None
    config = Config(config_path)

    if args.init_config:
        config.save()
        print(f"[DropSync] Template configuration saved to: {config.config_path}")
        print(f"Generated Auth Token: {config.auth_token}")
        sys.exit(0)

    # Apply CLI overrides
    if args.server:
        config.role = "server"
    elif args.client:
        config.role = "client"

    if args.node_name:
        config.node_name = args.node_name
    if args.sync_dir:
        config.sync_dir = args.sync_dir
    if args.port:
        config.listen_port = args.port
    if args.remote:
        config.remote_url = args.remote
    if args.token:
        config.auth_token = args.token

    if args.status:
        from .state_db import StateDatabase
        db = StateDatabase(config.sync_dir / ".dropsync" / "state.db")
        manifest = db.get_manifest()
        print(f"\n=== DropSync Status ({config.node_name}) ===")
        print(f"Sync Directory: {config.sync_dir}")
        print(f"Active Files: {sum(1 for f in manifest.values() if not f['deleted'])}")
        print(f"Deleted (Tombstones): {sum(1 for f in manifest.values() if f['deleted'])}\n")
        print("Recent Activity Logs:")
        for log in db.get_recent_logs(limit=15):
            print(f"  [{log['action']}] {log['rel_path']} ({log['status']}, {log['size']} bytes)")
        sys.exit(0)

    print(f"============================================================")
    print(f"  DropSync Daemon v1.0.0 — Node: '{config.node_name}'")
    print(f"  Role: {config.role.upper()} | Sync Dir: {config.sync_dir}")
    if config.role in ("server", "peer"):
        print(f"  Listening on: {config.listen_host}:{config.listen_port}")
    if config.role in ("client", "peer") and config.remote_url:
        print(f"  Remote URL: {config.remote_url}")
    print(f"  Auth Token: {config.auth_token[:8]}... (length: {len(config.auth_token)})")
    print(f"============================================================")

    try:
        asyncio.run(run_daemon(config))
    except KeyboardInterrupt:
        print("\n[DropSync] Exited.")


if __name__ == "__main__":
    main()
