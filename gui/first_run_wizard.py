"""
first_run_wizard.py — First-run setup QWizard (v2).

Shown on first launch when no config.json exists.  Guides the user
through Apps Script deployment and exit node setup, then saves the
resulting configuration with System Proxy mode active by default.

Changes from v1
---------------
- Auto-connect / "Connect now" option completely removed.
- ProxyMode wizard page removed; System Proxy is always set as default.
- Import mode jumps directly to the confirmation page (skips all setup).
- Improved visual design: cards, step badges, better spacing.
- Final page shows "Configuration saved" with "Launch Application →"
  instead of a Finish button labelled "Finish".
"""

from __future__ import annotations

import secrets
import webbrowser
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QRadioButton, QVBoxLayout,
    QWidget, QWizard, QWizardPage,
)

_GUI_ROOT = Path(__file__).resolve().parent.parent


# ─── Shared visual helpers ────────────────────────────────────────────────────

def _card(html: str, bg: str = "#252535", border: str = "#3D3D5C") -> QLabel:
    """Return a styled info-card QLabel."""
    lbl = QLabel(html)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(
        f"background:{bg}; border:1px solid {border}; border-radius:8px; "
        "padding:12px 16px; font-size:12px; line-height:1.7;"
    )
    return lbl


def _separator() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet("color:#3D3D5C; margin: 2px 0;")
    return f


def _bold(text: str, size: int = 13) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"font-weight:bold; font-size:{size}px; color:#CDD6F4;")
    return lbl


def _field_row(label_text: str, widget: QWidget,
               extra: Optional[QWidget] = None,
               label_width: int = 120) -> QHBoxLayout:
    row = QHBoxLayout()
    lbl = QLabel(label_text)
    lbl.setFixedWidth(label_width)
    lbl.setStyleSheet("font-weight:bold; font-size:12px;")
    row.addWidget(lbl)
    row.addWidget(widget, stretch=1)
    if extra:
        row.addWidget(extra)
    return row


def _make_success_pixmap(size: int = 72) -> QPixmap:
    """Draw an antialiased green circle with a white checkmark."""
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Outer glow (soft shadow)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(76, 175, 80, 40))
    p.drawEllipse(0, 0, size, size)

    # Green filled circle
    p.setBrush(QColor("#4CAF50"))
    margin = size // 10
    p.drawEllipse(margin, margin, size - margin * 2, size - margin * 2)

    # White checkmark
    pen = QPen(QColor("white"))
    pen.setWidth(max(3, size // 10))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawLine(int(size * 0.27), int(size * 0.53),
               int(size * 0.44), int(size * 0.70))
    p.drawLine(int(size * 0.44), int(size * 0.70),
               int(size * 0.76), int(size * 0.31))
    p.end()
    return px


def _link_button(text: str, color: str = "#42A5F5",
                 bg: str = "#1A2A40", hover_bg: str = "#1E3A58") -> QPushButton:
    """Return a styled small accent link-style button."""
    btn = QPushButton(text)
    btn.setStyleSheet(
        f"QPushButton {{ background:{bg}; border:1px solid {color}; "
        f"border-radius:5px; padding:5px 12px; color:{color}; font-size:12px; }}"
        f"QPushButton:hover {{ background:{hover_bg}; }}"
        "QPushButton:pressed { opacity: 0.8; }"
    )
    return btn


# ─── Connectivity-test worker ─────────────────────────────────────────────────

class TestScriptThread(QThread):
    """Background thread: tests a live Apps Script deployment."""
    result = pyqtSignal(bool, str)

    def __init__(self, script_id: str, auth_key: str, parent=None):
        super().__init__(parent)
        self.script_id = script_id
        self.auth_key = auth_key

    def run(self) -> None:
        import ssl
        import json
        import urllib.request
        import urllib.error
        try:
            url = f"https://script.google.com/macros/s/{self.script_id}/exec"
            payload = json.dumps({
                "auth":    self.auth_key,
                "url":     "http://example.com",
                "method":  "GET",
                "headers": {},
                "body":    None,
            }).encode()
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, context=ctx, timeout=15)
            body = resp.read(256).decode(errors="ignore")
            if resp.status == 200:
                self.result.emit(True, f"✓  Apps Script responded  (HTTP {resp.status})")
            else:
                self.result.emit(False, f"HTTP {resp.status}: {body[:80]}")
        except Exception as exc:
            self.result.emit(False, str(exc)[:120])


