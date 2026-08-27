"""Tests for semantic search and live snippet resolution."""

from __future__ import annotations

from pathlib import Path

from context_tree.indexer import Indexer
from context_tree.search import semantic_search


def test_semantic_search_empty_store(tmp_path: Path) -> None:
    results = semantic_search(tmp_path, "some query")
    assert results == []


def test_semantic_search_live_snippet(tmp_path: Path) -> None:
    src_file = tmp_path / "auth.py"
    src_content = (
        "def authenticate_user(username, password):\n"
        '    """Verify user credentials and grant access."""\n'
        "    if not username or not password:\n"
        "        return False\n"
        "    return True\n"
    )
    src_file.write_text(src_content, encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    results = semantic_search(tmp_path, "how to check user login credentials", limit=1)
    assert len(results) == 1
    hit = results[0]
    assert hit.file == "auth.py"
    assert hit.name == "authenticate_user"
    assert "Verify user credentials" in hit.code
    assert hit.start_line == 1
    assert hit.score > 0.0


def test_bm25_index_cached_and_invalidated_on_reindex(tmp_path: Path, monkeypatch) -> None:
    from context_tree.hybrid import BM25Index

    src_file = tmp_path / "calc.py"
    src_file.write_text("def calculate_sum(a, b):\n    return a + b\n", encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    build_calls = 0
    orig_build = BM25Index.build

    def counting_build(self, *args, **kwargs):
        nonlocal build_calls
        build_calls += 1
        return orig_build(self, *args, **kwargs)

    monkeypatch.setattr(BM25Index, "build", counting_build)

    # First search builds BM25
    res1 = semantic_search(tmp_path, "calculate sum", mode="keyword")
    assert len(res1) == 1
    assert build_calls == 1

    # Second search reuses cache without building
    res2 = semantic_search(tmp_path, "calculate sum", mode="keyword")
    assert len(res2) == 1
    assert build_calls == 1

    # Third search (hybrid) also reuses cached BM25
    res3 = semantic_search(tmp_path, "calculate sum", mode="hybrid")
    assert len(res3) == 1
    assert build_calls == 1

    # Modify file and re-index -> invalidates cache
    src_file.write_text("def calculate_product(a, b):\n    return a * b\n", encoding="utf-8")
    indexer.index()

    # Next search rebuilds BM25 and reflects new symbol
    res4 = semantic_search(tmp_path, "calculate product", mode="keyword")
    assert len(res4) == 1
    assert res4[0].name == "calculate_product"
    assert build_calls == 2

