# ContextTree MCP 🌳

**Deep semantic code search for AI assistants — powered by AST parsing and local embeddings. 100% offline.**

[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/protocol-Model%20Context%20Protocol-purple.svg)](https://modelcontextprotocol.io)
[![README (RU)](https://img.shields.io/badge/README-Русский-red.svg)](README.ru.md)

ContextTree MCP is a local [Model Context Protocol](https://modelcontextprotocol.io) server that gives your AI coding assistant **structural understanding** of a codebase. It combines two worlds:

- **tree-sitter** parses source files into an AST and extracts *logical blocks* — functions, methods, class signatures with docstrings.
- **sentence-transformers** (`all-MiniLM-L6-v2`) embeds each block — enriched with file path, class name, method name and docstring — into a local **ChromaDB** vector store.

The result: your assistant finds code by *meaning*, not by keywords, and every search hit comes back with exact file path and line numbers.

> 🔒 **Privacy first.** Everything runs on your machine: parsing, embedding model, vector index. No cloud calls, no telemetry, no code ever leaves the disk it lives on.

---

## Why not plain text search?

`grep` and full-text search match strings. They fail exactly where developers need help most:

| Task | Text search | ContextTree MCP |
|---|---|---|
| *"Where do we validate JWT tokens?"* | ❌ needs exact keyword guessing | ✅ matches `AuthService.verify_token()` even if "validate" never appears in code |
| Find a method whose name was refactored | ❌ broken by rename | ✅ docstring + surrounding context still carry the meaning |
| Distinguish definition vs. usage | ❌ impossible without regex gymnastics | ✅ AST-level separation of declarations and call sites |
| Return precise locations | ⚠️ line of match only | ✅ `file`, `class`, `method`, `start_line`, `end_line` metadata |
| Ignore comments / strings / imports noise | ❌ | ✅ only real logical units are indexed |

## Features

- 🌲 **AST-aware chunking** — indexes functions, methods and class signatures via tree-sitter, not arbitrary text windows.
- 🧩 **Context-Enriched Logical Blocks** — every indexed document embeds its file path, owning class, method name, docstring and body, so queries like *"payment retry logic"* hit the right method.
- ⚡ **Incremental indexing** — SHA-256 content hashes per file; only changed/new/deleted files are reprocessed.
- 🔍 **Semantic search** — natural-language query → ranked code fragments with exact line ranges.
- 📞 **AST usage lookup** — find real call sites of any symbol (function or class), filtered from false positives like string literals or comments.
- 🗄️ **Persistent local index** — ChromaDB stored in `.chroma/`, survives restarts, never committed to Git.
- 🔌 **Stdio MCP transport** — plugs into Claude Desktop, OpenCode, Cursor, Cline, or any MCP-compatible client.

## Tech stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| Protocol | Official [`mcp`](https://pypi.org/project/mcp/) SDK (stdio transport) |
| AST parsing | [`tree-sitter`](https://tree-sitter.github.io/) + bindings for Python, TypeScript, JavaScript |
| Vector database | [`chromadb`](https://www.trychroma.com/) (local persistent mode) |
| Embeddings | [`sentence-transformers`](https://www.sbert.net/) · `all-MiniLM-L6-v2` |

## Installation

Requires Python **3.12+**. [`uv`](https://docs.astral.sh/uv/) is recommended as a fast, modern package manager:

```bash
git clone https://github.com/<your-org>/mcp-context-tree.git
cd mcp-context-tree

# Option A — uv (recommended): resolves dependencies from pyproject.toml, locks uv.lock
uv sync

# Option B — classic pip + venv
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

> 💡 First run downloads the embedding model (~90 MB). PyTorch is installed as a dependency of `sentence-transformers`; CPU build is sufficient — no GPU required.

### Registering with an MCP client

Example configuration (Claude Desktop / any client supporting stdio servers):

```json
{
  "mcpServers": {
    "context-tree": {
      "command": "<path-to-venv>/bin/python",
      "args": ["-m", "context_tree"],
      "env": {}
    }
  }
}
```

*(On Windows use `<path-to-venv>\Scripts\python.exe`.)*

## Tools exposed to the assistant

| Tool | Signature | Description |
|---|---|---|
| `index_workspace` | `(directory_path: str)` | Walks the project, detects changed files by hash, incrementally updates the ChromaDB collection. |
| `semantic_search` | `(query: str, limit: int = 5)` | Natural-language search over indexed code. Returns enriched snippets with `file`, `class`, `start_line`, `end_line`. |
| `find_ast_usages` | `(symbol_name: str)` | AST-based lookup of real call sites / instantiations of a function or class. |

Typical workflow:

```
1. index_workspace("D:/projects/my-app")
2. semantic_search("where do we handle payment retries", limit=8)
3. find_ast_usages("PaymentGateway.retry")
```

## Supported languages

| Language | Status |
|---|---|
| Python | ✅ supported at launch |
| TypeScript / TSX | ✅ supported at launch |
| JavaScript / JSX | ✅ supported at launch |
| Go, Java, Rust… | 🗺️ roadmap — parser registry is designed for extension |

## Documentation

- 🏛️ [ARCHITECTURE.md](ARCHITECTURE.md) — project layout, ChromaDB data schema, AST extraction logic, incremental indexing design.
- 🇷🇺 [README.ru.md](README.ru.md) — документация на русском языке.

## Roadmap

- [ ] Watch mode — automatic re-indexing on file change (fs watcher)
- [ ] More languages via tree-sitter bindings
- [ ] Hybrid search (BM25 + vectors rerank)
- [ ] Call-graph aware ranking ("who calls this?")
- [ ] PyPI release (`context-tree-mcp`)

## Contributing

Issues and PRs are welcome. Please keep changes consistent with [ARCHITECTURE.md](ARCHITECTURE.md).

## License

MIT — see [LICENSE](LICENSE).
