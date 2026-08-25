"""AST extraction: walk parsed trees and emit logical code blocks.

Implements ARCHITECTURE.md §4.4 granularity — functions, methods and class
signatures (with docstrings) — plus §7.1 semantics for class chains.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from tree_sitter import Node

from context_tree.languages import LanguageConfig
from context_tree.parser import ParsedFile, parse_file

BlockType = Literal["function", "method", "class_signature"]

_EXPORT_STATEMENT = "export_statement"

_PY_STRING_LITERAL_RE = re.compile(r"^([bBrRuUfF]{0,3})(\"\"\"|'''|\"|\')(.*?)\2$", re.DOTALL)


@dataclass(frozen=True)
class CodeBlock:
    """One logical unit extracted from a source file."""

    file: str
    language: str
    block_type: BlockType
    name: str
    class_chain: str
    start_line: int
    end_line: int
    code: str
    docstring: str = ""

    @property
    def qualified_name(self) -> str:
        if self.class_chain:
            return f"{self.class_chain}::{self.name}"
        return self.name


@dataclass
class _WalkContext:
    """Mutable state threaded through a single-file extraction walk."""

    config: LanguageConfig
    source: bytes
    lines: tuple[str, ...]
    file: str
    blocks: list[CodeBlock] = field(default_factory=list)

    def slice_lines(self, start_line: int, end_line: int) -> str:
        return "\n".join(self.lines[start_line - 1 : end_line])


def extract_blocks(path: str | Path, *, root: Path | None = None) -> list[CodeBlock]:
    """Parse *path* and extract logical blocks; empty list when nothing to index."""
    parsed = parse_file(path, root=root)
    if parsed is None:
        return []
    return _extract_from_parsed(parsed)


def _extract_from_parsed(parsed: ParsedFile) -> list[CodeBlock]:
    lines = tuple(parsed.source.decode("utf-8", errors="replace").splitlines())
    ctx = _WalkContext(
        config=parsed.config,
        source=parsed.source,
        lines=lines,
        file=parsed.relative_path,
    )
    _walk(parsed.tree.root_node, "", ctx)
    return ctx.blocks


# --- node helpers ----------------------------------------------------------------


def _node_text(source: bytes, node: Node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _start_line(node: Node) -> int:
    return node.start_point[0] + 1


def _end_line(node: Node) -> int:
    return node.end_point[0] + 1


def _field_text(source: bytes, node: Node, field_name: str) -> str:
    child = node.child_by_field_name(field_name)
    return _node_text(source, child) if child is not None else ""


def _python_string_node(definition_node: Node) -> Node | None:
    """Return the docstring string-node of a python function/class, if present."""
    body = definition_node.child_by_field_name("body")
    if body is None or not body.named_children:
        return None
    first = body.named_children[0]
    if first.type != "expression_statement" or not first.named_children:
        return None
    inner = first.named_children[0]
    return inner if inner.type == "string" else None


def _clean_python_string(raw: str) -> str:
    match = _PY_STRING_LITERAL_RE.match(raw.strip())
    inner = match.group(3) if match else raw
    return inner.strip()


def _attached_jsdoc(ctx: _WalkContext, anchor: Node, pending: Node | None) -> Node | None:
    """Return an attached JSDoc comment node (adjacent or one blank line apart)."""
    candidates = (pending, anchor.prev_named_sibling)
    anchor_row = anchor.start_point[0]
    for candidate in candidates:
        if candidate is None or candidate.type != "comment":
            continue
        text = _node_text(ctx.source, candidate)
        adjacent = candidate.end_point[0] >= anchor_row - 2
        if text.lstrip().startswith("/**") and adjacent:
            return candidate
    return None


# --- emission ----------------------------------------------------------------------


def _emit_class(
    class_node: Node,
    span_start: Node,
    class_chain: str,
    ctx: _WalkContext,
    pending_jsdoc: Node | None,
) -> None:
    cfg = ctx.config
    name = _field_text(ctx.source, class_node, "name")
    if not name:
        return
    body = class_node.child_by_field_name("body")

    docstring = ""
    start_line = _start_line(span_start)
    if cfg.docstring_style == "python_docstring":
        # Signature-only block: decorators/header + docstring; members excluded.
        string_node = _python_string_node(class_node)
        end_line = _start_line(class_node)  # header-only fallback
        if string_node is not None:
            docstring = _clean_python_string(_node_text(ctx.source, string_node))
            end_line = _end_line(string_node)
    else:
        attached = pending_jsdoc or _attached_jsdoc(ctx, class_node, None)
        if attached is not None:
            docstring = _node_text(ctx.source, attached)
            start_line = _start_line(attached)
        # Signature ends at the opening brace line of the class body.
        end_line = _start_line(body) if body is not None else _end_line(class_node)

    ctx.blocks.append(
        CodeBlock(
            file=ctx.file,
            language=cfg.name,
            block_type="class_signature",
            name=name,
            class_chain=class_chain,
            start_line=start_line,
            end_line=end_line,
            code=ctx.slice_lines(start_line, end_line),
            docstring=docstring,
        )
    )

    if body is not None:
        nested_chain = f"{class_chain}::{name}" if class_chain else name
        for child in body.named_children:
            _walk(child, nested_chain, ctx)


def _emit_callable(
    definition: Node,
    *,
    bounds: Node,
    class_chain: str,
    ctx: _WalkContext,
    jsdoc: Node | None,
) -> None:
    cfg = ctx.config
    name = _field_text(ctx.source, definition, "name")
    if not name:
        return

    docstring = ""
    start_line = _start_line(bounds)
    if cfg.docstring_style == "python_docstring":
        string_node = _python_string_node(definition)
        if string_node is not None:
            docstring = _clean_python_string(_node_text(ctx.source, string_node))
    else:
        attached = jsdoc or _attached_jsdoc(ctx, definition, None)
        if attached is not None:
            docstring = _node_text(ctx.source, attached)
            start_line = _start_line(attached)

    is_method = definition.type in cfg.method_node_types or bool(
        class_chain and cfg.docstring_style == "python_docstring"
    )
    block_type: BlockType = "method" if is_method else "function"
    end_line = _end_line(bounds)

    ctx.blocks.append(
        CodeBlock(
            file=ctx.file,
            language=cfg.name,
            block_type=block_type,
            name=name,
            class_chain=class_chain,
            start_line=start_line,
            end_line=end_line,
            code=ctx.slice_lines(start_line, end_line),
            docstring=docstring,
        )
    )
    # Never descend into function/method bodies: no nested-function noise.


# --- walk -------------------------------------------------------------------------


def _walk(
    node: Node,
    class_chain: str,
    ctx: _WalkContext,
    pending_jsdoc: Node | None = None,
    *,
    bounds: Node | None = None,
) -> None:
    """Depth-first walk; *bounds* overrides the emitted span (decorator wrappers)."""
    ntype = node.type
    cfg = ctx.config

    if ntype == _EXPORT_STATEMENT:
        jsdoc = pending_jsdoc or _attached_jsdoc(ctx, node, None)
        declaration = node.child_by_field_name("declaration")
        if declaration is not None:
            _walk(declaration, class_chain, ctx, jsdoc)
        else:
            for child in node.named_children:
                _walk(child, class_chain, ctx)
        return

    if ntype in cfg.decorated_wrapper_types:
        inner = node.child_by_field_name("definition")
        if inner is not None:
            # Wrapper bounds keep decorator lines inside the emitted code span.
            _walk(inner, class_chain, ctx, bounds=node)
        return

    if ntype in cfg.class_node_types:
        _emit_class(node, bounds or node, class_chain, ctx, pending_jsdoc)
        return

    if ntype in cfg.function_node_types:
        _emit_callable(
            node, bounds=bounds or node, class_chain=class_chain, ctx=ctx, jsdoc=pending_jsdoc
        )
        return

    if ntype in cfg.method_node_types:
        if node.child_by_field_name("body") is None:
            # Overload / abstract signatures have no implementation to index.
            return
        _emit_callable(
            node, bounds=bounds or node, class_chain=class_chain, ctx=ctx, jsdoc=pending_jsdoc
        )
        return

    for child in node.named_children:
        _walk(child, class_chain, ctx)
