"""Semantic search execution and disk-backed snippet resolution.

Implements ARCHITECTURE.md §9:
- Embed natural-language query
- Query VectorStore for top-k hits
- Read fresh snippet from disk (start_line..end_line)
- Return structured search results
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from context_tree.config import CHROMA_DIR_NAME, DEFAULT_SEARCH_LIMIT
from context_tree.embedder import Embedder
from context_tree.store import VectorStore


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
            # start_line and end_line are 1-indexed inclusive
            selected = lines[max(0, start_line - 1) : end_line]
            if selected:
                return "\n".join(selected)
        except OSError:
            pass

    # Fallback to code portion of the stored document
    marker = "Code:\n"
    if marker in fallback_doc:
        return fallback_doc.split(marker, 1)[1]
    return fallback_doc


def semantic_search(
    root: Path | str,
    query: str,
    limit: int = DEFAULT_SEARCH_LIMIT,
    store: VectorStore | None = None,
    embedder: Embedder | None = None,
) -> list[SearchResult]:
    """Execute semantic code search over indexed workspace."""
    root_path = Path(root).resolve()
    chroma_dir = root_path / CHROMA_DIR_NAME
    vstore = store or VectorStore(chroma_dir)

    if vstore.count() == 0:
        return []

    emb = embedder or Embedder()
    q_vec = emb.encode_single(query)
    hits = vstore.query(q_vec, limit=limit)

    results: list[SearchResult] = []
    for hit in hits:
        meta = hit.metadata
        rel_file = str(meta.get("file", ""))
        start_line = int(meta.get("start_line", 1))
        end_line = int(meta.get("end_line", 1))
        b_type = str(meta.get("type", "function"))
        class_chain = str(meta.get("class", ""))
        name = str(meta.get("name", ""))

        code = read_snippet_from_disk(
            root_path, rel_file, start_line, end_line, hit.document
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
            )
        )

    return results
