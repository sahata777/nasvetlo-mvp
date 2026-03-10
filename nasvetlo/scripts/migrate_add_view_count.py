"""Migration: add view_count and traffic_boosted columns to generated_article."""

from __future__ import annotations

from sqlalchemy import inspect, text

from nasvetlo.db import get_engine, init_db


def migrate() -> None:
    init_db()
    engine = get_engine()

    with engine.connect() as conn:
        inspector = inspect(engine)
        columns = [c["name"] for c in inspector.get_columns("generated_article")]

        if "view_count" not in columns:
            conn.execute(text(
                "ALTER TABLE generated_article ADD COLUMN view_count INTEGER DEFAULT 0"
            ))
            conn.commit()
            print("[migrate] Added view_count column to generated_article.")
        else:
            print("[migrate] view_count column already exists.")

        if "traffic_boosted" not in columns:
            conn.execute(text(
                "ALTER TABLE generated_article ADD COLUMN traffic_boosted INTEGER DEFAULT 0"
            ))
            conn.commit()
            print("[migrate] Added traffic_boosted column to generated_article.")
        else:
            print("[migrate] traffic_boosted column already exists.")


if __name__ == "__main__":
    migrate()
