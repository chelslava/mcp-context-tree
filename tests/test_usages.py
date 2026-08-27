"""Tests for AST-based call site lookup."""

from __future__ import annotations

from pathlib import Path

from context_tree.usages import find_ast_usages


def test_find_ast_usages_python_and_ts(tmp_path: Path) -> None:
    py_file = tmp_path / "app.py"
    py_content = (
        "# Comment with verify_token() shouldn't match\n"
        'token_str = "verify_token() in string shouldn\'t match"\n\n'
        "def main():\n"
        '    verify_token("secret")\n'
        '    service.verify_token("other")\n'
        "    unrelated()\n"
    )
    py_file.write_text(py_content, encoding="utf-8")

    ts_file = tmp_path / "client.ts"
    ts_content = "function run() {\n    Auth.verify_token(123);\n}\n"
    ts_file.write_text(ts_content, encoding="utf-8")

    # Bare name lookup
    hits = find_ast_usages(tmp_path, "verify_token")
    assert len(hits) == 3
    assert any(h.file == "app.py" and h.line == 5 for h in hits)
    assert any(h.file == "app.py" and h.line == 6 for h in hits)
    assert any(h.file == "client.ts" and h.line == 2 for h in hits)


def test_find_ast_usages_dotted_name(tmp_path: Path) -> None:
    py_file = tmp_path / "app.py"
    py_content = (
        "def main():\n"
        '    AuthService.login("user", "pass")\n'
        '    PaymentService.login("user", "pass")\n'
        '    other_call()\n'
    )
    py_file.write_text(py_content, encoding="utf-8")

    hits = find_ast_usages(tmp_path, "AuthService.login")
    assert len(hits) == 1
    assert hits[0].line == 2
    assert "AuthService.login" in hits[0].preview


def test_find_ast_usages_java(tmp_path: Path) -> None:
    java_file = tmp_path / "App.java"
    java_content = (
        "class App {\n"
        "    void run() {\n"
        "        AuthService.login(\"user\", \"pass\");\n"
        "        PaymentService.login(\"user\", \"pass\");\n"
        "        login();\n"
        "    }\n"
        "}\n"
    )
    java_file.write_text(java_content, encoding="utf-8")

    # Bare lookup
    hits_bare = find_ast_usages(tmp_path, "login")
    assert len(hits_bare) == 3

    # Dotted lookup
    hits_dotted = find_ast_usages(tmp_path, "AuthService.login")
    assert len(hits_dotted) == 1
    assert hits_dotted[0].line == 3
    assert "AuthService.login" in hits_dotted[0].preview


def test_find_ast_usages_csharp(tmp_path: Path) -> None:
    cs_file = tmp_path / "App.cs"
    cs_content = (
        "class App {\n"
        "    void Run() {\n"
        "        AuthService.Login(\"user\", \"pass\");\n"
        "        PaymentService.Login(\"user\", \"pass\");\n"
        "        Login();\n"
        "    }\n"
        "}\n"
    )
    cs_file.write_text(cs_content, encoding="utf-8")

    # Bare lookup
    hits_bare = find_ast_usages(tmp_path, "Login")
    assert len(hits_bare) == 3

    # Dotted lookup
    hits_dotted = find_ast_usages(tmp_path, "AuthService.Login")
    assert len(hits_dotted) == 1
    assert hits_dotted[0].line == 3
    assert "AuthService.Login" in hits_dotted[0].preview


def test_find_ast_usages_rust(tmp_path: Path) -> None:
    rs_file = tmp_path / "main.rs"
    rs_content = (
        "fn run() {\n"
        "    AuthModule::login();\n"
        "    auth.login();\n"
        "    login();\n"
        "}\n"
    )
    rs_file.write_text(rs_content, encoding="utf-8")

    # Bare lookup
    hits_bare = find_ast_usages(tmp_path, "login")
    assert len(hits_bare) == 3

    # Scoped / dotted lookup
    hits_scoped = find_ast_usages(tmp_path, "AuthModule::login")
    assert len(hits_scoped) == 1
    assert hits_scoped[0].line == 2

