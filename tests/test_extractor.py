"""Golden-fixture tests for the AST extraction layer."""

from __future__ import annotations

from pathlib import Path

from context_tree.extractor import CodeBlock, extract_blocks
from context_tree.languages import get_language_config
from context_tree.parser import parse_file, read_source

PY_SOURCE = '''\
import os

def top_fn(a: int) -> str:
    """Docstring of top."""
    return str(a)

@decorator
async def deco_fn():
    pass

class Outer:
    """Class doc."""

    class Inner:
        def deep(self):
            return 1

    def m2(self, x):
        return x

if True:
    def cond_fn(): ...

def tail_fn():
    """Tail."""
    return 2
'''

TS_SOURCE = """\
/** Service docs */
export class Svc<T> extends Base {
    /** Method doc */
    async run(x: number): Promise<void> {}
    helper() { return 1; }
}

/** Fn docs */
export function fn(a: number): string { return ""; }

function* gen() { yield 1; }

const arrow = (x: number) => x * 2;
"""

JSX_SOURCE = """\
const el = <div className="x">hi</div>;

function JsComp() {
    return <span>ok</span>;
}

class JsClass {
    greet() { return 2; }
}
"""

TSX_SOURCE = """\
export function Btn(): JSX.Element {
    return <b>x</b>;
}
"""


def _write(tmp_path: Path, name: str, content: str) -> Path:
    file_path = tmp_path / name
    file_path.write_text(content, encoding="utf-8")
    return file_path


def _find(blocks: list[CodeBlock], name: str, chain: str = "") -> CodeBlock:
    matches = [b for b in blocks if b.name == name and b.class_chain == chain]
    assert len(matches) == 1, f"expected single block {chain}::{name}, got {matches}"
    return matches[0]


def test_python_golden_fixture(tmp_path: Path) -> None:
    source_path = _write(tmp_path, "sample.py", PY_SOURCE)

    blocks = extract_blocks(source_path, root=tmp_path)

    assert len(blocks) == 8
    assert all(b.file == "sample.py" for b in blocks)
    assert all(b.language == "python" for b in blocks)

    top_fn = _find(blocks, "top_fn")
    assert top_fn.block_type == "function"
    assert (top_fn.start_line, top_fn.end_line) == (3, 5)
    assert top_fn.docstring == "Docstring of top."

    deco_fn = _find(blocks, "deco_fn")
    assert (deco_fn.start_line, deco_fn.end_line) == (7, 9)
    assert deco_fn.docstring == ""
    assert deco_fn.code.startswith("@decorator")

    outer = _find(blocks, "Outer")
    assert outer.block_type == "class_signature"
    assert (outer.start_line, outer.end_line) == (11, 12)
    assert outer.docstring == "Class doc."
    assert "class Outer" in outer.code
    assert "def m2" not in outer.code  # body members excluded from signature

    inner = _find(blocks, "Inner", chain="Outer")
    assert inner.block_type == "class_signature"
    assert (inner.start_line, inner.end_line) == (14, 14)

    deep = _find(blocks, "deep", chain="Outer::Inner")
    assert deep.block_type == "method"
    assert (deep.start_line, deep.end_line) == (15, 16)
    assert deep.qualified_name == "Outer::Inner::deep"

    m2 = _find(blocks, "m2", chain="Outer")
    assert m2.block_type == "method"
    assert (m2.start_line, m2.end_line) == (18, 19)

    cond_fn = _find(blocks, "cond_fn")
    assert cond_fn.block_type == "function"
    assert cond_fn.start_line == 22

    tail_fn = _find(blocks, "tail_fn")
    assert (tail_fn.start_line, tail_fn.end_line) == (24, 26)
    assert tail_fn.docstring == "Tail."


def test_typescript_golden_fixture(tmp_path: Path) -> None:
    source_path = _write(tmp_path, "sample.ts", TS_SOURCE)

    blocks = extract_blocks(source_path, root=tmp_path)

    assert len(blocks) == 5

    svc = _find(blocks, "Svc")
    assert svc.block_type == "class_signature"
    assert (svc.start_line, svc.end_line) == (1, 2)
    assert svc.docstring == "/** Service docs */"
    assert "helper" not in svc.code

    run = _find(blocks, "run", chain="Svc")
    assert run.block_type == "method"
    assert (run.start_line, run.end_line) == (3, 4)
    assert run.docstring == "/** Method doc */"

    helper = _find(blocks, "helper", chain="Svc")
    assert helper.block_type == "method"
    assert (helper.start_line, helper.end_line) == (5, 5)

    fn = _find(blocks, "fn")
    assert fn.block_type == "function"
    assert (fn.start_line, fn.end_line) == (8, 9)
    assert fn.docstring == "/** Fn docs */"

    gen = _find(blocks, "gen")
    assert gen.block_type == "function"
    assert gen.start_line == 11
    # Arrow functions are out of v0.1 granularity (ARCHITECTURE.md §4.4).
    assert not [b for b in blocks if b.name == "arrow"]


def test_jsx_routed_to_javascript_grammar(tmp_path: Path) -> None:
    source_path = _write(tmp_path, "component.jsx", JSX_SOURCE)

    blocks = extract_blocks(source_path, root=tmp_path)

    js_comp = _find(blocks, "JsComp")
    assert js_comp.language == "javascript"
    assert (js_comp.start_line, js_comp.end_line) == (3, 5)

    js_class = _find(blocks, "JsClass")
    assert js_class.block_type == "class_signature"
    assert (js_class.start_line, js_class.end_line) == (7, 7)

    greet = _find(blocks, "greet", chain="JsClass")
    assert greet.block_type == "method"
    assert greet.start_line == 8


def test_tsx_uses_dedicated_grammar(tmp_path: Path) -> None:
    source_path = _write(tmp_path, "button.tsx", TSX_SOURCE)

    blocks = extract_blocks(source_path, root=tmp_path)

    btn = _find(blocks, "Btn")
    assert btn.language == "tsx"
    assert btn.block_type == "function"
    assert (btn.start_line, btn.end_line) == (1, 3)


def test_language_config_routing() -> None:
    assert get_language_config("a.PY").name == "python"  # case-insensitive suffix
    assert get_language_config("b.tsx").name == "tsx"
    assert get_language_config("c.jsx").name == "javascript"
    assert get_language_config("d.toml") is None


def test_binary_file_is_skipped(tmp_path: Path) -> None:
    binary_path = tmp_path / "binary.py"
    binary_path.write_bytes(b"\x00\x01\x02def broken(): pass")

    assert parse_file(binary_path) is None
    assert extract_blocks(binary_path) == []


def test_read_source_respects_max_bytes(tmp_path: Path) -> None:
    big_path = _write(tmp_path, "big.py", "# padding\n" * 20)

    assert read_source(big_path, max_bytes=10) is None
    assert read_source(big_path) == big_path.read_bytes()


def test_broken_syntax_still_yields_blocks(tmp_path: Path) -> None:
    truncated = "def good():\n    return 1\n\ndef bad(: int\n"
    source_path = _write(tmp_path, "truncated.py", truncated)

    blocks = extract_blocks(source_path, root=tmp_path)

    good = _find(blocks, "good")
    assert good.block_type == "function"


def test_unsupported_or_missing_paths_yield_nothing(tmp_path: Path) -> None:
    assert extract_blocks(tmp_path / "notes.toml") == []
    assert extract_blocks(tmp_path / "does_not_exist.py") == []
