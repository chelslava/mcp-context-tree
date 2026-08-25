"""Embedding layer: sentence-transformers lazy singleton with batching.

Implements ARCHITECTURE.md §6:
- sentence-transformers/all-MiniLM-L6-v2 (384 dims)
- L2 normalized embeddings (cosine-ready)
- Batching support (EMBEDDING_BATCH_SIZE)
- Lazy singleton lifecycle
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from context_tree.config import EMBEDDING_BATCH_SIZE, EMBEDDING_MODEL_NAME

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_MODEL_INSTANCE: SentenceTransformer | None = None


def get_model(model_name: str = EMBEDDING_MODEL_NAME) -> SentenceTransformer:
    """Return the cached SentenceTransformer singleton instance."""
    global _MODEL_INSTANCE
    if _MODEL_INSTANCE is None:
        from sentence_transformers import SentenceTransformer

        _MODEL_INSTANCE = SentenceTransformer(model_name)
    return _MODEL_INSTANCE


class Embedder:
    """Wrapper around SentenceTransformer with batching and L2 normalization."""

    def __init__(self, model_name: str = EMBEDDING_MODEL_NAME) -> None:
        self.model_name = model_name

    def encode(
        self, texts: Sequence[str], batch_size: int = EMBEDDING_BATCH_SIZE
    ) -> list[list[float]]:
        """Compute L2-normalized embeddings for *texts*."""
        if not texts:
            return []
        model = get_model(self.model_name)
        # normalize_embeddings=True ensures cosine similarity can be computed via dot product
        embeddings = model.encode(
            list(texts),
            batch_size=batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return [vec.tolist() for vec in embeddings]

    def encode_single(self, text: str) -> list[float]:
        """Compute embedding for a single text."""
        res = self.encode([text], batch_size=1)
        return res[0]
