"""
tray_icon.py — System tray icon with right-click context menu.

Menu layout (top → bottom):
  Open MasterHttpRelayVPN
  ─────────────────────────
  ▶  Connect  /  ■  Disconnect
  ↺  Restart Proxy
  ─────────────────────────
  System Proxy: OFF/ON  [checkable]
  TUN Mode: OFF/ON      [checkable]
  ─────────────────────────
  Certificate ▶
    CA Status: …
    Install CA Certificate…
  ─────────────────────────
  📋  View System Log
  ─────────────────────────
  🔄  Restart Application
  ✕   Exit
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import pyqtSignal, QObject
from PyQt6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor, QBrush, QFont
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

_ASSETS = Path(__file__).resolve().parent.parent / "assets"


def _make_circle_icon(color: str, size: int = 32) -> QIcon:
    """Generate a simple circle icon with the given hex colour."""
    px = QPixmap(size, size)
    px.fill(QColor(0, 0, 0, 0))
    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor(color).darker(130))
    painter.setBrush(QBrush(QColor(color)))
    margin = 3
    painter.drawEllipse(margin, margin, size - margin * 2, size - margin * 2)
    painter.end()
    return QIcon(px)


def _make_app_icon(size: int = 64) -> QIcon:
    """Generate a shield-style icon as fallback when icon.png is absent."""
    px = QPixmap(size, size)
    px.fill(QColor(0, 0, 0, 0))
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor("#1A1A2E").darker(110))
    p.setBrush(QBrush(QColor("#1A1A2E")))
    m = 2
    p.drawEllipse(m, m, size - 2*m, size - 2*m)
    p.setPen(QColor("#4CAF50"))
    font = QFont("Arial", int(size * 0.42), QFont.Weight.Bold)
    p.setFont(font)
    p.drawText(px.rect(), 0x84, "M")  # AlignCenter
    p.end()
    return QIcon(px)


def _load_icon(filename: str) -> Optional[QIcon]:
    """Load icon from assets/ directory, or return None if missing."""
    path = _ASSETS / filename
    if path.exists():
        return QIcon(str(path))
    return None


class TrayIcon(QObject):
    """
    QSystemTrayIcon wrapper with a rich context menu.

    Signals
    -------
    action_open              : open / restore main window
    action_connect           : request Connect
    action_disconnect        : request Disconnect
    action_restart           : restart proxy engine only
    action_restart_app       : restart the full application
    action_exit              : quit the application
    action_sys_proxy_toggle  : toggle System Proxy (bool)
    action_tun_toggle        : toggle TUN Mode (bool)
    action_install_cert      : install CA certificate
    action_view_system_log   : switch to System Log tab
    """

    action_open             = pyqtSignal()
    action_connect          = pyqtSignal()
    action_disconnect       = pyqtSignal()
    action_restart          = pyqtSignal()
    action_restart_app      = pyqtSignal()
    action_exit             = pyqtSignal()
    action_sys_proxy_toggle = pyqtSignal(bool)
    action_tun_toggle       = pyqtSignal(bool)
    action_install_cert     = pyqtSignal()
    action_view_system_log  = pyqtSignal()

    _ICON_CONNECTED    = "#4CAF50"
    _ICON_DISCONNECTED = "#666688"
    _ICON_CONNECTING   = "#FFA726"
    _ICON_ERROR        = "#F44336"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._icon_connected    = _load_icon("icon_connected.png")    or _make_circle_icon(self._ICON_CONNECTED)
        self._icon_disconnected = _load_icon("icon_disconnected.png") or _make_circle_icon(self._ICON_DISCONNECTED)
        self._icon_connecting   = _make_circle_icon(self._ICON_CONNECTING)
        self._icon_error        = _make_circle_icon(self._ICON_ERROR)
        self._app_icon          = _load_icon("icon.png") or _make_app_icon()

        self._tray = QSystemTrayIcon(self._icon_disconnected)
        self._tray.setToolTip("MasterHttpRelayVPN — Disconnected")

        self._connected    = False
        self._sys_proxy    = False
        self._tun_mode     = False
        self._cert_trusted = None  # None = checking

        # Current speed (updated externally for tooltip)
        self._speed_down: str = ""
        self._speed_up:   str = ""

        self._build_menu()
        self._tray.activated.connect(self._on_activated)

    def show(self) -> None:
        self._tray.show()

    def hide(self) -> None:
        self._tray.hide()

    def is_available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    # ── Public setters ─────────────────────────────────────────────────

    def set_state(self, state: str) -> None:
        state_map = {
            "connected":    (self._icon_connected,    "MasterHttpRelayVPN — Connected"),
            "connecting":   (self._icon_connecting,   "MasterHttpRelayVPN — Connecting…"),
            "disconnected": (self._icon_disconnected, "MasterHttpRelayVPN — Disconnected"),
            "error":        (self._icon_error,        "MasterHttpRelayVPN — Error"),
        }
        icon, tip = state_map.get(state, (self._icon_disconnected, "MasterHttpRelayVPN"))
        self._tray.setIcon(icon)
        self._tray.setToolTip(tip)
        self._connected = (state == "connected")
        self._refresh_menu_labels()

    def set_sys_proxy(self, enabled: bool) -> None:
        self._sys_proxy = enabled
        self._refresh_menu_labels()

    def set_tun_mode(self, enabled: bool) -> None:
        self._tun_mode = enabled
        self._refresh_menu_labels()

    def set_cert_trusted(self, trusted: bool) -> None:
        self._cert_trusted = trusted
        status = "Trusted ✓" if trusted else "Not Installed ✗"
        self._act_cert_status.setText(f"CA Status: {status}")
        self._act_install_cert.setVisible(not trusted)

    def update_speed(self, down: str, up: str) -> None:
        """Update speed strings shown in the tooltip when connected."""
        self._speed_down = down
        self._speed_up = up
        if self._connected:
            tip = f"MasterHttpRelayVPN — Connected\n↓ {down}  ↑ {up}"
            self._tray.setToolTip(tip)

    def show_message(self, title: str, msg: str,
                     icon=QSystemTrayIcon.MessageIcon.Information) -> None:
        self._tray.showMessage(title, msg, icon, 3000)

    # ── Build context menu ─────────────────────────────────────────────

    def _build_menu(self) -> None:
        menu = QMenu()

        # ── Open window ────────────────────────────────────────────────
        self._act_open = QAction("Open MasterHttpRelayVPN")
        self._act_open.setFont(self._bold_font())
        self._act_open.triggered.connect(self.action_open.emit)
        menu.addAction(self._act_open)

        menu.addSeparator()

        # ── Connection control ─────────────────────────────────────────
        self._act_connect = QAction("▶  Connect")
        self._act_connect.triggered.connect(self._on_connect_toggle)
        menu.addAction(self._act_connect)

        self._act_restart = QAction("↺  Restart Proxy Engine")
        self._act_restart.triggered.connect(self.action_restart.emit)
        self._act_restart.setEnabled(False)   # only enabled when connected
        menu.addAction(self._act_restart)

        menu.addSeparator()

        # ── Mode toggles ───────────────────────────────────────────────
        self._act_sys_proxy = QAction("System Proxy: OFF")
        self._act_sys_proxy.setCheckable(True)
        self._act_sys_proxy.triggered.connect(self._on_sys_proxy_toggle)
        menu.addAction(self._act_sys_proxy)

        self._act_tun = QAction("TUN Mode: OFF")
        self._act_tun.setCheckable(True)
        self._act_tun.triggered.connect(self._on_tun_toggle)
        menu.addAction(self._act_tun)

        # Shows "Adapter: MasterVPN (198.18.0.1)" when TUN is active
        self._act_tun_info = QAction("   Adapter: —")
        self._act_tun_info.setEnabled(False)
        menu.addAction(self._act_tun_info)

        menu.addSeparator()

        # ── Certificate sub-menu ───────────────────────────────────────
        cert_menu = menu.addMenu("🔒  Certificate")
        self._act_cert_status = QAction("CA Status: Checking…")
        self._act_cert_status.setEnabled(False)
        cert_menu.addAction(self._act_cert_status)

        self._act_install_cert = QAction("Install CA Certificate…")
        self._act_install_cert.triggered.connect(self.action_install_cert.emit)
        cert_menu.addAction(self._act_install_cert)

        menu.addSeparator()

        # ── Utility ────────────────────────────────────────────────────
        act_log = QAction("📋  View System Log")
        act_log.triggered.connect(self.action_view_system_log.emit)
        menu.addAction(act_log)

        menu.addSeparator()

        # ── App-level actions ──────────────────────────────────────────
        act_restart_app = QAction("🔄  Restart Application")
        act_restart_app.triggered.connect(self.action_restart_app.emit)
        menu.addAction(act_restart_app)

        act_exit = QAction("✕  Exit")
        act_exit.triggered.connect(self.action_exit.emit)
        menu.addAction(act_exit)

        self._tray.setContextMenu(menu)

    @staticmethod
    def _bold_font() -> QFont:
        f = QFont()
        f.setBold(True)
        return f

    def _refresh_menu_labels(self) -> None:
        if self._connected:
            self._act_connect.setText("■  Disconnect")
            self._act_restart.setEnabled(True)
        else:
            self._act_connect.setText("▶  Connect")
            self._act_restart.setEnabled(False)

        on_off_sys = "ON ✓" if self._sys_proxy else "OFF"
        self._act_sys_proxy.setText(f"System Proxy: {on_off_sys}")
        self._act_sys_proxy.setChecked(self._sys_proxy)

        on_off_tun = "ON ✓" if self._tun_mode else "OFF"
        self._act_tun.setText(f"TUN Mode: {on_off_tun}")
        self._act_tun.setChecked(self._tun_mode)
        if self._tun_mode:
            self._act_tun_info.setText("   Adapter: MasterVPN (198.18.0.1)")
            self._act_tun_info.setVisible(True)
        else:
            self._act_tun_info.setVisible(False)

    # ── Event handlers ─────────────────────────────────────────────────

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.DoubleClick,
                      QSystemTrayIcon.ActivationReason.Trigger):
            self.action_open.emit()

    def _on_connect_toggle(self) -> None:
        if self._connected:
            self.action_disconnect.emit()
        else:
            self.action_connect.emit()

    def _on_sys_proxy_toggle(self, checked: bool) -> None:
        self.action_sys_proxy_toggle.emit(checked)

    def _on_tun_toggle(self, checked: bool) -> None:
        self.action_tun_toggle.emit(checked)
