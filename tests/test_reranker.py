"""Tests for Cross-Encoder re-ranker."""

from __future__ import annotations

from unittest.mock import MagicMock

from context_tree.reranker import ReRanker
from context_tree.store import SearchHit


def test_reranker_reorders_hits() -> None:
    reranker = ReRanker()
    mock_model = MagicMock()
    # Mock scores so that doc2 gets a higher score than doc1
    mock_model.predict.return_value = [0.1, 0.95]
    reranker._model = mock_model

    hits = [
        SearchHit(id="doc1", score=0.8, metadata={"name": "f1"}, document="code 1"),
        SearchHit(id="doc2", score=0.7, metadata={"name": "f2"}, document="code 2"),
    ]

    reranked = reranker.rerank("search query", hits, limit=2)
    assert len(reranked) == 2
    assert reranked[0].id == "doc2"
    assert reranked[0].score == 0.95
    assert reranked[1].id == "doc1"
    assert reranked[1].score == 0.1


def test_reranker_empty_hits() -> None:
    reranker = ReRanker()
    reranked = reranker.rerank("query", [], limit=5)
    assert reranked == []
