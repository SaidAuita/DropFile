"""
Speed Chart Widget and Live Network Traffic Monitor Window for DropFile & DropSync.
Inspired by Keenetic router network dashboard:
Features dual-area graphs for Rx (Download) and Tx (Upload), dynamic peak auto-scaling,
smooth grid lines, and live session transfer statistics.
"""

from __future__ import annotations

import datetime
import math
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, List, Optional, Tuple

from i18n import t
from traffic_monitor import format_bytes, format_eta, format_speed, get_client_transfer, get_traffic_monitor


class TransferProgressBar(tk.Canvas):
    """
    Smooth, crisp progress bar drawn on Canvas to avoid OS-dependent ttk styling bugs.
    Supports animated fill, custom bar color, and dynamic sizing.
    """

    def __init__(self, parent: Any, height: int = 8, bg: str = "#E2E8F0", bar_color: str = "#0284C7", **kwargs: Any):
        super().__init__(parent, height=height, bg=bg, highlightthickness=0, bd=0, **kwargs)
        self.bar_color = bar_color
        self._percent: float = 0.0
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event: Any) -> None:
        self._draw()

    def set_progress(self, percent: float, color: Optional[str] = None) -> None:
        self._percent = max(0.0, min(100.0, float(percent)))
        if color:
            self.bar_color = color
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        w = float(self.winfo_width() or 100)
        h = float(self.winfo_height() or 8)
        if self._percent > 0:
            fill_w = (w * self._percent) / 100.0
            self.create_rectangle(0, 0, fill_w, h, fill=self.bar_color, width=0)


class SpeedChartWidget(tk.Canvas):
    """
    High-performance Canvas widget that renders real-time dual-area speed charts (Keenetic style).
    - Green area: Inbound / Rx (Download)
    - Blue area: Outbound / Tx (Upload)
    """

    def __init__(
        self,
        parent: Any,
        width: int = 540,
        height: int = 150,
        history_seconds: int = 60,
        bg: str = "#FFFFFF",
        **kwargs: Any,
    ):
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=bg,
            highlightthickness=1,
            highlightbackground="#E2E8F0",
            **kwargs,
        )
        self.chart_width = width
        self.chart_height = height
        self.history_seconds = max(20, history_seconds)

        # Visual styling tokens (matching Keenetic dashboard aesthetics)
        self.color_bg = bg
        self.color_grid = "#EEF2F6"
        self.color_text_muted = "#94A3B8"
        self.color_peak_text = "#64748B"

        # Green series (Rx / Download)
        self.color_rx_fill = "#DCFCE7"     # Pastel green
        self.color_rx_line = "#16A34A"     # Vibrant forest green

        # Blue series (Tx / Upload)
        self.color_tx_fill = "#E0F2FE"     # Pastel sky blue
        self.color_tx_line = "#0284C7"     # Vibrant ocean blue

        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event: Any) -> None:
        if event.width > 50 and event.height > 40:
            self.chart_width = event.width
            self.chart_height = event.height

    def render(self, history: List[Tuple[float, float, float]], lang: str = "ru") -> Tuple[str, str, str, str]:
        """
        Renders the dual-area graph on the canvas and returns:
        (rx_speed_str, tx_speed_str, peak_speed_str, time_range_str)
        """
        self.delete("all")
        w = float(self.winfo_width() or self.chart_width)
        h = float(self.winfo_height() or self.chart_height)

        pad_left = 12.0
        pad_right = 16.0
        pad_top = 22.0
        pad_bottom = 22.0

        plot_w = max(10.0, w - pad_left - pad_right)
        plot_h = max(10.0, h - pad_top - pad_bottom)
        base_y = pad_top + plot_h

        if not history:
            zero = format_speed(0, lang=lang)
            return (zero, zero, zero, "")

        # Compute max speed for auto-scaling
        all_speeds = [r[1] for r in history] + [r[2] for r in history]
        raw_max = max(all_speeds) if all_speeds else 0.0

        # Round up to a clean visual ceiling (at least 100 kbps floor so idle chart has a grid)
        floor_min = 100_000.0  # 100 kbps
        max_speed = max(raw_max * 1.15, floor_min)

        # Format peak label
        peak_str = format_speed(max_speed, lang=lang)

        # 1. Draw horizontal dashed grid lines (0%, 50%, 100%)
        # Top 100% line
        y_100 = pad_top
        self.create_line(pad_left, y_100, pad_left + plot_w, y_100, fill=self.color_grid, dash=(3, 3), width=1)
        self.create_text(
            pad_left + plot_w,
            y_100 - 9,
            text=peak_str,
            fill=self.color_peak_text,
            anchor="e",
            font=("Segoe UI", 8),
        )

        # Middle 50% line
        y_50 = pad_top + plot_h * 0.5
        self.create_line(pad_left, y_50, pad_left + plot_w, y_50, fill=self.color_grid, dash=(2, 4), width=1)

        # Baseline (0 speed)
        self.create_line(pad_left, base_y, pad_left + plot_w, base_y, fill="#CBD5E1", width=1)

        # 2. Map history points to coordinates
        n = len(history)
        rx_poly: List[float] = [pad_left, base_y]
        tx_poly: List[float] = [pad_left, base_y]

        rx_line_pts: List[float] = []
        tx_line_pts: List[float] = []

        dx = plot_w / max(1, n - 1)
        for i, (ts, rx_bps, tx_bps) in enumerate(history):
            x = pad_left + i * dx
            rx_y = base_y - (min(rx_bps, max_speed) / max_speed) * plot_h
            tx_y = base_y - (min(tx_bps, max_speed) / max_speed) * plot_h

            rx_poly.extend([x, rx_y])
            tx_poly.extend([x, tx_y])

            rx_line_pts.extend([x, rx_y])
            tx_line_pts.extend([x, tx_y])

        # Close polygons at baseline
        rx_poly.extend([pad_left + plot_w, base_y])
        tx_poly.extend([pad_left + plot_w, base_y])

        # 3. Draw area fills and lines
        # Draw the larger area first or draw both with subtle distinct colors
        # Green (Rx) area
        if len(rx_poly) >= 6:
            self.create_polygon(rx_poly, fill=self.color_rx_fill, outline="")
        # Blue (Tx) area
        if len(tx_poly) >= 6:
            self.create_polygon(tx_poly, fill=self.color_tx_fill, outline="")

        # Draw crisp top outlines
        if len(rx_line_pts) >= 4:
            self.create_line(rx_line_pts, fill=self.color_rx_line, width=2, smooth=True)
        if len(tx_line_pts) >= 4:
            self.create_line(tx_line_pts, fill=self.color_tx_line, width=2, smooth=True)

        # 4. Draw time labels at bottom
        start_ts = history[0][0]
        end_ts = history[-1][0]
        start_time_str = datetime.datetime.fromtimestamp(start_ts).strftime("%H:%M:%S")
        end_time_str = datetime.datetime.fromtimestamp(end_ts).strftime("%H:%M:%S")

        self.create_text(
            pad_left,
            base_y + 11,
            text=start_time_str,
            fill=self.color_text_muted,
            anchor="w",
            font=("Segoe UI", 8),
        )
        self.create_text(
            pad_left + plot_w,
            base_y + 11,
            text=end_time_str,
            fill=self.color_text_muted,
            anchor="e",
            font=("Segoe UI", 8),
        )

        # Current rates
        latest_rx = history[-1][1] if history else 0.0
        latest_tx = history[-1][2] if history else 0.0
        return (
            format_speed(latest_rx, lang=lang),
            format_speed(latest_tx, lang=lang),
            peak_str,
            f"{start_time_str} — {end_time_str}",
        )


