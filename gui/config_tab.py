"""
config_tab.py — Form-based editor for every config.json field.

Organised into collapsible sections matching the prompt specification.
Every field has a tooltip, and the bottom toolbar has Save / Reset /
Import / Export buttons.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton,
    QScrollArea, QSizePolicy, QSpinBox, QDoubleSpinBox, QTextEdit,
    QToolButton, QVBoxLayout, QWidget,
)

_GUI_ROOT = Path(__file__).resolve().parent.parent


# ──────────────────────────────────────────────────────────────────────────────
# Helper widgets
# ──────────────────────────────────────────────────────────────────────────────

class PasswordField(QWidget):
    """A QLineEdit in password mode with a show/hide toggle."""

    def __init__(self, placeholder: str = "", parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setPlaceholderText(placeholder)

        self.btn_toggle = QToolButton()
        self.btn_toggle.setText("👁")
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.setFixedWidth(28)
        self.btn_toggle.toggled.connect(self._toggle_visibility)

        layout.addWidget(self.edit)
        layout.addWidget(self.btn_toggle)

    def _toggle_visibility(self, checked: bool) -> None:
        self.edit.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )

    def text(self) -> str:
        return self.edit.text()

    def setText(self, t: str) -> None:
        self.edit.setText(t)


class TagInput(QWidget):
    """
    A tag/chip input widget. Users type a value and press Enter; tags appear as
    items in a list. Click × to remove.
    """

    def __init__(self, placeholder: str = "Type and press Enter…", parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        input_row = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.returnPressed.connect(self._add_tag)
        btn_add = QPushButton("+")
        btn_add.setFixedWidth(30)
        btn_add.clicked.connect(self._add_tag)
        input_row.addWidget(self.edit)
        input_row.addWidget(btn_add)

        self.list_widget = QListWidget()
        self.list_widget.setFixedHeight(80)
        self.list_widget.itemDoubleClicked.connect(self._remove_item)
        self.list_widget.setToolTip("Double-click to remove a tag")

        layout.addLayout(input_row)
        layout.addWidget(self.list_widget)

    def _add_tag(self) -> None:
        text = self.edit.text().strip()
        if text:
            self.list_widget.addItem(text)
            self.edit.clear()

    def _remove_item(self, item: QListWidgetItem) -> None:
        row = self.list_widget.row(item)
        self.list_widget.takeItem(row)

    def get_tags(self) -> list[str]:
        return [self.list_widget.item(i).text() for i in range(self.list_widget.count())]

    def set_tags(self, tags: list[str]) -> None:
        self.list_widget.clear()
        for t in tags:
            self.list_widget.addItem(t)


class CollapsibleSection(QWidget):
    """A section with a clickable header that collapses/expands its content."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header button
        self.header_btn = QPushButton(f"▼  {title}")
        self.header_btn.setCheckable(True)
        self.header_btn.setChecked(True)
        self.header_btn.setStyleSheet(
            "QPushButton { text-align: left; padding: 8px 12px; font-weight: bold;"
            " background: #252535; border: 1px solid #3D3D5C; border-radius: 4px; }"
            "QPushButton:hover { background: #2D2D45; }"
        )
        self.header_btn.clicked.connect(self._toggle)
        layout.addWidget(self.header_btn)

        # Content area
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(12, 8, 12, 8)
        layout.addWidget(self.content)

    def _toggle(self, checked: bool) -> None:
        self.content.setVisible(checked)
        title = self.header_btn.text()[3:]  # strip arrow prefix
        arrow = "▼" if checked else "▶"
        self.header_btn.setText(f"{arrow}  {title}")

    def add_widget(self, w: QWidget) -> None:
        self.content_layout.addWidget(w)

    def add_layout(self, lay) -> None:
        self.content_layout.addLayout(lay)


# ──────────────────────────────────────────────────────────────────────────────
# IP Scanner thread
# ──────────────────────────────────────────────────────────────────────────────

