"""
tun_adapter.py — TUN virtual adapter management with split-tunnelling.

Root problem (Windows): without exclusion routes for the relay server IP,
the proxy engine's own outbound HTTPS connection goes *through* the TUN
interface, which hands it back to tun2socks → SOCKS5 → proxy engine →
TUN again — an infinite routing loop.  The adapter shows "ON" in the UI
but nothing flows.

Fix: before adding the 0.0.0.0/0 via-TUN default route, we:
  1. Detect the real (pre-TUN) default gateway.
  2. Resolve the relay IP(s) from config (google_ip, front_domains,
     exit_node URL).
  3. Add specific /32 host routes for those IPs via the real gateway.
  4. Get the TUN adapter's Windows interface index.
  5. Add 0.0.0.0/0 via-TUN using PowerShell New-NetRoute with an explicit
     -InterfaceIndex so Windows cannot pick the wrong adapter.
  6. Set DNS on the TUN interface so DNS queries are also proxied.

Critical bug that was fixed: route add 0.0.0.0/0 without specifying the
interface index caused Windows to bind the default route to the WiFi
adapter (192.168.1.10) instead of the TUN adapter (198.18.0.1), because
the TUN network was not yet fully registered when the command ran.
The symptom: the adapter appeared in Network Connections and the routing
table showed "198.18.0.1 via 192.168.1.10" — traffic was silently dropped
because the WiFi router has no path to 198.18.0.1.

On stop, all TUN routes and exclusion routes are removed cleanly.

UI-FREEZE FIX: start() and stop() are designed to be called from a
background QThread (TunWorkerThread in proxy_mode_tab.py), NOT from the
GUI thread.  They are intentionally synchronous/blocking — callers must
run them off-thread.

Supported platforms: Windows (primary), Linux, macOS (best-effort).
"""

from __future__ import annotations

import collections
import ipaddress
import logging
import os
import platform
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

log = logging.getLogger("TUN")

_OS = platform.system()

# ── Resolve GUI root correctly in source and PyInstaller frozen mode ──────────
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _GUI_ROOT = Path(sys._MEIPASS)
else:
    _GUI_ROOT = Path(__file__).resolve().parent.parent

_BIN_DIR = _GUI_ROOT / "assets" / "bin"

# ── TUN interface constants ───────────────────────────────────────────────────
TUN_IFACE_WIN  = "MasterVPN"
TUN_IP_WIN     = "198.18.0.1"
TUN_MASK_WIN   = "255.255.0.0"   # /16
TUN_GW_WIN     = "198.18.0.1"   # gateway = interface IP (standard for TUN)
TUN_METRIC_WIN = "1"             # route metric (effective = route + iface metric)
TUN_MTU_WIN    = "1500"          # MTU for the TUN interface

TUN_IFACE_LINUX = "tun0"
TUN_IP_LINUX    = "10.0.0.1"
TUN_CIDR_LINUX  = "10.0.0.0/24"

SOCKS5_HOST = "127.0.0.1"
SOCKS5_PORT = 1080

# DNS servers to assign to the TUN interface (queries will be proxied)
TUN_DNS_PRIMARY   = "8.8.8.8"
TUN_DNS_SECONDARY = "1.1.1.1"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_valid_ipv4(addr: str) -> bool:
    """Return True if *addr* is a valid dotted-quad IPv4 address."""
    try:
        ipaddress.IPv4Address(addr)
        return True
    except ValueError:
        return False


