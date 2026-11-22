"""
core/log.py
Project-wide JSON-lines structured logger with correlation ID contextvars,
daily rotation, 14-day retention, gzip compression, and human-readable console output.
"""

import os
import sys
import json
import gzip
import shutil
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timezone
from pathlib import Path
from contextvars import ContextVar
from contextlib import contextmanager
from typing import Optional, Dict, Any

# Correlation contextvars
session_id_ctx: ContextVar[Optional[str]] = ContextVar("session_id", default=None)
page_id_ctx: ContextVar[Optional[str]] = ContextVar("page_id", default=None)


@contextmanager
def log_context(
    session_id: Optional[str] = None,
    page_id: Optional[str] = None
):
    """
    Context manager to propagate correlation IDs across async/sync task boundaries.
    """
    tokens = {}
    if session_id is not None:
        tokens["session_id"] = session_id_ctx.set(session_id)
    if page_id is not None:
        tokens["page_id"] = page_id_ctx.set(page_id)
    try:
        yield
    finally:
        if "session_id" in tokens:
            session_id_ctx.reset(tokens["session_id"])
        if "page_id" in tokens:
            page_id_ctx.reset(tokens["page_id"])


def set_log_context(
    session_id: Optional[str] = None,
    page_id: Optional[str] = None
) -> Dict[str, Any]:
    """Sets correlation IDs and returns reset tokens."""
    tokens = {}
    if session_id is not None:
        tokens["session_id"] = session_id_ctx.set(session_id)
    if page_id is not None:
        tokens["page_id"] = page_id_ctx.set(page_id)
    return tokens


def reset_log_context(tokens: Dict[str, Any]):
    """Resets correlation IDs from tokens."""
    if "session_id" in tokens:
        session_id_ctx.reset(tokens["session_id"])
    if "page_id" in tokens:
        page_id_ctx.reset(tokens["page_id"])


def _gzip_rotator(source: str, dest: str):
    """Rotator that compresses rotated log files into .gz archives."""
    with open(source, "rb") as sf, gzip.open(dest, "wb") as df:
        shutil.copyfileobj(sf, df)
    try:
        os.remove(source)
    except OSError:
        pass


def _gzip_namer(name: str) -> str:
    """Appends .gz to rotated file names if not already present."""
    if name.endswith(".gz"):
        return name
    return f"{name}.gz"


