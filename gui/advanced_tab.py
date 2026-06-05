"""
advanced_tab.py — Advanced / Expert settings tab.

Power-user fields not shown in the main Config tab.
A warning banner reminds the user these can break connectivity.
"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import pyqtSignal

_GUI_ROOT = Path(__file__).resolve().parent.parent


class AdvancedTab(QWidget):
    """Expert-only settings panel."""

    advanced_saved = pyqtSignal(dict)  # emitted when user saves advanced settings

    def __init__(self, config_manager, parent=None) -> None:
        super().__init__(parent)
        self._cm = config_manager
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # ── Warning banner ─────────────────────────────────────────────
        warn = QLabel(
            "⚠  Changing these settings may break connectivity. "
            "Only modify if you understand what each option does."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet(
            "background: rgba(255,167,38,0.15); color: #FFA726;"
            " border: 1px solid #E65100; border-radius: 4px;"
            " padding: 8px 14px; font-weight: bold; margin: 8px;"
        )
        outer.addWidget(warn)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 12, 20, 16)
        layout.setSpacing(10)

        self._build_timing(layout)
        self._build_chunked(layout)
        self._build_hosts_table(layout)
        self._build_google_ip_override(layout)
        self._build_buttons(layout)
        layout.addStretch()

        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _row(self, label: str, widget: QWidget, tip: str = "") -> QHBoxLayout:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setMinimumWidth(240)
        row.addWidget(lbl)
        row.addWidget(widget, stretch=1)
        if tip:
            from PyQt6.QtWidgets import QToolButton
            btn = QToolButton()
            btn.setText("?")
            btn.setFixedSize(20, 20)
            btn.setToolTip(tip)
            btn.setStyleSheet(
                "QToolButton { border:1px solid #555; border-radius:10px; font-size:10px; }"
            )
            row.addWidget(btn)
        return row

    def _build_timing(self, layout: QVBoxLayout) -> None:
        lbl = QLabel("Timing & Batching")
        lbl.setStyleSheet("font-weight:bold; font-size:14px; margin-top:8px;")
        layout.addWidget(lbl)

        self.ping_interval = QDoubleSpinBox()
        self.ping_interval.setRange(0.01, 2.0)
        self.ping_interval.setSingleStep(0.01)
        self.ping_interval.setDecimals(3)
        self.ping_interval.setValue(0.1)
        self.ping_interval.setSuffix(" s")
        layout.addLayout(self._row("Ping Interval", self.ping_interval,
                                    "How often keepalive pings are sent (seconds)."))

        self.tcp_connect_timeout = QSpinBox()
        self.tcp_connect_timeout.setRange(3, 60)
        self.tcp_connect_timeout.setValue(15)
        self.tcp_connect_timeout.setSuffix(" s")
        layout.addLayout(self._row("TCP Connect Timeout", self.tcp_connect_timeout,
                                    "Timeout for raw TCP connections (seconds)."))

        self.batch_window_micro = QDoubleSpinBox()
        self.batch_window_micro.setRange(0.001, 1.0)
        self.batch_window_micro.setSingleStep(0.001)
        self.batch_window_micro.setDecimals(3)
        self.batch_window_micro.setValue(0.020)
        self.batch_window_micro.setSuffix(" s")
        layout.addLayout(self._row("Micro-Batch Window", self.batch_window_micro,
                                    "Time window for micro-batching relay requests."))

        self.batch_window_macro = QDoubleSpinBox()
        self.batch_window_macro.setRange(0.010, 2.0)
        self.batch_window_macro.setSingleStep(0.010)
        self.batch_window_macro.setDecimals(3)
        self.batch_window_macro.setValue(0.100)
        self.batch_window_macro.setSuffix(" s")
        layout.addLayout(self._row("Macro-Batch Window", self.batch_window_macro,
                                    "Time window for macro-batching relay requests."))

        self.relay_ip_literals = QCheckBox("Route IP-literal addresses through relay")
        layout.addWidget(self.relay_ip_literals)

    def _build_chunked(self, layout: QVBoxLayout) -> None:
        lbl = QLabel("Chunked Download")
        lbl.setStyleSheet("font-weight:bold; font-size:14px; margin-top:16px;")
        layout.addWidget(lbl)

        self.chunked_exts = QLineEdit()
        self.chunked_exts.setPlaceholderText(".mp4, .mkv, .iso, .zip, .rar")
        layout.addLayout(self._row("File Extensions", self.chunked_exts,
                                    "Comma-separated list of extensions to stream in chunks."))

        self.chunked_min_size = QSpinBox()
        self.chunked_min_size.setRange(1, 10000)
        self.chunked_min_size.setValue(10)
        self.chunked_min_size.setSuffix(" MB")
        layout.addLayout(self._row("Min File Size", self.chunked_min_size,
                                    "Minimum file size (MB) to trigger chunked mode."))

        self.chunked_chunk_size = QSpinBox()
        self.chunked_chunk_size.setRange(1, 100)
        self.chunked_chunk_size.setValue(4)
        self.chunked_chunk_size.setSuffix(" MB")
        layout.addLayout(self._row("Chunk Size", self.chunked_chunk_size,
                                    "Size of each individual chunk (MB)."))

        self.chunked_max_parallel = QSpinBox()
        self.chunked_max_parallel.setRange(1, 16)
        self.chunked_max_parallel.setValue(4)
        layout.addLayout(self._row("Max Parallel Chunks", self.chunked_max_parallel,
                                    "Maximum concurrent chunk downloads."))

    def _build_hosts_table(self, layout: QVBoxLayout) -> None:
        lbl = QLabel("Manual DNS / Host Overrides")
        lbl.setStyleSheet("font-weight:bold; font-size:14px; margin-top:16px;")
        layout.addWidget(lbl)
        layout.addWidget(QLabel("Map hostnames to specific IPs (bypasses DNS):"))

        self.hosts_table = QTableWidget(0, 2)
        self.hosts_table.setHorizontalHeaderLabels(["Hostname / Pattern", "IP Address"])
        self.hosts_table.setFixedHeight(140)
        self.hosts_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.hosts_table)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("Add Row")
        btn_add.setFixedWidth(90)
        btn_add.clicked.connect(self._add_host_row)
        btn_del = QPushButton("Remove Row")
        btn_del.setFixedWidth(100)
        btn_del.clicked.connect(self._del_host_row)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_del)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # direct_google_exclude
        excl_lbl = QLabel("Direct Google Exclude (hostnames not routed directly to Google):")
        excl_lbl.setStyleSheet("margin-top:8px;")
        layout.addWidget(excl_lbl)
        self.direct_google_exclude = QLineEdit()
        self.direct_google_exclude.setPlaceholderText("Comma-separated hostnames")
        layout.addWidget(self.direct_google_exclude)

    def _build_google_ip_override(self, layout: QVBoxLayout) -> None:
        lbl = QLabel("Google IP Manual Override")
        lbl.setStyleSheet("font-weight:bold; font-size:14px; margin-top:16px;")
        layout.addWidget(lbl)

        self.google_ip_override = QLineEdit()
        self.google_ip_override.setPlaceholderText("Leave blank to use value from Configuration tab")
        layout.addLayout(self._row("Override Google IP", self.google_ip_override,
                                    "Overrides the google_ip field for this session only."))

    def _build_buttons(self, layout: QVBoxLayout) -> None:
        layout.addWidget(self._separator())
        btn_row = QHBoxLayout()

        btn_save = QPushButton("💾  Save Advanced Settings")
        btn_save.setStyleSheet(
            "QPushButton { background:#1565C0; color:white; font-weight:bold; "
            "border-radius:4px; padding:6px 14px; }"
            "QPushButton:hover { background:#1976D2; }"
        )
        btn_save.clicked.connect(self._save_advanced)

        btn_open_cfg = QPushButton("Open config.json in Text Editor")
        btn_open_cfg.clicked.connect(self._open_config_in_editor)

        btn_reset = QPushButton("Reset Advanced to Defaults")
        btn_reset.clicked.connect(self._reset_advanced)

        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_open_cfg)
        btn_row.addWidget(btn_reset)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _separator(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #3D3D5C;")
        return sep

    # ── Slots ──────────────────────────────────────────────────────────

    def _add_host_row(self) -> None:
        row = self.hosts_table.rowCount()
        self.hosts_table.insertRow(row)
        self.hosts_table.setItem(row, 0, QTableWidgetItem(""))
        self.hosts_table.setItem(row, 1, QTableWidgetItem(""))

    def _del_host_row(self) -> None:
        rows = {i.row() for i in self.hosts_table.selectedItems()}
        for row in sorted(rows, reverse=True):
            self.hosts_table.removeRow(row)

    def _save_advanced(self) -> None:
        """Emit advanced settings so AppWindow can persist them."""
        cfg = self.get_config()
        self.advanced_saved.emit(cfg)

    def _open_config_in_editor(self) -> None:
        cfg_path = _GUI_ROOT / "config.json"
        if not cfg_path.exists():
            QMessageBox.information(self, "No Config", "config.json does not exist yet.")
            return
        if platform.system() == "Windows":
            os.startfile(str(cfg_path))
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(cfg_path)])
        else:
            subprocess.Popen(["xdg-open", str(cfg_path)])

    def _reset_advanced(self) -> None:
        defaults = self._cm.get_defaults()
        self.load_config(defaults)

    # ── Public API ─────────────────────────────────────────────────────

    def load_config(self, cfg: dict) -> None:
        self.ping_interval.setValue(cfg.get("ping_interval", 0.1))
        self.tcp_connect_timeout.setValue(cfg.get("tcp_connect_timeout", 15))
        self.batch_window_micro.setValue(cfg.get("batch_window_micro", 0.020))
        self.batch_window_macro.setValue(cfg.get("batch_window_macro", 0.100))
        self.relay_ip_literals.setChecked(cfg.get("relay_ip_literals", True))

        exts = cfg.get("chunked_download_extensions", [])
        if isinstance(exts, list):
            self.chunked_exts.setText(", ".join(exts))
        else:
            self.chunked_exts.setText(str(exts))
        self.chunked_min_size.setValue(cfg.get("chunked_download_min_size", 10))
        self.chunked_chunk_size.setValue(cfg.get("chunked_download_chunk_size", 4))
        self.chunked_max_parallel.setValue(cfg.get("chunked_download_max_parallel", 4))

        hosts_dict = cfg.get("hosts", {})
        self.hosts_table.setRowCount(0)
        for host, ip in hosts_dict.items():
            row = self.hosts_table.rowCount()
            self.hosts_table.insertRow(row)
            self.hosts_table.setItem(row, 0, QTableWidgetItem(host))
            self.hosts_table.setItem(row, 1, QTableWidgetItem(ip))

        excl = cfg.get("direct_google_exclude", [])
        self.direct_google_exclude.setText(
            ", ".join(excl) if isinstance(excl, list) else str(excl)
        )

    def get_config(self) -> dict:
        exts_raw = self.chunked_exts.text()
        exts = [e.strip() for e in exts_raw.split(",") if e.strip()]

        hosts_dict = {}
        for row in range(self.hosts_table.rowCount()):
            host_item = self.hosts_table.item(row, 0)
            ip_item = self.hosts_table.item(row, 1)
            if host_item and ip_item:
                h, ip = host_item.text().strip(), ip_item.text().strip()
                if h and ip:
                    hosts_dict[h] = ip

        excl_raw = self.direct_google_exclude.text()
        excl = [e.strip() for e in excl_raw.split(",") if e.strip()]

        return {
            "ping_interval":              self.ping_interval.value(),
            "tcp_connect_timeout":        self.tcp_connect_timeout.value(),
            "batch_window_micro":         self.batch_window_micro.value(),
            "batch_window_macro":         self.batch_window_macro.value(),
            "relay_ip_literals":          self.relay_ip_literals.isChecked(),
            "chunked_download_extensions": exts,
            "chunked_download_min_size":  self.chunked_min_size.value(),
            "chunked_download_chunk_size": self.chunked_chunk_size.value(),
            "chunked_download_max_parallel": self.chunked_max_parallel.value(),
            "hosts":                      hosts_dict,
            "direct_google_exclude":      excl,
        }
