# -*- mode: python ; coding: utf-8 -*-
"""
MasterHttpRelayVPN.spec — PyInstaller build specification.

Key behaviour for the frozen EXE:
  ProxyThread launches the engine by re-running the same EXE with the
  ``--run-engine`` flag, which is handled in main_gui.py before Qt starts.
  This avoids the "second window opens" / "stuck at connecting" bug that
  occurs when sys.executable is an EXE and not a Python interpreter.

Usage:
    pyinstaller MasterHttpRelayVPN.spec --clean --noconfirm
"""

import sys
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH)

# ── Data files to bundle ──────────────────────────────────────────────────────
datas = [
    (str(ROOT / "engine"),  "engine"),
    (str(ROOT / "assets"),  "assets"),
]

# Only bundle _vendor/ if it exists
if (ROOT / "_vendor").is_dir():
    datas.append((str(ROOT / "_vendor"), "_vendor"))

# ── Hidden imports ────────────────────────────────────────────────────────────
hidden_imports = [
    # Engine modules (loaded via spec_from_file_location or direct import)
    "proxy.proxy_server",
    "proxy.mitm",
    "proxy.socks5",
    "proxy.proxy_support",
    "relay.domain_fronter",
    "relay.h2_transport",
    "relay.relay_response",
    "relay.fronting_support",
    "relay.http_reader",
    "core.cert_installer",
    "core.google_ip_scanner",
    "core.logging_utils",
    "core.adblock",
    "core.codec",
    "core.constants",
    "core.lan_utils",
    # PyQt6
    "PyQt6.sip",
    "PyQt6.QtSvg",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    # Cryptography
    "cryptography.hazmat.primitives.asymmetric.rsa",
    "cryptography.hazmat.primitives.serialization",
    "cryptography.x509",
    # Networking
    "h2",
    "hpack",
    "hyperframe",
    "certifi",
    "urllib.request",
    "urllib.error",
    "ssl",
    # Optional / psutil
    "psutil",
    # Compression (optional engine deps)
    "brotli",
    "zstandard",
]

a = Analysis(
    [str(ROOT / "main_gui.py")],
    pathex=[
        str(ROOT),
        str(ROOT / "engine"),
        str(ROOT / "engine" / "src"),
    ],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "IPython",
        "jupyter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MasterHttpRelayVPN",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # IMPORTANT: console=False hides the main window's console.
    # The engine subprocess (--run-engine child) writes to a pipe,
    # so no console is needed there either.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icon.ico") if sys.platform == "win32" else
         str(ROOT / "assets" / "icon.icns") if sys.platform == "darwin" else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MasterHttpRelayVPN",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="MasterHttpRelayVPN.app",
        icon=str(ROOT / "assets" / "icon.icns"),
        bundle_identifier="com.masterhttprelayvpn.gui",
        info_plist={
            "CFBundleName": "MasterHttpRelayVPN",
            "CFBundleDisplayName": "MasterHttpRelayVPN",
            "CFBundleVersion": "1.0.0",
            "CFBundleShortVersionString": "1.0.0",
            "NSHighResolutionCapable": True,
        },
    )
