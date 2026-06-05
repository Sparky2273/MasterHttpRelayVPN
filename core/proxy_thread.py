"""
proxy_thread.py — QThread that runs the MasterHttpRelayVPN engine as a subprocess.

Key behaviour when running as a compiled (PyInstaller) EXE:
  The frozen binary cannot run an external "python engine/main.py" because
  there is no standalone Python interpreter.  Instead, the same EXE is
  re-launched with the ``--run-engine`` flag, which routes through the
  engine-mode branch in main_gui.py before any Qt code runs.

  Raw subprocess output is piped back and parsed exactly as in interpreter mode.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import traceback
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from core.log_bridge import LogEntry, parse_special

_GUI_ROOT    = Path(__file__).resolve().parent.parent
_ENGINE_MAIN = _GUI_ROOT / "engine" / "main.py"

# ── detect if running inside a PyInstaller bundle ──────────────────────────
_IS_FROZEN: bool = getattr(sys, "frozen", False)

# ANSI escape stripper
_ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_GARBAGE     = re.compile(r"[^\x09\x20-\x7E\xA0-\xFF]")

_PRETTY_SPLIT = re.compile(
    r"(?=\d{2}:\d{2}:\d{2}\s+[•!]\s+(?:DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL))"
)
_PRETTY_RE = re.compile(
    r"^(\d{2}:\d{2}:\d{2})\s+[•!]\s+"
    r"(DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL)\s+"
    r"\[([^\]]+)\]\s+"
    r"(.+)$",
    re.DOTALL,
)
_PLAIN_LEVEL_RE = re.compile(r"\b(DEBUG|INFO|WARNING|ERROR|CRITICAL)\b")


def _clean(raw: str) -> str:
    s = _ANSI_ESCAPE.sub("", raw)
    s = _GARBAGE.sub("", s)
    return s.strip()


def _parse_pretty(raw: str) -> Optional[LogEntry]:
    m = _PRETTY_RE.match(raw.strip())
    if not m:
        return None
    level = m.group(2)
    if level == "WARN":
        level = "WARNING"
    logger  = m.group(3).strip()
    message = f"{m.group(1)}  {level:<8} [{logger:<10}] {m.group(4).strip()}"
    return LogEntry(level=level, logger=logger, message=message)


def _split_and_parse(raw: str) -> list[LogEntry]:
    raw = _clean(raw)
    if not raw:
        return []
    parts = _PRETTY_SPLIT.split(raw)
    entries = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        entry = _parse_pretty(part)
        if entry:
            entries.append(entry)
        else:
            m2    = _PLAIN_LEVEL_RE.search(part)
            level = m2.group(1) if m2 else "INFO"
            if level == "WARN":
                level = "WARNING"
            entries.append(LogEntry(level=level, logger="engine", message=part))
    return entries


class ProxyThread(QThread):
    """
    Background QThread that runs the engine as a subprocess.

    In interpreter mode:  python engine/main.py -c <config>
    In frozen (EXE) mode: MasterHttpRelayVPN.exe --run-engine -c <config>

    Signals
    -------
    log_entry      : LogEntry
    status_changed : str  — "connecting" | "connected" | "disconnected" | "error"
    exec_count     : int
    h2_status      : str  — "active" | "closed"
    cert_warn      : ()
    """

    log_entry      = pyqtSignal(object)
    status_changed = pyqtSignal(str)
    exec_count     = pyqtSignal(int)
    h2_status      = pyqtSignal(str)
    cert_warn      = pyqtSignal()

    def __init__(self, config: dict, parent=None) -> None:
        super().__init__(parent)
        self._config    = config
        self._proc: Optional[subprocess.Popen] = None
        self._log_queue: queue.Queue = queue.Queue()
        self._cfg_file: Optional[str] = None
        self._stopped: bool = False
        self._error_occurred: bool = False

    def run(self) -> None:
        self._stopped        = False
        self._error_occurred = False
        self.status_changed.emit("connecting")
        try:
            self._run_subprocess()
        except Exception as exc:
            logging.getLogger("ProxyThread").error(
                "Subprocess launch failed: %s\n%s", exc, traceback.format_exc()
            )
            if not self._stopped:
                entry = LogEntry("ERROR", "ProxyThread", f"Failed to start engine: {exc}")
                self._log_queue.put(entry)
                self.status_changed.emit("error")
        finally:
            self._cleanup_cfg_file()
            if not self._stopped and not self._error_occurred:
                self.status_changed.emit("disconnected")

    def _run_subprocess(self) -> None:
        fd, cfg_path = tempfile.mkstemp(suffix=".json", prefix="mhrvpn_cfg_")
        self._cfg_file = cfg_path
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._config, fh, indent="\t", ensure_ascii=False)
        except Exception:
            os.close(fd)
            raise

        if _IS_FROZEN:
            # ── Frozen EXE: re-launch ourself in engine mode ────────────────
            # The --run-engine flag is intercepted in main_gui.py *before*
            # any Qt/GUI code runs, so no second window appears.
            exe = sys.executable
            cmd = [exe, "--run-engine", "-c", cfg_path]
        else:
            # ── Interpreter: run engine/main.py with the current Python ─────
            python_exe = sys.executable or "python3"
            cmd = [python_exe, str(_ENGINE_MAIN), "-c", cfg_path]

        # On Windows, CREATE_NO_WINDOW prevents a black console popup.
        _cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(_GUI_ROOT / "engine"),
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=_cflags if sys.platform == "win32" else 0,
        )

        for raw_line in self._proc.stdout:  # type: ignore[union-attr]
            entries = _split_and_parse(raw_line)
            for entry in entries:
                self._log_queue.put(entry)

        self._proc.wait()
        rc = self._proc.returncode

        if not self._stopped and rc not in (0, -15, -2, 1, None):
            self._error_occurred = True
            entry = LogEntry("ERROR", "ProxyThread", f"Engine exited with code {rc}")
            self._log_queue.put(entry)
            self.status_changed.emit("error")

    def stop(self) -> None:
        """Terminate the engine subprocess gracefully."""
        self._stopped = True
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass

    def drain_log_queue(self) -> None:
        """Drain pending log entries and emit Qt signals. Call from main thread."""
        try:
            while True:
                entry: LogEntry = self._log_queue.get_nowait()
                self.log_entry.emit(entry)
                special = parse_special(entry)
                if special.get("connected"):
                    self.status_changed.emit("connected")
                if "exec_count" in special:
                    self.exec_count.emit(special["exec_count"])
                if special.get("h2_active"):
                    self.h2_status.emit("active")
                if special.get("h2_closed"):
                    self.h2_status.emit("closed")
                if special.get("cert_warn"):
                    self.cert_warn.emit()
        except queue.Empty:
            pass

    def _cleanup_cfg_file(self) -> None:
        if self._cfg_file:
            try:
                os.unlink(self._cfg_file)
            except OSError:
                pass
            self._cfg_file = None
