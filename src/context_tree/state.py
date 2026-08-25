"""File-hash persistence and change detection for incremental indexing.

Implements ARCHITECTURE.md §4.2:
- .chroma/index_state.json management
- Fast-path size/mtime check
- SHA-256 content hash change detection
- Atomic state file saving
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class FileMeta:
    """Stored metadata for a single tracked file."""

    sha256: str
    size: int
    mtime: float


@dataclass
class IndexState:
    """The root index state structure."""

    version: int = 1
    files: dict[str, FileMeta] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "files": {rel: asdict(meta) for rel, meta in self.files.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> IndexState:
        version = data.get("version", 1)
        raw_files = data.get("files", {})
        files = {
            rel: FileMeta(
                sha256=m["sha256"],
                size=m["size"],
                mtime=m["mtime"],
            )
            for rel, m in raw_files.items()
            if isinstance(m, dict) and "sha256" in m and "size" in m and "mtime" in m
        }
        return cls(version=version, files=files)


@dataclass(frozen=True)
class DiffResult:
    """Categorized file changes against previous state."""

    added: list[str]
    modified: list[str]
    deleted: list[str]
    unchanged: list[str]

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.modified or self.deleted)


def compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 of file content."""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def compute_file_meta(path: Path) -> FileMeta:
    """Stat and hash file."""
    st = path.stat()
    sha = compute_file_sha256(path)
    return FileMeta(sha256=sha, size=st.st_size, mtime=st.st_mtime)


def load_state(state_file: Path) -> IndexState:
    """Load index state from JSON file; returns empty state if missing/corrupt."""
    if not state_file.is_file():
        return IndexState()
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return IndexState.from_dict(data)
    except (OSError, json.JSONDecodeError):
        pass
    return IndexState()


def save_state_atomic(state: IndexState, state_file: Path) -> None:
    """Atomically write index state to disk using a temporary file."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = state_file.with_name(f"{state_file.name}.tmp.{os.getpid()}")
    try:
        content = json.dumps(state.to_dict(), indent=2, sort_keys=True)
        temp_file.write_text(content, encoding="utf-8")
        temp_file.replace(state_file)
    except Exception:
        if temp_file.exists():
            with contextlib.suppress(OSError):
                temp_file.unlink()
        raise


def diff_state(
    candidates: Mapping[str, Path], old_state: IndexState
) -> tuple[DiffResult, IndexState]:
    """Compute diff between candidate files and stored state.

    Returns:
        (DiffResult, updated_new_state)
    """
    added: list[str] = []
    modified: list[str] = []
    unchanged: list[str] = []
    deleted: list[str] = []

    new_files: dict[str, FileMeta] = {}

    for rel_path, abs_path in sorted(candidates.items()):
        try:
            st = abs_path.stat()
        except OSError:
            continue

        cached = old_state.files.get(rel_path)
        if cached is None:
            # Added file
            sha = compute_file_sha256(abs_path)
            meta = FileMeta(sha256=sha, size=st.st_size, mtime=st.st_mtime)
            new_files[rel_path] = meta
            added.append(rel_path)
        else:
            # Fast path: check size and mtime
            if cached.size == st.st_size and abs(cached.mtime - st.st_mtime) < 1e-4:
                new_files[rel_path] = cached
                unchanged.append(rel_path)
            else:
                # Content hash check
                sha = compute_file_sha256(abs_path)
                meta = FileMeta(sha256=sha, size=st.st_size, mtime=st.st_mtime)
                new_files[rel_path] = meta
                if sha == cached.sha256:
                    unchanged.append(rel_path)
                else:
                    modified.append(rel_path)

    # Check for deleted files
    for old_rel in old_state.files:
        if old_rel not in candidates:
            deleted.append(old_rel)

    result = DiffResult(
        added=added,
        modified=modified,
        deleted=deleted,
        unchanged=unchanged,
    )
    new_state = IndexState(version=old_state.version, files=new_files)
    return result, new_state
