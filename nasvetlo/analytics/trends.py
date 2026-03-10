"""Trend detection — surface hot topics, entities, and events.

Queries existing Event, Entity, and Cluster data without any new DB tables.
Called on-demand by the /dashboard/trends and /trending routes.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import TypedDict

from sqlalchemy.orm import Session

from nasvetlo.models import Entity, Event, GeneratedArticle
from nasvetlo.logging_utils import get_logger

log = get_logger("analytics.trends")


class TrendingEvent(TypedDict):
    id: int
    topic: str
    category: str
    importance_score: float
    last_updated: datetime
    article_id: int | None
    article_slug: str | None
    article_title: str | None


class TrendingEntity(TypedDict):
    id: int
    name: str
    entity_type: str
    mention_count: int
    importance_score: float
    slug: str


class TrendingTopic(TypedDict):
    topic: str
    event_count: int
    max_importance: float


class TrendsResult(TypedDict):
    events: list[TrendingEvent]
    entities: list[TrendingEntity]
    topics: list[TrendingTopic]
    lookback_hours: int
    computed_at: datetime


def compute_trends(
    session: Session,
    lookback_hours: int = 48,
    max_events: int = 10,
    max_entities: int = 15,
    max_topics: int = 10,
) -> TrendsResult:
    """Compute trending events, entities, and topics.

    Uses only existing data — no additional LLM calls or DB writes.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    # --- Trending events: recently updated, highest importance score ---
    events_q = (
        session.query(Event)
        .filter(
            Event.last_updated >= cutoff,
            Event.status != "archived",
        )
        .order_by(Event.importance_score.desc())
        .limit(max_events)
        .all()
    )

    # Batch-load related articles
    article_ids = [e.published_article_id for e in events_q if e.published_article_id]
    articles_by_id: dict[int, GeneratedArticle] = {}
    if article_ids:
        for art in session.query(GeneratedArticle).filter(
            GeneratedArticle.id.in_(article_ids)
        ).all():
            articles_by_id[art.id] = art

    trending_events: list[TrendingEvent] = []
    for ev in events_q:
        art = articles_by_id.get(ev.published_article_id) if ev.published_article_id else None
        trending_events.append({
            "id": ev.id,
            "topic": ev.topic or "—",
            "category": ev.category or "—",
            "importance_score": round(ev.importance_score or 0.0, 3),
            "last_updated": ev.last_updated,
            "article_id": ev.published_article_id,
            "article_slug": art.slug if art else None,
            "article_title": art.title if art else None,
        })

    # --- Trending entities: highest mention_count, recently updated ---
    entities_q = (
        session.query(Entity)
        .filter(Entity.last_updated >= cutoff)
        .order_by(Entity.mention_count.desc(), Entity.importance_score.desc())
        .limit(max_entities)
        .all()
    )

    trending_entities: list[TrendingEntity] = [
        {
            "id": e.id,
            "name": e.name,
            "entity_type": e.entity_type,
            "mention_count": e.mention_count,
            "importance_score": round(e.importance_score or 0.0, 3),
            "slug": e.slug,
        }
        for e in entities_q
    ]

    # --- Trending topics: group events by topic in the lookback window ---
    all_recent_events = (
        session.query(Event.topic, Event.importance_score)
        .filter(
            Event.last_updated >= cutoff,
            Event.topic.isnot(None),
            Event.status != "archived",
        )
        .all()
    )

    topic_counts: dict[str, dict] = {}
    for topic, score in all_recent_events:
        if not topic:
            continue
        if topic not in topic_counts:
            topic_counts[topic] = {"event_count": 0, "max_importance": 0.0}
        topic_counts[topic]["event_count"] += 1
        topic_counts[topic]["max_importance"] = max(
            topic_counts[topic]["max_importance"], score or 0.0
        )

    trending_topics: list[TrendingTopic] = sorted(
        [
            {
                "topic": t,
                "event_count": v["event_count"],
                "max_importance": round(v["max_importance"], 3),
            }
            for t, v in topic_counts.items()
        ],
        key=lambda x: (x["event_count"], x["max_importance"]),
        reverse=True,
    )[:max_topics]

    log.debug(
        "Trends computed: %d events, %d entities, %d topics (lookback=%dh)",
        len(trending_events), len(trending_entities), len(trending_topics), lookback_hours,
    )

    return {
        "events": trending_events,
        "entities": trending_entities,
        "topics": trending_topics,
        "lookback_hours": lookback_hours,
        "computed_at": datetime.now(timezone.utc),
    }
