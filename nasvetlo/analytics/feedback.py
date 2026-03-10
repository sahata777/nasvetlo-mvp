"""Traffic feedback — propagate high-traffic signals back into the pipeline.

Called once per pipeline cycle (Step 7).  For each recently published article
that exceeded the view threshold:

1. Boost the parent Event's importance_score (future clusters on the same
   story are scored higher, raising the chance of a follow-up article).
2. Increment entity mention_count for entities linked to that article
   (boosting those entities toward evergreen explainer generation).

All updates are additive and idempotent-safe: the view threshold acts as
a hysteresis filter — articles already boosted are not double-boosted
because we check `traffic_boosted` flag on the event.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from nasvetlo.config import AppConfig
from nasvetlo.logging_utils import get_logger

log = get_logger("analytics.feedback")

# Default boost values (can be made configurable later)
EVENT_IMPORTANCE_BOOST = 0.05   # added to event.importance_score
ENTITY_MENTION_BOOST = 2         # added to entity.mention_count per viral article


def apply_traffic_feedback(
    session: Session,
    config: AppConfig,
    lookback_days: int = 7,
) -> dict:
    """Apply traffic signals to event importance and entity mention counts.

    Returns summary dict with counts of boosted events and entities.
    """
    threshold = config.features.traffic_view_threshold
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    # Find recently published high-traffic articles not yet boosted
    rows = session.execute(
        text("""
            SELECT ga.id, ga.view_count, ga.cluster_id
            FROM generated_article ga
            WHERE ga.status = 'published'
              AND ga.view_count >= :threshold
              AND ga.created_at >= :cutoff
              AND ga.traffic_boosted = 0
        """),
        {"threshold": threshold, "cutoff": cutoff},
    ).fetchall()

    boosted_events = 0
    boosted_entities = 0

    for row in rows:
        article_id = row.id
        cluster_id = row.cluster_id

        # 1. Boost parent event importance
        try:
            session.execute(
                text("""
                    UPDATE event
                    SET importance_score = MIN(1.0, COALESCE(importance_score, 0.5) + :boost)
                    WHERE cluster_id = :cluster_id
                """),
                {"boost": EVENT_IMPORTANCE_BOOST, "cluster_id": cluster_id},
            )
            boosted_events += 1
        except Exception as e:
            log.debug("Event boost failed for cluster %d: %s", cluster_id, e)

        # 2. Boost entity mention counts
        try:
            session.execute(
                text("""
                    UPDATE entity
                    SET mention_count = mention_count + :boost
                    WHERE id IN (
                        SELECT entity_id FROM entity_event_link
                        WHERE article_id = :article_id
                    )
                """),
                {"boost": ENTITY_MENTION_BOOST, "article_id": article_id},
            )
            boosted_entities += 1
        except Exception as e:
            log.debug("Entity boost failed for article %d: %s", article_id, e)

        # Mark as boosted so we don't double-apply
        try:
            session.execute(
                text("UPDATE generated_article SET traffic_boosted = 1 WHERE id = :id"),
                {"id": article_id},
            )
        except Exception as e:
            log.debug("traffic_boosted mark failed for article %d: %s", article_id, e)

    session.commit()

    log.info(
        "Traffic feedback: %d articles processed, %d events boosted, %d entity groups boosted",
        len(rows), boosted_events, boosted_entities,
    )
    return {
        "articles_processed": len(rows),
        "events_boosted": boosted_events,
        "entities_boosted": boosted_entities,
    }
