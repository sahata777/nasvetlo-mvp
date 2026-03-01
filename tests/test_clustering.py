"""Tests for clustering assignment and centroid update."""

import json
from datetime import datetime, timezone, timedelta

from nasvetlo.models import Base, RawArticle, Cluster, SourceRegistry
from nasvetlo.utils.cosine import cosine_similarity, mean_vector
from nasvetlo.clustering.embeddings import DummyEmbedding, set_embedding_provider
from nasvetlo.clustering.clusterer import cluster_new_articles, _update_cluster


class TestCosine:
    def test_identical_vectors(self):
        v = [1.0, 0.0, 0.0]
        assert abs(cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert abs(cosine_similarity(a, b)) < 1e-6

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert abs(cosine_similarity(a, b) + 1.0) < 1e-6

    def test_empty_vectors(self):
        assert cosine_similarity([], []) == 0.0

    def test_zero_vector(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


class TestMeanVector:
    def test_single(self):
        result = mean_vector([[1.0, 2.0, 3.0]])
        assert result == [1.0, 2.0, 3.0]

    def test_two(self):
        result = mean_vector([[1.0, 0.0], [0.0, 1.0]])
        assert abs(result[0] - 0.5) < 1e-6
        assert abs(result[1] - 0.5) < 1e-6

    def test_empty(self):
        assert mean_vector([]) == []


class TestClustering:
    def test_new_article_creates_cluster(self, in_memory_db, sample_config):
        session = in_memory_db
        set_embedding_provider(DummyEmbedding(dim=16))

        # Add source
        source = SourceRegistry(name="Source A", rss_url="https://a.bg/rss", tier=1, credibility_score=0.95)
        session.add(source)
        session.flush()

        # Add article
        article = RawArticle(
            source_id=source.id,
            url="https://a.bg/article/1",
            title="Парламентът гласува бюджета",
            summary="Народното събрание одобри бюджета за 2024.",
            content_hash="hash1",
            published_at=datetime.now(timezone.utc),
        )
        session.add(article)
        session.commit()

        result = cluster_new_articles(session, sample_config)
        assert result == 1
        assert article.cluster_id is not None

        cluster = session.query(Cluster).filter_by(id=article.cluster_id).first()
        assert cluster is not None
        assert cluster.unique_domain_count == 1
        assert cluster.is_candidate is False  # Only 1 source

    def test_similar_articles_same_cluster(self, in_memory_db, sample_config):
        session = in_memory_db
        set_embedding_provider(DummyEmbedding(dim=16))

        sources = []
        for name, url in [("A", "https://a.bg"), ("B", "https://b.bg"), ("C", "https://c.bg")]:
            s = SourceRegistry(name=name, rss_url=f"{url}/rss", tier=1, credibility_score=0.90)
            session.add(s)
            sources.append(s)
        session.flush()

        # Same title = same embedding from DummyEmbedding (hash-based)
        same_title = "Идентично заглавие за тест"
        same_summary = "Идентично резюме за тест"
        now = datetime.now(timezone.utc)

        for i, source in enumerate(sources):
            article = RawArticle(
                source_id=source.id,
                url=f"https://{chr(97+i)}.bg/article/1",
                title=same_title,
                summary=same_summary,
                content_hash=f"hash_{i}",
                published_at=now,
            )
            session.add(article)
        session.commit()

        result = cluster_new_articles(session, sample_config)
        assert result == 3

        # All should be in the same cluster
        articles = session.query(RawArticle).all()
        cluster_ids = set(a.cluster_id for a in articles)
        assert len(cluster_ids) == 1

        cluster = session.query(Cluster).first()
        assert cluster.unique_domain_count == 3
        assert cluster.is_candidate is True  # 3 unique sources

    def test_cluster_centroid_updated(self, in_memory_db, sample_config):
        session = in_memory_db
        set_embedding_provider(DummyEmbedding(dim=16))

        source = SourceRegistry(name="A", rss_url="https://a.bg/rss", tier=1, credibility_score=0.90)
        session.add(source)
        session.flush()

        article = RawArticle(
            source_id=source.id,
            url="https://a.bg/1",
            title="Test Title",
            summary="Test Summary",
            content_hash="hash_test",
            published_at=datetime.now(timezone.utc),
        )
        session.add(article)
        session.commit()

        cluster_new_articles(session, sample_config)

        cluster = session.query(Cluster).first()
        centroid = cluster.centroid
        assert len(centroid) == 16
        assert any(v != 0.0 for v in centroid)
