"""Pydantic settings loaded from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings from environment."""

    database_url: str = Field(default="sqlite:///nasvetlo.db", alias="DATABASE_URL")
    nasvetlo_config: str = Field(default="config.yaml", alias="NASVETLO_CONFIG")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # LLM
    llm_provider: str = Field(default="anthropic", alias="LLM_PROVIDER")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")

    # Telegram
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")

    # WordPress
    wp_url: str = Field(default="", alias="WP_URL")
    wp_username: str = Field(default="", alias="WP_USERNAME")
    wp_application_password: str = Field(default="", alias="WP_APPLICATION_PASSWORD")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


_settings: Settings | None = None


def get_settings() -> Settings:
    """Get cached settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
