"""SQLAlchemy ORM models."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    String, Integer, Float, Text, Boolean, DateTime, ForeignKey, Index
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SourceRegistry(Base):
    __tablename__ = "source_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    rss_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    credibility_score: Mapped[float] = mapped_column(Float, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    articles: Mapped[list["RawArticle"]] = relationship(back_populates="source")


class RawArticle(Base):
    __tablename__ = "raw_article"
    __table_args__ = (
        Index("ix_raw_article_content_hash", "content_hash"),
        Index("ix_raw_article_url", "url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("source_registry.id"), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    embedding_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cluster_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("cluster.id"), nullable=True)

    source: Mapped["SourceRegistry"] = relationship(back_populates="articles")
    cluster: Mapped[Optional["Cluster"]] = relationship(back_populates="items")

    @property
    def embedding(self) -> list[float] | None:
        if self.embedding_json is None:
            return None
        return json.loads(self.embedding_json)

    @embedding.setter
    def embedding(self, value: list[float] | None) -> None:
        self.embedding_json = json.dumps(value) if value is not None else None


class Cluster(Base):
    __tablename__ = "cluster"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    centroid_json: Mapped[str] = mapped_column(Text, default="[]")
    window_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    unique_domain_count: Mapped[int] = mapped_column(Integer, default=0)
    is_candidate: Mapped[bool] = mapped_column(Boolean, default=False)
    coherence_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    coherence_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rejected: Mapped[bool] = mapped_column(Boolean, default=False)
    reject_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    importance_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    drafted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    items: Mapped[list["RawArticle"]] = relationship(back_populates="cluster")

    @property
    def centroid(self) -> list[float]:
        return json.loads(self.centroid_json)

    @centroid.setter
    def centroid(self, value: list[float]) -> None:
        self.centroid_json = json.dumps(value)


class GeneratedArticle(Base):
    __tablename__ = "generated_article"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cluster_id: Mapped[int] = mapped_column(Integer, ForeignKey("cluster.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    seo_title: Mapped[str] = mapped_column(Text, default="")
    meta_description: Mapped[str] = mapped_column(Text, default="")
    slug: Mapped[str] = mapped_column(String(512), default="")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    category_id: Mapped[int] = mapped_column(Integer, default=1)
    safety_risk_level: Mapped[str] = mapped_column(String(20), default="low")
    safety_flags_json: Mapped[str] = mapped_column(Text, default="[]")
    headline_variants_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    legal_risk_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_urls_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    editor_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    cluster: Mapped["Cluster"] = relationship()

    @property
    def tags(self) -> list[str]:
        return json.loads(self.tags_json)

    @tags.setter
    def tags(self, value: list[str]) -> None:
        self.tags_json = json.dumps(value, ensure_ascii=False)

    @property
    def source_urls(self) -> list[str]:
        return json.loads(self.source_urls_json)

    @source_urls.setter
    def source_urls(self, value: list[str]) -> None:
        self.source_urls_json = json.dumps(value, ensure_ascii=False)

    @property
    def safety_flags(self) -> list[str]:
        return json.loads(self.safety_flags_json)


class Event(Base):
    """Persistent record of a real-world news event across pipeline cycles.

    An Event is created the first time a coherent cluster appears.  When
    subsequent pipeline cycles produce clusters about the same story, the
    existing Event is updated rather than a new article being generated.
    This is the foundation of the event intelligence layer.
    """
    __tablename__ = "event"
    __table_args__ = (
        Index("ix_event_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Primary cluster that created this event (may be updated on refresh)
    cluster_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("cluster.id"), nullable=True
    )
    # Centroid embedding for similarity matching (same 384-dim format as raw_article)
    embedding_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Extracted entities: {"people": [], "orgs": [], "locations": [], "laws": []}
    entities_json: Mapped[str] = mapped_column(Text, default="{}")
    first_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_updated: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # All source URLs contributed to this event across all updates
    source_urls_json: Mapped[str] = mapped_column(Text, default="[]")
    topic: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    importance_score: Mapped[float] = mapped_column(Float, default=0.0)
    cluster_score: Mapped[float] = mapped_column(Float, default=0.0)
    # new → active (after first update) → published (after article created) → archived
    status: Mapped[str] = mapped_column(String(20), default="new")
    published_article_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("generated_article.id"), nullable=True
    )
    # Retrieved context from past related events (Phase 4)
    background_json: Mapped[str] = mapped_column(Text, default="{}")
    # Ordered timeline of key moments: [{"date": "...", "fact": "..."}, ...]
    timeline_json: Mapped[str] = mapped_column(Text, default="[]")
    # IDs of related events (Phase 4 cross-linking)
    related_event_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    cluster: Mapped[Optional["Cluster"]] = relationship(foreign_keys=[cluster_id])
    published_article: Mapped[Optional["GeneratedArticle"]] = relationship(
        foreign_keys=[published_article_id]
    )

    @property
    def source_urls(self) -> list[str]:
        return json.loads(self.source_urls_json)

    @property
    def entities(self) -> dict:
        return json.loads(self.entities_json)

    @property
    def related_event_ids(self) -> list[int]:
        return json.loads(self.related_event_ids_json)


class PublishingLog(Base):
    __tablename__ = "publishing_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(Integer, ForeignKey("generated_article.id"), nullable=False)
    cluster_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(50), default="created")
    actor: Mapped[str] = mapped_column(String(100), default="pipeline")
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    wp_post_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    wp_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class RunLog(Base):
    __tablename__ = "run_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="running")
    articles_ingested: Mapped[int] = mapped_column(Integer, default=0)
    clusters_formed: Mapped[int] = mapped_column(Integer, default=0)
    drafts_created: Mapped[int] = mapped_column(Integer, default=0)
    drafts_published: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    error_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)


class Entity(Base):
    """A named entity (person, org, location, company, or law) mentioned in articles.

    Entities are upserted by (name, entity_type).  The slug is used for
    public-facing URLs such as /entity/borisov-boyko.  mention_count and
    importance_score are updated every time a new article references the entity.
    """
    __tablename__ = "entity"
    __table_args__ = (
        Index("ix_entity_slug", "slug", unique=True),
        Index("ix_entity_type_name", "entity_type", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # person | organization | location | company | law
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # URL-safe slug — unique across all entity types
    slug: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    # Auto-generated or editor-written description (Phase 6 will expand this)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # WordPress entity page ID (set when the entity page is published — Phase 6)
    wp_page_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_updated: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    mention_count: Mapped[int] = mapped_column(Integer, default=1)
    importance_score: Mapped[float] = mapped_column(Float, default=0.0)
    # Phase 6 — Evergreen explainer content
    explainer_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    explainer_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    links: Mapped[list["EntityEventLink"]] = relationship(back_populates="entity")


class EntityEventLink(Base):
    """Knowledge graph edge: an entity mentioned in an event / article.

    Captures the role the entity plays (subject, mentioned, location, etc.)
    and provides the many-to-many join between entities and events/articles.
    """
    __tablename__ = "entity_event_link"
    __table_args__ = (
        Index("ix_eel_entity_id", "entity_id"),
        Index("ix_eel_event_id", "event_id"),
        Index("ix_eel_article_id", "article_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[int] = mapped_column(Integer, ForeignKey("entity.id"), nullable=False)
    event_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("event.id"), nullable=True
    )
    article_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("generated_article.id"), nullable=True
    )
    # subject | mentioned | location | organization
    role: Mapped[str] = mapped_column(String(30), default="mentioned")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    entity: Mapped["Entity"] = relationship(back_populates="links")


class SearchPage(Base):
    """A question-based search capture page derived from a news article.

    Each article produces several SearchPages — one per likely user question.
    Pages are served at /q/{slug} and included in sitemap.xml so search
    engines can index them independently from the main article.

    Visibility is controlled by the parent article's status: a SearchPage is
    only served publicly when its GeneratedArticle has status='published'.
    """
    __tablename__ = "search_page"
    __table_args__ = (
        Index("ix_search_page_slug", "slug", unique=True),
        Index("ix_search_page_article_id", "article_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("generated_article.id"), nullable=False
    )
    event_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("event.id"), nullable=True
    )
    # The search question, e.g. "Защо ЕС въведе санкции срещу Русия?"
    question: Mapped[str] = mapped_column(Text, nullable=False)
    # URL-safe slug (Latin transliteration of the question)
    slug: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    # HTML answer (2-3 paragraphs in Bulgarian)
    body_html: Mapped[str] = mapped_column(Text, default="")
    # SEO meta description for this question page
    meta_description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    article: Mapped["GeneratedArticle"] = relationship(foreign_keys=[article_id])
