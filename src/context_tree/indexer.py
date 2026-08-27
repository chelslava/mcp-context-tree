"""Orchestration of workspace scanning, diffing, extraction, embedding, and storing.

Implements ARCHITECTURE.md §4.1, §4.2, and §8:
- File discovery with deny-list & allow-list filtering
- Incremental indexing pipeline
- Fast-path for unchanged workspaces
- Atomic state persistence
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path

from context_tree.chunker import Chunk, chunk_blocks
from context_tree.config import (
    BINARY_SNIFF_BYTES,
    CHROMA_DIR_NAME,
    EMBEDDING_BATCH_SIZE,
    IGNORED_DIRS,
    MAX_FILE_SIZE_BYTES,
    STATE_FILE_NAME,
)
from context_tree.embedder import Embedder
from context_tree.extractor import extract_blocks
from context_tree.languages import get_language_config
from context_tree.state import diff_state, load_state, save_state_atomic
from context_tree.store import VectorStore


@dataclass(frozen=True)
class IndexStats:
    """Summary of an indexing execution run."""

    added: int
    modified: int
    deleted: int
    unchanged: int
    indexed_chunks: int
    total_in_store: int


def _load_gitignore_patterns(gitignore_path: Path) -> list[str]:
    """Load non-empty, non-comment patterns from a .gitignore file."""
    if not gitignore_path.is_file():
        return []
    try:
        content = gitignore_path.read_text(encoding="utf-8", errors="replace")
        patterns: list[str] = []
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)
        return patterns
    except OSError:
        return []


def _is_gitignored(rel_posix: str, patterns: list[str]) -> bool:
    """Check if relative posix path matches any gitignore pattern."""
    norm_path = rel_posix.strip("/")
    parts = norm_path.split("/")
    filename = parts[-1] if parts else ""

    for pat in patterns:
        negated = False
        if pat.startswith("!"):
            negated = True
            pat = pat[1:]

        is_dir_pat = pat.endswith("/")
        clean_pat = pat.rstrip("/")

        if is_dir_pat:
            if any(fnmatch.fnmatch(p, clean_pat) for p in parts):
                return not negated
            if fnmatch.fnmatch(norm_path, f"*{clean_pat}/*") or fnmatch.fnmatch(
                norm_path, f"{clean_pat}/*"
            ):
                return not negated
        else:
            if fnmatch.fnmatch(norm_path, pat) or fnmatch.fnmatch(filename, pat):
                return not negated
            if any(fnmatch.fnmatch(p, pat) for p in parts):
                return not negated

    return False


def discover_files(root: Path) -> dict[str, Path]:
    """Recursively discover indexable source files in *root*.

    Respects IGNORED_DIRS, .gitignore patterns, extension allow-list, size limit,
    and binary sniff.
    Returns mapping: relative_posix_path -> absolute Path.
    """
    candidates: dict[str, Path] = {}
    root_resolved = root.resolve()
    gitignore_patterns = _load_gitignore_patterns(root_resolved / ".gitignore")

    for dirpath, dirnames, filenames in os.walk(root_resolved):
        # Filter ignored directories in-place to prevent descending
        dirnames[:] = [
            d
            for d in dirnames
            if d not in IGNORED_DIRS
            and not (
                gitignore_patterns
                and _is_gitignored(
                    (Path(dirpath).resolve().relative_to(root_resolved) / d).as_posix() + "/",
                    gitignore_patterns,
                )
            )
        ]

        dir_path = Path(dirpath)
        for fname in filenames:
            file_path = dir_path / fname
            if get_language_config(file_path) is None:
                continue

            try:
                rel_posix = file_path.relative_to(root_resolved).as_posix()
            except ValueError:
                continue

            if gitignore_patterns and _is_gitignored(rel_posix, gitignore_patterns):
                continue

            try:
                st = file_path.stat()
                if st.st_size > MAX_FILE_SIZE_BYTES:
                    continue
                # Quick binary check
                with file_path.open("rb") as f:
                    header = f.read(BINARY_SNIFF_BYTES)
                    if b"\x00" in header:
                        continue
            except OSError:
                continue

            candidates[rel_posix] = file_path

    return candidates


class Indexer:
    """Coordinates workspace indexing into VectorStore."""

    def __init__(
        self,
        root: Path | str,
        store: VectorStore | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.chroma_dir = self.root / CHROMA_DIR_NAME
        self.state_file = self.chroma_dir / STATE_FILE_NAME
        self.store = store or VectorStore(self.chroma_dir)
        self.embedder = embedder or Embedder()

    def index(self) -> IndexStats:
        """Run incremental indexing on the workspace root."""
        candidates = discover_files(self.root)
        old_state = load_state(self.state_file)
        diff, new_state = diff_state(candidates, old_state)

        # Fast-path: no changes detected
        if not diff.has_changes:
            return IndexStats(
                added=0,
                modified=0,
                deleted=0,
                unchanged=len(diff.unchanged),
                indexed_chunks=0,
                total_in_store=self.store.count(),
            )

        # Remove stale vectors for modified and deleted files
        stale_files = diff.modified + diff.deleted
        if stale_files:
            self.store.delete_by_files(stale_files)

        # Process added and modified files
        new_chunks: list[Chunk] = []
        files_to_process = sorted(diff.added + diff.modified)

        for rel_path in files_to_process:
            abs_path = candidates[rel_path]
            blocks = extract_blocks(abs_path, root=self.root)
            file_chunks = chunk_blocks(blocks)
            new_chunks.extend(file_chunks)

        # Embed and upsert new chunks
        if new_chunks:
            documents = [c.document for c in new_chunks]
            embeddings = self.embedder.encode(documents, batch_size=EMBEDDING_BATCH_SIZE)
            self.store.upsert(new_chunks, embeddings)

        # Atomically commit new state
        save_state_atomic(new_state, self.state_file)

        return IndexStats(
            added=len(diff.added),
            modified=len(diff.modified),
            deleted=len(diff.deleted),
            unchanged=len(diff.unchanged),
            indexed_chunks=len(new_chunks),
            total_in_store=self.store.count(),
        )