_SERVER_STATS_CACHE: Optional[dict] = None
_CACHE_LOCK = threading.Lock()
_POLLER_THREAD: Optional[threading.Thread] = None
_POLLER_RUNNING = False


def _get_candidate_hosts(lan_host: Optional[str] = None) -> List[str]:
    hosts: List[str] = []
    if lan_host:
        hosts.append(lan_host)

    is_work = False
    is_home = False
    try:
        import socket
        local_ips = socket.gethostbyname_ex(socket.gethostname())[2]
        for ip in local_ips:
            if ip.startswith("192.168.0."):
                is_work = True
            elif ip.startswith("192.168.1."):
                is_home = True
    except Exception:
        pass

    if is_work:
        priority = ["192.168.0.22", "192.168.1.4", "cladovka"]
    elif is_home:
        priority = ["192.168.1.4", "cladovka", "192.168.0.22"]
    else:
        priority = ["192.168.0.22", "192.168.1.4", "cladovka"]

    for h in priority:
        if h not in hosts:
            hosts.append(h)

    try:
        from config import Config
        cfg = Config()
        import urllib.parse
        for url_str in [cfg.server_url, getattr(cfg, "backup_server_url", None)]:
            if url_str:
                parsed = urllib.parse.urlparse(url_str)
                h = parsed.hostname
                if h and h not in hosts:
                    hosts.append(h)
    except Exception:
        pass

    return hosts


