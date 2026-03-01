"""Embedding interface and implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod

from nasvetlo.logging_utils import get_logger

log = get_logger("clustering.embeddings")


class EmbeddingProvider(ABC):
    """Abstract base for embedding providers."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return embeddings for a list of texts."""
        ...

    def embed_single(self, text: str) -> list[float]:
        return self.embed([text])[0]


class LocalTransformerEmbedding(EmbeddingProvider):
    """Local sentence-transformers embeddings."""

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        self._model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            log.info("Loading embedding model: %s", self._model_name)
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._load()
        embeddings = self._model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        return [e.tolist() for e in embeddings]


class DummyEmbedding(EmbeddingProvider):
    """Deterministic dummy embeddings for testing (hash-based)."""

    def __init__(self, dim: int = 384):
        self._dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        import hashlib
        results = []
        for text in texts:
            h = hashlib.sha256(text.encode("utf-8")).digest()
            # Expand hash to fill dimension
            expanded = h * ((self._dim * 4 // len(h)) + 1)
            vec = []
            for i in range(self._dim):
                byte_val = expanded[i]
                vec.append((byte_val - 128) / 128.0)
            # Normalize
            import math
            norm = math.sqrt(sum(x * x for x in vec))
            if norm > 0:
                vec = [x / norm for x in vec]
            results.append(vec)
        return results


_provider: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    """Get the configured embedding provider."""
    global _provider
    if _provider is None:
        try:
            _provider = LocalTransformerEmbedding()
        except ImportError:
            log.warning("sentence-transformers not available, using dummy embeddings")
            _provider = DummyEmbedding()
    return _provider


def set_embedding_provider(provider: EmbeddingProvider) -> None:
    """Override the embedding provider (for testing)."""
    global _provider
    _provider = provider
