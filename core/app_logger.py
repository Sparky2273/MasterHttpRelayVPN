"""
app_logger.py — Application-level structured logging for the GUI.

All GUI actions (connect, disconnect, cert install, config save, errors, etc.)
are logged here. The AppLogger owns a queue that the SystemLogTab polls via
a QTimer on the main thread.
"""
from __future__ import annotations

import logging
import queue
import traceback
from typing import NamedTuple
from datetime import datetime


class AppLogEntry(NamedTuple):
    """A single application-level log entry."""
    level: str        # "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
    source: str       # e.g. "Connection", "Certificate", "Config"
    message: str
    timestamp: str    # HH:MM:SS


# Global singleton queue — main thread polls it
_app_log_queue: queue.Queue = queue.Queue()

_LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log_app(level: str, source: str, message: str) -> None:
    """Put an AppLogEntry into the app log queue (thread-safe)."""
    entry = AppLogEntry(
        level=level,
        source=source,
        message=message,
        timestamp=_now(),
    )
    _app_log_queue.put_nowait(entry)
    # Also emit to Python logging for any attached handlers
    py_logger = logging.getLogger(f"GUI.{source}")
    py_level = _LOG_LEVEL_MAP.get(level, logging.INFO)
    py_logger.log(py_level, "[%s] %s", source, message)


def drain_app_log_queue():
    """Drain and return all pending entries (non-blocking)."""
    entries = []
    try:
        while True:
            entries.append(_app_log_queue.get_nowait())
    except queue.Empty:
        pass
    return entries


def install_crash_logger() -> None:
    """Install a global exception hook so unhandled exceptions appear in app log."""
    import sys

    def _excepthook(exc_type, exc_value, exc_tb):
        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log_app("CRITICAL", "Unhandled", f"Unhandled exception:\n{tb_str}")
        # Don't suppress — also print to stderr
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook
