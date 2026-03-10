"""Evergreen explainer page generation for frequently mentioned entities.

Generates and maintains structured /entity/{slug} explainer pages for any
entity whose mention_count reaches the configured threshold.

Each explainer provides: definition, importance, background, timeline,
and key facts — all in Bulgarian, derived from recent article context.

The pipeline calls ``run_evergreen_explainers`` once per cycle after all
draft generation is complete.  Up to EXPLAINERS_PER_RUN pages are generated
per cycle to keep LLM cost bounded.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from nasvetlo.config import AppConfig
from nasvetlo.logging_utils import get_logger
from nasvetlo.models import Entity, EntityEventLink, GeneratedArticle
from nasvetlo.llm import load_prompt, call_llm_json
from nasvetlo.utils.time import utcnow

log = get_logger("entities.explainer")

# Hard cap on explainers generated per pipeline cycle (LLM cost control)
EXPLAINERS_PER_RUN = 3


class ExplainerResult(BaseModel):
    title: str = ""
    definition: str = ""
    importance: str = ""
    background: str = ""
    timeline: list[dict] = Field(default_factory=list)
    key_facts: list[str] = Field(default_factory=list)


def get_recent_articles_for_entity(
    session: Session,
    entity: Entity,
    limit: int = 5,
) -> list[GeneratedArticle]:
    """Return the most recent articles (any review status) mentioning ``entity``."""
    links = (
        session.query(EntityEventLink)
        .filter(
            EntityEventLink.entity_id == entity.id,
            EntityEventLink.article_id.isnot(None),
        )
        .all()
    )
    article_ids = [lnk.article_id for lnk in links if lnk.article_id]
    if not article_ids:
        return []
    return (
        session.query(GeneratedArticle)
        .filter(
            GeneratedArticle.id.in_(article_ids),
            GeneratedArticle.status.in_(["pending", "approved", "published"]),
        )
        .order_by(GeneratedArticle.created_at.desc())
        .limit(limit)
        .all()
    )


def _default_title(entity: Entity) -> str:
    """Fallback Bulgarian title when LLM does not produce one."""
    titles = {
        "person": f"Кой е {entity.name}?",
        "organization": f"{entity.name} — какво е?",
        "location": f"{entity.name} — всичко важно",
        "company": f"{entity.name} — профил",
        "law": f"{entity.name} — обяснено",
    }
    return titles.get(entity.entity_type, entity.name)


def generate_explainer(
    entity: Entity,
    articles: list[GeneratedArticle],
) -> ExplainerResult:
    """Call LLM to produce a structured explainer for ``entity``.

    Uses article titles + meta descriptions as low-cost context.
    Returns empty ExplainerResult on failure so the pipeline is never blocked.
    """
    system_prompt = load_prompt("entity_explainer.txt")

    if articles:
        lines = [
            f"- [{a.created_at.strftime('%d.%m.%Y')}] {a.title}: {a.meta_description}"
            for a in articles
        ]
        articles_block = "Recent articles mentioning this entity:\n" + "\n".join(lines)
    else:
        articles_block = "No recent articles available."

    user_prompt = (
        f"Entity name: {entity.name}\n"
        f"Entity type: {entity.entity_type}\n"
        f"Mention count: {entity.mention_count}\n\n"
        f"{articles_block}"
    )

    try:
        raw = call_llm_json(system=system_prompt, user=user_prompt)
        result = ExplainerResult(**raw)
        if not result.title:
            result.title = _default_title(entity)
        log.info(
            "Generated explainer for entity %d (%s): def=%d chars",
            entity.id, entity.name, len(result.definition),
        )
        return result
    except Exception as e:
        log.error("Explainer LLM call failed for entity %s: %s", entity.name, e)
        return ExplainerResult(title=_default_title(entity))


def build_explainer_html(result: ExplainerResult, entity: Entity) -> str:
    """Render ExplainerResult as a self-contained HTML block."""
    parts: list[str] = [
        f'<div class="entity-explainer" data-entity-type="{entity.entity_type}">'
    ]

    if result.definition:
        parts.append(
            '<section class="explainer-definition">'
            "<h2>Определение</h2>"
            f"<p>{result.definition}</p>"
            "</section>"
        )

    if result.importance:
        parts.append(
            '<section class="explainer-importance">'
            "<h2>Защо е важно</h2>"
            f"<p>{result.importance}</p>"
            "</section>"
        )

    if result.background:
        parts.append(
            '<section class="explainer-background">'
            "<h2>История</h2>"
            f"<p>{result.background}</p>"
            "</section>"
        )

    if result.timeline:
        items = "".join(
            f'<li><strong>{entry.get("date", "")}</strong>'
            f' — {entry.get("fact", "")}</li>'
            for entry in result.timeline
            if entry.get("fact")
        )
        if items:
            parts.append(
                '<section class="explainer-timeline">'
                "<h2>Хронология</h2>"
                f"<ul>{items}</ul>"
                "</section>"
            )

    if result.key_facts:
        facts_html = "".join(
            f"<li>{fact}</li>" for fact in result.key_facts if fact
        )
        if facts_html:
            parts.append(
                '<section class="explainer-facts">'
                "<h2>Ключови факти</h2>"
                f"<ul>{facts_html}</ul>"
                "</section>"
            )

    parts.append("</div>")
    return "\n".join(parts)


def run_evergreen_explainers(
    session: Session,
    config: AppConfig,
    dry_run: bool = False,
) -> int:
    """Generate or refresh explainers for qualifying entities.

    Selects entities where:
    - mention_count >= evergreen_mention_threshold
    - explainer_html is NULL  OR  explainer_updated_at < stale_cutoff

    Generates up to EXPLAINERS_PER_RUN per cycle.  Publishes to WordPress
    as draft pages unless dry_run is True.

    Returns the count of explainers generated.
    """
    threshold = config.features.evergreen_mention_threshold
    refresh_days = config.features.evergreen_refresh_days
    now = utcnow()
    stale_cutoff = now - timedelta(days=refresh_days)

    candidates = (
        session.query(Entity)
        .filter(Entity.mention_count >= threshold)
        .filter(
            (Entity.explainer_html.is_(None))
            | (Entity.explainer_updated_at < stale_cutoff)
        )
        .order_by(Entity.mention_count.desc())
        .limit(EXPLAINERS_PER_RUN)
        .all()
    )

    if not candidates:
        log.debug("No entities qualify for explainer generation this cycle.")
        return 0

    log.info(
        "Evergreen explainers: %d candidates (threshold=%d, refresh=%dd)",
        len(candidates), threshold, refresh_days,
    )
    generated = 0

    for entity in candidates:
        try:
            articles = get_recent_articles_for_entity(session, entity, limit=5)
            result = generate_explainer(entity, articles)

            entity.explainer_html = build_explainer_html(result, entity)
            entity.explainer_updated_at = now

            if not dry_run:
                from nasvetlo.publishing.wordpress import publish_entity_page
                wp_page = publish_entity_page(
                    title=result.title or _default_title(entity),
                    body_html=entity.explainer_html,
                    slug=entity.slug,
                    existing_wp_page_id=entity.wp_page_id,
                )
                if wp_page and wp_page.get("id"):
                    entity.wp_page_id = wp_page["id"]
                    log.info(
                        "Entity page published to WP: id=%d slug=%s",
                        wp_page["id"], entity.slug,
                    )

            generated += 1

        except Exception as e:
            log.error(
                "Explainer failed for entity %d (%s): %s",
                entity.id, entity.name, e,
            )

    session.commit()
    log.info("Evergreen explainers complete: %d generated.", generated)
    return generated
