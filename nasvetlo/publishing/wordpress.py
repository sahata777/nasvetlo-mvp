"""WordPress REST API publisher."""

from __future__ import annotations

import requests
from requests.auth import HTTPBasicAuth

from nasvetlo.logging_utils import get_logger
from nasvetlo.settings import get_settings

log = get_logger("publishing.wordpress")


def _get_or_create_tag(tag_name: str, base_url: str, auth: HTTPBasicAuth) -> int | None:
    """Return tag ID for a tag name, creating it if it doesn't exist."""
    try:
        resp = requests.get(
            f"{base_url}/wp-json/wp/v2/tags",
            params={"search": tag_name, "per_page": 1},
            auth=auth,
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            return results[0]["id"]
        resp = requests.post(
            f"{base_url}/wp-json/wp/v2/tags",
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
            f"{wp_url}/wp-json/wp/v2/posts",
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
