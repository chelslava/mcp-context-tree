"""Language registry: file extensions mapped to tree-sitter grammars and extraction rules."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import PurePath
from typing import Literal

from tree_sitter import Language, Parser

DocstringStyle = Literal["python_docstring", "jsdoc_comment"]


def _load_python() -> Language:
    import tree_sitter_python

    return Language(tree_sitter_python.language())


def _load_typescript() -> Language:
    import tree_sitter_typescript

    return Language(tree_sitter_typescript.language_typescript())


def _load_tsx() -> Language:
    import tree_sitter_typescript

    return Language(tree_sitter_typescript.language_tsx())


def _load_javascript() -> Language:
    import tree_sitter_javascript

    return Language(tree_sitter_javascript.language())


@dataclass(frozen=True)
class LanguageConfig:
    """Declarative description of one supported language for AST extraction.

    Node-type tuples follow the concrete grammar node names; they are consumed by
    ``extractor`` to decide what counts as a logical block and how docstrings are
    attached (see ARCHITECTURE.md §4.3-§4.4).
    """

    name: str
    extensions: tuple[str, ...]
    language_loader: Callable[[], Language]
    function_node_types: tuple[str, ...]
    method_node_types: tuple[str, ...]
    class_node_types: tuple[str, ...]
    decorated_wrapper_types: tuple[str, ...]
    docstring_style: DocstringStyle


PYTHON = LanguageConfig(
    name="python",
    extensions=(".py",),
    language_loader=_load_python,
    function_node_types=("function_definition",),
    method_node_types=(),
    class_node_types=("class_definition",),
    decorated_wrapper_types=("decorated_definition",),
    docstring_style="python_docstring",
)

TYPESCRIPT = LanguageConfig(
    name="typescript",
    extensions=(".ts", ".mts", ".cts"),
    language_loader=_load_typescript,
    function_node_types=("function_declaration", "generator_function_declaration"),
    method_node_types=("method_definition",),
    class_node_types=("class_declaration", "abstract_class_declaration"),
    decorated_wrapper_types=(),
    docstring_style="jsdoc_comment",
)

TSX = LanguageConfig(
    name="tsx",
    extensions=(".tsx",),
    language_loader=_load_tsx,
    function_node_types=("function_declaration", "generator_function_declaration"),
    method_node_types=("method_definition",),
    class_node_types=("class_declaration", "abstract_class_declaration"),
    decorated_wrapper_types=(),
    docstring_style="jsdoc_comment",
)

JAVASCRIPT = LanguageConfig(
    name="javascript",
    extensions=(".js", ".jsx", ".mjs", ".cjs"),
    language_loader=_load_javascript,
    function_node_types=("function_declaration", "generator_function_declaration"),
    method_node_types=("method_definition",),
    class_node_types=("class_declaration",),
    decorated_wrapper_types=(),
    docstring_style="jsdoc_comment",
)

EXTENSION_TO_CONFIG: dict[str, LanguageConfig] = {
    ext.lower(): config
    for config in (PYTHON, TYPESCRIPT, TSX, JAVASCRIPT)
    for ext in config.extensions
}


def get_language_config(path: str | PurePath) -> LanguageConfig | None:
    """Return the registered language config for *path*'s extension, or ``None``."""
    suffix = PurePath(path).suffix.lower()
    return EXTENSION_TO_CONFIG.get(suffix)


def iter_language_configs() -> Iterator[LanguageConfig]:
    """Iterate over every supported language exactly once."""
    yield from (PYTHON, TYPESCRIPT, TSX, JAVASCRIPT)


@cache
def get_parser(config: LanguageConfig) -> Parser:
    """Return a cached tree-sitter parser instance for *config* (one per language)."""
    return Parser(config.language_loader())
