"""Language Server Protocol (LSP) JSON-RPC client and lifecycle manager.

Implements v0.5 LSP bridge:
- Asynchronous JSON-RPC 2.0 stdio communication
- Client lifecycle (initialize, didOpen, gotoDefinition, findReferences, hover, shutdown)
- LSPManager for binary discovery, routing, and graceful fallback to tree-sitter AST
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from context_tree.config import DEFAULT_LSP_SERVERS, ENABLE_LSP
from context_tree.languages import get_language_config

logger = logging.getLogger("context_tree.lsp")


def encode_jsonrpc(payload: dict[str, Any]) -> bytes:
    """Encode a dictionary payload into JSON-RPC 2.0 wire format with Content-Length header."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def file_path_to_uri(path: Path | str) -> str:
    """Convert a filesystem path to a valid file:// URI."""
    return Path(path).resolve().as_uri()


def uri_to_file_path(uri: str) -> Path:
    """Convert a file:// URI to a local Path object."""
    if uri.startswith("file:///"):
        # Handle Windows vs POSIX URI formats
        raw = uri[7:]
        # On Windows, file:///C:/path -> C:/path
        if len(raw) >= 3 and raw[0] == "/" and raw[2] == ":":
            raw = raw[1:]
        return Path(raw)
    elif uri.startswith("file://"):
        return Path(uri[7:])
    return Path(uri)


@dataclass(frozen=True)
class LSPLocation:
    """A resolved source code location returned by LSP."""

    file: str
    start_line: int  # 1-indexed
    start_character: int  # 0-indexed
    end_line: int  # 1-indexed
    end_character: int  # 0-indexed

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "start_line": self.start_line,
            "start_character": self.start_character,
            "end_line": self.end_line,
            "end_character": self.end_character,
        }


class LSPClient:
    """Asynchronous JSON-RPC client for communicating with a language server over stdio."""

    def __init__(self, command: Sequence[str], root_path: Path | str) -> None:
        self.command = list(command)
        self.root_path = Path(root_path).resolve()
        self.process: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._pending_requests: dict[int, asyncio.Future[Any]] = {}
        self._reader_task: asyncio.Task | None = None
        self._is_initialized = False

    @property
    def is_running(self) -> bool:
        """Return True if the subprocess is running and not terminated."""
        return self.process is not None and self.process.returncode is None

    async def start(self) -> bool:
        """Start the LSP server subprocess and listener loop."""
        if self.is_running:
            return True

        executable = self.command[0]
        if not shutil.which(executable):
            logger.debug("LSP executable '%s' not found in PATH", executable)
            return False

        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._reader_task = asyncio.create_task(self._read_loop())
            return await self.initialize()
        except Exception as err:
            logger.debug("Failed to launch LSP server %s: %s", self.command, err)
            await self.stop()
            return False

    async def _read_loop(self) -> None:
        """Read incoming JSON-RPC responses from stdout."""
        if not self.process or not self.process.stdout:
            return

        stdout = self.process.stdout

        try:
            while True:
                line = await stdout.readline()
                if not line:
                    break

                if line.startswith(b"Content-Length:"):
                    content_length = int(line.split(b":")[1].strip())
                    # Read until empty separator line \r\n
                    while True:
                        sep = await stdout.readline()
                        if sep in (b"\r\n", b"\n", b""):
                            break

                    # Read exact content bytes
                    body = await stdout.readexactly(content_length)
                    try:
                        msg = json.loads(body.decode("utf-8"))
                        self._handle_incoming_message(msg)
                    except Exception as parse_err:
                        logger.debug("Error parsing LSP JSON-RPC message: %s", parse_err)
        except (asyncio.IncompleteReadError, asyncio.CancelledError):
            pass
        except Exception as loop_err:
            logger.debug("LSP read loop error: %s", loop_err)

    def _handle_incoming_message(self, message: dict[str, Any]) -> None:
        """Dispatch incoming JSON-RPC response or notification."""
        msg_id = message.get("id")
        if msg_id is not None and msg_id in self._pending_requests:
            fut = self._pending_requests.pop(msg_id)
            if not fut.done():
                if "error" in message:
                    fut.set_exception(RuntimeError(message["error"]))
                else:
                    fut.set_result(message.get("result"))

    async def send_request(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = 5.0
    ) -> Any:
        """Send a JSON-RPC request and await response."""
        if not self.is_running or not self.process or not self.process.stdin:
            raise RuntimeError("LSP server is not running")

        req_id = self._next_id
        self._next_id += 1

        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._pending_requests[req_id] = fut

        data = encode_jsonrpc(payload)
        self.process.stdin.write(data)
        await self.process.stdin.drain()

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except TimeoutError:
            self._pending_requests.pop(req_id, None)
            raise

    async def send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self.is_running or not self.process or not self.process.stdin:
            return

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        data = encode_jsonrpc(payload)
        self.process.stdin.write(data)
        await self.process.stdin.drain()

    async def initialize(self) -> bool:
        """Send initialize request and initialized notification."""
        try:
            params = {
                "processId": None,
                "rootUri": file_path_to_uri(self.root_path),
                "capabilities": {
                    "textDocument": {
                        "definition": {"dynamicRegistration": False},
                        "references": {"dynamicRegistration": False},
                        "hover": {"dynamicRegistration": False, "contentFormat": ["plaintext"]},
                    }
                },
            }
            await self.send_request("initialize", params, timeout=5.0)
            await self.send_notification("initialized", {})
            self._is_initialized = True
            return True
        except Exception as err:
            logger.debug("LSP initialize failed: %s", err)
            return False

    async def did_open(self, file_path: Path | str, language_id: str, text: str) -> None:
        """Notify server that a document was opened."""
        params = {
            "textDocument": {
                "uri": file_path_to_uri(file_path),
                "languageId": language_id,
                "version": 1,
                "text": text,
            }
        }
        await self.send_notification("textDocument/didOpen", params)

    async def did_close(self, file_path: Path | str) -> None:
        """Notify server that a document was closed."""
        params = {"textDocument": {"uri": file_path_to_uri(file_path)}}
        await self.send_notification("textDocument/didClose", params)

    async def goto_definition(
        self, file_path: Path | str, line: int, character: int = 0
    ) -> list[LSPLocation]:
        """Request textDocument/definition for given (1-indexed line, 0-indexed char)."""
        params = {
            "textDocument": {"uri": file_path_to_uri(file_path)},
            "position": {"line": max(0, line - 1), "character": character},
        }
        try:
            res = await self.send_request("textDocument/definition", params, timeout=3.0)
            return self._parse_locations(res)
        except Exception:
            return []

    async def find_references(
        self,
        file_path: Path | str,
        line: int,
        character: int = 0,
        include_declaration: bool = False,
    ) -> list[LSPLocation]:
        """Request textDocument/references for given (1-indexed line, 0-indexed char)."""
        params = {
            "textDocument": {"uri": file_path_to_uri(file_path)},
            "position": {"line": max(0, line - 1), "character": character},
            "context": {"includeDeclaration": include_declaration},
        }
        try:
            res = await self.send_request("textDocument/references", params, timeout=3.0)
            return self._parse_locations(res)
        except Exception:
            return []

    async def get_hover(self, file_path: Path | str, line: int, character: int = 0) -> str | None:
        """Request textDocument/hover for symbol type and documentation."""
        params = {
            "textDocument": {"uri": file_path_to_uri(file_path)},
            "position": {"line": max(0, line - 1), "character": character},
        }
        try:
            res = await self.send_request("textDocument/hover", params, timeout=2.0)
            if not res or not isinstance(res, dict):
                return None
            contents = res.get("contents")
            if isinstance(contents, str):
                return contents
            elif isinstance(contents, dict) and "value" in contents:
                return contents["value"]
            elif isinstance(contents, list):
                parts = [c if isinstance(c, str) else c.get("value", "") for c in contents if c]
                return "\n".join(parts)
            return None
        except Exception:
            return None

    def _parse_locations(self, result: Any) -> list[LSPLocation]:
        """Normalize Location, LocationLink, or list of Locations into LSPLocation objects."""
        if not result:
            return []

        raw_list = [result] if isinstance(result, dict) else result
        locations: list[LSPLocation] = []

        for item in raw_list:
            if not isinstance(item, dict):
                continue
            uri = item.get("uri") or item.get("targetUri")
            rng = item.get("range") or item.get("targetSelectionRange") or item.get("targetRange")
            if not uri or not rng:
                continue

            file_path = uri_to_file_path(uri)
            start = rng.get("start", {})
            end = rng.get("end", {})

            locations.append(
                LSPLocation(
                    file=str(file_path),
                    start_line=int(start.get("line", 0)) + 1,
                    start_character=int(start.get("character", 0)),
                    end_line=int(end.get("line", 0)) + 1,
                    end_character=int(end.get("character", 0)),
                )
            )

        return locations

    async def stop(self) -> None:
        """Gracefully shutdown and terminate the language server subprocess."""
        if self._is_initialized and self.is_running:
            with contextlib.suppress(Exception):
                await self.send_request("shutdown", {}, timeout=1.0)
                await self.send_notification("exit", {})

        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()

        if self.process and self.process.returncode is None:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=1.0)
            except Exception:
                with contextlib.suppress(Exception):
                    self.process.kill()

        self.process = None
        self._is_initialized = False


