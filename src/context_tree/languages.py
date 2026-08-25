"""Language registry: file extensions mapped to tree-sitter grammars and extraction rules."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import PurePath
from typing import Literal

from tree_sitter import Language, Parser

DocstringStyle = Literal["python_docstring", "jsdoc_comment", "prefix_comment"]


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


def _load_go() -> Language:
    import tree_sitter_go

    return Language(tree_sitter_go.language())


def _load_rust() -> Language:
    import tree_sitter_rust

    return Language(tree_sitter_rust.language())


def _load_c_sharp() -> Language:
    import tree_sitter_c_sharp

    return Language(tree_sitter_c_sharp.language())


def _load_java() -> Language:
    import tree_sitter_java

    return Language(tree_sitter_java.language())


@dataclass(frozen=True)
class LanguageConfig:
    """Declarative description of one supported language for AST extraction."""

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

GO = LanguageConfig(
    name="go",
    extensions=(".go",),
    language_loader=_load_go,
    function_node_types=("function_declaration",),
    method_node_types=("method_declaration",),
    class_node_types=("type_declaration",),
    decorated_wrapper_types=(),
    docstring_style="prefix_comment",
)

RUST = LanguageConfig(
    name="rust",
    extensions=(".rs",),
    language_loader=_load_rust,
    function_node_types=("function_item",),
    method_node_types=(),
    class_node_types=("struct_item", "trait_item", "impl_item"),
    decorated_wrapper_types=(),
    docstring_style="prefix_comment",
)

CSHARP = LanguageConfig(
    name="c_sharp",
    extensions=(".cs",),
    language_loader=_load_c_sharp,
    function_node_types=("local_function_statement",),
    method_node_types=("method_declaration", "constructor_declaration"),
    class_node_types=("class_declaration", "interface_declaration", "struct_declaration"),
    decorated_wrapper_types=(),
    docstring_style="prefix_comment",
)

JAVA = LanguageConfig(
    name="java",
    extensions=(".java",),
    language_loader=_load_java,
    function_node_types=(),
    method_node_types=("method_declaration", "constructor_declaration"),
    class_node_types=("class_declaration", "interface_declaration", "record_declaration"),
    decorated_wrapper_types=(),
    docstring_style="jsdoc_comment",
)

ALL_LANGUAGES = (PYTHON, TYPESCRIPT, TSX, JAVASCRIPT, GO, RUST, CSHARP, JAVA)

EXTENSION_TO_CONFIG: dict[str, LanguageConfig] = {
    ext.lower(): config for config in ALL_LANGUAGES for ext in config.extensions
}


def get_language_config(path: str | PurePath) -> LanguageConfig | None:
    """Return the registered language config for *path*'s extension, or ``None``."""
    suffix = PurePath(path).suffix.lower()
    return EXTENSION_TO_CONFIG.get(suffix)


def iter_language_configs() -> Iterator[LanguageConfig]:
    """Iterate over every supported language exactly once."""
    yield from ALL_LANGUAGES


@cache
def get_parser(config: LanguageConfig) -> Parser:
    """Return a cached tree-sitter parser instance for *config* (one per language)."""
    return Parser(config.language_loader())