def _poll_server_traffic_stats_now(lan_host: Optional[str] = None) -> Optional[dict]:
    """Fast probe: prioritized HTTP API on port 19877, non-blocking fallback to SMB."""
    import json
    import socket
    import urllib.request
    from pathlib import Path

    hosts = _get_candidate_hosts(lan_host)

    for host in hosts:
        # 1. Fast HTTP API first (port 19877) — responds in ~15 ms
        try:
            url = f"http://{host}:19877/traffic"
            req = urllib.request.Request(url, headers={"User-Agent": "DropFile-Monitor/1.0"})
            with urllib.request.urlopen(req, timeout=0.6) as resp:
                raw = resp.read().decode("utf-8")
                if raw:
                    return json.loads(raw)
        except Exception:
            pass

        # 2. SMB fallback only if TCP 445 is immediately reachable (prevents 45s Win32 hang!)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.12)
            err = s.connect_ex((host, 445))
            s.close()
            if err == 0:
                for share in ["Exchange", "DropSync"]:
                    smb_path = Path(rf"\\{host}\{share}\.dropsync\traffic_stats.json")
                    if smb_path.exists():
                        content = smb_path.read_text(encoding="utf-8")
                        if content:
                            data = json.loads(content)
                            if time.time() - float(data.get("timestamp", 0)) < 30.0:
                                return data
        except Exception:
            pass

    return None


def _background_poller_loop() -> None:
    global _SERVER_STATS_CACHE, _POLLER_RUNNING
    while _POLLER_RUNNING:
        try:
            data = _poll_server_traffic_stats_now()
            if data:
                with _CACHE_LOCK:
                    _SERVER_STATS_CACHE = data
        except Exception:
            pass
        time.sleep(1.0)


def fetch_server_traffic_stats(lan_host: Optional[str] = None) -> Optional[dict]:
    """Reads real-time DropSync server traffic stats without blocking Tkinter UI."""
    global _POLLER_THREAD, _POLLER_RUNNING, _SERVER_STATS_CACHE

    if not _POLLER_RUNNING:
        _POLLER_RUNNING = True
        _POLLER_THREAD = threading.Thread(target=_background_poller_loop, daemon=True, name="ServerStatsPoller")
        _POLLER_THREAD.start()

    with _CACHE_LOCK:
        if _SERVER_STATS_CACHE is not None:
            return _SERVER_STATS_CACHE

    # One-shot immediate probe on startup with tight timeout
    data = _poll_server_traffic_stats_now(lan_host)
    if data:
        with _CACHE_LOCK:
            _SERVER_STATS_CACHE = data
    return data


