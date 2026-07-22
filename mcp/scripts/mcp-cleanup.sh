#!/usr/bin/env bash
# mcp-cleanup.sh
# Emergency cleanup for MCP. The repo now uses only the containerized mcp-proxy,
# so the primary cleanup is `docker compose -f mcp-compose.yml down`. This script
# also kills any legacy local stdio processes that may remain from old setups.

set -euo pipefail

# Defensive: kill any legacy local stdio MCP processes.
PIDS=$(pgrep -f "codebase-memory-mcp|gitnexus mcp" || true)
if [ -n "$PIDS" ]; then
    echo "Killing legacy local stdio MCP processes:"
    ps -p $(echo "$PIDS" | tr '\n' ',' | sed 's/,$//') -o pid,command || true
    echo "$PIDS" | xargs -r kill -9
    echo ""
fi

# Stop the containerized proxy if it is running.
if docker compose -f mcp-compose.yml ps -q 2>/dev/null | grep -q .; then
    echo "Stopping mcp-proxy container..."
    docker compose -f mcp-compose.yml down
else
    echo "No mcp-proxy container running."
fi

echo "MCP cleanup complete."
