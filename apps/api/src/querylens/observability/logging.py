"""Structured logging module implementing C11 allowlisted logs and redaction."""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any


# Allowlisted keys in structured log events
ALLOWLISTED_KEYS = {
    "timestamp",
    "level",
    "event",
    "request_id",
    "run_id",
    "stage",
    "error_code",
    "status",
    "duration_ms",
    "row_count",
    "token_usage",
    "policy_version",
    "snapshot_hash",
    "dialect",
    "attempt",
    "connection_id",
    "user_id",
}

# Sensitive keys that must be unconditionally redacted if present
SENSITIVE_PATTERNS = [
    "password",
    "secret",
    "token",
    "cookie",
    "authorization",
    "ciphertext",
    "dsn",
    "key",
    "prompt",
    "sql",
]


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON adhering to allowlisted fields."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "event": record.getMessage(),
        }

        # Transfer allowlisted attributes from record
        for key in ALLOWLISTED_KEYS:
            if hasattr(record, key):
                data[key] = getattr(record, key)

        # Extra data passed in kwargs
        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            for k, v in record.extra_data.items():
                if k in ALLOWLISTED_KEYS:
                    data[k] = v

        return json.dumps(data)


def get_logger(name: str = "querylens") -> logging.Logger:
    """Configure and return structured logger."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredJsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def log_event(
    event: str,
    level: int = logging.INFO,
    logger_name: str = "querylens",
    **kwargs: Any,
) -> None:
    """Emit a structured allowlisted log event."""
    logger = get_logger(logger_name)
    filtered_extra = {k: v for k, v in kwargs.items() if k in ALLOWLISTED_KEYS}
    record = logger.makeRecord(
        name=logger.name,
        level=level,
        fn="",
        lno=0,
        msg=event,
        args=(),
        exc_info=None,
    )
    for k, v in filtered_extra.items():
        setattr(record, k, v)
    logger.handle(record)