class SpeedMonitorCard(tk.Frame):
    """
    Self-contained widget containing header, dual-area speed chart, and 4-metric statistics grid.
    Can be embedded into any settings tab or window.
    Supports toggling between DropSync Server traffic and local DropFile Client traffic.
    """

    def __init__(self, parent: Any, lang: str = "ru", auto_start: bool = True, **kwargs: Any):
        kwargs.setdefault("bg", "#FFFFFF")
        super().__init__(parent, **kwargs)
        self.lang = lang
        self._is_alive = True

        try:
            from config import Config
            self.mode = Config().speed_monitor_mode
        except Exception:
            self.mode = "server"

        self.monitor = get_traffic_monitor()

        # --- Top Header Row 1: Interface badge on left, Mode Toggle on right ---
        top_row = tk.Frame(self, bg="#FFFFFF")
        top_row.pack(fill="x", padx=12, pady=(8, 2))

        self.lbl_iface = tk.Label(
            top_row,
            text="",
            bg="#FFFFFF",
            fg="#1E293B",
            font=("Segoe UI", 10, "bold"),
        )
        self.lbl_iface.pack(side="left")

        # Mode Toggle Frame (Сервер / Клиент)
        toggle_frame = tk.Frame(top_row, bg="#F1F5F9", padx=2, pady=2)
        toggle_frame.pack(side="right")

        self.btn_mode_server = tk.Button(
            toggle_frame,
            text=self._t("speed_mode_server"),
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=8,
            pady=2,
            command=lambda: self.set_mode("server"),
        )
        self.btn_mode_server.pack(side="left")

        self.btn_mode_client = tk.Button(
            toggle_frame,
            text=self._t("speed_mode_client"),
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=8,
            pady=2,
            command=lambda: self.set_mode("client"),
        )
        self.btn_mode_client.pack(side="left")

        # --- Sub Header Row 2: Status pill (server name/status) first, then Disk Space pill ---
        info_row = tk.Frame(self, bg="#FFFFFF")
        info_row.pack(fill="x", padx=12, pady=(0, 4))

        info_right = tk.Frame(info_row, bg="#FFFFFF")
        info_right.pack(side="right")

        self.lbl_status_pill = tk.Label(
            info_right,
            text="",
            bg="#DCFCE7",
            fg="#15803D",
            padx=8,
            pady=2,
            font=("Segoe UI", 8, "bold"),
        )
        self.lbl_status_pill.pack(side="left")

        self.lbl_disk_pill = tk.Label(
            info_right,
            text="",
            bg="#F1F5F9",
            fg="#475569",
            padx=8,
            pady=2,
            font=("Segoe UI", 8, "bold"),
        )
        # Packed dynamically next to lbl_status_pill (side="left", padx=(6, 0))

        self._update_toggle_styles()

        # --- Canvas Speed Chart ---
        self.chart = SpeedChartWidget(self, width=540, height=140, history_seconds=60, bg="#FFFFFF")
        self.chart.pack(fill="x", expand=True, padx=12, pady=(4, 6))

        # --- Live Legend Bar (Dots + Current Speeds) ---
        legend_row = tk.Frame(self, bg="#FFFFFF")
        legend_row.pack(fill="x", padx=12, pady=(0, 8))

        zero_speed = format_speed(0, lang=self.lang)
        zero_bytes = format_bytes(0, lang=self.lang)
        rx_init = f"● {self._t('speed_rx_legend')}: {zero_speed}"
        tx_init = f"● {self._t('speed_tx_legend')}: {zero_speed}"

        # Rx Legend (Green)
        self.lbl_rx_badge = tk.Label(
            legend_row,
            text=rx_init,
            bg="#FFFFFF",
            fg="#16A34A",
            font=("Segoe UI", 9, "bold"),
        )
        self.lbl_rx_badge.pack(side="left", padx=(0, 16))

        # Tx Legend (Blue)
        self.lbl_tx_badge = tk.Label(
            legend_row,
            text=tx_init,
            bg="#FFFFFF",
            fg="#0284C7",
            font=("Segoe UI", 9, "bold"),
        )
        self.lbl_tx_badge.pack(side="left")

        # Separator line
        tk.Frame(self, height=1, bg="#F1F5F9").pack(fill="x", padx=12, pady=(0, 6))

        # --- File Transfer Progress Block (Live Sync / Upload / Download) ---
        self.transfer_box = tk.Frame(
            self,
            bg="#F8FAFC",
            highlightthickness=1,
            highlightbackground="#E2E8F0",
            padx=10,
            pady=7,
        )
        self.transfer_box.pack(fill="x", padx=12, pady=(0, 8))

        # Row 1: Direction + File name (left) & Percentage (right)
        self.t_row1 = tk.Frame(self.transfer_box, bg="#F8FAFC")
        self.t_row1.pack(fill="x", pady=(0, 3))

        self.lbl_file_name = tk.Label(
            self.t_row1,
            text=self._t("speed_transfer_idle"),
            bg="#F8FAFC",
            fg="#64748B",
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        )
        self.lbl_file_name.pack(side="left", fill="x", expand=True)

        self.lbl_file_pct = tk.Label(
            self.t_row1,
            text="",
            bg="#F8FAFC",
            fg="#0284C7",
            font=("Segoe UI", 9, "bold"),
        )
        self.lbl_file_pct.pack(side="right")

        # Row 2: File Progress Bar (Current File)
        self.progress_bar_file = TransferProgressBar(self.transfer_box, height=6, bg="#E2E8F0", bar_color="#0284C7")
        self.progress_bar_file.pack(fill="x", pady=(0, 4))
        self.progress_bar = self.progress_bar_file

        # Multi-file Batch Container (Total Commander style: shown when batch_total > 1)
        self.batch_container = tk.Frame(self.transfer_box, bg="#F8FAFC")

        self.b_row1 = tk.Frame(self.batch_container, bg="#F8FAFC")
        self.b_row1.pack(fill="x", pady=(1, 2))

        self.lbl_batch_files = tk.Label(
            self.b_row1,
            text="",
            bg="#F8FAFC",
            fg="#1E293B",
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        )
        self.lbl_batch_files.pack(side="left")

        self.lbl_batch_pct = tk.Label(
            self.b_row1,
            text="",
            bg="#F8FAFC",
            fg="#0284C7",
            font=("Segoe UI", 8, "bold"),
            anchor="e",
        )
        self.lbl_batch_pct.pack(side="right")

        self.progress_bar_batch = TransferProgressBar(self.batch_container, height=7, bg="#E2E8F0", bar_color="#0284C7")
        self.progress_bar_batch.pack(fill="x", pady=(0, 4))

        # Row 3 / Footer: Volume / Bytes (left) & Total ETA (right)
        self.t_footer = tk.Frame(self.transfer_box, bg="#F8FAFC")
        self.t_footer.pack(fill="x")

        self.lbl_transfer_bytes = tk.Label(
            self.t_footer,
            text="",
            bg="#F8FAFC",
            fg="#64748B",
            font=("Segoe UI", 8),
            anchor="w",
        )
        self.lbl_transfer_bytes.pack(side="left")

        self.lbl_transfer_eta = tk.Label(
            self.t_footer,
            text="",
            bg="#F8FAFC",
            fg="#64748B",
            font=("Segoe UI", 8),
            anchor="e",
        )
        self.lbl_transfer_eta.pack(side="right")

        # Separator line before stats
        tk.Frame(self, height=1, bg="#F1F5F9").pack(fill="x", padx=12, pady=(0, 6))

        # --- Stats Grid (Keenetic 4-block stats) ---
        stats_grid = tk.Frame(self, bg="#FFFFFF")
        stats_grid.pack(fill="x", padx=12, pady=(0, 8))

        # Col 1: Прием & Передача
        col1 = tk.Frame(stats_grid, bg="#FFFFFF")
        col1.pack(side="left", fill="x", expand=True)

        self.lbl_cur_rx_title = tk.Label(col1, text=self._t("speed_rx_label"), bg="#FFFFFF", fg="#64748B", font=("Segoe UI", 8))
        self.lbl_cur_rx_title.pack(anchor="w")
        self.lbl_cur_rx_val = tk.Label(col1, text=zero_speed, bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 9, "bold"))
        self.lbl_cur_rx_val.pack(anchor="w", pady=(0, 4))

        self.lbl_cur_tx_title = tk.Label(col1, text=self._t("speed_tx_label"), bg="#FFFFFF", fg="#64748B", font=("Segoe UI", 8))
        self.lbl_cur_tx_title.pack(anchor="w")
        self.lbl_cur_tx_val = tk.Label(col1, text=zero_speed, bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 9, "bold"))
        self.lbl_cur_tx_val.pack(anchor="w")

        # Col 2: Принято & Отправлено
        col2 = tk.Frame(stats_grid, bg="#FFFFFF")
        col2.pack(side="right", fill="x", expand=True)

        self.lbl_tot_rx_title = tk.Label(col2, text=self._t("speed_total_rx"), bg="#FFFFFF", fg="#64748B", font=("Segoe UI", 8))
        self.lbl_tot_rx_title.pack(anchor="w")
        self.lbl_tot_rx_val = tk.Label(col2, text=zero_bytes, bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 9, "bold"))
        self.lbl_tot_rx_val.pack(anchor="w", pady=(0, 4))

        self.lbl_tot_tx_title = tk.Label(col2, text=self._t("speed_total_tx"), bg="#FFFFFF", fg="#64748B", font=("Segoe UI", 8))
        self.lbl_tot_tx_title.pack(anchor="w")
        self.lbl_tot_tx_val = tk.Label(col2, text=zero_bytes, bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 9, "bold"))
        self.lbl_tot_tx_val.pack(anchor="w")

        if auto_start:
            self._schedule_tick()

    def _t(self, key: str, **kwargs: Any) -> str:
        """Translates key for this card's active language."""
        return t(key, lang=self.lang, **kwargs)

    def update_language(self, lang: Optional[str] = None) -> None:
        """Dynamically retranslates all card widgets."""
        if lang:
            self.lang = lang
        self._update_toggle_styles()
        self.btn_mode_server.config(text=self._t("speed_mode_server"))
        self.btn_mode_client.config(text=self._t("speed_mode_client"))
        self.lbl_cur_rx_title.config(text=self._t("speed_rx_label"))
        self.lbl_cur_tx_title.config(text=self._t("speed_tx_label"))
        self.lbl_tot_rx_title.config(text=self._t("speed_total_rx"))
        self.lbl_tot_tx_title.config(text=self._t("speed_total_tx"))
        self.update_view()

    def set_mode(self, mode: str) -> None:
        """Switches monitoring mode between 'server' and 'client'."""
        self.mode = "client" if mode == "client" else "server"
        try:
            from config import Config
            cfg = Config()
            cfg.speed_monitor_mode = self.mode
            cfg.save()
        except Exception:
            pass
        self._update_toggle_styles()
        self.update_view()

    def _update_toggle_styles(self) -> None:
        if self.mode == "server":
            self.btn_mode_server.config(bg="#0284C7", fg="#FFFFFF")
            self.btn_mode_client.config(bg="#F1F5F9", fg="#64748B")
            self.lbl_iface.config(text=self._t("speed_iface_server"))
        else:
            self.btn_mode_server.config(bg="#F1F5F9", fg="#64748B")
            self.btn_mode_client.config(bg="#0284C7", fg="#FFFFFF")
            self.lbl_iface.config(text=self._t("speed_iface_client"))

    def update_view(self) -> None:
        """Pulls latest metrics from selected source (Server or Client) and redraws chart."""
        if not self._is_alive:
            return

        transfer_info = None
        s_data = None
        if self.mode == "server":
            s_data = fetch_server_traffic_stats()
            if s_data:
                node = s_data.get("node_name", "")
                connected = s_data.get("connected", True)
                online_suffix = self._t("speed_status_online")
                offline_suffix = self._t("speed_status_offline")
                node_label = f"● {node}: {online_suffix}" if node else self._t("speed_status_server_online")
                node_offline = f"○ {node}: {offline_suffix}" if node else self._t("speed_status_server_offline")
                if connected:
                    self.lbl_status_pill.config(
                        text=node_label,
                        bg="#DCFCE7",
                        fg="#15803D",
                    )
                else:
                    self.lbl_status_pill.config(
                        text=node_offline,
                        bg="#FEF3C7",
                        fg="#B45309",
                    )

                history = s_data.get("history", [])
                tot_rx = s_data.get("total_rx", 0)
                tot_tx = s_data.get("total_tx", 0)
                transfer_info = s_data.get("current_transfer")
            else:
                self.lbl_status_pill.config(
                    text=self._t("speed_status_server_offline"),
                    bg="#F1F5F9",
                    fg="#94A3B8",
                )
                history = []
                tot_rx, tot_tx = 0, 0
        else:
            # Client mode
            self.lbl_status_pill.config(
                text=self._t("speed_status_client_active"),
                bg="#DCFCE7",
                fg="#15803D",
            )
            history = self.monitor.get_history(seconds=60)
            tot_rx, tot_tx = self.monitor.get_totals()
            transfer_info = get_client_transfer()

        # Update disk space badge if available (from server stats or local exchange)
        free_b = s_data.get("disk_free") if s_data else None
        tot_b = s_data.get("disk_total") if s_data else None
        if free_b is None or tot_b is None:
            try:
                import shutil
                from pathlib import Path
                from config import Config
                cfg = Config()
                for p in [getattr(cfg, "lan_share_path", None), getattr(cfg, "exchange_folder_local", None), getattr(cfg, "exchange_path", None)]:
                    if p and Path(p).exists():
                        du = shutil.disk_usage(p)
                        free_b = du.free
                        tot_b = du.total
                        break
            except Exception:
                pass

        if free_b is not None and tot_b is not None and tot_b > 0:
            free_str = format_bytes(free_b, lang=self.lang)
            tot_str = format_bytes(tot_b, lang=self.lang)
            disk_txt = self._t("disk_space_short", free=free_str, total=tot_str)
            self.lbl_disk_pill.config(text=disk_txt)
            try:
                if not self.lbl_disk_pill.winfo_ismapped():
                    self.lbl_disk_pill.pack(side="left", padx=(6, 0))
            except Exception:
                pass
        else:
            try:
                if self.lbl_disk_pill.winfo_ismapped():
                    self.lbl_disk_pill.pack_forget()
            except Exception:
                pass

        rx_str, tx_str, peak_str, time_str = self.chart.render(history, lang=self.lang)

        # Update legend text
        rx_text = f"● {self._t('speed_rx_legend')}: {rx_str}"
        tx_text = f"● {self._t('speed_tx_legend')}: {tx_str}"
        self.lbl_rx_badge.config(text=rx_text)
        self.lbl_tx_badge.config(text=tx_text)

        # Update current rates
        self.lbl_cur_rx_val.config(text=rx_str)
        self.lbl_cur_tx_val.config(text=tx_str)

        # Update session totals
        self.lbl_tot_rx_val.config(text=format_bytes(tot_rx, lang=self.lang))
        self.lbl_tot_tx_val.config(text=format_bytes(tot_tx, lang=self.lang))

        # Update active file transfer progress bar
        self._update_transfer_ui(transfer_info)

    def _update_transfer_ui(self, transfer: Optional[dict]) -> None:
        """Updates the file transfer progress indicator with file name, progress bar(s), bytes, and ETA."""
        if not transfer or not transfer.get("file_name"):
            self.lbl_file_name.config(
                text=self._t("speed_transfer_idle"),
                fg="#64748B",
            )
            self.lbl_file_pct.config(text="")
            self.progress_bar_file.set_progress(0, "#CBD5E1")
            try:
                if self.batch_container.winfo_manager() == "pack":
                    self.batch_container.pack_forget()
            except Exception:
                pass
            self.lbl_transfer_bytes.config(text="")
            self.lbl_transfer_eta.config(text="")
            return

        direction = transfer.get("direction", "tx")
        rel_path = transfer.get("rel_path")
        file_name = str(rel_path or transfer.get("file_name", ""))
        # Cleanly truncate overly long paths/file names
        if len(file_name) > 38:
            file_name = file_name[:18] + "..." + file_name[-17:]

        total_bytes = transfer.get("total_size") or transfer.get("total_bytes", 0)
        transferred = transfer.get("transferred_bytes", 0)
        pct = transfer.get("percent")
        if pct is None:
            pct = round((transferred / total_bytes) * 100.0, 1) if total_bytes > 0 else 0.0
        pct = min(100.0, max(0.0, float(pct)))

        is_tx = direction == "tx"
        color = "#0284C7" if is_tx else "#16A34A"  # Blue for upload/tx, Green for download/rx
        title_key = "speed_transfer_uploading" if is_tx else "speed_transfer_downloading"
        title_text = self._t(title_key, name=file_name)

        self.lbl_file_name.config(text=title_text, fg=color)
        pct_display = f"{int(pct)} %" if pct.is_integer() else f"{pct:.1f} %"
        self.lbl_file_pct.config(text=pct_display, fg=color)
        self.progress_bar_file.set_progress(pct, color)

        batch_total = transfer.get("batch_total", 1)
        batch_current = transfer.get("batch_current", 1)
        batch_bytes_total = transfer.get("batch_bytes_total", total_bytes)
        batch_bytes_transferred = transfer.get("batch_bytes_transferred", transferred)
        batch_pct = transfer.get("batch_percent", pct)

        if batch_total > 1:
            # Multi-file batch transfer (Total Commander style)
            try:
                if self.batch_container.winfo_manager() != "pack":
                    self.batch_container.pack(fill="x", before=self.t_footer)
            except Exception:
                self.batch_container.pack(fill="x")
            self.lbl_batch_files.config(text=f"{batch_current} / {batch_total}")
            b_pct_val = min(100.0, max(0.0, float(batch_pct)))
            b_pct_display = f"{int(b_pct_val)} %" if b_pct_val.is_integer() else f"{b_pct_val:.1f} %"
            self.lbl_batch_pct.config(text=b_pct_display, fg=color)
            self.progress_bar_batch.set_progress(b_pct_val, color)

            # Footer shows batch volume
            bytes_text = f"{format_bytes(batch_bytes_transferred, lang=self.lang)} / {format_bytes(batch_bytes_total, lang=self.lang)}"
            self.lbl_transfer_bytes.config(text=bytes_text)
        else:
            # Single file mode
            try:
                if self.batch_container.winfo_manager() == "pack":
                    self.batch_container.pack_forget()
            except Exception:
                pass
            bytes_text = f"{format_bytes(transferred, lang=self.lang)} / {format_bytes(total_bytes, lang=self.lang)}"
            self.lbl_transfer_bytes.config(text=bytes_text)

        eta_sec = transfer.get("eta_seconds")
        eta_str = format_eta(eta_sec, lang=self.lang)
        if eta_sec is not None and eta_sec >= 0:
            eta_tpl = self._t("speed_transfer_eta", eta=eta_str)
            self.lbl_transfer_eta.config(text=eta_tpl)
        else:
            self.lbl_transfer_eta.config(text="")

    def _schedule_tick(self) -> None:
        if not self._is_alive:
            return
        try:
            self.update_view()
            if self._is_alive:
                self._timer_id = self.after(1000, self._schedule_tick)
        except Exception:
            pass

    def stop(self) -> None:
        self._is_alive = False
        if hasattr(self, "_timer_id") and self._timer_id is not None:
            try:
                self.after_cancel(self._timer_id)
            except Exception:
                pass
            self._timer_id = None

    def destroy(self) -> None:
        self.stop()
        super().destroy()


