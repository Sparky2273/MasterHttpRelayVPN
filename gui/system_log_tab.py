"""
system_log_tab.py — Application / System Log tab.

Terminal-style: one clean timestamped line per entry.
"""
from __future__ import annotations

import platform

from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from core.app_logger import AppLogEntry

_LEVEL_COLORS = {
    "DEBUG":    "#78909C",
    "INFO":     "#90CAF9",
    "WARNING":  "#FFA726",
    "ERROR":    "#F44336",
    "CRITICAL": "#FF1744",
}

_MIN_LEVELS = {
    "DEBUG":   0,
    "INFO":    1,
    "WARNING": 2,
    "ERROR":   3,
}

_SOURCE_COLORS = {
    "Connection":  "#4CAF50",
    "Certificate": "#CE93D8",
    "Config":      "#4FC3F7",
    "Proxy":       "#80CBC4",
    "TUN":         "#FFD54F",
    "Cert":        "#CE93D8",
}


def _color_for_entry(entry: AppLogEntry) -> str:
    sc = _SOURCE_COLORS.get(entry.source)
    if sc and entry.level in ("INFO", "DEBUG"):
        return sc
    return _LEVEL_COLORS.get(entry.level, "#CDD6F4")


def _format_line(entry: AppLogEntry) -> str:
    return f"{entry.timestamp} [{entry.level:<8}] [{entry.source:<12}] {entry.message}"


class SystemLogTab(QWidget):
    """System / Application Log tab — terminal-style one line per entry."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._all_entries: list[AppLogEntry] = []
        self._filter_text = ""
        self._min_level = 0
        self._auto_scroll = True
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        toolbar = QHBoxLayout()

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter system log…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self.filter_edit, stretch=3)

        toolbar.addWidget(QLabel("Level:"))
        self.level_combo = QComboBox()
        self.level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.level_combo.setCurrentText("DEBUG")
        self.level_combo.currentTextChanged.connect(self._on_level_changed)
        toolbar.addWidget(self.level_combo)

        toolbar.addSpacing(10)

        self.chk_autoscroll = QCheckBox("Auto-scroll")
        self.chk_autoscroll.setChecked(True)
        self.chk_autoscroll.toggled.connect(lambda v: setattr(self, "_auto_scroll", v))
        toolbar.addWidget(self.chk_autoscroll)

        toolbar.addSpacing(10)

        btn_clear = QPushButton("Clear")
        btn_clear.setFixedWidth(70)
        btn_clear.clicked.connect(self.clear)
        toolbar.addWidget(btn_clear)

        btn_save = QPushButton("Save…")
        btn_save.setFixedWidth(70)
        btn_save.clicked.connect(self._save_to_file)
        toolbar.addWidget(btn_save)

        layout.addLayout(toolbar)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setMaximumBlockCount(20000)

        mono_font = QFont()
        if platform.system() == "Windows":
            mono_font.setFamily("Consolas")
        elif platform.system() == "Darwin":
            mono_font.setFamily("Menlo")
        else:
            mono_font.setFamily("DejaVu Sans Mono")
        mono_font.setPointSize(10)
        self.text_edit.setFont(mono_font)
        self.text_edit.setStyleSheet(
            "QPlainTextEdit { background-color: #0d1117; border: 1px solid #3D3D5C; "
            "border-radius: 6px; }"
        )

        layout.addWidget(self.text_edit)

        self.lbl_count = QLabel("0 entries")
        self.lbl_count.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self.lbl_count)

    # ── Public API ─────────────────────────────────────────────────────

    def append_entry(self, entry: AppLogEntry) -> None:
        self._all_entries.append(entry)

        entry_level = _MIN_LEVELS.get(entry.level, 0)
        if entry_level < self._min_level:
            return
        if self._filter_text and self._filter_text.lower() not in (
            entry.message.lower() + entry.source.lower()
        ):
            return

        self._append_colored(entry)

    def clear(self) -> None:
        self._all_entries.clear()
        self.text_edit.clear()
        self.lbl_count.setText("0 entries")

    # ── Private ────────────────────────────────────────────────────────

    def _append_colored(self, entry: AppLogEntry) -> None:
        color = _color_for_entry(entry)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))

        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        if self.text_edit.document().blockCount() > 1 or self.text_edit.toPlainText():
            cursor.insertText("\n")

        cursor.setCharFormat(fmt)
        cursor.insertText(_format_line(entry))

        if self._auto_scroll:
            self.text_edit.setTextCursor(cursor)
            self.text_edit.ensureCursorVisible()

        self.lbl_count.setText(f"{len(self._all_entries)} entries")

    def _rebuild_display(self) -> None:
        self.text_edit.clear()
        min_lvl = self._min_level
        flt = self._filter_text.lower()

        for entry in self._all_entries:
            entry_level = _MIN_LEVELS.get(entry.level, 0)
            if entry_level < min_lvl:
                continue
            if flt and flt not in (entry.message.lower() + entry.source.lower()):
                continue
            self._append_colored(entry)

    def _on_filter_changed(self, text: str) -> None:
        self._filter_text = text.strip()
        self._rebuild_display()

    def _on_level_changed(self, level: str) -> None:
        self._min_level = _MIN_LEVELS.get(level, 0)
        self._rebuild_display()

    def _save_to_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save System Log", "system_log.txt", "Text Files (*.txt);;All Files (*)"
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(self.text_edit.toPlainText())
            except OSError as exc:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Save Failed", str(exc))
