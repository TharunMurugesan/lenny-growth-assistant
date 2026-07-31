"""Structured JSON logging with request-id correlation — architecture.md §14.

One JSON line per event, every line carrying the `request_id` of the request
that produced it, so a single request yields a complete greppable trace.

Deliberately never logged: API keys, full message content in production (a
truncated prefix at DEBUG only), and raw provider response bodies.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any

# Set by middleware per request; read by the formatter. A ContextVar rather
# than a parameter so any module can log a correlated line without threading a
# request object down through the agent layer.
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_RESERVED = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()
) | {"message", "asctime", "taskName"}


def new_request_id() -> str:
    """A short, sortable-enough correlation id."""
    return uuid.uuid4().hex[:16]


class JsonFormatter(logging.Formatter):
    """Renders a record as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": request_id_ctx.get(),
            "message": record.getMessage(),
        }

        # Anything passed via logger.info("…", extra={...}) rides along as a
        # top-level field, which is what makes the stage logs in §14 queryable.
        for key, value in record.__dict__.items():
            if key not in _RESERVED:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


class PlainFormatter(logging.Formatter):
    """Human-readable console format for local development."""

    def format(self, record: logging.LogRecord) -> str:
        base = (
            f"{self.formatTime(record, '%H:%M:%S')} "
            f"{record.levelname:<7} "
            f"[{request_id_ctx.get()}] "
            f"{record.name} — {record.getMessage()}"
        )
        extras = {
            k: v for k, v in record.__dict__.items() if k not in _RESERVED
        }
        if extras:
            base += f"  {json.dumps(extras, default=str)}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging(level: str = "INFO", *, json_output: bool = False) -> None:
    """Install the root handler. Idempotent — safe under uvicorn --reload."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_output else PlainFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # uvicorn installs its own handlers; drop them so every line goes through
    # one formatter and nothing is emitted twice.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

    # asyncpg logs every statement at DEBUG, which drowns the trace.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
