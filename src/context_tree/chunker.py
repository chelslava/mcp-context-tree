"""Context-Enriched Logical Blocks: chunking, template rendering, and ID generation.

Implements:
- ARCHITECTURE.md §4.5: Oversized blocks splitting with ~15% overlap.
- ARCHITECTURE.md §5: Deterministic context-enriched document template.
- ARCHITECTURE.md §7.1: ID grammar (<file>::<ClassChain>::<name>[@partN]).
- ARCHITECTURE.md §7.2: Record fields and metadata.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Sequence

from context_tree.extractor import CodeBlock

# Thresholds for oversized block splitting (§4.5)
# ~4 chars per token estimate: 512 tokens ~= 2048 chars or ~60 lines
MAX_BLOCK_CHARS = 2048
OVERLAP_RATIO = 0.15


@dataclass(frozen=True)
class Chunk:
    """Enriched document and metadata ready for ChromaDB indexing."""

    id: str
    document: str
    file: str
    chunk_type: str
    class_chain: str
    name: str
    language: str
    start_line: int
    end_line: int
    content_hash: str

    def to_metadata(self) -> dict[str, str | int]:
        """Convert to ChromaDB-compatible metadata dictionary."""
        return {
            "file": self.file,
            "type": self.chunk_type,
            "class": self.class_chain,
            "name": self.name,
            "language": self.language,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "content_hash": self.content_hash,
        }


def compute_content_hash(code: str) -> str:
    """Return SHA-256 hex digest of the code string."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def render_document(
    file_path: str,
    name: str,
    code: str,
    class_chain: str = "",
    docstring: str = "",
) -> str:
    """Render deterministic plain-text document according to ARCHITECTURE.md §5."""
    parts: list[str] = [f"File: {file_path}"]
    if class_chain:
        parts.append(f"Class: {class_chain}")
    parts.append(f"Method: {name}")
    if docstring:
        parts.append(f"Docstring: {docstring}")
    parts.append(f"Code:\n{code}")
    return "\n".join(parts)


def build_base_id(file_path: str, name: str, class_chain: str = "") -> str:
    """Build base chunk ID according to ARCHITECTURE.md §7.1."""
    if class_chain:
        return f"{file_path}::{class_chain}::{name}"
    return f"{file_path}::{name}"


def _split_oversized_code(
    code: str, start_line: int, max_chars: int = MAX_BLOCK_CHARS
) -> list[tuple[str, int, int]]:
    """Split oversized code block into overlapping line-based slices.

    Returns a list of (slice_code, slice_start_line, slice_end_line).
    """
    lines = code.splitlines()
    if not lines:
        return [(code, start_line, start_line)]

    total_lines = len(lines)
    # Estimate chars per line
    avg_line_len = max(1, len(code) // total_lines)
    window_lines = max(10, max_chars // avg_line_len)
    overlap_lines = max(2, int(window_lines * OVERLAP_RATIO))
    step = max(1, window_lines - overlap_lines)

    slices: list[tuple[str, int, int]] = []
    idx = 0
    while idx < total_lines:
        end_idx = min(total_lines, idx + window_lines)
        slice_lines = lines[idx:end_idx]
        slice_code = "\n".join(slice_lines)
        slice_start = start_line + idx
        slice_end = start_line + end_idx - 1
        slices.append((slice_code, slice_start, slice_end))
        if end_idx >= total_lines:
            break
        idx += step

    return slices


def chunk_block(block: CodeBlock) -> list[Chunk]:
    """Convert a single CodeBlock into one or more Chunks."""
    base_id = build_base_id(block.file, block.name, block.class_chain)
    full_hash = compute_content_hash(block.code)

    if len(block.code) <= MAX_BLOCK_CHARS:
        doc = render_document(
            file_path=block.file,
            name=block.name,
            code=block.code,
            class_chain=block.class_chain,
            docstring=block.docstring,
        )
        return [
            Chunk(
                id=base_id,
                document=doc,
                file=block.file,
                chunk_type=block.block_type,
                class_chain=block.class_chain,
                name=block.name,
                language=block.language,
                start_line=block.start_line,
                end_line=block.end_line,
                content_hash=full_hash,
            )
        ]

    # Oversized block splitting
    slices = _split_oversized_code(block.code, block.start_line)
    chunks: list[Chunk] = []
    for part_idx, (slice_code, slice_start, slice_end) in enumerate(slices, start=1):
        part_id = f"{base_id}@part{part_idx}"
        part_doc = render_document(
            file_path=block.file,
            name=block.name,
            code=slice_code,
            class_chain=block.class_chain,
            docstring=block.docstring,
        )
        chunks.append(
            Chunk(
                id=part_id,
                document=part_doc,
                file=block.file,
                chunk_type=block.block_type,
                class_chain=block.class_chain,
                name=block.name,
                language=block.language,
                start_line=slice_start,
                end_line=slice_end,
                content_hash=compute_content_hash(slice_code),
            )
        )
    return chunks


def chunk_blocks(blocks: Sequence[CodeBlock]) -> list[Chunk]:
    """Convert a sequence of CodeBlocks into unique Chunks with collision handling."""
    seen_ids: dict[str, int] = {}
    all_chunks: list[Chunk] = []

    for block in blocks:
        for chunk in chunk_block(block):
            raw_id = chunk.id
            if raw_id not in seen_ids:
                seen_ids[raw_id] = 1
                all_chunks.append(chunk)
            else:
                seen_ids[raw_id] += 1
                dedup_id = f"{raw_id}#{seen_ids[raw_id]}"
                all_chunks.append(
                    Chunk(
                        id=dedup_id,
                        document=chunk.document,
                        file=chunk.file,
                        chunk_type=chunk.chunk_type,
                        class_chain=chunk.class_chain,
                        name=chunk.name,
                        language=chunk.language,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                        content_hash=chunk.content_hash,
                    )
                )

    return all_chunks
