"""
log_tab.py — Live Logs tab.

Terminal-style: one clean line per log entry, colour-coded by level.
Strips ANSI escape codes, box-drawing characters, and any garbled
characters produced by the engine's pretty-formatter.
"""
from __future__ import annotations

import platform
import re

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QTextCursor, QTextCharFormat
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from core.log_bridge import LogEntry

# Strip ANSI escape codes
_ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
# Strip non-printable / box-drawing / block elements that engines emit
# Keep: tab (09), LF (0A), printable ASCII (20-7E), common extended latin (A0-FF)
_GARBAGE    = re.compile(r"[^\x09\x20-\x7E\xA0-\xFF]")
# Collapse multiple spaces into one (after stripping)
_MULTI_SPACE = re.compile(r"  +")

_LEVEL_COLORS = {
    "DEBUG":    "#78909C",
    "INFO":     "#CDD6F4",
    "WARNING":  "#FFA726",
    "ERROR":    "#F44336",
    "CRITICAL": "#FF1744",
}

_PATTERN_COLORS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"H2 (idle keepalive|remote closed|connect)", re.I), "#42A5F5"),
    (re.compile(r"(MITM|CONNECT|HTTP proxy|SOCKS5)",          re.I), "#78909C"),
    (re.compile(r"Apps Script executions",                    re.I), "#66BB6A"),
    (re.compile(r"(exception|traceback|unhandled)",           re.I), "#F44336"),
    (re.compile(r"(listening on|started)",                    re.I), "#80CBC4"),
    (re.compile(r"(Fronter|Relay|H2)",                        re.I), "#42A5F5"),
    (re.compile(r"(Adblock|adblock)",                         re.I), "#AB47BC"),
]

_MIN_LEVELS = {
    "DEBUG":   0,
    "INFO":    1,
    "WARNING": 2,
    "ERROR":   3,
}

# The engine's PrettyFormatter emits lines like:
#   11:03:22  • INFO   [Main    ]  DomainFront Tunnel starting (Apps Script relay)
# We parse that into a clean terminal-style line.
_PRETTY_RE = re.compile(
    r"^(\d{2}:\d{2}:\d{2})\s+[•!]\s+"
    r"(DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL)\s+"
    r"\[([^\]]+)\]\s+"
    r"(.+)$"
)


def _clean(raw: str) -> str:
    """Strip ANSI + garbage and return a clean one-line string."""
    s = _ANSI_ESCAPE.sub("", raw)
    s = _GARBAGE.sub("", s)
    s = _MULTI_SPACE.sub(" ", s)
    return s.strip()


def _format_entry(entry: LogEntry) -> str:
    """Return a single terminal-style line for an entry."""
    msg = _clean(entry.message)
    # Try to re-parse engine pretty-format
    m = _PRETTY_RE.match(msg)
    if m:
        ts, level, logger, text = m.group(1), m.group(2), m.group(3).strip(), m.group(4).strip()
        return f"{ts}  {level:<8} [{logger:<10}] {text}"
    # Fallback: return as-is (already cleaned)
    return msg


def _color_for_entry(entry: LogEntry) -> str:
    msg = entry.message
    for pattern, color in _PATTERN_COLORS:
        if pattern.search(msg):
            return color
    return _LEVEL_COLORS.get(entry.level, "#CDD6F4")


class LogTab(QWidget):
    """Live Logs tab — clean terminal-style output."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._all_entries: list[tuple[LogEntry, str]] = []  # (entry, formatted_line)
        self._filter_text = ""
        self._min_level = 0
        self._auto_scroll = True
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        # Toolbar
        toolbar = QHBoxLayout()

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter log lines…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self.filter_edit, stretch=3)

        toolbar.addWidget(QLabel("Level:"))
        self.level_combo = QComboBox()
        self.level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.level_combo.setCurrentText("INFO")
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

        # Log text area
        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setMaximumBlockCount(15000)

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

        self.lbl_count = QLabel("0 lines")
        self.lbl_count.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self.lbl_count)

    # ── Public API ─────────────────────────────────────────────────────

    def append_entry(self, entry: LogEntry) -> None:
        line = _format_entry(entry)
        clean_entry = LogEntry(level=entry.level, logger=entry.logger, message=line)
        self._all_entries.append((clean_entry, line))

        entry_level = _MIN_LEVELS.get(clean_entry.level, 1)
        if entry_level < self._min_level:
            return
        if self._filter_text and self._filter_text.lower() not in line.lower():
            return

        self._append_colored(clean_entry, line)

    def clear(self) -> None:
        self._all_entries.clear()
        self.text_edit.clear()
        self.lbl_count.setText("0 lines")

    # ── Private ────────────────────────────────────────────────────────

    def _append_colored(self, entry: LogEntry, line: str) -> None:
        color = _color_for_entry(entry)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))

        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # Each entry on its own line
        if self.text_edit.document().blockCount() > 1 or self.text_edit.toPlainText():
            cursor.insertText("\n")

        cursor.setCharFormat(fmt)
        cursor.insertText(line)

        if self._auto_scroll:
            self.text_edit.setTextCursor(cursor)
            self.text_edit.ensureCursorVisible()

        self.lbl_count.setText(f"{len(self._all_entries)} lines")

    def _rebuild_display(self) -> None:
        self.text_edit.clear()
        min_lvl = self._min_level
        flt = self._filter_text.lower()

        for entry, line in self._all_entries:
            entry_level = _MIN_LEVELS.get(entry.level, 1)
            if entry_level < min_lvl:
                continue
            if flt and flt not in line.lower():
                continue
            self._append_colored(entry, line)

    def _on_filter_changed(self, text: str) -> None:
        self._filter_text = text.strip()
        self._rebuild_display()

    def _on_level_changed(self, level: str) -> None:
        self._min_level = _MIN_LEVELS.get(level, 0)
        self._rebuild_display()

    def _save_to_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Log", "proxy_log.txt", "Text Files (*.txt);;All Files (*)"
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(self.text_edit.toPlainText())
            except OSError as exc:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Save Failed", str(exc))
