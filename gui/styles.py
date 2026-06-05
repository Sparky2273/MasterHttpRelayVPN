"""
styles.py — Qt Stylesheet (QSS) constants for the dark and light themes.

Import :data:`DARK_THEME` or :data:`LIGHT_THEME` and apply with
``app.setStyleSheet(DARK_THEME)`` or per-widget.
"""

from __future__ import annotations
import platform

_OS = platform.system()

# Platform-specific font family
if _OS == "Windows":
    _FONT = "Segoe UI"
elif _OS == "Darwin":
    _FONT = "SF Pro Display"
else:
    _FONT = "Ubuntu, Cantarell, sans-serif"

# ── Colour palette (dark) ─────────────────────────────────────────────────────
DARK = {
    "bg":            "#1E1E2E",
    "bg2":           "#252535",
    "bg3":           "#2D2D45",
    "border":        "#3D3D5C",
    "text":          "#CDD6F4",
    "text_muted":    "#6E6E96",
    "accent_green":  "#4CAF50",
    "accent_red":    "#F44336",
    "accent_yellow": "#FFA726",
    "accent_blue":   "#42A5F5",
    "accent_orange": "#FFA726",
    "tab_bg":        "#1A1A2E",
    "input_bg":      "#1A1A2E",
    "button_bg":     "#3D3D5C",
    "button_hover":  "#4D4D6C",
    "scroll_bg":     "#2D2D45",
    "scroll_handle": "#5C5C7A",
}

# ── Colour palette (light) ────────────────────────────────────────────────────
LIGHT = {
    "bg":            "#F5F5F5",
    "bg2":           "#FFFFFF",
    "bg3":           "#E8E8E8",
    "border":        "#C8C8C8",
    "text":          "#1E1E2E",
    "text_muted":    "#6E6E8E",
    "accent_green":  "#2E7D32",
    "accent_red":    "#C62828",
    "accent_yellow": "#E65100",
    "accent_blue":   "#1565C0",
    "accent_orange": "#E65100",
    "tab_bg":        "#EFEFEF",
    "input_bg":      "#FFFFFF",
    "button_bg":     "#DEDEDE",
    "button_hover":  "#CACACA",
    "scroll_bg":     "#E0E0E0",
    "scroll_handle": "#ABABAB",
}


