"""Tests for semantic search, live snippet resolution, and cross-encoder re-ranking."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from context_tree.hybrid import BM25Index
from context_tree.indexer import Indexer
from context_tree.reranker import ReRanker
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


def test_semantic_search_hybrid_call_graph_boost(tmp_path: Path) -> None:
    src_file1 = tmp_path / "auth.py"
    src_file1.write_text(
        "def authenticate_user(u, p):\n    '''Verify user login'''\n    return True\n",
        encoding="utf-8",
    )

    src_file2 = tmp_path / "app.py"
    src_file2.write_text(
        "def main():\n"
        "    authenticate_user('a', 'b')\n"
        "    authenticate_user('c', 'd')\n"
        "    authenticate_user('e', 'f')\n",
        encoding="utf-8",
    )

    indexer = Indexer(tmp_path)
    indexer.index()

    results = semantic_search(tmp_path, "authenticate user login", mode="hybrid", limit=2)
    assert len(results) >= 1
    assert results[0].name == "authenticate_user"
    assert results[0].score > 0.0


def test_semantic_search_with_rerank(tmp_path: Path, monkeypatch) -> None:
    src_file1 = tmp_path / "calc.py"
    src_file1.write_text("def add(a, b): return a + b\n", encoding="utf-8")

    src_file2 = tmp_path / "math_utils.py"
    src_file2.write_text("def multiply(a, b): return a * b\n", encoding="utf-8")

    indexer = Indexer(tmp_path)
    indexer.index()

    # Mock reranker predict to boost multiply
    orig_init = ReRanker.__init__

    def mock_init(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        mock_model = MagicMock()
        mock_model.predict.side_effect = lambda pairs: [
            0.99 if "multiply" in p[1] else 0.1 for p in pairs
        ]
        self._model = mock_model

    monkeypatch.setattr(ReRanker, "__init__", mock_init)

    results = semantic_search(tmp_path, "compute result", mode="hybrid", limit=2, rerank=True)
    assert len(results) >= 2
    assert results[0].name == "multiply"
    assert results[0].score == 0.99
