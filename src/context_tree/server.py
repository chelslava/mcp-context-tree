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
from pathlib import Path
from typing import Literal

from mcp.server import MCPServer

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
    app = MCPServer("context-tree", version="0.2.0")

    @app.tool(
        description=(
            "Walks the project, detects changed files by SHA-256 hash, and "
            "incrementally updates the persistent local ChromaDB vector store."
        )
    )
    async def index_workspace(directory_path: str = ".") -> str:
        """Index or incrementally update the workspace vector store."""
        async with _MUTEX:
            target = Path(directory_path).resolve()
            if not target.is_dir():
                return json.dumps({"error": f"Directory not found: {directory_path}"})
            indexer = Indexer(target)
            stats = indexer.index()
            return json.dumps(
                {
                    "status": "ok",
                    "workspace": str(target),
                    "added": stats.added,
                    "modified": stats.modified,
                    "deleted": stats.deleted,
                    "unchanged": stats.unchanged,
                    "indexed_chunks": stats.indexed_chunks,
                    "total_in_store": stats.total_in_store,
                },
                indent=2,
            )

    @app.tool(
        description=(
            "Search code by meaning and keywords (hybrid BM25+vectors, semantic, or keyword). "
            "Returns ranked code fragments with exact file, class, method, start_line, end_line, and code snippets."
        )
    )
    async def semantic_search(
        query: str,
        directory_path: str = ".",
        limit: int = DEFAULT_SEARCH_LIMIT,
        mode: SearchMode = "hybrid",
    ) -> str:
        """Search code using hybrid, semantic, or keyword matching."""
        async with _MUTEX:
            target = Path(directory_path).resolve()
            results = do_semantic_search(target, query, limit=limit, mode=mode)
            return json.dumps({"results": [r.to_dict() for r in results]}, indent=2)

    @app.tool(
        description=(
            "AST-based lookup of real call sites / instantiations of a function or class. "
            "Filters out string literals, comments, and non-call occurrences."
        )
    )
    async def find_ast_usages(
        symbol_name: str,
        directory_path: str = ".",
        limit: int = 50,
    ) -> str:
        """Find AST call sites of a symbol across the workspace."""
        async with _MUTEX:
            target = Path(directory_path).resolve()
            hits = do_find_ast_usages(target, symbol_name, max_hits=limit)
            return json.dumps({"usages": [h.to_dict() for h in hits]}, indent=2)

    return app


async def run_stdio_server() -> None:
    """Run the ContextTree MCP server over stdio."""
    app = create_server()
    await app.run_stdio_async()
