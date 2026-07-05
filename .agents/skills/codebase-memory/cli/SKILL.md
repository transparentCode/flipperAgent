---
name: codebase-memory-cli
description: Use the codebase-memory-mcp CLI for indexing, status checks, and maintenance. Use when the MCP tools are unavailable or when running batch operations.
user-invocable: true
---

# Codebase Memory — CLI

## Installation
The `codebase-memory-mcp` binary should be on your PATH. If not, install it from [DeusData/codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp).

## Common Commands

```bash
# Index the current repo
codebase-memory-mcp cli index_repository '{"repo_path": "/Users/aloobhujia/flipperAgent"}'

# Check indexing status
codebase-memory-mcp cli index_status '{"project": "flipperAgent"}'

# List indexed projects
codebase-memory-mcp cli list_projects

# Search symbols
codebase-memory-mcp cli search_graph '{"name_pattern": ".*Handler.*", "label": "Function"}'

# Trace call chain
codebase-memory-mcp cli trace_path '{"function_name": "X", "direction": "both"}'

# Run a Cypher-like query
codebase-memory-mcp cli query_graph '{"query": "MATCH (f:Function) RETURN f.name LIMIT 5"}'

# Detect changes vs git HEAD
codebase-memory-mcp cli detect_changes
```

## Keeping the Index Fresh
- Re-index after large refactors: `codebase-memory-mcp cli index_repository ...`
- The background watcher auto-syncs smaller changes.
- If queries return stale results, run `index_repository` explicitly.