class IPScannerThread(QThread):
    """Runs the Google IP scanner and emits the best IP found."""

    result = pyqtSignal(str, int)  # (best_ip, latency_ms)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, front_domain: str, parent=None) -> None:
        super().__init__(parent)
        self.front_domain = front_domain

    def run(self) -> None:
        try:
            # Ensure engine on path
            engine_src = _GUI_ROOT / "engine" / "src"
            if str(engine_src) not in sys.path:
                sys.path.insert(0, str(engine_src))

            import asyncio
            from core.google_ip_scanner import _probe_ip, CANDIDATE_IPS  # type: ignore
            from core.constants import GOOGLE_SCANNER_TIMEOUT, GOOGLE_SCANNER_CONCURRENCY  # type: ignore

            self.progress.emit("Scanning Google frontend IPs…")

            async def _scan():
                import asyncio
                sem = asyncio.Semaphore(GOOGLE_SCANNER_CONCURRENCY)
                tasks = [_probe_ip(ip, self.front_domain, sem, GOOGLE_SCANNER_TIMEOUT)
                         for ip in CANDIDATE_IPS]
                results = await asyncio.gather(*tasks)
                return results

            results = asyncio.run(_scan())
            reachable = [r for r in results if r.ok]
            if not reachable:
                self.error.emit("No reachable Google IPs found on this network.")
                return
            reachable.sort(key=lambda r: r.latency_ms or 99999)
            best = reachable[0]
            self.result.emit(best.ip, best.latency_ms or 0)
        except Exception as exc:
            self.error.emit(str(exc))


# ──────────────────────────────────────────────────────────────────────────────
# ConfigTab
# ──────────────────────────────────────────────────────────────────────────────

def _tooltip_btn(tip: str) -> QToolButton:
    btn = QToolButton()
    btn.setText("?")
    btn.setFixedSize(20, 20)
    btn.setToolTip(tip)
    btn.setStyleSheet("QToolButton { border: 1px solid #555; border-radius: 10px; font-size:10px; }")
    return btn


def _field_row(label: str, widget: QWidget, tip: str = "") -> QHBoxLayout:
    row = QHBoxLayout()
    lbl = QLabel(label)
    lbl.setMinimumWidth(180)
    row.addWidget(lbl)
    row.addWidget(widget, stretch=1)
    if tip:
        row.addWidget(_tooltip_btn(tip))
    return row


