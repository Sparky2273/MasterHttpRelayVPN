#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# install_deps.sh — Install all required Python packages into _vendor/
#
# Run this ONCE when you first install MasterHttpRelayVPN-GUI.
# An internet connection is required for this one-time step only.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

echo "============================================================"
echo " MasterHttpRelayVPN-GUI — Dependency Installer (Linux/macOS)"
echo "============================================================"
echo

# ── Find Python 3.10+ ────────────────────────────────────────────────────────
PYTHON=""
for cmd in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; print(sys.version_info >= (3,10))" 2>/dev/null)
        if [[ "$ver" == "True" ]]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    echo "ERROR: Python 3.10+ is required but was not found."
    echo "Install it via your package manager:"
    echo "  Ubuntu/Debian:  sudo apt install python3.11"
    echo "  Fedora:         sudo dnf install python3.11"
    echo "  macOS (Homebrew): brew install python@3.11"
    exit 1
fi

echo "Using Python: $($PYTHON --version)"
echo

# ── Create _vendor/ ───────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR_DIR="$SCRIPT_DIR/_vendor"
mkdir -p "$VENDOR_DIR"

echo "Installing packages into _vendor/ ..."
echo

"$PYTHON" -m pip install \
    "PyQt6>=6.6.0" \
    "cryptography>=41.0.0" \
    "h2>=4.1.0" \
    "brotli>=1.1.0" \
    "zstandard>=0.22.0" \
    --target="$VENDOR_DIR" \
    --upgrade \
    --quiet

echo
echo "============================================================"
echo " Installation complete!"
echo " The application now runs without internet after this step."
echo "============================================================"
echo
echo "To launch:"
echo "  python3 main_gui.py"
echo