def _build_qss(c: dict) -> str:
    return f"""
/* ── Global ─────────────────────────────────────────────── */
* {{
    font-family: "{_FONT}";
    font-size: 13px;
    color: {c['text']};
    selection-background-color: {c['accent_blue']};
    selection-color: #ffffff;
}}

QMainWindow, QDialog, QWidget {{
    background-color: {c['bg']};
}}

/* ── Tab Widget ─────────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {c['border']};
    background: {c['bg']};
    border-radius: 4px;
}}

QTabBar::tab {{
    background: {c['tab_bg']};
    color: {c['text_muted']};
    padding: 8px 18px;
    border: 1px solid {c['border']};
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
    font-size: 12px;
}}

QTabBar::tab:selected {{
    background: {c['bg']};
    color: {c['text']};
    border-bottom: 2px solid {c['accent_green']};
}}

QTabBar::tab:hover {{
    background: {c['bg3']};
    color: {c['text']};
}}

/* ── Push Buttons ───────────────────────────────────────── */
QPushButton {{
    background-color: {c['button_bg']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 6px 16px;
    font-size: 13px;
}}

QPushButton:hover {{
    background-color: {c['button_hover']};
    border-color: {c['accent_blue']};
}}

QPushButton:pressed {{
    background-color: {c['bg3']};
}}

QPushButton:disabled {{
    color: {c['text_muted']};
    background-color: {c['bg2']};
    border-color: {c['border']};
}}

QPushButton#btn_connect {{
    background-color: {c['accent_green']};
    color: #ffffff;
    font-size: 16px;
    font-weight: bold;
    border-radius: 8px;
    padding: 12px;
    border: none;
}}

QPushButton#btn_connect:hover {{
    background-color: #66BB6A;
}}

QPushButton#btn_disconnect {{
    background-color: {c['accent_red']};
    color: #ffffff;
    font-size: 16px;
    font-weight: bold;
    border-radius: 8px;
    padding: 12px;
    border: none;
}}

QPushButton#btn_disconnect:hover {{
    background-color: #EF5350;
}}

QPushButton#btn_primary {{
    background-color: {c['accent_blue']};
    color: #ffffff;
    border: none;
    font-weight: bold;
}}

QPushButton#btn_primary:hover {{
    background-color: #64B5F6;
}}

/* ── Line Edit / Text Edit ──────────────────────────────── */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {c['input_bg']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    padding: 4px 8px;
    color: {c['text']};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {c['accent_blue']};
}}

/* ── SpinBox ────────────────────────────────────────────── */
QSpinBox, QDoubleSpinBox {{
    background-color: {c['input_bg']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    padding: 3px 6px;
    color: {c['text']};
}}

QSpinBox::up-button, QDoubleSpinBox::up-button {{
    border: none;
    background: transparent;
}}

QSpinBox::down-button, QDoubleSpinBox::down-button {{
    border: none;
    background: transparent;
}}

/* ── ComboBox ───────────────────────────────────────────── */
QComboBox {{
    background-color: {c['input_bg']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    padding: 4px 8px;
    color: {c['text']};
    min-width: 6em;
}}

QComboBox:hover {{
    border-color: {c['accent_blue']};
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox QAbstractItemView {{
    background-color: {c['bg2']};
    border: 1px solid {c['border']};
    selection-background-color: {c['accent_blue']};
    outline: none;
}}

/* ── CheckBox / RadioButton ─────────────────────────────── */
QCheckBox, QRadioButton {{
    color: {c['text']};
    spacing: 8px;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {c['border']};
    background: {c['input_bg']};
    border-radius: 3px;
}}

QCheckBox::indicator:checked {{
    background-color: {c['accent_green']};
    border-color: {c['accent_green']};
}}

QRadioButton::indicator {{
    border-radius: 8px;
}}

QRadioButton::indicator:checked {{
    background-color: {c['accent_blue']};
    border-color: {c['accent_blue']};
}}

/* ── GroupBox ───────────────────────────────────────────── */
QGroupBox {{
    border: 1px solid {c['border']};
    border-radius: 6px;
    margin-top: 12px;
    padding: 8px;
    font-weight: bold;
    color: {c['text']};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
    background-color: {c['bg']};
}}

/* ── Labels ─────────────────────────────────────────────── */
QLabel {{
    color: {c['text']};
    background: transparent;
}}

QLabel#label_status_main {{
    font-size: 20px;
    font-weight: bold;
}}

QLabel#label_status_sub {{
    color: {c['text_muted']};
    font-size: 12px;
}}

/* ── Scroll Area ────────────────────────────────────────── */
QScrollArea {{
    border: none;
    background: transparent;
}}

QScrollBar:vertical {{
    background: {c['scroll_bg']};
    width: 8px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical {{
    background: {c['scroll_handle']};
    border-radius: 4px;
    min-height: 20px;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    background: {c['scroll_bg']};
    height: 8px;
    border-radius: 4px;
}}

QScrollBar::handle:horizontal {{
    background: {c['scroll_handle']};
    border-radius: 4px;
    min-width: 20px;
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── List / Table Widget ────────────────────────────────── */
QListWidget, QTableWidget, QTreeWidget {{
    background-color: {c['input_bg']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    alternate-background-color: {c['bg3']};
    gridline-color: {c['border']};
}}

QListWidget::item:selected, QTableWidget::item:selected {{
    background-color: {c['accent_blue']};
    color: #ffffff;
}}

QHeaderView::section {{
    background-color: {c['bg3']};
    border: 1px solid {c['border']};
    padding: 4px 8px;
    font-weight: bold;
}}

/* ── ToolTip ────────────────────────────────────────────── */
QToolTip {{
    background-color: {c['bg3']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    padding: 4px 8px;
}}

/* ── MenuBar / Menu ─────────────────────────────────────── */
QMenuBar {{
    background-color: {c['bg2']};
    border-bottom: 1px solid {c['border']};
}}

QMenuBar::item {{
    padding: 4px 10px;
    background: transparent;
}}

QMenuBar::item:selected {{
    background-color: {c['bg3']};
    border-radius: 4px;
}}

QMenu {{
    background-color: {c['bg2']};
    border: 1px solid {c['border']};
    border-radius: 4px;
}}

QMenu::item {{
    padding: 6px 24px 6px 12px;
}}

QMenu::item:selected {{
    background-color: {c['accent_blue']};
    color: #ffffff;
    border-radius: 2px;
}}

QMenu::separator {{
    height: 1px;
    background: {c['border']};
    margin: 4px 8px;
}}

/* ── Status Bar ─────────────────────────────────────────── */
QStatusBar {{
    background-color: {c['bg2']};
    border-top: 1px solid {c['border']};
    color: {c['text_muted']};
    font-size: 11px;
}}

/* ── Wizard ─────────────────────────────────────────────── */
QWizard {{
    background-color: {c['bg']};
}}

QWizardPage {{
    background-color: {c['bg']};
}}

/* ── Frame / Separator ──────────────────────────────────── */
QFrame[frameShape="4"],   /* HLine */
QFrame[frameShape="5"] {{ /* VLine */
    color: {c['border']};
}}

/* ── Progress Bar ───────────────────────────────────────── */
QProgressBar {{
    background-color: {c['bg3']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    text-align: center;
    color: {c['text']};
}}

QProgressBar::chunk {{
    background-color: {c['accent_green']};
    border-radius: 4px;
}}

/* ── Splitter ───────────────────────────────────────────── */
QSplitter::handle {{
    background: {c['border']};
}}
"""


DARK_THEME = _build_qss(DARK)
LIGHT_THEME = _build_qss(LIGHT)

# Convenience colour access for widget-level styling
def get_color(name: str, theme: str = "dark") -> str:
    """Return a hex colour string from the theme palette."""
    palette = DARK if theme == "dark" else LIGHT
    return palette.get(name, "#000000")
