#!/usr/bin/env python3
"""Migration: add the ``event`` table to an existing nasvetlo database.

Safe to run multiple times — uses CREATE TABLE IF NOT EXISTS.

Usage
-----
    python -m nasvetlo.scripts.migrate_add_event_registry
"""

from __future__ import annotations

import sys

from nasvetlo.db import get_engine
from nasvetlo.models import Base, Event  # noqa: F401 — registers Event with Base


def run() -> None:
    engine = get_engine()
    Event.__table__.create(engine, checkfirst=True)
    print("[migrate] 'event' table created (or already existed).")
    print("[migrate] Run backfill_events next to populate existing clusters.")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"[migrate] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
