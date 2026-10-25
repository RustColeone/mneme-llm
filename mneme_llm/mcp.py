"""A Model Context Protocol server over stdio, so any MCP client (Claude Desktop, Claude Code, Cursor, …) can use
mneme-llm's tools without code:

    mneme-llm --db companion.db --space whale_chan mcp --subject discord:42

With `--subject` every call is about that person; without it, each call names its `subject`.
Messages are newline-delimited JSON-RPC 2.0, as the stdio transport specifies.
"""

from __future__ import annotations

import json
import sys
from typing import IO

from . import __version__
from .tools import Toolbox, specs

PROTOCOL = "2025-06-18"
INSTRUCTIONS = ("Long-term memory and mood for this companion. Before answering about the person's life, recall; "
                "when they share something lasting, remember it (one sentence per note).")


def handle(message: dict, toolbox: Toolbox, bound: bool) -> dict | None:
    """The reply to one JSON-RPC message (None for notifications)."""
    method, ident = message.get("method"), message.get("id")
    params = message.get("params") or {}

    def ok(result):
        return {"jsonrpc": "2.0", "id": ident, "result": result}

    if ident is None:  # notifications need no reply
        return None
    if method == "initialize":
        return ok({"protocolVersion": params.get("protocolVersion", PROTOCOL), "capabilities": {"tools": {}},
                   "serverInfo": {"name": "mneme-llm", "version": __version__}, "instructions": INSTRUCTIONS})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": specs("mcp", with_subject=not bound)})
    if method == "tools/call":
        text = toolbox.call(str(params.get("name", "")), params.get("arguments") or {})
        return ok({"content": [{"type": "text", "text": text}], "isError": text.startswith("Error:")})
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"unknown method {method}"}}


def serve(mneme, subject: str | None = None, stdin: IO[str] = sys.stdin, stdout: IO[str] = sys.stdout) -> None:
    toolbox = Toolbox(mneme, subject)
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            reply = handle(message, toolbox, subject is not None) if isinstance(message, dict) else None
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()
