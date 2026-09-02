"""Tests for multi-repository unified workspace indexing and cross-repo search."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from context_tree.definitions import find_symbol_definitions
from context_tree.indexer import Indexer, resolve_workspace_roots
from context_tree.search import semantic_search
from context_tree.server import create_server
from context_tree.usages import find_ast_usages


def test_resolve_workspace_roots_single_and_multi(tmp_path: Path) -> None:
    dir_a = tmp_path / "backend"
    dir_b = tmp_path / "frontend"
    dir_a.mkdir()
    dir_b.mkdir()

    # None defaults to current dir
    assert len(resolve_workspace_roots(None)) == 1

    # Single path string
    r1 = resolve_workspace_roots(str(dir_a))
    assert len(r1) == 1
    assert r1[0] == dir_a.resolve()

    # Comma-separated paths
    r2 = resolve_workspace_roots(f"{dir_a}, {dir_b}")
    assert len(r2) == 2
    assert dir_a.resolve() in r2
    assert dir_b.resolve() in r2

    # Semicolon-separated paths
    r3 = resolve_workspace_roots(f"{dir_a};{dir_b}")
    assert len(r3) == 2

    # Sequence of paths
    r4 = resolve_workspace_roots([dir_a, dir_b])
    assert len(r4) == 2


def test_multi_repo_indexing_and_cross_search(tmp_path: Path) -> None:
    # 1. Setup repo_a (backend - Python)
    repo_a = tmp_path / "backend"
    repo_a.mkdir()
    auth_file = repo_a / "auth.py"
    auth_file.write_text(
        "def authenticate_token(token: str) -> bool:\n"
        '    """Validate JWT token signature and expiry."""\n'
        "    return token == 'secret'\n",
        encoding="utf-8",
    )

    # 2. Setup repo_b (frontend - TypeScript)
    repo_b = tmp_path / "frontend"
    repo_b.mkdir()
    api_client = repo_b / "client.ts"
    api_client.write_text(
        "export function authenticate_token(token: string): boolean {\n"
        "    // Send token to backend auth endpoint\n"
        "    return token.length > 0;\n"
        "}\n",
        encoding="utf-8",
    )

    # 3. Index both repositories in unified indexer
    indexer = Indexer([repo_a, repo_b])
    stats = indexer.index()
    assert stats.added == 2
    assert stats.indexed_chunks == 2
    assert stats.total_in_store == 2

    # 4. Search across all repositories
    results_all = semantic_search(
        [repo_a, repo_b],
        "validate token authentication",
        limit=5,
        mode="hybrid",
    )
    assert len(results_all) == 2
    repos_found = {r.repo for r in results_all}
    assert "backend" in repos_found
    assert "frontend" in repos_found

    # 5. Filter search by repo
    results_backend = semantic_search(
        [repo_a, repo_b],
        "validate token authentication",
        limit=5,
        repo="backend",
    )
    assert len(results_backend) >= 1
    for r in results_backend:
        assert r.repo == "backend"

    # 6. Cross-repo go_to_definition
    defs = find_symbol_definitions([repo_a, repo_b], "authenticate_token")
    assert len(defs) == 2
    def_repos = {d.repo for d in defs}
    assert "backend" in def_repos
    assert "frontend" in def_repos


def test_multi_repo_usages(tmp_path: Path) -> None:
    repo_a = tmp_path / "service_a"
    repo_a.mkdir()
    (repo_a / "worker.py").write_text(
        "def process_job():\n    dispatch_event('job_started')\n",
        encoding="utf-8",
    )

    repo_b = tmp_path / "service_b"
    repo_b.mkdir()
    (repo_b / "handler.py").write_text(
        "def on_message():\n    dispatch_event('message_received')\n",
        encoding="utf-8",
    )

    usages = find_ast_usages([repo_a, repo_b], "dispatch_event")
    assert len(usages) == 2
    usage_repos = {u.repo for u in usages}
    assert "service_a" in usage_repos
    assert "service_b" in usage_repos


@pytest.mark.asyncio
async def test_server_multi_repo_tools(tmp_path: Path) -> None:
    app = create_server()

    repo_core = tmp_path / "core"
    repo_core.mkdir()
    (repo_core / "math.py").write_text(
        "def compute_matrix(dim: int):\n"
        '    """Compute square matrix dimensions."""\n'
        "    return dim * dim\n",
        encoding="utf-8",
    )

    repo_ui = tmp_path / "ui"
    repo_ui.mkdir()
    (repo_ui / "render.py").write_text(
        "def render_chart():\n    return compute_matrix(10)\n",
        encoding="utf-8",
    )

    multi_path_str = f"{repo_core}, {repo_ui}"

    # 1. Index multi-workspace via server
    idx_call = await app.call_tool("index_workspace", {"directory_path": multi_path_str})
    assert not idx_call.is_error
    idx_data = json.loads(idx_call.content[0].text)
    assert idx_data["status"] == "ok"
    assert "workspaces" in idx_data
    assert len(idx_data["workspaces"]) == 2

    # 2. Semantic search across multi-workspace
    search_call = await app.call_tool(
        "semantic_search",
        {"query": "compute matrix", "directory_path": multi_path_str},
    )
    assert not search_call.is_error
    search_data = json.loads(search_call.content[0].text)
    assert len(search_data["results"]) >= 1
    assert search_data["results"][0]["name"] == "compute_matrix"

    # 3. Find usages across multi-workspace
    usages_call = await app.call_tool(
        "find_ast_usages",
        {"symbol_name": "compute_matrix", "directory_path": multi_path_str},
    )
    assert not usages_call.is_error
    usages_data = json.loads(usages_call.content[0].text)
    assert len(usages_data["usages"]) == 1
    assert usages_data["usages"][0]["file"] == "render.py"
    assert usages_data["usages"][0]["repo"] == "ui"

    # 4. Go to definition across multi-workspace
    def_call = await app.call_tool(
        "go_to_definition",
        {"symbol_name": "compute_matrix", "directory_path": multi_path_str},
    )
    assert not def_call.is_error
    def_data = json.loads(def_call.content[0].text)
    assert len(def_data["definitions"]) == 1
    assert def_data["definitions"][0]["file"] == "math.py"
    assert def_data["definitions"][0]["repo"] == "core"
