"""LLM-based coherence validation for clusters."""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from nasvetlo.config import AppConfig
from nasvetlo.logging_utils import get_logger
from nasvetlo.models import Cluster, RawArticle
from nasvetlo.utils.text import extract_domain
from nasvetlo.llm import load_prompt, call_llm_json

log = get_logger("clustering.coherence")


class CoherenceResult(BaseModel):
    same_event: bool
    confidence: float = Field(ge=0.0, le=1.0)
    short_reason: str = ""


def validate_cluster_coherence(session: Session, cluster: Cluster, config: AppConfig) -> bool:
    """Validate that a cluster represents a single real event. Returns True if coherent."""
    items = session.query(RawArticle).filter_by(cluster_id=cluster.id).all()
    if not items:
        return False

    # Build compact input for LLM
    source_lines = []
    for item in items[:8]:  # Cap at 8 sources for prompt length
        domain = extract_domain(item.url)
        pub = item.published_at.isoformat() if item.published_at else "unknown"
        summary_short = item.summary[:200] if item.summary else ""
        source_lines.append(
            f"- [{domain}] {item.title} | {summary_short} | {pub}"
        )
    sources_text = "\n".join(source_lines)

    system_prompt = load_prompt("coherence_validator.txt")
    user_prompt = f"Analyse these {len(items)} articles from different sources:\n\n{sources_text}"

    try:
        result_dict = call_llm_json(system=system_prompt, user=user_prompt)
        result = CoherenceResult(**result_dict)
    except (ValueError, Exception) as e:
        log.error("Coherence validation failed for cluster %d: %s", cluster.id, e)
        cluster.rejected = True
        cluster.reject_reason = f"LLM error: {e}"
        session.flush()
        return False

    cluster.coherence_validated = True
    cluster.coherence_confidence = result.confidence

    min_confidence = config.thresholds.coherence_confidence_min

    if not result.same_event or result.confidence < min_confidence:
        cluster.rejected = True
        cluster.reject_reason = f"Not same event (confidence={result.confidence:.2f}): {result.short_reason}"
        log.info("Cluster %d rejected: %s", cluster.id, cluster.reject_reason)
        session.flush()
        return False

    log.info("Cluster %d coherent (confidence=%.2f): %s", cluster.id, result.confidence, result.short_reason)
    session.flush()
    return True


def validate_candidates(session: Session, config: AppConfig) -> int:
    """Validate all unvalidated candidate clusters. Returns count validated."""
    candidates = session.query(Cluster).filter(
        Cluster.is_candidate == True,  # noqa: E712
        Cluster.coherence_validated == False,  # noqa: E712
        Cluster.rejected == False,  # noqa: E712
    ).all()

    validated = 0
    for cluster in candidates:
        if validate_cluster_coherence(session, cluster, config):
            validated += 1

    session.commit()
    return validated
