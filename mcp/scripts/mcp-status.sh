#!/usr/bin/env bash
# mcp-status.sh
# Quick health and index status check for the containerized MCP gateway.

set -euo pipefail

GATEWAY_URL="${MCP_GATEWAY_URL:-http://127.0.0.1:9747}"

echo "=== MCP Gateway Health ==="
if curl -fsS "${GATEWAY_URL}/health" | python3 -m json.tool; then
    echo ""
else
    echo "Gateway health check failed. Is 'docker compose -f mcp-compose.yml up -d' running?"
    exit 1
fi

echo "=== codebase-memory-mcp Indexes ==="
echo "NOTE: cbm can index code directories, but research/ contains large JSON/JSONL/CSV files that exceed the worker memory budget, so the tree is split into per-directory projects."
curl -fsS "${GATEWAY_URL}/mcp/cbm" -X POST \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_projects"}}' | python3 -m json.tool || true

echo ""
echo "=== GitNexus Index ==="
curl -fsS "${GATEWAY_URL}/mcp/gitnexus" -X POST \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_repos"}}' | python3 -m json.tool || true
