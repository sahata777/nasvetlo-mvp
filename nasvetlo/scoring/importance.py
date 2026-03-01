"""Importance scoring for clusters."""

from __future__ import annotations

from sqlalchemy.orm import Session

from nasvetlo.config import AppConfig
from nasvetlo.logging_utils import get_logger
from nasvetlo.models import Cluster, RawArticle, SourceRegistry
from nasvetlo.utils.time import hours_ago

log = get_logger("scoring.importance")

TIER_SCORES = {1: 1.0, 2: 0.8, 3: 0.6, 4: 0.3}


def compute_importance(
    session: Session,
    cluster: Cluster,
    config: AppConfig,
) -> float:
    """Compute importance score for a cluster using the configured formula."""
    items = session.query(RawArticle).filter_by(cluster_id=cluster.id).all()
    if not items:
        return 0.0

    weights = config.scoring_weights
    safety_cfg = config.safety

    # S_norm = min(1, S / 6)
    source_count = cluster.unique_domain_count
    s_norm = min(1.0, source_count / 6.0)

    # Tier_avg
    tier_scores: list[float] = []
    for item in items:
        source = session.query(SourceRegistry).filter_by(id=item.source_id).first()
        if source:
            tier_scores.append(TIER_SCORES.get(source.tier, 0.3))
    tier_avg = sum(tier_scores) / len(tier_scores) if tier_scores else 0.3

    # Speed = clamp(0, 1, 1 - span_hours / 12)
    pub_times = [item.published_at or item.fetched_at for item in items]
    if len(pub_times) >= 2:
        span = (max(pub_times) - min(pub_times)).total_seconds() / 3600.0
    else:
        span = 0.0
    speed = max(0.0, min(1.0, 1.0 - span / 12.0))

    # Institutional = 1 if any Tier1 OR keyword hit
    has_tier1 = any(
        session.query(SourceRegistry).filter_by(id=item.source_id).first()
        and (session.query(SourceRegistry).filter_by(id=item.source_id).first().tier == 1)
        for item in items
    )
    keyword_hit = False
    inst_keywords = [kw.lower() for kw in safety_cfg.institutional_keywords]
    for item in items:
        text = (item.title + " " + item.summary).lower()
        if any(kw in text for kw in inst_keywords):
            keyword_hit = True
            break
    institutional = 1.0 if (has_tier1 or keyword_hit) else 0.0

    # Decay = clamp(0, 1, age_hours / 24)
    cluster_age = hours_ago(cluster.window_end)
    decay = max(0.0, min(1.0, cluster_age / 24.0))

    # Importance formula
    importance = (
        weights.source_count * s_norm
        + weights.tier_average * tier_avg
        + weights.speed * speed
        + weights.institutional * institutional
        + weights.recency * (1.0 - decay)
    )

    return round(importance, 4)


def score_clusters(session: Session, config: AppConfig) -> int:
    """Score all candidate, coherent, non-rejected clusters. Returns count scored."""
    clusters = session.query(Cluster).filter(
        Cluster.is_candidate == True,  # noqa: E712
        Cluster.coherence_validated == True,  # noqa: E712
        Cluster.rejected == False,  # noqa: E712
        Cluster.importance_score.is_(None),
    ).all()

    scored = 0
    for cluster in clusters:
        score = compute_importance(session, cluster, config)
        cluster.importance_score = score
        log.info("Cluster %d scored %.4f", cluster.id, score)
        scored += 1

    session.commit()
    return scored


def get_eligible_clusters(session: Session, config: AppConfig, limit: int = 8) -> list[Cluster]:
    """Get clusters eligible for drafting, ordered by importance desc."""
    threshold = config.thresholds.importance_threshold
    return (
        session.query(Cluster)
        .filter(
            Cluster.is_candidate == True,  # noqa: E712
            Cluster.coherence_validated == True,  # noqa: E712
            Cluster.rejected == False,  # noqa: E712
            Cluster.drafted == False,  # noqa: E712
            Cluster.importance_score >= threshold,
        )
        .order_by(Cluster.importance_score.desc(), Cluster.window_end.desc())
        .limit(limit)
        .all()
    )
