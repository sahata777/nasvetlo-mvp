#!/usr/bin/env python3
"""Backfill: populate the event registry from all existing clusters.

Run once after ``migrate_add_event_registry`` to create Event records for
every coherent, scored cluster already in the database.

Usage
-----
    python -m nasvetlo.scripts.backfill_events
"""

from __future__ import annotations

import sys

from nasvetlo.config import get_config
from nasvetlo.db import init_db, get_session
from nasvetlo.events.registry import sync_event_registry


def run() -> None:
    init_db()
    config = get_config()
    session = get_session()
    try:
        result = sync_event_registry(session, config)
        print(
            f"[backfill] Done: {result['created']} events created, "
            f"{result['updated']} updated."
        )
    finally:
        session.close()


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"[backfill] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
