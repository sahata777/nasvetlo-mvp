"""Tests for importance scoring formula."""

import json
from datetime import datetime, timezone, timedelta

from nasvetlo.models import Cluster, RawArticle, SourceRegistry
from nasvetlo.scoring.importance import compute_importance, TIER_SCORES
from nasvetlo.clustering.embeddings import DummyEmbedding, set_embedding_provider


class TestImportanceScoring:
    def _setup_cluster(self, session, n_sources=3, tier=1, age_hours=1, span_hours=0.5):
        """Helper to create a cluster with N sources."""
        sources = []
        now = datetime.now(timezone.utc)

        for i in range(n_sources):
            s = SourceRegistry(
                name=f"Src_{i}",
                rss_url=f"https://src{i}.bg/rss",
                tier=tier,
                credibility_score=0.90,
            )
            session.add(s)
            sources.append(s)
        session.flush()

        cluster = Cluster(
            centroid_json="[]",
            window_start=now - timedelta(hours=age_hours + span_hours),
            window_end=now - timedelta(hours=age_hours),
            unique_domain_count=n_sources,
        )
        session.add(cluster)
        session.flush()

        for i, src in enumerate(sources):
            pub_time = now - timedelta(hours=age_hours + span_hours * (1 - i / max(n_sources - 1, 1)))
            article = RawArticle(
                source_id=src.id,
                url=f"https://src{i}.bg/article/1",
                title="Тест заглавие за парламент",
                summary="Тест резюме",
                content_hash=f"hash_{i}_{n_sources}",
                published_at=pub_time,
                cluster_id=cluster.id,
            )
            session.add(article)

        session.commit()
        return cluster

    def test_high_importance_cluster(self, in_memory_db, sample_config):
        """6 Tier-1 sources, fresh, fast-breaking, institutional."""
        session = in_memory_db
        cluster = self._setup_cluster(session, n_sources=6, tier=1, age_hours=0.5, span_hours=0.5)

        score = compute_importance(session, cluster, sample_config)

        # S_norm = min(1, 6/6) = 1.0
        # Tier_avg = 1.0
        # Speed = clamp(0,1,1-0.5/12) ≈ 0.958
        # Institutional = 1 (tier 1)
        # Decay = clamp(0,1, 0.5/24) ≈ 0.021
        # Score ≈ 0.35*1 + 0.25*1 + 0.15*0.958 + 0.15*1 + 0.10*(1-0.021) ≈ 0.35+0.25+0.144+0.15+0.098 ≈ 0.99
        assert score > 0.90

    def test_low_importance_cluster(self, in_memory_db, sample_config):
        """1 Tier-4 source, old, no institutional."""
        session = in_memory_db
        cluster = self._setup_cluster(session, n_sources=1, tier=4, age_hours=20, span_hours=0)

        score = compute_importance(session, cluster, sample_config)

        # S_norm = min(1, 1/6) ≈ 0.167
        # Tier_avg = 0.3
        # Speed = 1 (span=0)
        # Institutional = 1 (keyword "парламент" in text)
        # Decay = clamp(0,1, 20/24) ≈ 0.833
        # Score ≈ 0.35*0.167 + 0.25*0.3 + 0.15*1 + 0.15*1 + 0.10*(1-0.833)
        # ≈ 0.058 + 0.075 + 0.15 + 0.15 + 0.017 ≈ 0.45
        assert score < 0.60

    def test_scoring_formula_components(self, in_memory_db, sample_config):
        """Verify individual formula components."""
        session = in_memory_db
        cluster = self._setup_cluster(session, n_sources=3, tier=2, age_hours=2, span_hours=1)

        score = compute_importance(session, cluster, sample_config)

        # S_norm = min(1, 3/6) = 0.5
        # Tier_avg = 0.8 (tier 2)
        # Speed = clamp(0,1, 1-1/12) ≈ 0.917
        # Institutional = 1 (keyword match)
        # Decay = clamp(0,1, 2/24) ≈ 0.083
        # Score ≈ 0.35*0.5 + 0.25*0.8 + 0.15*0.917 + 0.15*1 + 0.10*(1-0.083)
        # ≈ 0.175 + 0.2 + 0.138 + 0.15 + 0.092 ≈ 0.755
        assert 0.60 < score < 0.90

    def test_tier_scores_mapping(self):
        assert TIER_SCORES[1] == 1.0
        assert TIER_SCORES[2] == 0.8
        assert TIER_SCORES[3] == 0.6
        assert TIER_SCORES[4] == 0.3
