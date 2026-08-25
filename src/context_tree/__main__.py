"""CLI entry point for ContextTree MCP server."""

from __future__ import annotations

import asyncio
import sys

from context_tree.server import run_stdio_server


def main() -> None:
    """Run stdio MCP server."""
    try:
        asyncio.run(run_stdio_server())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
