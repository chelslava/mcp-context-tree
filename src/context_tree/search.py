"""Semantic and hybrid search execution and disk-backed snippet resolution.

Implements ARCHITECTURE.md §9 & v0.2 Hybrid Search (BM25 + RRF).
"""

from __future__ import annotations

from collections.abc import Sequence
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
    repo: str = ""

    def to_dict(self) -> dict:
        data = {
            "file": self.file,
            "type": self.type,
            "class": self.class_chain,
            "name": self.name,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "score": round(self.score, 4),
            "code": self.code,
        }
        if self.repo:
            data["repo"] = self.repo
        return data


def read_snippet_from_disk(
    roots: Path | Sequence[Path],
    rel_file: str,
    start_line: int,
    end_line: int,
    fallback_doc: str,
    repo: str = "",
) -> str:
    """Read snippet lines [start_line..end_line] from disk if file exists in any workspace root."""
    root_list = [roots] if isinstance(roots, Path) else list(roots)

    # If repo is specified, prioritize matching root directory
    if repo:
        matched = [r for r in root_list if r.name == repo]
        if matched:
            root_list = matched + [r for r in root_list if r.name != repo]

    for root_dir in root_list:
        file_path = (root_dir / rel_file).resolve()
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
    root: Path | str | Sequence[Path | str],
    query: str,
    limit: int = DEFAULT_SEARCH_LIMIT,
    mode: SearchMode = "hybrid",
    store: VectorStore | None = None,
    embedder: Embedder | None = None,
    rerank: bool = False,
    repo: str | None = None,
) -> list[SearchResult]:
    """Execute code search (hybrid BM25+RRF, semantic, or keyword) over workspace(s)."""
    from context_tree.indexer import resolve_workspace_roots

    roots = resolve_workspace_roots(root)
    primary_root = roots[0]
    chroma_dir = primary_root / CHROMA_DIR_NAME
    vstore = store or VectorStore(chroma_dir)

    if vstore.count() == 0:
        return []

    emb = embedder or Embedder()
    hits: list[SearchHit] = []
    where_filter = {"repo": repo} if repo else None

    # If rerank is enabled, fetch more initial candidates to rerank
    candidate_limit = max(limit * 3, 15) if rerank else limit

    if mode == "semantic":
        q_vec = emb.encode_single(query)
        hits = vstore.query(q_vec, limit=candidate_limit, where=where_filter)

    elif mode == "keyword":
        bm25 = get_or_build_bm25(primary_root, vstore)
        hits = bm25.query(query, limit=candidate_limit, where_repo=repo)

    else:  # hybrid
        q_vec = emb.encode_single(query)
        vec_hits = vstore.query(q_vec, limit=max(candidate_limit * 2, 10), where=where_filter)

        bm25 = get_or_build_bm25(primary_root, vstore)
        bm25_hits = bm25.query(query, limit=max(candidate_limit * 2, 10), where_repo=repo)

        # Compute call-graph ranks for candidate pool based on AST usage frequency
        from context_tree.usages import batch_count_ast_usages

        candidates = {h.id: h for h in list(vec_hits) + list(bm25_hits)}
        symbol_names = {
            str(h.metadata.get("name", "")).strip()
            for h in candidates.values()
            if str(h.metadata.get("name", "")).strip()
        }
        symbol_counts = batch_count_ast_usages(roots, symbol_names, max_hits_per_symbol=50)

        sorted_by_usage = sorted(
            candidates.keys(),
            key=lambda doc_id: symbol_counts.get(
                str(candidates[doc_id].metadata.get("name", "")).strip(), 0
            ),
            reverse=True,
        )
        graph_ranks = {doc_id: rank for rank, doc_id in enumerate(sorted_by_usage, start=1)}

        hits = reciprocal_rank_fusion(
            vec_hits, bm25_hits, graph_ranks=graph_ranks, limit=candidate_limit
        )

    if rerank and hits:
        from context_tree.reranker import ReRanker

        reranker = ReRanker()
        hits = reranker.rerank(query, hits, limit=limit)

    results: list[SearchResult] = []
    for hit in hits:
        meta = hit.metadata
        rel_file = str(meta.get("file", ""))
        start_line = int(meta.get("start_line", 1))
        end_line = int(meta.get("end_line", 1))
        b_type = str(meta.get("type", "function"))
        class_chain = str(meta.get("class", ""))
        name = str(meta.get("name", ""))
        repo_val = str(meta.get("repo", ""))

        code = read_snippet_from_disk(
            roots, rel_file, start_line, end_line, hit.document, repo=repo_val
        )

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
                repo=repo_val,
            )
        )

    return results
