"""Single pipeline run orchestrator."""

from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from nasvetlo.config import AppConfig
from nasvetlo.db import get_session, init_db
from nasvetlo.logging_utils import get_logger
from nasvetlo.models import (
    Cluster, RawArticle, GeneratedArticle, PublishingLog, RunLog,
)
from nasvetlo.ingestion.normalize import ingest_all
from nasvetlo.clustering.clusterer import cluster_new_articles
from nasvetlo.clustering.coherence import validate_candidates
from nasvetlo.scoring.importance import score_clusters, get_eligible_clusters
from nasvetlo.drafting.source_summaries import summarize_cluster_sources
from nasvetlo.drafting.synthesis import merge_facts
from nasvetlo.drafting.writer import write_article
from nasvetlo.drafting.self_edit import self_edit
from nasvetlo.drafting.safety import full_safety_gate
from nasvetlo.drafting.seo import generate_seo
from nasvetlo.utils.time import utcnow

log = get_logger("pipeline.run_once")


def _count_today_drafts(session: Session) -> int:
    """Count drafts created today."""
    today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return session.query(GeneratedArticle).filter(
        GeneratedArticle.created_at >= today_start
    ).count()


def _count_recent_high_risk(session: Session, hours: int = 24) -> int:
    """Count high-risk articles in the last N hours."""
    cutoff = utcnow() - timedelta(hours=hours)
    return session.query(GeneratedArticle).filter(
        GeneratedArticle.created_at >= cutoff,
        GeneratedArticle.safety_risk_level == "high",
    ).count()


def _is_paused(session: Session) -> bool:
    """Check if pipeline is paused."""
    last_run = session.query(RunLog).order_by(RunLog.id.desc()).first()
    return last_run.is_paused if last_run else False


def _set_paused(session: Session, paused: bool) -> None:
    """Set pause state."""
    run_log = RunLog(
        started_at=utcnow(),
        finished_at=utcnow(),
        status="paused" if paused else "resumed",
        is_paused=paused,
    )
    session.add(run_log)
    session.commit()


def run_pipeline(
    config: AppConfig,
    dry_run: bool = False,
    max_drafts: int | None = None,
) -> dict:
    """Execute the full pipeline once. Returns summary dict."""
    init_db()
    session = get_session()
    summary = {
        "articles_ingested": 0,
        "clusters_formed": 0,
        "coherence_validated": 0,
        "clusters_scored": 0,
        "drafts_created": 0,
        "drafts_published": 0,
        "errors": 0,
        "error_details": [],
        "dry_run": dry_run,
    }

    run_log = RunLog(started_at=utcnow(), status="running")
    session.add(run_log)
    session.commit()

    try:
        # Check pause
        if _is_paused(session):
            log.warning("Pipeline is PAUSED. Use 'nasvetlo resume' to continue.")
            run_log.status = "skipped_paused"
            run_log.finished_at = utcnow()
            session.commit()
            summary["status"] = "paused"
            return summary

        # Step 1: Ingest
        log.info("=== STEP 1: Ingestion ===")
        try:
            new_articles = ingest_all(session, config)
            summary["articles_ingested"] = new_articles
        except Exception as e:
            log.error("Ingestion failed: %s", e)
            summary["errors"] += 1
            summary["error_details"].append(f"ingestion: {e}")

        # Step 2: Cluster
        log.info("=== STEP 2: Clustering ===")
        try:
            clustered = cluster_new_articles(session, config)
            summary["clusters_formed"] = clustered
        except Exception as e:
            log.error("Clustering failed: %s", e)
            summary["errors"] += 1
            summary["error_details"].append(f"clustering: {e}")

        # Step 3: Coherence validation
        log.info("=== STEP 3: Coherence Validation ===")
        try:
            validated = validate_candidates(session, config)
            summary["coherence_validated"] = validated
        except Exception as e:
            log.error("Coherence validation failed: %s", e)
            summary["errors"] += 1
            summary["error_details"].append(f"coherence: {e}")

        # Step 4: Scoring
        log.info("=== STEP 4: Importance Scoring ===")
        try:
            scored = score_clusters(session, config)
            summary["clusters_scored"] = scored
        except Exception as e:
            log.error("Scoring failed: %s", e)
            summary["errors"] += 1
            summary["error_details"].append(f"scoring: {e}")

        # Step 5: Drafting
        log.info("=== STEP 5: Draft Generation ===")
        daily_cap = config.schedule.daily_cap
        already_today = _count_today_drafts(session)
        remaining_cap = daily_cap - already_today
        if max_drafts is not None:
            remaining_cap = min(remaining_cap, max_drafts)

        if remaining_cap <= 0:
            log.info("Daily cap reached (%d/%d). Skipping drafting.", already_today, daily_cap)
        else:
            eligible = get_eligible_clusters(session, config, limit=remaining_cap)
            log.info("Found %d eligible clusters for drafting", len(eligible))

            consecutive_failures = 0
            for cluster in eligible:
                try:
                    draft_result = _draft_cluster(session, cluster, config, dry_run)
                    if draft_result:
                        summary["drafts_created"] += 1
                        if not dry_run:
                            summary["drafts_published"] += 1
                        consecutive_failures = 0
                    else:
                        consecutive_failures += 1
                except Exception as e:
                    log.error("Draft generation failed for cluster %d: %s\n%s", cluster.id, e, traceback.format_exc())
                    summary["errors"] += 1
                    summary["error_details"].append(f"draft_cluster_{cluster.id}: {e}")
                    consecutive_failures += 1

                # Auto-pause on 3 consecutive failures
                if consecutive_failures >= 3:
                    log.error("3 consecutive failures. Auto-pausing pipeline.")
                    _set_paused(session, True)
                    break

            # Check high-risk pause condition
            if _count_recent_high_risk(session) >= 3:
                log.error("3+ high-risk articles in 24h. Auto-pausing pipeline.")
                _set_paused(session, True)

        run_log.status = "completed"
        run_log.articles_ingested = summary["articles_ingested"]
        run_log.clusters_formed = summary["clusters_formed"]
        run_log.drafts_created = summary["drafts_created"]
        run_log.drafts_published = summary["drafts_published"]
        run_log.errors = summary["errors"]
        run_log.error_details = json.dumps(summary["error_details"], ensure_ascii=False) if summary["error_details"] else None

    except Exception as e:
        log.error("Pipeline failed: %s\n%s", e, traceback.format_exc())
        run_log.status = "failed"
        run_log.errors = summary["errors"] + 1
        summary["errors"] += 1
        summary["error_details"].append(f"pipeline: {e}")
    finally:
        run_log.finished_at = utcnow()
        session.commit()
        session.close()

    return summary


