"""
system_proxy.py — Cross-platform OS-level system proxy management.

Supports Windows, Linux (GNOME + KDE), and macOS.  All functions return
``True`` on success and ``False`` (or raise) on failure.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import logging

log = logging.getLogger("SystemProxy")

_OS = platform.system()  # "Windows", "Linux", "Darwin"


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def set_system_proxy(host: str, port: int) -> bool:
    """
    Enable the OS-level HTTP/HTTPS system proxy.

    Parameters
    ----------
    host :
        Proxy host, typically ``"127.0.0.1"``.
    port :
        Proxy port, e.g. ``8085``.

    Returns
    -------
    bool
        ``True`` on success, ``False`` on failure.
    """
    try:
        if _OS == "Windows":
            return _win_set(host, port)
        elif _OS == "Linux":
            return _linux_set(host, port)
        elif _OS == "Darwin":
            return _mac_set(host, port)
        else:
            log.warning("set_system_proxy: unsupported OS '%s'", _OS)
            return False
    except Exception as exc:
        log.error("set_system_proxy failed: %s", exc)
        return False


def clear_system_proxy() -> bool:
    """
    Disable the OS-level system proxy.

    Returns
    -------
    bool
        ``True`` on success, ``False`` on failure.
    """
    try:
        if _OS == "Windows":
            return _win_clear()
        elif _OS == "Linux":
            return _linux_clear()
        elif _OS == "Darwin":
            return _mac_clear()
        else:
            log.warning("clear_system_proxy: unsupported OS '%s'", _OS)
            return False
    except Exception as exc:
        log.error("clear_system_proxy failed: %s", exc)
        return False


def get_system_proxy() -> dict | None:
    """
    Return the current OS-level proxy settings.

    Returns
    -------
    dict or None
        ``{"host": str, "port": int}`` if a proxy is set, else ``None``.
    """
    try:
        if _OS == "Windows":
            return _win_get()
        elif _OS == "Linux":
            return _linux_get()
        elif _OS == "Darwin":
            return _mac_get()
    except Exception as exc:
        log.error("get_system_proxy failed: %s", exc)
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Windows implementation
# ──────────────────────────────────────────────────────────────────────────────

def _win_set(host: str, port: int) -> bool:
    import winreg, ctypes  # noqa: F401
    key = _win_open_key(winreg.KEY_SET_VALUE)
    if key is None:
        return False
    with key:
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"{host}:{port}")
        winreg.SetValueEx(
            key, "ProxyOverride", 0, winreg.REG_SZ,
            "<local>;localhost;127.0.0.1;::1"
        )
    _win_notify()
    log.info("Windows system proxy set to %s:%d", host, port)
    return True


def _win_clear() -> bool:
    import winreg
    key = _win_open_key(winreg.KEY_SET_VALUE)
    if key is None:
        return False
    with key:
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
        # Remove ProxyServer value; ignore if absent
        try:
            winreg.DeleteValue(key, "ProxyServer")
        except FileNotFoundError:
            pass
    _win_notify()
    log.info("Windows system proxy cleared")
    return True


def _win_get() -> dict | None:
    import winreg
    key = _win_open_key(winreg.KEY_QUERY_VALUE)
    if key is None:
        return None
    with key:
        try:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not enabled:
                return None
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
            host, _, portstr = server.partition(":")
            return {"host": host, "port": int(portstr)} if portstr else None
        except FileNotFoundError:
            return None


def _win_open_key(access):
    """Open the Internet Settings registry key, or return None on failure."""
    try:
        import winreg
        return winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            0,
            access,
        )
    except OSError as exc:
        log.error("Cannot open registry key: %s", exc)
        return None


def _win_notify() -> None:
    """Notify running applications of the proxy change."""
    try:
        import ctypes
        # INTERNET_OPTION_SETTINGS_CHANGED = 95
        ctypes.windll.wininet.InternetSetOptionW(0, 95, None, 0)  # type: ignore[attr-defined]
        # INTERNET_OPTION_REFRESH = 37
        ctypes.windll.wininet.InternetSetOptionW(0, 37, None, 0)  # type: ignore[attr-defined]
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Linux implementation
# ──────────────────────────────────────────────────────────────────────────────

def _linux_set(host: str, port: int) -> bool:
    ok = True
    de = _detect_de()

    if de in ("gnome", "unity", "pantheon"):
        ok &= _gsettings_set(host, port)
    elif de == "kde":
        ok &= _kde_set(host, port)
    else:
        # Best-effort: try gsettings if available, fall through silently
        if shutil.which("gsettings"):
            ok &= _gsettings_set(host, port)

    log.info("Linux system proxy set to %s:%d (DE=%s)", host, port, de)
    return ok


def _linux_clear() -> bool:
    ok = True
    de = _detect_de()
    if de in ("gnome", "unity", "pantheon"):
        ok &= _gsettings_clear()
    elif de == "kde":
        ok &= _kde_clear()
    else:
        if shutil.which("gsettings"):
            ok &= _gsettings_clear()
    log.info("Linux system proxy cleared (DE=%s)", de)
    return ok


def _linux_get() -> dict | None:
    if shutil.which("gsettings"):
        try:
            mode = _run_out(["gsettings", "get", "org.gnome.system.proxy", "mode"])
            if "'manual'" not in mode:
                return None
            host = _run_out(["gsettings", "get", "org.gnome.system.proxy.http", "host"]).strip("' \n")
            port = _run_out(["gsettings", "get", "org.gnome.system.proxy.http", "port"]).strip()
            if host and port:
                return {"host": host, "port": int(port)}
        except Exception:
            pass
    return None


def _gsettings_set(host: str, port: int) -> bool:
    cmds = [
        ["gsettings", "set", "org.gnome.system.proxy", "mode", "manual"],
        ["gsettings", "set", "org.gnome.system.proxy.http", "host", host],
        ["gsettings", "set", "org.gnome.system.proxy.http", "port", str(port)],
        ["gsettings", "set", "org.gnome.system.proxy.https", "host", host],
        ["gsettings", "set", "org.gnome.system.proxy.https", "port", str(port)],
        ["gsettings", "set", "org.gnome.system.proxy", "ignore-hosts",
         "['localhost', '127.0.0.0/8', '::1']"],
    ]
    return _run_all(cmds)


def _gsettings_clear() -> bool:
    return _run_cmd(["gsettings", "set", "org.gnome.system.proxy", "mode", "none"])


def _kde_set(host: str, port: int) -> bool:
    if not shutil.which("kwriteconfig5"):
        return False
    cfg = os.path.expanduser("~/.config/kioslaverc")
    cmds = [
        ["kwriteconfig5", "--file", cfg, "--group", "Proxy Settings",
         "--key", "ProxyType", "1"],
        ["kwriteconfig5", "--file", cfg, "--group", "Proxy Settings",
         "--key", "httpProxy", f"http://{host} {port}"],
        ["kwriteconfig5", "--file", cfg, "--group", "Proxy Settings",
         "--key", "httpsProxy", f"http://{host} {port}"],
    ]
    return _run_all(cmds)


def _kde_clear() -> bool:
    if not shutil.which("kwriteconfig5"):
        return False
    import os
    cfg = os.path.expanduser("~/.config/kioslaverc")
    return _run_cmd(
        ["kwriteconfig5", "--file", cfg, "--group", "Proxy Settings", "--key", "ProxyType", "0"]
    )


def _detect_de() -> str:
    """Return a lowercase desktop environment name."""
    import os
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    session = os.environ.get("DESKTOP_SESSION", "").lower()
    for token in (desktop, session):
        if "gnome" in token:
            return "gnome"
        if "kde" in token or "plasma" in token:
            return "kde"
        if "unity" in token:
            return "unity"
        if "pantheon" in token:
            return "pantheon"
    return "unknown"


# ──────────────────────────────────────────────────────────────────────────────
# macOS implementation
# ──────────────────────────────────────────────────────────────────────────────

def _mac_set(host: str, port: int) -> bool:
    iface = _mac_active_interface()
    if not iface:
        return False
    port_str = str(port)
    cmds = [
        ["networksetup", "-setwebproxy", iface, host, port_str],
        ["networksetup", "-setsecurewebproxy", iface, host, port_str],
        ["networksetup", "-setwebproxystate", iface, "on"],
        ["networksetup", "-setsecurewebproxystate", iface, "on"],
    ]
    ok = _run_all(cmds)
    log.info("macOS system proxy set to %s:%d (interface=%s)", host, port, iface)
    return ok


def _mac_clear() -> bool:
    iface = _mac_active_interface()
    if not iface:
        return False
    cmds = [
        ["networksetup", "-setwebproxystate", iface, "off"],
        ["networksetup", "-setsecurewebproxystate", iface, "off"],
    ]
    return _run_all(cmds)


def _mac_get() -> dict | None:
    iface = _mac_active_interface()
    if not iface:
        return None
    try:
        out = _run_out(["networksetup", "-getwebproxy", iface])
        enabled = "Enabled: Yes" in out
        if not enabled:
            return None
        host_line = [l for l in out.splitlines() if l.startswith("Server:")]
        port_line = [l for l in out.splitlines() if l.startswith("Port:")]
        if host_line and port_line:
            return {
                "host": host_line[0].split(":", 1)[1].strip(),
                "port": int(port_line[0].split(":", 1)[1].strip()),
            }
    except Exception:
        pass
    return None


def _mac_active_interface() -> str | None:
    try:
        out = _run_out(["networksetup", "-listallnetworkservices"])
        for line in out.splitlines():
            line = line.strip()
            if line and not line.startswith("*") and line != "An asterisk (*) denotes that a network service is disabled.":
                # Return first enabled service
                return line
    except Exception:
        pass
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────────

def _run_cmd(cmd: list[str]) -> bool:
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        return result.returncode == 0
    except Exception as exc:
        log.debug("Command %s failed: %s", cmd, exc)
        return False


def _run_all(cmds: list[list[str]]) -> bool:
    return all(_run_cmd(c) for c in cmds)


def _run_out(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    return result.stdout


# Import os at module level so it's available in helpers
import os  # noqa: E402
