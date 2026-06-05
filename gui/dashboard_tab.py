"""
dashboard_tab.py — Dashboard tab with connection status and quick controls.

Shows the animated connection status circle, the big Connect/Disconnect
button, a live uptime counter, quick stats, and toggle switches for
System Proxy, TUN Mode, LAN Sharing, and Ad Blocker.

Traffic monitor measures physical-interface bytes (not loopback)
so it works correctly on both Windows and Linux.
"""

from __future__ import annotations

import math
import time
from typing import Optional

from PyQt6.QtCore import (
    QEasingCurve, QPropertyAnimation, QRectF, QTimer, Qt, pyqtProperty,
)
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)


# ─── Animated connection orb ──────────────────────────────────────────────────

class ConnectionOrb(QWidget):
    """
    An animated circle that reflects the current connection state.

    States
    ------
    ``disconnected``  — solid grey
    ``connecting``    — pulsing yellow/amber
    ``connected``     — pulsing green
    ``error``         — solid red
    """

    _COLORS = {
        "disconnected": ("#666688", "#444466"),
        "connecting":   ("#FFA726", "#E65100"),
        "connected":    ("#4CAF50", "#2E7D32"),
        "error":        ("#F44336", "#B71C1C"),
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(120, 120)
        self._state = "disconnected"
        self._pulse = 0.0          # 0.0 – 1.0 glow factor
        self._direction = 1

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(30)      # ~33 fps

    def set_state(self, state: str) -> None:
        self._state = state
        if state in ("connecting", "connected"):
            self._timer.start(30)
        else:
            self._timer.stop()
            self._pulse = 0.0
            self.update()

    def _animate(self) -> None:
        speed = 0.03 if self._state == "connecting" else 0.02
        self._pulse += speed * self._direction
        if self._pulse >= 1.0:
            self._direction = -1
        elif self._pulse <= 0.0:
            self._direction = 1
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 10

        color_inner, color_outer = self._COLORS.get(
            self._state, self._COLORS["disconnected"]
        )

        # Glow ring (when pulsing)
        if self._pulse > 0 and self._state in ("connecting", "connected"):
            glow_alpha = int(100 * self._pulse)
            glow_r = r + 12 * self._pulse
            glow_color = QColor(color_inner)
            glow_color.setAlpha(glow_alpha)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(glow_color))
            p.drawEllipse(QRectF(cx - glow_r, cy - glow_r, glow_r * 2, glow_r * 2))

        # Outer ring
        pen = QPen(QColor(color_outer), 3)
        p.setPen(pen)
        p.setBrush(QBrush(QColor(color_inner)))
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # Icon symbol
        p.setPen(QPen(QColor("#FFFFFF"), 2.5))
        if self._state == "connected":
            # Checkmark
            pts_x = [cx - 10, cx - 3, cx + 11]
            pts_y = [cy + 2, cy + 9, cy - 8]
            for i in range(len(pts_x) - 1):
                p.drawLine(int(pts_x[i]), int(pts_y[i]), int(pts_x[i+1]), int(pts_y[i+1]))
        elif self._state == "error":
            # X mark
            p.drawLine(int(cx - 8), int(cy - 8), int(cx + 8), int(cy + 8))
            p.drawLine(int(cx + 8), int(cy - 8), int(cx - 8), int(cy + 8))
        elif self._state == "connecting":
            # Spinner arc
            rect = QRectF(cx - 10, cy - 10, 20, 20)
            angle = int(self._pulse * 360 * 16)
            p.drawArc(rect, angle, 240 * 16)
        else:
            # Power icon
            p.drawArc(QRectF(cx - 9, cy - 6, 18, 16), 0, 16 * 360)
            p.drawLine(int(cx), int(cy - 14), int(cx), int(cy - 2))

        p.end()


# ─── Toggle switch widget ─────────────────────────────────────────────────────

