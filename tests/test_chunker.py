"""Tests for the chunker module: ID grammar, template rendering, oversized splitting."""

from __future__ import annotations

from context_tree.chunker import (
    Chunk,
    build_base_id,
    chunk_block,
    chunk_blocks,
    compute_content_hash,
    render_document,
)
from context_tree.extractor import CodeBlock


def test_build_base_id() -> None:
    assert build_base_id("src/api/auth.py", "login", "AuthService") == "src/api/auth.py::AuthService::login"
    assert build_base_id("src/models/tree.py", "prune", "Outer::Inner") == "src/models/tree.py::Outer::Inner::prune"
    assert build_base_id("src/utils/hash.py", "compute_digest") == "src/utils/hash.py::compute_digest"


def test_render_document() -> None:
    doc = render_document(
        file_path="src/api/auth.py",
        name="login",
        code="def login(): pass",
        class_chain="AuthService",
        docstring="Authenticate user credentials.",
    )
    expected = (
        "File: src/api/auth.py\n"
        "Class: AuthService\n"
        "Method: login\n"
        "Docstring: Authenticate user credentials.\n"
        "Code:\ndef login(): pass"
    )
    assert doc == expected


def test_render_document_module_level_without_docstring() -> None:
    doc = render_document(
        file_path="src/utils.py",
        name="helper",
        code="def helper(): return 1",
    )
    expected = (
        "File: src/utils.py\n"
        "Method: helper\n"
        "Code:\ndef helper(): return 1"
    )
    assert doc == expected


def test_chunk_normal_block() -> None:
    block = CodeBlock(
        file="src/service.py",
        language="python",
        block_type="method",
        name="execute",
        class_chain="Runner",
        start_line=10,
        end_line=15,
        code="def execute(self):\n    return True",
        docstring="Run process.",
    )
    chunks = chunk_block(block)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.id == "src/service.py::Runner::execute"
    assert c.file == "src/service.py"
    assert c.chunk_type == "method"
    assert c.class_chain == "Runner"
    assert c.name == "execute"
    assert c.language == "python"
    assert c.start_line == 10
    assert c.end_line == 15
    assert c.content_hash == compute_content_hash(block.code)
    assert "Class: Runner" in c.document


def test_chunk_oversized_block() -> None:
    long_code = "\n".join(f"    line_{i} = {i} * 2  # extensive calculation step" for i in range(150))
    block = CodeBlock(
        file="src/big.py",
        language="python",
        block_type="function",
        name="huge_pipeline",
        class_chain="",
        start_line=1,
        end_line=150,
        code=long_code,
        docstring="Heavy computation.",
    )
    chunks = chunk_block(block)
    assert len(chunks) > 1
    assert chunks[0].id == "src/big.py::huge_pipeline@part1"
    assert chunks[1].id == "src/big.py::huge_pipeline@part2"
    assert all("Docstring: Heavy computation." in c.document for c in chunks)
    assert chunks[0].start_line == 1
    assert chunks[-1].end_line == 150


def test_chunk_blocks_collision_handling() -> None:
    b1 = CodeBlock(
        file="src/overloads.ts",
        language="typescript",
        block_type="function",
        name="process",
        class_chain="",
        start_line=1,
        end_line=3,
        code="function process(x: number): void;",
    )
    b2 = CodeBlock(
        file="src/overloads.ts",
        language="typescript",
        block_type="function",
        name="process",
        class_chain="",
        start_line=4,
        end_line=6,
        code="function process(x: string): void;",
    )
    chunks = chunk_blocks([b1, b2])
    assert len(chunks) == 2
    assert chunks[0].id == "src/overloads.ts::process"
    assert chunks[1].id == "src/overloads.ts::process#2"