# ─── Page 1 — Welcome ─────────────────────────────────────────────────────────

class WelcomePage(QWizardPage):
    """Intro page: choose between fresh setup or config import."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Welcome to MasterHttpRelayVPN")
        self.setSubTitle(
            "Quick setup in just a few steps.  Takes about 2 minutes."
        )
        self._imported_path: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(8, 4, 8, 4)

        # What is this?
        layout.addWidget(_card(
            "🛡  <b>MasterHttpRelayVPN</b> routes your traffic through a "
            "<b>Google Apps Script</b> relay using domain fronting — bypassing "
            "DPI-based censorship without a commercial VPN.<br><br>"
            "You only need a <b>free Google account</b> to get started.  "
            "A Cloudflare account is optional (only for claude.ai / ChatGPT)."
        ))

        layout.addSpacing(4)
        layout.addWidget(_bold("How would you like to start?"))
        layout.addSpacing(2)

        self.radio_fresh = QRadioButton(
            "Set up from scratch  —  guided step-by-step  (recommended)"
        )
        self.radio_import = QRadioButton(
            "Import an existing  config.json  file"
        )
        self.radio_fresh.setChecked(True)
        for rb in (self.radio_fresh, self.radio_import):
            rb.setStyleSheet("font-size:13px; padding:4px 0;")
        layout.addWidget(self.radio_fresh)
        layout.addWidget(self.radio_import)

        # Import file picker (visible but disabled until radio selected)
        import_row = QHBoxLayout()
        import_row.setContentsMargins(24, 0, 0, 0)
        self.btn_import = QPushButton("  📂  Choose config.json…")
        self.btn_import.setFixedWidth(210)
        self.btn_import.setEnabled(False)
        self.btn_import.setStyleSheet(
            "QPushButton { background:#2A2A3E; border:1px solid #5C5C7A; "
            "border-radius:5px; padding:5px 10px; }"
            "QPushButton:hover { background:#3A3A50; }"
            "QPushButton:disabled { color:#555577; border-color:#3D3D5C; }"
        )
        self.btn_import.clicked.connect(self._pick_file)

        self.lbl_file = QLabel("")
        self.lbl_file.setStyleSheet("color:#6E9EC0; font-size:11px; margin-left:8px;")
        import_row.addWidget(self.btn_import)
        import_row.addWidget(self.lbl_file, stretch=1)
        layout.addLayout(import_row)

        self.radio_import.toggled.connect(self.btn_import.setEnabled)
        self.radio_fresh.toggled.connect(lambda _: self.completeChanged.emit())
        self.radio_import.toggled.connect(lambda _: self.completeChanged.emit())

        layout.addStretch()

    # ── QWizardPage overrides ──────────────────────────────────────────

    def isComplete(self) -> bool:
        if self.radio_import.isChecked():
            return bool(self._imported_path)
        return True

    def nextId(self) -> int:
        wiz = self.wizard()
        if self.radio_import.isChecked() and self._imported_path:
            return wiz._PAGE_FINISH
        return wiz._PAGE_GAS

    # ── Slots ──────────────────────────────────────────────────────────

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose config.json", "", "JSON Files (*.json);;All Files (*)"
        )
        if path:
            self._imported_path = path
            name = Path(path).name
            self.btn_import.setText(f"  ✓  {name}")
            self.lbl_file.setText("Ready to import")
            self.completeChanged.emit()

    # ── Public helpers ─────────────────────────────────────────────────

    def get_import_path(self) -> Optional[str]:
        return self._imported_path if self.radio_import.isChecked() else None


# ─── Page 2 — Apps Script Relay ───────────────────────────────────────────────

class AppsScriptPage(QWizardPage):
    """Configure the Google Apps Script relay deployment."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("① Apps Script Relay")
        self.setSubTitle(
            "Deploy the relay script to Google Apps Script and enter the details below."
        )
        self._test_thread: Optional[TestScriptThread] = None

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(8, 4, 8, 4)

        # Action buttons row
        btn_row = QHBoxLayout()
        btn_gas = _link_button("Open Google Apps Script →", "#42A5F5", "#1A2A40", "#1E3A58")
        btn_gas.clicked.connect(lambda: webbrowser.open("https://script.google.com"))
        btn_copy = _link_button("Copy Code.gs", "#9090B8", "#252535", "#2D2D45")
        btn_copy.clicked.connect(self._copy_code_gs)
        btn_row.addWidget(btn_gas)
        btn_row.addSpacing(8)
        btn_row.addWidget(btn_copy)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Instructions card
        layout.addWidget(_card(
            "<b>Quick steps:</b><br>"
            "(1)  Open <b>script.google.com</b> &rarr; New project<br>"
            "(2)  Paste the <b>Code.gs</b> content "
            "(use <i>Copy Code.gs</i> above)<br>"
            "(3)  Set a strong AUTH_KEY inside the script, or generate one below<br>"
            "(4)  <b>Deploy &rarr; New deployment &rarr; Web app &rarr; "
            "Execute as Me &rarr; Who has access: Anyone &rarr; Deploy</b><br>"
            "(5)  Copy the <b>Deployment ID</b> and paste it in the field below"
        ))

        layout.addSpacing(2)

        # Auth Key field
        self.auth_key = QLineEdit()
        self.auth_key.setPlaceholderText("Strong random secret (must match CODE.GS AUTH_KEY)")
        self.auth_key.setEchoMode(QLineEdit.EchoMode.Password)
        btn_gen_key = QPushButton("Generate")
        btn_gen_key.setFixedWidth(84)
        btn_gen_key.clicked.connect(
            lambda: self.auth_key.setText(secrets.token_hex(16))
        )
        layout.addLayout(_field_row("Auth Key:", self.auth_key, btn_gen_key))

        # Script ID field
        self.script_id = QLineEdit()
        self.script_id.setPlaceholderText("AKfycby…  (from Apps Script → Deploy → Manage deployments)")
        layout.addLayout(_field_row("Deployment ID:", self.script_id))

        layout.addSpacing(2)

        # Test connection row
        test_row = QHBoxLayout()
        self.btn_test = QPushButton("🔌  Test Connection")
        self.btn_test.setFixedWidth(160)
        self.btn_test.clicked.connect(self._test_connection)
        self.lbl_test = QLabel("")
        self.lbl_test.setStyleSheet("font-size:12px; margin-left:10px;")
        test_row.addWidget(self.btn_test)
        test_row.addWidget(self.lbl_test)
        test_row.addStretch()
        layout.addLayout(test_row)

        layout.addStretch()

        # Required-field registration (QWizard validates these before Next)
        self.registerField("auth_key*", self.auth_key)
        self.registerField("script_id*", self.script_id)

    # ── QWizardPage overrides ──────────────────────────────────────────

    def nextId(self) -> int:
        return self.wizard()._PAGE_EXIT

    # ── Slots ──────────────────────────────────────────────────────────

    def _copy_code_gs(self) -> None:
        from PyQt6.QtWidgets import QApplication
        path = _GUI_ROOT / "engine" / "apps_script" / "Code.gs"
        try:
            QApplication.clipboard().setText(path.read_text(encoding="utf-8"))
            self.lbl_test.setStyleSheet("font-size:12px; margin-left:10px; color:#4CAF50;")
            self.lbl_test.setText("✓  Code.gs copied to clipboard")
        except OSError as exc:
            QMessageBox.warning(self, "Error", str(exc))

    def _test_connection(self) -> None:
        sid = self.script_id.text().strip()
        key = self.auth_key.text().strip()
        if not sid or not key:
            self.lbl_test.setStyleSheet("font-size:12px; margin-left:10px; color:#FFA726;")
            self.lbl_test.setText("⚠  Enter Auth Key and Deployment ID first")
            return
        self.btn_test.setEnabled(False)
        self.lbl_test.setStyleSheet("font-size:12px; margin-left:10px; color:#CDD6F4;")
        self.lbl_test.setText("Testing…")
        self._test_thread = TestScriptThread(sid, key, self)
        self._test_thread.result.connect(self._on_test_result)
        self._test_thread.start()

    def _on_test_result(self, ok: bool, msg: str) -> None:
        self.btn_test.setEnabled(True)
        color = "#4CAF50" if ok else "#F44336"
        self.lbl_test.setStyleSheet(f"font-size:12px; margin-left:10px; color:{color};")
        self.lbl_test.setText(msg)


