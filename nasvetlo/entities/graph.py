"""Knowledge graph management — entity upsert and event/article linking.

Maintains the ``entity`` table and the ``entity_event_link`` join table.
Called after each article draft to register extracted entities and connect
them to the event and article that surfaced them.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from nasvetlo.logging_utils import get_logger
from nasvetlo.models import Entity, EntityEventLink, Event, GeneratedArticle
from nasvetlo.utils.text import slugify
from nasvetlo.entities.extractor import ExtractionResult, EntityItem

log = get_logger("entities.graph")

# Map from ExtractionResult field name → entity_type string stored in DB
_FIELD_TO_TYPE: dict[str, str] = {
    "people": "person",
    "organizations": "organization",
    "locations": "location",
    "companies": "company",
    "laws": "law",
}


def get_or_create_entity(
    session: Session,
    name: str,
    entity_type: str,
) -> Entity:
    """Return existing entity or create a new one.

    Lookup is by (name, entity_type).  The slug is generated from the name;
    if a slug collision occurs with a different entity type, the entity_type
    is appended to ensure global uniqueness.
    """
    now = datetime.now(timezone.utc)

    # Primary lookup by normalised name + type
    existing = (
        session.query(Entity)
        .filter_by(name=name, entity_type=entity_type)
        .first()
    )
    if existing:
        existing.mention_count += 1
        existing.last_updated = now
        session.flush()
        return existing

    # New entity — generate a unique slug
    base_slug = slugify(name, max_length=250)
    slug = base_slug or slugify(entity_type + "-" + name[:30], max_length=250)

    # Check for slug collision with a different entity type
    slug_owner = session.query(Entity).filter_by(slug=slug).first()
    if slug_owner is not None and slug_owner.entity_type != entity_type:
        slug = f"{base_slug}-{entity_type}"

    entity = Entity(
        name=name,
        entity_type=entity_type,
        slug=slug,
        first_seen=now,
        last_updated=now,
        mention_count=1,
        importance_score=0.0,
    )
    session.add(entity)
    session.flush()
    log.debug("Created entity: %s (%s) slug=%s", name, entity_type, slug)
    return entity


def link_entity_to_event(
    session: Session,
    entity: Entity,
    event_id: Optional[int],
    article_id: Optional[int],
    role: str = "mentioned",
) -> None:
    """Create an EntityEventLink edge if one does not already exist."""
    # Avoid duplicate edges for the same (entity, article) pair
    if article_id is not None:
        exists = (
            session.query(EntityEventLink)
            .filter_by(entity_id=entity.id, article_id=article_id)
            .first()
        )
        if exists:
            return

    link = EntityEventLink(
        entity_id=entity.id,
        event_id=event_id,
        article_id=article_id,
        role=role,
    )
    session.add(link)
    session.flush()


def process_article_entities(
    session: Session,
    article: GeneratedArticle,
    event: Optional[Event],
    extraction: ExtractionResult,
) -> int:
    """Upsert all extracted entities and create knowledge graph edges.

    Also writes the extracted entity names back to ``event.entities_json``
    so future context retrieval can include structured entity information.

    Returns the total number of entity records processed.
    """
    event_id = event.id if event else None
    article_id = article.id

    entity_map: dict[str, list[str]] = {
        "people": [],
        "organizations": [],
        "locations": [],
        "companies": [],
        "laws": [],
    }

    total = 0
    for field_name, entity_type in _FIELD_TO_TYPE.items():
        items: list[EntityItem] = getattr(extraction, field_name, [])
        for item in items:
            name = item.name.strip()
            if not name:
                continue
            try:
                entity = get_or_create_entity(session, name, entity_type)
                link_entity_to_event(
                    session, entity, event_id, article_id, role=item.role
                )
                entity_map[field_name].append(name)
                total += 1
            except Exception as e:
                log.warning(
                    "Failed to process entity '%s' (%s): %s", name, entity_type, e
                )

    # Persist extracted entity names to the event for future context retrieval
    if event is not None:
        event.entities_json = json.dumps(entity_map, ensure_ascii=False)
        session.flush()

    session.commit()
    log.info(
        "Processed %d entities for article %d (event %s)",
        total, article_id, event_id,
    )
    return total
