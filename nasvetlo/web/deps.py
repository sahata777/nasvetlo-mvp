"""Shared dependencies for web routes."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from nasvetlo.db import get_session_factory

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["reading_time"] = lambda wc: max(1, (wc or 0) // 200)


def get_db() -> Generator[Session, None, None]:
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()
