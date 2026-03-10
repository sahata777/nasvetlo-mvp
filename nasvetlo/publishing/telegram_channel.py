"""Telegram public channel distribution.

Posts a formatted message to a Telegram channel when an article is published.
Distinct from telegram.py (editor draft notifications) — this targets the
public-facing channel, configured via `telegram.channel_id` in config.yaml.
"""

from __future__ import annotations

import os

import requests

from nasvetlo.config import AppConfig
from nasvetlo.logging_utils import get_logger

log = get_logger("publishing.telegram_channel")


def post_article_to_channel(
    title: str,
    meta_description: str,
    article_url: str,
    config: AppConfig,
) -> bool:
    """Send a published article announcement to the Telegram channel.

    Returns True on success, False on failure or if not configured.
    """
    bot_token = os.environ.get(config.telegram.bot_token_env, "")
    channel_id = config.telegram.channel_id
    if not bot_token or not channel_id:
        log.debug("Telegram channel not configured, skipping distribution")
        return False

    excerpt = (meta_description or "")[:200]
    text = (
        f"<b>{title}</b>\n\n"
        f"{excerpt}\n\n"
        f'<a href="{article_url}">Прочети цялата статия</a>'
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": channel_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        log.info("Article posted to Telegram channel %s: %s", channel_id, title)
        return True
    except Exception as e:
        log.error("Failed to post to Telegram channel: %s", e)
        return False