class LSPManager:
    """Manages LSP client lifecycles and routes requests by language."""

    def __init__(self, custom_servers: dict[str, list[str]] | None = None) -> None:
        self.servers_config = custom_servers or dict(DEFAULT_LSP_SERVERS)
        self.clients: dict[tuple[str, str], LSPClient] = {}
        self._lock = asyncio.Lock()

    async def get_client_for_language(
        self, language: str, root_path: Path | str
    ) -> LSPClient | None:
        """Return or start an LSPClient for *language* in workspace *root_path*."""
        if not ENABLE_LSP or language not in self.servers_config:
            return None

        root_resolved = str(Path(root_path).resolve())
        key = (language, root_resolved)

        async with self._lock:
            if key in self.clients:
                client = self.clients[key]
                if client.is_running:
                    return client
                else:
                    self.clients.pop(key, None)

            command = self.servers_config[language]
            client = LSPClient(command, root_resolved)
            started = await client.start()
            if started:
                self.clients[key] = client
                return client
            return None

    async def get_client_for_file(
        self, file_path: Path | str, root_path: Path | str | None = None
    ) -> LSPClient | None:
        """Resolve language for file and return its active LSP client if available."""
        path = Path(file_path)
        cfg = get_language_config(path)
        if cfg is None:
            return None

        root = Path(root_path).resolve() if root_path else path.parent.resolve()
        return await self.get_client_for_language(cfg.name, root)

    async def close_all(self) -> None:
        """Stop all active language server processes."""
        async with self._lock:
            for client in self.clients.values():
                await client.stop()
            self.clients.clear()


# Global manager singleton
_GLOBAL_LSP_MANAGER: LSPManager | None = None


def get_lsp_manager() -> LSPManager:
    """Return the global LSPManager instance."""
    global _GLOBAL_LSP_MANAGER
    if _GLOBAL_LSP_MANAGER is None:
        _GLOBAL_LSP_MANAGER = LSPManager()
    return _GLOBAL_LSP_MANAGER