class JSONLinesFormatter(logging.Formatter):
    """Formats log records as JSONL with fixed fields."""

    def format(self, record: logging.LogRecord) -> str:
        # Extract payload attached to record
        payload = getattr(record, "_structured_payload", None)
        if payload is None:
            # Fallback for standard log records
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            level_str = "WARN" if record.levelname == "WARNING" else record.levelname
            payload = {
                "ts": now_iso,
                "level": level_str,
                "service": getattr(record, "service", record.name),
                "event": getattr(record, "event", "general"),
                "message": record.getMessage()
            }
        return json.dumps(payload, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Human-readable console formatter for developer experience."""

    LEVEL_COLORS = {
        "DEBUG": "\033[36m",    # Cyan
        "INFO": "\033[32m",     # Green
        "WARN": "\033[33m",     # Yellow
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",    # Red
        "CRITICAL": "\033[35m", # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        payload = getattr(record, "_structured_payload", None)
        if payload:
            ts = payload.get("ts", "")[:19].replace("T", " ")
            level = payload.get("level", record.levelname)
            service = payload.get("service", record.name)
            event = payload.get("event", "general")
            msg = payload.get("message", record.getMessage())
            corr_parts = []
            if payload.get("session_id"):
                corr_parts.append(f"sess={payload['session_id']}")
            if payload.get("page_id"):
                corr_parts.append(f"page={payload['page_id']}")
            corr_str = f" ({' '.join(corr_parts)})" if corr_parts else ""
            data_str = f" data={json.dumps(payload['data'])}" if payload.get("data") else ""
        else:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            level = record.levelname
            service = record.name
            event = getattr(record, "event", "general")
            msg = record.getMessage()
            corr_str = ""
            data_str = ""

        color = self.LEVEL_COLORS.get(level, "")
        reset = self.RESET if color else ""
        level_fmt = f"{color}[{level:>5}]{reset}"
        return f"{ts} {level_fmt} [{service}:{event}] {msg}{corr_str}{data_str}"


# Singleton configuration state
_LOGGING_INITIALIZED = False
_LOG_DIR = Path("logs")
_LOG_FILE = _LOG_DIR / "app.jsonl"


def init_logging(log_file: Optional[Path] = None, console_level: int = logging.INFO, force: bool = False):
    """
    Initializes root logging handlers (Console + TimedRotatingFileHandler with Gzip).
    Supports reinitialization when a specific log_file is provided or force=True.
    """
    global _LOGGING_INITIALIZED, _LOG_FILE
    if _LOGGING_INITIALIZED and not force and log_file is None:
        return

    target_file = Path(log_file) if log_file else _LOG_FILE
    _LOG_FILE = target_file
    target_dir = target_file.parent
    target_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger("learning_platform")
    root_logger.setLevel(logging.DEBUG)
    
    for h in root_logger.handlers:
        h.close()
    root_logger.handlers.clear()
    root_logger.propagate = False

    # 1. Console handler (human readable)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(ConsoleFormatter())
    root_logger.addHandler(console_handler)

    # 2. Daily rotating JSONL file handler (keeps 14 days, gzipped)
    file_handler = TimedRotatingFileHandler(
        filename=str(target_file),
        when="midnight",
        interval=1,
        backupCount=14,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JSONLinesFormatter())
    file_handler.rotator = _gzip_rotator
    file_handler.namer = _gzip_namer
    root_logger.addHandler(file_handler)

    _LOGGING_INITIALIZED = True


class StructuredLogger:
    """
    JSON-Lines Structured Logger adhering to project-wide requirements:
    Fields: ts, level, service, event, message, [session_id], [page_id], [data]
    """

    def __init__(self, service: str):
        self.service = service
        self._underlying = logging.getLogger(f"learning_platform.{service}")

    def _emit(
        self,
        level_name: str,
        event: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        page_id: Optional[str] = None,
        exc_info: bool = False
    ):
        if not _LOGGING_INITIALIZED:
            init_logging()

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        norm_level = "WARN" if level_name in ("WARN", "WARNING") else level_name

        payload: Dict[str, Any] = {
            "ts": now_iso,
            "level": norm_level,
            "service": self.service,
            "event": event,
            "message": str(message)
        }

        # Resolve correlation IDs from args or ContextVars
        eff_session_id = session_id if session_id is not None else session_id_ctx.get()
        eff_page_id = page_id if page_id is not None else page_id_ctx.get()

        if eff_session_id:
            payload["session_id"] = eff_session_id
        if eff_page_id:
            payload["page_id"] = eff_page_id
        if data is not None:
            payload["data"] = data

        log_level = getattr(logging, "WARNING" if norm_level == "WARN" else norm_level, logging.INFO)

        record = self._underlying.makeRecord(
            name=self._underlying.name,
            level=log_level,
            fn="",
            lno=0,
            msg=message,
            args=(),
            exc_info=sys.exc_info() if exc_info else None
        )
        record._structured_payload = payload
        record.service = self.service
        record.event = event
        self._underlying.handle(record)

    def debug(
        self,
        event_or_msg: str,
        message: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        page_id: Optional[str] = None,
        **kwargs
    ):
        event = event_or_msg if message is not None else "debug"
        msg = message if message is not None else event_or_msg
        self._emit("DEBUG", event, msg, data, session_id, page_id, **kwargs)

    def info(
        self,
        event_or_msg: str,
        message: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        page_id: Optional[str] = None,
        **kwargs
    ):
        event = event_or_msg if message is not None else "info"
        msg = message if message is not None else event_or_msg
        self._emit("INFO", event, msg, data, session_id, page_id, **kwargs)

    def warn(
        self,
        event_or_msg: str,
        message: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        page_id: Optional[str] = None,
        **kwargs
    ):
        event = event_or_msg if message is not None else "warning"
        msg = message if message is not None else event_or_msg
        self._emit("WARN", event, msg, data, session_id, page_id, **kwargs)

    def warning(self, *args, **kwargs):
        """Alias for warn()"""
        self.warn(*args, **kwargs)

    def error(
        self,
        event_or_msg: str,
        message: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        page_id: Optional[str] = None,
        exc_info: bool = False,
        **kwargs
    ):
        event = event_or_msg if message is not None else "error"
        msg = message if message is not None else event_or_msg
        self._emit("ERROR", event, msg, data, session_id, page_id, exc_info=exc_info, **kwargs)

    def critical(
        self,
        event_or_msg: str,
        message: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        page_id: Optional[str] = None,
        exc_info: bool = False,
        **kwargs
    ):
        event = event_or_msg if message is not None else "critical"
        msg = message if message is not None else event_or_msg
        self._emit("CRITICAL", event, msg, data, session_id, page_id, exc_info=exc_info, **kwargs)


def get_logger(service: str) -> StructuredLogger:
    """
    Returns a StructuredLogger for the specified service name.
    Usage:
        logger = get_logger("engine")
        logger.info("page_saved", "Page 2 saved", data={"page_number": 2})
    """
    return StructuredLogger(service)
