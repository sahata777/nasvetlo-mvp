"""Ingest RSS items into database with deduplication."""

from __future__ import annotations

from sqlalchemy.orm import Session

from nasvetlo.config import AppConfig
from nasvetlo.logging_utils import get_logger
from nasvetlo.models import SourceRegistry, RawArticle
from nasvetlo.utils.text import normalize_text, content_hash, extract_domain
from nasvetlo.utils.time import utcnow, ensure_utc
from nasvetlo.ingestion.rss import fetch_feed

log = get_logger("ingestion.normalize")


def sync_sources(session: Session, config: AppConfig) -> None:
    """Upsert source registry from config."""
    for src in config.sources:
        existing = session.query(SourceRegistry).filter_by(name=src.name).first()
        if existing:
            existing.rss_url = src.rss_url
            existing.tier = src.tier
            existing.credibility_score = src.credibility_score
            existing.enabled = src.enabled
        else:
            session.add(SourceRegistry(
                name=src.name,
                rss_url=src.rss_url,
                tier=src.tier,
                credibility_score=src.credibility_score,
                enabled=src.enabled,
            ))
    session.commit()


def ingest_all(session: Session, config: AppConfig) -> int:
    """Fetch all enabled feeds and upsert articles. Returns count of new articles."""
    sync_sources(session, config)
    sources = session.query(SourceRegistry).filter_by(enabled=True).all()
    new_count = 0

    for source in sources:
        items = fetch_feed(source.rss_url)
        for item in items:
            norm_title = normalize_text(item.title)
            norm_summary = normalize_text(item.summary)
            c_hash = content_hash(norm_title, norm_summary)

            # Dedupe by url or content_hash
            exists = session.query(RawArticle).filter(
                (RawArticle.url == item.url) | (RawArticle.content_hash == c_hash)
            ).first()

            if exists:
                continue

            article = RawArticle(
                source_id=source.id,
                url=item.url,
                title=norm_title,
                summary=norm_summary,
                content_hash=c_hash,
                published_at=ensure_utc(item.published_at),
                fetched_at=utcnow(),
            )
            session.add(article)
            new_count += 1

        source.last_fetched_at = utcnow()

    session.commit()
    log.info("Ingested %d new articles from %d sources", new_count, len(sources))
    return new_count
