"""
Unit tests for core.log_bridge.
"""

import logging
import queue
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.log_bridge import (
    LogEntry,
    QueueLogHandler,
    install_handler,
    parse_special,
    remove_handler,
)


# ── QueueLogHandler ───────────────────────────────────────────────────────────

def test_handler_puts_entry_in_queue():
    q = queue.Queue()
    handler = QueueLogHandler(q, level=logging.DEBUG)
    logger = logging.getLogger("test.handler")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    logger.info("hello from test")
    logger.removeHandler(handler)

    assert not q.empty()
    entry = q.get_nowait()
    assert isinstance(entry, LogEntry)
    assert "hello from test" in entry.message
    assert entry.level == "INFO"


def test_handler_filters_below_level():
    q = queue.Queue()
    handler = QueueLogHandler(q, level=logging.WARNING)
    logger = logging.getLogger("test.filter")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    logger.debug("debug msg")      # should be filtered
    logger.info("info msg")        # should be filtered
    logger.warning("warn msg")     # should pass
    logger.removeHandler(handler)

    assert q.qsize() == 1
    entry = q.get_nowait()
    assert entry.level == "WARNING"


def test_handler_includes_logger_name():
    q = queue.Queue()
    handler = QueueLogHandler(q)
    logger = logging.getLogger("MySpecialLogger")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    logger.error("error!")
    logger.removeHandler(handler)

    entry = q.get_nowait()
    assert entry.logger == "MySpecialLogger"


# ── install_handler / remove_handler ─────────────────────────────────────────

def test_install_handler_attaches_to_root():
    q = queue.Queue()
    handler = install_handler(q, level="DEBUG")
    try:
        root = logging.getLogger()
        assert handler in root.handlers
    finally:
        remove_handler(handler)


def test_remove_handler_detaches():
    q = queue.Queue()
    handler = install_handler(q, level="DEBUG")
    remove_handler(handler)
    root = logging.getLogger()
    assert handler not in root.handlers


# ── parse_special ─────────────────────────────────────────────────────────────

def _entry(msg: str, level: str = "INFO") -> LogEntry:
    return LogEntry(level=level, logger="test", message=msg)


def test_parse_special_connected():
    result = parse_special(_entry("HTTP proxy listening on 127.0.0.1:8085"))
    assert result.get("connected") is True


def test_parse_special_h2_active():
    result = parse_special(_entry("H2 idle keepalive active — stream open"))
    assert result.get("h2_active") is True


def test_parse_special_h2_closed():
    result = parse_special(_entry("H2 remote closed — reconnecting"))
    assert result.get("h2_closed") is True


def test_parse_special_exec_count():
    result = parse_special(_entry("Apps Script executions used so far: 42"))
    assert result.get("exec_count") == 42


def test_parse_special_exec_count_zero():
    result = parse_special(_entry("Apps Script executions used so far: 0"))
    assert result.get("exec_count") == 0


def test_parse_special_cert_warn():
    result = parse_special(_entry("WARNING: MITM CA is not trusted by the system"))
    assert result.get("cert_warn") is True


def test_parse_special_no_match():
    result = parse_special(_entry("Normal log line with no special event"))
    assert result == {}


def test_parse_special_multiple_matches():
    result = parse_special(_entry(
        "HTTP proxy listening on 127.0.0.1:8085 — Apps Script executions used so far: 7"
    ))
    assert result.get("connected") is True
    assert result.get("exec_count") == 7


def test_parse_special_case_insensitive():
    result = parse_special(_entry("http proxy LISTENING on 127.0.0.1:8085"))
    assert result.get("connected") is True
