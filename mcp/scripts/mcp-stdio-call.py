#!/usr/bin/env python3
"""Call a single tool on a backend exposed by the mcp-proxy container.

Maps legacy stdio command names ('codebase-memory-mcp', 'gitnexus mcp') to the
named HTTP/SSE endpoints and pretty-prints the tool result."""

import argparse
import json
import queue
import threading
import urllib.parse
import urllib.request
import uuid
import sys

PROXY_URL = "http://127.0.0.1:9748"

SERVER_MAP = {
    "codebase-memory-mcp": "cbm",
    "gitnexus mcp": "gitnexus",
    "gitnexus": "gitnexus",
    "caveman-shrink": "caveman-shrink",
    "gitnexus-shrink": "gitnexus-shrink",
}


def _backend(server_cmd: str) -> str:
    server = server_cmd.strip()
    if server in SERVER_MAP:
        return SERVER_MAP[server]
    # Also accept already-mapped names.
    if server in ("cbm", "gitnexus", "caveman-shrink", "gitnexus-shrink"):
        return server
    raise ValueError(f"Unknown server command: {server_cmd!r}")


def _post(base: str, session_id: str, payload: dict) -> tuple[int, str]:
    url = f"{base}/messages/?session_id={session_id}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.status, resp.read().decode()


def _rpc(base: str, session_id: str, payload: dict, q: queue.Queue) -> dict:
    status, body = _post(base, session_id, payload)
    if status == 202:
        while True:
            kind, val = q.get(timeout=60)
            if kind == "data":
                return json.loads(val)
    return json.loads(body)


def _sse_reader(base: str, q: queue.Queue) -> None:
    req = urllib.request.Request(f"{base}/sse", method="GET", headers={"Accept": "text/event-stream"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        while True:
            line = resp.readline()
            if not line:
                break
            line = line.decode().strip()
            if not line:
                continue
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
                data_line = resp.readline().decode().strip()
                data = data_line[len("data:"):].strip() if data_line.startswith("data:") else ""
                if event == "endpoint":
                    parsed = urllib.parse.urlparse(data)
                    sid = urllib.parse.parse_qs(parsed.query).get("session_id", [None])[0]
                    q.put(("session", sid))
                else:
                    q.put(("data", data))


def call_tool(backend: str, tool: str, tool_args: dict) -> dict:
    base = f"{PROXY_URL}/servers/{backend}"
    q: queue.Queue = queue.Queue()
    t = threading.Thread(target=_sse_reader, args=(base, q), daemon=True)
    t.start()
    session_id = q.get(timeout=30)[1]

    init = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mcp-stdio-call", "version": "1.0"},
        },
    }
    _rpc(base, session_id, init, q)
    # Notifications have no response; send them without waiting on the SSE queue.
    _post(base, session_id, {"jsonrpc": "2.0", "method": "notifications/initialized"})

    req = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tools/call",
        "params": {"name": tool, "arguments": tool_args},
    }
    return _rpc(base, session_id, req, q)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Call one tool on a backend exposed by the mcp-proxy container."
    )
    parser.add_argument("server", help="Backend name or stdio command (e.g. 'codebase-memory-mcp' or 'gitnexus mcp')")
    parser.add_argument("tool", help="Tool name to call")
    parser.add_argument("--args", default="{}", help="JSON object of tool arguments")
    args = parser.parse_args()

    try:
        tool_args = json.loads(args.args)
        backend = _backend(args.server)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid input: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        result = call_tool(backend, args.tool, tool_args)
    except Exception as exc:
        print(f"Tool call failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if "error" in result:
        print(json.dumps(result["error"], indent=2))
        sys.exit(1)

    content = result.get("result", {}).get("content", [])
    for item in content:
        if item.get("type") == "text":
            text = item.get("text", "")
            try:
                data = json.loads(text)
                print(json.dumps(data, indent=2))
            except json.JSONDecodeError:
                print(text)
            return

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
