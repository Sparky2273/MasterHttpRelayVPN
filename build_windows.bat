@echo off
REM ──────────────────────────────────────────────────────────────────────────
REM build_windows.bat — Build MasterHttpRelayVPN-GUI for Windows
REM
REM Prerequisites:
REM   - Python 3.10+
REM   - Run install_deps.bat first
REM
REM Output: dist\MasterHttpRelayVPN\  (onedir, ready to distribute)
REM ──────────────────────────────────────────────────────────────────────────

echo ============================================================
echo  MasterHttpRelayVPN-GUI — Windows Build
echo ============================================================
echo.

python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo ERROR: Python not found on PATH.
    pause
    exit /b 1
)

echo Installing PyInstaller...
python -m pip install pyinstaller --quiet
IF ERRORLEVEL 1 (
    echo ERROR: Could not install PyInstaller.
    pause
    exit /b 1
)

echo.
echo Running PyInstaller...
pyinstaller MasterHttpRelayVPN.spec --clean --noconfirm

IF ERRORLEVEL 1 (
    echo.
    echo ERROR: PyInstaller build failed.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Build complete: dist\MasterHttpRelayVPN\
echo ============================================================
echo.
echo The dist\MasterHttpRelayVPN\ folder is your distributable.
echo Zip it or create an installer from it.
echo.

REM Optional: Build Inno Setup installer if iscc.exe is available
WHERE iscc >nul 2>&1
IF NOT ERRORLEVEL 1 (
    echo Building Inno Setup installer...
    IF EXIST "installer\setup.iss" (
        iscc installer\setup.iss
        echo Installer created in installer\Output\
    )
)

pause
