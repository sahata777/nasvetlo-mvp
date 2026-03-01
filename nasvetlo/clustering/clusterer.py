"""Incremental clustering of articles into events."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from nasvetlo.config import AppConfig
from nasvetlo.logging_utils import get_logger
from nasvetlo.models import RawArticle, Cluster
from nasvetlo.utils.cosine import cosine_similarity, mean_vector
from nasvetlo.utils.text import extract_domain
from nasvetlo.utils.time import utcnow, ensure_utc
from nasvetlo.clustering.embeddings import get_embedding_provider

log = get_logger("clustering.clusterer")


def cluster_new_articles(session: Session, config: AppConfig) -> int:
    """Assign unclustered articles to clusters. Returns number of new assignments."""
    threshold = config.thresholds.similarity_threshold
    window_hours = config.thresholds.time_window_hours
    min_sources = config.thresholds.min_sources
    cutoff = utcnow() - timedelta(hours=window_hours)

    # Get unclustered articles
    unclustered = session.query(RawArticle).filter(
        RawArticle.cluster_id.is_(None)
    ).order_by(RawArticle.fetched_at.asc()).all()

    if not unclustered:
        return 0

    provider = get_embedding_provider()
    assignments = 0

    for article in unclustered:
        # Compute embedding if missing
        if article.embedding is None:
            text = f"{article.title} {article.summary}"
            article.embedding = provider.embed_single(text)

        emb = article.embedding

        # Find candidate clusters within time window
        candidates = session.query(Cluster).filter(
            Cluster.window_start >= cutoff,
            Cluster.rejected == False,  # noqa: E712
        ).all()

        best_cluster: Cluster | None = None
        best_sim = 0.0

        for cluster in candidates:
            centroid = cluster.centroid
            if not centroid:
                continue
            sim = cosine_similarity(emb, centroid)
            if sim >= threshold and sim > best_sim:
                best_sim = sim
                best_cluster = cluster

        if best_cluster is not None:
            article.cluster_id = best_cluster.id
            session.flush()
            _update_cluster(session, best_cluster, min_sources)
        else:
            # Create new cluster
            now = utcnow()
            pub = article.published_at or now
            new_cluster = Cluster(
                centroid_json="[]",
                window_start=pub,
                window_end=pub,
                unique_domain_count=1,
            )
            new_cluster.centroid = emb
            session.add(new_cluster)
            session.flush()
            article.cluster_id = new_cluster.id
            session.flush()
            _update_cluster(session, new_cluster, min_sources)

        assignments += 1

    session.commit()
    log.info("Clustered %d articles", assignments)
    return assignments


def _update_cluster(session: Session, cluster: Cluster, min_sources: int) -> None:
    """Recompute centroid, domain count, candidate status."""
    items = session.query(RawArticle).filter_by(cluster_id=cluster.id).all()

    # Update centroid
    embeddings = [item.embedding for item in items if item.embedding is not None]
    if embeddings:
        cluster.centroid = mean_vector(embeddings)

    # Update time window (ensure all are UTC-aware)
    pub_times = [ensure_utc(item.published_at) or ensure_utc(item.fetched_at) or utcnow() for item in items]
    if pub_times:
        cluster.window_start = min(pub_times)
        cluster.window_end = max(pub_times)

    # Update unique domain count
    domains = set()
    for item in items:
        domain = extract_domain(item.url)
        if domain:
            domains.add(domain)
    cluster.unique_domain_count = len(domains)

    # Mark as candidate if enough unique sources
    cluster.is_candidate = cluster.unique_domain_count >= min_sources

    session.flush()
