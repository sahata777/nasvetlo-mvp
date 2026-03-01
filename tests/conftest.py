"""Shared test fixtures."""

from __future__ import annotations

import os
import pytest

from nasvetlo.config import AppConfig, load_config
from nasvetlo.db import reset_engine, init_db, get_session
from nasvetlo.settings import Settings


@pytest.fixture(autouse=True)
def _reset_globals():
    """Reset all module-level singletons between tests."""
    import nasvetlo.settings as s
    import nasvetlo.config as c
    import nasvetlo.db as d
    import nasvetlo.llm as llm_mod
    import nasvetlo.clustering.embeddings as emb

    s._settings = None
    c._config = None
    d._engine = None
    d._SessionLocal = None
    llm_mod._provider = None
    emb._provider = None
    yield


@pytest.fixture
def in_memory_db(tmp_path):
    """Set up an in-memory SQLite DB and return a session."""
    os.environ["DATABASE_URL"] = "sqlite://"
    os.environ["NASVETLO_CONFIG"] = str(tmp_path / "config.yaml")
    os.environ["ANTHROPIC_API_KEY"] = "test-key"

    reset_engine()
    init_db()
    session = get_session()
    yield session
    session.close()


@pytest.fixture
def sample_config(tmp_path) -> AppConfig:
    """Write a minimal config and load it."""
    import yaml
    config_data = {
        "sources": [
            {"name": "Source A", "rss_url": "https://a.bg/rss", "tier": 1, "credibility_score": 0.95, "enabled": True},
            {"name": "Source B", "rss_url": "https://b.bg/rss", "tier": 2, "credibility_score": 0.80, "enabled": True},
            {"name": "Source C", "rss_url": "https://c.bg/rss", "tier": 2, "credibility_score": 0.80, "enabled": True},
            {"name": "Source D", "rss_url": "https://d.bg/rss", "tier": 3, "credibility_score": 0.65, "enabled": True},
        ],
        "thresholds": {
            "similarity_threshold": 0.80,
            "min_sources": 3,
            "time_window_hours": 24,
            "importance_threshold": 0.60,
            "coherence_confidence_min": 0.60,
        },
        "scoring_weights": {
            "source_count": 0.35,
            "tier_average": 0.25,
            "speed": 0.15,
            "institutional": 0.15,
            "recency": 0.10,
        },
        "schedule": {"scan_minutes": 40, "daily_cap": 8},
        "safety": {
            "high_risk_keywords": ["обвинен", "корупция"],
            "institutional_keywords": ["правителство", "парламент"],
            "defamation_keywords": ["мошеник", "престъпник"],
        },
        "web": {
            "site_url": "http://localhost:8000",
            "site_name": "На Светло Test",
            "default_category_id": 1,
            "category_map": {"политика": 2, "общество": 4},
        },
        "llm": {"provider": "anthropic", "model": "test-model", "temperature": 0.3, "max_tokens": 4096},
    }
    cfg_path = tmp_path / "config.yaml"
    with open(cfg_path, "w") as f:
        yaml.dump(config_data, f)

    os.environ["NASVETLO_CONFIG"] = str(cfg_path)
    return load_config(cfg_path)
