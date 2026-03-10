#!/usr/bin/env python3
"""Migration: add explainer columns to the ``entity`` table.

Adds ``explainer_html`` (TEXT) and ``explainer_updated_at`` (DATETIME)
to support Phase 6 — Evergreen Explainer System.

Safe to run multiple times — checks for column existence before altering.

Usage
-----
    python -m nasvetlo.scripts.migrate_add_entity_explainer
"""

from __future__ import annotations

import sys

from sqlalchemy import inspect, text

from nasvetlo.db import get_engine


def run() -> None:
    engine = get_engine()
    inspector = inspect(engine)

    try:
        existing_cols = {col["name"] for col in inspector.get_columns("entity")}
    except Exception:
        print("[migrate] 'entity' table not found — run migrate_add_entities first.")
        sys.exit(1)

    with engine.connect() as conn:
        if "explainer_html" not in existing_cols:
            conn.execute(text("ALTER TABLE entity ADD COLUMN explainer_html TEXT"))
            print("[migrate] Added column: entity.explainer_html")
        else:
            print("[migrate] Column entity.explainer_html already exists.")

        if "explainer_updated_at" not in existing_cols:
            conn.execute(text("ALTER TABLE entity ADD COLUMN explainer_updated_at DATETIME"))
            print("[migrate] Added column: entity.explainer_updated_at")
        else:
            print("[migrate] Column entity.explainer_updated_at already exists.")

        conn.commit()

    print("[migrate] Entity explainer migration complete.")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"[migrate] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
