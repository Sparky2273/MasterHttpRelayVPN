"""
Unit tests for core.tun_adapter (non-root-safe, mocked subprocess).
"""

import platform
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.tun_adapter as tun

_OS = platform.system()


# ── is_elevation_available ────────────────────────────────────────────────────

@pytest.mark.skipif(_OS != "Windows", reason="Windows-only")
def test_elevation_windows_admin():
    with patch("ctypes.windll.shell32.IsUserAnAdmin", return_value=1):
        assert tun.is_elevation_available() is True


@pytest.mark.skipif(_OS != "Windows", reason="Windows-only")
def test_elevation_windows_not_admin():
    with patch("ctypes.windll.shell32.IsUserAnAdmin", return_value=0):
        assert tun.is_elevation_available() is False


@pytest.mark.skipif(_OS == "Windows", reason="Unix-only")
def test_elevation_unix_root(monkeypatch):
    monkeypatch.setattr(tun.os, "geteuid", lambda: 0)
    assert tun.is_elevation_available() is True


@pytest.mark.skipif(_OS == "Windows", reason="Unix-only")
def test_elevation_unix_not_root(monkeypatch):
    monkeypatch.setattr(tun.os, "geteuid", lambda: 1000)
    assert tun.is_elevation_available() is False


# ── tun2socks_available ───────────────────────────────────────────────────────

def test_tun2socks_not_available(tmp_path, monkeypatch):
    monkeypatch.setattr(tun, "_BIN_DIR", tmp_path)
    assert tun.tun2socks_available() is False


def test_tun2socks_available_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(tun, "_BIN_DIR", tmp_path)
    monkeypatch.setattr(tun, "_OS", "Windows")
    (tmp_path / "tun2socks.exe").touch()
    assert tun.tun2socks_available() is True


def test_tun2socks_available_linux(tmp_path, monkeypatch):
    monkeypatch.setattr(tun, "_BIN_DIR", tmp_path)
    monkeypatch.setattr(tun, "_OS", "Linux")
    (tmp_path / "tun2socks").touch()
    assert tun.tun2socks_available() is True


# ── TunAdapter.stop (no-op when not running) ──────────────────────────────────

def test_stop_when_not_running():
    adapter = tun.TunAdapter(socks5_port=1080)
    adapter.stop()   # Should not raise


def test_is_running_false_initially():
    adapter = tun.TunAdapter()
    assert adapter.is_running is False


# ── TunAdapter.start raises FileNotFoundError when binary missing ─────────────

def test_start_raises_file_not_found_linux(tmp_path, monkeypatch):
    monkeypatch.setattr(tun, "_BIN_DIR", tmp_path)
    monkeypatch.setattr(tun, "_OS", "Linux")

    # Root check — pretend we're root
    monkeypatch.setattr(tun.os, "geteuid", lambda: 0)

    adapter = tun.TunAdapter()
    with pytest.raises(FileNotFoundError, match="tun2socks"):
        adapter.start()


def test_start_raises_permission_error_linux(tmp_path, monkeypatch):
    monkeypatch.setattr(tun, "_BIN_DIR", tmp_path)
    monkeypatch.setattr(tun, "_OS", "Linux")
    (tmp_path / "tun2socks").touch()

    # Not root
    monkeypatch.setattr(tun.os, "geteuid", lambda: 1000)

    adapter = tun.TunAdapter()
    with pytest.raises(PermissionError, match="root"):
        adapter.start()


# ── TunAdapter.start (mocked subprocess) ─────────────────────────────────────

def test_start_linux_launches_subprocess(tmp_path, monkeypatch):
    monkeypatch.setattr(tun, "_BIN_DIR", tmp_path)
    monkeypatch.setattr(tun, "_OS", "Linux")
    bin_path = tmp_path / "tun2socks"
    bin_path.touch()
    bin_path.chmod(0o755)

    monkeypatch.setattr(tun.os, "geteuid", lambda: 0)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    with patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
         patch("time.sleep"), \
         patch.object(tun, "_run_cmd", return_value=True):
        adapter = tun.TunAdapter(socks5_port=1080)
        adapter.start()

    assert mock_popen.called
    cmd = mock_popen.call_args[0][0]
    assert "tun2socks" in cmd[0]
    assert "socks5://127.0.0.1:1080" in " ".join(cmd)
    assert adapter.is_running is True


def test_stop_terminates_process(tmp_path, monkeypatch):
    monkeypatch.setattr(tun, "_BIN_DIR", tmp_path)
    monkeypatch.setattr(tun, "_OS", "Linux")
    bin_path = tmp_path / "tun2socks"
    bin_path.touch()
    monkeypatch.setattr(tun.os, "geteuid", lambda: 0)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    with patch("subprocess.Popen", return_value=mock_proc), \
         patch("time.sleep"), \
         patch.object(tun, "_run_cmd", return_value=True):
        adapter = tun.TunAdapter()
        adapter.start()
        adapter.stop()

    mock_proc.terminate.assert_called_once()
    assert adapter.is_running is False
