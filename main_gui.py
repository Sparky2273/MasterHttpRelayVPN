#!/usr/bin/env python3
"""
main_gui.py — PyQt6 entry point for MasterHttpRelayVPN GUI.

Handles:
- --run-engine mode: used by frozen PyInstaller EXE to spawn the engine
  as a subprocess of itself (instead of needing an external Python interpreter)
- Offline-first dependency check (_vendor/ injection)
- Missing-dependency error dialog with instructions
- First-run wizard (when no config.json exists)
- Main window launch

Changes from previous version:
- Auto-connect after wizard has been removed. The wizard no longer has
  a "Connect now" option; the user starts the proxy manually from the
  main window. System Proxy mode is activated by default.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ─── Offline-first: inject _vendor/ into sys.path BEFORE any imports ─────────

_GUI_ROOT = Path(__file__).resolve().parent
_VENDOR   = _GUI_ROOT / "_vendor"

if _VENDOR.is_dir():
    vendor_str = str(_VENDOR)
    if vendor_str not in sys.path:
        sys.path.insert(0, vendor_str)

# ─── Engine subprocess mode (PyInstaller frozen EXE) ─────────────────────────
# When the frozen EXE is launched with --run-engine it runs the proxy engine
# directly instead of showing the GUI, letting ProxyThread spawn it as a child
# process via Popen (stdout pipe).  This avoids needing a separate python.exe.

if "--run-engine" in sys.argv:
    _engine_root = _GUI_ROOT / "engine"
    _engine_src  = _engine_root / "src"
    for _p in (str(_engine_root), str(_engine_src)):
        if _p not in sys.path:
            sys.path.insert(0, _p)

    # Forward remaining args to engine main() (strips --run-engine)
    sys.argv = [sys.argv[0]] + sys.argv[sys.argv.index("--run-engine") + 1:]

    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("engine_main", str(_engine_root / "main.py"))
    _eng  = _ilu.module_from_spec(_spec)   # type: ignore[arg-type]
    _spec.loader.exec_module(_eng)          # type: ignore[union-attr]
    _eng.main()
    sys.exit(0)

# ─── Dependency check before importing Qt ────────────────────────────────────

_REQUIRED = {
    "PyQt6":        "PyQt6",
    "cryptography": "cryptography",
    "h2":           "h2",
}

_missing: list[str] = []
for pkg_import, pkg_name in _REQUIRED.items():
    try:
        __import__(pkg_import)
    except ImportError:
        _missing.append(pkg_name)

if _missing:
    print(
        f"ERROR: Missing required Python packages: {', '.join(_missing)}\n\n"
        "Run the bundled installer to install them:\n"
        "  Windows: install_deps.bat\n"
        "  Linux/macOS: bash install_deps.sh\n\n"
        "This only requires internet access once."
    )
    if "PyQt6" not in _missing:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        _dep_app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(
            None,
            "Missing Dependencies",
            f"The following Python packages are missing:\n\n"
            + "\n".join(f"  • {p}" for p in _missing)
            + "\n\nRun <b>install_deps.bat</b> (Windows) or "
              "<b>install_deps.sh</b> (Linux/macOS) to install them.\n"
              "An internet connection is required for this one-time step.",
        )
    sys.exit(1)

# ─── Now safe to import Qt and application modules ────────────────────────────

import platform

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from core.config_manager import ConfigManager
from core.app_logger import log_app, install_crash_logger
from gui.app_window import AppWindow
from gui.first_run_wizard import FirstRunWizard
from gui.styles import DARK_THEME


def _setup_app() -> QApplication:
    """Create and configure the QApplication instance."""
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("MasterHttpRelayVPN")
    app.setApplicationDisplayName("MasterHttpRelayVPN")
    app.setOrganizationName("MasterHttpRelayVPN")
    app.setStyleSheet(DARK_THEME)

    from PyQt6.QtGui import QFont
    _os = platform.system()
    if _os == "Windows":
        f = QFont("Segoe UI")
        f.setPointSize(9)
    elif _os == "Darwin":
        f = QFont("SF Pro Text")
        f.setPointSize(13)
    else:
        f = QFont("Ubuntu")
        if f.exactMatch():
            f.setPointSize(10)
        else:
            f = QFont("DejaVu Sans")
            f.setPointSize(10)
    app.setFont(f)
    return app


def main() -> None:
    """Application entry point."""
    app = _setup_app()

    cm = ConfigManager()

    if not cm.config_exists():
        wizard = FirstRunWizard(cm)
        result = wizard.exec()
        if result != FirstRunWizard.DialogCode.Accepted:
            reply = QMessageBox.question(
                None,
                "Continue Without Config?",
                "No configuration was saved. The proxy won't work until you "
                "set up an Apps Script deployment.\n\n"
                "Open the application anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                sys.exit(0)

    window = AppWindow(app)
    window.show()

    # Note: auto-connect after wizard has been intentionally removed.
    # System Proxy mode is active by default; users start the proxy
    # engine manually from the Dashboard when they are ready.

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
