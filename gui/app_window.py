"""
app_window.py — QMainWindow root window (v3).

Fixes:
  - cert_installer imported directly from engine path via spec_from_file_location
    (avoids 'No module named core.cert_installer' when GUI core/ shadows engine core/).
  - Disconnect now shows 'Disconnected' not 'Error'.
  - Orange cert banner is hidden once cert is trusted, and status updates correctly.
  - Dashboard wizard-chosen proxy mode is reflected in toggles on startup.
  - Status bar shows app version + proxy status (no Windows/Python version).
  - Log lines are guaranteed one entry per line in both tabs.
  - TUN mode fully wired.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QIcon
from PyQt6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QMessageBox,
    QPushButton, QStatusBar, QTabWidget, QVBoxLayout, QHBoxLayout, QWidget,
    QSystemTrayIcon,
)

from core.config_manager import ConfigManager
from core.proxy_thread import ProxyThread
from core.app_logger import log_app, drain_app_log_queue, install_crash_logger
from gui.advanced_tab import AdvancedTab
from gui.config_tab import ConfigTab
from gui.dashboard_tab import DashboardTab
from gui.guide_tab import GuideTab
from gui.log_tab import LogTab
from gui.proxy_mode_tab import ProxyModeTab
from gui.system_log_tab import SystemLogTab
from gui.styles import DARK_THEME, LIGHT_THEME
from gui.tray_icon import TrayIcon

_GUI_ROOT = Path(__file__).resolve().parent.parent
_ASSETS   = _GUI_ROOT / "assets"
APP_VERSION = "1.0.0"


# ─── Helper: load engine cert modules robustly ────────────────────────────────

def _load_engine_cert_modules():
    """
    Load cert_installer and mitm from the engine/src directory without
    triggering collisions with the GUI's own 'core' package.
    Uses spec_from_file_location so the imports bypass sys.modules namespace.
    """
    import importlib.util

    engine_src = _GUI_ROOT / "engine" / "src"

    # Load cert_installer directly by file path
    ci_path = engine_src / "core" / "cert_installer.py"
    if not ci_path.exists():
        raise FileNotFoundError(f"cert_installer.py not found at {ci_path}")

    spec_ci = importlib.util.spec_from_file_location(
        "_engine_cert_installer", str(ci_path)
    )
    ci = importlib.util.module_from_spec(spec_ci)  # type: ignore
    spec_ci.loader.exec_module(ci)  # type: ignore

    # Load mitm directly by file path
    mitm_path = engine_src / "proxy" / "mitm.py"
    if not mitm_path.exists():
        raise FileNotFoundError(f"mitm.py not found at {mitm_path}")

    # mitm.py imports from its own package; add engine/src to path temporarily
    engine_src_str = str(engine_src)
    inserted = engine_src_str not in sys.path
    if inserted:
        sys.path.insert(0, engine_src_str)
    try:
        spec_mitm = importlib.util.spec_from_file_location(
            "_engine_mitm", str(mitm_path)
        )
        mitm = importlib.util.module_from_spec(spec_mitm)  # type: ignore
        spec_mitm.loader.exec_module(mitm)  # type: ignore
    finally:
        if inserted:
            sys.path.remove(engine_src_str)

    return ci, mitm


# ─── Background worker for cert operations ────────────────────────────────────

class _CertWorker(QThread):
    """Generic background worker for cert install/uninstall/check."""
    done = pyqtSignal(bool, str)  # (ok, message)

    def __init__(self, op: str, parent=None):
        super().__init__(parent)
        self._op = op  # "check", "install", "uninstall"

    def run(self) -> None:
        try:
            ci, mitm = _load_engine_cert_modules()
            ca_cert_file = mitm.CA_CERT_FILE

            if self._op == "check":
                # If cert file doesn't exist, it's not installed
                if not Path(ca_cert_file).exists():
                    self.done.emit(False, "cert file not found")
                    return
                trusted = ci.is_ca_trusted(ca_cert_file)
                self.done.emit(trusted, "")

            elif self._op == "install":
                # Generate cert if missing
                if not Path(ca_cert_file).exists():
                    try:
                        mitm.MITMCertManager()
                    except Exception as e:
                        log_app("WARNING", "Certificate", f"Cert generation: {e}")
                # Now install
                if not Path(ca_cert_file).exists():
                    self.done.emit(False, f"ca.crt not found at {ca_cert_file}")
                    return
                ok = ci.install_ca(ca_cert_file)
                self.done.emit(ok, "" if ok else "install_ca returned False")

            elif self._op == "uninstall":
                if not Path(ca_cert_file).exists():
                    self.done.emit(False, f"ca.crt not found at {ca_cert_file}")
                    return
                ok = ci.uninstall_ca(ca_cert_file)
                self.done.emit(ok, "" if ok else "uninstall_ca returned False")

        except Exception as exc:
            self.done.emit(False, str(exc))


# ─── Cert banner ──────────────────────────────────────────────────────────────

class CertBanner(QWidget):
    """Non-blocking banner shown when the MITM CA is not trusted."""

    install_clicked = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setVisible(False)
        self.setStyleSheet(
            "QWidget { background: rgba(255,167,38,0.15); border: 1px solid #E65100; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)

        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)

        self.lbl = QLabel(
            "⚠  MITM CA certificate is not trusted — HTTPS inspection disabled. "
            "Install it to proxy HTTPS sites."
        )
        self.lbl.setStyleSheet("color: #FFA726; font-size: 12px;")
        row.addWidget(self.lbl, stretch=1)

        self.btn_install = QPushButton("Install Certificate")
        self.btn_install.setFixedWidth(160)
        self.btn_install.setStyleSheet(
            "QPushButton { background: #E65100; color: white; border: none; "
            "border-radius: 4px; padding: 4px 8px; }"
            "QPushButton:hover { background: #F57C00; }"
        )
        self.btn_install.clicked.connect(self.install_clicked.emit)
        row.addWidget(self.btn_install)

        btn_dismiss = QPushButton("✕")
        btn_dismiss.setFixedSize(24, 24)
        btn_dismiss.setStyleSheet("QPushButton { border: none; color: #FFA726; font-size:14px; }")
        btn_dismiss.clicked.connect(lambda: self.setVisible(False))
        row.addWidget(btn_dismiss)

        layout.addWidget(row_widget)


# ─── AppWindow ────────────────────────────────────────────────────────────────

class AppWindow(QMainWindow):
    """The root application window."""

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app
        self._proxy_thread: Optional[ProxyThread] = None
        self._current_theme = "dark"
        self._drain_timer = QTimer(self)
        self._app_log_timer = QTimer(self)
        self._cert_workers: list[_CertWorker] = []

        self._cm = ConfigManager()
        self._config: dict = self._cm.load() if self._cm.config_exists() else self._cm.get_defaults()

        install_crash_logger()
        log_app("INFO", "App", "Application starting…")

        self._setup_window()
        self._setup_menu()
        self._setup_tabs()
        self._setup_status_bar()
        self._setup_tray()
        self._setup_timers()

        self._apply_theme(self._current_theme)
        self._refresh_all_from_config()
        # Async cert check — won't block startup
        self._check_cert_status_async()

    # ── Window setup ───────────────────────────────────────────────────

    def _setup_window(self) -> None:
        self.setWindowTitle("MasterHttpRelayVPN")
        self.setMinimumSize(960, 680)
        self.resize(1100, 820)

        icon_path = _ASSETS / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        else:
            # Generate a fallback icon at runtime so the taskbar/title always has one
            from gui.tray_icon import _make_app_icon
            self.setWindowIcon(_make_app_icon(64))

    def _setup_menu(self) -> None:
        mb = self.menuBar()

        # File menu
        file_menu = mb.addMenu("File")
        act_import = QAction("Import Config…", self)
        act_import.triggered.connect(self._import_config)
        file_menu.addAction(act_import)

        act_export = QAction("Export Config…", self)
        act_export.triggered.connect(self._export_config)
        file_menu.addAction(act_export)

        file_menu.addSeparator()

        act_restart_proxy = QAction("↺  Restart Proxy", self)
        act_restart_proxy.setShortcut("Ctrl+R")
        act_restart_proxy.triggered.connect(self._restart_proxy)
        file_menu.addAction(act_restart_proxy)

        act_restart = QAction("Restart Application", self)
        act_restart.triggered.connect(self._restart_app)
        file_menu.addAction(act_restart)

        file_menu.addSeparator()

        act_exit = QAction("Exit", self)
        act_exit.triggered.connect(self._quit_app)
        file_menu.addAction(act_exit)

        # View menu
        view_menu = mb.addMenu("View")
        self.act_dark = QAction("Dark Theme", self)
        self.act_dark.setCheckable(True)
        self.act_dark.setChecked(True)
        self.act_dark.triggered.connect(lambda: self._apply_theme("dark"))
        view_menu.addAction(self.act_dark)

        self.act_light = QAction("Light Theme", self)
        self.act_light.setCheckable(True)
        self.act_light.triggered.connect(lambda: self._apply_theme("light"))
        view_menu.addAction(self.act_light)

        # Proxy menu
        proxy_menu = mb.addMenu("Proxy")
        self.act_connect = QAction("▶  Connect", self)
        self.act_connect.triggered.connect(self._toggle_connection)
        proxy_menu.addAction(self.act_connect)

        # Certificate menu
        cert_menu = mb.addMenu("Certificate")

        act_install = QAction("Install CA Certificate", self)
        act_install.triggered.connect(self._install_cert)
        cert_menu.addAction(act_install)

        act_uninstall = QAction("Uninstall CA Certificate", self)
        act_uninstall.triggered.connect(self._uninstall_cert)
        cert_menu.addAction(act_uninstall)

        act_view_cert = QAction("View Certificate…", self)
        act_view_cert.triggered.connect(self._view_cert)
        cert_menu.addAction(act_view_cert)

        cert_menu.addSeparator()

        self.act_cert_status = QAction("CA Status: Checking…", self)
        self.act_cert_status.setEnabled(False)
        cert_menu.addAction(self.act_cert_status)

        # Help menu
        help_menu = mb.addMenu("Help")
        act_guide = QAction("Setup Guide", self)
        act_guide.triggered.connect(lambda: self.tabs.setCurrentWidget(self.guide_tab))
        help_menu.addAction(act_guide)

        act_about = QAction("About", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _setup_tabs(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.cert_banner = CertBanner()
        self.cert_banner.install_clicked.connect(self._install_cert)
        layout.addWidget(self.cert_banner)

        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)

        self.dashboard_tab  = DashboardTab()
        self.config_tab     = ConfigTab(self._cm)
        self.proxy_mode_tab = ProxyModeTab(self._config)
        self.log_tab        = LogTab()
        self.system_log_tab = SystemLogTab()
        self.guide_tab      = GuideTab()
        self.advanced_tab   = AdvancedTab(self._cm)

        self.tabs.addTab(self.dashboard_tab,  "🏠  Dashboard")
        self.tabs.addTab(self.config_tab,     "⚙  Configuration")
        self.tabs.addTab(self.proxy_mode_tab, "🌐  Proxy Mode")
        self.tabs.addTab(self.log_tab,        "📋  Live Logs")
        self.tabs.addTab(self.system_log_tab, "🔧  System Log")
        self.tabs.addTab(self.guide_tab,      "📖  Guide")
        self.tabs.addTab(self.advanced_tab,   "🔬  Advanced")

        layout.addWidget(self.tabs)
        self.setCentralWidget(central)

        # ── Wire signals ───────────────────────────────────────────────
        self.dashboard_tab.btn_connect.clicked.connect(self._toggle_connection)
        self.dashboard_tab.tog_sys_proxy.set_callback(self._on_sys_proxy_toggle)
        self.dashboard_tab.tog_tun.set_callback(self._on_tun_toggle)
        self.dashboard_tab.tog_lan.set_callback(self._on_lan_toggle)
        self.dashboard_tab.tog_adblock.set_callback(self._on_adblock_toggle)

        self.config_tab.config_saved.connect(self._on_config_saved)
        self.advanced_tab.advanced_saved.connect(self._on_advanced_saved)

        # ProxyModeTab → Dashboard sync
        self.proxy_mode_tab.system_proxy_changed.connect(self._on_proxy_mode_sys_changed)
        self.proxy_mode_tab.tun_mode_changed.connect(self._on_proxy_mode_tun_changed)

    def _setup_status_bar(self) -> None:
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # Version label (left)
        ver_lbl = QLabel(f"v{APP_VERSION}")
        ver_lbl.setStyleSheet("color: #555; margin: 0 8px;")
        self.status_bar.addWidget(ver_lbl)

        # Proxy status (right permanent)
        self.lbl_status_proxy = QLabel("Proxy: Stopped")
        self.lbl_status_proxy.setStyleSheet("color: #9E9EC0; margin: 0 8px;")
        self.status_bar.addPermanentWidget(self.lbl_status_proxy)

        # Active proxy mode (right permanent)
        self.lbl_proxy_mode = QLabel("Mode: —")
        self.lbl_proxy_mode.setStyleSheet("color: #888; margin: 0 8px;")
        self.status_bar.addPermanentWidget(self.lbl_proxy_mode)

    def _setup_tray(self) -> None:
        self.tray = TrayIcon(self)
        if self.tray.is_available():
            self.tray.show()
            self.tray.action_open.connect(self._restore_window)
            self.tray.action_connect.connect(self._start_proxy)
            self.tray.action_disconnect.connect(self._stop_proxy)
            self.tray.action_restart.connect(self._restart_proxy)
            self.tray.action_exit.connect(self._quit_app)
            self.tray.action_sys_proxy_toggle.connect(self._on_tray_sys_proxy)
            self.tray.action_tun_toggle.connect(self._on_tray_tun)
            self.tray.action_install_cert.connect(self._install_cert)
            self.tray.action_restart_app.connect(self._restart_app)
            self.tray.action_view_system_log.connect(
                lambda: (self._restore_window(), self.tabs.setCurrentWidget(self.system_log_tab))
            )

    def _setup_timers(self) -> None:
        self._drain_timer.timeout.connect(self._drain_log_queue)
        self._app_log_timer.timeout.connect(self._drain_app_log)
        self._app_log_timer.start(250)
        # Sync traffic speed to tray tooltip every 2 seconds
        self._tray_speed_timer = QTimer(self)
        self._tray_speed_timer.timeout.connect(self._sync_speed_to_tray)
        self._tray_speed_timer.start(2000)

    # ── Config refresh ─────────────────────────────────────────────────

    def _refresh_all_from_config(self) -> None:
        self.config_tab.load_config(self._config)
        self.advanced_tab.load_config(self._config)
        self.proxy_mode_tab.set_config(self._config)
        self.dashboard_tab.set_config_info(self._config)
        self.dashboard_tab.tog_adblock.set_checked(
            bool(self._config.get("adblock_lists"))
        )

        # Sync dashboard toggles from config.
        # Support both the new "proxy_mode" key and wizard's "_wizard_*" keys.
        if "proxy_mode" in self._config:
            proxy_mode = self._config.get("proxy_mode", "system")
            sys_on = proxy_mode in ("system", "both")
            tun_on = proxy_mode in ("tun", "both")
        else:
            sys_on = self._config.get("_wizard_sys_proxy", True)
            tun_on = self._config.get("_wizard_tun", False)
        self.dashboard_tab.tog_sys_proxy.set_checked(sys_on)
        self.dashboard_tab.tog_tun.set_checked(tun_on)
        self.proxy_mode_tab.sync_sys_proxy_state(sys_on)
        self.proxy_mode_tab.sync_tun_state(tun_on)
        self._update_mode_badge()

    def _on_advanced_saved(self, adv: dict) -> None:
        """Persist advanced tab settings into config and save to disk."""
        self._config.update(adv)
        try:
            self._cm.save(self._config)
            self.status_bar.showMessage("Advanced settings saved.", 3000)
            log_app("INFO", "Config", "Advanced settings saved to disk")
        except Exception as exc:
            log_app("ERROR", "Config", f"Failed to save advanced settings: {exc}")
        if self._proxy_thread and self._proxy_thread.isRunning():
            self.status_bar.showMessage(
                "Advanced settings saved. Restart the proxy to apply changes.", 5000
            )

    def _on_config_saved(self, cfg: dict) -> None:
        # Merge advanced tab settings into the saved config before updating self._config
        adv = self.advanced_tab.get_config()
        cfg.update(adv)
        self._config = cfg
        self._refresh_all_from_config()
        self.advanced_tab.load_config(cfg)
        self.status_bar.showMessage("Configuration saved.", 3000)
        log_app("INFO", "Config", "Configuration saved to disk")
        if self._proxy_thread and self._proxy_thread.isRunning():
            self.status_bar.showMessage(
                "Config saved. Restart the proxy to apply changes.", 5000
            )
            log_app("WARNING", "Config", "Proxy running — restart needed to apply new config")

    # ── Connection control ─────────────────────────────────────────────

    def _toggle_connection(self) -> None:
        if self._proxy_thread and self._proxy_thread.isRunning():
            self._stop_proxy()
        else:
            self._start_proxy()

    def _start_proxy(self) -> None:
        if self._proxy_thread and self._proxy_thread.isRunning():
            return

        errors = self._cm.validate(self._config)
        if errors:
            log_app("WARNING", "Connection", f"Cannot connect — config errors: {'; '.join(errors)}")
            QMessageBox.warning(
                self,
                "Configuration Required",
                "Cannot connect — please fix the following configuration issues:\n\n"
                + "\n".join(f"  • {e}" for e in errors)
                + "\n\nGo to the ⚙ Configuration tab to set up your Apps Script deployment.",
            )
            return

        adv = self.advanced_tab.get_config()
        merged_config = {**self._config, **adv}

        log_app("INFO", "Connection", "Starting proxy engine…")

        self._proxy_thread = ProxyThread(merged_config)
        self._proxy_thread.log_entry.connect(self.log_tab.append_entry)
        self._proxy_thread.status_changed.connect(self._on_status_changed)
        self._proxy_thread.exec_count.connect(self.dashboard_tab.update_exec_count)
        self._proxy_thread.h2_status.connect(self.dashboard_tab.update_h2_status)
        self._proxy_thread.cert_warn.connect(self._on_cert_warn)

        self._proxy_thread.start()
        self._drain_timer.start(200)

        self.dashboard_tab.set_state("connecting")
        self.tray.set_state("connecting")
        self.act_connect.setText("■  Disconnect")
        self.lbl_status_proxy.setText("Proxy: Connecting…")
        self.lbl_status_proxy.setStyleSheet("color: #FFA726; margin: 0 8px;")

    def _stop_proxy(self) -> None:
        if not self._proxy_thread:
            return
        log_app("INFO", "Connection", "Stopping proxy engine…")
        self._proxy_thread.stop()
        self._drain_timer.stop()
        self._proxy_thread = None
        self.dashboard_tab.set_state("disconnected")
        self.tray.set_state("disconnected")
        self.act_connect.setText("▶  Connect")
        self.lbl_status_proxy.setText("Proxy: Stopped")
        self.lbl_status_proxy.setStyleSheet("color: #9E9EC0; margin: 0 8px;")
        self.proxy_mode_tab.set_proxy_running(False)
        log_app("INFO", "Connection", "Proxy engine stopped")

    def _on_status_changed(self, status: str) -> None:
        self.dashboard_tab.set_state(status)
        self.tray.set_state(status)

        if status == "connected":
            self.lbl_status_proxy.setText("Proxy: Running")
            self.lbl_status_proxy.setStyleSheet("color: #4CAF50; margin: 0 8px;")
            self.act_connect.setText("■  Disconnect")
            self.proxy_mode_tab.set_proxy_running(True)
            self.tray.show_message("Connected", "Proxy is active.")
            log_app("INFO", "Connection", "Proxy engine connected and running")
            # After connecting, check cert status (async, non-blocking)
            self._check_cert_status_async()

        elif status == "disconnected":
            self.lbl_status_proxy.setText("Proxy: Stopped")
            self.lbl_status_proxy.setStyleSheet("color: #9E9EC0; margin: 0 8px;")
            self.act_connect.setText("▶  Connect")
            self.dashboard_tab.set_state("disconnected")
            self.proxy_mode_tab.set_proxy_running(False)
            self._drain_timer.stop()
            log_app("INFO", "Connection", "Proxy engine disconnected")

        elif status == "error":
            # Show as "stopped" not "error" to avoid confusing the user
            self.lbl_status_proxy.setText("Proxy: Stopped")
            self.lbl_status_proxy.setStyleSheet("color: #9E9EC0; margin: 0 8px;")
            self.act_connect.setText("▶  Connect")
            self.dashboard_tab.set_state("disconnected")
            self.proxy_mode_tab.set_proxy_running(False)
            self._drain_timer.stop()
            self._proxy_thread = None
            log_app("ERROR", "Connection", "Proxy engine reported an error — see Live Logs")

        self._update_mode_badge()

    def _on_cert_warn(self) -> None:
        """Engine reported cert not trusted — show banner."""
        self.cert_banner.setVisible(True)
        self.tray.set_cert_trusted(False)
        self.act_cert_status.setText("CA Status: Not Trusted ✗")
        log_app("WARNING", "Certificate", "Engine reported MITM CA is not trusted")

    def _drain_log_queue(self) -> None:
        if self._proxy_thread:
            self._proxy_thread.drain_log_queue()

    def _drain_app_log(self) -> None:
        entries = drain_app_log_queue()
        for entry in entries:
            self.system_log_tab.append_entry(entry)

    # ── Toggle callbacks ───────────────────────────────────────────────

    def _on_sys_proxy_toggle(self, enabled: bool) -> None:
        from core.system_proxy import set_system_proxy, clear_system_proxy
        http_port = self._config.get("http_port", 8085)
        if enabled:
            ok = set_system_proxy("127.0.0.1", http_port)
            log_app("INFO", "Proxy", f"System proxy {'enabled' if ok else 'failed'} on port {http_port}")
        else:
            ok = clear_system_proxy()
            log_app("INFO", "Proxy", f"System proxy {'cleared' if ok else 'clear failed'}")
        self.proxy_mode_tab.sync_sys_proxy_state(enabled)
        self.tray.set_sys_proxy(enabled)
        self._update_mode_badge()
        self._save_proxy_mode_to_config()

    def _on_tun_toggle(self, enabled: bool) -> None:
        """Dashboard quick toggle → TUN mode."""
        if enabled:
            # Ensure ProxyModeTab has the latest merged config so the
            # TunAdapter can resolve the correct relay/exclusion IPs.
            adv = self.advanced_tab.get_config()
            merged = {**self._config, **adv}
            self.proxy_mode_tab.set_config(merged)
            self.proxy_mode_tab.enable_tun_from_outside()
        else:
            self.proxy_mode_tab.disable_tun_from_outside()
        log_app("INFO", "TUN", f"TUN mode {'ON' if enabled else 'OFF'} from dashboard")
        self.tray.set_tun_mode(enabled)
        self._update_mode_badge()
        self._save_proxy_mode_to_config()

    def _on_lan_toggle(self, enabled: bool) -> None:
        self._config["lan_sharing"] = enabled
        self._config["listen_host"] = "0.0.0.0" if enabled else "127.0.0.1"
        log_app("INFO", "Config", f"LAN sharing {'enabled' if enabled else 'disabled'}")
        try:
            self._cm.save(self._config)
        except Exception:
            pass

    def _on_adblock_toggle(self, enabled: bool) -> None:
        if not enabled:
            self._config["adblock_lists"] = []
        else:
            defaults = self._cm.get_defaults()
            self._config["adblock_lists"] = defaults.get("adblock_lists", [])
        log_app("INFO", "Config", f"Ad-blocker {'enabled' if enabled else 'disabled'}")
        try:
            self._cm.save(self._config)
        except Exception:
            pass

    def _save_proxy_mode_to_config(self) -> None:
        """Persist current toggle state as proxy_mode in config."""
        sys_on = self.dashboard_tab.tog_sys_proxy.is_checked()
        tun_on = self.dashboard_tab.tog_tun.is_checked()
        if sys_on and tun_on:
            mode = "both"
        elif tun_on:
            mode = "tun"
        elif sys_on:
            mode = "system"
        else:
            mode = "none"
        self._config["proxy_mode"] = mode
        try:
            self._cm.save(self._config)
        except Exception:
            pass

    # ── ProxyModeTab → Dashboard sync ─────────────────────────────────

    def _on_proxy_mode_sys_changed(self, enabled: bool) -> None:
        self.dashboard_tab.tog_sys_proxy.set_checked(enabled)
        self.tray.set_sys_proxy(enabled)
        self._update_mode_badge()
        self._save_proxy_mode_to_config()
        log_app("INFO", "Proxy", f"System proxy {'enabled' if enabled else 'disabled'} via Proxy Mode tab")

    def _on_proxy_mode_tun_changed(self, enabled: bool) -> None:
        self.dashboard_tab.tog_tun.set_checked(enabled)
        self.tray.set_tun_mode(enabled)
        self._update_mode_badge()
        self._save_proxy_mode_to_config()
        log_app("INFO", "TUN", f"TUN mode {'enabled' if enabled else 'disabled'} via Proxy Mode tab")

    # ── Tray callbacks ─────────────────────────────────────────────────

    def _on_tray_sys_proxy(self, enabled: bool) -> None:
        self.dashboard_tab.tog_sys_proxy.set_checked(enabled)
        self._on_sys_proxy_toggle(enabled)

    def _on_tray_tun(self, enabled: bool) -> None:
        if enabled and not (self._proxy_thread and self._proxy_thread.isRunning()):
            # Remind user they need the proxy engine running first
            self.tray.show_message(
                "Proxy Engine Not Running",
                "Please Connect the proxy engine before enabling TUN mode.",
                QSystemTrayIcon.MessageIcon.Warning,
            )
            # Revert the tray checkbox
            self.tray.set_tun_mode(False)
            return
        self.dashboard_tab.tog_tun.set_checked(enabled)
        self._on_tun_toggle(enabled)

    def _update_mode_badge(self) -> None:
        sys_p = self.dashboard_tab.tog_sys_proxy.is_checked()
        tun   = self.dashboard_tab.tog_tun.is_checked()
        self.dashboard_tab.update_proxy_mode_badge(sys_p, tun)
        # Update status bar mode label
        if sys_p and tun:
            mode_str = "System + TUN"
        elif sys_p:
            mode_str = "System Proxy"
        elif tun:
            mode_str = "TUN Mode"
        else:
            mode_str = "No Mode"
        self.lbl_proxy_mode.setText(f"Mode: {mode_str}")

    # ── Certificate management (all async) ────────────────────────────

    def _check_cert_status_async(self) -> None:
        """Non-blocking background cert check."""
        log_app("DEBUG", "Certificate", "Checking CA certificate status…")
        worker = _CertWorker("check", self)
        worker.done.connect(self._on_cert_check_done)
        worker.finished.connect(lambda: self._cert_workers.remove(worker) if worker in self._cert_workers else None)
        self._cert_workers.append(worker)
        worker.start()

    def _on_cert_check_done(self, trusted: bool, err: str) -> None:
        self.cert_banner.setVisible(not trusted)
        self.tray.set_cert_trusted(trusted)
        status_text = "Trusted ✓" if trusted else "Not Installed ✗"
        self.act_cert_status.setText(f"CA Status: {status_text}")
        log_app(
            "INFO" if trusted else "WARNING",
            "Certificate",
            f"CA cert status: {status_text}" + (f" — {err}" if err else ""),
        )

    def _install_cert(self) -> None:
        """Install CA cert (async)."""
        log_app("INFO", "Certificate", "Installing CA certificate…")
        self.cert_banner.btn_install.setEnabled(False)
        worker = _CertWorker("install", self)
        worker.done.connect(self._on_install_cert_done)
        worker.finished.connect(lambda: self._cert_workers.remove(worker) if worker in self._cert_workers else None)
        self._cert_workers.append(worker)
        worker.start()

    def _on_install_cert_done(self, ok: bool, err: str) -> None:
        self.cert_banner.btn_install.setEnabled(True)
        if ok:
            self.cert_banner.setVisible(False)
            self.tray.set_cert_trusted(True)
            self.act_cert_status.setText("CA Status: Trusted ✓")
            log_app("INFO", "Certificate", "CA certificate installed successfully")
            QMessageBox.information(
                self, "Certificate Installed",
                "CA certificate installed successfully.\n"
                "Restart your browser for changes to take effect."
            )
        else:
            log_app("ERROR", "Certificate", f"CA certificate install failed: {err}")
            QMessageBox.warning(
                self, "Install Failed",
                f"Could not install CA certificate.\n{err}\n\n"
                "Try running the application as administrator/root."
            )

    def _uninstall_cert(self) -> None:
        """Uninstall CA cert (async)."""
        log_app("INFO", "Certificate", "Uninstalling CA certificate…")
        worker = _CertWorker("uninstall", self)
        worker.done.connect(self._on_uninstall_cert_done)
        worker.finished.connect(lambda: self._cert_workers.remove(worker) if worker in self._cert_workers else None)
        self._cert_workers.append(worker)
        worker.start()

    def _on_uninstall_cert_done(self, ok: bool, err: str) -> None:
        if ok:
            self.cert_banner.setVisible(True)
            self.tray.set_cert_trusted(False)
            self.act_cert_status.setText("CA Status: Not Installed ✗")
            log_app("INFO", "Certificate", "CA certificate uninstalled")
            QMessageBox.information(self, "Certificate Removed", "CA certificate uninstalled.")
        else:
            log_app("ERROR", "Certificate", f"CA certificate uninstall failed: {err}")
            QMessageBox.warning(self, "Uninstall Failed", f"Could not uninstall: {err}")

    def _view_cert(self) -> None:
        import subprocess, platform
        cert_file = _GUI_ROOT / "engine" / "ca" / "ca.crt"
        if not cert_file.exists():
            cert_file = _GUI_ROOT / "ca" / "ca.crt"
        if not cert_file.exists():
            QMessageBox.information(
                self, "No Certificate",
                "ca.crt not found. Connect at least once to generate it."
            )
            return
        log_app("INFO", "Certificate", f"Opening certificate file: {cert_file}")
        if platform.system() == "Windows":
            os.startfile(str(cert_file))
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(cert_file)])
        else:
            subprocess.Popen(["xdg-open", str(cert_file)])

    # ── Import / Export ────────────────────────────────────────────────

    def _import_config(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Config", "", "JSON Files (*.json);;All Files (*)"
        )
        if path:
            try:
                cfg = self._cm.import_from(path)
                self._config = cfg
                self._refresh_all_from_config()
                self.status_bar.showMessage(f"Imported config from {Path(path).name}", 4000)
                log_app("INFO", "Config", f"Config imported from {Path(path).name}")
            except Exception as exc:
                log_app("ERROR", "Config", f"Config import failed: {exc}")
                QMessageBox.critical(self, "Import Failed", str(exc))

    def _export_config(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Config", "config_export.json", "JSON Files (*.json)"
        )
        if path:
            try:
                self._cm.export_to(path, self._config)
                self.status_bar.showMessage(f"Exported to {Path(path).name}", 3000)
                log_app("INFO", "Config", f"Config exported to {Path(path).name}")
            except Exception as exc:
                log_app("ERROR", "Config", f"Config export failed: {exc}")
                QMessageBox.critical(self, "Export Failed", str(exc))

    # ── Theme ──────────────────────────────────────────────────────────

    def _apply_theme(self, theme: str) -> None:
        self._current_theme = theme
        self._app.setStyleSheet(DARK_THEME if theme == "dark" else LIGHT_THEME)
        self.act_dark.setChecked(theme == "dark")
        self.act_light.setChecked(theme == "light")
        log_app("DEBUG", "App", f"Theme changed to {theme}")

    # ── Restart ────────────────────────────────────────────────────────

    def _restart_proxy(self) -> None:
        """Restart (stop then start) the proxy engine — called from tray."""
        if self._proxy_thread:
            log_app("INFO", "Connection", "Restarting proxy engine…")
            self._stop_proxy()
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(800, self._start_proxy)

    def _restart_app(self) -> None:
        reply = QMessageBox.question(
            self, "Restart Application",
            "This will stop the proxy and restart the application.\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        log_app("INFO", "App", "Restarting application…")
        self._stop_proxy()
        self.proxy_mode_tab.cleanup()
        self.tray.hide()
        QTimer.singleShot(300, self._do_restart)

    def _do_restart(self) -> None:
        import subprocess
        python = sys.executable
        args = sys.argv[:]
        try:
            subprocess.Popen([python] + args)
        except Exception as exc:
            log_app("ERROR", "App", f"Restart failed: {exc}")
            QMessageBox.critical(self, "Restart Failed", str(exc))
            return
        QApplication.quit()

    # ── Window lifecycle ───────────────────────────────────────────────

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.tray.is_available():
            event.ignore()
            self.hide()
            self.tray.show_message(
                "Running in Background",
                "MasterHttpRelayVPN is still running. Right-click the tray icon to exit."
            )
        else:
            self._quit_app()

    def _restore_window(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _sync_speed_to_tray(self) -> None:
        """Forward current traffic speed to the tray tooltip."""
        try:
            down = self.dashboard_tab.lbl_speed_down.text().lstrip("↓").strip()
            up   = self.dashboard_tab.lbl_speed_up.text().lstrip("↑").strip()
            self.tray.update_speed(down, up)
        except Exception:
            pass

    def _quit_app(self) -> None:
        log_app("INFO", "App", "Application exiting")
        self._stop_proxy()
        self.proxy_mode_tab.cleanup()
        for w in self._cert_workers:
            if w.isRunning():
                w.quit()
                w.wait(2000)
        self.tray.hide()
        QApplication.quit()

    def _show_about(self) -> None:
        QMessageBox.about(
            self, "About MasterHttpRelayVPN",
            f"<h2>MasterHttpRelayVPN GUI</h2>"
            f"<p><b>Version:</b> {APP_VERSION}</p>"
            "<p>A PyQt6 desktop client for the MasterHttpRelayVPN proxy engine.</p>"
            "<p>Routes traffic through Google Apps Script using domain fronting "
            "to bypass DPI censorship.</p>"
            "<p><b>Engine:</b> "
            "<a href='https://github.com/masterking32/MasterHttpRelayVPN'>"
            "github.com/masterking32/MasterHttpRelayVPN</a></p>"
        )
