"""Watch mode: asynchronous filesystem change watcher with debouncing.

Implements v0.2 automatic incremental re-indexing on file change events.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from watchfiles import Change, awatch

from context_tree.config import CHROMA_DIR_NAME, IGNORED_DIRS
from context_tree.indexer import Indexer, IndexStats, _is_gitignored, _load_gitignore_patterns
from context_tree.languages import get_language_config

logger = logging.getLogger("context_tree.watcher")


def _is_indexable_change(
    change: Change,
    path_str: str,
    root: Path,
    gitignore_patterns: list[str] | None = None,
) -> bool:
    """Check if the changed file path is an indexable source file and not ignored."""
    try:
        root_resolved = root.resolve()
        path = Path(path_str).resolve()
        rel_path = path.relative_to(root_resolved)
        rel_parts = rel_path.parts
        rel_posix = rel_path.as_posix()
    except (ValueError, OSError):
        return False

    # Check if any parent component is in IGNORED_DIRS or CHROMA_DIR_NAME
    for part in rel_parts:
        if part in IGNORED_DIRS or part == CHROMA_DIR_NAME:
            return False

    # Check extension
    if get_language_config(path) is None:
        return False

    # Check .gitignore patterns
    patterns = (
        gitignore_patterns
        if gitignore_patterns is not None
        else _load_gitignore_patterns(root_resolved / ".gitignore")
    )
    return not (bool(patterns) and _is_gitignored(rel_posix, patterns))


async def watch_workspace(
    root: Path | str,
    debounce_ms: int = 500,
    indexer: Indexer | None = None,
    on_indexed: Callable[[IndexStats], None] | None = None,
    stop_event: asyncio.Event | None = None,
    lock: asyncio.Lock | None = None,
) -> None:
    """Asynchronously monitor *root* and re-index when supported files change."""
    root_path = Path(root).resolve()
    idx = indexer or Indexer(root_path)

    # Initial index pass
    if lock is not None:
        async with lock:
            initial_stats = idx.index()
    else:
        initial_stats = idx.index()

    if on_indexed:
        on_indexed(initial_stats)

    gitignore_file = root_path / ".gitignore"

    async for changes in awatch(root_path, debounce=debounce_ms, stop_event=stop_event):
        patterns = _load_gitignore_patterns(gitignore_file)
        relevant = [
            (change, p)
            for change, p in changes
            if _is_indexable_change(change, p, root_path, gitignore_patterns=patterns)
        ]
        if not relevant:
            continue

        logger.info("Detected %d relevant file change(s), re-indexing...", len(relevant))
        if lock is not None:
            async with lock:
                stats = idx.index()
        else:
            stats = idx.index()

        if on_indexed:
            on_indexed(stats)

        if stop_event is not None and stop_event.is_set():
            break
