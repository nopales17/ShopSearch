"""Structured operational logging, separate from behavioral telemetry (S10).

Operational logs use the standard library only. They record runtime facts an operator
needs — startup, migration and health failures, request completion, backup/restore
outcome — as one JSON object per line. They must never carry merchant passwords, raw
session cookies, CSRF tokens, request bodies, uploaded bytes or full header dumps, and
they deliberately omit query strings so the log cannot become a second behavioral
telemetry stream. Telemetry stays in the store-scoped `telemetry_events` table.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

LOGGER_NAME = "shopsearch.operational"


class JsonLineFormatter(logging.Formatter):
    """One JSON object per record; message plus explicitly allowed extras."""

    # Fields logging itself adds to every record; everything else is context.
    _RESERVED = frozenset(
        {
            "args",
            "asctime",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "thread",
            "threadName",
            "taskName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = record.exc_info[0].__name__ if record.exc_info[0] else "error"
        return json.dumps(payload, sort_keys=True, default=str, allow_nan=False)


def configure_operational_logging(level: str = "INFO") -> logging.Logger:
    """Return the process-wide operational logger writing JSON lines to stderr."""

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level.upper())
    logger.propagate = False
    if not any(
        isinstance(handler, logging.StreamHandler) and handler.get_name() == "shopsearch"
        for handler in logger.handlers
    ):
        handler = logging.StreamHandler()
        handler.set_name("shopsearch")
        handler.setFormatter(JsonLineFormatter())
        logger.addHandler(handler)
    return logger


def log_event(logger: logging.Logger, event: str, **context: Any) -> None:
    """Log one operational event; callers pass only non-secret context."""

    logger.info(event, extra=context)
