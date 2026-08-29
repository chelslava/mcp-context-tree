"""Cross-Encoder re-ranking for second-stage precision ranking in code search.

Jointly encodes (query, code_document) pairs through full cross-attention to
accurately score semantic relevance.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from context_tree.store import SearchHit

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

DEFAULT_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
ENV_RERANKER_MODEL = "CONTEXT_TREE_RERANKER_MODEL"


class ReRanker:
    """Lazy-loaded Cross-Encoder re-ranker for search candidates."""

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or os.environ.get(ENV_RERANKER_MODEL) or DEFAULT_RERANKER_MODEL
        self._model: CrossEncoder | None = None

    @property
    def model(self) -> CrossEncoder:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
        return self._model

    def rerank(self, query: str, hits: list[SearchHit], limit: int = 5) -> list[SearchHit]:
        """Score candidate hits with cross-encoder and return top ranked hits."""
        if not hits or not query.strip():
            return hits[:limit]

        pairs = [[query, hit.document] for hit in hits]
        raw_scores = self.model.predict(pairs)

        # Predict can return a scalar or numpy array
        scores: list[float] = [float(s) for s in raw_scores]

        scored_hits = [
            SearchHit(
                id=hit.id,
                score=score,
                metadata=hit.metadata,
                document=hit.document,
            )
            for hit, score in zip(hits, scores, strict=False)
        ]

        scored_hits.sort(key=lambda h: h.score, reverse=True)
        return scored_hits[:limit]
