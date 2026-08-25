"""Tests for tokenizer, BM25 indexing, and Reciprocal Rank Fusion."""

from __future__ import annotations

from context_tree.hybrid import (
    BM25Index,
    reciprocal_rank_fusion,
    tokenize_code,
)
from context_tree.store import SearchHit


def test_tokenize_code() -> None:
    tokens = tokenize_code("AuthService.verify_jwt_token(requestHeader)")
    assert "authservice" in tokens
    assert "auth" in tokens
    assert "service" in tokens
    assert "verify" in tokens
    assert "jwt" in tokens
    assert "token" in tokens
    assert "request" in tokens
    assert "header" in tokens


def test_bm25_index_query() -> None:
    docs = [
        ("id1", "def login_user(username, password): pass", {"file": "auth.py"}),
        ("id2", "def payment_checkout(card, amount): pass", {"file": "pay.py"}),
    ]
    idx = BM25Index()
    idx.build(docs)

    hits = idx.query("checkout payment", limit=2)
    assert len(hits) == 1
    assert hits[0].id == "id2"
    assert hits[0].score > 0.0


def test_reciprocal_rank_fusion() -> None:
    vec_hits = [
        SearchHit(id="doc1", score=0.9, metadata={}, document="d1"),
        SearchHit(id="doc2", score=0.8, metadata={}, document="d2"),
    ]
    bm25_hits = [
        SearchHit(id="doc2", score=5.0, metadata={}, document="d2"),
        SearchHit(id="doc3", score=4.0, metadata={}, document="d3"),
    ]

    fused = reciprocal_rank_fusion(vec_hits, bm25_hits, limit=3)
    assert len(fused) == 3
    # doc2 appeared in both lists, so should be top ranked in RRF
    assert fused[0].id == "doc2"
