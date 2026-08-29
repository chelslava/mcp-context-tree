"""Tests for MCP server tool registration and execution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from context_tree.server import create_server


@pytest.mark.asyncio
async def test_server_list_tools() -> None:
    app = create_server()
    tools = await app.list_tools()
    names = [t.name for t in tools]
    assert "index_workspace" in names
    assert "semantic_search" in names
    assert "find_ast_usages" in names
    assert "go_to_definition" in names


@pytest.mark.asyncio
async def test_server_tool_calls(tmp_path: Path) -> None:
    app = create_server()

    # Create dummy source file
    code_file = tmp_path / "app.py"
    code_content = (
        "def login_service(username, password):\n"
        '    """Handle user authentication and login."""\n'
        "    return True\n"
    )
    code_file.write_text(code_content, encoding="utf-8")

    # 1. index_workspace
    idx_call = await app.call_tool("index_workspace", {"directory_path": str(tmp_path)})
    assert not idx_call.is_error
    idx_data = json.loads(idx_call.content[0].text)
    assert idx_data["status"] == "ok"
    assert idx_data["indexed_chunks"] == 1

    # 2. semantic_search
    search_call = await app.call_tool(
        "semantic_search",
        {"query": "user authentication service", "directory_path": str(tmp_path)},
    )
    assert not search_call.is_error
    search_data = json.loads(search_call.content[0].text)
    assert len(search_data["results"]) == 1
    assert search_data["results"][0]["name"] == "login_service"

    # 3. find_ast_usages
    usages_call = await app.call_tool(
        "find_ast_usages",
        {"symbol_name": "login_service", "directory_path": str(tmp_path)},
    )
    assert not usages_call.is_error
    usages_data = json.loads(usages_call.content[0].text)
    assert "usages" in usages_data

    # 4. go_to_definition
    def_call = await app.call_tool(
        "go_to_definition",
        {"symbol_name": "login_service", "directory_path": str(tmp_path)},
    )
    assert not def_call.is_error
    def_data = json.loads(def_call.content[0].text)
    assert len(def_data["definitions"]) == 1
    assert def_data["definitions"][0]["name"] == "login_service"
    assert def_data["definitions"][0]["file"] == "app.py"


def test_server_sse_app_creation() -> None:
    app = create_server()
    starlette_sse = app.sse_app()
    assert starlette_sse is not None

    starlette_http = app.streamable_http_app()
    assert starlette_http is not None


def test_cli_transport_args(monkeypatch) -> None:
    from context_tree.__main__ import main

    called = {}

    async def mock_run_sse(*args, **kwargs):
        called["sse"] = (args, kwargs)

    monkeypatch.setattr("context_tree.__main__.run_sse_server", mock_run_sse)
    monkeypatch.setattr("sys.argv", ["context-tree", "--transport", "sse", "--port", "9000"])

    main()
    assert "sse" in called
    assert called["sse"][1]["port"] == 9000
