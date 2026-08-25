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
        'def authenticate_user(username, password):\n'
        '    """Verify user credentials and grant access."""\n'
        '    if not username or not password:\n'
        '        return False\n'
        '    return True\n'
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
