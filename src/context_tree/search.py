"""Semantic and hybrid search execution and disk-backed snippet resolution.

Implements ARCHITECTURE.md §9 & v0.2 Hybrid Search (BM25 + RRF).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from context_tree.config import CHROMA_DIR_NAME, DEFAULT_SEARCH_LIMIT, STATE_FILE_NAME
from context_tree.embedder import Embedder
from context_tree.hybrid import BM25Index, reciprocal_rank_fusion
from context_tree.store import SearchHit, VectorStore

SearchMode = Literal["hybrid", "semantic", "keyword"]

_BM25_CACHE: dict[str, tuple[int, BM25Index]] = {}


def invalidate_bm25_cache(root: Path | str | None = None) -> None:
    """Invalidate cached BM25 index for *root* or all workspaces."""
    if root is None:
        _BM25_CACHE.clear()
    else:
        root_key = str(Path(root).resolve())
        _BM25_CACHE.pop(root_key, None)


def get_or_build_bm25(root: Path, vstore: VectorStore) -> BM25Index:
    """Return a cached in-memory BM25Index for *root*, rebuilding if state changed."""
    root_resolved = root.resolve()
    cache_key = str(root_resolved)
    state_file = root_resolved / CHROMA_DIR_NAME / STATE_FILE_NAME

    current_mtime = state_file.stat().st_mtime_ns if state_file.is_file() else 0

    if cache_key in _BM25_CACHE:
        cached_mtime, cached_bm25 = _BM25_CACHE[cache_key]
        if cached_mtime == current_mtime and current_mtime != 0:
            return cached_bm25

    all_docs = vstore.get_all_documents()
    bm25 = BM25Index()
    bm25.build(all_docs)
    _BM25_CACHE[cache_key] = (current_mtime, bm25)
    return bm25


@dataclass(frozen=True)
class SearchResult:
    """A ranked code search result with exact location and live snippet."""

    file: str
    type: str
    class_chain: str
    name: str
    start_line: int
    end_line: int
    score: float
    code: str

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "type": self.type,
            "class": self.class_chain,
            "name": self.name,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "score": round(self.score, 4),
            "code": self.code,
        }


def read_snippet_from_disk(
    root: Path, rel_file: str, start_line: int, end_line: int, fallback_doc: str
) -> str:
    """Read snippet lines [start_line..end_line] from disk if file exists."""
    file_path = (root / rel_file).resolve()
    if file_path.is_file():
        try:
            lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            selected = lines[max(0, start_line - 1) : end_line]
            if selected:
                return "\n".join(selected)
        except OSError:
            pass

    marker = "Code:\n"
    if marker in fallback_doc:
        return fallback_doc.split(marker, 1)[1]
    return fallback_doc


def semantic_search(
    root: Path | str,
    query: str,
    limit: int = DEFAULT_SEARCH_LIMIT,
    mode: SearchMode = "hybrid",
    store: VectorStore | None = None,
    embedder: Embedder | None = None,
) -> list[SearchResult]:
    """Execute code search (hybrid BM25+RRF, semantic, or keyword) over workspace."""
    root_path = Path(root).resolve()
    chroma_dir = root_path / CHROMA_DIR_NAME
    vstore = store or VectorStore(chroma_dir)

    if vstore.count() == 0:
        return []

    emb = embedder or Embedder()
    hits: list[SearchHit] = []

    if mode == "semantic":
        q_vec = emb.encode_single(query)
        hits = vstore.query(q_vec, limit=limit)

    elif mode == "keyword":
        bm25 = get_or_build_bm25(root_path, vstore)
        hits = bm25.query(query, limit=limit)

    else:  # hybrid
        q_vec = emb.encode_single(query)
        vec_hits = vstore.query(q_vec, limit=max(limit * 2, 10))

        bm25 = get_or_build_bm25(root_path, vstore)
        bm25_hits = bm25.query(query, limit=max(limit * 2, 10))

        hits = reciprocal_rank_fusion(vec_hits, bm25_hits, limit=limit)

    results: list[SearchResult] = []
    for hit in hits:
        meta = hit.metadata
        rel_file = str(meta.get("file", ""))
        start_line = int(meta.get("start_line", 1))
        end_line = int(meta.get("end_line", 1))
        b_type = str(meta.get("type", "function"))
        class_chain = str(meta.get("class", ""))
        name = str(meta.get("name", ""))

        code = read_snippet_from_disk(root_path, rel_file, start_line, end_line, hit.document)

        results.append(
            SearchResult(
                file=rel_file,
                type=b_type,
                class_chain=class_chain,
                name=name,
                start_line=start_line,
                end_line=end_line,
                score=hit.score,
                code=code,
            )
        )

    return results
