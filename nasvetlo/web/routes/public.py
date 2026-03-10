"""Public news site routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from nasvetlo.config import get_config
from nasvetlo.models import Entity, EntityEventLink, GeneratedArticle, SearchPage
from nasvetlo.web.deps import get_db, templates

router = APIRouter()

CATEGORY_NAMES = {
    1: "Общи",
    2: "Политика",
    3: "Икономика",
    4: "Общество",
    5: "Свят",
    6: "Технологии",
}


@router.get("/", response_class=HTMLResponse)
def homepage(request: Request, page: int = 1, db: Session = Depends(get_db)):
    config = get_config()
    per_page = config.web.articles_per_page
    offset = (page - 1) * per_page

    total = db.query(GeneratedArticle).filter(
        GeneratedArticle.status == "published"
    ).count()

    articles = (
        db.query(GeneratedArticle)
        .filter(GeneratedArticle.status == "published")
        .order_by(GeneratedArticle.created_at.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )

    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse("public/index.html", {
        "request": request,
        "articles": articles,
        "page": page,
        "total_pages": total_pages,
        "category_names": CATEGORY_NAMES,
        "config": config,
    })


@router.get("/article/{slug}", response_class=HTMLResponse)
def article_page(slug: str, request: Request, db: Session = Depends(get_db)):
    config = get_config()
    article = (
        db.query(GeneratedArticle)
        .filter(GeneratedArticle.slug == slug, GeneratedArticle.status == "published")
        .first()
    )
    if not article:
        return templates.TemplateResponse("public/404.html", {
            "request": request,
            "config": config,
        }, status_code=404)

    return templates.TemplateResponse("public/article.html", {
        "request": request,
        "article": article,
        "category_names": CATEGORY_NAMES,
        "config": config,
    })


@router.get("/category/{category_id}", response_class=HTMLResponse)
def category_page(
    category_id: int, request: Request, page: int = 1, db: Session = Depends(get_db)
):
    config = get_config()
    per_page = config.web.articles_per_page
    offset = (page - 1) * per_page

    total = db.query(GeneratedArticle).filter(
        GeneratedArticle.status == "published",
        GeneratedArticle.category_id == category_id,
    ).count()

    articles = (
        db.query(GeneratedArticle)
        .filter(
            GeneratedArticle.status == "published",
            GeneratedArticle.category_id == category_id,
        )
        .order_by(GeneratedArticle.created_at.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )

    total_pages = max(1, (total + per_page - 1) // per_page)
    cat_name = CATEGORY_NAMES.get(category_id, f"Категория {category_id}")

    return templates.TemplateResponse("public/index.html", {
        "request": request,
        "articles": articles,
        "page": page,
        "total_pages": total_pages,
        "category_names": CATEGORY_NAMES,
        "config": config,
        "current_category": cat_name,
    })


@router.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = "", db: Session = Depends(get_db)):
    config = get_config()
    articles = []
    if q.strip():
        pattern = f"%{q.strip()}%"
        articles = (
            db.query(GeneratedArticle)
            .filter(
                GeneratedArticle.status == "published",
                GeneratedArticle.title.like(pattern) | GeneratedArticle.body_text.like(pattern),
            )
            .order_by(GeneratedArticle.created_at.desc())
            .limit(30)
            .all()
        )

    return templates.TemplateResponse("public/search.html", {
        "request": request,
        "articles": articles,
        "q": q,
        "category_names": CATEGORY_NAMES,
        "config": config,
    })


@router.get("/about", response_class=HTMLResponse)
def about_page(request: Request):
    config = get_config()
    return templates.TemplateResponse("public/about.html", {
        "request": request,
        "config": config,
    })


@router.get("/contact", response_class=HTMLResponse)
def contact_page(request: Request):
    config = get_config()
    return templates.TemplateResponse("public/contact.html", {
        "request": request,
        "config": config,
    })


@router.get("/entity/{slug}", response_class=HTMLResponse)
def entity_page(slug: str, request: Request, db: Session = Depends(get_db)):
    config = get_config()
    entity = db.query(Entity).filter_by(slug=slug).first()
    if not entity or not entity.explainer_html:
        return templates.TemplateResponse(
            "public/404.html",
            {"request": request, "config": config},
            status_code=404,
        )

    # Recent published articles mentioning this entity
    links = db.query(EntityEventLink).filter_by(entity_id=entity.id).all()
    article_ids = [lnk.article_id for lnk in links if lnk.article_id]
    recent_articles = (
        db.query(GeneratedArticle)
        .filter(
            GeneratedArticle.id.in_(article_ids),
            GeneratedArticle.status == "published",
        )
        .order_by(GeneratedArticle.created_at.desc())
        .limit(10)
        .all()
    ) if article_ids else []

    return templates.TemplateResponse("public/entity.html", {
        "request": request,
        "entity": entity,
        "recent_articles": recent_articles,
        "config": config,
    })


@router.get("/q/{slug}", response_class=HTMLResponse)
def search_capture_page(slug: str, request: Request, db: Session = Depends(get_db)):
    config = get_config()
    page = db.query(SearchPage).filter_by(slug=slug).first()
    if not page:
        return templates.TemplateResponse(
            "public/404.html",
            {"request": request, "config": config},
            status_code=404,
        )

    # Only serve if parent article is published
    article = (
        db.query(GeneratedArticle)
        .filter_by(id=page.article_id, status="published")
        .first()
    )
    if not article:
        return templates.TemplateResponse(
            "public/404.html",
            {"request": request, "config": config},
            status_code=404,
        )

    return templates.TemplateResponse("public/search_capture.html", {
        "request": request,
        "page": page,
        "article": article,
        "config": config,
    })


@router.get("/feed.xml")
def rss_feed(request: Request, db: Session = Depends(get_db)):
    config = get_config()
    articles = (
        db.query(GeneratedArticle)
        .filter(GeneratedArticle.status == "published")
        .order_by(GeneratedArticle.created_at.desc())
        .limit(20)
        .all()
    )

    return templates.TemplateResponse(
        "public/feed.xml",
        {
            "request": request,
            "articles": articles,
            "config": config,
        },
        media_type="application/xml",
    )


@router.get("/sitemap.xml")
def sitemap(request: Request, db: Session = Depends(get_db)):
    config = get_config()
    articles = (
        db.query(GeneratedArticle)
        .filter(GeneratedArticle.status == "published")
        .order_by(GeneratedArticle.created_at.desc())
        .all()
    )

    entity_pages = db.query(Entity).filter(Entity.explainer_html.isnot(None)).all()

    # Search capture pages — only for published parent articles
    published_ids = {a.id for a in articles}
    search_pages = (
        db.query(SearchPage)
        .filter(SearchPage.article_id.in_(published_ids))
        .all()
    ) if published_ids else []

    xml_lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml_lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    base = config.web.site_url.rstrip("/")
    xml_lines.append(f"  <url><loc>{base}/</loc></url>")
    for a in articles:
        xml_lines.append(f"  <url><loc>{base}/article/{a.slug}</loc></url>")
    for e in entity_pages:
        xml_lines.append(f"  <url><loc>{base}/entity/{e.slug}</loc></url>")
    for sp in search_pages:
        xml_lines.append(f"  <url><loc>{base}/q/{sp.slug}</loc></url>")
    xml_lines.append("</urlset>")

    return Response(content="\n".join(xml_lines), media_type="application/xml")
