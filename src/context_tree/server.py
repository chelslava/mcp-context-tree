"""MCP server instance exposing index_workspace, semantic_search, and find_ast_usages.

Implements ARCHITECTURE.md §3, §9, §10, §11:
- MCP stdio server via MCPServer
- Tool registration and schemas (with hybrid search support)
- Concurrency protection via asyncio.Lock
"""

from __future__ import annotations

import asyncio
import json
import logging

from mcp.server import MCPServer

from context_tree import __version__
from context_tree.config import DEFAULT_SEARCH_LIMIT
from context_tree.indexer import Indexer
from context_tree.search import SearchMode
from context_tree.search import semantic_search as do_semantic_search
from context_tree.usages import find_ast_usages as do_find_ast_usages

logger = logging.getLogger("context_tree.server")

# Mutex to ensure safe execution under concurrency (§11)
_MUTEX = asyncio.Lock()


def create_server() -> MCPServer:
    """Create and configure the ContextTree MCP server instance."""
    app = MCPServer("context-tree", version=__version__)

    @app.tool(
        description=(
            "Walks the project or multiple workspace repositories, detects changed files by "
            "SHA-256 hash, and incrementally updates the persistent local ChromaDB vector store. "
            "Supports single directory path or multiple comma-separated workspace paths."
        )
    )
    async def index_workspace(directory_path: str = ".") -> str:
        """Index or incrementally update the workspace vector store."""
        async with _MUTEX:
            from context_tree.indexer import resolve_workspace_roots

            roots = resolve_workspace_roots(directory_path)
            valid_roots = [r for r in roots if r.is_dir()]
            if not valid_roots:
                return json.dumps({"error": f"Directory not found: {directory_path}"})
            indexer = Indexer(valid_roots)
            stats = indexer.index()
            payload: dict = {
                "status": "ok",
                "workspace": str(valid_roots[0]),
                "added": stats.added,
                "modified": stats.modified,
                "deleted": stats.deleted,
                "unchanged": stats.unchanged,
                "indexed_chunks": stats.indexed_chunks,
                "total_in_store": stats.total_in_store,
            }
            if len(valid_roots) > 1:
                payload["workspaces"] = [str(r) for r in valid_roots]
            return json.dumps(payload, indent=2)

    @app.tool(
        description=(
            "Search code by meaning and keywords (hybrid BM25+vectors, semantic, or keyword) "
            "across one or more repositories. Returns ranked code fragments with exact file, "
            "repo, class, method, start_line, end_line, and code snippets. "
            "Supports optional Cross-Encoder re-ranking (rerank=True) and repo filter."
        )
    )
    async def semantic_search(
        query: str,
        directory_path: str = ".",
        limit: int = DEFAULT_SEARCH_LIMIT,
        mode: SearchMode = "hybrid",
        rerank: bool = False,
        repo: str | None = None,
    ) -> str:
        """Search code using hybrid, semantic, or keyword matching with optional reranking."""
        async with _MUTEX:
            from context_tree.indexer import resolve_workspace_roots

            roots = resolve_workspace_roots(directory_path)
            results = do_semantic_search(
                roots, query, limit=limit, mode=mode, rerank=rerank, repo=repo
            )
            return json.dumps({"results": [r.to_dict() for r in results]}, indent=2)

    @app.tool(
        description=(
            "AST-based lookup of real call sites / instantiations of a function or class "
            "across one or more repositories. Filters out string literals, comments, "
            "and non-call occurrences."
        )
    )
    async def find_ast_usages(
        symbol_name: str,
        directory_path: str = ".",
        limit: int = 50,
        repo: str | None = None,
    ) -> str:
        """Find AST call sites of a symbol across the workspace(s)."""
        async with _MUTEX:
            from context_tree.indexer import resolve_workspace_roots

            roots = resolve_workspace_roots(directory_path)
            hits = do_find_ast_usages(roots, symbol_name, max_hits=limit, repo=repo)
            return json.dumps({"usages": [h.to_dict() for h in hits]}, indent=2)

    @app.tool(
        description=(
            "Finds the exact definition/declaration location of a symbol (function, "
            "method, class, struct, trait, interface) across workspace files and repositories."
        )
    )
    async def go_to_definition(
        symbol_name: str,
        directory_path: str = ".",
        limit: int = 20,
        repo: str | None = None,
    ) -> str:
        """Find exact AST declaration sites of a symbol across the workspace(s)."""
        async with _MUTEX:
            from context_tree.indexer import resolve_workspace_roots

            roots = resolve_workspace_roots(directory_path)
            from context_tree.definitions import find_symbol_definitions

            hits = find_symbol_definitions(roots, symbol_name, max_hits=limit, repo=repo)
            return json.dumps({"definitions": [h.to_dict() for h in hits]}, indent=2)

    return app


async def run_stdio_server() -> None:
    """Run the ContextTree MCP server over stdio."""
    app = create_server()
    await app.run_stdio_async()


async def run_sse_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the ContextTree MCP server over SSE (Server-Sent Events) HTTP transport."""
    app = create_server()
    logger.info("Starting ContextTree MCP SSE server on %s:%d", host, port)
    await app.run_sse_async(host=host, port=port)


async def run_streamable_http_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the ContextTree MCP server over Streamable HTTP transport."""
    app = create_server()
    logger.info("Starting ContextTree MCP Streamable HTTP server on %s:%d", host, port)
    await app.run_streamable_http_async(host=host, port=port)
