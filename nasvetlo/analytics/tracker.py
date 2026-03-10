"""View tracking — increment article view counters.

Designed for fire-and-forget use from the web tier.  The increment is done
with a raw SQL UPDATE so it is safe under concurrent requests without
loading the full ORM object.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from nasvetlo.logging_utils import get_logger

log = get_logger("analytics.tracker")


def record_view(session: Session, article_id: int) -> None:
    """Increment view_count for *article_id* by 1.

    No-ops silently if the article does not exist.
    """
    try:
        session.execute(
            text("UPDATE generated_article SET view_count = view_count + 1 WHERE id = :id"),
            {"id": article_id},
        )
        session.commit()
    except Exception as e:
        log.debug("record_view failed for article %d: %s", article_id, e)
        session.rollback()


def get_top_articles(
    session: Session,
    limit: int = 20,
    min_views: int = 1,
) -> list[dict]:
    """Return top articles by view count with basic stats."""
    rows = session.execute(
        text("""
            SELECT id, title, slug, view_count, created_at, category_id
            FROM generated_article
            WHERE status = 'published' AND view_count >= :min_views
            ORDER BY view_count DESC
            LIMIT :limit
        """),
        {"min_views": min_views, "limit": limit},
    ).fetchall()

    return [
        {
            "id": row.id,
            "title": row.title,
            "slug": row.slug,
            "view_count": row.view_count,
            "created_at": row.created_at,
            "category_id": row.category_id,
        }
        for row in rows
    ]
