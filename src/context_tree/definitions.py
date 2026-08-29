"""AST-based symbol definition lookup across workspace files.

Locates exact declarations/definitions for functions, methods, classes, structs,
traits, and interfaces across all supported languages.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from context_tree.extractor import CodeBlock, extract_blocks
from context_tree.indexer import discover_files


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
            if (
                block_class_norm == expected_class
                or block_class_norm.endswith(f".{expected_class}")
            ):
                return True
        return False
    else:
        return block.name == target_norm


def find_symbol_definitions(
    root: Path | str, symbol_name: str, max_hits: int = 20
) -> list[DefinitionHit]:
    """Find exact definition/declaration sites for *symbol_name* in the workspace."""
    root_path = Path(root).resolve()
    candidates = discover_files(root_path)

    hits: list[DefinitionHit] = []

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
