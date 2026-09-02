"""Tests for embedding quantization (float32, int8, binary, ubinary)."""

from __future__ import annotations

from pathlib import Path

from context_tree.embedder import Embedder
from context_tree.indexer import Indexer
from context_tree.search import semantic_search


def test_embedder_float32_precision() -> None:
    emb = Embedder(precision="float32")
    vec = emb.encode_single("function compute_total(a, b)")
    assert len(vec) == 384
    assert isinstance(vec[0], float)


def test_embedder_int8_quantization() -> None:
    emb = Embedder(precision="int8")
    vecs = emb.encode(["def add(x, y): return x + y", "def sub(x, y): return x - y"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 384
    # Check int8 values
    assert isinstance(vecs[0][0], int)
    assert all(-128 <= val <= 127 for val in vecs[0])


def test_embedder_ubinary_quantization() -> None:
    emb = Embedder(precision="ubinary")
    vecs = emb.encode(["def mul(x, y): return x * y"])
    assert len(vecs) == 1
    # 384 dimensions packed into 384/8 = 48 bytes
    assert len(vecs[0]) == 48
    assert isinstance(vecs[0][0], int)
    assert all(0 <= val <= 255 for val in vecs[0])


def test_int8_quantized_indexing_and_search(tmp_path: Path) -> None:
    src_file = tmp_path / "payment.py"
    src_file.write_text(
        "def process_stripe_payment(amount: float, customer_id: str) -> bool:\n"
        '    """Execute credit card charge through Stripe Gateway."""\n'
        "    return amount > 0\n",
        encoding="utf-8",
    )

    int8_embedder = Embedder(precision="int8")
    indexer = Indexer(tmp_path, embedder=int8_embedder)
    stats = indexer.index()
    assert stats.indexed_chunks == 1
    assert stats.total_in_store == 1

    # Search with matching int8 embedder
    results = semantic_search(
        tmp_path,
        "charge credit card via Stripe",
        limit=1,
        mode="semantic",
        embedder=int8_embedder,
    )
    assert len(results) == 1
    assert results[0].name == "process_stripe_payment"
    assert "process_stripe_payment" in results[0].code


def test_cli_precision_flag(monkeypatch) -> None:
    import os

    from context_tree.__main__ import main

    monkeypatch.setattr("sys.argv", ["context-tree", "--precision", "int8", "--transport", "stdio"])

    async def mock_run_stdio():
        pass

    monkeypatch.setattr("context_tree.__main__.run_stdio_server", mock_run_stdio)
    main()
    assert os.environ.get("CONTEXT_TREE_EMBEDDING_PRECISION") == "int8"
