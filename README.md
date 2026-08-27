# ContextTree MCP 🌳

**Deep semantic & hybrid code search for AI assistants — powered by AST parsing and local embeddings. 100% offline.**

[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/protocol-Model%20Context%20Protocol-purple.svg)](https://modelcontextprotocol.io)
[![README (RU)](https://img.shields.io/badge/README-Русский-red.svg)](README.ru.md)

ContextTree MCP is a local [Model Context Protocol](https://modelcontextprotocol.io) server that gives your AI coding assistant **structural understanding** of a codebase. It combines three powerful pillars:

- **tree-sitter** parses source files into an AST and extracts *logical blocks* — functions, methods, and class/struct signatures with docstrings.
- **Hybrid Search (BM25 + Dense Vectors with Reciprocal Rank Fusion)** — combines exact keyword/identifier matches (`camelCase`, `snake_case`) with dense vector embeddings (`sentence-transformers/all-MiniLM-L6-v2` in ChromaDB).
- **Watch Mode & Incremental Indexing** — SHA-256 hash change detection and asynchronous filesystem watcher for instant updates on save.

> 🔒 **Privacy first.** Everything runs on your machine: parsing, embedding model, vector index. No cloud calls, no telemetry, no code ever leaves the disk it lives on.

---

## Supported Languages

| Language | Extensions | AST Units Indexed |
|---|---|---|
| **Python** | `.py` | functions, decorated functions, methods, class signatures & PEP-257 docs |
| **TypeScript / TSX** | `.ts`, `.tsx`, `.mts`, `.cts` | functions, arrow functions, methods, class signatures & JSDoc |
| **JavaScript / JSX** | `.js`, `.jsx`, `.mjs`, `.cjs` | functions, arrow functions, methods, class signatures & JSDoc |
| **Go** | `.go` | functions, receiver methods, struct/interface types & comments |
| **Rust** | `.rs` | functions, impl methods, struct & trait signatures, `///` docs |
| **C#** | `.cs` | methods, constructors, class & interface signatures, `/// <summary>` XML-docs |
| **Java** | `.java` | methods, constructors, class, interface & record signatures, Javadoc |
| **C** | `.c`, `.h` | functions, struct/union/enum declarations & doc comments |
| **C++** | `.cpp`, `.hpp`, `.cc`, `.cxx`, `.hh`, `.hxx` | functions, methods, classes, structs, namespaces & doc comments |
| **Kotlin** | `.kt`, `.kts` | functions, classes, objects, member methods & KDoc |
| **Swift** | `.swift` | functions, methods, classes, structs, protocols, enums & Swift docs |

---

## Installation & Quick Start

Requires Python **3.12+**. [`uv`](https://docs.astral.sh/uv/) is recommended:

```bash
git clone https://github.com/chelslava/mcp-context-tree.git
cd mcp-context-tree
uv sync
```

### Running the Server

```bash
# Standard stdio server (for MCP clients)
uv run context-tree

# Watch mode (monitors directory and incrementally indexes on save)
uv run context-tree --watch /path/to/project
```

### Registering with MCP Clients

Example configuration (`claude_desktop_config.json` or Antigravity / Cursor configs):

```json
{
  "mcpServers": {
    "context-tree": {
      "command": "uv",
      "args": ["run", "--directory", "D:/Repo/mcp-context-tree", "context-tree"]
    }
  }
}
```

---

## Tools Exposed to Assistant

| Tool | Parameters | Description |
|---|---|---|
| `index_workspace` | `(directory_path: str = ".")` | Scans workspace, diffs against index state, incrementally indexes changed files. |
| `semantic_search` | `(query: str, limit: int = 5, mode: str = "hybrid")` | Hybrid (BM25 + vectors), semantic-only, or keyword search. Returns exact line snippets. |
| `find_ast_usages` | `(symbol_name: str, limit: int = 50)` | AST lookup of real call sites / instantiations (filters out string literals & comments). |

---

## License

MIT — see [LICENSE](LICENSE).
