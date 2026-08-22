---
name: codebase-memory-cli
description: Use the codebase-memory-mcp CLI for indexing, status checks, and maintenance. Use when the MCP tools are unavailable or when running batch operations.
---

# Codebase Memory — CLI

## Runtime

The backend runs privately inside the external per-server container project at
`../mcp`. Use the adapter scripts from the repository root; do not install or run a
second raw backend locally.

## Common Commands

```bash
# Check both adapter and backend health
../mcp/scripts/mcp-status.sh

# Check indexing status
../mcp/scripts/mcp-stdio-call.py cbm index_status --args '{"project":"flipperAgent"}'

# List indexed projects
../mcp/scripts/mcp-stdio-call.py cbm list_projects

# Search symbols
../mcp/scripts/mcp-stdio-call.py cbm search_graph --args '{"project":"flipperAgent","name_pattern":".*Handler.*","label":"Function"}'

# Trace call chain
../mcp/scripts/mcp-stdio-call.py cbm trace_path --args '{"project":"flipperAgent","function_name":"X","direction":"both"}'

# Run a Cypher-like query
../mcp/scripts/mcp-stdio-call.py cbm query_graph --args '{"project":"flipperAgent","query":"MATCH (f:Function) RETURN f.name LIMIT 5"}'

# Detect changes vs git HEAD
../mcp/scripts/mcp-stdio-call.py cbm detect_changes --args '{"project":"flipperAgent"}'
```

## Keeping the Index Fresh

Indexing is operator-only and deliberately opt-in. After reviewing the mounted
checkout and tool arguments, an operator may run:

```bash
MCP_ALLOW_INDEX=1 ../mcp/scripts/mcp-index.sh
```

Agents must not run indexing as a routine post-change action. If results look
stale, report the freshness evidence and fall back to direct source inspection.
