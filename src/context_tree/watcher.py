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
from context_tree.indexer import Indexer, IndexStats
from context_tree.languages import get_language_config

logger = logging.getLogger("context_tree.watcher")


def _is_indexable_change(change: Change, path_str: str, root: Path) -> bool:
    """Check if the changed file path is an indexable source file and not ignored."""
    try:
        path = Path(path_str).resolve()
        rel_parts = path.relative_to(root.resolve()).parts
    except (ValueError, OSError):
        return False

    # Check if any parent component is in IGNORED_DIRS or CHROMA_DIR_NAME
    for part in rel_parts:
        if part in IGNORED_DIRS or part == CHROMA_DIR_NAME:
            return False

    # Check extension
    return get_language_config(path) is not None


async def watch_workspace(
    root: Path | str,
    debounce_ms: int = 500,
    indexer: Indexer | None = None,
    on_indexed: Callable[[IndexStats], None] | None = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Asynchronously monitor *root* and re-index when supported files change."""
    root_path = Path(root).resolve()
    idx = indexer or Indexer(root_path)

    # Initial index pass
    initial_stats = idx.index()
    if on_indexed:
        on_indexed(initial_stats)

    async for changes in awatch(root_path, debounce=debounce_ms, stop_event=stop_event):
        relevant = [
            (change, p) for change, p in changes if _is_indexable_change(change, p, root_path)
        ]
        if not relevant:
            continue

        logger.info("Detected %d relevant file change(s), re-indexing...", len(relevant))
        stats = idx.index()
        if on_indexed:
            on_indexed(stats)

        if stop_event is not None and stop_event.is_set():
            break
