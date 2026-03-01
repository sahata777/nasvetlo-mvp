"""Public news site routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from nasvetlo.config import get_config
from nasvetlo.models import GeneratedArticle
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

    xml_lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml_lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    base = config.web.site_url.rstrip("/")
    xml_lines.append(f"  <url><loc>{base}/</loc></url>")
    for a in articles:
        xml_lines.append(f"  <url><loc>{base}/article/{a.slug}</loc></url>")
    xml_lines.append("</urlset>")

    return Response(content="\n".join(xml_lines), media_type="application/xml")
