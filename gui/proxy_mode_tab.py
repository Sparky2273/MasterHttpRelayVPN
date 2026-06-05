"""
proxy_mode_tab.py — System Proxy and TUN Mode controls tab.

KEY FIX — UI FREEZE + TUN NOT WORKING:
  The previous version called TunAdapter.start() / .stop() directly on
  the Qt GUI thread.  tun2socks startup on Windows can block for 15–25 s
  (waiting for the WinTUN kernel driver to create the adapter) which
  freezes the entire application window and causes the OS to mark it
  "Not Responding".

  Worse: while the GUI thread was frozen, queued button clicks were
  delivered once it unfroze — so clicking "Disable TUN Mode" during
  startup triggered another start() call instead of a stop(), leaving
  the UI permanently stuck in "Active" even though nothing worked.

  Fix: all TUN start / stop work is dispatched to a dedicated
  TunWorkerThread (a QThread subclass).  The UI immediately reflects the
  "pending" state, progress messages stream in via a Qt signal, and the
  toggle button is locked until the operation completes.  If the
  operation fails, the detailed tun2socks output is shown in a dialog.

  Additional improvements:
  • Orphaned tun2socks.exe from prior sessions are killed before start.
  • tun2socks log level changed from "warning" to "info" so startup
    errors are always captured.
  • Output reader thread starts BEFORE the adapter-wait loop so crash
    output is captured even on instant exits.
  • is_running property now detects silent process crashes and updates
    the UI badge accordingly.
  • Periodic health-check timer updates the badge if tun2socks dies
    unexpectedly after successful start.
"""
from __future__ import annotations

import platform as _plat
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from core.system_proxy import clear_system_proxy, get_system_proxy, set_system_proxy
from core.tun_adapter import TunAdapter, is_elevation_available, tun2socks_available
from core.app_logger import log_app

_GUI_ROOT = Path(__file__).resolve().parent.parent

_IS_WINDOWS = _plat.system() == "Windows"


# ── Status badge ──────────────────────────────────────────────────────────────

class StatusBadge(QLabel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(120)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_inactive()

    def set_active(self) -> None:
        self.setText("● Active")
        self.setStyleSheet(
            "background:#1B5E20; color:#A5D6A7; border-radius:4px;"
            " padding:4px 8px; font-weight:bold;"
        )

    def set_inactive(self) -> None:
        self.setText("○ Inactive")
        self.setStyleSheet(
            "background:#37374A; color:#888; border-radius:4px; padding:4px 8px;"
        )

    def set_pending(self, msg: str = "Working…") -> None:
        self.setText(f"⟳ {msg}")
        self.setStyleSheet(
            "background:#1A237E; color:#90CAF9; border-radius:4px;"
            " padding:4px 8px; font-weight:bold;"
        )

    def set_error(self, msg: str = "Error") -> None:
        self.setText(f"✗ {msg}")
        self.setStyleSheet(
            "background:#B71C1C; color:#FFCDD2; border-radius:4px;"
            " padding:4px 8px; font-weight:bold;"
        )


# ── TUN worker thread ─────────────────────────────────────────────────────────

class TunWorkerThread(QThread):
    """
    Background QThread that performs TUN start or stop off the GUI thread.

    Signals
    -------
    progress  str   — human-readable status update (stream to UI label)
    finished  bool, str — (success, error_message)
    """

    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)   # (ok, error_detail)

    def __init__(self, adapter: TunAdapter, action: str, parent=None) -> None:
        super().__init__(parent)
        self._adapter = adapter
        self._action  = action   # "start" or "stop"

    def run(self) -> None:
        try:
            if self._action == "start":
                self._adapter.start(on_progress=self.progress.emit)
                self.finished.emit(True, "")
            else:
                self._adapter.stop()
                self.finished.emit(True, "")
        except Exception as exc:
            # Capture tun2socks output for the error dialog
            detail = str(exc)
            captured = self._adapter.get_captured_output()
            if captured and captured not in detail:
                detail = f"{detail}\n\n--- tun2socks output ---\n{captured}"
            self.finished.emit(False, detail)


# ── Test-connection worker ────────────────────────────────────────────────────

