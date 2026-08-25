"""AST extraction: walk parsed trees and emit logical code blocks across languages."""

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
_PY_STRING_LITERAL_RE = re.compile(r"^([bBrRuUfF]{0,3})(\"\"\"|'''|\"|')(.*?)\2$", re.DOTALL)


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


def _attached_comment(
    ctx: _WalkContext, anchor: Node, pending: Node | None
) -> tuple[str, Node | None]:
    """Return attached preceding comment text and first comment node (if adjacent)."""
    start_node = pending or anchor.prev_named_sibling
    if start_node is None:
        return "", None

    curr = start_node
    anchor_row = anchor.start_point[0]
    comment_nodes: list[Node] = []

    while curr is not None and (
        "comment" in curr.type or curr.type in ("line_comment", "block_comment")
    ):
        if not comment_nodes:
            if curr.end_point[0] < anchor_row - 2:
                break
        else:
            if curr.end_point[0] < comment_nodes[-1].start_point[0] - 1:
                break
        comment_nodes.append(curr)
        curr = curr.prev_named_sibling

    if not comment_nodes:
        return "", None

    comment_nodes.reverse()
    first_doc_node = comment_nodes[0]
    full_text = "\n".join(_node_text(ctx.source, n).strip() for n in comment_nodes)
    return full_text, first_doc_node


def _extract_go_receiver_type(ctx: _WalkContext, method_node: Node) -> str:
    receiver = method_node.child_by_field_name("receiver")
    if receiver is not None:
        raw = _node_text(ctx.source, receiver).strip("() ")
        # raw like "(s *Server)" or "(s Server)"
        parts = raw.split()
        if len(parts) >= 2:
            return parts[-1].lstrip("*")
        elif parts:
            return parts[0].lstrip("*")
    return ""


def _emit_class(
    class_node: Node,
    span_start: Node,
    class_chain: str,
    ctx: _WalkContext,
    pending_comment: Node | None,
) -> None:
    cfg = ctx.config
    ntype = class_node.type

    # Go type_declaration -> type_spec
    if cfg.name == "go" and ntype == "type_declaration":
        for spec in class_node.named_children:
            if spec.type == "type_spec":
                name = _field_text(ctx.source, spec, "name")
                if not name:
                    continue
                doc, doc_node = _attached_comment(ctx, class_node, pending_comment)
                start_line = _start_line(doc_node) if doc_node else _start_line(class_node)
                end_line = _end_line(class_node)
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
                        docstring=doc,
                    )
                )
        return

    # Rust impl_item
    if cfg.name == "rust" and ntype == "impl_item":
        type_node = class_node.child_by_field_name("type")
        impl_name = _node_text(ctx.source, type_node).strip() if type_node else ""
        body = class_node.child_by_field_name("body")
        nested_chain = (
            f"{class_chain}::{impl_name}"
            if class_chain and impl_name
            else (impl_name or class_chain)
        )
        if body is not None:
            for child in body.named_children:
                _walk(child, nested_chain, ctx)
        return

    name = _field_text(ctx.source, class_node, "name")
    if not name:
        return

    body = class_node.child_by_field_name("body")
    docstring = ""
    start_line = _start_line(span_start)

    if cfg.docstring_style == "python_docstring":
        string_node = _python_string_node(class_node)
        end_line = _start_line(class_node)
        if string_node is not None:
            docstring = _clean_python_string(_node_text(ctx.source, string_node))
            end_line = _end_line(string_node)
    else:
        doc, doc_node = _attached_comment(ctx, class_node, pending_comment)
        if doc_node is not None:
            docstring = doc
            start_line = _start_line(doc_node)
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
    comment_node: Node | None,
) -> None:
    cfg = ctx.config
    name = _field_text(ctx.source, definition, "name")
    if not name:
        return

    # Go method receiver extraction
    if cfg.name == "go" and definition.type == "method_declaration":
        recv_type = _extract_go_receiver_type(ctx, definition)
        if recv_type:
            class_chain = recv_type

    docstring = ""
    start_line = _start_line(bounds)

    if cfg.docstring_style == "python_docstring":
        string_node = _python_string_node(definition)
        if string_node is not None:
            docstring = _clean_python_string(_node_text(ctx.source, string_node))
    else:
        doc, doc_node = _attached_comment(ctx, definition, comment_node)
        if doc_node is not None:
            docstring = doc
            start_line = _start_line(doc_node)

    is_method = bool(
        definition.type in cfg.method_node_types
        or (class_chain and (cfg.docstring_style == "python_docstring" or cfg.name == "rust"))
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


def _walk(
    node: Node,
    class_chain: str,
    ctx: _WalkContext,
    pending_comment: Node | None = None,
    *,
    bounds: Node | None = None,
) -> None:
    ntype = node.type
    cfg = ctx.config

    if ntype == _EXPORT_STATEMENT:
        _, doc_node = _attached_comment(ctx, node, pending_comment)
        declaration = node.child_by_field_name("declaration")
        if declaration is not None:
            _walk(declaration, class_chain, ctx, doc_node)
        else:
            for child in node.named_children:
                _walk(child, class_chain, ctx)
        return

    if ntype in cfg.decorated_wrapper_types:
        inner = node.child_by_field_name("definition")
        if inner is not None:
            _walk(inner, class_chain, ctx, bounds=node)
        return

    if ntype in cfg.class_node_types:
        _emit_class(node, bounds or node, class_chain, ctx, pending_comment)
        return

    if ntype in cfg.function_node_types or ntype in cfg.method_node_types:
        _emit_callable(
            node,
            bounds=bounds or node,
            class_chain=class_chain,
            ctx=ctx,
            comment_node=pending_comment,
        )
        return

    for child in node.named_children:
        _walk(child, class_chain, ctx)
