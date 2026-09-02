"""Central constants shared across ContextTree MCP modules."""

from __future__ import annotations

import os

# --- Vector store / index state -----------------------------------------------
CHROMA_DIR_NAME = ".chroma"
STATE_FILE_NAME = "index_state.json"
COLLECTION_NAME = "context_tree"

# --- Embeddings & Quantization --------------------------------------------------
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_BATCH_SIZE = 64
DEFAULT_EMBEDDING_PRECISION = os.getenv("CONTEXT_TREE_EMBEDDING_PRECISION", "float32")
SUPPORTED_EMBEDDING_PRECISIONS: tuple[str, ...] = ("float32", "int8", "binary", "ubinary")

# --- File scanning guards -------------------------------------------------------
MAX_FILE_SIZE_BYTES = 1_000_000
BINARY_SNIFF_BYTES = 8_192

IGNORED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".nox",
        "dist",
        "build",
        "target",
        "bin",
        "obj",
        "vendor",
        "out",
        ".gradle",
        ".next",
        ".nuxt",
        ".turbo",
        ".output",
        "coverage",
        ".chroma",
        ".idea",
        ".vscode",
    }
)

# --- Search defaults ------------------------------------------------------------
DEFAULT_SEARCH_LIMIT = 5

# --- Language Server Protocol (LSP) Bridge --------------------------------------
ENABLE_LSP = os.getenv("CONTEXT_TREE_ENABLE_LSP", "true").lower() in ("true", "1", "yes")
DEFAULT_LSP_SERVERS: dict[str, list[str]] = {
    "python": ["pyright-langserver", "--stdio"],
    "typescript": ["typescript-language-server", "--stdio"],
    "javascript": ["typescript-language-server", "--stdio"],
    "go": ["gopls"],
    "rust": ["rust-analyzer"],
    "c": ["clangd"],
    "cpp": ["clangd"],
    "c_sharp": ["csharp-ls"],
}