def _draft_cluster(
    session: Session,
    cluster: Cluster,
    config: AppConfig,
    dry_run: bool,
) -> dict | None:
    """Generate a draft for a single cluster. Returns info dict or None on failure."""
    log.info("Drafting cluster %d (importance=%.4f, sources=%d)",
             cluster.id, cluster.importance_score or 0, cluster.unique_domain_count)

    items = session.query(RawArticle).filter_by(cluster_id=cluster.id).all()
    if not items:
        return None

    # 5a: Source summaries
    summaries = summarize_cluster_sources(items)

    # 5b: Merge facts
    facts = merge_facts(summaries)

    # 5c: Write article
    article_text = write_article(facts)

    # 5d: Self-edit
    edit_result = self_edit(article_text)
    final_text = edit_result.revised_article

    # 5e: Safety gate
    safety_result = full_safety_gate(final_text, config)
    log.info("Safety result: risk=%s, flags=%s", safety_result.risk_level, safety_result.flags)

    # 5f: SEO
    seo = generate_seo(final_text, config)

    # Resolve category ID
    category_map = config.web.category_map
    category_id = category_map.get(seo.category, config.web.default_category_id)

    # Extract title from article (first line)
    lines = final_text.strip().split("\n")
    title = lines[0].strip().lstrip("#").strip() if lines else "Без заглавие"

    # Build HTML body
    body_lines = lines[1:] if len(lines) > 1 else []
    body_html = "\n".join(f"<p>{line}</p>" for line in body_lines if line.strip())

    # Word count
    word_count = len(final_text.split())

    # Store in DB
    gen_article = GeneratedArticle(
        cluster_id=cluster.id,
        title=title,
        body_html=body_html,
        body_text=final_text,
        word_count=word_count,
        seo_title=seo.seo_title,
        meta_description=seo.meta_description,
        slug=seo.slug,
        category_id=category_id,
        safety_risk_level=safety_result.risk_level,
    )
    gen_article.tags = seo.tags
    gen_article.source_urls = [item.url for item in items]
    gen_article.safety_flags_json = json.dumps(
        [str(f) for f in safety_result.flags], ensure_ascii=False
    )

    session.add(gen_article)
    cluster.drafted = True
    session.flush()

    result_info: dict = {
        "article_id": gen_article.id,
        "title": title,
        "word_count": word_count,
        "safety_risk": safety_result.risk_level,
    }

    # Step 6: Mark as pending for editorial review
    if dry_run:
        log.info("[DRY RUN] Would create pending draft: %s (%d words, risk=%s)",
                 title, word_count, safety_result.risk_level)
    else:
        # Check idempotency
        existing_pub = session.query(PublishingLog).filter_by(
            cluster_id=cluster.id
        ).first()
        if existing_pub:
            log.warning("Cluster %d already drafted (article %d). Skipping.",
                        cluster.id, existing_pub.article_id)
        else:
            pub_log = PublishingLog(
                article_id=gen_article.id,
                cluster_id=cluster.id,
                action="created",
                actor="pipeline",
            )
            session.add(pub_log)
            gen_article.status = "pending"

            # Optional Telegram notification
            site_url = config.web.site_url.rstrip("/")
            article_url = f"{site_url}/dashboard/article/{gen_article.id}"
            try:
                from nasvetlo.publishing.telegram import notify_new_draft
                notify_new_draft(title, article_url, config)
            except Exception:
                pass

    session.commit()
    return result_info
