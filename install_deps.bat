@echo off
REM ──────────────────────────────────────────────────────────────────────────
REM install_deps.bat — Install all required Python packages into _vendor/
REM
REM Run this ONCE when you first install MasterHttpRelayVPN-GUI.
REM An internet connection is required for this one-time step.
REM After installation the application runs completely offline.
REM ──────────────────────────────────────────────────────────────────────────

echo ============================================================
echo  MasterHttpRelayVPN-GUI — Dependency Installer (Windows)
echo ============================================================
echo.

REM Check Python is available
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo ERROR: Python was not found on PATH.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo Make sure to tick "Add Python to PATH" during installation.
    pause
    exit /b 1
)

python -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)"
IF ERRORLEVEL 1 (
    echo ERROR: Python 3.10 or newer is required.
    python --version
    pause
    exit /b 1
)

echo Python found:
python --version
echo.

REM Create _vendor/ directory
IF NOT EXIST "_vendor" mkdir "_vendor"

echo Installing packages into _vendor\ ...
echo.

python -m pip install ^
    PyQt6>=6.6.0 ^
    cryptography==46.0.0 ^
    h2>=4.1.0 ^
    brotli>=1.1.0 ^
    zstandard>=0.22.0 ^
    --target="_vendor" ^
    --upgrade ^
    --quiet

IF ERRORLEVEL 1 (
    echo.
    echo ERROR: pip install failed. Check your internet connection and try again.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Installation complete!
echo  You can now run MasterHttpRelayVPN-GUI without internet.
echo ============================================================
echo.
echo To launch:  python main_gui.py
echo.
pause