class TestConnectionThread(QThread):
    result = pyqtSignal(bool, str)

    def __init__(self, proxy_host: str = "127.0.0.1", proxy_port: int = 8085,
                 direct: bool = False, parent=None):
        super().__init__(parent)
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        self.direct = direct

    def run(self) -> None:
        import urllib.request, time
        try:
            if self.direct:
                opener = urllib.request.build_opener()
            else:
                proxy = urllib.request.ProxyHandler({
                    "http":  f"http://{self.proxy_host}:{self.proxy_port}",
                    "https": f"http://{self.proxy_host}:{self.proxy_port}",
                })
                opener = urllib.request.build_opener(proxy)
            start   = time.time()
            resp    = opener.open("http://example.com", timeout=10)
            latency = int((time.time() - start) * 1000)
            status  = resp.status
            resp.close()
            self.result.emit(True, f"HTTP {status} — {latency} ms")
        except Exception as exc:
            self.result.emit(False, str(exc)[:80])


# ── External-IP worker ────────────────────────────────────────────────────────

class FetchIPThread(QThread):
    result = pyqtSignal(str)

    def __init__(self, proxy_host: str = "127.0.0.1", proxy_port: int = 8085,
                 direct: bool = False, parent=None):
        super().__init__(parent)
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        self.direct = direct

    def run(self) -> None:
        import urllib.request
        try:
            if self.direct:
                opener = urllib.request.build_opener()
            else:
                proxy = urllib.request.ProxyHandler({
                    "http":  f"http://{self.proxy_host}:{self.proxy_port}",
                    "https": f"http://{self.proxy_host}:{self.proxy_port}",
                })
                opener = urllib.request.build_opener(proxy)
            ip = opener.open("http://api.ipify.org", timeout=10).read().decode().strip()
            self.result.emit(ip)
        except Exception:
            self.result.emit("—")


# ── Routing-diagnostics worker ────────────────────────────────────────────────

