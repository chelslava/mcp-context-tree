"""Tests for AST symbol definition lookup."""

from __future__ import annotations

from pathlib import Path

from context_tree.definitions import find_symbol_definitions


def test_find_symbol_definitions_bare_and_qualified(tmp_path: Path) -> None:
    py_file = tmp_path / "service.py"
    py_content = (
        "class AuthService:\n"
        '    """Handles user auth."""\n'
        "    def login(self, username, password):\n"
        '        """Login user."""\n'
        "        return True\n\n"
        "def helper_func():\n"
        "    return 42\n"
    )
    py_file.write_text(py_content, encoding="utf-8")

    ts_file = tmp_path / "api.ts"
    ts_content = "export const addNumbers = (a: number, b: number) => a + b;\n"
    ts_file.write_text(ts_content, encoding="utf-8")

    # 1. Bare function name
    hits_helper = find_symbol_definitions(tmp_path, "helper_func")
    assert len(hits_helper) == 1
    assert hits_helper[0].file == "service.py"
    assert hits_helper[0].type == "function"
    assert hits_helper[0].start_line == 7

    # 2. Bare class name
    hits_class = find_symbol_definitions(tmp_path, "AuthService")
    assert len(hits_class) == 1
    assert hits_class[0].type == "class_signature"

    # 3. Qualified method name (dotted)
    hits_login_dotted = find_symbol_definitions(tmp_path, "AuthService.login")
    assert len(hits_login_dotted) == 1
    assert hits_login_dotted[0].name == "login"
    assert hits_login_dotted[0].class_chain == "AuthService"
    assert hits_login_dotted[0].type == "method"

    # 4. Qualified method name (C++/Rust scoped syntax)
    hits_login_scoped = find_symbol_definitions(tmp_path, "AuthService::login")
    assert len(hits_login_scoped) == 1
    assert hits_login_scoped[0].name == "login"

    # 5. TS arrow function
    hits_ts = find_symbol_definitions(tmp_path, "addNumbers")
    assert len(hits_ts) == 1
    assert hits_ts[0].file == "api.ts"


def test_find_symbol_definitions_multi_language(tmp_path: Path) -> None:
    c_file = tmp_path / "math.c"
    c_file.write_text("int compute(int x) { return x * 2; }\n", encoding="utf-8")

    kt_file = tmp_path / "User.kt"
    kt_file.write_text('class UserRepo { fun getUser(): String = "u" }\n', encoding="utf-8")

    # C definition
    hits_c = find_symbol_definitions(tmp_path, "compute")
    assert len(hits_c) == 1
    assert hits_c[0].file == "math.c"
    assert hits_c[0].language == "c"

    # Kotlin method definition
    hits_kt = find_symbol_definitions(tmp_path, "UserRepo.getUser")
    assert len(hits_kt) == 1
    assert hits_kt[0].file == "User.kt"
    assert hits_kt[0].language == "kotlin"
