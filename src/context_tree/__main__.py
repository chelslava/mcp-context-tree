"""CLI entry point for ContextTree MCP server and standalone watcher."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from context_tree.server import (
    run_sse_server,
    run_stdio_server,
    run_streamable_http_server,
)
from context_tree.watcher import watch_workspace


def main() -> None:
    """Parse CLI arguments and run MCP server or file watcher."""
    parser = argparse.ArgumentParser(
        prog="context-tree",
        description="ContextTree MCP: Local semantic code search server.",
    )
    parser.add_argument(
        "--watch",
        nargs="?",
        const=".",
        metavar="PATH",
        help="Run in watch mode: monitor directory and incrementally re-index on change.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport protocol (default: stdio).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind for SSE / HTTP transport (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind for SSE / HTTP transport (default: 8000).",
    )

    args = parser.parse_args()

    if args.watch is not None:
        target_dir = Path(args.watch).resolve()
        print(f"ContextTree MCP Watcher starting on: {target_dir}")

        def log_stats(stats):
            if stats.indexed_chunks > 0 or stats.deleted > 0:
                print(
                    f"Indexed: +{stats.added} ~{stats.modified} -{stats.deleted} files "
                    f"({stats.indexed_chunks} chunks). Total in index: {stats.total_in_store}"
                )

        try:
            asyncio.run(watch_workspace(target_dir, on_indexed=log_stats))
        except KeyboardInterrupt:
            print("\nWatcher stopped.")
            sys.exit(0)
    else:
        try:
            if args.transport == "sse":
                asyncio.run(run_sse_server(host=args.host, port=args.port))
            elif args.transport == "streamable-http":
                asyncio.run(run_streamable_http_server(host=args.host, port=args.port))
            else:
                asyncio.run(run_stdio_server())
        except KeyboardInterrupt:
            sys.exit(0)


if __name__ == "__main__":
    main()
