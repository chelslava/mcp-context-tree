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
    callee_norm = callee_text.strip().replace("::", ".").replace("->", ".")
    target_norm = target.strip().replace("::", ".").replace("->", ".")
    if "." in target_norm:
        return callee_norm == target_norm or callee_norm.endswith(f".{target_norm}")
    else:
        return callee_norm == target_norm or callee_norm.endswith(f".{target_norm}")


def _extract_callee_text(node: Node, source: bytes) -> str | None:
    """Extract callee expression text from supported AST call and instantiation nodes."""
    ntype = node.type

    # Python call node, JS/TS/Go/Rust/C/CPP/Kotlin/Swift call_expression, C# invocation_expression
    if ntype in ("call", "call_expression", "invocation_expression"):
        func_node = node.child_by_field_name("function")
        if func_node is None and node.named_children:
            first = node.named_children[0]
            if first.type in (
                "navigation_expression",
                "simple_identifier",
                "identifier",
                "field_expression",
                "scoped_identifier",
                "user_type",
            ):
                func_node = first
        if func_node is not None:
            return source[func_node.start_byte : func_node.end_byte].decode(
                "utf-8", errors="replace"
            )
    elif ntype == "method_invocation":
        # Java method invocation: [object.]name(args)
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            name_text = source[name_node.start_byte : name_node.end_byte].decode(
                "utf-8", errors="replace"
            )
            object_node = node.child_by_field_name("object")
            if object_node is not None:
                object_text = source[object_node.start_byte : object_node.end_byte].decode(
                    "utf-8", errors="replace"
                )
                return f"{object_text}.{name_text}"
            else:
                return name_text
    elif ntype in ("new_expression", "object_creation_expression"):
        # JS/TS/C++ new_expression (constructor / type), Java/C# object_creation_expression (type)
        target_node = node.child_by_field_name("constructor") or node.child_by_field_name("type")
        if target_node is None and node.named_children:
            target_node = node.named_children[0]
        if target_node is not None:
            return source[target_node.start_byte : target_node.end_byte].decode(
                "utf-8", errors="replace"
            )

    return None


def _find_calls_in_node(
    node: Node,
    source: bytes,
    target: str,
    rel_path: str,
    hits: list[UsageHit],
    lines: list[str],
    max_hits: int,
) -> None:
    if len(hits) >= max_hits:
        return

    callee_text = _extract_callee_text(node, source)
    if callee_text is not None and _matches_target(callee_text, target):
        line_idx = node.start_point[0]
        line_no = line_idx + 1
        preview = lines[line_idx].strip() if line_idx < len(lines) else callee_text
        hits.append(UsageHit(file=rel_path, line=line_no, preview=preview))

    for child in node.named_children:
        _find_calls_in_node(child, source, target, rel_path, hits, lines, max_hits)


def find_ast_usages(root: Path | str, symbol_name: str, max_hits: int = 50) -> list[UsageHit]:
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


def _batch_count_in_node(
    node: Node,
    source: bytes,
    norm_to_symbols: dict[str, list[str]],
    counts: dict[str, int],
    max_hits_per_symbol: int,
) -> None:
    callee_text = _extract_callee_text(node, source)
    if callee_text is not None:
        callee_norm = callee_text.strip().replace("::", ".").replace("->", ".")
        parts = callee_norm.split(".")
        for i in range(len(parts)):
            suffix = ".".join(parts[i:])
            if suffix in norm_to_symbols:
                for sym in norm_to_symbols[suffix]:
                    if counts[sym] < max_hits_per_symbol:
                        counts[sym] += 1

    for child in node.named_children:
        _batch_count_in_node(child, source, norm_to_symbols, counts, max_hits_per_symbol)


def batch_count_ast_usages(
    root: Path | str,
    symbol_names: set[str] | list[str] | tuple[str, ...],
    max_hits_per_symbol: int = 50,
) -> dict[str, int]:
    """Count AST call sites for multiple symbols in a single pass over workspace files.

    Performs an $O(N)$ workspace scan across all candidate symbols simultaneously,
    matching bare and qualified / dotted names without repeated disk I/O or AST parsing.
    """
    root_path = Path(root).resolve()
    counts: dict[str, int] = {}
    norm_to_symbols: dict[str, list[str]] = {}

    for sym in symbol_names:
        s = sym.strip()
        if not s:
            continue
        counts[sym] = 0
        norm = s.replace("::", ".").replace("->", ".")
        norm_to_symbols.setdefault(norm, []).append(sym)

    if not norm_to_symbols:
        return counts

    candidates = discover_files(root_path)

    for _rel_path, abs_path in sorted(candidates.items()):
        if all(counts[sym] >= max_hits_per_symbol for sym in counts):
            break

        parsed = parse_file(abs_path, root=root_path)
        if parsed is None:
            continue

        _batch_count_in_node(
            parsed.tree.root_node,
            parsed.source,
            norm_to_symbols,
            counts,
            max_hits_per_symbol,
        )

    return counts