# ─── Page 3 — Exit Node (Optional) ───────────────────────────────────────────

class ExitNodePage(QWizardPage):
    """Optional Cloudflare exit node for AI-site access."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("② Exit Node  (Optional)")
        self.setSubTitle(
            "Only needed if you want to reach claude.ai, ChatGPT, or OpenAI."
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(8, 4, 8, 4)

        # Why card
        layout.addWidget(_card(
            "🚀  <b>When is this needed?</b><br>"
            "Sites like <b>claude.ai</b>, <b>chatgpt.com</b>, and "
            "<b>openai.com</b> actively block Google's IP ranges.  "
            "A Cloudflare Worker exit node re-routes those requests "
            "through Cloudflare's edge network so they become reachable.<br><br>"
            "⚡  <b>Skip this step</b> if you only need to bypass standard "
            "DPI censorship — the Apps Script relay is sufficient."
        ))

        self.chk_enable = QCheckBox(
            "Enable Cloudflare Worker exit node for AI sites"
        )
        self.chk_enable.setStyleSheet("font-size:13px; padding:4px 0;")
        self.chk_enable.toggled.connect(self._toggle_fields)
        layout.addWidget(self.chk_enable)

        # Fields (hidden until checkbox ticked)
        self.fields_widget = QWidget()
        fl = QVBoxLayout(self.fields_widget)
        fl.setContentsMargins(20, 4, 0, 4)
        fl.setSpacing(8)

        btn_row = QHBoxLayout()
        btn_cf = _link_button("Open Cloudflare Dashboard →", "#FFA726", "#2A1E0A", "#3A2A0A")
        btn_cf.clicked.connect(lambda: webbrowser.open("https://dash.cloudflare.com"))
        btn_copy_w = _link_button("Copy cloudflare_worker.js", "#9090B8", "#252535", "#2D2D45")
        btn_copy_w.clicked.connect(self._copy_worker)
        btn_row.addWidget(btn_cf)
        btn_row.addSpacing(8)
        btn_row.addWidget(btn_copy_w)
        btn_row.addStretch()
        fl.addLayout(btn_row)

        fl.addWidget(_card(
            "<b>Steps:</b>  Cloudflare Dashboard → Workers → Create → "
            "paste <b>cloudflare_worker.js</b> → set PSK secret → Deploy → "
            "copy your worker URL below",
            bg="#1E2020", border="#3A4040"
        ))

        self.exit_url = QLineEdit()
        self.exit_url.setPlaceholderText("https://your-worker.workers.dev")
        fl.addLayout(_field_row("Worker URL:", self.exit_url, label_width=110))

        self.exit_psk = QLineEdit()
        self.exit_psk.setEchoMode(QLineEdit.EchoMode.Password)
        self.exit_psk.setPlaceholderText("Secret from cloudflare_worker.js")
        btn_psk = QPushButton("Generate")
        btn_psk.setFixedWidth(84)
        btn_psk.clicked.connect(
            lambda: self.exit_psk.setText(secrets.token_hex(16))
        )
        fl.addLayout(_field_row("Worker PSK:", self.exit_psk, btn_psk, label_width=110))

        layout.addWidget(self.fields_widget)
        self.fields_widget.setEnabled(False)
        layout.addStretch()

    # ── QWizardPage overrides ──────────────────────────────────────────

    def nextId(self) -> int:
        return self.wizard()._PAGE_FINISH

    # ── Slots ──────────────────────────────────────────────────────────

    def _toggle_fields(self, enabled: bool) -> None:
        self.fields_widget.setEnabled(enabled)

    def _copy_worker(self) -> None:
        from PyQt6.QtWidgets import QApplication
        path = _GUI_ROOT / "engine" / "apps_script" / "cloudflare_worker.js"
        try:
            QApplication.clipboard().setText(path.read_text(encoding="utf-8"))
        except OSError as exc:
            QMessageBox.warning(self, "Error", str(exc))

    # ── Public helpers ─────────────────────────────────────────────────

    def get_exit_node(self) -> dict:
        return {
            "enabled":  self.chk_enable.isChecked(),
            "provider": "cloudflare",
            "url":      self.exit_url.text().strip(),
            "psk":      self.exit_psk.text(),
            "mode":     "selective",
            "hosts": [
                "claude.ai", "anthropic.com",
                "chatgpt.com", "openai.com",
                "chat.openai.com", "api.openai.com",
                "challenges.cloudflare.com", "turnstile.cloudflare.com",
            ],
        }


# ─── Page 4 — Finish / Confirmation ──────────────────────────────────────────

class FinishPage(QWizardPage):
    """
    Final confirmation page.

    The summary is populated by FirstRunWizard when this page becomes
    current (before the user clicks "Launch Application →").
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("You're all set!")
        self.setSubTitle("Your configuration has been saved.  The application is ready to use.")
        self.setFinalPage(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ── Success icon + headline ────────────────────────────────────
        icon_row = QHBoxLayout()
        icon_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl = QLabel()
        self._icon_lbl.setPixmap(_make_success_pixmap(72))
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_row.addWidget(self._icon_lbl)
        layout.addLayout(icon_row)

        self.lbl_headline = QLabel(
            "✓  Configuration saved successfully!"
        )
        self.lbl_headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_headline.setWordWrap(True)
        self.lbl_headline.setStyleSheet(
            "font-size:16px; font-weight:bold; color:#4CAF50; margin:4px 0 2px;"
        )
        layout.addWidget(self.lbl_headline)

        self.lbl_info = QLabel(
            "🌐  <b>System Proxy</b> is enabled by default.<br>"
            "Your browser and any app that respects OS proxy settings will be "
            "routed through MasterHttpRelayVPN immediately after you click "
            "<b>Launch Application</b>."
        )
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_info.setStyleSheet(
            "font-size:12px; color:#A0A0C0; line-height:1.6;"
        )
        layout.addWidget(self.lbl_info)

        layout.addWidget(_separator())

        # ── Configuration summary card ─────────────────────────────────
        self._summary = QLabel("—")
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet(
            "background:#252535; border:1px solid #3D3D5C; border-radius:8px; "
            "padding:12px 16px; font-size:12px; line-height:1.9;"
        )
        layout.addWidget(self._summary)

        layout.addStretch()

        # ── Tip ────────────────────────────────────────────────────────
        tip = QLabel(
            "💡  You can adjust proxy mode, ports, and advanced settings "
            "inside the application at any time."
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("font-size:11px; color:#6E6E96; font-style:italic;")
        layout.addWidget(tip)

    # ── Public helpers ─────────────────────────────────────────────────

    def populate_summary(self, import_mode: bool = False,
                         script_id: str = "",
                         exit_enabled: bool = False) -> None:
        """Fill the summary card.  Called when the page becomes visible."""
        if import_mode:
            self._summary.setText(
                "📁  <b>Source:</b>  Imported from existing config.json<br>"
                "🌐  <b>Proxy Mode:</b>  System Proxy  <i>(active by default)</i>"
            )
        else:
            sid_short = (script_id[:22] + "…") if len(script_id) > 22 else script_id
            exit_str = (
                "✓  Cloudflare Worker enabled"
                if exit_enabled
                else "Not enabled  <i>(optional — required for claude.ai / ChatGPT)</i>"
            )
            self._summary.setText(
                f"🔗  <b>Apps Script:</b>  Configured"
                f"  <span style='color:#6E6E96;font-size:11px;'>({sid_short})</span><br>"
                f"🚪  <b>Exit Node:</b>  {exit_str}<br>"
                "🌐  <b>Proxy Mode:</b>  System Proxy  <i>(active by default)</i>"
            )

    def set_error(self, msg: str) -> None:
        """Show a warning headline (called on save failure)."""
        self.lbl_headline.setText(f"⚠  Warning: {msg}")
        self.lbl_headline.setStyleSheet(
            "font-size:14px; font-weight:bold; color:#FFA726; margin:4px 0 2px;"
        )
        self._icon_lbl.hide()


# ─── Main wizard class ────────────────────────────────────────────────────────

class FirstRunWizard(QWizard):
    """
    First-run setup wizard shown when no config.json exists.

    Page flow
    ---------
    Fresh setup:  Welcome → AppsScript → ExitNode → Finish
    Import mode:  Welcome → Finish  (configuration pages skipped)

    After ``exec()`` returns ``QDialog.Accepted``:
    - Call :meth:`get_config` to retrieve the assembled config dict.

    Note: The "connect now" option has been removed.  System Proxy mode
    is always saved as the active default.
    """

    def __init__(self, config_manager, parent=None) -> None:
        super().__init__(parent)
        self._cm = config_manager
        self._config: dict = {}

        self.setWindowTitle("MasterHttpRelayVPN — First-Time Setup")
        self.setMinimumSize(720, 560)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)

        # ── Button labels ──────────────────────────────────────────────
        self.setButtonText(QWizard.WizardButton.FinishButton, "Launch Application  →")
        self.setButtonText(QWizard.WizardButton.NextButton,   "Next  ›")
        self.setButtonText(QWizard.WizardButton.BackButton,   "‹  Back")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Cancel")

        # ── Extra QSS on top of the app's global dark theme ────────────
        self.setStyleSheet("""
            QWizard > QWidget {
                background-color: #1E1E2E;
            }
            /* Modern-style header area */
            QLabel#qt_wizard_titleLabel {
                font-size: 16px;
                font-weight: bold;
                color: #CDD6F4;
            }
            QLabel#qt_wizard_subTitleLabel {
                font-size: 12px;
                color: #9090B0;
            }
            /* Finish / Next buttons get an accent colour */
            QPushButton#qt_wizard_finishButton,
            QPushButton#qt_wizard_nextButton {
                background: #3A6A9E;
                color: #FFFFFF;
                border: none;
                border-radius: 5px;
                padding: 6px 18px;
                font-weight: bold;
            }
            QPushButton#qt_wizard_finishButton:hover,
            QPushButton#qt_wizard_nextButton:hover {
                background: #4A80B8;
            }
            QPushButton#qt_wizard_backButton,
            QPushButton#qt_wizard_cancelButton {
                background: #3D3D5C;
                color: #CDD6F4;
                border: 1px solid #5C5C7A;
                border-radius: 5px;
                padding: 6px 14px;
            }
            QPushButton#qt_wizard_backButton:hover,
            QPushButton#qt_wizard_cancelButton:hover {
                background: #4D4D6C;
            }
        """)

        # ── Pages ──────────────────────────────────────────────────────
        self.welcome_page = WelcomePage()
        self.gas_page     = AppsScriptPage()
        self.exit_page    = ExitNodePage()
        self.finish_page  = FinishPage()

        self._PAGE_WELCOME = self.addPage(self.welcome_page)
        self._PAGE_GAS     = self.addPage(self.gas_page)
        self._PAGE_EXIT    = self.addPage(self.exit_page)
        self._PAGE_FINISH  = self.addPage(self.finish_page)

        # ── Wire signals ───────────────────────────────────────────────
        self.currentIdChanged.connect(self._on_page_changed)
        self.button(QWizard.WizardButton.FinishButton).clicked.connect(
            self._on_finish
        )

    # ── Signal handlers ────────────────────────────────────────────────

    def _on_page_changed(self, page_id: int) -> None:
        """Populate the finish page summary when the user arrives there."""
        if page_id != self._PAGE_FINISH:
            return
        import_path = self.welcome_page.get_import_path()
        if import_path:
            self.finish_page.populate_summary(import_mode=True)
        else:
            self.finish_page.populate_summary(
                import_mode=False,
                script_id=self.gas_page.script_id.text().strip(),
                exit_enabled=self.exit_page.chk_enable.isChecked(),
            )

    def _on_finish(self) -> None:
        """Assemble and persist config when the user clicks 'Launch Application'."""
        import_path = self.welcome_page.get_import_path()

        if import_path:
            # ── Import mode ────────────────────────────────────────────
            try:
                cfg = self._cm.import_from(import_path)
                # Write to the canonical config path
                self._cm.config_path.write_text(
                    Path(import_path).read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
                # Ensure system proxy is set as default if not present
                if "proxy_mode" not in cfg:
                    cfg["proxy_mode"] = "system"
                    try:
                        self._cm.save(cfg)
                    except Exception:
                        pass
                cfg["_wizard_sys_proxy"] = True
                cfg["_wizard_tun"] = False
                self._config = cfg
            except Exception as exc:
                self.finish_page.set_error(f"Import failed: {exc}")
            return

        # ── Fresh-setup mode ───────────────────────────────────────────
        defaults = self._cm.get_defaults()
        defaults.update({
            "auth_key":          self.gas_page.auth_key.text().strip(),
            "script_id":         self.gas_page.script_id.text().strip(),
            "exit_node":         self.exit_page.get_exit_node(),
            # System Proxy is always the startup default
            "proxy_mode":        "system",
            "_wizard_sys_proxy": True,
            "_wizard_tun":       False,
        })

        try:
            errors = self._cm.validate(defaults)
            if errors:
                self.finish_page.set_error(
                    "Validation warnings: " + ";  ".join(errors[:2])
                )
            self._cm.save(defaults)
            self._config = defaults
        except Exception as exc:
            self.finish_page.set_error(str(exc))

    # ── Public API ─────────────────────────────────────────────────────

    def get_config(self) -> dict:
        """Return the assembled and saved configuration dict."""
        return self._config

    # Retained for backward compatibility; always returns False.
    def should_connect_now(self) -> bool:
        return False

    def wizard_sys_proxy(self) -> bool:
        return self._config.get("_wizard_sys_proxy", True)

    def wizard_tun(self) -> bool:
        return self._config.get("_wizard_tun", False)
