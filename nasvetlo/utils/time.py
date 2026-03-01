"""Time utilities."""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime | None) -> datetime | None:
    """Attach UTC timezone if naive."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def hours_ago(dt: datetime) -> float:
    """Hours elapsed since dt."""
    dt = ensure_utc(dt) or utcnow()
    delta = utcnow() - dt
    return delta.total_seconds() / 3600.0
