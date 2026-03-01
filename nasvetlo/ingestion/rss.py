"""RSS feed fetching."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import mktime

import feedparser

from nasvetlo.logging_utils import get_logger

log = get_logger("ingestion.rss")


@dataclass
class FeedItem:
    title: str
    summary: str
    url: str
    published_at: datetime | None


def fetch_feed(rss_url: str, timeout: int = 30) -> list[FeedItem]:
    """Fetch and parse an RSS feed, returning a list of items."""
    try:
        feed = feedparser.parse(rss_url, request_headers={"User-Agent": "NaSvetlo/1.0"})
    except Exception as e:
        log.error("Failed to fetch feed %s: %s", rss_url, e)
        return []

    if feed.bozo and not feed.entries:
        log.warning("Feed %s returned bozo error: %s", rss_url, feed.bozo_exception)
        return []

    items: list[FeedItem] = []
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        if not title:
            continue

        summary = entry.get("summary", "") or entry.get("description", "") or ""
        link = entry.get("link", "")
        if not link:
            continue

        pub_date: datetime | None = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                pub_date = datetime.fromtimestamp(mktime(entry.published_parsed), tz=timezone.utc)
            except (ValueError, OverflowError):
                pass
        elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
            try:
                pub_date = datetime.fromtimestamp(mktime(entry.updated_parsed), tz=timezone.utc)
            except (ValueError, OverflowError):
                pass

        items.append(FeedItem(title=title, summary=summary, url=link, published_at=pub_date))

    log.info("Fetched %d items from %s", len(items), rss_url)
    return items
