"""SQLAlchemy engine and session management."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from nasvetlo.settings import get_settings

_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            echo=False,
            connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
        )
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


def get_session() -> Session:
    """Create a new session."""
    return get_session_factory()()


def init_db() -> None:
    """Create all tables."""
    from nasvetlo.models import Base
    Base.metadata.create_all(bind=get_engine())


def reset_engine() -> None:
    """Reset cached engine/session (useful for tests)."""
    global _engine, _SessionLocal
    _engine = None
    _SessionLocal = None
