"""Tests for Language Server Protocol (LSP) Bridge."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from context_tree.lsp import (
    LSPClient,
    LSPManager,
    encode_jsonrpc,
    file_path_to_uri,
    uri_to_file_path,
)


def test_encode_jsonrpc() -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "result": "ok"}
    encoded = encode_jsonrpc(payload)
    body_str = json.dumps(payload, ensure_ascii=False)
    expected_header = f"Content-Length: {len(body_str.encode('utf-8'))}\r\n\r\n".encode("ascii")
    assert encoded.startswith(expected_header)
    assert encoded.endswith(body_str.encode("utf-8"))


def test_file_path_and_uri_conversion(tmp_path: Path) -> None:
    sample_file = tmp_path / "app.py"
    sample_file.write_text("print('hello')", encoding="utf-8")

    uri = file_path_to_uri(sample_file)
    assert uri.startswith("file://")

    back_path = uri_to_file_path(uri)
    assert back_path.resolve() == sample_file.resolve()


def test_lsp_location_parsing() -> None:
    client = LSPClient(command=["nonexistent_cmd"], root_path=".")

    loc_dict = {
        "uri": "file:///path/to/module.py",
        "range": {"start": {"line": 10, "character": 4}, "end": {"line": 15, "character": 0}},
    }
    parsed = client._parse_locations(loc_dict)
    assert len(parsed) == 1
    assert parsed[0].start_line == 11
    assert parsed[0].start_character == 4
    assert parsed[0].end_line == 16
    assert parsed[0].end_character == 0
    assert parsed[0].to_dict()["start_line"] == 11

    # LocationLink format
    link_dict = {
        "targetUri": "file:///path/to/service.py",
        "targetRange": {
            "start": {"line": 20, "character": 0},
            "end": {"line": 25, "character": 8},
        },
    }
    parsed_link = client._parse_locations([link_dict])
    assert len(parsed_link) == 1
    assert parsed_link[0].start_line == 21


@pytest.mark.asyncio
async def test_lsp_client_mock_server(tmp_path: Path) -> None:
    # Create a lightweight Python mock LSP server
    mock_server_script = tmp_path / "mock_lsp.py"
    mock_server_code = """
import sys
import json

def send_response(payload):
    body = json.dumps(payload).encode('utf-8')
    header = f"Content-Length: {len(body)}\\r\\n\\r\\n".encode('ascii')
    sys.stdout.buffer.write(header + body)
    sys.stdout.buffer.flush()

while True:
    line = sys.stdin.buffer.readline()
    if not line:
        break
    if line.startswith(b"Content-Length:"):
        length = int(line.split(b":")[1].strip())
        while True:
            sep = sys.stdin.buffer.readline()
            if sep in (b"\\r\\n", b"\\n", b""):
                break
        body = sys.stdin.buffer.read(length)
        msg = json.loads(body.decode('utf-8'))
        msg_id = msg.get('id')
        method = msg.get('method')

        if msg_id is not None:
            if method == 'initialize':
                send_response({'jsonrpc': '2.0', 'id': msg_id, 'result': {'capabilities': {}}})
            elif method == 'textDocument/definition':
                send_response({
                    'jsonrpc': '2.0', 'id': msg_id, 'result': {
                        'uri': 'file:///mock/target.py',
                        'range': {
                            'start': {'line': 4, 'character': 0},
                            'end': {'line': 10, 'character': 0}
                        }
                    }
                })
            elif method == 'textDocument/references':
                send_response({
                    'jsonrpc': '2.0', 'id': msg_id, 'result': [{
                        'uri': 'file:///mock/ref1.py',
                        'range': {
                            'start': {'line': 1, 'character': 2},
                            'end': {'line': 1, 'character': 10}
                        }
                    }]
                })
            elif method == 'textDocument/hover':
                send_response({
                    'jsonrpc': '2.0', 'id': msg_id, 'result': {
                        'contents': 'def calculate_tax(amount: float) -> float'
                    }
                })
            elif method == 'shutdown':
                send_response({'jsonrpc': '2.0', 'id': msg_id, 'result': None})
"""
    mock_server_script.write_text(mock_server_code, encoding="utf-8")

    client = LSPClient([sys.executable, str(mock_server_script)], root_path=tmp_path)
    started = await client.start()
    assert started is True
    assert client.is_running is True

    # Test definition lookup
    defs = await client.goto_definition(tmp_path / "test.py", line=5, character=2)
    assert len(defs) == 1
    assert defs[0].start_line == 5

    # Test references lookup
    refs = await client.find_references(tmp_path / "test.py", line=5, character=2)
    assert len(refs) == 1
    assert refs[0].start_line == 2

    # Test hover lookup
    hover = await client.get_hover(tmp_path / "test.py", line=5, character=2)
    assert hover == "def calculate_tax(amount: float) -> float"

    # Stop client
    await client.stop()
    assert client.is_running is False


@pytest.mark.asyncio
async def test_lsp_manager_missing_binary_fallback(tmp_path: Path) -> None:
    manager = LSPManager(custom_servers={"python": ["non_existent_binary_xyz_123"]})
    client = await manager.get_client_for_language("python", tmp_path)
    assert client is None
    await manager.close_all()
