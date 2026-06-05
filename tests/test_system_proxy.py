"""
Unit tests for core.system_proxy.

Platform-specific tests are skipped automatically when not running on
the relevant OS.  The Linux tests mock subprocess so they work on any
CI machine.
"""

import platform
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.system_proxy as sp

_OS = platform.system()


# ── Helper ────────────────────────────────────────────────────────────────────

def _mock_run_ok():
    result = MagicMock()
    result.returncode = 0
    result.stdout = ""
    result.stderr = ""
    return result


def _mock_run_fail():
    result = MagicMock()
    result.returncode = 1
    result.stdout = ""
    result.stderr = "error"
    return result


# ── _run_cmd ──────────────────────────────────────────────────────────────────

def test_run_cmd_success():
    with patch("subprocess.run", return_value=_mock_run_ok()):
        assert sp._run_cmd(["echo", "hello"]) is True


def test_run_cmd_failure():
    with patch("subprocess.run", return_value=_mock_run_fail()):
        assert sp._run_cmd(["false"]) is False


def test_run_cmd_exception():
    with patch("subprocess.run", side_effect=OSError("no such file")):
        assert sp._run_cmd(["nonexistent_cmd"]) is False


# ── Linux ─────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(_OS != "Linux", reason="Linux-only")
def test_linux_detect_de_gnome(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    assert sp._detect_de() == "gnome"


@pytest.mark.skipif(_OS != "Linux", reason="Linux-only")
def test_linux_detect_de_kde(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    assert sp._detect_de() == "kde"


def test_linux_set_gsettings_calls_correct_commands():
    """Verify _gsettings_set issues the right gsettings commands."""
    calls = []
    def _fake_run(cmd, **kw):
        calls.append(cmd)
        r = MagicMock()
        r.returncode = 0
        return r

    with patch("subprocess.run", side_effect=_fake_run):
        sp._gsettings_set("127.0.0.1", 8085)

    # Should set mode=manual and http/https host+port
    cmd_strs = [" ".join(c) for c in calls]
    assert any("mode" in s and "manual" in s for s in cmd_strs)
    assert any("http" in s and "127.0.0.1" in s for s in cmd_strs)
    assert any("8085" in s for s in cmd_strs)


def test_linux_clear_gsettings():
    with patch("subprocess.run", return_value=_mock_run_ok()) as mock_run:
        sp._gsettings_clear()
        args = mock_run.call_args[0][0]
        assert "none" in args


# ── Windows ───────────────────────────────────────────────────────────────────

@pytest.mark.skipif(_OS != "Windows", reason="Windows-only")
def test_win_set_proxy():
    import winreg
    with patch("winreg.OpenKey"), \
         patch("winreg.SetValueEx"), \
         patch.object(sp, "_win_notify"):
        result = sp._win_set("127.0.0.1", 8085)
    assert result is True


@pytest.mark.skipif(_OS != "Windows", reason="Windows-only")
def test_win_clear_proxy():
    import winreg
    with patch("winreg.OpenKey"), \
         patch("winreg.SetValueEx"), \
         patch("winreg.DeleteValue"), \
         patch.object(sp, "_win_notify"):
        result = sp._win_clear()
    assert result is True


@pytest.mark.skipif(_OS != "Windows", reason="Windows-only")
def test_win_get_returns_none_when_disabled():
    import winreg
    mock_key = MagicMock()
    mock_key.__enter__ = lambda s: s
    mock_key.__exit__ = MagicMock(return_value=False)

    def _qve(key, name):
        if name == "ProxyEnable":
            return (0, winreg.REG_DWORD)
        raise FileNotFoundError

    with patch("winreg.OpenKey", return_value=mock_key), \
         patch("winreg.QueryValueEx", side_effect=_qve):
        result = sp._win_get()
    assert result is None


@pytest.mark.skipif(_OS != "Windows", reason="Windows-only")
def test_win_get_returns_dict_when_enabled():
    import winreg
    mock_key = MagicMock()
    mock_key.__enter__ = lambda s: s
    mock_key.__exit__ = MagicMock(return_value=False)

    def _qve(key, name):
        if name == "ProxyEnable":
            return (1, winreg.REG_DWORD)
        if name == "ProxyServer":
            return ("127.0.0.1:8085", winreg.REG_SZ)
        raise FileNotFoundError

    with patch("winreg.OpenKey", return_value=mock_key), \
         patch("winreg.QueryValueEx", side_effect=_qve):
        result = sp._win_get()
    assert result == {"host": "127.0.0.1", "port": 8085}


# ── Public API smoke tests (no side-effects) ──────────────────────────────────

def test_set_system_proxy_unsupported_os(monkeypatch):
    """Should log warning and return False for unknown OS."""
    monkeypatch.setattr(sp, "_OS", "HaikuOS")
    result = sp.set_system_proxy("127.0.0.1", 8085)
    assert result is False


def test_clear_system_proxy_unsupported_os(monkeypatch):
    monkeypatch.setattr(sp, "_OS", "HaikuOS")
    result = sp.clear_system_proxy()
    assert result is False


def test_get_system_proxy_unsupported_os(monkeypatch):
    monkeypatch.setattr(sp, "_OS", "HaikuOS")
    result = sp.get_system_proxy()
    assert result is None
