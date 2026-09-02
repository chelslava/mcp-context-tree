"""Hybrid search combining BM25 lexical token matching and dense vector search via RRF.

Implements:
- Identifier-aware code tokenizer (camelCase, snake_case, punctuation)
- Pure-Python in-memory BM25 index over chunk documents
- Reciprocal Rank Fusion (RRF) ranking
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from context_tree.store import SearchHit

_TOKEN_SPLIT_RE = re.compile(r"[^a-zA-Z0-9_]+")
_CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")


def tokenize_code(text: str) -> list[str]:
    """Tokenize code preserving original tokens, camelCase parts, and snake_case parts."""
    raw_tokens = _TOKEN_SPLIT_RE.split(text)
    tokens: list[str] = []

    for raw in raw_tokens:
        if not raw:
            continue
        lower_raw = raw.lower()
        tokens.append(lower_raw)

        # Split snake_case
        if "_" in raw:
            for part in raw.split("_"):
                if part:
                    tokens.append(part.lower())

        # Split camelCase
        camel_split = _CAMEL_RE.sub(r"\1 \2", raw)
        if camel_split != raw:
            for part in camel_split.split():
                if part:
                    tokens.append(part.lower())

    return tokens


@dataclass
class BM25Document:
    id: str
    tokens: list[str]
    length: int
    term_counts: Counter[str]
    metadata: dict
    document: str


class BM25Index:
    """Lightweight in-memory BM25 index for chunk documents."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.docs: list[BM25Document] = []
        self.df: Counter[str] = Counter()
        self.total_docs = 0
        self.avg_len = 0.0

    def build(self, documents: Sequence[tuple[str, str, dict]]) -> None:
        """Build BM25 index from a list of (id, text, metadata) tuples."""
        self.docs = []
        self.df = Counter()
        total_len = 0

        for doc_id, text, meta in documents:
            tokens = tokenize_code(text)
            t_counts = Counter(tokens)
            doc_len = len(tokens)
            total_len += doc_len

            # Update document frequency
            for term in t_counts:
                self.df[term] += 1

            self.docs.append(
                BM25Document(
                    id=doc_id,
                    tokens=tokens,
                    length=doc_len,
                    term_counts=t_counts,
                    metadata=meta,
                    document=text,
                )
            )

        self.total_docs = len(self.docs)
        self.avg_len = (total_len / self.total_docs) if self.total_docs > 0 else 0.0

    def query(
        self, query_text: str, limit: int = 10, where_repo: str | None = None
    ) -> list[SearchHit]:
        """Query index and return top-k SearchHits ranked by BM25 score."""
        if self.total_docs == 0:
            return []

        q_tokens = tokenize_code(query_text)
        if not q_tokens:
            return []

        scores: list[tuple[float, BM25Document]] = []

        for doc in self.docs:
            if where_repo and doc.metadata.get("repo") != where_repo:
                continue
            score = 0.0
            for q in q_tokens:
                if q not in doc.term_counts:
                    continue
                tf = doc.term_counts[q]
                df = self.df.get(q, 0)
                # Robertson-Spärck Jones IDF
                idf = math.log(1.0 + (self.total_docs - df + 0.5) / (df + 0.5))
                # BM25 term weight
                denom = tf + self.k1 * (
                    1.0 - self.b + self.b * (doc.length / (self.avg_len or 1.0))
                )
                score += idf * (tf * (self.k1 + 1.0)) / (denom or 1.0)

            if score > 0.0:
                scores.append((score, doc))

        scores.sort(key=lambda x: x[0], reverse=True)
        top = scores[:limit]

        return [
            SearchHit(
                id=doc.id,
                score=score,
                metadata=doc.metadata,
                document=doc.document,
            )
            for score, doc in top
        ]


def reciprocal_rank_fusion(
    vector_hits: Sequence[SearchHit],
    bm25_hits: Sequence[SearchHit],
    k: int = 60,
    w_vec: float = 1.0,
    w_bm25: float = 1.0,
    w_graph: float = 0.5,
    graph_ranks: dict[str, int] | None = None,
    limit: int = 5,
) -> list[SearchHit]:
    """Fuse vector, BM25, and optional call-graph ranked hits using Reciprocal Rank Fusion (RRF)."""
    scores: dict[str, float] = {}
    hit_map: dict[str, SearchHit] = {}

    for rank, hit in enumerate(vector_hits, start=1):
        scores[hit.id] = scores.get(hit.id, 0.0) + (w_vec / (k + rank))
        hit_map[hit.id] = hit

    for rank, hit in enumerate(bm25_hits, start=1):
        scores[hit.id] = scores.get(hit.id, 0.0) + (w_bm25 / (k + rank))
        if hit.id not in hit_map:
            hit_map[hit.id] = hit

    if graph_ranks and w_graph > 0.0:
        for doc_id, g_rank in graph_ranks.items():
            if doc_id in scores:
                scores[doc_id] += w_graph / (k + g_rank)

    ranked_ids = sorted(scores.keys(), key=lambda doc_id: scores[doc_id], reverse=True)
    fused: list[SearchHit] = []

    for doc_id in ranked_ids[:limit]:
        base_hit = hit_map[doc_id]
        fused.append(
            SearchHit(
                id=doc_id,
                score=scores[doc_id],
                metadata=base_hit.metadata,
                document=base_hit.document,
            )
        )

    return fused