class ToggleSwitch(QWidget):
    """
    A Material-style toggle switch.

    Emits ``toggled(bool)`` when clicked.
    """

    toggled_signal = None  # Set per instance

    def __init__(self, parent=None) -> None:
        from PyQt6.QtCore import pyqtSignal

        super().__init__(parent)
        self.setFixedSize(48, 26)
        self._checked = False
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click to toggle")

        # Create signal dynamically via class hack
        self.__class__._make_signal(self)

    @classmethod
    def _make_signal(cls, instance):
        pass  # Signals are defined below properly

    def is_checked(self) -> bool:
        return self._checked

    def set_checked(self, value: bool) -> None:
        if self._checked != value:
            self._checked = value
            self.update()

    def mousePressEvent(self, event) -> None:
        self._checked = not self._checked
        self.update()
        self._emit_toggled()

    def _emit_toggled(self) -> None:
        # Parent containers connect via the 'toggled' attribute
        pass

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        track_color = QColor("#4CAF50") if self._checked else QColor("#555575")
        if self._hover:
            track_color = track_color.lighter(115)

        # Track
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(track_color))
        p.drawRoundedRect(0, 4, 48, 18, 9, 9)

        # Knob
        knob_x = 26 if self._checked else 4
        p.setBrush(QBrush(QColor("#FFFFFF")))
        p.drawEllipse(knob_x, 2, 22, 22)
        p.end()


class LabeledToggle(QWidget):
    """A toggle switch with a label and optional callback."""

    def __init__(self, label: str, tooltip: str = "", parent=None) -> None:
        super().__init__(parent)
        self._callback = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel(label)
        self.label.setMinimumWidth(130)
        self.toggle = ToggleSwitch()
        if tooltip:
            self.toggle.setToolTip(tooltip)
            self.label.setToolTip(tooltip)

        layout.addWidget(self.label)
        layout.addWidget(self.toggle)
        layout.addStretch()

        # Wire toggle
        self.toggle.mousePressEvent = self._on_toggle_click

    def _on_toggle_click(self, event) -> None:
        self.toggle._checked = not self.toggle._checked
        self.toggle.update()
        if self._callback:
            self._callback(self.toggle._checked)

    def set_callback(self, fn) -> None:
        self._callback = fn

    def is_checked(self) -> bool:
        return self.toggle.is_checked()

    def set_checked(self, value: bool) -> None:
        self.toggle.set_checked(value)


# ─── Quick stats badge ────────────────────────────────────────────────────────

