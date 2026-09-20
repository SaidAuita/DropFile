"""
DropSync Binary and JSON Framing Protocol over WebSockets.
Optimized for high-speed streaming without base64 overhead.
"""

from __future__ import annotations

import json
import struct
from typing import Any, Dict, Optional, Tuple


PROTOCOL_VERSION = "1.0"

# Message Types
MSG_HELLO = "HELLO"
MSG_AUTH = "AUTH"
MSG_AUTH_OK = "AUTH_OK"
MSG_AUTH_FAIL = "AUTH_FAIL"
MSG_MANIFEST_REQ = "MANIFEST_REQ"
MSG_MANIFEST_RESP = "MANIFEST_RESP"
MSG_FILE_OFFER = "FILE_OFFER"
MSG_FILE_REQUEST = "FILE_REQUEST"
MSG_FILE_CHUNK = "FILE_CHUNK"
MSG_FILE_ACK = "FILE_ACK"
MSG_FILE_DELETE = "FILE_DELETE"
MSG_DIR_DELETE = "DIR_DELETE"
MSG_PING = "PING"
MSG_PONG = "PONG"


def pack_json_message(msg_type: str, data: Optional[Dict[str, Any]] = None) -> str:
    """Serializes control command as a JSON text message."""
    payload = {"type": msg_type}
    if data:
        payload.update(data)
    return json.dumps(payload, ensure_ascii=False)


def unpack_json_message(text: str) -> Dict[str, Any]:
    """Parses control command from JSON string."""
    try:
        return json.loads(text)
    except Exception as e:
        return {"type": "ERROR", "error": f"Invalid JSON: {e}"}


def pack_binary_chunk(header_dict: Dict[str, Any], chunk_data: bytes) -> bytes:
    """
    Packs a file chunk into a zero-copy binary frame:
    [4 bytes: header JSON length in big-endian] + [header JSON bytes] + [raw binary chunk]
    """
    header_bytes = json.dumps(header_dict, ensure_ascii=False).encode("utf-8")
    header_len = len(header_bytes)
    return struct.pack(">I", header_len) + header_bytes + chunk_data


def unpack_binary_chunk(raw_bytes: bytes) -> Tuple[Optional[Dict[str, Any]], bytes]:
    """
    Unpacks binary frame into:
    (header_dict, raw_chunk_bytes)
    """
    if len(raw_bytes) < 4:
        return None, b""
    header_len = struct.unpack(">I", raw_bytes[:4])[0]
    if len(raw_bytes) < 4 + header_len:
        return None, b""
    header_bytes = raw_bytes[4 : 4 + header_len]
    chunk_data = raw_bytes[4 + header_len :]
    try:
        header_dict = json.loads(header_bytes.decode("utf-8"))
        return header_dict, chunk_data
    except Exception:
        return None, b""