class SpeedMonitorWindow:
    """
    Dedicated floating window for real-time network traffic and speed monitoring.
    Features Keenetic aesthetics, always-on-top toggle, and live updates.
    """

    _INSTANCE: Optional["SpeedMonitorWindow"] = None

    @classmethod
    def show_or_focus(cls, parent: Optional[tk.Tk] = None, lang: Optional[str] = None) -> "SpeedMonitorWindow":
        if lang is None:
            try:
                from config import Config
                lang = Config().language
            except Exception:
                from i18n import get_current_language
                lang = get_current_language()

        try:
            from i18n import set_current_language
            set_current_language(lang)
        except Exception:
            pass

        if cls._INSTANCE is not None and cls._INSTANCE.is_alive():
            try:
                cls._INSTANCE.update_language(lang)
                cls._INSTANCE.window.lift()
                cls._INSTANCE.window.focus_force()
                return cls._INSTANCE
            except Exception:
                cls._INSTANCE = None

        inst = cls(parent=parent, lang=lang)
        cls._INSTANCE = inst
        if getattr(inst, "_owns_root", False):
            try:
                inst.window.mainloop()
            except Exception:
                pass
        return inst

    def __init__(self, parent: Optional[tk.Tk] = None, lang: Optional[str] = None):
        if not lang:
            try:
                from config import Config
                lang = Config().language
            except Exception:
                from i18n import get_current_language
                lang = get_current_language()
        try:
            from i18n import set_current_language
            set_current_language(lang)
        except Exception:
            pass
        self.lang = lang
        self._owns_root = False

        if parent is not None:
            try:
                if parent.winfo_exists():
                    self.window = tk.Toplevel(parent)
                else:
                    self.window = tk.Tk()
                    self._owns_root = True
            except Exception:
                self.window = tk.Tk()
                self._owns_root = True
        else:
            try:
                if tk._default_root is not None and tk._default_root.winfo_exists():
                    self.window = tk.Toplevel(tk._default_root)
                else:
                    self.window = tk.Tk()
                    self._owns_root = True
            except Exception:
                self.window = tk.Tk()
                self._owns_root = True

        self.window.title(f"{t('app_name', lang=self.lang)} — {t('speed_monitor_title', lang=self.lang)}")

        # Restore geometry or use comfortable default 660x580
        saved_geom = "660x580"
        try:
            from config import Config
            cfg_geom = Config().speed_window_geometry
            if cfg_geom and "x" in cfg_geom:
                saved_geom = cfg_geom
        except Exception:
            pass

        self.window.geometry(saved_geom)
        self.window.minsize(540, 480)
        self.window.configure(bg="#F8FAFC")

        # Set window icon
        from pathlib import Path
        ico_path = Path(__file__).resolve().parent / "icon.ico"
        if getattr(sys, "frozen", False):
            candidate = Path(sys.executable).parent / "icon.ico"
            if candidate.exists():
                ico_path = candidate
            elif hasattr(sys, "_MEIPASS"):
                candidate = Path(sys._MEIPASS) / "icon.ico"
                if candidate.exists():
                    ico_path = candidate
        if ico_path.exists():
            if sys.platform.startswith("win"):
                try:
                    self.window.iconbitmap(str(ico_path))
                except Exception:
                    pass
            else:
                try:
                    from PIL import Image, ImageTk
                    img = Image.open(ico_path)
                    photo = ImageTk.PhotoImage(img)
                    self.window.iconphoto(True, photo)
                except Exception:
                    pass

        # Ensure clean close
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        # Top banner with Title and Always-on-top toggle
        header_bar = tk.Frame(self.window, bg="#FFFFFF", padx=16, pady=10)
        header_bar.pack(fill="x")

        self.lbl_win_title = tk.Label(
            header_bar,
            text=f"📈 {t('speed_monitor_title', lang=self.lang)}",
            font=("Segoe UI", 11, "bold"),
            bg="#FFFFFF",
            fg="#0F172A",
        )
        self.lbl_win_title.pack(side="left")

        self.var_ontop = tk.BooleanVar(value=False)
        self.chk_ontop = ttk.Checkbutton(
            header_bar,
            text=t("speed_always_on_top", lang=self.lang),
            variable=self.var_ontop,
            command=self._toggle_on_top,
        )
        self.chk_ontop.pack(side="right")

        tk.Frame(self.window, height=1, bg="#E2E8F0").pack(fill="x")

        # Container card
        card_outer = tk.Frame(self.window, bg="#F8FAFC", padx=14, pady=12)
        card_outer.pack(fill="both", expand=True)

        self.card = SpeedMonitorCard(card_outer, lang=self.lang, auto_start=True)
        self.card.pack(fill="both", expand=True)

    def update_language(self, lang: str) -> None:
        """Dynamically retranslates window controls and card when language changes."""
        self.lang = lang
        try:
            self.window.title(f"{t('app_name', lang=self.lang)} — {t('speed_monitor_title', lang=self.lang)}")
            if hasattr(self, "lbl_win_title"):
                self.lbl_win_title.config(text=f"📈 {t('speed_monitor_title', lang=self.lang)}")
            if hasattr(self, "chk_ontop"):
                self.chk_ontop.config(text=t("speed_always_on_top", lang=self.lang))
            if hasattr(self, "card") and self.card:
                self.card.update_language(lang)
        except Exception:
            pass

    def _toggle_on_top(self) -> None:
        try:
            self.window.attributes("-topmost", self.var_ontop.get())
        except Exception:
            pass

    def is_alive(self) -> bool:
        try:
            return self.window is not None and self.window.winfo_exists()
        except Exception:
            return False

    def _on_close(self) -> None:
        SpeedMonitorWindow._INSTANCE = None
        try:
            geom = self.window.geometry()
            if geom and "x" in geom:
                from config import Config
                cfg = Config()
                cfg.speed_window_geometry = geom
                cfg.save()
        except Exception:
            pass
        try:
            if hasattr(self, "card"):
                self.card._is_alive = False
            self.window.destroy()
        except Exception:
            pass
