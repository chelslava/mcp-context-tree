"""Tests for file state tracking, hashing, and incremental diff logic."""

from __future__ import annotations

from pathlib import Path

from context_tree.state import (
    FileMeta,
    IndexState,
    compute_file_meta,
    diff_state,
    load_state,
    save_state_atomic,
)


def test_load_state_missing_file(tmp_path: Path) -> None:
    state_file = tmp_path / "index_state.json"
    state = load_state(state_file)
    assert state.version == 1
    assert state.files == {}


def test_save_and_load_state_roundtrip(tmp_path: Path) -> None:
    state_file = tmp_path / "sub" / "index_state.json"
    state = IndexState(
        version=1,
        files={
            "src/a.py": FileMeta(sha256="abc123", size=100, mtime=12345.67),
            "src/b.ts": FileMeta(sha256="def456", size=200, mtime=23456.78),
        },
    )
    save_state_atomic(state, state_file)
    assert state_file.is_file()

    loaded = load_state(state_file)
    assert loaded.version == 1
    assert len(loaded.files) == 2
    assert loaded.files["src/a.py"].sha256 == "abc123"
    assert loaded.files["src/b.ts"].size == 200


def test_diff_state_added_modified_deleted_unchanged(tmp_path: Path) -> None:
    f1 = tmp_path / "f1.py"
    f2 = tmp_path / "f2.py"
    f3 = tmp_path / "f3.py"

    f1.write_text("print(1)", encoding="utf-8")
    f2.write_text("print(2)", encoding="utf-8")
    f3.write_text("print(3)", encoding="utf-8")

    meta1 = compute_file_meta(f1)
    meta2 = compute_file_meta(f2)

    old_state = IndexState(
        files={
            "f1.py": meta1,
            "f2.py": meta2,
            "f_deleted.py": FileMeta(sha256="old", size=50, mtime=100.0),
        }
    )

    # Modify f2
    f2.write_text("print(2_modified)", encoding="utf-8")

    candidates = {
        "f1.py": f1,  # unchanged
        "f2.py": f2,  # modified
        "f3.py": f3,  # added
    }

    diff, new_state = diff_state(candidates, old_state)

    assert diff.added == ["f3.py"]
    assert diff.modified == ["f2.py"]
    assert diff.deleted == ["f_deleted.py"]
    assert diff.unchanged == ["f1.py"]
    assert diff.has_changes is True

    assert "f3.py" in new_state.files
    assert "f2.py" in new_state.files
    assert "f1.py" in new_state.files
    assert "f_deleted.py" not in new_state.files


def test_diff_state_fast_path_when_unchanged(tmp_path: Path) -> None:
    f1 = tmp_path / "f1.py"
    f1.write_text("hello", encoding="utf-8")
    meta1 = compute_file_meta(f1)

    old_state = IndexState(files={"f1.py": meta1})
    candidates = {"f1.py": f1}

    diff, _new_state = diff_state(candidates, old_state)
    assert diff.unchanged == ["f1.py"]
    assert diff.has_changes is False