class RouteDiagnosticsThread(QThread):
    result = pyqtSignal(str)

    def run(self) -> None:
        import subprocess, socket as _sock
        if not _IS_WINDOWS:
            self.result.emit("Route diagnostics only available on Windows.")
            return
        try:
            r = subprocess.run(
                ["route", "print"],
                capture_output=True, timeout=10, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            output = r.stdout or r.stderr or "<no output>"

            # ── TUN interface index diagnosis ──────────────────────────────────
            from core.tun_adapter import (
                TUN_IFACE_WIN, TUN_GW_WIN, TUN_IP_WIN,
                _get_tun_if_index_windows,
            )
            tun_idx = _get_tun_if_index_windows(TUN_IFACE_WIN)

            diag_lines = ["\n=== TUN Routing Diagnosis ==="]
            if tun_idx:
                diag_lines.append(f"TUN adapter '{TUN_IFACE_WIN}' interface index: {tun_idx}")
            else:
                diag_lines.append(f"TUN adapter '{TUN_IFACE_WIN}' NOT FOUND in adapter list")

            # Check if default TUN route is on the right interface
            for line in output.splitlines():
                stripped = line.strip()
                if stripped.startswith("0.0.0.0") and TUN_GW_WIN in stripped:
                    parts = stripped.split()
                    iface = parts[3] if len(parts) >= 4 else "?"
                    if iface == TUN_IP_WIN:
                        diag_lines.append(
                            f"✓ TUN default route correctly bound to TUN interface ({iface})"
                        )
                    else:
                        diag_lines.append(
                            f"✗ TUN default route is on WRONG interface: {iface} "
                            f"(expected {TUN_IP_WIN}) — traffic is NOT going through TUN!"
                        )

            # SOCKS5 check
            try:
                with _sock.create_connection(("127.0.0.1", 1080), timeout=1.5):
                    diag_lines.append("✓ SOCKS5 port 1080 is listening")
            except OSError:
                diag_lines.append("✗ SOCKS5 port 1080 is NOT listening — start the proxy engine first")

            diag_lines.append("=== End TUN Diagnosis ===")
            self.result.emit(output + "\n".join(diag_lines))
        except Exception as exc:
            self.result.emit(f"Error: {exc}")


# ── Main widget ───────────────────────────────────────────────────────────────

class ProxyModeTab(QWidget):
    """
    The Proxy Mode tab with full bidirectional sync.

    TUN operations run in a background TunWorkerThread — the GUI thread
    is never blocked.
    """

    system_proxy_changed = pyqtSignal(bool)
    tun_mode_changed     = pyqtSignal(bool)

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config       = config
        self._tun_adapter: Optional[TunAdapter] = None
        self._tun_worker:  Optional[TunWorkerThread] = None
        self._test_threads: list = []
        self._syncing       = False
        self._proxy_running = False

        # Pending desired state while worker is busy
        self._tun_pending_enable: Optional[bool] = None

        self._setup_ui()
        self._refresh_status()

        # Health-check timer: detect unexpected tun2socks crashes
        self._health_timer = QTimer(self)
        self._health_timer.timeout.connect(self._check_tun_health)
        self._health_timer.start(3000)   # every 3 seconds

    def set_config(self, config: dict) -> None:
        self._config = config

    def set_proxy_running(self, running: bool) -> None:
        self._proxy_running = running
        self._update_button_states()
        if hasattr(self, "_not_running_warn"):
            self._not_running_warn.setVisible(not running)

    # ── Sync API (from AppWindow) ─────────────────────────────────────

    def sync_sys_proxy_state(self, enabled: bool) -> None:
        self._syncing = True
        try:
            if enabled:
                self.sys_badge.set_active()
                self.sys_btn_toggle.setText("Disable System Proxy")
            else:
                self.sys_badge.set_inactive()
                self.sys_btn_toggle.setText("Enable System Proxy")
        finally:
            self._syncing = False

    def sync_tun_state(self, enabled: bool) -> None:
        """Called by AppWindow to reflect config state; does NOT start/stop TUN."""
        self._syncing = True
        try:
            if enabled:
                self.tun_badge.set_active()
                self.tun_btn_toggle.setText("Disable TUN Mode")
            else:
                self.tun_badge.set_inactive()
                self.tun_btn_toggle.setText("Enable TUN Mode")
        finally:
            self._syncing = False

    def is_sys_proxy_active(self) -> bool:
        return self.sys_badge.text() == "● Active"

    def is_tun_active(self) -> bool:
        return self._tun_adapter is not None and self._tun_adapter.is_running

    # ── Called from Dashboard toggle / AppWindow ──────────────────────

    def enable_tun_from_outside(self) -> None:
        if self._tun_worker and self._tun_worker.isRunning():
            self._tun_pending_enable = True
            return
        if self._tun_adapter and self._tun_adapter.is_running:
            return
        self._start_tun(from_user=False)

    def disable_tun_from_outside(self) -> None:
        if self._tun_worker and self._tun_worker.isRunning():
            self._tun_pending_enable = False
            return
        self._stop_tun()

    # ── Health check ──────────────────────────────────────────────────

    def _check_tun_health(self) -> None:
        """Detect if tun2socks crashed after a successful start."""
        if self._tun_worker and self._tun_worker.isRunning():
            return  # Worker still running, don't interfere
        if self._tun_adapter and not self._tun_adapter.is_running and \
                self.tun_badge.text() == "● Active":
            # Process died unexpectedly
            log_app("WARNING", "TUN", "tun2socks process exited unexpectedly — TUN mode is now off")
            self.tun_badge.set_error("Crashed")
            self.tun_btn_toggle.setText("Enable TUN Mode")
            self._tun_adapter = None
            if not self._syncing:
                self.tun_mode_changed.emit(False)
            self._update_button_states()

    # ── UI setup ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)

        inner = QWidget()
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        outer.addWidget(self._build_system_proxy_group())
        outer.addWidget(self._build_tun_group())
        outer.addStretch()

        scroll.setWidget(inner)
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(scroll)

    def _build_system_proxy_group(self) -> QGroupBox:
        grp    = QGroupBox("Mode 1: System Proxy")
        layout = QVBoxLayout(grp)

        http_port   = self._config.get("http_port", 8085)
        socks5_port = self._config.get("socks5_port", 1080)

        desc = QLabel(
            f"Sets the OS-level HTTP/HTTPS proxy to <b>127.0.0.1:{http_port}</b>.<br>"
            "Works with Chrome, Edge and most desktop applications automatically.<br>"
            "<b>Important:</b> Connect the proxy engine first, then enable System Proxy."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #AAA; margin-bottom: 8px;")
        layout.addWidget(desc)

        self._not_running_warn = QLabel(
            "⚠  The proxy engine is not running. "
            "Click <b>Connect</b> on the Dashboard first, then enable System Proxy."
        )
        self._not_running_warn.setWordWrap(True)
        self._not_running_warn.setStyleSheet(
            "color:#FF9800; background:rgba(255,152,0,0.1); border:1px solid #E65100;"
            " border-radius:4px; padding:6px 10px;"
        )
        self._not_running_warn.setVisible(True)
        layout.addWidget(self._not_running_warn)

        row1 = QHBoxLayout()
        self.sys_badge = StatusBadge()
        row1.addWidget(self.sys_badge)

        self.sys_btn_toggle = QPushButton("Enable System Proxy")
        self.sys_btn_toggle.setFixedWidth(210)
        self.sys_btn_toggle.clicked.connect(self._toggle_system_proxy)
        row1.addWidget(self.sys_btn_toggle)
        row1.addStretch()
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.sys_btn_test = QPushButton("Test Connection")
        self.sys_btn_test.setEnabled(False)
        self.sys_btn_test.clicked.connect(lambda: self._test_connection(direct=False))
        self.sys_lbl_test = QLabel("")
        self.sys_lbl_test.setStyleSheet("font-size:12px; margin-left:8px;")
        row2.addWidget(self.sys_btn_test)
        row2.addWidget(self.sys_lbl_test)

        self.sys_btn_ip = QPushButton("Fetch External IP")
        self.sys_btn_ip.setEnabled(False)
        self.sys_btn_ip.clicked.connect(lambda: self._fetch_ip(direct=False))
        self.sys_lbl_ip = QLabel("")
        self.sys_lbl_ip.setStyleSheet("font-size:12px; margin-left:8px; color:#4CAF50;")
        row2.addWidget(self.sys_btn_ip)
        row2.addWidget(self.sys_lbl_ip)
        row2.addStretch()
        layout.addLayout(row2)

        chrome_note = QLabel(
            "✅ <b>Chrome / Edge / Opera:</b> These browsers use the OS system proxy "
            "automatically. No extra configuration needed."
        )
        chrome_note.setWordWrap(True)
        chrome_note.setStyleSheet(
            "color:#B0BEC5; font-size:12px; margin-top:6px;"
            " background:rgba(76,175,80,0.07); border:1px solid #2E7D32;"
            " border-radius:4px; padding:6px 10px;"
        )
        layout.addWidget(chrome_note)

        firefox_note = QLabel(
            f"🦊 <b>Firefox — Two steps required:</b><br>"
            f"<b>Step 1 – Proxy settings:</b><br>"
            f"&nbsp;&nbsp;Settings → General → Network Settings → Manual proxy configuration<br>"
            f"&nbsp;&nbsp;HTTP Proxy: <b>127.0.0.1</b> &nbsp; Port: <b>{http_port}</b> &nbsp;"
            f"(check 'Also use this proxy for HTTPS')<br>"
            f"&nbsp;&nbsp;Or select <i>Use system proxy settings</i> and restart Firefox.<br><br>"
            f"<b>Step 2 – Install CA Certificate (required for HTTPS):</b><br>"
            f"&nbsp;&nbsp;Firefox uses its own certificate store — the system CA does <b>not</b> apply.<br>"
            f"&nbsp;&nbsp;Settings → Privacy &amp; Security → Certificates → <b>View Certificates</b><br>"
            f"&nbsp;&nbsp;→ Authorities tab → <b>Import…</b> → select <code>engine/ca/ca.crt</code><br>"
            f"&nbsp;&nbsp;→ Check <i>Trust this CA to identify websites</i> → OK<br>"
            f"&nbsp;&nbsp;Restart Firefox after importing."
        )
        firefox_note.setWordWrap(True)
        firefox_note.setOpenExternalLinks(True)
        firefox_note.setStyleSheet(
            "color:#CCC; font-size:12px; margin-top:6px;"
            " background:rgba(255,167,38,0.07); border:1px solid #554400;"
            " border-radius:4px; padding:8px 12px;"
        )
        layout.addWidget(firefox_note)

        return grp

    def _build_tun_group(self) -> QGroupBox:
        grp    = QGroupBox("Mode 2: TUN Mode (Virtual Network Adapter)")
        layout = QVBoxLayout(grp)

        desc = QLabel(
            "Creates a <b>MasterVPN</b> WireGuard Tunnel network adapter that captures "
            "<b>ALL application traffic</b> — including games, CLI tools, and apps that "
            "ignore system proxy settings.<br>"
            "Uses tun2socks to forward all connections through the local SOCKS5 proxy.<br>"
            "The <b>MasterVPN</b> adapter is visible in Windows Network Connections "
            "(Control Panel → Network Adapters) when active, just like xray_tun in v2rayN.<br>"
            "<b>Split tunnelling</b> is applied automatically: the relay server IP from your "
            "config bypasses TUN and uses your real gateway to avoid routing loops."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #AAA; margin-bottom: 6px;")
        layout.addWidget(desc)

        warn = QLabel("⚠  TUN mode requires administrator / root privileges and the proxy engine to be running.")
        warn.setWordWrap(True)
        warn.setStyleSheet(
            "background:rgba(255,167,38,0.15); color:#FFA726; border:1px solid #E65100;"
            " border-radius:4px; padding:6px 10px; font-weight:bold;"
        )
        layout.addWidget(warn)

        if not tun2socks_available():
            missing = QLabel(
                "⚠  tun2socks binary not found in assets/bin/.<br>"
                "Download from <a href='https://github.com/xjasonlyu/tun2socks/releases'>"
                "github.com/xjasonlyu/tun2socks/releases</a> and rename it to "
                "<b>tun2socks.exe</b> (Windows), then place it in <code>assets/bin/</code>.<br>"
                "Also place <b>wintun.dll</b> (AMD64, from wintun.net) in the same folder.<br>"
                "<b>Use tun2socks-windows-amd64.exe</b> (not the -v3 variant) for best compatibility."
            )
            missing.setOpenExternalLinks(True)
            missing.setWordWrap(True)
            missing.setStyleSheet("color:#F44336; margin-top:4px;")
            layout.addWidget(missing)

        # Badge + toggle button row
        row1 = QHBoxLayout()
        self.tun_badge = StatusBadge()
        row1.addWidget(self.tun_badge)

        self.tun_btn_toggle = QPushButton("Enable TUN Mode")
        self.tun_btn_toggle.setFixedWidth(210)
        self.tun_btn_toggle.clicked.connect(self._toggle_tun_mode)
        self.tun_btn_toggle.setEnabled(tun2socks_available())
        row1.addWidget(self.tun_btn_toggle)

        # Progress label next to button
        self.tun_lbl_progress = QLabel("")
        self.tun_lbl_progress.setStyleSheet("font-size:11px; margin-left:10px; color:#90CAF9;")
        row1.addWidget(self.tun_lbl_progress)

        row1.addStretch()
        layout.addLayout(row1)

        # Test / IP row
        row2 = QHBoxLayout()
        self.tun_btn_test = QPushButton("Test Connection")
        self.tun_btn_test.setEnabled(False)
        self.tun_btn_test.setToolTip(
            "Makes a direct (no-proxy) HTTP request. "
            "When TUN is active and routing is correct, this goes through "
            "MasterVPN adapter → SOCKS5 → relay → internet."
        )
        self.tun_btn_test.clicked.connect(lambda: self._test_connection(direct=True))
        self.tun_lbl_test = QLabel("")
        self.tun_lbl_test.setStyleSheet("font-size:12px; margin-left:8px;")
        row2.addWidget(self.tun_btn_test)
        row2.addWidget(self.tun_lbl_test)

        self.tun_btn_ip = QPushButton("Fetch External IP")
        self.tun_btn_ip.setEnabled(False)
        self.tun_btn_ip.setToolTip(
            "Fetches your external IP via a direct (no-proxy) connection. "
            "If TUN routing is correct, the IP shown should be the relay's exit IP."
        )
        self.tun_btn_ip.clicked.connect(lambda: self._fetch_ip(direct=True))
        self.tun_lbl_ip = QLabel("")
        self.tun_lbl_ip.setStyleSheet("font-size:12px; margin-left:8px; color:#4CAF50;")
        row2.addWidget(self.tun_btn_ip)
        row2.addWidget(self.tun_lbl_ip)
        row2.addStretch()
        layout.addLayout(row2)

        # Diagnostics button (Windows only)
        if _IS_WINDOWS:
            row3 = QHBoxLayout()
            self.tun_btn_diag = QPushButton("🔍  TUN Diagnostics")
            self.tun_btn_diag.setToolTip(
                "Captures the Windows routing table and logs it to System Log."
            )
            self.tun_btn_diag.clicked.connect(self._run_tun_diagnostics)
            self.tun_lbl_diag = QLabel("")
            self.tun_lbl_diag.setStyleSheet("font-size:11px; margin-left:8px; color:#9E9EC0;")
            row3.addWidget(self.tun_btn_diag)
            row3.addWidget(self.tun_lbl_diag)
            row3.addStretch()
            layout.addLayout(row3)

        # Setup checklist
        checklist = QLabel(
            "<b>Setup checklist for TUN mode:</b><br>"
            "&nbsp; ✓ &nbsp;Place <code>tun2socks.exe</code> and <code>wintun.dll</code> "
            "in <code>assets/bin/</code><br>"
            "&nbsp; &nbsp; &nbsp; Use <b>tun2socks-windows-amd64.exe</b> (not -v3) for best compatibility<br>"
            "&nbsp; ✓ &nbsp;Run the application as <b>Administrator</b><br>"
            "&nbsp; ✓ &nbsp;<b>Connect</b> the proxy engine first (Dashboard → Connect)<br>"
            "&nbsp; ✓ &nbsp;Set <code>google_ip</code> in Configuration so the exclusion "
            "route can be determined<br>"
            "&nbsp; ✓ &nbsp;Add <code>assets/bin/</code> to Windows Defender exclusions<br>"
            "&nbsp; ✓ &nbsp;Then enable TUN Mode here or from the Dashboard toggle"
        )
        checklist.setWordWrap(True)
        checklist.setStyleSheet(
            "color:#B0BEC5; font-size:12px; margin-top:8px;"
            " background:rgba(66,165,245,0.07); border:1px solid #1565C0;"
            " border-radius:4px; padding:8px 12px;"
        )
        layout.addWidget(checklist)

        return grp

    # ── Button state management ───────────────────────────────────────

    def _update_button_states(self) -> None:
        """Enable/disable buttons based on current state."""
        worker_busy = self._tun_worker is not None and self._tun_worker.isRunning()
        tun_avail   = tun2socks_available()

        # System proxy buttons
        self.sys_btn_toggle.setEnabled(True)
        self.sys_btn_test.setEnabled(self._proxy_running)
        self.sys_btn_ip.setEnabled(self._proxy_running)

        # TUN toggle — locked while worker is running
        self.tun_btn_toggle.setEnabled(tun_avail and not worker_busy)
        self.tun_btn_test.setEnabled(self._proxy_running and not worker_busy)
        self.tun_btn_ip.setEnabled(self._proxy_running and not worker_busy)

    # ── Toggle implementations ────────────────────────────────────────

    def _toggle_system_proxy(self) -> None:
        current   = get_system_proxy()
        http_port = self._config.get("http_port", 8085)

        if current:
            ok = clear_system_proxy()
            if ok:
                self.sys_badge.set_inactive()
                self.sys_btn_toggle.setText("Enable System Proxy")
                if not self._syncing:
                    log_app("INFO", "Proxy", "System proxy disabled via Proxy Mode tab")
                    self.system_proxy_changed.emit(False)
            else:
                self.sys_badge.set_error("Clear failed")
                log_app("ERROR", "Proxy", "Failed to clear system proxy")
        else:
            if not self._proxy_running:
                QMessageBox.warning(
                    self, "Proxy Not Running",
                    "The proxy engine is not running.\n\n"
                    "Please click Connect on the Dashboard first, "
                    "then enable System Proxy."
                )
                return
            ok = set_system_proxy("127.0.0.1", http_port)
            if ok:
                self.sys_badge.set_active()
                self.sys_btn_toggle.setText("Disable System Proxy")
                if not self._syncing:
                    log_app("INFO", "Proxy", f"System proxy enabled on port {http_port}")
                    self.system_proxy_changed.emit(True)
            else:
                self.sys_badge.set_error("Set failed")
                log_app("ERROR", "Proxy", "Failed to set system proxy")

    def _toggle_tun_mode(self) -> None:
        """Toggle TUN on/off — dispatches work to background thread."""
        # If worker is busy, ignore the click (button should be disabled, but be safe)
        if self._tun_worker and self._tun_worker.isRunning():
            return

        if self._tun_adapter and self._tun_adapter.is_running:
            # Currently ON → stop
            self._stop_tun()
        else:
            # Currently OFF → start
            self._start_tun(from_user=True)

    def _start_tun(self, from_user: bool = True) -> None:
        """Begin TUN start sequence in background thread."""
        if not tun2socks_available():
            if from_user:
                QMessageBox.critical(
                    self, "Missing Binary",
                    "tun2socks binary not found in assets/bin/.\n\n"
                    "Download tun2socks-windows-amd64.exe from\n"
                    "https://github.com/xjasonlyu/tun2socks/releases\n"
                    "rename it to tun2socks.exe and place it in assets/bin/.\n\n"
                    "Also place wintun.dll (AMD64) from wintun.net in assets/bin/.\n\n"
                    "NOTE: Use tun2socks-windows-amd64.exe (not the -v3 variant)\n"
                    "unless your CPU definitely supports AVX2."
                )
            log_app("ERROR", "TUN", "tun2socks binary not found")
            return

        if not is_elevation_available():
            if from_user:
                QMessageBox.warning(
                    self, "Elevation Required",
                    "TUN mode requires administrator (Windows) or root (Linux) privileges.\n\n"
                    "Please restart the application with elevated privileges and try again.\n\n"
                    "On Windows: right-click the app → Run as administrator."
                )
            log_app("WARNING", "TUN", "TUN mode requires elevation — not started")
            return

        socks5_port = self._config.get("socks5_port", 1080)

        # ── SOCKS5 pre-check: warn if proxy engine is not running ──────────
        if not self._proxy_running and from_user:
            reply = QMessageBox.warning(
                self, "Proxy Engine Not Running",
                f"The proxy engine does not appear to be running "
                f"(SOCKS5 port {socks5_port} is not listening).\n\n"
                "TUN mode routes all traffic through the SOCKS5 proxy — "
                "if the proxy is not running, you will lose internet access "
                "while TUN mode is active.\n\n"
                "Connect the proxy engine first (Dashboard → Connect), "
                "then enable TUN Mode.\n\n"
                "Continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # Create adapter with current config
        self._tun_adapter = TunAdapter(socks5_port=socks5_port, config=self._config)

        # Update UI to "pending" state
        self.tun_badge.set_pending("Starting…")
        self.tun_btn_toggle.setText("Starting…")
        self.tun_lbl_progress.setText("Initialising…")
        self._update_button_states()

        log_app("INFO", "TUN", f"TUN mode starting (SOCKS5 port {socks5_port})…")

        # Launch background worker
        self._tun_worker = TunWorkerThread(self._tun_adapter, "start", self)
        self._tun_worker.progress.connect(self._on_tun_progress)
        self._tun_worker.finished.connect(
            lambda ok, err: self._on_tun_start_done(ok, err, from_user)
        )
        self._tun_worker.start()

    def _stop_tun(self) -> None:
        """Begin TUN stop sequence in background thread."""
        if self._tun_adapter is None:
            # Nothing to stop — just reset UI
            self.tun_badge.set_inactive()
            self.tun_btn_toggle.setText("Enable TUN Mode")
            self.tun_lbl_progress.setText("")
            if not self._syncing:
                self.tun_mode_changed.emit(False)
            return

        # Update UI to "pending" state
        self.tun_badge.set_pending("Stopping…")
        self.tun_btn_toggle.setText("Stopping…")
        self.tun_lbl_progress.setText("Removing routes…")
        self._update_button_states()

        log_app("INFO", "TUN", "TUN mode stopping…")

        # Launch background worker
        self._tun_worker = TunWorkerThread(self._tun_adapter, "stop", self)
        self._tun_worker.progress.connect(self._on_tun_progress)
        self._tun_worker.finished.connect(self._on_tun_stop_done)
        self._tun_worker.start()

    # ── Worker signal handlers ────────────────────────────────────────

    def _on_tun_progress(self, msg: str) -> None:
        """Called from TunWorkerThread.progress signal (already on GUI thread via Qt)."""
        self.tun_lbl_progress.setText(msg)
        log_app("DEBUG", "TUN", msg)

    def _on_tun_start_done(self, ok: bool, error: str, from_user: bool) -> None:
        """Called when TUN start worker finishes."""
        self._tun_worker = None

        if ok:
            self.tun_badge.set_active()
            self.tun_btn_toggle.setText("Disable TUN Mode")
            self.tun_lbl_progress.setText("✓ Active")
            socks5_port = self._config.get('socks5_port', 1080)
            if_index = getattr(self._tun_adapter, '_tun_if_index', '') if self._tun_adapter else ''
            if_info = f" (IF={if_index})" if if_index else ""
            log_app("INFO", "TUN", f"TUN mode enabled (SOCKS5 port {socks5_port}){if_info}")
            log_app("INFO", "TUN", "TUN mode enabled via Proxy Mode tab")
            if not self._syncing:
                self.tun_mode_changed.emit(True)

            # Handle any pending request that came in during startup
            if self._tun_pending_enable is False:
                self._tun_pending_enable = None
                self._stop_tun()
                return
        else:
            self.tun_badge.set_error("Failed")
            self.tun_btn_toggle.setText("Enable TUN Mode")
            self.tun_lbl_progress.setText("✗ Failed — see System Log")
            log_app("ERROR", "TUN", f"TUN start failed: {error.splitlines()[0] if error else 'unknown'}")
            if from_user:
                QMessageBox.critical(
                    self, "TUN Mode Failed",
                    f"Failed to start TUN adapter:\n\n{error}\n\n"
                    "Check the System Log tab for full diagnostics.\n\n"
                    "Quick checklist:\n"
                    "  • tun2socks.exe and wintun.dll (AMD64) in assets/bin/\n"
                    "  • App running as Administrator\n"
                    "  • Antivirus exclusion for assets/bin/ folder\n"
                    "  • Use tun2socks-windows-amd64.exe (not -v3 variant)\n"
                    "  • Reboot if wintun driver was never installed before"
                )
            self._tun_adapter = None

        self._tun_pending_enable = None
        self._update_button_states()

    def _on_tun_stop_done(self, ok: bool, error: str) -> None:
        """Called when TUN stop worker finishes."""
        self._tun_worker = None
        self._tun_adapter = None

        self.tun_badge.set_inactive()
        self.tun_btn_toggle.setText("Enable TUN Mode")
        self.tun_lbl_progress.setText("")

        if not ok:
            log_app("WARNING", "TUN", f"TUN stop had errors: {error.splitlines()[0] if error else 'unknown'}")
        else:
            log_app("INFO", "TUN", "TUN mode disabled")

        if not self._syncing:
            self.tun_mode_changed.emit(False)

        # Handle any pending request that came in during shutdown
        if self._tun_pending_enable is True:
            self._tun_pending_enable = None
            self._start_tun(from_user=False)
            return

        self._tun_pending_enable = None
        self._update_button_states()

    # ── Connection test / IP fetch ────────────────────────────────────

    def _test_connection(self, direct: bool = False) -> None:
        http_port = self._config.get("http_port", 8085)
        lbl = self.tun_lbl_test if direct else self.sys_lbl_test
        lbl.setText("Testing…")
        t = TestConnectionThread("127.0.0.1", http_port, direct=direct, parent=self)
        t.result.connect(lambda ok, msg: self._on_test_result(ok, msg, lbl))
        t.start()
        self._test_threads.append(t)

    def _on_test_result(self, ok: bool, msg: str, lbl: QLabel) -> None:
        if ok:
            lbl.setText(f"✓ {msg}")
            lbl.setStyleSheet("font-size:12px; margin-left:8px; color:#4CAF50;")
        else:
            lbl.setText(f"✗ {msg}")
            lbl.setStyleSheet("font-size:12px; margin-left:8px; color:#F44336;")

    def _fetch_ip(self, direct: bool = False) -> None:
        http_port = self._config.get("http_port", 8085)
        lbl = self.tun_lbl_ip if direct else self.sys_lbl_ip
        lbl.setText("Fetching…")
        t = FetchIPThread("127.0.0.1", http_port, direct=direct, parent=self)
        t.result.connect(lambda ip: lbl.setText(f"External IP: {ip}"))
        t.start()
        self._test_threads.append(t)

    def _run_tun_diagnostics(self) -> None:
        self.tun_lbl_diag.setText("Capturing routes…")
        t = RouteDiagnosticsThread(self)
        t.result.connect(self._on_route_diagnostics)
        t.start()
        self._test_threads.append(t)

    def _on_route_diagnostics(self, output: str) -> None:
        self.tun_lbl_diag.setText("Done — see System Log tab")
        log_app("INFO",  "TUN", "=== Routing Table Diagnostics ===")
        for line in output.splitlines():
            stripped = line.strip()
            if stripped:
                log_app("DEBUG", "TUN", stripped)
        log_app("INFO",  "TUN", "=== End Routing Table ===")

    # ── Refresh ───────────────────────────────────────────────────────

    def _refresh_status(self) -> None:
        current = get_system_proxy()
        if current:
            self.sys_badge.set_active()
            self.sys_btn_toggle.setText("Disable System Proxy")
        else:
            self.sys_badge.set_inactive()
            self.sys_btn_toggle.setText("Enable System Proxy")
        self._update_button_states()

    # ── Cleanup ───────────────────────────────────────────────────────

    def cleanup(self) -> None:
        self._health_timer.stop()

        # Wait for any in-progress worker
        if self._tun_worker and self._tun_worker.isRunning():
            self._tun_worker.quit()
            self._tun_worker.wait(3000)

        if self._tun_adapter and self._tun_adapter.is_running:
            # Run stop synchronously on cleanup (app is already closing)
            import threading as _threading
            stop_done = _threading.Event()
            def _do_stop():
                try:
                    self._tun_adapter.stop()
                finally:
                    stop_done.set()
            t = _threading.Thread(target=_do_stop, daemon=True)
            t.start()
            stop_done.wait(timeout=10)

        for t in self._test_threads:
            if t.isRunning():
                t.quit()
                t.wait(1000)
