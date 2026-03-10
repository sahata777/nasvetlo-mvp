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
        "events_created": 0,
        "events_updated": 0,
        "drafts_created": 0,
        "drafts_published": 0,
        "search_pages_created": 0,
        "explainers_generated": 0,
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

        # Step 4b: Event Registry Sync (feature-flagged)
        if config.features.event_registry:
            log.info("=== STEP 4b: Event Registry Sync ===")
            try:
                from nasvetlo.events.registry import sync_event_registry
                er_result = sync_event_registry(session, config)
                summary["events_created"] = er_result["created"]
                summary["events_updated"] = er_result["updated"]
                log.info(
                    "Event registry: %d created, %d updated",
                    er_result["created"], er_result["updated"],
                )
            except Exception as e:
                log.error("Event registry sync failed: %s", e)
                summary["errors"] += 1
                summary["error_details"].append(f"event_registry: {e}")

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
                        summary["search_pages_created"] += draft_result.get("search_pages", 0)
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

        # Step 6: Evergreen Explainer Generation (feature-flagged)
        if config.features.evergreen_explainers:
            log.info("=== STEP 6: Evergreen Explainer Generation ===")
            try:
                from nasvetlo.entities.explainer import run_evergreen_explainers
                explainers = run_evergreen_explainers(session, config, dry_run)
                summary["explainers_generated"] = explainers
                log.info("Evergreen explainers: %d generated", explainers)
            except Exception as e:
                log.error("Evergreen explainer generation failed: %s", e)
                summary["errors"] += 1
                summary["error_details"].append(f"evergreen_explainers: {e}")

        # Step 7: Traffic Feedback Loop (feature-flagged)
        if config.features.traffic_feedback:
            log.info("=== STEP 7: Traffic Feedback ===")
            try:
                from nasvetlo.analytics.feedback import apply_traffic_feedback
                fb = apply_traffic_feedback(session, config)
                summary["traffic_boosted_events"] = fb["events_boosted"]
                summary["traffic_boosted_entities"] = fb["entities_boosted"]
            except Exception as e:
                log.error("Traffic feedback failed: %s", e)
                summary["errors"] += 1
                summary["error_details"].append(f"traffic_feedback: {e}")

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

    # LLM budget tracker — counts optional LLM calls; 0 = unlimited
    _budget = config.features.llm_calls_per_article_budget
    _llm_calls = 0

    def _budget_ok() -> bool:
        return _budget == 0 or _llm_calls < _budget

    # 5a: Source summaries (session enables per-article cache)
    summaries = summarize_cluster_sources(items, session=session)

    # 5b: Merge facts
    facts = merge_facts(summaries)

    # 5c: Write article
    article_text = write_article(facts)

    # 5d: Self-edit
    edit_result = self_edit(article_text)
    final_text = edit_result.revised_article

    # 5d2: Headline Optimization (feature-flagged, budget-gated)
    _headline_variants_json = None
    if config.features.headline_optimization and _budget_ok():
        try:
            from nasvetlo.drafting.headline_optimizer import optimize_headline
            _lines = final_text.strip().split("\n")
            _raw_title = _lines[0].strip().lstrip("#").strip() if _lines else ""
            if _raw_title:
                hl_result = optimize_headline(_raw_title, final_text)
                if hl_result.best_headline:
                    final_text = hl_result.best_headline + "\n" + "\n".join(_lines[1:])
                _headline_variants_json = json.dumps(
                    [v.model_dump() for v in hl_result.variants],
                    ensure_ascii=False,
                )
            _llm_calls += 1
        except Exception as e:
            log.warning("Headline optimization failed for cluster %d: %s", cluster.id, e)

    # 5e: Safety gate
    safety_result = full_safety_gate(final_text, config)
    log.info("Safety result: risk=%s, flags=%s", safety_result.risk_level, safety_result.flags)

    # 5e2: Legal review (feature-flagged, selective, budget-gated)
    _legal_risk_json = None
    if config.features.legal_review and _budget_ok():
        try:
            from nasvetlo.drafting.legal_reviewer import run_legal_review
            _legal_result = run_legal_review(
                article_text=final_text,
                safety_flags=[str(f) for f in safety_result.flags],
            )
            if _legal_result is not None:
                _legal_risk_json = json.dumps(
                    _legal_result.model_dump(), ensure_ascii=False
                )
                # Escalate risk if legal review found high-severity issues
                if _legal_result.risk_level == "high" and safety_result.risk_level != "high":
                    safety_result.risk_level = "high"
                    safety_result.flags.append("legal_review: high risk")
                    log.warning(
                        "Legal review escalated risk to HIGH for cluster %d", cluster.id
                    )
            _llm_calls += 1
        except Exception as e:
            log.warning("Legal review failed for cluster %d: %s", cluster.id, e)

    # 5f: SEO
    seo = generate_seo(final_text, config)

    # Resolve category ID
    category_map = config.web.category_map
    category_id = category_map.get(seo.category, config.web.default_category_id)

    # Extract title from article (first line)
    lines = final_text.strip().split("\n")
    title = lines[0].strip().lstrip("#").strip() if lines else "Без заглавие"

    # Build HTML body — convert markdown to proper HTML
    import markdown as md_lib
    body_text = "\n".join(lines[1:]) if len(lines) > 1 else ""
    body_html = md_lib.markdown(body_text, extensions=["nl2br"])

    # 5g: Context Expansion (budget-gated)
    if config.features.context_expansion and _budget_ok():
        try:
            from nasvetlo.events.registry import get_event_for_cluster
            from nasvetlo.events.context import build_event_context
            from nasvetlo.drafting.context_expander import expand_context, build_context_html
            event = get_event_for_cluster(session, cluster.id)
            if event:
                event_context = build_event_context(session, event)
                sections = expand_context(final_text, event_context)
                context_html = build_context_html(sections)
                if context_html:
                    body_html += "\n" + context_html
                # Persist timeline and background back to the event for future context
                if sections.timeline:
                    event.timeline_json = json.dumps(sections.timeline, ensure_ascii=False)
                if sections.background:
                    event.background_json = json.dumps(
                        {"text": sections.background}, ensure_ascii=False
                    )
                log.info("Context expansion complete for cluster %d", cluster.id)
                _llm_calls += 1
        except Exception as e:
            log.warning("Context expansion failed for cluster %d: %s", cluster.id, e)

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
    if _headline_variants_json:
        gen_article.headline_variants_json = _headline_variants_json
    if _legal_risk_json:
        gen_article.legal_risk_json = _legal_risk_json

    session.add(gen_article)
    cluster.drafted = True
    session.flush()

    # Post-storage enrichment — event linking and entity extraction share a
    # single get_event_for_cluster call to avoid redundant DB queries.
    _article_event = None
    if config.features.event_registry or config.features.entity_extraction:
        try:
            from nasvetlo.events.registry import get_event_for_cluster
            _article_event = get_event_for_cluster(session, cluster.id)
        except Exception as e:
            log.warning("Could not fetch event for cluster %d: %s", cluster.id, e)

    # Link article to event registry
    if config.features.event_registry and _article_event:
        try:
            from nasvetlo.events.registry import mark_event_published
            mark_event_published(session, _article_event.id, gen_article.id)
        except Exception as e:
            log.warning("Failed to link article %d to event registry: %s", gen_article.id, e)

    # Entity extraction — build knowledge graph
    if config.features.entity_extraction:
        try:
            from nasvetlo.entities.extractor import extract_entities
            from nasvetlo.entities.graph import process_article_entities
            extraction = extract_entities(final_text)
            process_article_entities(session, gen_article, _article_event, extraction)
        except Exception as e:
            log.warning("Entity extraction failed for article %d: %s", gen_article.id, e)

    # Search capture — generate question/answer pages (budget-gated)
    _search_pages_stored = 0
    if config.features.search_capture and _budget_ok():
        try:
            from nasvetlo.search.question_generator import (
                generate_search_questions, store_search_pages,
            )
            n = config.features.search_questions_per_event
            sq_result = generate_search_questions(title, final_text, n=n)
            _search_pages_stored = store_search_pages(
                session, gen_article, _article_event, sq_result
            )
            _llm_calls += 1
        except Exception as e:
            log.warning("Search capture failed for article %d: %s", gen_article.id, e)

    result_info: dict = {
        "article_id": gen_article.id,
        "title": title,
        "word_count": word_count,
        "safety_risk": safety_result.risk_level,
        "search_pages": _search_pages_stored,
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

            # Publish to WordPress as pending post
            try:
                from nasvetlo.publishing.wordpress import publish_pending_post
                wp_post = publish_pending_post(
                    title=title,
                    body_html=body_html,
                    slug=seo.slug,
                    meta_description=seo.meta_description,
                    category_id=category_id,
                    tags=seo.tags,
                )
                if wp_post:
                    pub_log.wp_post_id = wp_post.get("id")
                    pub_log.wp_url = wp_post.get("link")
                    pub_log.status = "wp_pending"
                    result_info["wp_post_id"] = wp_post.get("id")
            except Exception as e:
                log.error("WordPress publish failed: %s", e)

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
