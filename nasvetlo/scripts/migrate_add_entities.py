#!/usr/bin/env python3
"""Migration: add ``entity`` and ``entity_event_link`` tables.

Safe to run multiple times — uses CREATE TABLE IF NOT EXISTS.

Usage
-----
    python -m nasvetlo.scripts.migrate_add_entities
"""

from __future__ import annotations

import sys

from nasvetlo.db import get_engine
from nasvetlo.models import Base, Entity, EntityEventLink  # noqa: F401


def run() -> None:
    engine = get_engine()
    Entity.__table__.create(engine, checkfirst=True)
    EntityEventLink.__table__.create(engine, checkfirst=True)
    print("[migrate] 'entity' and 'entity_event_link' tables created (or already existed).")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"[migrate] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
