"""Central event registry — persistent event identity across pipeline cycles.

An Event represents a real-world news event that may be reported across
multiple sources over multiple pipeline cycles.  The registry prevents
duplicate article generation and accumulates context over time.

Core operations
---------------
- ``sync_event_registry`` — called after scoring; links every coherent
  cluster to either an existing Event or a newly created one.
- ``get_event_for_cluster`` — look up the Event for a cluster_id.
- ``mark_event_published`` — record that an article was generated for an
  event so future cycles can skip re-drafting it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from nasvetlo.config import AppConfig
from nasvetlo.logging_utils import get_logger
from nasvetlo.models import Cluster, Event, RawArticle
from nasvetlo.utils.cosine import cosine_similarity

log = get_logger("events.registry")

# Minimum cosine similarity between a cluster centroid and an event centroid
# for them to be considered the same real-world event.
# Set deliberately higher than the clustering threshold (0.80) to avoid
# false merges across semantically related but distinct stories.
EVENT_SIMILARITY_THRESHOLD = 0.82


def find_existing_event(
    session: Session,
    cluster_embedding: list[float],
    threshold: float = EVENT_SIMILARITY_THRESHOLD,
) -> Optional[Event]:
    """Return the active event most similar to ``cluster_embedding``.

    Scans all non-archived events and returns the best match whose
    similarity is at or above ``threshold``.  Returns ``None`` if no
    suitable match is found.
    """
    candidates = session.query(Event).filter(
        Event.status.in_(["new", "active", "published"])
    ).all()

    best_event: Optional[Event] = None
    best_score = 0.0

    for event in candidates:
        if not event.embedding_json:
            continue
        centroid = json.loads(event.embedding_json)
        if not centroid:
            continue
        score = cosine_similarity(cluster_embedding, centroid)
        if score >= threshold and score > best_score:
            best_score = score
            best_event = event

    if best_event:
        log.debug(
            "Matched cluster to existing event %d (similarity=%.4f)",
            best_event.id, best_score,
        )
    return best_event


def create_event_from_cluster(session: Session, cluster: Cluster) -> Event:
    """Create and persist a new Event from a coherent, scored cluster."""
    items = session.query(RawArticle).filter_by(cluster_id=cluster.id).all()
    source_urls = [item.url for item in items]

    event = Event(
        cluster_id=cluster.id,
        embedding_json=cluster.centroid_json,
        first_seen=cluster.window_start,
        last_updated=cluster.window_end,
        source_urls_json=json.dumps(source_urls, ensure_ascii=False),
        importance_score=cluster.importance_score or 0.0,
        cluster_score=cluster.coherence_confidence or 0.0,
        status="new",
    )
    session.add(event)
    session.flush()
    log.info("Created event %d from cluster %d", event.id, cluster.id)
    return event


def update_event_from_cluster(session: Session, event: Event, cluster: Cluster) -> Event:
    """Merge new cluster data into an existing event.

    - Merges source URLs (no duplicates, order preserved)
    - Advances centroid and importance_score if the new cluster scores higher
    - Transitions status from ``new`` → ``active`` on first update
    """
    now = datetime.now(timezone.utc)

    existing_urls: list[str] = json.loads(event.source_urls_json or "[]")
    new_items = session.query(RawArticle).filter_by(cluster_id=cluster.id).all()
    new_urls = [item.url for item in new_items]
    # dict.fromkeys preserves insertion order and deduplicates
    merged = list(dict.fromkeys(existing_urls + new_urls))

    event.source_urls_json = json.dumps(merged, ensure_ascii=False)
    event.last_updated = now

    if (cluster.importance_score or 0.0) > event.importance_score:
        event.embedding_json = cluster.centroid_json
        event.importance_score = cluster.importance_score or event.importance_score

    if event.status == "new":
        event.status = "active"

    session.flush()
    log.info(
        "Updated event %d with cluster %d (%d total sources)",
        event.id, cluster.id, len(merged),
    )
    return event


def sync_event_registry(session: Session, config: AppConfig) -> dict:
    """Link every unregistered coherent cluster to an event record.

    For each coherent, scored cluster not yet associated with an Event:
    - If a similar event exists (similarity >= threshold): update it
    - Otherwise: create a new event

    Called after importance scoring, before draft generation.

    Returns
    -------
    dict with keys ``created`` and ``updated`` (both int).
    """
    # Cluster IDs already registered — skip them
    linked_cluster_ids: set[int] = {
        row[0]
        for row in session.query(Event.cluster_id)
        .filter(Event.cluster_id.isnot(None))
        .all()
    }

    unlinked = session.query(Cluster).filter(
        Cluster.is_candidate == True,        # noqa: E712
        Cluster.coherence_validated == True,  # noqa: E712
        Cluster.rejected == False,            # noqa: E712
        Cluster.importance_score.isnot(None),
    ).all()

    unlinked = [c for c in unlinked if c.id not in linked_cluster_ids]

    created = 0
    updated = 0

    for cluster in unlinked:
        centroid = cluster.centroid
        if not centroid:
            continue

        existing = find_existing_event(session, centroid)
        if existing:
            update_event_from_cluster(session, existing, cluster)
            updated += 1
        else:
            create_event_from_cluster(session, cluster)
            created += 1

    session.commit()
    log.info(
        "Event registry sync complete: created=%d, updated=%d", created, updated
    )
    return {"created": created, "updated": updated}


def get_event_for_cluster(session: Session, cluster_id: int) -> Optional[Event]:
    """Return the Event linked to ``cluster_id``, or ``None``."""
    return session.query(Event).filter_by(cluster_id=cluster_id).first()


def mark_event_published(session: Session, event_id: int, article_id: int) -> None:
    """Record that a generated article was created for this event."""
    event = session.get(Event, event_id)
    if event:
        event.published_article_id = article_id
        event.status = "published"
        session.flush()
        log.debug("Event %d linked to article %d", event_id, article_id)
