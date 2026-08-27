"""Integration tests for the Indexer pipeline: add, modify, delete, ignore rules."""

from __future__ import annotations

from pathlib import Path

from context_tree.indexer import Indexer, discover_files


def test_discover_files_respects_ignores_and_extensions(tmp_path: Path) -> None:
    # Supported files
    (tmp_path / "a.py").write_text("def a(): pass", encoding="utf-8")
    (tmp_path / "b.ts").write_text("function b() {}", encoding="utf-8")

    # Ignored build & compiler output directories
    for ignored in (
        ".git",
        ".venv",
        "target",
        "bin",
        "obj",
        "vendor",
        "out",
        ".gradle",
        ".next",
        ".nuxt",
        ".turbo",
        ".output",
        "coverage",
    ):
        d = tmp_path / ignored
        d.mkdir(parents=True, exist_ok=True)
        (d / "ignored.rs").write_text("fn ignored() {}", encoding="utf-8")
        (d / "ignored.cs").write_text("class Ignored {}", encoding="utf-8")
        (d / "ignored.go").write_text("package ignored", encoding="utf-8")

    # Unsupported extension
    (tmp_path / "data.json").write_text("{}", encoding="utf-8")

    candidates = discover_files(tmp_path)
    assert "a.py" in candidates
    assert "b.ts" in candidates
    assert len(candidates) == 2


def test_discover_files_respects_gitignore(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("def main(): pass", encoding="utf-8")
    (tmp_path / "secret.py").write_text("def secret(): pass", encoding="utf-8")

    custom_dir = tmp_path / "generated"
    custom_dir.mkdir()
    (custom_dir / "gen.ts").write_text("export const x = 1;", encoding="utf-8")

    (tmp_path / ".gitignore").write_text(
        "# Comments should be ignored\n\nsecret.py\ngenerated/\n",
        encoding="utf-8",
    )

    candidates = discover_files(tmp_path)
    assert "main.py" in candidates
    assert "secret.py" not in candidates
    assert "generated/gen.ts" not in candidates
    assert len(candidates) == 1


def test_indexer_incremental_scenarios(tmp_path: Path) -> None:
    f1 = tmp_path / "src" / "math.py"
    f1.parent.mkdir(parents=True)
    f1.write_text("def add(a, b): return a + b\n\ndef sub(a, b): return a - b", encoding="utf-8")

    indexer = Indexer(tmp_path)

    # 1. Initial run (added)
    stats1 = indexer.index()
    assert stats1.added == 1
    assert stats1.indexed_chunks == 2
    assert stats1.total_in_store == 2

    # 2. Warm run (unchanged fast-path)
    stats2 = indexer.index()
    assert stats2.unchanged == 1
    assert stats2.indexed_chunks == 0
    assert stats2.total_in_store == 2

    # 3. Add second file
    f2 = tmp_path / "src" / "greet.ts"
    f2.write_text("export function hello(): string { return 'hi'; }", encoding="utf-8")

    stats3 = indexer.index()
    assert stats3.added == 1
    assert stats3.unchanged == 1
    assert stats3.indexed_chunks == 1
    assert stats3.total_in_store == 3

    # 4. Modify math.py
    f1.write_text("def add(a, b): return a + b", encoding="utf-8")  # removed sub
    stats4 = indexer.index()
    assert stats4.modified == 1
    assert stats4.unchanged == 1
    assert stats4.indexed_chunks == 1
    assert stats4.total_in_store == 2  # 1 math + 1 greet

    # 5. Delete greet.ts
    f2.unlink()
    stats5 = indexer.index()
    assert stats5.deleted == 1
    assert stats5.unchanged == 1
    assert stats5.indexed_chunks == 0
    assert stats5.total_in_store == 1
