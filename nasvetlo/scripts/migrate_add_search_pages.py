#!/usr/bin/env python3
"""Migration: add the ``search_page`` table.

Safe to run multiple times — uses CREATE TABLE IF NOT EXISTS.

Usage
-----
    python -m nasvetlo.scripts.migrate_add_search_pages
"""

from __future__ import annotations

import sys

from nasvetlo.db import get_engine
from nasvetlo.models import Base, SearchPage  # noqa: F401


def run() -> None:
    engine = get_engine()
    SearchPage.__table__.create(engine, checkfirst=True)
    print("[migrate] 'search_page' table created (or already existed).")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"[migrate] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