def _get_default_gateway_windows() -> str:
    """
    Return the current best (lowest-metric) IPv4 default gateway,
    excluding the TUN interface so we capture the *real* upstream
    gateway even if called after TUN routes have been partially set up.

    Tries PowerShell first (reliable), falls back to ``route print``.
    """
    # Method 1 — PowerShell Get-NetRoute (Windows 8+ / Server 2012+)
    try:
        ps_script = (
            "Get-NetRoute -DestinationPrefix '0.0.0.0/0' "
            f"| Where-Object {{ $_.NextHop -ne '0.0.0.0' "
            f"  -and $_.InterfaceAlias -ne '{TUN_IFACE_WIN}' }} "
            "| Sort-Object RouteMetric "
            "| Select-Object -First 1 -ExpandProperty NextHop"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True, timeout=15, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        gw = result.stdout.strip()
        if gw and _is_valid_ipv4(gw) and gw != "0.0.0.0":
            log.debug("Default gateway (PowerShell): %s", gw)
            return gw
    except Exception as exc:
        log.debug("PowerShell gateway lookup failed: %s", exc)

    # Method 2 — parse ``route print 0.0.0.0``
    try:
        result = subprocess.run(
            ["route", "print", "0.0.0.0"],
            capture_output=True, timeout=10, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        best_gw     = ""
        best_metric = 9999
        in_section  = False
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if "Active Routes" in line:
                in_section = True
                continue
            if in_section and stripped.startswith("0.0.0.0"):
                parts = stripped.split()
                # format: network  mask  gateway  iface  metric
                if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                    gw = parts[2]
                    try:
                        metric = int(parts[4])
                    except (ValueError, IndexError):
                        metric = 9999
                    if (
                        _is_valid_ipv4(gw)
                        and gw not in ("0.0.0.0", TUN_GW_WIN)
                        and metric < best_metric
                    ):
                        best_gw     = gw
                        best_metric = metric
        if best_gw:
            log.debug("Default gateway (route print): %s", best_gw)
            return best_gw
    except Exception as exc:
        log.debug("route print gateway lookup failed: %s", exc)

    return ""


def _get_tun_if_index_windows(iface_name: str) -> str:
    """
    Return the Windows interface index (as a string) for *iface_name*.

    Uses PowerShell Get-NetAdapter first (reliable), then falls back to
    parsing 'route print' interface list.

    Returns '' if the index cannot be determined.
    """
    # Method 1: PowerShell Get-NetAdapter (returns integer ifIndex)
    try:
        ps = (
            f"$a = Get-NetAdapter | Where-Object {{ $_.Name -eq '{iface_name}' }}; "
            f"if ($a) {{ $a.ifIndex }}"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, timeout=10, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        idx = r.stdout.strip()
        if idx and idx.isdigit():
            log.debug("TUN interface index (PowerShell Get-NetAdapter): %s", idx)
            return idx
    except Exception as exc:
        log.debug("PowerShell Get-NetAdapter ifIndex failed: %s", exc)

    # Method 2: parse 'route print' interface list section
    # Lines look like:  "49...........................tun2socks Tunnel"
    # or:               "17...3c 52 a1 08 26 ec ......TP-Link ..."
    try:
        r2 = subprocess.run(
            ["route", "print"],
            capture_output=True, timeout=10, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        in_iface_list = False
        for line in r2.stdout.splitlines():
            if "Interface List" in line:
                in_iface_list = True
                continue
            if in_iface_list and line.strip().startswith("="):
                break
            if in_iface_list and line.strip():
                stripped = line.strip()
                # Split on first non-digit sequence to get index
                digits = ""
                for ch in stripped:
                    if ch.isdigit():
                        digits += ch
                    else:
                        break
                if digits:
                    rest = stripped[len(digits):].lstrip(". ").lower()
                    # Match by adapter name or tun2socks description
                    if (iface_name.lower() in rest
                            or "tun2socks" in rest
                            or "mastervpn" in rest.replace(" ", "")):
                        log.debug("TUN interface index (route print): %s", digits)
                        return digits
    except Exception as exc:
        log.debug("route print interface index lookup failed: %s", exc)

    return ""


def _wait_for_tun_network_windows(tun_ip: str = TUN_IP_WIN,
                                   timeout: float = 10.0) -> bool:
    """
    Wait until the TUN network (198.18.x.x) appears in the Windows IPv4
    routing table.  This confirms that the netsh IP assignment has
    propagated to the routing stack before we add the default route.

    Returns True when the network is detected, False on timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = subprocess.run(
                ["route", "print", "198.18.0.0"],
                capture_output=True, timeout=5, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if tun_ip in r.stdout:
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def _add_default_route_windows(tun_if_index: str) -> bool:
    """
    Add the 0.0.0.0/0 default route through the TUN adapter.

    Uses three methods in order of reliability:

    1. PowerShell New-NetRoute with explicit -InterfaceIndex — most
       reliable; guarantees the route is bound to the correct adapter.
    2. ``route add`` with explicit IF parameter — reliable fallback.
    3. ``route add`` without IF — last resort; may bind to wrong adapter.

    Returns True if any method succeeds.
    """
    # ── Method 1: PowerShell New-NetRoute ─────────────────────────────────────
    if tun_if_index:
        ps_cmd = (
            f"New-NetRoute "
            f"-InterfaceIndex {tun_if_index} "
            f"-DestinationPrefix '0.0.0.0/0' "
            f"-NextHop '{TUN_GW_WIN}' "
            f"-RouteMetric 1 "
            f"-PolicyStore ActiveStore "
            f"-ErrorAction SilentlyContinue"
        )
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True, timeout=15, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if r.returncode == 0:
                log.info(
                    "Default TUN route added via PowerShell New-NetRoute "
                    "(InterfaceIndex=%s) ✓", tun_if_index
                )
                return True
            else:
                stderr = (r.stdout + r.stderr).strip()
                log.debug(
                    "PowerShell New-NetRoute failed (rc=%d): %s",
                    r.returncode, stderr[:300],
                )
        except Exception as exc:
            log.debug("PowerShell New-NetRoute exception: %s", exc)

    # ── Method 2: route add with explicit IF ──────────────────────────────────
    if tun_if_index:
        cmd = [
            "route", "add", "0.0.0.0", "mask", "0.0.0.0",
            TUN_GW_WIN, "metric", TUN_METRIC_WIN, "IF", tun_if_index,
        ]
        if _run_cmd(cmd):
            log.info(
                "Default TUN route added via 'route add IF=%s' ✓", tun_if_index
            )
            return True

    # ── Method 3: route add without IF (last resort) ──────────────────────────
    log.warning(
        "Adding default TUN route WITHOUT explicit interface index — "
        "Windows may pick the wrong adapter.  Resolve this by ensuring "
        "the TUN network 198.18.x.x is fully registered before this call."
    )
    cmd = [
        "route", "add", "0.0.0.0", "mask", "0.0.0.0",
        TUN_GW_WIN, "metric", TUN_METRIC_WIN,
    ]
    if _run_cmd(cmd):
        log.info("Default TUN route added via 'route add' (no IF) ✓")
        return True

    return False


def _remove_default_route_windows() -> None:
    """
    Remove the TUN 0.0.0.0/0 default route.
    Tries PowerShell Remove-NetRoute first, then route delete.
    """
    # Method 1: PowerShell Remove-NetRoute
    ps_cmd = (
        f"Remove-NetRoute "
        f"-DestinationPrefix '0.0.0.0/0' "
        f"-NextHop '{TUN_GW_WIN}' "
        f"-Confirm:$false "
        f"-ErrorAction SilentlyContinue"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as exc:
        log.debug("PowerShell Remove-NetRoute failed: %s", exc)

    # Method 2: route delete (belt-and-braces)
    _run_cmd(["route", "delete", "0.0.0.0", "mask", "0.0.0.0", TUN_GW_WIN])

    # Method 3: try to delete any stale route still bound to TUN GW
    try:
        r = subprocess.run(
            ["route", "print", "0.0.0.0"],
            capture_output=True, timeout=8, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        for line in r.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("0.0.0.0") and TUN_GW_WIN in stripped:
                parts = stripped.split()
                if len(parts) >= 4:
                    iface_ip = parts[3]
                    _run_cmd([
                        "route", "delete", "0.0.0.0", "mask", "0.0.0.0",
                        TUN_GW_WIN, iface_ip,
                    ])
    except Exception:
        pass


def _get_exclusion_ips(config: Optional[dict]) -> list[str]:
    """
    Return a list of IPv4 addresses that MUST bypass the TUN interface
    (the relay server / upstream IPs the proxy engine dials directly).
    """
    if not config:
        return []

    ips: set[str] = set()

    # ── Primary relay IP (domain fronting via Google infra) ──────────
    google_ip = str(config.get("google_ip", "")).strip()
    if google_ip and _is_valid_ipv4(google_ip):
        ips.add(google_ip)
        log.debug("Exclusion: google_ip = %s", google_ip)

    # ── Front domains (may resolve to different IPs than google_ip) ───
    for domain in config.get("front_domains", []):
        domain = str(domain).strip().lstrip(".")
        if not domain:
            continue
        try:
            addr = socket.gethostbyname(domain)
            if addr and _is_valid_ipv4(addr):
                ips.add(addr)
                log.debug("Exclusion: front_domain %s → %s", domain, addr)
        except OSError:
            pass

    # ── Exit node (Cloudflare Worker / VPS) ──────────────────────────
    exit_node = config.get("exit_node", {})
    if exit_node and exit_node.get("enabled"):
        url = str(exit_node.get("url", "")).strip()
        if url:
            try:
                host = urlparse(url).hostname or ""
                host = host.strip()
                if host:
                    if _is_valid_ipv4(host):
                        ips.add(host)
                        log.debug("Exclusion: exit_node IP = %s", host)
                    else:
                        resolved = socket.getaddrinfo(host, None, socket.AF_INET)
                        for entry in resolved:
                            addr = entry[4][0]
                            if addr and _is_valid_ipv4(addr):
                                ips.add(addr)
                                log.debug("Exclusion: exit_node %s → %s", host, addr)
            except Exception as exc:
                log.debug("exit_node host resolution failed: %s", exc)

    return list(ips)


def _wait_for_adapter_windows(iface_name: str, timeout: float = 20.0,
                               output_buf: Optional[collections.deque] = None,
                               proc: Optional[subprocess.Popen] = None,
                               on_progress: Optional[Callable] = None) -> bool:
    """
    Poll until the WinTUN adapter named *iface_name* appears.

    Uses multiple detection methods:
      1. PowerShell Get-NetAdapter (most reliable for WinTUN)
      2. netsh interface show interface (fallback)

    Also monitors *proc* for early exit — if tun2socks crashes we stop
    waiting immediately and return False.

    Returns True on success, False on timeout or process crash.
    """
    deadline = time.monotonic() + timeout
    last_progress_t = 0.0
    elapsed = 0

    while time.monotonic() < deadline:
        elapsed = int(time.monotonic() - (deadline - timeout))

        # ── Progress heartbeat every 3 seconds ────────────────────────
        now = time.monotonic()
        if on_progress and (now - last_progress_t) >= 3.0:
            last_progress_t = now
            on_progress(f"Waiting for '{iface_name}' adapter… ({elapsed}s)")

        # ── Check if tun2socks exited prematurely ──────────────────────
        if proc is not None and proc.poll() is not None:
            log.warning("tun2socks process exited (rc=%s) while waiting for adapter",
                        proc.returncode)
            return False

        # ── Method 1: PowerShell Get-NetAdapter ───────────────────────
        try:
            ps = (
                f"$a = Get-NetAdapter | Where-Object {{ $_.Name -eq '{iface_name}' }}; "
                f"if ($a) {{ 'FOUND' }} else {{ 'NOT_FOUND' }}"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True, timeout=6, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if "FOUND" in r.stdout:
                log.debug("Adapter '%s' found via PowerShell Get-NetAdapter", iface_name)
                return True
        except Exception:
            pass

        # ── Method 2: netsh interface show interface ───────────────────
        try:
            r2 = subprocess.run(
                ["netsh", "interface", "show", "interface", iface_name],
                capture_output=True, timeout=5, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if r2.returncode == 0 and iface_name in r2.stdout:
                log.debug("Adapter '%s' found via netsh", iface_name)
                return True
        except Exception:
            pass

        time.sleep(0.75)

    return False


def _check_socks5_port(host: str = SOCKS5_HOST, port: int = SOCKS5_PORT,
                       timeout: float = 2.0) -> bool:
    """
    Return True if something is listening on the SOCKS5 port.
    Quick TCP connect check — does not authenticate.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ── Orphan cleanup ────────────────────────────────────────────────────────────

def kill_orphaned_processes() -> None:
    """
    Kill any running tun2socks.exe processes from previous (orphaned)
    sessions.  Called at start of TUN enable to ensure a clean slate.
    Also cleans up stale TUN routes left over from previous sessions.
    """
    if _OS != "Windows":
        return

    # Kill orphaned tun2socks processes
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/IM", "tun2socks.exe"],
            capture_output=True, timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            log.info("Killed orphaned tun2socks.exe process(es)")
            time.sleep(0.5)  # Brief pause after kill
    except Exception as exc:
        log.debug("taskkill tun2socks.exe: %s", exc)

    # Clean up any stale TUN default route (from previous failed sessions)
    try:
        _run_cmd(["route", "delete", "0.0.0.0", "mask", "0.0.0.0", TUN_GW_WIN])
        log.debug("Cleaned up stale TUN default route (if any)")
    except Exception:
        pass


# ── TunAdapter ────────────────────────────────────────────────────────────────

class TunAdapter:
    """
    Manages the TUN virtual network adapter and tun2socks subprocess.

    IMPORTANT: start() and stop() are BLOCKING calls that may take
    15-25 seconds.  Always call them from a background thread, never
    from the Qt GUI thread.

    Parameters
    ----------
    socks5_port : int
        Local SOCKS5 port the proxy engine is listening on.
    config : dict, optional
        Full application config dict.  Used to derive relay-server IPs
        that must bypass the TUN interface (split-tunnelling / exclusion
        routes).
    """

    def __init__(self, socks5_port: int = SOCKS5_PORT,
                 config: Optional[dict] = None) -> None:
        self.socks5_port = socks5_port
        self._config     = config or {}
        self._proc: Optional[subprocess.Popen] = None
        self._running     = False
        self._stderr_thread: Optional[threading.Thread] = None

        # Thread-safe output capture (last 200 lines from tun2socks)
        self._output_buf: collections.deque = collections.deque(maxlen=200)
        self._output_lock = threading.Lock()

        # State saved during _start for use in _stop
        self._real_gateway:  str       = ""
        self._exclusion_ips: list[str] = []
        self._tun_if_index:  str       = ""   # Windows interface index

    @property
    def is_running(self) -> bool:
        """True if tun2socks is alive and the interface is up."""
        if not self._running:
            return False
        if self._proc and self._proc.poll() is not None:
            rc = self._proc.returncode
            log.warning(
                "tun2socks process has exited (rc=%s) — TUN mode is no longer active",
                rc
            )
            self._running = False
        return self._running

    def get_captured_output(self, last_n: int = 50) -> str:
        """Return last *last_n* lines of tun2socks output as a single string."""
        with self._output_lock:
            lines = list(self._output_buf)[-last_n:]
        return "\n".join(lines) if lines else ""

    # ── Public API ────────────────────────────────────────────────────

    def start(self, on_progress: Optional[Callable[[str], None]] = None) -> None:
        """
        Start the TUN adapter.  BLOCKING — call from a background thread.

        Parameters
        ----------
        on_progress : callable(str), optional
            Called with human-readable status messages as startup progresses.
            Safe to forward directly to a Qt signal from a QThread subclass.

        Raises
        ------
        PermissionError  — if not running as administrator/root.
        FileNotFoundError — if tun2socks binary is missing.
        RuntimeError     — for any other setup failure (includes tun2socks output).
        """
        if self.is_running:
            return

        _require_elevation()

        def _progress(msg: str) -> None:
            log.info(msg)
            if on_progress:
                on_progress(msg)

        if _OS == "Windows":
            self._start_windows(_progress)
        elif _OS == "Linux":
            self._start_linux(_progress)
        elif _OS == "Darwin":
            self._start_macos(_progress)
        else:
            raise RuntimeError(f"TUN mode not supported on {_OS}")

        self._running = True
        _progress(f"TUN adapter started (socks5_port={self.socks5_port})")

    def stop(self) -> None:
        """
        Stop the TUN adapter and clean up all routes.
        BLOCKING — call from a background thread.
        """
        log.info("Stopping TUN adapter…")

        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                    self._proc.wait(timeout=3)
                except Exception:
                    pass
            self._proc = None

        if self._stderr_thread and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=2)
        self._stderr_thread = None

        # Kill any orphaned instances that might have survived
        if _OS == "Windows":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", "tun2socks.exe"],
                    capture_output=True, timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except Exception:
                pass

        if _OS == "Windows":
            self._stop_windows()
        elif _OS == "Linux":
            self._stop_linux()

        self._running = False
        log.info("TUN adapter stopped")

    # ── Windows ───────────────────────────────────────────────────────

    def _start_windows(self, progress: Callable[[str], None]) -> None:
        tun2socks  = _BIN_DIR / "tun2socks.exe"
        wintun_dll = _BIN_DIR / "wintun.dll"

        # ── Pre-flight ─────────────────────────────────────────────────
        progress("TUN pre-flight checks…")
        log.info("TUN pre-flight check:")
        log.info("  assets/bin dir : %s (exists=%s)", _BIN_DIR, _BIN_DIR.exists())
        log.info(
            "  tun2socks.exe  : %s (exists=%s, size=%s)",
            tun2socks,
            tun2socks.exists(),
            f"{tun2socks.stat().st_size // 1024} KB" if tun2socks.exists() else "N/A",
        )
        log.info(
            "  wintun.dll     : %s (exists=%s, size=%s)",
            wintun_dll,
            wintun_dll.exists(),
            f"{wintun_dll.stat().st_size // 1024} KB" if wintun_dll.exists() else "N/A",
        )
        log.info("  elevation      : %s", is_elevation_available())

        if not tun2socks.exists():
            raise FileNotFoundError(
                f"tun2socks.exe not found at {tun2socks}.\n"
                "Download from https://github.com/xjasonlyu/tun2socks/releases\n"
                "and rename it to tun2socks.exe, then place it in assets/bin/.\n\n"
                "NOTE: Use tun2socks-windows-amd64.exe (not the -v3 variant)\n"
                "unless you are certain your CPU supports AVX2."
            )
        if not wintun_dll.exists():
            log.warning(
                "wintun.dll not found at %s — tun2socks may fail to create "
                "the virtual adapter.  Download wintun.dll (AMD64) from "
                "https://www.wintun.net and place it in assets/bin/.",
                wintun_dll,
            )

        # ── SOCKS5 port pre-check ──────────────────────────────────────
        log.info("  socks5_port    : %s", self.socks5_port)
        if not _check_socks5_port(SOCKS5_HOST, self.socks5_port):
            log.warning(
                "Nothing is listening on SOCKS5 port %s — "
                "make sure the proxy engine is running before enabling TUN mode.",
                self.socks5_port,
            )

        # ── Kill orphaned tun2socks processes from prior sessions ──────
        progress("Cleaning up any previous tun2socks processes…")
        kill_orphaned_processes()

        # ── Step 1: capture real default gateway BEFORE adding TUN routes
        progress("Detecting real default gateway…")
        real_gw = _get_default_gateway_windows()
        if real_gw:
            log.info("Real default gateway: %s", real_gw)
            progress(f"Real default gateway: {real_gw}")
        else:
            log.warning(
                "Could not detect real default gateway. "
                "Exclusion routes will NOT be added — the proxy engine's relay "
                "connection may be routed through TUN, causing a routing loop."
            )

        # ── Step 2: resolve relay / exclusion IPs from config ──────────
        progress("Resolving relay/exclusion IPs…")
        exclusion_ips = _get_exclusion_ips(self._config)
        if exclusion_ips:
            log.info("Relay/exclusion IPs (will bypass TUN): %s", exclusion_ips)
            progress(f"Exclusion IPs: {', '.join(exclusion_ips)}")
        else:
            log.warning(
                "No exclusion IPs resolved from config. "
                "If google_ip is not set, the proxy engine cannot reach "
                "its relay through TUN mode."
            )

        # ── Step 3: launch tun2socks ────────────────────────────────────
        cmd = [
            str(tun2socks),
            "-device",   f"tun://{TUN_IFACE_WIN}",
            "-proxy",    f"socks5://{SOCKS5_HOST}:{self.socks5_port}",
            # Use 'info' so we capture startup messages (adapter creation, errors)
            "-loglevel", "info",
        ]
        progress("Launching tun2socks…")
        log.info("Launching tun2socks: %s", " ".join(cmd))
        log.info("Working directory : %s", _BIN_DIR)

        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)

        self._proc = subprocess.Popen(
            cmd,
            env=env,
            cwd=str(_BIN_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        # ── Step 4: start output reader IMMEDIATELY ─────────────────────
        # Critical: we need to read tun2socks output NOW so:
        #  a) We capture any startup errors/crashes
        #  b) The pipe buffer doesn't fill up and block tun2socks
        self._stderr_thread = threading.Thread(
            target=self._read_proc_output, daemon=True, name="tun2socks-reader"
        )
        self._stderr_thread.start()

        # Brief pause to let tun2socks begin initialization
        time.sleep(0.5)

        # ── Step 5: check if it crashed immediately ─────────────────────
        if self._proc.poll() is not None:
            time.sleep(0.3)  # Give reader thread a moment to capture output
            captured = self.get_captured_output()
            rc = self._proc.returncode
            log.error(
                "tun2socks.exe exited immediately (code %d).\n"
                "  Output  : %s",
                rc, captured or "<no output>",
            )
            raise RuntimeError(
                f"tun2socks.exe exited immediately (code {rc}).\n\n"
                f"tun2socks output:\n{captured or '<no output>'}\n\n"
                "Common causes:\n"
                "  1. wintun.dll missing or wrong architecture (need AMD64)\n"
                "  2. Not running as Administrator\n"
                "  3. Antivirus blocking tun2socks.exe or wintun.dll\n"
                "  4. Stale 'MasterVPN' adapter in Device Manager (delete it)\n"
                "  5. Using -v3 binary on CPU without AVX2 — try plain "
                "tun2socks-windows-amd64.exe\n\n"
                "See System Log for full diagnostics."
            )

        # ── Step 6: wait for WinTUN adapter to appear ───────────────────
        progress(f"Waiting for WinTUN adapter '{TUN_IFACE_WIN}'… (up to 20s)")
        log.info("Waiting for WinTUN adapter '%s'…", TUN_IFACE_WIN)

        adapter_ok = _wait_for_adapter_windows(
            TUN_IFACE_WIN,
            timeout=20.0,
            output_buf=self._output_buf,
            proc=self._proc,
            on_progress=progress,
        )

        if not adapter_ok:
            # Give output reader thread a moment to capture recent output
            time.sleep(0.5)
            captured = self.get_captured_output()

            # Kill tun2socks so we don't leave an orphan
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                pass
            self._proc = None

            raise RuntimeError(
                f"WinTUN adapter '{TUN_IFACE_WIN}' did not appear after 20 seconds.\n\n"
                f"tun2socks output:\n{captured or '<no output>'}\n\n"
                "This usually means one of:\n"
                "  1. Windows Defender / antivirus is blocking wintun.dll or tun2socks.exe\n"
                "     → Add exclusion for the assets/bin/ folder in Windows Defender\n"
                "  2. The wintun kernel driver failed to install\n"
                "     → Reboot and try again; or check Windows Event Viewer for errors\n"
                "  3. You are using the -v3 (AVX2) binary but driver loading stalls\n"
                "     → Try tun2socks-windows-amd64.exe (no -v3 suffix)\n"
                "  4. A stale 'MasterVPN' WireGuard adapter exists in Device Manager\n"
                "     → Open Device Manager, show hidden devices, delete it\n"
                "  5. Insufficient privileges\n"
                "     → Ensure the app is running as Administrator\n\n"
                "See System Log for full diagnostics."
            )

        progress(f"Adapter '{TUN_IFACE_WIN}' is present ✓")
        log.info("Adapter '%s' is present.", TUN_IFACE_WIN)

        # Additional brief pause to let the driver fully settle
        time.sleep(1.0)

        # ── Step 7: assign IP to the TUN interface ─────────────────────
        progress(f"Assigning IP {TUN_IP_WIN}/{TUN_MASK_WIN} to adapter…")
        log.info("Assigning IP %s mask %s to '%s'", TUN_IP_WIN, TUN_MASK_WIN, TUN_IFACE_WIN)
        ok = _run_cmd([
            "netsh", "interface", "ip", "set", "address",
            TUN_IFACE_WIN, "static", TUN_IP_WIN, TUN_MASK_WIN,
        ])
        if not ok:
            log.warning(
                "netsh IP assignment returned non-zero — interface may already "
                "have an address or the adapter is not fully up yet."
            )

        # ── Step 8: set MTU on TUN interface ────────────────────────────
        log.info("Setting MTU=%s on '%s'", TUN_MTU_WIN, TUN_IFACE_WIN)
        _run_cmd([
            "netsh", "interface", "ipv4", "set", "subinterface",
            TUN_IFACE_WIN, f"mtu={TUN_MTU_WIN}", "store=active",
        ])

        # ── Step 9: configure DNS on TUN interface ─────────────────────
        progress(f"Setting DNS: {TUN_DNS_PRIMARY} / {TUN_DNS_SECONDARY}")
        log.info("Setting DNS on '%s': %s, %s", TUN_IFACE_WIN, TUN_DNS_PRIMARY, TUN_DNS_SECONDARY)
        _run_cmd([
            "netsh", "interface", "ip", "set", "dns",
            TUN_IFACE_WIN, "static", TUN_DNS_PRIMARY, "primary",
        ])
        _run_cmd([
            "netsh", "interface", "ip", "add", "dns",
            TUN_IFACE_WIN, TUN_DNS_SECONDARY, "index=2",
        ])

        # ── Step 10: add exclusion routes BEFORE default TUN route ──────
        if real_gw and exclusion_ips:
            progress(f"Adding {len(exclusion_ips)} split-tunnel exclusion route(s)…")
            log.info("Adding split-tunnel exclusion routes via real gateway %s …", real_gw)
            for ip in exclusion_ips:
                ok = _run_cmd([
                    "route", "add", ip, "mask", "255.255.255.255", real_gw,
                ])
                log.info(
                    "  Exclusion route %s/32 via %s — %s",
                    ip, real_gw, "OK" if ok else "FAILED (may already exist)",
                )
            self._real_gateway  = real_gw
            self._exclusion_ips = list(exclusion_ips)
        elif not real_gw:
            log.warning("Skipping exclusion routes (real gateway unknown).")
        elif not exclusion_ips:
            log.warning(
                "No relay IPs to exclude. Set 'google_ip' in Configuration "
                "so the proxy engine can bypass TUN."
            )

        # ── Step 11: wait for TUN network to be registered ─────────────
        # CRITICAL FIX: we must wait for the 198.18.x.x route to appear
        # in Windows's routing table before adding the 0.0.0.0/0 default
        # route.  If we add the default route too early, Windows cannot
        # find the TUN adapter as the correct egress for 198.18.0.1 and
        # binds the route to the WiFi adapter instead — traffic is then
        # silently dropped because the WiFi router has no path to 198.18.0.1.
        progress("Waiting for TUN network stack registration…")
        net_ready = _wait_for_tun_network_windows(TUN_IP_WIN, timeout=10.0)
        if net_ready:
            log.debug("TUN network 198.18.x.x registered in routing table ✓")
        else:
            log.warning(
                "TUN network 198.18.x.x not detected after 10s — "
                "the IP assignment may have been delayed. Proceeding anyway."
            )

        # ── Step 12: get TUN adapter interface index ────────────────────
        # This is the KEY fix.  We must specify the interface index when
        # adding the default route so Windows binds it to the TUN adapter
        # (e.g. IF 49) and NOT to the physical WiFi/Ethernet adapter.
        progress("Getting TUN adapter interface index…")
        tun_if_index = _get_tun_if_index_windows(TUN_IFACE_WIN)
        if tun_if_index:
            log.info("TUN adapter interface index: %s", tun_if_index)
            self._tun_if_index = tun_if_index
        else:
            log.warning(
                "Could not determine TUN interface index — "
                "default route may be bound to the wrong adapter."
            )

        # ── Step 13: add default route via TUN ─────────────────────────
        progress(f"Adding default route via TUN (IF={tun_if_index or '?'}, metric {TUN_METRIC_WIN})…")
        log.info(
            "Adding 0.0.0.0/0 via TUN gateway %s (IF=%s, metric %s)",
            TUN_GW_WIN, tun_if_index or "unknown", TUN_METRIC_WIN,
        )
        ok = _add_default_route_windows(tun_if_index)
        if not ok:
            log.warning(
                "Default TUN route add failed — traffic may not route through TUN."
            )

        # ── Step 14: verify routing table ──────────────────────────────
        self._log_routing_summary()
        progress(
            f"TUN mode active — '{TUN_IFACE_WIN}' adapter is visible in "
            "Control Panel → Network Connections."
        )
        log.info(
            "TUN mode active. Adapter '%s' visible in "
            "Control Panel → Network Connections.",
            TUN_IFACE_WIN,
        )

    def _stop_windows(self) -> None:
        # Remove default TUN route first so traffic reverts to real adapter
        log.info("Removing TUN default route via %s", TUN_GW_WIN)
        _remove_default_route_windows()

        # Remove exclusion routes
        if self._real_gateway and self._exclusion_ips:
            log.info(
                "Removing %d exclusion route(s) via %s …",
                len(self._exclusion_ips), self._real_gateway,
            )
            for ip in self._exclusion_ips:
                ok = _run_cmd([
                    "route", "delete", ip, "mask", "255.255.255.255",
                    self._real_gateway,
                ])
                log.debug("  Removed exclusion route %s — %s", ip, "OK" if ok else "FAILED")
        else:
            log.debug("No exclusion routes to remove.")

        self._real_gateway  = ""
        self._exclusion_ips = []
        self._tun_if_index  = ""

        # Clear DNS settings from TUN interface (best-effort)
        _run_cmd([
            "netsh", "interface", "ip", "set", "dns",
            TUN_IFACE_WIN, "dhcp",
        ])

    def _log_routing_summary(self) -> None:
        """Log the active default routes for diagnostics."""
        try:
            result = subprocess.run(
                ["route", "print", "0.0.0.0"],
                capture_output=True, timeout=8, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            default_lines = [
                ln for ln in result.stdout.splitlines()
                if ln.strip().startswith("0.0.0.0") and "0.0.0.0" in ln
            ]
            if default_lines:
                log.info("Active default routes:")
                for line in default_lines[:4]:
                    ln = line.strip()
                    # Diagnose if TUN route is on the wrong interface
                    if TUN_GW_WIN in ln:
                        parts = ln.split()
                        iface = parts[3] if len(parts) >= 4 else "?"
                        if iface != TUN_IP_WIN:
                            log.warning(
                                "  ⚠ TUN default route is on interface %s (expected %s) — "
                                "traffic may not route through TUN!",
                                iface, TUN_IP_WIN,
                            )
                        else:
                            log.info("  ✓ TUN default route correctly bound to TUN interface")
                    log.info("  %s", ln)
        except Exception:
            pass

    def _read_proc_output(self) -> None:
        """Background thread: forward tun2socks stdout/stderr to the logger."""
        try:
            for line in self._proc.stdout:  # type: ignore[union-attr]
                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="replace")
                line = line.rstrip()
                if line:
                    log.debug("[tun2socks] %s", line)
                    with self._output_lock:
                        self._output_buf.append(line)
        except Exception:
            pass

    # ── Linux ─────────────────────────────────────────────────────────

    def _start_linux(self, progress: Callable[[str], None]) -> None:
        tun2socks = _BIN_DIR / "tun2socks"
        if not tun2socks.exists():
            raise FileNotFoundError(
                f"tun2socks not found at {tun2socks}.\n"
                "Download from https://github.com/xjasonlyu/tun2socks/releases "
                "and place it in assets/bin/."
            )
        tun2socks.chmod(0o755)
        progress(f"TUN pre-flight: tun2socks={tun2socks} elevation={is_elevation_available()}")

        cmd = [
            str(tun2socks),
            "-device",   f"tun://{TUN_IFACE_LINUX}",
            "-proxy",    f"socks5://{SOCKS5_HOST}:{self.socks5_port}",
            "-loglevel", "info",
        ]
        progress(f"Launching: {' '.join(cmd)}")
        self._proc = subprocess.Popen(
            cmd,
            cwd=str(_BIN_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        # Start reader immediately
        self._stderr_thread = threading.Thread(
            target=self._read_proc_output, daemon=True, name="tun2socks-reader"
        )
        self._stderr_thread.start()

        time.sleep(1.5)

        if self._proc.poll() is not None:
            captured = self.get_captured_output()
            log.error("tun2socks exited immediately (rc=%d). Output: %s",
                      self._proc.returncode, captured)
            raise RuntimeError(
                f"tun2socks exited immediately — "
                f"{captured or 'check binary architecture and CAP_NET_ADMIN / root privileges'}."
            )

        # Get real gateway for split tunnelling
        real_gw = ""
        try:
            result = subprocess.run(
                ["ip", "route", "show", "default"],
                capture_output=True, timeout=5, text=True,
            )
            for line in result.stdout.splitlines():
                parts = line.split()
                if "via" in parts:
                    idx = parts.index("via")
                    real_gw = parts[idx + 1]
                    break
        except Exception:
            pass

        exclusion_ips = _get_exclusion_ips(self._config)
        if real_gw and exclusion_ips:
            for ip in exclusion_ips:
                _run_cmd(["ip", "route", "add", ip, "via", real_gw])
            self._real_gateway  = real_gw
            self._exclusion_ips = list(exclusion_ips)

        progress("Configuring TUN interface…")
        _run_cmd(["ip", "addr",  "add", f"{TUN_IP_LINUX}/24", "dev", TUN_IFACE_LINUX])
        _run_cmd(["ip", "link",  "set", TUN_IFACE_LINUX, "up"])
        _run_cmd(["ip", "route", "add", "default", "dev", TUN_IFACE_LINUX, "metric", "1"])

    def _stop_linux(self) -> None:
        _run_cmd(["ip", "route", "del", "default", "dev", TUN_IFACE_LINUX])
        if self._real_gateway and self._exclusion_ips:
            for ip in self._exclusion_ips:
                _run_cmd(["ip", "route", "del", ip, "via", self._real_gateway])
        _run_cmd(["ip", "link",   "set", TUN_IFACE_LINUX, "down"])
        _run_cmd(["ip", "tuntap", "del", "dev", TUN_IFACE_LINUX, "mode", "tun"])
        self._real_gateway  = ""
        self._exclusion_ips = []

    # ── macOS (best-effort) ───────────────────────────────────────────

    def _start_macos(self, progress: Callable[[str], None]) -> None:
        tun2socks = _BIN_DIR / "tun2socks-darwin"
        if not tun2socks.exists():
            raise FileNotFoundError(
                f"tun2socks-darwin not found at {tun2socks}.\n"
                "Download from https://github.com/xjasonlyu/tun2socks/releases."
            )
        tun2socks.chmod(0o755)
        progress("Launching tun2socks (macOS)…")

        cmd = [
            str(tun2socks),
            "-device", "utun7",
            "-proxy",  f"socks5://{SOCKS5_HOST}:{self.socks5_port}",
        ]
        self._proc = subprocess.Popen(
            cmd, cwd=str(_BIN_DIR),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        self._stderr_thread = threading.Thread(
            target=self._read_proc_output, daemon=True, name="tun2socks-reader"
        )
        self._stderr_thread.start()
        time.sleep(1.5)
        _run_cmd(["ifconfig", "utun7", "10.0.0.1", "10.0.0.1",
                  "netmask", "255.255.255.255", "up"])
        _run_cmd(["route", "add", "default", "10.0.0.1"])


# ── Standalone helpers ────────────────────────────────────────────────────────

def _require_elevation() -> None:
    """Raise PermissionError if the process lacks admin/root privileges."""
    if _OS == "Windows":
        try:
            import ctypes
            if not ctypes.windll.shell32.IsUserAnAdmin():  # type: ignore[attr-defined]
                raise PermissionError(
                    "TUN mode requires administrator privileges.\n"
                    "Right-click the application and select 'Run as administrator'."
                )
        except ImportError:
            pass
    else:
        if os.geteuid() != 0:
            raise PermissionError(
                "TUN mode requires root/CAP_NET_ADMIN privileges.\n"
                "Run the app with 'sudo' or grant the binary the required capabilities."
            )


def _run_cmd(cmd: list[str]) -> bool:
    """
    Run a system command silently.  Returns True on success (rc == 0).
    Logs stderr output at DEBUG level on failure.
    """
    try:
        kwargs: dict = dict(capture_output=True, timeout=15)
        if _OS == "Windows":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(cmd, **kwargs)
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode(errors="replace").strip()
            log.debug(
                "Command %s returned %d: %s",
                cmd, result.returncode, stderr or "<no stderr>",
            )
        return result.returncode == 0
    except Exception as exc:
        log.debug("Command %s raised: %s", cmd, exc)
        return False


def is_elevation_available() -> bool:
    """Return True if the current process has administrator/root privileges."""
    if _OS == "Windows":
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
        except Exception:
            return False
    else:
        return os.geteuid() == 0


def tun2socks_available() -> bool:
    """Return True if the tun2socks binary exists in assets/bin/."""
    if _OS == "Windows":
        return (_BIN_DIR / "tun2socks.exe").exists()
    elif _OS == "Darwin":
        return (_BIN_DIR / "tun2socks-darwin").exists()
    else:
        return (_BIN_DIR / "tun2socks").exists()
