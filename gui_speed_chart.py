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
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, List, Optional, Tuple

from i18n import t
from traffic_monitor import format_bytes, format_speed, get_traffic_monitor


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
            return ("0 бит/с", "0 бит/с", "0 бит/с", "")

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


class SpeedMonitorCard(tk.Frame):
    """
    Self-contained card component containing the SpeedChartWidget,
    live legend badges, and session volume counters.
    Can be embedded into any settings tab or window.
    """

    def __init__(self, parent: Any, lang: str = "ru", auto_start: bool = True, **kwargs: Any):
        kwargs.setdefault("bg", "#FFFFFF")
        super().__init__(parent, **kwargs)
        self.lang = lang
        self._is_alive = True

        self.monitor = get_traffic_monitor()

        # --- Top Header Row: Interface badge & Live status ---
        top_row = tk.Frame(self, bg="#FFFFFF")
        top_row.pack(fill="x", padx=12, pady=(8, 4))

        self.lbl_iface = tk.Label(
            top_row,
            text="Ethernet / DropSync LAN",
            bg="#FFFFFF",
            fg="#1E293B",
            font=("Segoe UI", 10, "bold"),
        )
        self.lbl_iface.pack(side="left")

        self.lbl_status_pill = tk.Label(
            top_row,
            text=f"● {t('status_connected') if hasattr(t, '__call__') else 'ПОДКЛЮЧЕНО'}",
            bg="#DCFCE7",
            fg="#15803D",
            padx=8,
            pady=2,
            font=("Segoe UI", 8, "bold"),
        )
        self.lbl_status_pill.pack(side="right")

        # --- Canvas Speed Chart ---
        self.chart = SpeedChartWidget(self, width=540, height=140, history_seconds=60, bg="#FFFFFF")
        self.chart.pack(fill="x", expand=True, padx=12, pady=(4, 6))

        # --- Live Legend Bar (Dots + Current Speeds) ---
        legend_row = tk.Frame(self, bg="#FFFFFF")
        legend_row.pack(fill="x", padx=12, pady=(0, 8))

        # Rx Legend (Green)
        self.lbl_rx_badge = tk.Label(
            legend_row,
            text="● Прием: 0 кбит/с",
            bg="#FFFFFF",
            fg="#16A34A",
            font=("Segoe UI", 9, "bold"),
        )
        self.lbl_rx_badge.pack(side="left", padx=(0, 16))

        # Tx Legend (Blue)
        self.lbl_tx_badge = tk.Label(
            legend_row,
            text="● Передача: 0 кбит/с",
            bg="#FFFFFF",
            fg="#0284C7",
            font=("Segoe UI", 9, "bold"),
        )
        self.lbl_tx_badge.pack(side="left")

        # Separator line
        tk.Frame(self, height=1, bg="#F1F5F9").pack(fill="x", padx=12, pady=(0, 8))

        # --- Stats Grid (Keenetic 4-block stats) ---
        stats_grid = tk.Frame(self, bg="#FFFFFF")
        stats_grid.pack(fill="x", padx=12, pady=(0, 10))

        # Col 1: Прием & Передача
        col1 = tk.Frame(stats_grid, bg="#FFFFFF")
        col1.pack(side="left", fill="x", expand=True)

        self.lbl_cur_rx_title = tk.Label(col1, text=t("speed_rx_label"), bg="#FFFFFF", fg="#64748B", font=("Segoe UI", 8))
        self.lbl_cur_rx_title.pack(anchor="w")
        self.lbl_cur_rx_val = tk.Label(col1, text="0 кбит/с", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 9, "bold"))
        self.lbl_cur_rx_val.pack(anchor="w", pady=(0, 4))

        self.lbl_cur_tx_title = tk.Label(col1, text=t("speed_tx_label"), bg="#FFFFFF", fg="#64748B", font=("Segoe UI", 8))
        self.lbl_cur_tx_title.pack(anchor="w")
        self.lbl_cur_tx_val = tk.Label(col1, text="0 кбит/с", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 9, "bold"))
        self.lbl_cur_tx_val.pack(anchor="w")

        # Col 2: Принято & Отправлено
        col2 = tk.Frame(stats_grid, bg="#FFFFFF")
        col2.pack(side="right", fill="x", expand=True)

        self.lbl_tot_rx_title = tk.Label(col2, text=t("speed_total_rx"), bg="#FFFFFF", fg="#64748B", font=("Segoe UI", 8))
        self.lbl_tot_rx_title.pack(anchor="w")
        self.lbl_tot_rx_val = tk.Label(col2, text="0 КБ", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 9, "bold"))
        self.lbl_tot_rx_val.pack(anchor="w", pady=(0, 4))

        self.lbl_tot_tx_title = tk.Label(col2, text=t("speed_total_tx"), bg="#FFFFFF", fg="#64748B", font=("Segoe UI", 8))
        self.lbl_tot_tx_title.pack(anchor="w")
        self.lbl_tot_tx_val = tk.Label(col2, text="0 КБ", bg="#FFFFFF", fg="#0F172A", font=("Segoe UI", 9, "bold"))
        self.lbl_tot_tx_val.pack(anchor="w")

        if auto_start:
            self._schedule_tick()

    def update_view(self) -> None:
        """Pulls latest metrics from TrafficMonitor and redraws chart."""
        if not self._is_alive:
            return

        history = self.monitor.get_history(seconds=60)
        rx_str, tx_str, peak_str, time_str = self.chart.render(history, lang=self.lang)

        # Update legend text
        rx_text = f"● {t('speed_rx_legend')}: {rx_str}"
        tx_text = f"● {t('speed_tx_legend')}: {tx_str}"
        self.lbl_rx_badge.config(text=rx_text)
        self.lbl_tx_badge.config(text=tx_text)

        # Update current rates
        self.lbl_cur_rx_val.config(text=rx_str)
        self.lbl_cur_tx_val.config(text=tx_str)

        # Update session totals
        tot_rx, tot_tx = self.monitor.get_totals()
        self.lbl_tot_rx_val.config(text=format_bytes(tot_rx, lang=self.lang))
        self.lbl_tot_tx_val.config(text=format_bytes(tot_tx, lang=self.lang))

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
    def show_or_focus(cls, parent: Optional[tk.Tk] = None, lang: str = "ru") -> "SpeedMonitorWindow":
        if cls._INSTANCE is not None and cls._INSTANCE.is_alive():
            try:
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

    def __init__(self, parent: Optional[tk.Tk] = None, lang: str = "ru"):
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

        self.window.title(f"{t('app_name')} — {t('speed_monitor_title')}")
        self.window.geometry("580x360")
        self.window.minsize(480, 320)
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

        lbl_title = tk.Label(
            header_bar,
            text=f"📈 {t('speed_monitor_title')}",
            font=("Segoe UI", 11, "bold"),
            bg="#FFFFFF",
            fg="#0F172A",
        )
        lbl_title.pack(side="left")

        self.var_ontop = tk.BooleanVar(value=False)
        chk_ontop = ttk.Checkbutton(
            header_bar,
            text=t("speed_always_on_top"),
            variable=self.var_ontop,
            command=self._toggle_on_top,
        )
        chk_ontop.pack(side="right")

        tk.Frame(self.window, height=1, bg="#E2E8F0").pack(fill="x")

        # Container card
        card_outer = tk.Frame(self.window, bg="#F8FAFC", padx=14, pady=12)
        card_outer.pack(fill="both", expand=True)

        self.card = SpeedMonitorCard(card_outer, lang=self.lang, auto_start=True)
        self.card.pack(fill="both", expand=True)

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
            if hasattr(self, "card"):
                self.card._is_alive = False
            self.window.destroy()
        except Exception:
            pass
