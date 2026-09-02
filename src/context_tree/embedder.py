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

from context_tree.config import (
    DEFAULT_EMBEDDING_PRECISION,
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_MODEL_NAME,
)

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
    """Wrapper around SentenceTransformer with batching, L2 normalization, and quantization."""

    def __init__(
        self,
        model_name: str = EMBEDDING_MODEL_NAME,
        precision: str = DEFAULT_EMBEDDING_PRECISION,
    ) -> None:
        self.model_name = model_name
        self.precision = precision

    def encode(
        self,
        texts: Sequence[str],
        batch_size: int = EMBEDDING_BATCH_SIZE,
        precision: str | None = None,
    ) -> list[list[float | int]]:
        """Compute L2-normalized embeddings for *texts*, with optional precision quantization."""
        if not texts:
            return []
        model = get_model(self.model_name)
        prec = precision or self.precision

        encode_kwargs: dict = {
            "batch_size": batch_size,
            "show_progress_bar": False,
            "normalize_embeddings": True,
        }
        if prec != "float32":
            encode_kwargs["precision"] = prec

        embeddings = model.encode(list(texts), **encode_kwargs)
        return [vec.tolist() for vec in embeddings]

    def encode_single(self, text: str, precision: str | None = None) -> list[float | int]:
        """Compute embedding for a single text."""
        res = self.encode([text], batch_size=1, precision=precision)
        return res[0]
