"""Structured logging setup."""

from __future__ import annotations

import logging
import json
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Emit one JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_obj["exception"] = self.formatException(record.exc_info)
        # Merge extra fields
        for key in ("source", "cluster_id", "article_id", "step", "duration_ms"):
            val = getattr(record, key, None)
            if val is not None:
                log_obj[key] = val
        return json.dumps(log_obj, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with JSON output to stderr."""
    root = logging.getLogger("nasvetlo")
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the nasvetlo namespace."""
    return logging.getLogger(f"nasvetlo.{name}")
