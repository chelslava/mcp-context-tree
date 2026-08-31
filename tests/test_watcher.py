"""Tests for file system watcher and change filtering."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from watchfiles import Change

from context_tree.indexer import IndexStats
from context_tree.watcher import _is_indexable_change, watch_workspace


def test_is_indexable_change(tmp_path: Path) -> None:
    valid_file = str(tmp_path / "src" / "app.py")
    ignored_git = str(tmp_path / ".git" / "config.py")
    ignored_chroma = str(tmp_path / ".chroma" / "state.py")
    unsupported = str(tmp_path / "readme.txt")

    assert _is_indexable_change(Change.added, valid_file, tmp_path) is True
    assert _is_indexable_change(Change.modified, ignored_git, tmp_path) is False
    assert _is_indexable_change(Change.modified, ignored_chroma, tmp_path) is False
    assert _is_indexable_change(Change.added, unsupported, tmp_path) is False


def test_is_indexable_change_respects_gitignore(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored.py\ncustom_build/\n", encoding="utf-8")

    ignored_file = str(tmp_path / "ignored.py")
    ignored_dir_file = str(tmp_path / "custom_build" / "app.py")
    valid_file = str(tmp_path / "main.py")

    assert _is_indexable_change(Change.added, ignored_file, tmp_path) is False
    assert _is_indexable_change(Change.added, ignored_dir_file, tmp_path) is False
    assert _is_indexable_change(Change.added, valid_file, tmp_path) is True


@pytest.mark.asyncio
async def test_watch_workspace_runs_and_stops(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def hello(): pass", encoding="utf-8")

    stats_log: list[IndexStats] = []
    stop_event = asyncio.Event()

    # Trigger stop immediately after initial index pass
    def on_indexed(stats: IndexStats) -> None:
        stats_log.append(stats)
        stop_event.set()

    await watch_workspace(
        tmp_path,
        debounce_ms=50,
        on_indexed=on_indexed,
        stop_event=stop_event,
    )

    assert len(stats_log) >= 1
    assert stats_log[0].added == 1
    assert stats_log[0].indexed_chunks == 1


@pytest.mark.asyncio
async def test_watch_workspace_with_lock(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def hello(): pass", encoding="utf-8")

    stats_log: list[IndexStats] = []
    stop_event = asyncio.Event()
    lock = asyncio.Lock()

    def on_indexed(stats: IndexStats) -> None:
        stats_log.append(stats)
        stop_event.set()

    await watch_workspace(
        tmp_path,
        debounce_ms=50,
        on_indexed=on_indexed,
        stop_event=stop_event,
        lock=lock,
    )

    assert len(stats_log) >= 1
    assert stats_log[0].added == 1
    assert stats_log[0].indexed_chunks == 1
