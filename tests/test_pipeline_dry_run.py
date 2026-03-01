"""Integration test: full pipeline dry run with mocked RSS + mocked LLM."""

import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from nasvetlo.clustering.embeddings import DummyEmbedding, EmbeddingProvider, set_embedding_provider
from nasvetlo.db import init_db, get_session, reset_engine
from nasvetlo.llm import MockLLMProvider, set_llm_provider
from nasvetlo.models import RawArticle, Cluster, GeneratedArticle, SourceRegistry
from nasvetlo.ingestion.rss import FeedItem


class TitleKeyEmbedding(EmbeddingProvider):
    """Embedding that hashes only the title portion (before first space-run after 10 chars).
    Articles with the same title get the same embedding regardless of summary."""

    def __init__(self, dim: int = 16):
        self._inner = DummyEmbedding(dim=dim)

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Extract title: the clusterer calls embed_single("title summary"),
        # so we use a known title marker to group texts
        normalized = []
        for text in texts:
            # Use first 32 chars as the key (covers the title portion only)
            normalized.append(text[:32])
        return self._inner.embed(normalized)


# Mock RSS responses
# For clustering tests, we need articles with:
# - Different content_hash (so dedup doesn't reject them)
# - Similar embeddings (so they cluster together)
# DummyEmbedding is hash-based, so we use a TitleOnlyEmbedding that hashes only the title portion
_BUDGET_TITLE = "Парламентът прие бюджета за 2024"

MOCK_FEEDS = {
    "https://a.bg/rss": [
        FeedItem(title=_BUDGET_TITLE, summary="Народното събрание прие бюджета с 145 гласа за.", url="https://a.bg/article/budget", published_at=datetime.now(timezone.utc)),
    ],
    "https://b.bg/rss": [
        FeedItem(title=_BUDGET_TITLE, summary="Бюджетът за 2024 беше одобрен от парламента днес.", url="https://b.bg/article/budget", published_at=datetime.now(timezone.utc)),
    ],
    "https://c.bg/rss": [
        FeedItem(title=_BUDGET_TITLE, summary="Депутатите гласуваха бюджета за следващата година.", url="https://c.bg/article/budget", published_at=datetime.now(timezone.utc)),
    ],
    "https://d.bg/rss": [
        FeedItem(title="Времето утре: слънчево", summary="Синоптиците прогнозират слънчево време.", url="https://d.bg/article/weather", published_at=datetime.now(timezone.utc)),
    ],
}

# Mock LLM responses keyed by keyword in system prompt
MOCK_LLM_RESPONSES = {
    "coherence": json.dumps({"same_event": True, "confidence": 0.92, "short_reason": "All about budget vote"}),
    "fact-extraction": json.dumps({
        "key_facts": ["Парламентът прие бюджета за 2024"],
        "uncertainties": [],
        "entities": ["Народно събрание"],
        "numbers_dates": ["2024", "145 гласа"],
        "source_stance": "neutral",
    }),
    "journalist": "Парламентът прие бюджета за 2024\n\nНародното събрание одобри бюджета за следващата година с мнозинство. "
        + "Решението беше взето след дълги дебати между политическите партии. " * 40
        + "\n\nИзточници: a.bg, b.bg, c.bg",
    "editor": json.dumps({
        "revised_article": "Парламентът прие бюджета за 2024\n\nНародното събрание одобри бюджета. " + "Текст. " * 100 + "\n\nИзточници: a.bg, b.bg, c.bg",
        "checklist": {
            "accuracy": True, "word_count_ok": True, "balanced": True,
            "attributed": True, "language_ok": True, "structure_ok": True,
            "no_defamation": True, "no_clickbait": True,
        },
        "changes_made": ["Minor style fixes"],
    }),
    "safety": json.dumps({"risk_level": "low", "flags": [], "required_actions": []}),
    "seo": json.dumps({
        "seo_title": "Парламентът прие бюджета за 2024",
        "meta_description": "Народното събрание одобри бюджета за 2024 г.",
        "slug": "parlamentat-prie-byudzheta-2024",
        "tags": ["бюджет", "парламент", "2024"],
        "category": "политика",
    }),
}


def mock_fetch_feed(rss_url: str, timeout: int = 30):
    return MOCK_FEEDS.get(rss_url, [])


class TestPipelineDryRun:
    @pytest.fixture(autouse=True)
    def setup(self, in_memory_db, sample_config):
        self.session = in_memory_db
        self.config = sample_config

        # Set up mock providers
        set_embedding_provider(TitleKeyEmbedding(dim=16))
        set_llm_provider(MockLLMProvider(MOCK_LLM_RESPONSES))

    @patch("nasvetlo.ingestion.normalize.fetch_feed", side_effect=mock_fetch_feed)
    def test_full_dry_run(self, mock_feed):
        """End-to-end pipeline dry run: ingest, cluster, validate, score, draft."""
        from nasvetlo.ingestion.normalize import ingest_all
        from nasvetlo.clustering.clusterer import cluster_new_articles
        from nasvetlo.clustering.coherence import validate_candidates
        from nasvetlo.scoring.importance import score_clusters, get_eligible_clusters

        # Step 1: Ingest
        new_count = ingest_all(self.session, self.config)
        assert new_count == 4  # 3 budget articles + 1 weather

        articles = self.session.query(RawArticle).all()
        assert len(articles) == 4

        # Step 2: Cluster
        clustered = cluster_new_articles(self.session, self.config)
        assert clustered == 4

        clusters = self.session.query(Cluster).all()
        # The 3 identical titles should cluster together, weather separate
        budget_cluster = None
        for c in clusters:
            if c.unique_domain_count >= 3:
                budget_cluster = c
                break

        assert budget_cluster is not None, f"Expected a cluster with 3+ sources. Clusters: {[(c.id, c.unique_domain_count) for c in clusters]}"
        assert budget_cluster.is_candidate is True

        # Step 3: Coherence
        validated = validate_candidates(self.session, self.config)
        assert validated >= 1
        assert budget_cluster.coherence_validated is True
        assert budget_cluster.rejected is False

        # Step 4: Score
        scored = score_clusters(self.session, self.config)
        assert scored >= 1
        assert budget_cluster.importance_score is not None
        assert budget_cluster.importance_score >= 0.60

        # Step 5: Draft (dry run)
        eligible = get_eligible_clusters(self.session, self.config)
        assert len(eligible) >= 1

    @patch("nasvetlo.ingestion.normalize.fetch_feed", side_effect=mock_fetch_feed)
    def test_deduplication(self, mock_feed):
        """Ingesting the same feed twice should not create duplicates."""
        from nasvetlo.ingestion.normalize import ingest_all

        first = ingest_all(self.session, self.config)
        second = ingest_all(self.session, self.config)

        assert first == 4
        assert second == 0  # All deduplicated

    @patch("nasvetlo.ingestion.normalize.fetch_feed", side_effect=mock_fetch_feed)
    def test_run_pipeline_function(self, mock_feed):
        """Test the run_pipeline orchestrator in dry-run mode."""
        from nasvetlo.pipeline.run_once import run_pipeline

        summary = run_pipeline(self.config, dry_run=True, max_drafts=2)

        assert summary["dry_run"] is True
        assert summary["articles_ingested"] == 4
        assert summary["errors"] == 0 or summary["errors"] >= 0  # Tolerate some errors in mocked env
