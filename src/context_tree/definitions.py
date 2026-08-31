"""AST-based symbol definition lookup across workspace files.

Locates exact declarations/definitions for functions, methods, classes, structs,
traits, and interfaces across all supported languages.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from context_tree.config import CHROMA_DIR_NAME
from context_tree.extractor import CodeBlock, extract_blocks
from context_tree.indexer import discover_files
from context_tree.search import read_snippet_from_disk
from context_tree.store import VectorStore


@dataclass(frozen=True)
class DefinitionHit:
    """Exact definition/declaration site of a symbol."""

    file: str
    language: str
    type: str
    name: str
    class_chain: str
    start_line: int
    end_line: int
    code: str
    docstring: str = ""

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "language": self.language,
            "type": self.type,
            "name": self.name,
            "class": self.class_chain,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "code": self.code,
            "docstring": self.docstring,
        }


def _matches_target(block: CodeBlock, target: str) -> bool:
    """Check if a code block matches bare or dotted symbol target."""
    target_norm = target.strip().replace("::", ".")
    block_qname_norm = block.qualified_name.replace("::", ".")

    if "." in target_norm:
        if block_qname_norm == target_norm or block_qname_norm.endswith(f".{target_norm}"):
            return True
        # Also check class-relative match
        parts = target_norm.split(".")
        if block.name == parts[-1] and block.class_chain:
            expected_class = ".".join(parts[:-1])
            block_class_norm = block.class_chain.replace("::", ".")
            if block_class_norm == expected_class or block_class_norm.endswith(
                f".{expected_class}"
            ):
                return True
        return False
    else:
        return block.name == target_norm


def _matches_meta_target(name: str, class_chain: str, target: str) -> bool:
    """Check if symbol metadata matches bare or dotted target."""
    target_norm = target.strip().replace("::", ".")
    qualified_name = f"{class_chain}.{name}" if class_chain else name
    block_qname_norm = qualified_name.replace("::", ".")

    if "." in target_norm:
        if block_qname_norm == target_norm or block_qname_norm.endswith(f".{target_norm}"):
            return True
        # Also check class-relative match
        parts = target_norm.split(".")
        if name == parts[-1] and class_chain:
            expected_class = ".".join(parts[:-1])
            block_class_norm = class_chain.replace("::", ".")
            if block_class_norm == expected_class or block_class_norm.endswith(
                f".{expected_class}"
            ):
                return True
        return False
    else:
        return name == target_norm


def find_symbol_definitions(
    root: Path | str, symbol_name: str, max_hits: int = 20
) -> list[DefinitionHit]:
    """Find exact definition/declaration sites for *symbol_name* in the workspace."""
    root_path = Path(root).resolve()
    target_norm = symbol_name.strip().replace("::", ".")
    if not target_norm:
        return []

    name_part = target_norm.split(".")[-1] if "." in target_norm else target_norm

    # 1. Fast-path: query persistent ChromaDB vector store metadata if workspace is indexed
    chroma_dir = root_path / CHROMA_DIR_NAME
    if chroma_dir.is_dir():
        try:
            vstore = VectorStore(chroma_dir)
            if vstore.count() > 0:
                data = vstore.collection.get(
                    where={"name": name_part},
                    include=["metadatas", "documents"],  # type: ignore[list-item]
                )
                metas = data.get("metadatas", []) or []
                docs = data.get("documents", []) or []

                hits: list[DefinitionHit] = []
                seen: set[tuple[str, int, str]] = set()

                for i, meta in enumerate(metas):
                    if not isinstance(meta, dict):
                        continue
                    name = str(meta.get("name", ""))
                    class_chain = str(meta.get("class", ""))
                    if not _matches_meta_target(name, class_chain, symbol_name):
                        continue

                    rel_file = str(meta.get("file", ""))
                    start_line = int(meta.get("start_line", 1))
                    end_line = int(meta.get("end_line", 1))
                    language = str(meta.get("language", ""))
                    b_type = str(meta.get("type", "function"))

                    key = (rel_file, start_line, name)
                    if key in seen:
                        continue
                    seen.add(key)

                    fallback_doc = docs[i] if i < len(docs) and docs[i] is not None else ""
                    code = read_snippet_from_disk(
                        root_path, rel_file, start_line, end_line, str(fallback_doc)
                    )

                    hits.append(
                        DefinitionHit(
                            file=rel_file,
                            language=language,
                            type=b_type,
                            name=name,
                            class_chain=class_chain,
                            start_line=start_line,
                            end_line=end_line,
                            code=code,
                        )
                    )
                    if len(hits) >= max_hits:
                        break

                return hits
        except Exception:
            # Fall back to live disk extraction if store access fails
            pass

    # 2. Slow-path / Fallback: discover and extract AST blocks from disk files
    candidates = discover_files(root_path)
    hits = []
    for _rel_path, abs_path in sorted(candidates.items()):
        if len(hits) >= max_hits:
            break

        blocks = extract_blocks(abs_path, root=root_path)
        for block in blocks:
            if _matches_target(block, symbol_name):
                hits.append(
                    DefinitionHit(
                        file=block.file,
                        language=block.language,
                        type=block.block_type,
                        name=block.name,
                        class_chain=block.class_chain,
                        start_line=block.start_line,
                        end_line=block.end_line,
                        code=block.code,
                        docstring=block.docstring,
                    )
                )
                if len(hits) >= max_hits:
                    break

    return hits
