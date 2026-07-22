#!/usr/bin/env bash
# mcp-status.sh
# Quick health and index status check for the containerized MCP proxy.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROXY_URL="${MCP_PROXY_URL:-http://127.0.0.1:9748}"

echo "=== MCP Proxy Status ==="
if curl -fsS "${PROXY_URL}/status" | python3 -m json.tool; then
    echo ""
else
    echo "Proxy status check failed. Is 'docker compose -f mcp-compose.yml up -d' running?"
    exit 1
fi

echo "=== codebase-memory-mcp Indexes ==="
echo "NOTE: cbm can index code directories, but research/ contains large JSON/JSONL/CSV files"
echo "that exceed the worker memory budget, so the tree is split into per-directory projects."
"${SCRIPT_DIR}/mcp-stdio-call.py" "codebase-memory-mcp" "list_projects"

echo ""
echo "=== GitNexus Index ==="
"${SCRIPT_DIR}/mcp-stdio-call.py" "gitnexus mcp" "list_repos"
