"""Tests for ChromaDB VectorStore and Embedder."""

from __future__ import annotations

from pathlib import Path

from context_tree.chunker import Chunk
from context_tree.embedder import Embedder
from context_tree.store import VectorStore


def test_vector_store_crud_and_query(tmp_path: Path) -> None:
    store = VectorStore(tmp_path / ".chroma", collection_name="test_col")
    assert store.count() == 0

    chunk1 = Chunk(
        id="src/auth.py::login",
        document="File: src/auth.py\nMethod: login\nCode:\ndef login(): pass",
        file="src/auth.py",
        chunk_type="function",
        class_chain="",
        name="login",
        language="python",
        start_line=1,
        end_line=5,
        content_hash="h1",
    )
    chunk2 = Chunk(
        id="src/pay.py::pay",
        document="File: src/pay.py\nMethod: pay\nCode:\ndef pay(): pass",
        file="src/pay.py",
        chunk_type="function",
        class_chain="",
        name="pay",
        language="python",
        start_line=1,
        end_line=5,
        content_hash="h2",
    )

    # 384-dim distinct unit embeddings
    emb1 = [1.0] + [0.0] * 383
    emb2 = [0.0, 1.0] + [0.0] * 382

    store.upsert([chunk1, chunk2], [emb1, emb2])
    assert store.count() == 2

    # Query close to emb1
    hits = store.query([1.0] + [0.0] * 383, limit=2)
    assert len(hits) == 2
    assert hits[0].id == "src/auth.py::login"
    assert hits[0].metadata["file"] == "src/auth.py"

    # Delete by file
    store.delete_by_files(["src/auth.py"])
    assert store.count() == 1
    remaining = store.query([1.0] + [0.0] * 383, limit=2)
    assert len(remaining) == 1
    assert remaining[0].id == "src/pay.py::pay"


def test_embedder_encodes_texts() -> None:
    embedder = Embedder()
    texts = ["def auth(): pass", "def payment(): pass"]
    vecs = embedder.encode(texts)
    assert len(vecs) == 2
    assert len(vecs[0]) == 384
    assert len(vecs[1]) == 384

    single = embedder.encode_single("quick test")
    assert len(single) == 384
