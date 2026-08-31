"""Tests for AST-based call site lookup."""

from __future__ import annotations

from pathlib import Path

from context_tree.usages import batch_count_ast_usages, find_ast_usages


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
        "    other_call()\n"
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
        '        AuthService.login("user", "pass");\n'
        '        PaymentService.login("user", "pass");\n'
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
        '        AuthService.Login("user", "pass");\n'
        '        PaymentService.Login("user", "pass");\n'
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
    rs_content = "fn run() {\n    AuthModule::login();\n    auth.login();\n    login();\n}\n"
    rs_file.write_text(rs_content, encoding="utf-8")

    # Bare lookup
    hits_bare = find_ast_usages(tmp_path, "login")
    assert len(hits_bare) == 3

    # Scoped / dotted lookup
    hits_scoped = find_ast_usages(tmp_path, "AuthModule::login")
    assert len(hits_scoped) == 1
    assert hits_scoped[0].line == 2


def test_find_ast_usages_c_cpp(tmp_path: Path) -> None:
    c_file = tmp_path / "main.c"
    c_file.write_text("void run() {\n    add(1, 2);\n    calc.add(3, 4);\n}\n", encoding="utf-8")

    cpp_file = tmp_path / "app.cpp"
    cpp_file.write_text("void exec() {\n    App::add(5, 6);\n}\n", encoding="utf-8")

    hits = find_ast_usages(tmp_path, "add")
    assert len(hits) == 3

    hits_scoped = find_ast_usages(tmp_path, "App::add")
    assert len(hits_scoped) == 1
    assert hits_scoped[0].file == "app.cpp"


def test_find_ast_usages_kotlin_swift(tmp_path: Path) -> None:
    kt_file = tmp_path / "App.kt"
    kt_file.write_text(
        "fun run() {\n    service.findUser(1)\n    findUser(2)\n}\n",
        encoding="utf-8",
    )

    swift_file = tmp_path / "App.swift"
    swift_file.write_text(
        "func run() {\n    service.findUser(3)\n}\n",
        encoding="utf-8",
    )

    hits_bare = find_ast_usages(tmp_path, "findUser")
    assert len(hits_bare) == 3

    hits_dotted = find_ast_usages(tmp_path, "service.findUser")
    assert len(hits_dotted) == 2


def test_batch_count_ast_usages_multi_language(tmp_path: Path) -> None:
    # Python
    py_file = tmp_path / "app.py"
    py_file.write_text(
        "def main():\n"
        '    verify_token("secret")\n'
        '    service.verify_token("other")\n'
        '    AuthService.login("u", "p")\n'
        "    unrelated_call()\n",
        encoding="utf-8",
    )

    # TypeScript
    ts_file = tmp_path / "client.ts"
    ts_file.write_text(
        "function run() {\n    Auth.verify_token(123);\n    PaymentGateway.process();\n}\n",
        encoding="utf-8",
    )

    # Rust
    rs_file = tmp_path / "main.rs"
    rs_file.write_text(
        "fn run() {\n    AuthModule::login();\n    calc.add(1, 2);\n}\n",
        encoding="utf-8",
    )

    symbols = [
        "verify_token",
        "Auth.verify_token",
        "AuthService.login",
        "login",
        "AuthModule::login",
        "process",
        "PaymentGateway.process",
        "add",
        "non_existent_func",
        "",
        "   ",
    ]

    counts = batch_count_ast_usages(tmp_path, symbols)

    assert counts["verify_token"] == 3
    assert counts["Auth.verify_token"] == 1
    assert counts["AuthService.login"] == 1
    assert counts["login"] == 2  # AuthService.login and AuthModule::login
    assert counts["AuthModule::login"] == 1
    assert counts["process"] == 1
    assert counts["PaymentGateway.process"] == 1
    assert counts["add"] == 1
    assert counts["non_existent_func"] == 0

    # Verify that batch counts are 100% equivalent to individual find_ast_usages
    for sym in ["verify_token", "AuthService.login", "login", "AuthModule::login", "process"]:
        assert counts[sym] == len(find_ast_usages(tmp_path, sym))


def test_batch_count_ast_usages_empty_and_limits(tmp_path: Path) -> None:
    # Empty symbols collection
    assert batch_count_ast_usages(tmp_path, []) == {}
    assert batch_count_ast_usages(tmp_path, ["", "   "]) == {}

    # Check max_hits_per_symbol limit
    py_file = tmp_path / "repeated.py"
    py_file.write_text(
        "def test():\n" + "\n".join(f"    foo({i})" for i in range(100)),
        encoding="utf-8",
    )

    counts_default = batch_count_ast_usages(tmp_path, ["foo"], max_hits_per_symbol=50)
    assert counts_default["foo"] == 50

    counts_custom = batch_count_ast_usages(tmp_path, ["foo"], max_hits_per_symbol=10)
    assert counts_custom["foo"] == 10


def test_find_ast_usages_pointer_dereference_c_cpp(tmp_path: Path) -> None:
    c_file = tmp_path / "main.c"
    c_file.write_text(
        "void run() {\n    client->connect();\n    ptr->service->doWork(1);\n}\n",
        encoding="utf-8",
    )

    cpp_file = tmp_path / "app.cpp"
    cpp_file.write_text(
        "void exec() {\n    m_client->connect();\n}\n",
        encoding="utf-8",
    )

    hits_bare = find_ast_usages(tmp_path, "connect")
    assert len(hits_bare) == 2
    assert any(h.file == "main.c" and "client->connect" in h.preview for h in hits_bare)
    assert any(h.file == "app.cpp" and "m_client->connect" in h.preview for h in hits_bare)

    hits_scoped = find_ast_usages(tmp_path, "client->connect")
    assert len(hits_scoped) == 1
    assert hits_scoped[0].file == "main.c"

    hits_dowork = find_ast_usages(tmp_path, "doWork")
    assert len(hits_dowork) == 1


def test_find_ast_usages_new_instantiations(tmp_path: Path) -> None:
    # TS
    ts_file = tmp_path / "client.ts"
    ts_file.write_text(
        "const s = new AuthService();\nconst s2 = new auth.AuthService();\n",
        encoding="utf-8",
    )

    # Java
    java_file = tmp_path / "App.java"
    java_file.write_text(
        "class App { void m() { AuthService s = new AuthService(); } }\n",
        encoding="utf-8",
    )

    # C#
    cs_file = tmp_path / "App.cs"
    cs_file.write_text(
        "class App { void M() { var s = new AuthService(); } }\n",
        encoding="utf-8",
    )

    # C++
    cpp_file = tmp_path / "main.cpp"
    cpp_file.write_text(
        "void m() { auto s = new AuthService(); }\n",
        encoding="utf-8",
    )

    hits_bare = find_ast_usages(tmp_path, "AuthService")
    assert len(hits_bare) == 5

    hits_dotted = find_ast_usages(tmp_path, "auth.AuthService")
    assert len(hits_dotted) == 1
    assert hits_dotted[0].file == "client.ts"

    # Batch test
    batch_counts = batch_count_ast_usages(
        tmp_path, ["AuthService", "auth.AuthService", "NonExistent"]
    )
    assert batch_counts["AuthService"] == 5
    assert batch_counts["auth.AuthService"] == 1
    assert batch_counts["NonExistent"] == 0
