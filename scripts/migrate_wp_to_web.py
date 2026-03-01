"""One-time migration: add new columns, backfill status from published bool."""

import sqlite3
import sys

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "nasvetlo.db"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# 1. Add status column to generated_article
for col, typedef in [
    ("status", "VARCHAR(20) DEFAULT 'pending'"),
    ("reviewed_by", "VARCHAR(100)"),
    ("reviewed_at", "DATETIME"),
    ("editor_notes", "TEXT"),
]:
    try:
        cur.execute(f"ALTER TABLE generated_article ADD COLUMN {col} {typedef}")
        print(f"  Added generated_article.{col}")
    except sqlite3.OperationalError:
        print(f"  generated_article.{col} already exists")

# 2. Backfill status from published bool
cur.execute("UPDATE generated_article SET status = 'published' WHERE published = 1")
cur.execute("UPDATE generated_article SET status = 'pending' WHERE published = 0 OR published IS NULL")
print(f"  Backfilled status column")

# 3. Add columns to publishing_log
for col, typedef in [
    ("action", "VARCHAR(50) DEFAULT 'created'"),
    ("actor", "VARCHAR(100) DEFAULT 'pipeline'"),
    ("note", "TEXT"),
    ("created_at", "DATETIME"),
]:
    try:
        cur.execute(f"ALTER TABLE publishing_log ADD COLUMN {col} {typedef}")
        print(f"  Added publishing_log.{col}")
    except sqlite3.OperationalError:
        print(f"  publishing_log.{col} already exists")

# 4. Backfill publishing_log action for existing WP entries
cur.execute("UPDATE publishing_log SET action = 'wp_published' WHERE wp_post_id IS NOT NULL AND action = 'created'")

# 5. Create index on status
try:
    cur.execute("CREATE INDEX ix_generated_article_status ON generated_article(status)")
    print("  Created index on generated_article.status")
except sqlite3.OperationalError:
    print("  Index already exists")

conn.commit()
conn.close()
print(f"\nMigration complete: {DB_PATH}")
