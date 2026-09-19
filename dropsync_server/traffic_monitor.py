"""
Traffic Monitor for DropFile & DropSync.
Tracks real-time network transfer speeds (Rx / Tx in bits/sec and bytes/sec)
and maintains a rolling history buffer for visual network activity graphs (Keenetic style).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, List, Optional, Tuple


class TrafficMonitor:
    """
    Thread-safe traffic monitor and speed estimator.
    Accumulates bytes transferred in 1-second time windows and provides
    instantaneous speed, total session transfer counters, and a rolling history.
    """

    def __init__(self, history_seconds: int = 120):
        self._history_seconds = max(30, history_seconds)
        self._lock = threading.Lock()

        # Cumulative session counters
        self._total_rx_bytes: int = 0
        self._total_tx_bytes: int = 0

        # Current 1-second bucket
        self._current_second: int = int(time.time())
        self._bucket_rx_bytes: int = 0
        self._bucket_tx_bytes: int = 0

        # Rolling history: each item is (timestamp, rx_bps, tx_bps)
        self._history: Deque[Tuple[float, float, float]] = deque(maxlen=self._history_seconds)

        # Last calculated rates (in bits per second)
        self._last_rx_bps: float = 0.0
        self._last_tx_bps: float = 0.0

        # Background ticker thread
        self._running = True
        self._ticker_thread = threading.Thread(target=self._ticker_loop, daemon=True, name="TrafficMonitorTicker")
        self._ticker_thread.start()

    def record_rx(self, num_bytes: int) -> None:
        """Records inbound (download / receive) bytes."""
        if num_bytes <= 0:
            return
        with self._lock:
            self._flush_bucket_if_needed()
            self._bucket_rx_bytes += num_bytes
            self._total_rx_bytes += num_bytes

    def record_tx(self, num_bytes: int) -> None:
        """Records outbound (upload / transmit) bytes."""
        if num_bytes <= 0:
            return
        with self._lock:
            self._flush_bucket_if_needed()
            self._bucket_tx_bytes += num_bytes
            self._total_tx_bytes += num_bytes

    def _flush_bucket_if_needed(self, now: Optional[float] = None) -> None:
        """Flushes completed second buckets into rolling history."""
        ts = now or time.time()
        cur_sec = int(ts)
        diff = cur_sec - self._current_second

        if diff <= 0:
            return

        if diff == 1:
            rx_bps = float(self._bucket_rx_bytes * 8)
            tx_bps = float(self._bucket_tx_bytes * 8)
            self._last_rx_bps = rx_bps
            self._last_tx_bps = tx_bps
            self._history.append((float(self._current_second), rx_bps, tx_bps))
            self._current_second = cur_sec
            self._bucket_rx_bytes = 0
            self._bucket_tx_bytes = 0
        else:
            # 1 or more seconds passed with no activity
            rx_bps = float(self._bucket_rx_bytes * 8)
            tx_bps = float(self._bucket_tx_bytes * 8)
            self._history.append((float(self._current_second), rx_bps, tx_bps))

            # Fill intermediate gap seconds with 0
            fill_count = min(diff - 1, self._history_seconds)
            for i in range(1, fill_count + 1):
                self._history.append((float(self._current_second + i), 0.0, 0.0))

            self._last_rx_bps = 0.0
            self._last_tx_bps = 0.0
            self._current_second = cur_sec
            self._bucket_rx_bytes = 0
            self._bucket_tx_bytes = 0

    def _ticker_loop(self) -> None:
        """Ensures that empty seconds are recorded into the rolling history even when idle."""
        while self._running:
            time.sleep(1.0)
            with self._lock:
                self._flush_bucket_if_needed()

    def get_current_speeds_bps(self) -> Tuple[float, float]:
        """Returns (rx_bps, tx_bps) as bits per second."""
        with self._lock:
            self._flush_bucket_if_needed()
            rx = self._last_rx_bps if self._last_rx_bps > 0 else float(self._bucket_rx_bytes * 8)
            tx = self._last_tx_bps if self._last_tx_bps > 0 else float(self._bucket_tx_bytes * 8)
            return (rx, tx)

    def get_totals(self) -> Tuple[int, int]:
        """Returns total session (total_rx_bytes, total_tx_bytes)."""
        with self._lock:
            return (self._total_rx_bytes, self._total_tx_bytes)

    def get_history(self, seconds: Optional[int] = None) -> List[Tuple[float, float, float]]:
        """
        Returns snapshot of rolling history: [(timestamp, rx_bps, tx_bps), ...].
        Guaranteed to have at least `seconds` points padded with 0 if recent.
        """
        req_len = seconds or self._history_seconds
        with self._lock:
            self._flush_bucket_if_needed()
            items = list(self._history)

        now = time.time()
        if len(items) < req_len:
            pad_count = req_len - len(items)
            base_time = (items[0][0] if items else now) - pad_count
            padding = [(base_time + i, 0.0, 0.0) for i in range(pad_count)]
            items = padding + items
        else:
            items = items[-req_len:]
        return items

    def stop(self) -> None:
        self._running = False


# Global Singleton instance
_INSTANCE: Optional[TrafficMonitor] = None
_INSTANCE_LOCK = threading.Lock()


def get_traffic_monitor() -> TrafficMonitor:
    """Returns global singleton TrafficMonitor instance."""
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = TrafficMonitor()
    return _INSTANCE


def record_rx(nbytes: int) -> None:
    """Convenience helper to record received bytes in global monitor."""
    get_traffic_monitor().record_rx(nbytes)


def record_tx(nbytes: int) -> None:
    """Convenience helper to record transmitted bytes in global monitor."""
    get_traffic_monitor().record_tx(nbytes)


def get_current_speeds_bps() -> Tuple[float, float]:
    """Returns current (rx_bps, tx_bps) from global monitor."""
    return get_traffic_monitor().get_current_speeds_bps()


def get_totals() -> Tuple[int, int]:
    """Returns total session (rx_bytes, tx_bytes) from global monitor."""
    return get_traffic_monitor().get_totals()


def get_history(seconds: Optional[int] = None) -> List[Tuple[float, float, float]]:
    """Returns rolling traffic history from global monitor."""
    return get_traffic_monitor().get_history(seconds)


_CLIENT_TRANSFER: Optional[dict] = None
_CLIENT_TRANSFER_LOCK = threading.Lock()


def set_client_transfer(transfer_info: Optional[dict]) -> None:
    """Sets active file transfer info for local client GUI."""
    global _CLIENT_TRANSFER
    with _CLIENT_TRANSFER_LOCK:
        _CLIENT_TRANSFER = transfer_info


def get_client_transfer() -> Optional[dict]:
    """Returns active file transfer info for local client GUI."""
    with _CLIENT_TRANSFER_LOCK:
        return _CLIENT_TRANSFER


# ---------------------------------------------------------------------------
# Formatting helpers (compatible with Russian / English Keenetic style)
# ---------------------------------------------------------------------------

def format_speed(bps: float, lang: str = "ru") -> str:
    """Formats bits per second into human-readable rate string (e.g. '2,18 Мбит/с' or '178 кбит/с')."""
    is_ru = lang == "ru"
    kb = 1000.0
    mb = 1000.0 * 1000.0
    gb = 1000.0 * 1000.0 * 1000.0

    unit_bps = "бит/с" if is_ru else "bps"
    unit_kbps = "кбит/с" if is_ru else "kbps"
    unit_mbps = "Мбит/с" if is_ru else "Mbps"
    unit_gbps = "Гбит/с" if is_ru else "Gbps"

    if bps >= gb:
        val = bps / gb
        s = f"{val:.2f}".replace(".", "," if is_ru else ".")
        return f"{s} {unit_gbps}"
    elif bps >= mb:
        val = bps / mb
        s = f"{val:.2f}".replace(".", "," if is_ru else ".")
        return f"{s} {unit_mbps}"
    elif bps >= kb:
        val = bps / kb
        s = f"{val:.0f}" if val >= 10 else f"{val:.1f}".replace(".", "," if is_ru else ".")
        return f"{s} {unit_kbps}"
    else:
        return f"{int(bps)} {unit_bps}"


def format_bytes(total_bytes: int, lang: str = "ru") -> str:
    """Formats byte counts into human-readable volume string (e.g. '1,83 ГБ' or '5,42 МБ')."""
    is_ru = lang == "ru"
    kb = 1024.0
    mb = 1024.0 * 1024.0
    gb = 1024.0 * 1024.0 * 1024.0

    unit_b = "Б" if is_ru else "B"
    unit_kb = "КБ" if is_ru else "KB"
    unit_mb = "МБ" if is_ru else "MB"
    unit_gb = "ГБ" if is_ru else "GB"

    if total_bytes >= gb:
        val = total_bytes / gb
        s = f"{val:.2f}".replace(".", "," if is_ru else ".")
        return f"{s} {unit_gb}"
    elif total_bytes >= mb:
        val = total_bytes / mb
        s = f"{val:.2f}".replace(".", "," if is_ru else ".")
        return f"{s} {unit_mb}"
    elif total_bytes >= kb:
        val = total_bytes / kb
        s = f"{val:.1f}".replace(".", "," if is_ru else ".")
        return f"{s} {unit_kb}"
    else:
        return f"{total_bytes} {unit_b}"


def format_eta(seconds: Optional[int], lang: str = "ru") -> str:
    """Formats estimated time of arrival (ETA) into a clean string (e.g. '~45 сек', '~1 мин 20 сек', '~12 мин')."""
    if seconds is None or seconds < 0:
        return "—"
    is_ru = lang == "ru"
    if seconds == 0:
        return "< 1 сек" if is_ru else "< 1s"
    if seconds < 60:
        return f"~{seconds} сек" if is_ru else f"~{seconds}s"
    elif seconds < 3600:
        m = seconds // 60
        s = seconds % 60
        if s > 0 and m < 10:
            return f"~{m} мин {s} сек" if is_ru else f"~{m}m {s}s"
        return f"~{m} мин" if is_ru else f"~{m}m"
    else:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        if m > 0:
            return f"~{h} ч {m} мин" if is_ru else f"~{h}h {m}m"
        return f"~{h} ч" if is_ru else f"~{h}h"

