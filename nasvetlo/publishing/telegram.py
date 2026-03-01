"""Optional Telegram distribution."""

from __future__ import annotations

import requests

from nasvetlo.config import AppConfig
from nasvetlo.logging_utils import get_logger
from nasvetlo.settings import get_settings

log = get_logger("publishing.telegram")


def send_telegram_message(text: str, config: AppConfig) -> bool:
    """Send a message to the configured Telegram chat."""
    settings = get_settings()
    bot_token = getattr(settings, config.telegram.bot_token_env.lower(), "")
    if not bot_token:
        import os
        bot_token = os.environ.get(config.telegram.bot_token_env, "")

    chat_id = config.telegram.chat_id
    if not bot_token or not chat_id:
        log.warning("Telegram not configured, skipping")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        log.info("Telegram message sent to chat %s", chat_id)
        return True
    except Exception as e:
        log.error("Failed to send Telegram message: %s", e)
        return False


def notify_new_draft(title: str, article_url: str, config: AppConfig) -> bool:
    """Send notification about a new pending draft."""
    text = (
        f"📰 <b>Нов чернова:</b>\n{title}\n\n"
        f'📝 <a href="{article_url}">Преглед</a>'
    )
    return send_telegram_message(text, config)
