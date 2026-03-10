"""Context retrieval from the Event registry for article enrichment.

Finds past related events and builds a structured context dict that the
context expander uses to add background, timeline, and forward-looking
sections to each drafted article.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from nasvetlo.logging_utils import get_logger
from nasvetlo.models import Event, GeneratedArticle
from nasvetlo.utils.cosine import cosine_similarity

log = get_logger("events.context")

# Looser than the event identity threshold (0.82) — we want thematic
# neighbours, not just exact duplicates.
RELATED_EVENT_THRESHOLD = 0.65
RELATED_EVENT_LIMIT = 3


def get_related_events(
    session: Session,
    event: Event,
    top_k: int = RELATED_EVENT_LIMIT,
) -> list[Event]:
    """Return the top-K published events most similar to ``event``.

    Only considers events that already have a published article so we can
    pull their summaries as background context.  Excludes the event itself.
    """
    if not event.embedding_json:
        return []

    my_centroid = json.loads(event.embedding_json)
    if not my_centroid:
        return []

    # Fetch the most recent published events as candidates (hard limit 50
    # to keep the similarity scan fast on SQLite).
    candidates = (
        session.query(Event)
        .filter(
            Event.id != event.id,
            Event.status == "published",
            Event.published_article_id.isnot(None),
        )
        .order_by(Event.last_updated.desc())
        .limit(50)
        .all()
    )

    scored: list[tuple[float, Event]] = []
    for candidate in candidates:
        if not candidate.embedding_json:
            continue
        centroid = json.loads(candidate.embedding_json)
        score = cosine_similarity(my_centroid, centroid)
        if score >= RELATED_EVENT_THRESHOLD:
            scored.append((score, candidate))

    scored.sort(key=lambda x: x[0], reverse=True)
    result = [ev for _, ev in scored[:top_k]]
    log.debug("Found %d related events for event %d", len(result), event.id)
    return result


def build_event_context(session: Session, event: Event) -> dict:
    """Build a context dict for ``event`` suitable for the context expander.

    Returns
    -------
    dict with keys:
    - ``related_events``: list of dicts with ``title``, ``date``, ``summary``
    - ``existing_timeline``: list from ``event.timeline_json`` (may be empty)
    - ``existing_background``: str from ``event.background_json`` (may be "")
    """
    related = get_related_events(session, event)

    related_summaries: list[dict] = []
    for rel in related:
        if not rel.published_article_id:
            continue
        article = session.get(GeneratedArticle, rel.published_article_id)
        if not article:
            continue
        date_str = rel.first_seen.strftime("%d.%m.%Y") if rel.first_seen else ""
        summary = (
            article.meta_description
            or (article.body_text[:200] if article.body_text else "")
        )
        related_summaries.append(
            {"title": article.title, "date": date_str, "summary": summary}
        )

    existing_timeline: list = json.loads(event.timeline_json or "[]")

    background_raw = json.loads(event.background_json or "{}")
    existing_background: str = (
        background_raw.get("text", "")
        if isinstance(background_raw, dict)
        else ""
    )

    return {
        "related_events": related_summaries,
        "existing_timeline": existing_timeline,
        "existing_background": existing_background,
    }
