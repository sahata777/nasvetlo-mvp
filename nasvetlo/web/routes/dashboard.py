"""Editorial dashboard routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from nasvetlo.config import get_config
from nasvetlo.publishing.wordpress import publish_to_wordpress
from nasvetlo.settings import get_settings
from nasvetlo.models import (
    Cluster,
    GeneratedArticle,
    PublishingLog,
    RawArticle,
    RunLog,
    SourceRegistry,
)
from nasvetlo.utils.time import utcnow
from nasvetlo.web.deps import get_db, templates
from nasvetlo.web.routes.public import CATEGORY_NAMES

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard_home(request: Request, db: Session = Depends(get_db)):
    config = get_config()
    today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    pending_count = db.query(GeneratedArticle).filter(
        GeneratedArticle.status == "pending"
    ).count()
    published_today = db.query(GeneratedArticle).filter(
        GeneratedArticle.status == "published",
        GeneratedArticle.created_at >= today_start,
    ).count()
    high_risk_count = db.query(GeneratedArticle).filter(
        GeneratedArticle.status == "pending",
        GeneratedArticle.safety_risk_level == "high",
    ).count()

    last_run = db.query(RunLog).order_by(RunLog.id.desc()).first()

    recent_articles = (
        db.query(GeneratedArticle)
        .order_by(GeneratedArticle.created_at.desc())
        .limit(10)
        .all()
    )

    return templates.TemplateResponse("dashboard/index.html", {
        "request": request,
        "pending_count": pending_count,
        "published_today": published_today,
        "high_risk_count": high_risk_count,
        "last_run": last_run,
        "recent_articles": recent_articles,
        "category_names": CATEGORY_NAMES,
        "config": config,
    })


@router.get("/pending", response_class=HTMLResponse)
def pending_list(request: Request, db: Session = Depends(get_db)):
    articles = (
        db.query(GeneratedArticle)
        .filter(GeneratedArticle.status == "pending")
        .order_by(GeneratedArticle.created_at.desc())
        .all()
    )

    is_htmx = request.headers.get("HX-Request") == "true"
    template = "dashboard/partials/pending_list.html" if is_htmx else "dashboard/pending.html"

    return templates.TemplateResponse(template, {
        "request": request,
        "articles": articles,
        "category_names": CATEGORY_NAMES,
    })


@router.get("/articles", response_class=HTMLResponse)
def articles_list(
    request: Request,
    status: str = "all",
    db: Session = Depends(get_db),
):
    query = db.query(GeneratedArticle)
    if status != "all":
        query = query.filter(GeneratedArticle.status == status)
    articles = query.order_by(GeneratedArticle.created_at.desc()).all()

    return templates.TemplateResponse("dashboard/articles.html", {
        "request": request,
        "articles": articles,
        "current_status": status,
        "category_names": CATEGORY_NAMES,
    })


@router.get("/article/{article_id}", response_class=HTMLResponse)
def article_detail(article_id: int, request: Request, db: Session = Depends(get_db)):
    article = db.query(GeneratedArticle).get(article_id)
    if not article:
        return HTMLResponse("<h1>Not found</h1>", status_code=404)

    cluster = db.query(Cluster).get(article.cluster_id)
    source_articles = (
        db.query(RawArticle)
        .filter(RawArticle.cluster_id == article.cluster_id)
        .all()
    ) if cluster else []

    logs = (
        db.query(PublishingLog)
        .filter(PublishingLog.article_id == article_id)
        .order_by(PublishingLog.created_at.desc())
        .all()
    )

    wp_log = next((l for l in logs if l.wp_url), None)

    return templates.TemplateResponse("dashboard/article_detail.html", {
        "request": request,
        "article": article,
        "cluster": cluster,
        "source_articles": source_articles,
        "logs": logs,
        "category_names": CATEGORY_NAMES,
        "wp_url": wp_log.wp_url if wp_log else None,
    })


@router.post("/article/{article_id}/approve", response_class=HTMLResponse)
def approve_article(article_id: int, request: Request, db: Session = Depends(get_db)):
    article = db.query(GeneratedArticle).get(article_id)
    if article:
        article.status = "approved"
        article.reviewed_at = datetime.now(timezone.utc)
        log = PublishingLog(
            article_id=article_id,
            cluster_id=article.cluster_id,
            action="approved",
            actor="editor",
        )
        db.add(log)
        db.commit()

    return templates.TemplateResponse("dashboard/partials/status_badge.html", {
        "request": request,
        "article": article,
    })


@router.post("/article/{article_id}/reject", response_class=HTMLResponse)
def reject_article(
    article_id: int,
    request: Request,
    reason: str = Form(""),
    db: Session = Depends(get_db),
):
    article = db.query(GeneratedArticle).get(article_id)
    if article:
        article.status = "rejected"
        article.reviewed_at = datetime.now(timezone.utc)
        article.editor_notes = reason or article.editor_notes
        log = PublishingLog(
            article_id=article_id,
            cluster_id=article.cluster_id,
            action="rejected",
            actor="editor",
            note=reason,
        )
        db.add(log)
        db.commit()

    return templates.TemplateResponse("dashboard/partials/status_badge.html", {
        "request": request,
        "article": article,
    })


@router.post("/article/{article_id}/publish", response_class=HTMLResponse)
def publish_article(article_id: int, request: Request, db: Session = Depends(get_db)):
    config = get_config()
    article = db.query(GeneratedArticle).get(article_id)
    wp_url = None
    if article:
        article.status = "published"
        article.published = True
        article.reviewed_at = datetime.now(timezone.utc)

        result = publish_to_wordpress(article, get_settings())
        wp_url = result.wp_url

        pub_log = PublishingLog(
            article_id=article_id,
            cluster_id=article.cluster_id,
            action="published",
            actor="editor",
            wp_post_id=result.wp_post_id,
            wp_url=result.wp_url,
            status="success" if result.success else "wp_failed",
            note=f"WP post #{result.wp_post_id}" if result.success else f"WP error: {result.error}",
        )
        db.add(pub_log)
        db.commit()

        # Telegram channel distribution (feature-flagged)
        if config.features.telegram_distribution:
            try:
                from nasvetlo.publishing.telegram_channel import post_article_to_channel
                article_url = f"{config.web.site_url.rstrip('/')}/article/{article.slug}"
                post_article_to_channel(
                    title=article.title,
                    meta_description=article.meta_description,
                    article_url=article_url,
                    config=config,
                )
            except Exception:
                pass

    return templates.TemplateResponse("dashboard/partials/status_badge.html", {
        "request": request,
        "article": article,
        "wp_url": wp_url,
    })


@router.get("/article/{article_id}/edit", response_class=HTMLResponse)
def edit_form(article_id: int, request: Request, db: Session = Depends(get_db)):
    article = db.query(GeneratedArticle).get(article_id)
    if not article:
        return HTMLResponse("<h1>Not found</h1>", status_code=404)

    return templates.TemplateResponse("dashboard/article_edit.html", {
        "request": request,
        "article": article,
    })


@router.post("/article/{article_id}/edit", response_class=HTMLResponse)
def save_edit(
    article_id: int,
    request: Request,
    title: str = Form(...),
    body_html: str = Form(...),
    db: Session = Depends(get_db),
):
    article = db.query(GeneratedArticle).get(article_id)
    if article:
        article.title = title
        article.body_html = body_html
        article.word_count = len(body_html.split())
        log = PublishingLog(
            article_id=article_id,
            cluster_id=article.cluster_id,
            action="edited",
            actor="editor",
        )
        db.add(log)
        db.commit()

    return templates.TemplateResponse("dashboard/article_detail.html", {
        "request": request,
        "article": article,
        "cluster": db.query(Cluster).get(article.cluster_id) if article else None,
        "source_articles": (
            db.query(RawArticle).filter(RawArticle.cluster_id == article.cluster_id).all()
            if article else []
        ),
        "logs": (
            db.query(PublishingLog).filter(PublishingLog.article_id == article_id)
            .order_by(PublishingLog.created_at.desc()).all()
        ),
        "category_names": CATEGORY_NAMES,
    })


@router.get("/runs", response_class=HTMLResponse)
def run_history(request: Request, db: Session = Depends(get_db)):
    runs = db.query(RunLog).order_by(RunLog.id.desc()).limit(50).all()
    return templates.TemplateResponse("dashboard/runs.html", {
        "request": request,
        "runs": runs,
    })


@router.get("/sources", response_class=HTMLResponse)
def sources_list(request: Request, db: Session = Depends(get_db)):
    sources = db.query(SourceRegistry).order_by(SourceRegistry.tier, SourceRegistry.name).all()
    return templates.TemplateResponse("dashboard/sources.html", {
        "request": request,
        "sources": sources,
    })
