"""ChromaDB persistent vector store client.

Implements ARCHITECTURE.md §7:
- PersistentClient rooted at <workspace>/.chroma/
- Collection context_tree with cosine distance (hnsw:space = cosine)
- Upsert, delete-by-file, and top-k vector query
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection

from context_tree.chunker import Chunk
from context_tree.config import COLLECTION_NAME


@dataclass(frozen=True)
class SearchHit:
    """A single ranked hit from vector search or BM25."""

    id: str
    score: float
    metadata: dict[str, Any]
    document: str


class VectorStore:
    """Wrapper around persistent ChromaDB client."""

    def __init__(self, chroma_dir: Path | str, collection_name: str = COLLECTION_NAME) -> None:
        self.chroma_dir = Path(chroma_dir)
        self.collection_name = collection_name
        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(self.chroma_dir))
        self.collection: Collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def count(self) -> int:
        """Return the number of items in the collection."""
        return self.collection.count()

    def upsert(self, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]]) -> None:
        """Insert or update chunks with their precomputed embeddings."""
        if not chunks:
            return

        ids = [c.id for c in chunks]
        documents = [c.document for c in chunks]
        metadatas = [c.to_metadata() for c in chunks]
        raw_embeddings = list(embeddings)

        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,  # type: ignore[arg-type]
            embeddings=raw_embeddings,  # type: ignore[arg-type]
        )

    def delete_by_files(self, files: Sequence[str]) -> None:
        """Delete all chunk records belonging to any of the specified file paths."""
        if not files:
            return
        for file_path in files:
            self.collection.delete(where={"file": file_path})

    def get_all_documents(self) -> list[tuple[str, str, dict[str, Any]]]:
        """Fetch all indexed (id, document, metadata) records."""
        if self.count() == 0:
            return []
        data = self.collection.get(include=["documents", "metadatas"])  # type: ignore[list-item]
        ids = data.get("ids", [])
        docs = data.get("documents", []) or []
        metas = data.get("metadatas", []) or []
        records: list[tuple[str, str, dict[str, Any]]] = []
        for i, doc_id in enumerate(ids):
            doc = docs[i] if i < len(docs) and docs[i] is not None else ""
            meta = metas[i] if i < len(metas) and metas[i] is not None else {}
            records.append((doc_id, str(doc), meta))
        return records

    def query(self, query_embedding: Sequence[float], limit: int = 5) -> list[SearchHit]:
        """Query top-k most similar records by cosine similarity."""
        if self.count() == 0:
            return []

        results = self.collection.query(
            query_embeddings=[list(query_embedding)],
            n_results=min(limit, self.count()),
            include=["metadatas", "documents", "distances"],  # type: ignore[list-item]
        )

        hits: list[SearchHit] = []
        ids_list = results.get("ids", [[]])[0]
        distances = results.get("distances", [[]])[0] if results.get("distances") else []
        metadatas = results.get("metadatas", [[]])[0] if results.get("metadatas") else []
        documents = results.get("documents", [[]])[0] if results.get("documents") else []

        for i, doc_id in enumerate(ids_list):
            dist = distances[i] if i < len(distances) else 0.0
            # score = 1 - cosine distance (§9)
            score = 1.0 - dist
            meta = metadatas[i] if i < len(metadatas) and metadatas[i] is not None else {}
            doc = documents[i] if i < len(documents) and documents[i] is not None else ""
            hits.append(SearchHit(id=doc_id, score=score, metadata=meta, document=doc))

        return hits
