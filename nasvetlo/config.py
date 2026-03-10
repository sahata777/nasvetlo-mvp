"""Load and validate YAML configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class SourceConfig(BaseModel):
    name: str
    rss_url: str
    tier: int = Field(ge=1, le=4)
    credibility_score: float = Field(ge=0.0, le=1.0)
    enabled: bool = True


class ThresholdsConfig(BaseModel):
    similarity_threshold: float = 0.80
    min_sources: int = 3
    time_window_hours: int = 24
    importance_threshold: float = 0.60
    coherence_confidence_min: float = 0.60


class ScoringWeightsConfig(BaseModel):
    source_count: float = 0.35
    tier_average: float = 0.25
    speed: float = 0.15
    institutional: float = 0.15
    recency: float = 0.10


class ScheduleConfig(BaseModel):
    scan_minutes: int = 40
    daily_cap: int = 8


class SafetyConfig(BaseModel):
    high_risk_keywords: list[str] = Field(default_factory=list)
    institutional_keywords: list[str] = Field(default_factory=list)
    defamation_keywords: list[str] = Field(default_factory=list)


class WebConfig(BaseModel):
    site_url: str = "http://localhost:8000"
    site_name: str = "На Светло"
    site_description: str = "Българският новинарски агрегатор"
    host: str = "0.0.0.0"
    port: int = 8000
    articles_per_page: int = 20
    default_category_id: int = 1
    category_map: dict[str, int] = Field(default_factory=dict)


class LLMConfig(BaseModel):
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-5-20250929"
    temperature: float = 0.3
    max_tokens: int = 4096


class TelegramConfig(BaseModel):
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    chat_id: str = ""


class FeaturesConfig(BaseModel):
    """Feature flags — each can be toggled in config.yaml without code changes."""
    event_registry: bool = False
    context_expansion: bool = False
    entity_extraction: bool = False
    evergreen_explainers: bool = False
    evergreen_mention_threshold: int = 3   # min mentions before generating explainer
    evergreen_refresh_days: int = 7        # re-generate if older than N days
    search_capture: bool = False
    search_questions_per_event: int = 3    # question pages generated per article


class AppConfig(BaseModel):
    sources: list[SourceConfig] = Field(default_factory=list)
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)
    scoring_weights: ScoringWeightsConfig = Field(default_factory=ScoringWeightsConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)


_config: AppConfig | None = None


def load_config(path: str | Path) -> AppConfig:
    """Load YAML config from path."""
    global _config
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")
    with open(p, "r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}
    _config = AppConfig(**raw)
    return _config


def get_config() -> AppConfig:
    """Return cached config; load from default path if needed."""
    global _config
    if _config is None:
        from nasvetlo.settings import get_settings
        return load_config(get_settings().nasvetlo_config)
    return _config
