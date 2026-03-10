"""Migration: add summary_cache_json column to raw_article."""

from __future__ import annotations

from sqlalchemy import inspect, text

from nasvetlo.db import get_engine, init_db


def migrate() -> None:
    init_db()
    engine = get_engine()

    with engine.connect() as conn:
        inspector = inspect(engine)
        columns = [c["name"] for c in inspector.get_columns("raw_article")]

        if "summary_cache_json" not in columns:
            conn.execute(text(
                "ALTER TABLE raw_article ADD COLUMN summary_cache_json TEXT"
            ))
            conn.commit()
            print("[migrate] Added summary_cache_json column to raw_article.")
        else:
            print("[migrate] summary_cache_json column already exists.")


if __name__ == "__main__":
    migrate()
