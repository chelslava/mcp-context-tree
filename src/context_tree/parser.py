"""tree-sitter parsing helpers: detect language, read source, parse into an AST."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tree_sitter import Tree

from context_tree.config import BINARY_SNIFF_BYTES, MAX_FILE_SIZE_BYTES
from context_tree.languages import LanguageConfig, get_language_config, get_parser


@dataclass(frozen=True)
class ParsedFile:
    """A successfully parsed source file together with its AST and metadata."""

    path: Path
    relative_path: str
    config: LanguageConfig
    source: bytes
    tree: Tree


def read_source(path: Path, *, max_bytes: int = MAX_FILE_SIZE_BYTES) -> bytes | None:
    """Read raw bytes of *path*.

    Returns ``None`` when the file exceeds *max_bytes* or looks binary (NUL byte
    within the first ``BINARY_SNIFF_BYTES``).
    """
    try:
        if path.stat().st_size > max_bytes:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:BINARY_SNIFF_BYTES]:
        return None
    return data


def parse_file(path: str | Path, *, root: Path | None = None) -> ParsedFile | None:
    """Detect the language of *path*, read it and parse it.

    Returns ``None`` when the extension is unsupported or the content is skipped
    (oversized / binary / unreadable).
    """
    file_path = Path(path)
    config = get_language_config(file_path)
    if config is None:
        return None
    source = read_source(file_path)
    if source is None:
        return None
    tree = get_parser(config).parse(source)
    return ParsedFile(
        path=file_path,
        relative_path=_relative_posix_path(file_path, root),
        config=config,
        source=source,
        tree=tree,
    )


def _relative_posix_path(file_path: Path, root: Path | None) -> str:
    if root is not None:
        try:
            return file_path.relative_to(root).as_posix()
        except ValueError:
            try:
                return file_path.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                pass
    return file_path.as_posix()
