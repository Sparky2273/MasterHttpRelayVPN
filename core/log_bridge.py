"""
LogBridge — bridges the engine's Python ``logging`` system to the GUI.

A ``QueueLogHandler`` captures every log record emitted by the engine
(running in a background QThread) and puts a formatted string into a
thread-safe ``queue.Queue``.  The main thread polls that queue via a
``QTimer`` and appends lines to the live log panel.
"""

from __future__ import annotations

import logging
import queue
import re
from typing import NamedTuple


# ── Named tuple for structured log entries ───────────────────────────────────

class LogEntry(NamedTuple):
    """A single structured log entry forwarded to the GUI."""
    level: str        # "DEBUG", "INFO", "WARNING", "ERROR"
    logger: str       # Logger name, e.g. "Proxy" or "Relay"
    message: str      # Formatted one-line message (no trailing newline)


# ── Compiled patterns the GUI uses to detect special engine events ────────────

PATTERNS = {
    "connected":    re.compile(r"HTTP proxy listening", re.IGNORECASE),
    "h2_active":    re.compile(r"H2 idle keepalive active", re.IGNORECASE),
    "h2_closed":    re.compile(r"H2 remote closed", re.IGNORECASE),
    "exec_count":   re.compile(r"Apps Script executions used so far:\s*(\d+)", re.IGNORECASE),
    "error":        re.compile(r"(unhandled|exception|fatal|crash)", re.IGNORECASE),
    "cert_warn":    re.compile(r"MITM CA is not trusted", re.IGNORECASE),
}


class QueueLogHandler(logging.Handler):
    """
    A :class:`logging.Handler` that enqueues :class:`LogEntry` objects.

    Parameters
    ----------
    log_queue :
        The :class:`queue.Queue` into which log entries are placed.
    level :
        Minimum log level to capture (default: ``logging.DEBUG``).
    """

    def __init__(self, log_queue: queue.Queue, level: int = logging.DEBUG) -> None:
        super().__init__(level)
        self._queue = log_queue

        fmt = logging.Formatter(
            fmt="%(asctime)s [%(name)s] %(message)s",
            datefmt="%H:%M:%S",
        )
        self.setFormatter(fmt)

    def emit(self, record: logging.LogRecord) -> None:
        """Format *record* and place a :class:`LogEntry` in the queue."""
        try:
            msg = self.format(record)
            entry = LogEntry(
                level=record.levelname,
                logger=record.name,
                message=msg,
            )
            self._queue.put_nowait(entry)
        except Exception:  # pragma: no cover
            self.handleError(record)


def install_handler(log_queue: queue.Queue, level: str = "INFO") -> QueueLogHandler:
    """
    Install a :class:`QueueLogHandler` on the root logger.

    Removes any existing handlers on the root logger first so that
    the GUI is the sole consumer of log output from the engine thread.

    Parameters
    ----------
    log_queue :
        Destination queue for :class:`LogEntry` objects.
    level :
        Log level name string, e.g. ``"DEBUG"`` or ``"INFO"``.

    Returns
    -------
    QueueLogHandler
        The newly installed handler (caller may keep a reference to
        remove it later).
    """
    root = logging.getLogger()
    # Remove existing handlers silently
    for h in root.handlers[:]:
        root.removeHandler(h)

    handler = QueueLogHandler(log_queue, level=getattr(logging, level, logging.INFO))
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)  # Let the handler decide filtering
    return handler


def remove_handler(handler: QueueLogHandler) -> None:
    """Remove *handler* from the root logger."""
    logging.getLogger().removeHandler(handler)


def parse_special(entry: LogEntry) -> dict[str, object]:
    """
    Scan *entry* for well-known engine events.

    Returns
    -------
    dict
        Keys that were matched.  Possible keys:

        ``"connected"``
            True when the proxy server has started listening.
        ``"exec_count"``
            Integer Apps Script execution count.
        ``"h2_active"``
            True when the H2 keepalive loop is running.
        ``"h2_closed"``
            True when the H2 connection dropped.
        ``"cert_warn"``
            True when the CA is not trusted.
    """
    result: dict[str, object] = {}
    m_exec = PATTERNS["exec_count"].search(entry.message)
    if m_exec:
        result["exec_count"] = int(m_exec.group(1))
    if PATTERNS["connected"].search(entry.message):
        result["connected"] = True
    if PATTERNS["h2_active"].search(entry.message):
        result["h2_active"] = True
    if PATTERNS["h2_closed"].search(entry.message):
        result["h2_closed"] = True
    if PATTERNS["cert_warn"].search(entry.message):
        result["cert_warn"] = True
    return result
