"""Generate per-source fact summaries via LLM.

Summaries are cached in ``raw_article.summary_cache_json`` so the same source
article is never summarised twice across pipeline cycles.  Pass a SQLAlchemy
session to enable caching; without a session the call always hits the LLM.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from nasvetlo.logging_utils import get_logger
from nasvetlo.models import RawArticle
from nasvetlo.llm import load_prompt, call_llm_json

log = get_logger("drafting.source_summaries")


class SourceSummary(BaseModel):
    source_url: str = ""
    source_domain: str = ""
    key_facts: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    numbers_dates: list[str] = Field(default_factory=list)
    source_stance: str = "neutral"


def summarize_source(
    article: RawArticle,
    session: Optional[Session] = None,
) -> SourceSummary:
    """Extract structured facts from a single source article.

    If *session* is provided, checks ``raw_article.summary_cache_json`` first
    and writes the result back after a fresh LLM call.
    """
    from nasvetlo.utils.text import extract_domain

    # --- Cache read ---
    if session is not None and article.summary_cache_json:
        try:
            cached = json.loads(article.summary_cache_json)
            log.debug("Cache hit for article %d (%s)", article.id, article.url)
            return SourceSummary(**cached)
        except Exception:
            pass  # Corrupt cache — fall through to LLM

    system_prompt = load_prompt("source_summary_json.txt")
    user_text = f"Title: {article.title}\n\nSummary: {article.summary}"

    try:
        result = call_llm_json(system=system_prompt, user=user_text)
        summary = SourceSummary(
            source_url=article.url,
            source_domain=extract_domain(article.url),
            **result,
        )
    except (ValueError, Exception) as e:
        log.error("Failed to summarize article %d: %s", article.id, e)
        summary = SourceSummary(
            source_url=article.url,
            source_domain=extract_domain(article.url),
            key_facts=[article.title],
        )

    # --- Cache write ---
    if session is not None:
        try:
            article.summary_cache_json = json.dumps(
                summary.model_dump(), ensure_ascii=False
            )
        except Exception:
            pass  # Non-critical — proceed without caching

    return summary


def summarize_cluster_sources(
    articles: list[RawArticle],
    max_sources: int = 6,
    session: Optional[Session] = None,
) -> list[SourceSummary]:
    """Summarize top K sources from a cluster.

    Pass *session* to enable per-article summary caching.
    """
    summaries = []
    cached_count = 0
    for article in articles[:max_sources]:
        had_cache = bool(article.summary_cache_json)
        summary = summarize_source(article, session=session)
        summaries.append(summary)
        if had_cache:
            cached_count += 1

    if cached_count:
        log.info("Source summary cache: %d/%d hits", cached_count, len(summaries))

    return summaries