class ConfigTab(QWidget):
    """
    Form-based editor for all config.json fields.

    Call :meth:`load_config` to populate fields from a dict and
    :meth:`get_config` to read back the current form values.
    """

    config_saved = pyqtSignal(dict)   # emitted after successful save

    def __init__(self, config_manager, parent=None) -> None:
        super().__init__(parent)
        self._cm = config_manager
        self._scanner_thread: Optional[IPScannerThread] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        self._build_relay_section(layout)
        self._build_ports_section(layout)
        self._build_fronting_section(layout)
        self._build_exit_node_section(layout)
        self._build_performance_section(layout)
        self._build_host_policies_section(layout)
        self._build_adblock_section(layout)

        layout.addStretch()
        scroll.setWidget(container)
        outer.addWidget(scroll)

        # ── Bottom toolbar ─────────────────────────────────────────────
        toolbar = QFrame()
        toolbar.setFrameShape(QFrame.Shape.StyledPanel)
        toolbar.setStyleSheet("QFrame { border-top: 1px solid #3D3D5C; background: #252535; }")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(16, 8, 16, 8)

        btn_save = QPushButton("💾  Save Config")
        btn_save.setObjectName("btn_primary")
        btn_save.clicked.connect(self._on_save)

        btn_reset = QPushButton("↺  Reset to Defaults")
        btn_reset.clicked.connect(self._on_reset)

        btn_import = QPushButton("📂  Import Config…")
        btn_import.clicked.connect(self._on_import)

        btn_export = QPushButton("💼  Export Config…")
        btn_export.clicked.connect(self._on_export)

        for btn in (btn_save, btn_reset, btn_import, btn_export):
            tb_layout.addWidget(btn)
        tb_layout.addStretch()

        outer.addWidget(toolbar)

    # ── Section builders ───────────────────────────────────────────────

    def _build_relay_section(self, layout: QVBoxLayout) -> None:
        sec = CollapsibleSection("Google Apps Script Relay")

        # auth_key
        auth_row = QHBoxLayout()
        auth_lbl = QLabel("Auth Key")
        auth_lbl.setMinimumWidth(180)
        self.auth_key_field = PasswordField("Strong random secret (must match Code.gs)")
        btn_gen = QPushButton("Generate Random")
        btn_gen.setFixedWidth(130)
        btn_gen.clicked.connect(self._generate_auth_key)
        auth_row.addWidget(auth_lbl)
        auth_row.addWidget(self.auth_key_field, stretch=1)
        auth_row.addWidget(btn_gen)
        auth_row.addWidget(_tooltip_btn("Must match AUTH_KEY in your Code.gs deployment."))
        sec.add_layout(auth_row)

        # script_id (single)
        self.script_id_edit = QLineEdit()
        self.script_id_edit.setPlaceholderText("AKfycby… (single deployment ID)")
        sec.add_layout(_field_row(
            "Script ID", self.script_id_edit,
            "The Apps Script deployment ID. Get it from Deploy → Manage deployments."
        ))

        # script_ids (multiple)
        ids_lbl = QLabel("Script IDs (Load Balancing)")
        ids_lbl.setStyleSheet("font-weight: bold; margin-top: 8px;")
        sec.add_widget(ids_lbl)
        sec.add_widget(QLabel(
            "Add multiple deployment IDs to distribute requests and avoid quota limits:"
        ))

        ids_row = QHBoxLayout()
        self.script_ids_list = QListWidget()
        self.script_ids_list.setFixedHeight(90)
        self.script_id_input = QLineEdit()
        self.script_id_input.setPlaceholderText("AKfycby…")
        self.script_id_input.returnPressed.connect(self._add_script_id)
        btn_add_id = QPushButton("Add")
        btn_add_id.setFixedWidth(60)
        btn_add_id.clicked.connect(self._add_script_id)
        btn_del_id = QPushButton("Remove")
        btn_del_id.setFixedWidth(70)
        btn_del_id.clicked.connect(self._remove_script_id)

        ids_left = QVBoxLayout()
        ids_left.addWidget(self.script_ids_list)
        input_row2 = QHBoxLayout()
        input_row2.addWidget(self.script_id_input)
        input_row2.addWidget(btn_add_id)
        input_row2.addWidget(btn_del_id)
        ids_left.addLayout(input_row2)
        ids_row.addLayout(ids_left)
        sec.add_layout(ids_row)

        # Buttons
        btn_row = QHBoxLayout()
        btn_open_gas = QPushButton("Open Google Apps Script →")
        btn_open_gas.clicked.connect(lambda: self._open_url("https://script.google.com"))
        btn_copy_gs = QPushButton("Copy Code.gs to Clipboard")
        btn_copy_gs.clicked.connect(self._copy_code_gs)
        btn_row.addWidget(btn_open_gas)
        btn_row.addWidget(btn_copy_gs)
        btn_row.addStretch()
        sec.add_layout(btn_row)

        layout.addWidget(sec)

    def _build_ports_section(self, layout: QVBoxLayout) -> None:
        sec = CollapsibleSection("Proxy Ports")

        self.http_port = QSpinBox()
        self.http_port.setRange(1, 65535)
        self.http_port.setValue(8085)
        sec.add_layout(_field_row("HTTP Proxy Port", self.http_port,
                                   "Local port for the HTTP/HTTPS proxy (default 8085)."))

        self.socks5_port = QSpinBox()
        self.socks5_port.setRange(1, 65535)
        self.socks5_port.setValue(1080)
        sec.add_layout(_field_row("SOCKS5 Port", self.socks5_port,
                                   "Local port for the SOCKS5 proxy (default 1080)."))

        self.listen_host = QComboBox()
        self.listen_host.addItem("Localhost only (127.0.0.1)", "127.0.0.1")
        self.listen_host.addItem("All interfaces (0.0.0.0) — enables LAN sharing", "0.0.0.0")
        sec.add_layout(_field_row("Listen Host", self.listen_host,
                                   "Bind address. Use 0.0.0.0 to share on LAN."))

        layout.addWidget(sec)

    def _build_fronting_section(self, layout: QVBoxLayout) -> None:
        sec = CollapsibleSection("Domain Fronting")

        ip_row = QHBoxLayout()
        ip_lbl = QLabel("Google IP")
        ip_lbl.setMinimumWidth(180)
        self.google_ip = QLineEdit()
        self.google_ip.setPlaceholderText("216.239.38.120")
        btn_scan = QPushButton("Scan for Fastest IP")
        btn_scan.setFixedWidth(150)
        btn_scan.clicked.connect(self._scan_ips)
        self.lbl_scan_result = QLabel("")
        self.lbl_scan_result.setStyleSheet("color: #4CAF50; font-size: 11px;")
        ip_row.addWidget(ip_lbl)
        ip_row.addWidget(self.google_ip, stretch=1)
        ip_row.addWidget(btn_scan)
        ip_row.addWidget(_tooltip_btn("Google frontend IP for domain fronting."))
        sec.add_layout(ip_row)
        sec.add_widget(self.lbl_scan_result)

        self.front_domains = QTextEdit()
        self.front_domains.setFixedHeight(80)
        self.front_domains.setPlaceholderText(
            "www.google.com\nmail.google.com\naccounts.google.com"
        )
        sec.add_layout(_field_row(
            "Front Domains", self.front_domains,
            "SNI/Host domains to use for fronting (one per line)."
        ))

        self.verify_ssl = QCheckBox("Verify SSL certificates")
        sec.add_widget(self.verify_ssl)

        layout.addWidget(sec)

    def _build_exit_node_section(self, layout: QVBoxLayout) -> None:
        sec = CollapsibleSection("Exit Node")

        enable_row = QHBoxLayout()
        self.exit_enabled = QCheckBox("Enable exit node")
        self.exit_enabled.toggled.connect(self._toggle_exit_node)
        enable_row.addWidget(self.exit_enabled)
        enable_row.addWidget(_tooltip_btn(
            "Route selected hosts through a Cloudflare Worker or VPS exit node."
        ))
        enable_row.addStretch()
        sec.add_layout(enable_row)

        self.exit_node_widget = QWidget()
        en_layout = QVBoxLayout(self.exit_node_widget)
        en_layout.setContentsMargins(0, 0, 0, 0)

        self.exit_provider = QComboBox()
        self.exit_provider.addItems(["Cloudflare Workers", "Deno Deploy", "VPS", "Custom"])
        en_layout.addLayout(_field_row("Provider", self.exit_provider,
                                        "The type of exit node you've deployed."))

        self.exit_url = QLineEdit()
        self.exit_url.setPlaceholderText("https://your-worker.workers.dev")
        en_layout.addLayout(_field_row("Exit Node URL", self.exit_url,
                                        "The HTTPS URL of your Cloudflare Worker or VPS."))

        self.exit_psk = PasswordField("Pre-shared key (must match worker PSK)")
        en_layout.addLayout(_field_row("PSK", self.exit_psk,
                                        "Secret key to authenticate requests to your exit node."))

        mode_lbl = QLabel("Mode:")
        self.exit_mode_selective = QRadioButton("Selective (listed hosts only)")
        self.exit_mode_full = QRadioButton("Full (all traffic)")
        self.exit_mode_selective.setChecked(True)
        mode_row = QHBoxLayout()
        mode_row.addWidget(mode_lbl)
        mode_row.addWidget(self.exit_mode_selective)
        mode_row.addWidget(self.exit_mode_full)
        mode_row.addStretch()
        en_layout.addLayout(mode_row)

        hosts_lbl = QLabel("Hosts (selective mode):")
        en_layout.addWidget(hosts_lbl)
        self.exit_hosts = TagInput("Add hostname and press Enter")
        self.exit_hosts.set_tags([
            "claude.ai", "anthropic.com", "chatgpt.com", "openai.com",
            "chat.openai.com", "api.openai.com",
            "challenges.cloudflare.com", "turnstile.cloudflare.com",
        ])
        en_layout.addWidget(self.exit_hosts)

        # ── Deployment instructions ────────────────────────────────────────
        deploy_note = QLabel(
            "<b>⚠  Cloudflare Worker PSK must match this field!</b><br>"
            "After deploying <code>cloudflare_worker.js</code>, open the Worker in the Cloudflare "
            "dashboard → <i>Settings → Variables</i> and set a variable named <b>PSK</b> to the "
            "same value as the PSK field above.<br>"
            "Alternatively, edit line 3 of <code>cloudflare_worker.js</code> before deploying:<br>"
            "&nbsp;&nbsp;<code>const PSK = &quot;YOUR_SECRET_HERE&quot;;</code><br>"
            "Then set the same value in the PSK field here and save."
        )
        deploy_note.setWordWrap(True)
        deploy_note.setOpenExternalLinks(True)
        deploy_note.setStyleSheet(
            "color:#CCC; font-size:12px; margin-top:6px;"
            " background:rgba(255,152,0,0.08); border:1px solid #553300;"
            " border-radius:4px; padding:8px 12px;"
        )
        en_layout.addWidget(deploy_note)

        btn_row = QHBoxLayout()
        btn_cf = QPushButton("Open Cloudflare Workers →")
        btn_cf.clicked.connect(lambda: self._open_url("https://dash.cloudflare.com"))
        btn_copy_worker = QPushButton("Copy cloudflare_worker.js")
        btn_copy_worker.clicked.connect(self._copy_worker_js)
        btn_row.addWidget(btn_cf)
        btn_row.addWidget(btn_copy_worker)
        btn_row.addStretch()
        en_layout.addLayout(btn_row)

        sec.add_widget(self.exit_node_widget)
        self.exit_node_widget.setEnabled(False)
        layout.addWidget(sec)

    def _build_performance_section(self, layout: QVBoxLayout) -> None:
        sec = CollapsibleSection("Performance")

        self.h2_connections = QSpinBox()
        self.h2_connections.setRange(1, 8)
        self.h2_connections.setValue(1)
        sec.add_layout(_field_row("H2 Connections", self.h2_connections,
                                   "Number of HTTP/2 connections to the relay (1–8)."))

        self.parallel_relay = QSpinBox()
        self.parallel_relay.setRange(1, 4)
        self.parallel_relay.setValue(1)
        sec.add_layout(_field_row("Parallel Relay", self.parallel_relay,
                                   "Number of parallel relay workers."))

        self.relay_timeout = QSpinBox()
        self.relay_timeout.setRange(5, 120)
        self.relay_timeout.setValue(55)
        self.relay_timeout.setSuffix(" s")
        sec.add_layout(_field_row("Relay Timeout", self.relay_timeout,
                                   "Timeout for relay requests in seconds."))

        self.tls_connect_timeout = QSpinBox()
        self.tls_connect_timeout.setRange(5, 60)
        self.tls_connect_timeout.setValue(20)
        self.tls_connect_timeout.setSuffix(" s")
        sec.add_layout(_field_row("TLS Connect Timeout", self.tls_connect_timeout,
                                   "Timeout for TLS handshake."))

        self.enable_batch = QCheckBox("Enable request batching (micro)")
        self.enable_sub_batch = QCheckBox("Enable sub-batching")
        self.youtube_via_relay = QCheckBox("Route YouTube through relay")
        for w in (self.enable_batch, self.enable_sub_batch, self.youtube_via_relay):
            sec.add_widget(w)

        layout.addWidget(sec)

    def _build_host_policies_section(self, layout: QVBoxLayout) -> None:
        sec = CollapsibleSection("Host Policies")

        direct_lbl = QLabel("Direct Hosts (bypass relay, connect directly):")
        self.direct_hosts = TagInput("e.g. rubika.ir")
        bypass_lbl = QLabel("Bypass Hosts (bypass MITM and relay entirely):")
        self.bypass_hosts = TagInput("e.g. .local")
        block_lbl = QLabel("Block Hosts (return 403 to client):")
        self.block_hosts = TagInput("e.g. .doubleclick.net")

        for w in (direct_lbl, self.direct_hosts, bypass_lbl, self.bypass_hosts,
                  block_lbl, self.block_hosts):
            sec.add_widget(w)

        layout.addWidget(sec)

    def _build_adblock_section(self, layout: QVBoxLayout) -> None:
        sec = CollapsibleSection("Ad Blocking")

        sec.add_widget(QLabel(
            "Hosts list URLs. The proxy downloads and applies these on startup."
        ))

        self.adblock_list = QListWidget()
        self.adblock_list.setFixedHeight(110)
        sec.add_widget(self.adblock_list)

        btn_row = QHBoxLayout()
        self.adblock_input = QLineEdit()
        self.adblock_input.setPlaceholderText("https://raw.githubusercontent.com/…")
        btn_add_ab = QPushButton("Add")
        btn_add_ab.setFixedWidth(50)
        btn_add_ab.clicked.connect(self._add_adblock)
        btn_del_ab = QPushButton("Remove")
        btn_del_ab.setFixedWidth(70)
        btn_del_ab.clicked.connect(self._remove_adblock)
        btn_row.addWidget(self.adblock_input)
        btn_row.addWidget(btn_add_ab)
        btn_row.addWidget(btn_del_ab)
        sec.add_layout(btn_row)

        layout.addWidget(sec)

    # ── Slot implementations ───────────────────────────────────────────

    def _generate_auth_key(self) -> None:
        key = secrets.token_hex(16)
        self.auth_key_field.setText(key)

    def _add_script_id(self) -> None:
        text = self.script_id_input.text().strip()
        if text:
            self.script_ids_list.addItem(text)
            self.script_id_input.clear()

    def _remove_script_id(self) -> None:
        for item in self.script_ids_list.selectedItems():
            self.script_ids_list.takeItem(self.script_ids_list.row(item))

    def _add_adblock(self) -> None:
        url = self.adblock_input.text().strip()
        if url:
            self.adblock_list.addItem(url)
            self.adblock_input.clear()

    def _remove_adblock(self) -> None:
        for item in self.adblock_list.selectedItems():
            self.adblock_list.takeItem(self.adblock_list.row(item))

    def _toggle_exit_node(self, enabled: bool) -> None:
        self.exit_node_widget.setEnabled(enabled)

    def _scan_ips(self) -> None:
        front = self.front_domains.toPlainText().strip().splitlines()
        domain = front[0].strip() if front else "www.google.com"
        self.lbl_scan_result.setText("Scanning… this may take up to 30 seconds")

        self._scanner_thread = IPScannerThread(domain, self)
        self._scanner_thread.result.connect(self._on_scan_result)
        self._scanner_thread.error.connect(self._on_scan_error)
        self._scanner_thread.start()

    def _on_scan_result(self, ip: str, latency: int) -> None:
        self.google_ip.setText(ip)
        self.lbl_scan_result.setText(f"✓ Best IP: {ip} ({latency} ms)")

    def _on_scan_error(self, msg: str) -> None:
        self.lbl_scan_result.setText(f"✗ Scan failed: {msg}")

    def _open_url(self, url: str) -> None:
        import webbrowser
        webbrowser.open(url)

    def _copy_code_gs(self) -> None:
        path = _GUI_ROOT / "engine" / "apps_script" / "Code.gs"
        self._copy_file_to_clipboard(path)

    def _copy_worker_js(self) -> None:
        path = _GUI_ROOT / "engine" / "apps_script" / "cloudflare_worker.js"
        self._copy_file_to_clipboard(path)

    def _copy_file_to_clipboard(self, path: Path) -> None:
        from PyQt6.QtWidgets import QApplication
        try:
            text = path.read_text(encoding="utf-8")
            QApplication.clipboard().setText(text)
            QMessageBox.information(self, "Copied", f"Content of {path.name} copied to clipboard.")
        except OSError as exc:
            QMessageBox.warning(self, "Error", f"Could not read file: {exc}")

    # ── Public config API ──────────────────────────────────────────────

    def load_config(self, cfg: dict) -> None:
        """Populate all form fields from a configuration dict."""
        self.auth_key_field.setText(cfg.get("auth_key", ""))
        self.script_id_edit.setText(cfg.get("script_id", ""))

        self.script_ids_list.clear()
        for sid in cfg.get("script_ids", []):
            self.script_ids_list.addItem(sid)

        self.http_port.setValue(cfg.get("http_port", 8085))
        self.socks5_port.setValue(cfg.get("socks5_port", 1080))
        idx = self.listen_host.findData(cfg.get("listen_host", "127.0.0.1"))
        self.listen_host.setCurrentIndex(max(0, idx))

        self.google_ip.setText(cfg.get("google_ip", "216.239.38.120"))
        self.front_domains.setPlainText(
            "\n".join(cfg.get("front_domains", ["www.google.com"]))
        )
        self.verify_ssl.setChecked(cfg.get("verify_ssl", True))

        en = cfg.get("exit_node", {})
        self.exit_enabled.setChecked(en.get("enabled", False))
        self.exit_node_widget.setEnabled(en.get("enabled", False))
        provider_map = {"cloudflare": 0, "deno": 1, "vps": 2, "custom": 3}
        self.exit_provider.setCurrentIndex(provider_map.get(en.get("provider", "cloudflare"), 0))
        self.exit_url.setText(en.get("url", ""))
        self.exit_psk.setText(en.get("psk", ""))
        if en.get("mode", "selective") == "full":
            self.exit_mode_full.setChecked(True)
        else:
            self.exit_mode_selective.setChecked(True)
        self.exit_hosts.set_tags(en.get("hosts", []))

        self.h2_connections.setValue(cfg.get("h2_connections", 1))
        self.parallel_relay.setValue(cfg.get("parallel_relay", 1))
        self.relay_timeout.setValue(cfg.get("relay_timeout", 55))
        self.tls_connect_timeout.setValue(cfg.get("tls_connect_timeout", 20))
        self.enable_batch.setChecked(cfg.get("enable_batch", True))
        self.enable_sub_batch.setChecked(cfg.get("enable_sub_batch", False))
        self.youtube_via_relay.setChecked(cfg.get("youtube_via_relay", False))

        self.direct_hosts.set_tags(cfg.get("direct_hosts", []))
        self.bypass_hosts.set_tags(cfg.get("bypass_hosts", []))
        self.block_hosts.set_tags(cfg.get("block_hosts", []))

        self.adblock_list.clear()
        for url in cfg.get("adblock_lists", []):
            self.adblock_list.addItem(url)

    def get_config(self) -> dict:
        """Read all form fields and return a config dict."""
        script_ids = [
            self.script_ids_list.item(i).text()
            for i in range(self.script_ids_list.count())
        ]

        cfg: dict[str, Any] = {
            "auth_key":             self.auth_key_field.text(),
            "script_id":            self.script_id_edit.text().strip(),
            "script_ids":           script_ids,
            "http_port":            self.http_port.value(),
            "socks5_port":          self.socks5_port.value(),
            "listen_host":          self.listen_host.currentData(),
            "lan_sharing":          self.listen_host.currentData() == "0.0.0.0",
            "google_ip":            self.google_ip.text().strip(),
            "front_domains":        [
                l.strip() for l in self.front_domains.toPlainText().splitlines()
                if l.strip()
            ],
            "front_domain":         (
                self.front_domains.toPlainText().strip().splitlines() or ["www.google.com"]
            )[0].strip(),
            "verify_ssl":           self.verify_ssl.isChecked(),
            "exit_node": {
                "enabled":   self.exit_enabled.isChecked(),
                "provider":  self.exit_provider.currentText().lower().split()[0],
                "url":       self.exit_url.text().strip(),
                "psk":       self.exit_psk.text(),
                "mode":      "full" if self.exit_mode_full.isChecked() else "selective",
                "hosts":     self.exit_hosts.get_tags(),
            },
            "h2_connections":       self.h2_connections.value(),
            "parallel_relay":       self.parallel_relay.value(),
            "relay_timeout":        self.relay_timeout.value(),
            "tls_connect_timeout":  self.tls_connect_timeout.value(),
            "enable_batch":         self.enable_batch.isChecked(),
            "enable_sub_batch":     self.enable_sub_batch.isChecked(),
            "youtube_via_relay":    self.youtube_via_relay.isChecked(),
            "direct_hosts":         self.direct_hosts.get_tags(),
            "bypass_hosts":         self.bypass_hosts.get_tags(),
            "block_hosts":          self.block_hosts.get_tags(),
            "adblock_lists":        [
                self.adblock_list.item(i).text()
                for i in range(self.adblock_list.count())
            ],
        }
        return cfg

    def _on_save(self) -> None:
        cfg = self.get_config()
        errors = self._cm.validate(cfg)
        if errors:
            QMessageBox.warning(self, "Validation Errors",
                                "Please fix the following issues:\n\n" + "\n".join(errors))
            return
        try:
            self._cm.save(cfg)
            self.config_saved.emit(cfg)
            self._show_toast("Config saved successfully.")
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))

    def _on_reset(self) -> None:
        if QMessageBox.question(
            self, "Reset Config",
            "Reset all fields to defaults? Current values will be lost.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.load_config(self._cm.get_defaults())

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Config", "", "JSON Files (*.json);;All Files (*)"
        )
        if path:
            try:
                cfg = self._cm.import_from(path)
                self.load_config(cfg)
                self._show_toast(f"Imported from {Path(path).name}")
            except Exception as exc:
                QMessageBox.critical(self, "Import Failed", str(exc))

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Config", "config_export.json", "JSON Files (*.json)"
        )
        if path:
            strip = QMessageBox.question(
                self, "Strip Sensitive Fields?",
                "Remove auth_key and PSK before exporting?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            ) == QMessageBox.StandardButton.Yes
            try:
                cfg = self.get_config()
                self._cm.export_to(path, cfg, strip_sensitive=strip)
                self._show_toast(f"Exported to {Path(path).name}")
            except Exception as exc:
                QMessageBox.critical(self, "Export Failed", str(exc))

    def _show_toast(self, msg: str) -> None:
        QMessageBox.information(self, "Config", msg)
