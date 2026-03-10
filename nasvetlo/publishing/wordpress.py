"""WordPress REST API publisher."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import requests
from requests.auth import HTTPBasicAuth

from nasvetlo.logging_utils import get_logger
from nasvetlo.settings import get_settings

if TYPE_CHECKING:
    from nasvetlo.models import GeneratedArticle
    from nasvetlo.settings import Settings


@dataclass
class PublishResult:
    success: bool = False
    wp_post_id: int | None = None
    wp_url: str | None = None
    error: str | None = None

log = get_logger("publishing.wordpress")


def _wp_url(base_url: str, route: str) -> str:
    """Build WordPress REST API URL using ?rest_route= fallback (works when /wp-json/ is not rewritten)."""
    return f"{base_url}?rest_route={route}"


def _get_or_create_tag(tag_name: str, base_url: str, auth: HTTPBasicAuth) -> int | None:
    """Return tag ID for a tag name, creating it if it doesn't exist."""
    try:
        resp = requests.get(
            _wp_url(base_url, "/wp/v2/tags"),
            params={"search": tag_name, "per_page": 1},
            auth=auth,
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            return results[0]["id"]
        resp = requests.post(
            _wp_url(base_url, "/wp/v2/tags"),
            json={"name": tag_name},
            auth=auth,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["id"]
    except Exception as e:
        log.warning("Could not get/create tag '%s': %s", tag_name, e)
        return None


def publish_pending_post(
    title: str,
    body_html: str,
    slug: str,
    meta_description: str,
    category_id: int,
    tags: list[str],
) -> dict | None:
    """
    Create a pending post in WordPress via REST API.
    Returns the WP post dict on success, None on failure.
    """
    settings = get_settings()
    wp_url = settings.wp_url.rstrip("/")
    username = settings.wp_username
    password = settings.wp_application_password

    if not wp_url or not username or not password:
        log.warning("WordPress credentials not configured — skipping WP publish")
        return None

    auth = HTTPBasicAuth(username, password)

    tag_ids = []
    for tag_name in tags:
        tag_id = _get_or_create_tag(tag_name, wp_url, auth)
        if tag_id:
            tag_ids.append(tag_id)

    payload = {
        "title": title,
        "content": body_html,
        "status": "pending",
        "slug": slug,
        "excerpt": meta_description,
        "categories": [category_id],
        "tags": tag_ids,
    }

    try:
        resp = requests.post(
            _wp_url(wp_url, "/wp/v2/posts"),
            json=payload,
            auth=auth,
            timeout=30,
        )
        resp.raise_for_status()
        post = resp.json()
        log.info("Created WP pending post id=%d title=%s", post["id"], title)
        return post
    except Exception as e:
        log.error("Failed to create WP post '%s': %s", title, e)
        return None


def publish_entity_page(
    title: str,
    body_html: str,
    slug: str,
    existing_wp_page_id: int | None = None,
) -> dict | None:
    """Create or update a WordPress page for an entity explainer.

    Pages are created with ``status: "draft"`` so an editor must publish them.
    If ``existing_wp_page_id`` is provided, the existing page is updated.

    Returns the WP page dict on success, None on failure.
    """
    settings = get_settings()
    wp_url = settings.wp_url.rstrip("/") if settings.wp_url else ""
    username = settings.wp_username
    password = settings.wp_application_password

    if not wp_url or not username or not password:
        log.warning("WordPress credentials not configured — skipping entity page publish")
        return None

    auth = HTTPBasicAuth(username, password)
    payload = {
        "title": title,
        "content": body_html,
        "status": "draft",
        "slug": slug,
    }

    try:
        if existing_wp_page_id:
            resp = requests.post(
                _wp_url(wp_url, f"/wp/v2/pages/{existing_wp_page_id}"),
                json=payload,
                auth=auth,
                timeout=30,
            )
        else:
            resp = requests.post(
                _wp_url(wp_url, "/wp/v2/pages"),
                json=payload,
                auth=auth,
                timeout=30,
            )
        resp.raise_for_status()
        page = resp.json()
        log.info(
            "Entity page %s: id=%d slug=%s",
            "updated" if existing_wp_page_id else "created",
            page["id"], slug,
        )
        return page
    except Exception as e:
        log.error("Failed to create/update entity page '%s': %s", title, e)
        return None


def publish_to_wordpress(article: "GeneratedArticle", settings: "Settings") -> PublishResult:
    """
    Publish a GeneratedArticle to WordPress as a live 'publish' post.
    If a WP post already exists (from PublishingLog), updates it to published status.
    Returns a PublishResult with success/failure info.
    """
    wp_url = settings.wp_url.rstrip("/") if settings.wp_url else ""
    username = settings.wp_username
    password = settings.wp_application_password

    if not wp_url or not username or not password:
        log.warning("WordPress credentials not configured — skipping WP publish")
        return PublishResult(success=False, error="WordPress credentials not configured")

    auth = HTTPBasicAuth(username, password)

    tag_ids = []
    for tag_name in article.tags:
        tag_id = _get_or_create_tag(tag_name, wp_url, auth)
        if tag_id:
            tag_ids.append(tag_id)

    payload = {
        "title": article.title,
        "content": article.body_html,
        "status": "publish",
        "slug": article.slug,
        "excerpt": article.meta_description,
        "categories": [article.category_id],
        "tags": tag_ids,
    }

    try:
        # Check if a WP post already exists for this article
        from nasvetlo.db import get_session
        from nasvetlo.models import PublishingLog
        session = get_session()
        existing = (
            session.query(PublishingLog)
            .filter(
                PublishingLog.article_id == article.id,
                PublishingLog.wp_post_id.isnot(None),
            )
            .order_by(PublishingLog.id.desc())
            .first()
        )
        session.close()

        if existing and existing.wp_post_id:
            # Update existing post to published
            resp = requests.post(
                _wp_url(wp_url, f"/wp/v2/posts/{existing.wp_post_id}"),
                json=payload,
                auth=auth,
                timeout=30,
            )
        else:
            # Create new post
            resp = requests.post(
                _wp_url(wp_url, "/wp/v2/posts"),
                json=payload,
                auth=auth,
                timeout=30,
            )

        resp.raise_for_status()
        post = resp.json()
        log.info("Published WP post id=%d url=%s", post["id"], post.get("link", ""))
        return PublishResult(
            success=True,
            wp_post_id=post["id"],
            wp_url=post.get("link"),
        )
    except Exception as e:
        log.error("Failed to publish WP post '%s': %s", article.title, e)
        return PublishResult(success=False, error=str(e))
