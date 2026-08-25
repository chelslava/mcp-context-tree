"""Central constants shared across ContextTree MCP modules."""

from __future__ import annotations

# --- Vector store / index state -----------------------------------------------
CHROMA_DIR_NAME = ".chroma"
STATE_FILE_NAME = "index_state.json"
COLLECTION_NAME = "context_tree"

# --- Embeddings -----------------------------------------------------------------
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_BATCH_SIZE = 64

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
        ".chroma",
        ".idea",
        ".vscode",
    }
)

# --- Search defaults ------------------------------------------------------------
DEFAULT_SEARCH_LIMIT = 5