class StatBadge(QFrame):
    """A small labelled stat badge."""

    def __init__(self, title: str, value: str = "—", parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame { border-radius: 6px; background: rgba(61,61,92,0.5); padding: 6px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)

        self._title = QLabel(title)
        self._title.setStyleSheet("font-size: 10px; color: #888; font-weight: bold;")
        self._value = QLabel(value)
        self._value.setStyleSheet("font-size: 13px; color: #CDD6F4; font-weight: bold;")

        layout.addWidget(self._title)
        layout.addWidget(self._value)

    def set_value(self, v: str) -> None:
        self._value.setText(v)


# ─── Traffic helpers ──────────────────────────────────────────────────────────

# Loopback names to exclude when summing physical-interface traffic
_LOOPBACK_NAMES = frozenset({
    "lo", "lo0",
    "loopback pseudo-interface 1",   # Windows
    "loopback",
})


def _fmt_bytes(n: float, per_sec: bool = False) -> str:
    """Format a byte count as a human-readable string."""
    suffix = "/s" if per_sec else ""
    if n >= 1_073_741_824:
        return f"{n / 1_073_741_824:.2f} GB{suffix}"
    if n >= 1_048_576:
        return f"{n / 1_048_576:.2f} MB{suffix}"
    if n >= 1024:
        return f"{n / 1024:.2f} KB{suffix}"
    return f"{n:.0f} B{suffix}"


# ─── DashboardTab ─────────────────────────────────────────────────────────────

class DashboardTab(QWidget):
    """
    Main dashboard tab showing connection status and quick controls.

    Signals are connected to the parent window's ProxyThread machinery.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._connect_time: Optional[float] = None
        self._uptime_timer = QTimer(self)
        self._uptime_timer.timeout.connect(self._update_uptime)

        # Traffic tracking
        self._traffic_timer = QTimer(self)
        self._traffic_timer.timeout.connect(self._update_traffic)

        # Snapshot at connection start (sum of physical interfaces)
        self._baseline_sent: int = 0
        self._baseline_recv: int = 0
        # Previous sample for delta (speed) calculation
        self._prev_sent: int = 0
        self._prev_recv: int = 0
        # Accumulated deltas since connection
        self._total_sent: int = 0
        self._total_recv: int = 0

        self._psutil_available: bool = False
        try:
            import psutil  # noqa: F401
            self._psutil_available = True
        except ImportError:
            pass

        self._setup_ui()

    # ── UI setup ───────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 30, 40, 30)
        outer.setSpacing(20)

        # ── Connection status ──────────────────────────────────────────
        status_frame = QFrame()
        status_frame.setFrameShape(QFrame.Shape.StyledPanel)
        status_frame.setStyleSheet(
            "QFrame { border-radius: 12px; background: rgba(37,37,53,0.8); }"
        )
        status_layout = QVBoxLayout(status_frame)
        status_layout.setContentsMargins(30, 24, 30, 24)
        status_layout.setSpacing(8)

        # Orb + text row
        orb_row = QHBoxLayout()
        orb_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.orb = ConnectionOrb()
        orb_row.addWidget(self.orb)

        orb_text = QVBoxLayout()
        orb_text.setSpacing(4)

        self.lbl_status = QLabel("Disconnected")
        self.lbl_status.setObjectName("label_status_main")
        font = QFont()
        font.setPointSize(20)
        font.setBold(True)
        self.lbl_status.setFont(font)

        self.lbl_uptime = QLabel("—")
        self.lbl_uptime.setObjectName("label_status_sub")

        self.lbl_ip = QLabel("")
        self.lbl_ip.setObjectName("label_status_sub")

        self.lbl_script = QLabel("")
        self.lbl_script.setObjectName("label_status_sub")

        orb_text.addWidget(self.lbl_status)
        orb_text.addWidget(self.lbl_uptime)
        orb_text.addWidget(self.lbl_ip)
        orb_text.addWidget(self.lbl_script)

        orb_row.addSpacing(20)
        orb_row.addLayout(orb_text)
        status_layout.addLayout(orb_row)

        outer.addWidget(status_frame)

        # ── Connect / Disconnect button ────────────────────────────────
        self.btn_connect = QPushButton("▶  Connect")
        self.btn_connect.setObjectName("btn_connect")
        self.btn_connect.setMinimumHeight(54)
        self.btn_connect.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        outer.addWidget(self.btn_connect)

        # ── Quick stats row ────────────────────────────────────────────
        stats_row = QHBoxLayout()
        self.stat_exec = StatBadge("Apps Script Execs", "0")
        self.stat_h2 = StatBadge("H2 Connection", "—")
        self.stat_mode = StatBadge("Proxy Mode", "—")

        for badge in (self.stat_exec, self.stat_h2, self.stat_mode):
            stats_row.addWidget(badge)

        outer.addLayout(stats_row)

        # ── Quick toggles ──────────────────────────────────────────────
        toggles_frame = QFrame()
        toggles_frame.setFrameShape(QFrame.Shape.StyledPanel)
        toggles_frame.setStyleSheet(
            "QFrame { border-radius: 10px; background: rgba(37,37,53,0.6); }"
        )
        tl = QVBoxLayout(toggles_frame)
        tl.setContentsMargins(20, 16, 20, 16)
        tl.setSpacing(10)

        tl.addWidget(QLabel("Quick Toggles"))

        toggles_grid = QHBoxLayout()

        left_col = QVBoxLayout()
        right_col = QVBoxLayout()

        self.tog_sys_proxy = LabeledToggle(
            "System Proxy",
            "Route browser traffic through the local proxy via OS settings."
        )
        self.tog_tun = LabeledToggle(
            "TUN Mode",
            "Route ALL application traffic (not just browsers) via a virtual TUN adapter."
        )
        self.tog_lan = LabeledToggle(
            "LAN Sharing",
            "Allow other devices on the local network to use this proxy."
        )
        self.tog_adblock = LabeledToggle(
            "Ad Blocker",
            "Block ads and trackers using the configured host lists."
        )

        left_col.addWidget(self.tog_sys_proxy)
        left_col.addWidget(self.tog_lan)
        right_col.addWidget(self.tog_tun)
        right_col.addWidget(self.tog_adblock)

        toggles_grid.addLayout(left_col)
        toggles_grid.addLayout(right_col)
        tl.addLayout(toggles_grid)

        outer.addWidget(toggles_frame)

        # ── Traffic Stats ──────────────────────────────────────────────
        traffic_frame = QFrame()
        traffic_frame.setFrameShape(QFrame.Shape.StyledPanel)
        traffic_frame.setStyleSheet(
            "QFrame { border-radius: 10px; background: rgba(37,37,53,0.6); }"
        )
        traf_layout = QVBoxLayout(traffic_frame)
        traf_layout.setContentsMargins(20, 14, 20, 14)
        traf_layout.setSpacing(8)

        # Header row with source note
        header_row = QHBoxLayout()
        traf_title = QLabel("Traffic Monitor (Session)")
        traf_title.setStyleSheet("font-weight: bold; color: #CCC;")
        header_row.addWidget(traf_title)
        header_row.addStretch()
        self.lbl_traffic_iface = QLabel("")
        self.lbl_traffic_iface.setStyleSheet("font-size: 10px; color: #666;")
        header_row.addWidget(self.lbl_traffic_iface)
        traf_layout.addLayout(header_row)

        # Real-time speed row
        speed_row = QHBoxLayout()
        self.lbl_speed_down = self._make_traffic_label("↓  0.00 KB/s", "#4CAF50")
        self.lbl_speed_up   = self._make_traffic_label("↑  0.00 KB/s", "#2196F3")
        speed_row.addWidget(self.lbl_speed_down)
        speed_row.addSpacing(24)
        speed_row.addWidget(self.lbl_speed_up)
        speed_row.addStretch()
        traf_layout.addLayout(speed_row)

        # Total transfer row
        total_row = QHBoxLayout()
        self.lbl_total_down = self._make_traffic_label("Total ↓  0.00 MB", "#81C784")
        self.lbl_total_up   = self._make_traffic_label("Total ↑  0.00 MB", "#64B5F6")
        total_row.addWidget(self.lbl_total_down)
        total_row.addSpacing(24)
        total_row.addWidget(self.lbl_total_up)
        total_row.addStretch()
        traf_layout.addLayout(total_row)

        if not self._psutil_available:
            note = QLabel("Install psutil for real-time traffic stats: pip install psutil")
            note.setStyleSheet("color: #888; font-size: 11px;")
            traf_layout.addWidget(note)

        outer.addWidget(traffic_frame)
        outer.addStretch()

    def _make_traffic_label(self, text: str, color: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {color}; font-size: 13px; font-family: monospace; font-weight: bold;"
        )
        return lbl

    # ── State management ───────────────────────────────────────────────

    def set_state(self, state: str) -> None:
        """Update all visual indicators. state: connecting/connected/disconnected/error"""
        self.orb.set_state(state)

        if state == "connected":
            self.lbl_status.setText("Connected")
            self.lbl_status.setStyleSheet("color: #4CAF50; font-size: 20px; font-weight: bold;")
            self.btn_connect.setText("■  Disconnect")
            self.btn_connect.setObjectName("btn_disconnect")
            self.btn_connect.setStyleSheet(
                "QPushButton { background-color: #F44336; color: white; font-size: 16px;"
                " font-weight: bold; border-radius: 8px; padding: 12px; border: none; }"
                "QPushButton:hover { background-color: #EF5350; }"
            )
            self.btn_connect.setEnabled(True)
            self._connect_time = time.time()
            self._uptime_timer.start(1000)
            self._start_traffic_monitor()

        elif state == "connecting":
            self.lbl_status.setText("Connecting…")
            self.lbl_status.setStyleSheet("color: #FFA726; font-size: 20px; font-weight: bold;")
            self.btn_connect.setText("■  Abort")
            self.btn_connect.setEnabled(True)
            self.lbl_uptime.setText("—")

        elif state == "disconnected":
            self.lbl_status.setText("Disconnected")
            self.lbl_status.setStyleSheet("color: #9E9EC0; font-size: 20px; font-weight: bold;")
            self.btn_connect.setText("▶  Connect")
            self.btn_connect.setObjectName("btn_connect")
            self.btn_connect.setStyleSheet(
                "QPushButton { background-color: #4CAF50; color: white; font-size: 16px;"
                " font-weight: bold; border-radius: 8px; padding: 12px; border: none; }"
                "QPushButton:hover { background-color: #66BB6A; }"
            )
            self.btn_connect.setEnabled(True)
            self._uptime_timer.stop()
            self._traffic_timer.stop()
            self._connect_time = None
            self.lbl_uptime.setText("—")
            self.stat_h2.set_value("—")
            self.lbl_speed_down.setText("↓  0.00 KB/s")
            self.lbl_speed_up.setText("↑  0.00 KB/s")
            self.lbl_traffic_iface.setText("")

        elif state == "error":
            self.lbl_status.setText("Error")
            self.lbl_status.setStyleSheet("color: #F44336; font-size: 20px; font-weight: bold;")
            self.btn_connect.setEnabled(True)
            self._uptime_timer.stop()
            self._traffic_timer.stop()

    def set_config_info(self, config: dict) -> None:
        """Populate display labels from the current config."""
        ip = config.get("google_ip", "—")
        self.lbl_ip.setText(f"Google IP: {ip}")

        sid = config.get("script_id") or (
            config.get("script_ids", [""])[0] if config.get("script_ids") else ""
        )
        if sid and len(sid) > 14:
            sid_display = f"{sid[:12]}…"
        else:
            sid_display = sid or "—"
        self.lbl_script.setText(f"Script ID: {sid_display}")

    def update_exec_count(self, count: int) -> None:
        self.stat_exec.set_value(str(count))

    def update_h2_status(self, status: str) -> None:
        if status == "active":
            self.stat_h2.set_value("✓ Active")
        else:
            self.stat_h2.set_value("↻ Reconnecting")

    def update_proxy_mode_badge(self, sys_proxy: bool, tun: bool) -> None:
        if sys_proxy and tun:
            self.stat_mode.set_value("System + TUN")
        elif sys_proxy:
            self.stat_mode.set_value("System Proxy")
        elif tun:
            self.stat_mode.set_value("TUN Mode")
        else:
            self.stat_mode.set_value("None")

    # ── Uptime ─────────────────────────────────────────────────────────

    def _update_uptime(self) -> None:
        if self._connect_time is None:
            return
        elapsed = int(time.time() - self._connect_time)
        h = elapsed // 3600
        m = (elapsed % 3600) // 60
        s = elapsed % 60
        self.lbl_uptime.setText(f"Uptime: {h:02d}:{m:02d}:{s:02d}")

    # ── Traffic monitoring ─────────────────────────────────────────────

    def _get_physical_io(self):
        """
        Return aggregated bytes for all PHYSICAL (non-loopback) network
        interfaces combined.

        Returns a simple object with .bytes_sent and .bytes_recv attributes.
        On failure, falls back to the global psutil counters.
        """
        import psutil

        class _IO:
            __slots__ = ("bytes_sent", "bytes_recv", "iface_name")
            def __init__(self, sent: int, recv: int, name: str = "") -> None:
                self.bytes_sent = sent
                self.bytes_recv = recv
                self.iface_name = name

        try:
            per_nic = psutil.net_io_counters(pernic=True)
            total_sent = 0
            total_recv = 0
            included = []
            for name, ctr in per_nic.items():
                if name.lower().strip() in _LOOPBACK_NAMES:
                    continue
                total_sent += ctr.bytes_sent
                total_recv += ctr.bytes_recv
                included.append(name)

            if total_sent + total_recv > 0:
                label = ", ".join(included[:3])
                if len(included) > 3:
                    label += f" +{len(included) - 3} more"
                return _IO(total_sent, total_recv, label)
        except Exception:
            pass

        # Fallback: global aggregate
        ctr = psutil.net_io_counters()
        return _IO(ctr.bytes_sent, ctr.bytes_recv, "all interfaces")

    def _start_traffic_monitor(self) -> None:
        """Snapshot baseline counters and start the 1-second update timer."""
        if not self._psutil_available:
            self.lbl_traffic_iface.setText("psutil not installed")
            return
        try:
            io = self._get_physical_io()
            self._baseline_sent = io.bytes_sent
            self._baseline_recv = io.bytes_recv
            self._prev_sent     = io.bytes_sent
            self._prev_recv     = io.bytes_recv
            self._total_sent    = 0
            self._total_recv    = 0
            if hasattr(io, "iface_name") and io.iface_name:
                self.lbl_traffic_iface.setText(f"via {io.iface_name}")
            self._traffic_timer.start(1000)
        except Exception as exc:
            self.lbl_traffic_iface.setText(f"monitor error: {exc}")

    def _update_traffic(self) -> None:
        """Called every second to update speed and total labels."""
        if not self._psutil_available:
            return
        try:
            io = self._get_physical_io()

            # Speed deltas (bytes per second)
            sent_delta = max(0, io.bytes_sent - self._prev_sent)
            recv_delta = max(0, io.bytes_recv - self._prev_recv)
            self._prev_sent = io.bytes_sent
            self._prev_recv = io.bytes_recv

            # Session totals (from baseline)
            self._total_sent = max(0, io.bytes_sent - self._baseline_sent)
            self._total_recv = max(0, io.bytes_recv - self._baseline_recv)

            # Update speed labels
            self.lbl_speed_down.setText(f"↓  {_fmt_bytes(recv_delta, per_sec=True)}")
            self.lbl_speed_up.setText(  f"↑  {_fmt_bytes(sent_delta, per_sec=True)}")

            # Update total labels
            self.lbl_total_down.setText(f"Total ↓  {_fmt_bytes(self._total_recv)}")
            self.lbl_total_up.setText(  f"Total ↑  {_fmt_bytes(self._total_sent)}")

        except Exception:
            pass
