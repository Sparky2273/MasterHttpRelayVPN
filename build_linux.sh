#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# build_linux.sh — Build MasterHttpRelayVPN-GUI for Linux
#
# Prerequisites:
#   - Python 3.10+
#   - Run install_deps.sh first
#   - Optional: appimagetool (for .AppImage), dpkg-deb (for .deb)
#
# Output: dist/MasterHttpRelayVPN/  (onedir distribution)
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

echo "============================================================"
echo " MasterHttpRelayVPN-GUI — Linux Build"
echo "============================================================"
echo

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Find Python ───────────────────────────────────────────────────────────────
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; print(sys.version_info >= (3,10))" 2>/dev/null || echo False)
        if [[ "$ver" == "True" ]]; then
            PYTHON="$cmd"
            break
        fi
    fi
done
[[ -z "$PYTHON" ]] && { echo "ERROR: Python 3.10+ required"; exit 1; }
echo "Using: $($PYTHON --version)"

# ── Install PyInstaller ───────────────────────────────────────────────────────
echo "Installing PyInstaller..."
"$PYTHON" -m pip install pyinstaller --quiet

# ── Build ─────────────────────────────────────────────────────────────────────
echo "Running PyInstaller..."
"$PYTHON" -m PyInstaller MasterHttpRelayVPN.spec --clean --noconfirm

echo
echo "Build complete: dist/MasterHttpRelayVPN/"
echo

# ── AppImage (optional) ───────────────────────────────────────────────────────
if command -v appimagetool &>/dev/null; then
    echo "Creating AppImage..."
    APPDIR="dist/MasterHttpRelayVPN.AppDir"
    mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib" "$APPDIR/usr/share/applications"

    # Copy dist into AppDir
    cp -r dist/MasterHttpRelayVPN/* "$APPDIR/usr/bin/"

    # Create .desktop file
    cat > "$APPDIR/MasterHttpRelayVPN.desktop" << 'DESKTOP'
[Desktop Entry]
Name=MasterHttpRelayVPN
Exec=MasterHttpRelayVPN
Icon=MasterHttpRelayVPN
Type=Application
Categories=Network;
DESKTOP

    # Copy icon
    [ -f assets/icon.png ] && cp assets/icon.png "$APPDIR/MasterHttpRelayVPN.png"

    # Create AppRun symlink
    cat > "$APPDIR/AppRun" << 'APPRUN'
#!/bin/bash
HERE="$(dirname "$(readlink -f "${0}")")"
exec "$HERE/usr/bin/MasterHttpRelayVPN" "$@"
APPRUN
    chmod +x "$APPDIR/AppRun"

    appimagetool "$APPDIR" "dist/MasterHttpRelayVPN-x86_64.AppImage"
    echo "AppImage: dist/MasterHttpRelayVPN-x86_64.AppImage"
else
    echo "(appimagetool not found — skipping AppImage creation)"
    echo "To create an AppImage: https://appimage.github.io/appimagetool/"
fi

# ── .deb package (optional) ───────────────────────────────────────────────────
if command -v dpkg-deb &>/dev/null; then
    echo "Creating .deb package..."
    DEB_DIR="dist/MasterHttpRelayVPN-deb"
    mkdir -p "$DEB_DIR/DEBIAN"
    mkdir -p "$DEB_DIR/opt/MasterHttpRelayVPN"
    mkdir -p "$DEB_DIR/usr/share/applications"
    mkdir -p "$DEB_DIR/usr/bin"

    cp -r dist/MasterHttpRelayVPN/* "$DEB_DIR/opt/MasterHttpRelayVPN/"

    # Symlink binary
    cat > "$DEB_DIR/usr/bin/masterhttprelayvpn" << 'LAUNCH'
#!/bin/bash
exec /opt/MasterHttpRelayVPN/MasterHttpRelayVPN "$@"
LAUNCH
    chmod +x "$DEB_DIR/usr/bin/masterhttprelayvpn"

    # .desktop file
    cat > "$DEB_DIR/usr/share/applications/masterhttprelayvpn.desktop" << 'DESKTOP'
[Desktop Entry]
Name=MasterHttpRelayVPN
Comment=DPI-bypass proxy using Google Apps Script
Exec=/opt/MasterHttpRelayVPN/MasterHttpRelayVPN
Icon=/opt/MasterHttpRelayVPN/assets/icon.png
Type=Application
Categories=Network;
Terminal=false
DESKTOP

    # DEBIAN/control
    cat > "$DEB_DIR/DEBIAN/control" << 'CONTROL'
Package: masterhttprelayvpn
Version: 1.0.0
Section: net
Priority: optional
Architecture: amd64
Depends: libgl1
Maintainer: MasterHttpRelayVPN
Description: DPI-bypass local proxy using Google Apps Script relay
 Routes traffic through a Google Apps Script relay with domain fronting
 to bypass Deep Packet Inspection censorship.
CONTROL

    dpkg-deb --build "$DEB_DIR" "dist/masterhttprelayvpn_1.0.0_amd64.deb"
    echo ".deb: dist/masterhttprelayvpn_1.0.0_amd64.deb"
else
    echo "(dpkg-deb not found — skipping .deb creation)"
fi

echo
echo "============================================================"
echo " All done."
echo "============================================================"
