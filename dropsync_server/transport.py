"""
DropSync WebSocket Transport (Server and Client).
Full-duplex bi-directional communication with token authentication.
"""

from __future__ import annotations

import asyncio
import ssl
from typing import Any, Callable, Dict, Optional, Set
import websockets

from .config import Config
from .protocol import (
    MSG_AUTH,
    MSG_AUTH_FAIL,
    MSG_AUTH_OK,
    MSG_HELLO,
    MSG_PING,
    MSG_PONG,
    PROTOCOL_VERSION,
    pack_binary_chunk,
    pack_json_message,
    unpack_binary_chunk,
    unpack_json_message,
)


class PeerConnection:
    def __init__(self, ws: Any, peer_id: str, is_inbound: bool):
        self.ws = ws
        self.peer_id = peer_id
        self.is_inbound = is_inbound
        self.authenticated = False
        self.remote_node_name = "unknown"

    async def send_text(self, text: str) -> None:
        await self.ws.send(text)

    async def send_binary(self, data: bytes) -> None:
        try:
            try:
                from .traffic_monitor import get_traffic_monitor
            except ImportError:
                from traffic_monitor import get_traffic_monitor
            get_traffic_monitor().record_tx(len(data))
        except Exception:
            pass
        await self.ws.send(data)


class DropSyncTransport:
    def __init__(
        self,
        config: Config,
        on_peer_ready: Callable[[PeerConnection], Any],
        on_peer_disconnected: Callable[[PeerConnection], Any],
        on_json_message: Callable[[PeerConnection, Dict[str, Any]], Any],
        on_binary_chunk: Callable[[PeerConnection, Dict[str, Any], bytes], Any],
    ):
        self.config = config
        self.on_peer_ready = on_peer_ready
        self.on_peer_disconnected = on_peer_disconnected
        self.on_json_message = on_json_message
        self.on_binary_chunk = on_binary_chunk

        self.active_peers: Dict[str, PeerConnection] = {}
        self._server: Optional[Any] = None
        self._running = False
        self._client_task: Optional[asyncio.Task] = None

    @property
    def is_connected(self) -> bool:
        return bool(self.active_peers)

    def _build_server_ssl_context(self) -> Optional[ssl.SSLContext]:
        if not self.config.ssl_enabled:
            return None
        if not self.config.ssl_cert or not self.config.ssl_key:
            print("[Transport] SSL enabled but ssl_cert/ssl_key not specified. Running unencrypted WS.")
            return None
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.config.ssl_cert, self.config.ssl_key)
        return ctx

    def _build_client_ssl_context(self) -> Optional[ssl.SSLContext]:
        if not self.config.remote_url.startswith("wss://"):
            return None
        ctx = ssl.create_default_context()
        if not self.config.ssl_verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    async def start(self) -> None:
        self._running = True

        # If role is server or peer, start listening
        if self.config.role in ("server", "peer"):
            ssl_ctx = self._build_server_ssl_context()
            proto = "wss" if ssl_ctx else "ws"
            self._server = await websockets.serve(
                self._handle_inbound_connection,
                host=self.config.listen_host,
                port=self.config.listen_port,
                ssl=ssl_ctx,
                max_size=self.config.chunk_size + 65536,  # Allow chunk + header
                ping_interval=20,
                ping_timeout=20,
            )
            print(f"[Transport] Server listening on {proto}://{self.config.listen_host}:{self.config.listen_port}")

        # If role is client or peer, start outgoing client connection loop
        if self.config.role in ("client", "peer") and self.config.remote_url:
            self._client_task = asyncio.create_task(self._client_reconnect_loop())

    async def stop(self) -> None:
        self._running = False
        if self._client_task:
            self._client_task.cancel()

        if self._server:
            self._server.close()
            await self._server.wait_closed()

        for peer in list(self.active_peers.values()):
            try:
                await peer.ws.close()
            except Exception:
                pass
        self.active_peers.clear()

    async def _handle_inbound_connection(self, ws: Any) -> None:
        """Handles incoming connection on the Server listener."""
        peer_id = f"inbound-{id(ws)}"
        peer = PeerConnection(ws, peer_id, is_inbound=True)
        self.active_peers[peer_id] = peer
        print(f"[Transport] Inbound connection received from {ws.remote_address}")

        try:
            # First, send HELLO
            await peer.send_text(
                pack_json_message(
                    MSG_HELLO,
                    {
                        "node_name": self.config.node_name,
                        "version": PROTOCOL_VERSION,
                    },
                )
            )

            async for raw_msg in ws:
                await self._process_incoming_message(peer, raw_msg)

        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            print(f"[Transport] Inbound connection error ({peer_id}): {e}")
        finally:
            self.active_peers.pop(peer_id, None)
            if peer.authenticated:
                self.on_peer_disconnected(peer)
            print(f"[Transport] Inbound connection closed: {peer_id}")

    async def _client_reconnect_loop(self) -> None:
        """Maintains persistent connection to remote server with auto-reconnect."""
        retry_delay = 2
        max_retry_delay = 30

        while self._running:
            url = self.config.remote_url
            ssl_ctx = self._build_client_ssl_context()
            print(f"[Transport] Connecting to remote peer at {url}...")

            try:
                async with websockets.connect(
                    url,
                    ssl=ssl_ctx,
                    max_size=self.config.chunk_size + 65536,
                    ping_interval=20,
                    ping_timeout=20,
                ) as ws:
                    peer_id = f"outbound-{id(ws)}"
                    peer = PeerConnection(ws, peer_id, is_inbound=False)
                    self.active_peers[peer_id] = peer
                    retry_delay = 2  # Reset backoff on successful connect
                    print(f"[Transport] Connected to remote peer at {url}")

                    # Send HELLO and AUTH
                    await peer.send_text(
                        pack_json_message(
                            MSG_HELLO,
                            {
                                "node_name": self.config.node_name,
                                "version": PROTOCOL_VERSION,
                            },
                        )
                    )
                    await peer.send_text(
                        pack_json_message(
                            MSG_AUTH,
                            {
                                "auth_token": self.config.auth_token,
                                "node_name": self.config.node_name,
                            },
                        )
                    )

                    async for raw_msg in ws:
                        await self._process_incoming_message(peer, raw_msg)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Transport] Connection to {url} failed: {e}. Reconnecting in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

    async def _process_incoming_message(self, peer: PeerConnection, raw_msg: Any) -> None:
        """Routes message based on text (JSON control) or bytes (binary file chunk)."""
        if isinstance(raw_msg, bytes):
            try:
                try:
                    from .traffic_monitor import get_traffic_monitor
                except ImportError:
                    from traffic_monitor import get_traffic_monitor
                get_traffic_monitor().record_rx(len(raw_msg))
            except Exception:
                pass
            # Binary chunk
            if not peer.authenticated:
                return
            header, chunk_data = unpack_binary_chunk(raw_msg)
            if header:
                await self.on_binary_chunk(peer, header, chunk_data)
            return

        # Text message (JSON)
        msg = unpack_json_message(raw_msg)
        msg_type = msg.get("type", "")

        # Authentication handshake
        if msg_type == MSG_AUTH:
            token = msg.get("auth_token", "")
            if token == self.config.auth_token:
                peer.authenticated = True
                peer.remote_node_name = msg.get("node_name", "peer")
                await peer.send_text(pack_json_message(MSG_AUTH_OK))
                print(f"[Transport] Peer '{peer.remote_node_name}' successfully authenticated.")
                self.on_peer_ready(peer)
            else:
                print(f"[Transport] Peer authentication failed: invalid token from {peer.peer_id}")
                await peer.send_text(pack_json_message(MSG_AUTH_FAIL, {"error": "Invalid auth_token"}))
                await peer.ws.close()
            return

        if msg_type == MSG_AUTH_OK:
            peer.authenticated = True
            print(f"[Transport] Authenticated successfully with remote peer.")
            self.on_peer_ready(peer)
            return

        if msg_type == MSG_AUTH_FAIL:
            print(f"[Transport] Remote peer rejected authentication: {msg.get('error')}")
            await peer.ws.close()
            return

        if msg_type == MSG_HELLO:
            peer.remote_node_name = msg.get("node_name", "peer")
            return

        if msg_type == MSG_PING:
            await peer.send_text(pack_json_message(MSG_PONG))
            return

        # All other messages require authentication
        if peer.authenticated:
            await self.on_json_message(peer, msg)
