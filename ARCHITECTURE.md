# ContextTree MCP — Architecture

> Status: design document for v0.1 · Target runtime: Python 3.12+ · Last updated: 2026-08

This document describes the internal architecture of **ContextTree MCP**: project layout, the
AST extraction logic, the ChromaDB data schema, and the incremental indexing algorithm.
It is the source of truth for contributors — keep code changes consistent with it.

---

## 1. Overview

ContextTree MCP is a local [Model Context Protocol](https://modelcontextprotocol.io) server
(stdio transport) that indexes a workspace into a persistent vector store so that an AI
assistant can search code by *meaning* rather than by keywords.

Design principles:

| Principle | Consequence |
|---|---|
| **Local-first privacy** | Parsing, embeddings and storage are fully offline; nothing leaves the machine. The index lives in `.chroma/` and is git-ignored. |
| **AST fidelity over text windows** | Chunks are logical units (functions, methods, class signatures) produced by tree-sitter, never arbitrary fixed-size text slices. |
| **Context-enriched documents** | Every embedded document carries file path, class, method name, docstring and body — so vector similarity reflects *where* and *what*, not just raw tokens. |
| **Incremental by default** | Files are hashed (SHA-256); only added / modified / deleted files ever touch the parser or the embedding model. |
| **Extensible language registry** | Adding a language = registering one config object (grammar import + node-type queries). No changes to core logic. |

Non-goals for v0.1: network transports (SSE/WebSocket), remote DB backends, watch mode,
multi-workspace single collection.

---

## 2. High-Level Data Flow

```
                        INDEXING PATH (index_workspace)
┌─────────────┐   ┌──────────────┐   ┌───────────────┐   ┌──────────────────┐
│ Workspace    │→ │ Hash diff vs │→ │ tree-sitter    │→ │ Context-Enriched  │
│ scan         │   │ index_state  │   │ parse (changed │   │ Logical Blocks    │
│ (filtered)   │   │ (.chroma/)   │   │ files only)    │   │ (chunker)         │
└─────────────┘   └──────────────┘   └───────────────┘   └────────┬─────────┘
                                                                    │
                     ┌──────────────────────┐   ┌──────────────────▼─────────┐
                     │ ChromaDB upsert/delete │← │ all-MiniLM-L6-v2            │
                     │ collection .chroma/    │   │ embeddings (batched)        │
                     └──────────────────────┘   └─────────────────────────────┘

                        QUERY PATHS
semantic_search:  query → embed → ANN top-k (cosine) → read snippet from disk → results
find_ast_usages:  parse file(s) on demand → AST query for call sites → locations
```

---

## 3. Project Layout

Modern `src/` layout (packaged via `pyproject.toml`, console script `context-tree`).

```
mcp-context-tree/
├── src/
│   └── context_tree/
│       ├── __init__.py          # package metadata
│       ├── __main__.py          # entry point: builds server, serves via stdio
│       ├── server.py            # MCP server instance; tool registration & schemas
│       ├── config.py            # constants: model name, chunk caps, ignore rules,
│       │                        #   state paths, collection name
│       ├── languages.py         # LanguageConfig registry: ext → grammar + node queries
│       ├── parser.py            # tree-sitter parsing; returns (tree, source_bytes)
│       ├── extractor.py         # AST → logical blocks (per-language node walk)
│       ├── chunker.py           # block → enriched document string; oversized splitting
│       ├── embedder.py          # sentence-transformers wrapper (lazy singleton, batching)
│       ├── indexer.py           # orchestration: scan → diff → extract → embed → commit
│       ├── store.py             # ChromaDB client/collection wrapper (upsert/delete/query)
│       └── state.py             # file-hash persistence: .chroma/index_state.json
├── tests/
│   ├── test_extractor.py        # golden fixtures: source → expected blocks
│   ├── test_chunker.py          # enrichment template, ID grammar, oversized split
│   ├── test_indexer.py          # add/modify/delete/rename scenarios (tmp dirs)
│   └── test_store.py            # schema round-trip against a temp chroma dir
├── examples/                    # sample configs, demo workspace
├── docs/
├── .chroma/                     # git-ignored: vector store + index_state.json
├── pyproject.toml               # canonical manifest (deps, ruff, pytest config)
├── requirements.txt             # pip compatibility layer
├── ARCHITECTURE.md              # this document
├── README.md                    # English readme
└── README.ru.md                 # Russian readme
```

Module dependency direction (strictly one-way):

```
server.py → indexer.py → {parser, extractor, chunker, embedder, store, state}
                ↑
languages.py / config.py are leaf modules used by everyone
```

---

## 4. Indexing Pipeline (`index_workspace(directory_path)`)

### 4.1 File discovery & filtering

- Walk the workspace with `pathlib.Path.rglob("*")`.
- **Directory deny-list** (never descend): `.git`, `.hg`, `.svn`, `node_modules`,
  `__pycache__`, `.venv`, `venv`, `.tox`, `dist`, `build`, `.chroma`, `.idea`, `.vscode`.
- **Extension allow-list** comes from the language registry (§4.3): `.py`, `.ts`, `.tsx`,
  `.js`, `.jsx` at launch.
- Skip files larger than a configurable cap (default **1 MB**) and binary-looking content
  (NUL byte in first 8 KB).

### 4.2 Change detection — incremental core

State lives in `.chroma/index_state.json` next to the vector store:

```json
{
  "version": 1,
  "files": {
    "src/api/auth.py": {
      "sha256": "9f86d081884c7d65…",
      "size": 4821,
      "mtime": 1755850000.123
    }
  }
}
```

Algorithm per candidate file:

1. Fast-path: if `size` and `mtime` match the stored values → treat as unchanged, skip
   hashing entirely (cheap check dominates on warm runs).
2. Otherwise compute `sha256(content)`. Equal hash → unchanged (touch `mtime` in state).
3. Classify: `added` (no entry), `modified` (hash differs), `deleted` (entry without file).

Only `added` + `modified` files are parsed and embedded. For every `added`/`modified`
file, all previous vectors of that file are removed before inserting fresh ones
(`collection.delete(where={"file": rel_path})`) — this guarantees no stale chunks survive
partial edits. `deleted` files get the same removal plus a state-entry purge.

Crash-safety: the state file is written atomically (temp file + `os.replace`) **after**
the ChromaDB mutations succeed. Worst case after a crash: some files are re-parsed and
re-embedded on the next run — the index itself never becomes inconsistent.

### 4.3 AST parsing — language registry

Each supported language is a `LanguageConfig` record:

| Field | Purpose | Example (Python) |
|---|---|---|
| `extensions` | routing | `{".py"}` |
| `language_fn` | grammar loader | `from tree_sitter_python import language` |
| `block_queries` | node kinds to extract | `function_definition`, `decorated_definition`, `class_definition` |
| `docstring_rule` | how to fetch docs | first child `expression_statement(string)` of body |
| `class_context` | ancestor walk | enclosing `class_definition` `identifier` chain |

Parsing uses one shared `Parser` per language (created lazily). tree-sitter is
error-tolerant: syntactically broken files still yield partial trees — blocks extracted
before the error point are indexed, the error is logged, never fatal.

### 4.4 Logical block extraction (granularity)

Extraction walks the tree and emits one block per logical unit:

| Node kind | What becomes a block | Notes |
|---|---|---|
| `function_definition` (py) | whole function | module-level functions |
| `decorated_definition` wrapper (py) | decorator + function | decorators included in code span |
| method = `function_definition` inside `class_definition.body` | whole method | `class` metadata filled from ancestors |
| `class_definition` (py) | **signature-only**: header line(s) + docstring | body excluded — members are indexed separately |
| `function_declaration`, `generator_function_declaration` (ts/js) | whole function | |
| `method_definition` (ts/js/jsx) | whole method | class from `class_declaration` parent |
| `class_declaration` / `class` (ts/js) | signature + JSDoc comment | body excluded |

Docs sources: Python — PEP-257 docstring (first string literal of the body);
JS/TS — preceding `/** … */` JSDoc block attached to the node.

Nested classes produce chained context (`Outer::Inner`) both in IDs and documents.

### 4.5 Oversized blocks

The embedding model truncates input at ~256 word-pieces, so giant functions would lose
their tail silently. Blocks whose body exceeds a token estimate cap (~512 tokens) are
split into overlapping body windows (~15% overlap), while each part keeps the full
enrichment header (file/class/name/docstring) so retrieval quality is preserved.
Part suffixes extend the ID: `…::method_name@part2`. Metadata keeps the real
`start_line`/`end_line` of that window's slice.

---

## 5. Context-Enriched Logical Blocks (document template)

Before vectorization, every block is rendered into a canonical plain-text document.
This is what the embedding model actually sees:

```
File: src/api/auth.py
Class: AuthService
Method: login
Docstring: Authenticate user credentials and return a signed JWT token.
Code:
def login(self, username: str, password: str) -> Token:
    """Authenticate user credentials and return a signed JWT token."""
    ...
```

Rules:

- `Class:` omitted for module-level functions; `Method:` equals the function name there.
- Path is workspace-relative with forward slashes (stable across OS/clone locations).
- The template is deterministic — identical source ⇒ byte-identical document ⇒ stable
  embeddings, which makes future hash-based reuse trivial.

Why each field exists: the path disambiguates same-named symbols; class/method names give
the model identifier vocabulary users will query with; the docstring carries intent in
natural language (the strongest signal for NL queries); the body grounds everything in
real implementation details.

---

## 6. Embedding Layer

| Property | Value |
|---|---|
| Model | `sentence-transformers/all-MiniLM-L6-v2` |
| Dimensions | 384 |
| Normalization | L2 (cosine-ready) |
| Batching | configurable batch size (default 64), single pass per indexing run |
| Lifecycle | lazy singleton — loaded on first tool call, reused afterwards |
| Device | CPU default; auto-upgrade if CUDA/MPS available |

---

## 7. ChromaDB Schema

Persistent client rooted at `<workspace>/.chroma/`, single collection:

| Setting | Value |
|---|---|
| Collection name | `context_tree` |
| Distance metric | `hnsw:space = cosine` |
| Client | `chromadb.PersistentClient(path=".chroma")` |

### 7.1 ID grammar

```
<relative_file_path>::<ClassChain>::<member_name>[@partN]
```

| Case | ID example |
|---|---|
| Method | `src/api/auth.py::AuthService::login` |
| Nested-class method | `src/models/tree.py::Outer::Inner::prune` |
| Module-level function | `src/utils/hash.py::compute_digest` |
| Split oversized block | `src/big.py::pipeline::stage@part2` |

Collision policy: if two blocks resolve to the same ID (e.g. overloaded names in TS), a
numeric suffix `#2`, `#3`, … is appended deterministically in source order.

### 7.2 Record fields

| Field | Type | Content |
|---|---|---|
| `id` | string | grammar above |
| `document` | string | enriched template from §5 |
| `metadatas.file` | string | relative posix path |
| `metadatas.type` | string | `function` \| `method` \| `class_signature` |
| `metadatas.class` | string | owning class chain, `""` for module level |
| `metadatas.name` | string | member/function name |
| `metadatas.language` | string | `python` \| `typescript` \| `tsx` \| `javascript` |
| `metadatas.start_line` | int | 1-based inclusive |
| `metadatas.end_line` | int | 1-based inclusive |
| `metadatas.content_hash` | string | SHA-256 of the block's source slice (future reuse) |

Example record:

```json
{
  "id": "src/api/auth.py::AuthService::login",
  "document": "File: src/api/auth.py\nClass: AuthService\nMethod: login\n...",
  "metadata": {
    "file": "src/api/auth.py",
    "type": "method",
    "class": "AuthService",
    "name": "login",
    "language": "python",
    "start_line": 42,
    "end_line": 67,
    "content_hash": "b6c3e0…"
  },
  "embedding": "[384 floats]"
}
```

### 7.3 Mutation semantics

- Insert/update: `collection.upsert(ids, documents, metadatas, embeddings)` — idempotent.
- Remove-by-file: `collection.delete(where={"file": rel_path})` — used for deleted files
  and before re-inserting modified ones (ChromaDB `where` filters apply to metadata).

---

## 8. Incremental Re-indexing Algorithm

```
def index_workspace(root):
    candidates  = discover_files(root)                      # §4.1
    old_state   = load_state(".chroma/index_state.json")
    added, modified, deleted = diff(candidates, old_state)  # §4.2

    collection.delete(where={"$in": {"file": [*modified, *deleted]}})
    state.drop(deleted)

    blocks     = [extract(parse(f)) for f in sorted(added + modified)]
    documents  = [render(b) for b in blocks]                # §5
    embeddings = embedder.encode(documents, batch=64)       # §6

    collection.upsert(ids, documents, metadatas, embeddings)
    save_state_atomic(state.merge(candidates))              # last step, atomic write
```

Properties:

- **Unchanged files cost O(1)** (size/mtime fast-path) — no parsing, no embedding.
- Re-indexing an empty-diff workspace performs zero model calls.
- Failure mid-run leaves the previous consistent generation intact; the next run simply
  redoes the interrupted files.

---

## 9. `semantic_search(query, limit=5)` Flow

1. Reject if the collection is empty (explicit "run index_workspace first" message).
2. `q = embedder.encode([query])[0]`.
3. `res = collection.query(query_embeddings=[q], n_results=limit, include=[metadatas, documents, distances])`.
4. For each hit, read the snippet live from disk using `start_line..end_line` (the index
   may be slightly stale; disk is always current).
5. Return structured results:

```json
{
  "results": [
    {
      "file": "src/api/auth.py",
      "type": "method",
      "class": "AuthService",
      "name": "login",
      "start_line": 42,
      "end_line": 67,
      "score": 0.87,
      "code": "def login(self, username: str, ...) -> Token:\n    ..."
    }
  ]
}
```

(`score = 1 − cosine distance`, higher is better.)

---

## 10. `find_ast_usages(symbol_name)` Flow

Accepts a bare name (`retry`) or dotted target (`PaymentGateway.retry`).

1. Locate candidate files: prefer files present in the index state (already-known source
   files of supported languages); parse each with its language grammar.
2. Run an AST query for call-shaped nodes:
   - Python: `call` whose function is an `attribute` (`obj.method`) matching the member
     name, or an `identifier` matching a bare name;
   - JS/TS: `call_expression` whose `function` is `member_expression` / `identifier`.
3. Match semantics: dotted form requires the trailing segment to equal the member name
   (and, when resolvable cheaply, the object type prefix to start with the class name);
   bare name matches any callee identifier.
4. String literals and comments can never match — they are not call nodes in the AST.
5. Return `file`, `start_line`, `end_line` and a one-line preview per hit, capped at a
   configurable maximum (default 50 hits).

---

## 11. Concurrency & Performance Notes

- Stdio MCP servers handle requests sequentially; nevertheless all collection mutations
  are guarded by a single `asyncio.Lock` to stay safe under client concurrency.
- Embedding is the dominant cost; batching (§6) and incremental diffs (§8) keep warm runs
  near-instant.
- ChromaDB HNSW handles hundreds of thousands of blocks comfortably at 384 dims; no
  approximate-search tuning needed at this scale.

## 12. Quality Gates

Per repository engineering standards (canonical manifest `pyproject.toml`):

| Gate | Command |
|---|---|
| Format + lint | `ruff format . && ruff check .` |
| Static types | `pyright` (public APIs and boundaries must be annotated) |
| Tests | `pytest` (unit fixtures per module; tmp-dir based integration tests) |

CI runs exactly these commands; local verification before pushing mirrors CI.

## 13. Extending to a New Language

Add one `LanguageConfig` to `languages.py` (extensions, grammar import, block node kinds,
doc rule, class-context rule) + fixture tests. No changes to indexer/store/search logic.

## 14. Future Directions

Watch mode (fs watcher), hybrid lexical+vector ranking, call-graph-aware scoring,
chunk-level embedding cache keyed by `content_hash` (skip unchanged blocks inside a
changed file), additional grammars.
