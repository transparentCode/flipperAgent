#!/usr/bin/env bash
# mcp-index.sh
# Re-index the flipperAgent repo for both containerized MCP backends.
# Run while the mcp-proxy container is up:
#   docker compose -f mcp-compose.yml up -d
#   ./mcp/scripts/mcp-index.sh
#
# NOTE: codebase-memory-mcp can index the code directories in this repo, but the
# research/ directory contains large JSON/JSONL/CSV files that exceed the worker's
# per-process memory budget (~1 GB in this Docker setup). cbm does not support
# directory excludes, so the tree is split into per-directory projects. GitNexus
# indexes the whole repo into .gitnexus/ without this memory issue.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

index_cbm_dir() {
  local path="$1"
  local name="$2"
  echo "=== codebase-memory-mcp: indexing ${path#/workspace/} as ${name} ==="
  "${SCRIPT_DIR}/mcp-stdio-call.py" "codebase-memory-mcp" "index_repository" \
    --args "{\"repo_path\":\"${path}\",\"name\":\"${name}\",\"mode\":\"fast\"}"
  echo ""
}

index_cbm_dir "/workspace/src"          "flipperAgent-src"
index_cbm_dir "/workspace/tests"        "flipperAgent-tests"
index_cbm_dir "/workspace/conductor"     "flipperAgent-conductor"
index_cbm_dir "/workspace/scripts"       "flipperAgent-scripts"
index_cbm_dir "/workspace/docs"           "flipperAgent-docs"
index_cbm_dir "/workspace/plans"         "flipperAgent-plans"

echo "=== GitNexus: indexing whole repo ==="
docker compose -f mcp-compose.yml exec -T mcp-proxy /bin/bash -c \
  'cd /app/gitnexus && HOME=/data/gitnexus node dist/cli/index.js analyze --index-only /workspace' \
  | tail -20

echo ""
echo "=== Status ==="
"${SCRIPT_DIR}/mcp-status.sh"
