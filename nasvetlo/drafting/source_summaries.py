"""Generate per-source fact summaries via LLM."""

from __future__ import annotations

from pydantic import BaseModel, Field

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


def summarize_source(article: RawArticle) -> SourceSummary:
    """Extract structured facts from a single source article."""
    from nasvetlo.utils.text import extract_domain

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

    return summary


def summarize_cluster_sources(articles: list[RawArticle], max_sources: int = 6) -> list[SourceSummary]:
    """Summarize top K sources from a cluster."""
    summaries = []
    for article in articles[:max_sources]:
        summary = summarize_source(article)
        summaries.append(summary)
    return summaries
