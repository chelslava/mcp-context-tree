"""AST-based symbol call sites lookup.

Implements ARCHITECTURE.md §10:
- Parses workspace files on demand with tree-sitter
- Detects real call sites / instantiations (filters strings/comments)
- Supports bare names ('retry') and dotted targets ('PaymentGateway.retry')
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Node

from context_tree.indexer import discover_files
from context_tree.parser import parse_file


@dataclass(frozen=True)
class UsageHit:
    """A real AST call site match."""

    file: str
    line: int
    preview: str

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "preview": self.preview,
        }


def _matches_target(callee_text: str, target: str) -> bool:
    """Check if callee expression matches bare or dotted target."""
    callee = callee_text.strip()
    if "." in target:
        return callee.endswith(f".{target.split('.')[-1]}") or callee == target
    else:
        return callee == target or callee.endswith(f".{target}")


def _find_calls_in_node(
    node: Node, source: bytes, target: str, rel_path: str, hits: list[UsageHit], lines: list[str], max_hits: int
) -> None:
    if len(hits) >= max_hits:
        return

    ntype = node.type

    # Python call node or JS/TS call_expression
    if ntype in ("call", "call_expression"):
        func_node = node.child_by_field_name("function")
        if func_node is not None:
            callee_text = source[func_node.start_byte : func_node.end_byte].decode("utf-8", errors="replace")
            if _matches_target(callee_text, target):
                line_idx = node.start_point[0]
                line_no = line_idx + 1
                preview = lines[line_idx].strip() if line_idx < len(lines) else callee_text
                hits.append(UsageHit(file=rel_path, line=line_no, preview=preview))

    for child in node.named_children:
        _find_calls_in_node(child, source, target, rel_path, hits, lines, max_hits)


def find_ast_usages(
    root: Path | str, symbol_name: str, max_hits: int = 50
) -> list[UsageHit]:
    """Find real call sites of *symbol_name* across all supported files in workspace."""
    root_path = Path(root).resolve()
    candidates = discover_files(root_path)

    hits: list[UsageHit] = []

    for rel_path, abs_path in sorted(candidates.items()):
        if len(hits) >= max_hits:
            break

        parsed = parse_file(abs_path, root=root_path)
        if parsed is None:
            continue

        lines = parsed.source.decode("utf-8", errors="replace").splitlines()
        _find_calls_in_node(
            parsed.tree.root_node,
            parsed.source,
            symbol_name,
            rel_path,
            hits,
            lines,
            max_hits,
        )

    return hits
