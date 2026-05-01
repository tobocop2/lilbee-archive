# ruff: noqa: S607
"""Tiny MCP JSON-RPC driver.

Spawns ``lilbee mcp`` over stdio, sends one tool call, prints the
response, exits. Used by the matrix runner for the MCP-Search cell.

Usage::

    uv run python scripts/qa/mcp_driver.py search 'battery technology'
    uv run python scripts/qa/mcp_driver.py status
"""

from __future__ import annotations

import json
import subprocess
import sys

_REQUIRED_ARGS = 2  # script + tool name


def _send(proc: subprocess.Popen[bytes], obj: dict) -> dict:
    line = (json.dumps(obj) + "\n").encode("utf-8")
    proc.stdin.write(line)
    proc.stdin.flush()
    response = proc.stdout.readline()
    return json.loads(response.decode("utf-8"))


def main() -> int:
    if len(sys.argv) < _REQUIRED_ARGS:
        print("usage: mcp_driver.py <tool> [args...]", file=sys.stderr)
        return 2
    tool = sys.argv[1]
    arg_text = " ".join(sys.argv[2:])

    proc = subprocess.Popen(
        ["uv", "run", "lilbee", "mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    try:
        # Init handshake.
        _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "qa-driver", "version": "0.0"},
                },
            },
        )
        proc.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        proc.stdin.flush()

        if tool == "search":
            args = {"query": arg_text or "test", "top_k": 5}
        elif tool == "status":
            args = {}
        else:
            args = {"query": arg_text} if arg_text else {}

        result = _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool, "arguments": args},
            },
        )
        print(json.dumps(result, indent=2))
        return 0 if "result" in result else 1
    finally:
        proc.stdin.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
