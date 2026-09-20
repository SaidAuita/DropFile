"""
DropSync Engine — Orchestrates File System Watcher, State Database, and WebSocket Transport.
Handles full-duplex chunk streaming, delta verification, conflict resolution, and trash management.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional, Set

from .config import Config
from .protocol import (
    MSG_FILE_ACK,
    MSG_FILE_CHUNK,
    MSG_FILE_DELETE,
    MSG_FILE_OFFER,
    MSG_FILE_REQUEST,
    MSG_MANIFEST_REQ,
    MSG_MANIFEST_RESP,
    pack_binary_chunk,
    pack_json_message,
)
from .state_db import StateDatabase
from .transport import DropSyncTransport, PeerConnection
from .watcher import FileSystemWatcher


class DropSyncEngine:
    def __init__(self, config: Config):
        self.config = config
        self.state_db = StateDatabase(self.config.sync_dir / ".dropsync" / "state.db")
        self.watcher = FileSystemWatcher(
            root_dir=self.config.sync_dir,
            ignore_patterns=self.config.ignore_patterns,
            debounce_delay=self.config.debounce_delay,
            on_change_callback=self._handle_local_change,
            on_delete_callback=self._handle_local_delete,
        )
        self.transport = DropSyncTransport(
            config=self.config,
            on_peer_ready=self._handle_peer_ready,
            on_peer_disconnected=self._handle_peer_disconnected,
            on_json_message=self._handle_json_message,
            on_binary_chunk=self._handle_binary_chunk,
        )

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False
        self._traffic_task: Optional[asyncio.Task] = None
        self._receiving_files: Dict[str, Dict[str, Any]] = {}  # {rel_path: {temp_path, hasher, bytes_received, total_size}}
        self._current_transfer: Optional[Dict[str, Any]] = None
        self._batch_transfer: Optional[Dict[str, Any]] = None
        self._batch_last_activity: float = 0.0
        self._stream_semaphore = asyncio.Semaphore(2)
        self._active_stream_tasks: Set[asyncio.Task] = set()

    async def start(self) -> None:
        """Starts the sync engine, state reconciliation, watcher and transport."""
        self._loop = asyncio.get_running_loop()
        self._running = True

        print(f"[Engine] Starting DropSync Engine (Node: {self.config.node_name}, Dir: {self.config.sync_dir})")

        # Initial local scan to index existing files
        await self._scan_and_index_local_files()

        # Start watcher
        self.watcher.start()

        # Start transport (server listening / client reconnect)
        await self.transport.start()

        # Start periodic traffic stats recorder
        self._traffic_task = asyncio.create_task(self._record_traffic_stats_loop())

    async def stop(self) -> None:
        self._running = False
        if self._traffic_task and not self._traffic_task.done():
            self._traffic_task.cancel()
        for task in list(self._active_stream_tasks):
            task.cancel()
        self.watcher.stop()
        await self.transport.stop()
        print("[Engine] DropSync Engine stopped.")

    async def _record_traffic_stats_loop(self) -> None:
        """Periodically records speed metrics to .dropsync/traffic_stats.json for client GUI monitoring."""
        try:
            from .traffic_monitor import get_traffic_monitor
        except Exception:
            try:
                from dropsync_server.traffic_monitor import get_traffic_monitor
            except Exception:
                try:
                    from traffic_monitor import get_traffic_monitor
                except Exception:
                    return

        stats_file = self.config.sync_dir / ".dropsync" / "traffic_stats.json"
        stats_file.parent.mkdir(parents=True, exist_ok=True)

        while self._running:
            try:
                tm = get_traffic_monitor()
                rx_bps, tx_bps = tm.get_current_speeds_bps()
                tot_rx, tot_tx = tm.get_totals()
                history = tm.get_history(seconds=60)

                now = time.time()
                bt = self._batch_transfer
                # Clear stale batch if no active transfer and idle for > 15s
                if bt and not ct and (now - getattr(self, "_batch_last_activity", 0) > 15.0):
                    self._batch_transfer = None
                    bt = None

                transfer_info = None
                if ct and ct.get("total_size", 0) > 0:
                    direction = ct.get("direction", "tx")
                    file_name = ct.get("file_name", "")
                    rel_path = ct.get("rel_path", "")
                    file_bytes = ct.get("total_size", 0)
                    file_transferred = min(ct.get("transferred_bytes", 0), file_bytes)
                    file_pct = round((file_transferred / file_bytes) * 100.0, 1) if file_bytes > 0 else 0.0

                    if (
                        bt
                        and bt.get("direction") == direction
                        and bt.get("total_files", 0) > 1
                        and (now - getattr(self, "_batch_last_activity", 0) < 30.0)
                    ):
                        batch_total = bt.get("total_files", 1)
                        batch_current = min(bt.get("completed_files", 0) + 1, batch_total)
                        batch_bytes_total = bt.get("total_bytes", file_bytes)
                        batch_bytes_transferred = min(bt.get("transferred_bytes", file_transferred), batch_bytes_total)
                        batch_pct = round((batch_bytes_transferred / batch_bytes_total) * 100.0, 1) if batch_bytes_total > 0 else file_pct
                        rem_bytes = max(0, batch_bytes_total - batch_bytes_transferred)
                    else:
                        batch_total = 1
                        batch_current = 1
                        batch_bytes_total = file_bytes
                        batch_bytes_transferred = file_transferred
                        batch_pct = file_pct
                        rem_bytes = max(0, file_bytes - file_transferred)

                    speed_bps = tx_bps if direction == "tx" else rx_bps
                    eta_sec = None
                    if speed_bps > 8000 and rem_bytes > 0:
                        eta_sec = int((rem_bytes * 8) / speed_bps)

                    transfer_info = {
                        "direction": direction,
                        "file_name": file_name,
                        "rel_path": rel_path,
                        "total_bytes": file_bytes,
                        "transferred_bytes": file_transferred,
                        "percent": file_pct,
                        "batch_current": batch_current,
                        "batch_total": batch_total,
                        "batch_bytes_transferred": batch_bytes_transferred,
                        "batch_bytes_total": batch_bytes_total,
                        "batch_percent": batch_pct,
                        "eta_seconds": eta_sec,
                    }

                disk_free = None
                disk_total = None
                try:
                    import shutil
                    du = shutil.disk_usage(self.config.sync_dir)
                    disk_free = int(du.free)
                    disk_total = int(du.total)
                except Exception:
                    pass

                stats = {
                    "timestamp": time.time(),
                    "node_name": self.config.node_name,
                    "role": self.config.role,
                    "connected": self.transport.is_connected,
                    "peer_count": len(self.transport.active_peers),
                    "rx_bps": rx_bps,
                    "tx_bps": tx_bps,
                    "total_rx": tot_rx,
                    "total_tx": tot_tx,
                    "history": history,
                    "current_transfer": transfer_info,
                    "disk_free": disk_free,
                    "disk_total": disk_total,
                }
                tmp_f = stats_file.with_suffix(".tmp")
                tmp_f.write_text(json.dumps(stats, ensure_ascii=False), encoding="utf-8")
                tmp_f.replace(stats_file)
            except asyncio.CancelledError:
                break
            except Exception as e:
                pass
            await asyncio.sleep(1.0)

    # --- Local Scanning & Indexing ---

    async def _scan_and_index_local_files(self) -> None:
        """Indexes all local files in sync_dir into StateDatabase."""
        print("[Engine] Indexing local files...")
        count = 0
        sync_dir = self.config.sync_dir

        for root, dirs, files in os.walk(str(sync_dir)):
            # Skip hidden internal directories
            dirs[:] = [d for d in dirs if not d.startswith(".dropsync") and d != ".git"]

            for f in files:
                full_path = Path(root) / f
                try:
                    rel = str(full_path.relative_to(sync_dir)).replace("\\", "/")
                    if self.watcher.is_ignored(rel):
                        continue

                    stat = full_path.stat()
                    existing = self.state_db.get_file(rel)

                    # Only compute hash if file is new or mtime/size changed
                    if existing and existing["mtime"] == stat.st_mtime and existing["size"] == stat.st_size:
                        continue

                    file_hash = await asyncio.to_thread(StateDatabase.calculate_file_hash, full_path)
                    self.state_db.upsert_file(rel, stat.st_size, stat.st_mtime, file_hash, deleted=0)
                    count += 1
                except Exception as e:
                    print(f"[Engine] Error indexing {f}: {e}")

        print(f"[Engine] Indexing complete. Checked/updated {count} file(s).")

    # --- Local Watcher Callbacks (Run on watcher thread -> scheduled on asyncio event loop) ---

    def _handle_local_change(self, rel_path: str) -> None:
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._process_local_change_async(rel_path), self._loop)

    def _handle_local_delete(self, rel_path: str) -> None:
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._process_local_delete_async(rel_path), self._loop)

    async def _process_local_change_async(self, rel_path: str) -> None:
        full_path = self.config.sync_dir / rel_path
        if not full_path.is_file():
            return

        try:
            stat = full_path.stat()
            existing = self.state_db.get_file(rel_path)

            # Optimization: if mtime and size match existing non-deleted record, skip re-hashing
            if existing and existing["mtime"] == stat.st_mtime and existing["size"] == stat.st_size and not existing["deleted"]:
                file_hash = existing["hash"]
            else:
                file_hash = await asyncio.to_thread(StateDatabase.calculate_file_hash, full_path)

            if existing and existing["hash"] == file_hash and not existing["deleted"]:
                return  # No actual content change

            self.state_db.upsert_file(rel_path, stat.st_size, stat.st_mtime, file_hash, deleted=0)
            self.state_db.log_sync("LOCAL_CHANGE", rel_path, "SUCCESS", stat.st_size)
            print(f"[Engine] Local file changed: {rel_path} ({stat.st_size} bytes)")

            # Offer to all active peers
            msg = pack_json_message(
                MSG_FILE_OFFER,
                {
                    "rel_path": rel_path,
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "hash": file_hash,
                },
            )
            await self.transport.broadcast_text(msg)

        except Exception as e:
            print(f"[Engine] Error processing local change {rel_path}: {e}")

    async def _process_local_delete_async(self, rel_path: str) -> None:
        self.state_db.mark_deleted(rel_path)
        self.state_db.log_sync("LOCAL_DELETE", rel_path, "SUCCESS")
        print(f"[Engine] Local file deleted: {rel_path}")

        msg = pack_json_message(
            MSG_FILE_DELETE,
            {
                "rel_path": rel_path,
                "timestamp": time.time(),
            },
        )
        await self.transport.broadcast_text(msg)

    # --- Transport & Peer Handshake Callbacks ---

    def _handle_peer_ready(self, peer: PeerConnection) -> None:
        """Called when peer authenticates successfully. Triggers reconciliation."""
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._reconcile_with_peer(peer), self._loop)

    def _handle_peer_disconnected(self, peer: PeerConnection) -> None:
        print(f"[Engine] Peer disconnected: {peer.remote_node_name}")

    async def _reconcile_with_peer(self, peer: PeerConnection) -> None:
        """Sends manifest request to peer to initiate synchronization."""
        print(f"[Engine] Reconciling state with peer '{peer.remote_node_name}'...")
        await peer.send_text(pack_json_message(MSG_MANIFEST_REQ))

    # --- Message & Chunk Dispatch ---

    async def _handle_json_message(self, peer: PeerConnection, msg: Dict[str, Any]) -> None:
        msg_type = msg.get("type", "")

        if msg_type == MSG_MANIFEST_REQ:
            manifest = self.state_db.get_manifest()
            await peer.send_text(pack_json_message(MSG_MANIFEST_RESP, {"manifest": manifest}))
            return

        if msg_type == MSG_MANIFEST_RESP:
            remote_manifest = msg.get("manifest", {})
            await self._compare_manifests(peer, remote_manifest)
            return

        if msg_type == MSG_FILE_OFFER:
            rel_path = msg.get("rel_path", "")
            remote_hash = msg.get("hash", "")
            remote_size = msg.get("size", 0)

            local = self.state_db.get_file(rel_path)
            local_full = self.config.sync_dir / rel_path

            # If local file already matches remote hash, we are up to date!
            if local and local["hash"] == remote_hash and local_full.is_file():
                return

            self._register_rx_batch_file(rel_path, remote_size)

            # Request file from peer starting at offset 0
            await peer.send_text(
                pack_json_message(
                    MSG_FILE_REQUEST,
                    {
                        "rel_path": rel_path,
                        "offset": 0,
                    },
                )
            )
            return

        if msg_type == MSG_FILE_REQUEST:
            rel_path = msg.get("rel_path", "")
            offset = msg.get("offset", 0)
            task = asyncio.create_task(self._safe_stream_file(peer, rel_path, offset))
            self._active_stream_tasks.add(task)
            task.add_done_callback(self._active_stream_tasks.discard)
            return

        if msg_type == MSG_FILE_ACK:
            rel_path = msg.get("rel_path", "")
            print(f"[Engine] Peer '{peer.remote_node_name}' confirmed receipt of {rel_path}")
            return

        if msg_type == MSG_FILE_DELETE:
            rel_path = msg.get("rel_path", "")
            await self._apply_remote_delete(rel_path)
            return

    def _register_tx_batch_file(self, rel_path: str, size: int) -> None:
        now = time.time()
        if (
            not self._batch_transfer
            or self._batch_transfer.get("direction") != "tx"
            or (now - getattr(self, "_batch_last_activity", 0) > 15.0)
        ):
            self._batch_transfer = {
                "direction": "tx",
                "total_files": 1,
                "completed_files": 0,
                "total_bytes": size,
                "transferred_bytes": 0,
                "registered_files": {rel_path},
            }
        else:
            reg = self._batch_transfer.setdefault("registered_files", set())
            if rel_path not in reg:
                reg.add(rel_path)
                self._batch_transfer["total_files"] = len(reg)
                self._batch_transfer["total_bytes"] = self._batch_transfer.get("total_bytes", 0) + size
        self._batch_last_activity = now

    def _register_rx_batch_file(self, rel_path: str, size: int) -> None:
        now = time.time()
        if (
            not self._batch_transfer
            or self._batch_transfer.get("direction") != "rx"
            or (now - getattr(self, "_batch_last_activity", 0) > 15.0)
        ):
            self._batch_transfer = {
                "direction": "rx",
                "total_files": 1,
                "completed_files": 0,
                "total_bytes": size,
                "transferred_bytes": 0,
                "registered_files": {rel_path},
            }
        else:
            reg = self._batch_transfer.setdefault("registered_files", set())
            if rel_path not in reg:
                reg.add(rel_path)
                self._batch_transfer["total_files"] = len(reg)
                self._batch_transfer["total_bytes"] = self._batch_transfer.get("total_bytes", 0) + size
        self._batch_last_activity = now

    async def _safe_stream_file(self, peer: PeerConnection, rel_path: str, offset: int = 0) -> None:
        full_path = self.config.sync_dir / rel_path
        if full_path.is_file():
            try:
                self._register_tx_batch_file(rel_path, full_path.stat().st_size)
            except Exception:
                pass
        async with self._stream_semaphore:
            await self._stream_file_to_peer(peer, rel_path, offset)

    async def _compare_manifests(self, peer: PeerConnection, remote_manifest: Dict[str, Any]) -> None:
        """Compares remote manifest with local manifest to synchronize both ways."""
        local_manifest = self.state_db.get_manifest()

        # 1. Check files offered by remote peer
        to_request = []
        for rel_path, rem_info in remote_manifest.items():
            loc_info = local_manifest.get(rel_path)
            if rem_info.get("deleted", False):
                if loc_info and not loc_info.get("deleted", False):
                    # Remote deleted it, apply deletion locally
                    if rem_info.get("updated_at", 0) > loc_info.get("updated_at", 0):
                        await self._apply_remote_delete(rel_path)
                continue

            # Remote file is active
            if not loc_info or loc_info.get("deleted", False) or loc_info.get("hash") != rem_info.get("hash"):
                to_request.append((rel_path, rem_info.get("size", 0)))

        if to_request:
            total_req_bytes = sum(s for _, s in to_request)
            self._batch_transfer = {
                "direction": "rx",
                "total_files": len(to_request),
                "completed_files": 0,
                "total_bytes": total_req_bytes,
                "transferred_bytes": 0,
                "registered_files": {p for p, _ in to_request},
            }
            self._batch_last_activity = time.time()
            for rel_path, _ in to_request:
                try:
                    await peer.send_text(
                        pack_json_message(
                            MSG_FILE_REQUEST,
                            {"rel_path": rel_path, "offset": 0},
                        )
                    )
                except Exception as e:
                    print(f"[Engine] Error requesting {rel_path} from {peer.peer_id}: {e}")

        # 2. Offer local files that remote is missing or has older
        to_offer = []
        for rel_path, loc_info in local_manifest.items():
            if loc_info.get("deleted", False):
                continue
            rem_info = remote_manifest.get(rel_path)
            if not rem_info or (not rem_info.get("deleted", False) and rem_info.get("hash") != loc_info.get("hash")):
                if not rem_info or loc_info.get("mtime", 0) > rem_info.get("mtime", 0):
                    to_offer.append((rel_path, loc_info))

        if to_offer and not to_request:
            total_offer_bytes = sum(info.get("size", 0) for _, info in to_offer)
            self._batch_transfer = {
                "direction": "tx",
                "total_files": len(to_offer),
                "completed_files": 0,
                "total_bytes": total_offer_bytes,
                "transferred_bytes": 0,
                "registered_files": {p for p, _ in to_offer},
            }
            self._batch_last_activity = time.time()

        for rel_path, loc_info in to_offer:
            try:
                await peer.send_text(
                    pack_json_message(
                        MSG_FILE_OFFER,
                        {
                            "rel_path": rel_path,
                            "size": loc_info["size"],
                            "mtime": loc_info["mtime"],
                            "hash": loc_info["hash"],
                        },
                    )
                )
            except Exception as e:
                print(f"[Engine] Error offering {rel_path} to {peer.peer_id}: {e}")

    async def _stream_file_to_peer(self, peer: PeerConnection, rel_path: str, offset: int = 0) -> None:
        """Streams file chunks in binary frames over the WebSocket."""
        full_path = self.config.sync_dir / rel_path
        if not full_path.is_file():
            print(f"[Engine] Cannot stream {rel_path}: file not found")
            return

        try:
            stat = full_path.stat()
            total_size = stat.st_size
            existing = self.state_db.get_file(rel_path)
            if existing and existing["mtime"] == stat.st_mtime and existing["size"] == total_size and not existing["deleted"]:
                file_hash = existing["hash"]
            else:
                file_hash = await asyncio.to_thread(StateDatabase.calculate_file_hash, full_path)
            chunk_size = self.config.chunk_size
            file_name = Path(rel_path).name

            self._current_transfer = {
                "direction": "tx",
                "rel_path": rel_path,
                "file_name": file_name,
                "total_size": total_size,
                "transferred_bytes": offset,
                "start_time": time.time(),
            }

            print(f"[Engine] Streaming {rel_path} ({total_size} bytes) to '{peer.remote_node_name}' from offset {offset}...")

            with open(full_path, "rb") as f:
                if offset > 0:
                    f.seek(offset)

                curr_offset = offset
                while curr_offset < total_size:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break

                    is_last = (curr_offset + len(chunk)) >= total_size
                    header = {
                        "rel_path": rel_path,
                        "offset": curr_offset,
                        "chunk_size": len(chunk),
                        "total_size": total_size,
                        "mtime": stat.st_mtime,
                        "hash": file_hash,
                        "is_last": is_last,
                    }

                    frame = pack_binary_chunk(header, chunk)
                    await peer.send_binary(frame)
                    curr_offset += len(chunk)
                    self._batch_last_activity = time.time()

                    if self._current_transfer and self._current_transfer.get("rel_path") == rel_path:
                        self._current_transfer["transferred_bytes"] = curr_offset

                    if self._batch_transfer and self._batch_transfer.get("direction") == "tx":
                        self._batch_transfer["transferred_bytes"] = self._batch_transfer.get("transferred_bytes", 0) + len(chunk)

                    # Yield to event loop to allow concurrent messages
                    await asyncio.sleep(0)

            print(f"[Engine] Finished streaming {rel_path} ({total_size} bytes)")

        except Exception as e:
            print(f"[Engine] Error streaming {rel_path}: {e}")
        finally:
            self._batch_last_activity = time.time()
            if self._batch_transfer and self._batch_transfer.get("direction") == "tx":
                self._batch_transfer["completed_files"] = self._batch_transfer.get("completed_files", 0) + 1
                if self._batch_transfer["completed_files"] >= self._batch_transfer.get("total_files", 1):
                    self._batch_transfer = None

            if self._current_transfer and self._current_transfer.get("rel_path") == rel_path and self._current_transfer.get("direction") == "tx":
                self._current_transfer = None

    async def _handle_binary_chunk(self, peer: PeerConnection, header: Dict[str, Any], chunk_data: bytes) -> None:
        """Receives and writes a binary chunk into a temporary file, verifying on last chunk."""
        rel_path = header.get("rel_path", "")
        offset = header.get("offset", 0)
        total_size = header.get("total_size", 0)
        file_hash = header.get("hash", "")
        mtime = header.get("mtime", time.time())
        is_last = header.get("is_last", False)
        chunk_len = len(chunk_data)

        # Track active incoming transfer
        self._current_transfer = {
            "direction": "rx",
            "rel_path": rel_path,
            "file_name": Path(rel_path).name,
            "total_size": total_size,
            "transferred_bytes": offset + chunk_len,
            "start_time": (
                self._current_transfer.get("start_time")
                if (self._current_transfer and self._current_transfer.get("rel_path") == rel_path)
                else time.time()
            ),
        }

        self._batch_last_activity = time.time()
        if self._batch_transfer and self._batch_transfer.get("direction") == "rx":
            self._batch_transfer["transferred_bytes"] = self._batch_transfer.get("transferred_bytes", 0) + chunk_len

        target_path = self.config.sync_dir / rel_path
        target_path.parent.mkdir(parents=True, exist_ok=True)

        temp_dir = self.config.sync_dir / ".dropsync" / "tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_file = temp_dir / f"{file_hash}.tmp"

        # Suppress watcher notification for this path while downloading
        self.watcher.suppress_path(rel_path, duration=3.0)

        # Append chunk
        try:
            mode = "r+b" if temp_file.exists() and offset > 0 else "wb"
            with open(temp_file, mode) as f:
                f.seek(offset)
                f.write(chunk_data)

            if is_last:
                # Verify complete file hash
                received_hash = await asyncio.to_thread(StateDatabase.calculate_file_hash, temp_file)
                if received_hash == file_hash:
                    # Move temp file atomically into place
                    temp_file.replace(target_path)
                    os.utime(target_path, (mtime, mtime))

                    # Update local state DB
                    self.state_db.upsert_file(rel_path, total_size, mtime, file_hash, deleted=0)
                    self.state_db.log_sync("DOWNLOAD", rel_path, "SUCCESS", total_size)
                    print(f"[Engine] Successfully downloaded and verified: {rel_path} ({total_size} bytes)")

                    # Send ACK
                    await peer.send_text(
                        pack_json_message(
                            MSG_FILE_ACK,
                            {"rel_path": rel_path, "hash": file_hash, "status": "OK"},
                        )
                    )

                    if self._batch_transfer and self._batch_transfer.get("direction") == "rx":
                        self._batch_transfer["completed_files"] = self._batch_transfer.get("completed_files", 0) + 1
                        if self._batch_transfer["completed_files"] >= self._batch_transfer.get("total_files", 1):
                            self._batch_transfer = None

                    if self._current_transfer and self._current_transfer.get("rel_path") == rel_path and self._current_transfer.get("direction") == "rx":
                        self._current_transfer = None
                else:
                    print(f"[Engine] Hash mismatch for {rel_path}! Expected {file_hash}, got {received_hash}")
                    if self._current_transfer and self._current_transfer.get("rel_path") == rel_path:
                        self._current_transfer = None
                    try:
                        temp_file.unlink()
                    except Exception:
                        pass

        except Exception as e:
            print(f"[Engine] Error writing chunk for {rel_path}: {e}")
            if self._current_transfer and self._current_transfer.get("rel_path") == rel_path:
                self._current_transfer = None

    async def _apply_remote_delete(self, rel_path: str) -> None:
        """Handles remote deletion: moves file to .dropsync_trash if enabled."""
        full_path = self.config.sync_dir / rel_path
        self.watcher.suppress_path(rel_path, duration=3.0)

        if full_path.is_file():
            try:
                if self.config.trash_enabled:
                    trash_dir = self.config.trash_dir
                    trash_dir.mkdir(parents=True, exist_ok=True)
                    trash_dest = trash_dir / f"{int(time.time())}_{full_path.name}"
                    shutil.move(str(full_path), str(trash_dest))
                    print(f"[Engine] Moved deleted file to trash: {rel_path} -> {trash_dest.name}")
                else:
                    full_path.unlink()
                    print(f"[Engine] Deleted file: {rel_path}")
            except Exception as e:
                print(f"[Engine] Error deleting {rel_path}: {e}")

        self.state_db.mark_deleted(rel_path)
        self.state_db.log_sync("REMOTE_DELETE", rel_path, "SUCCESS")
