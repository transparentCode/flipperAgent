---
name: codebase-memory-cli
description: Use read-only HTTP helpers for missing MCP discovery/status tools, or container CLIs for explicitly authorized indexing.
---

# Codebase Memory — CLI

## Runtime

The backend runs privately inside the external per-server container project at
`../mcp`. Use the adapter scripts from the repository root; do not install or run a
second raw backend locally.
The historically named `mcp-stdio-call.py` uses HTTP and cannot index through the
read-only adapter. For query schemas, role routing, and component selection, follow
the canonical `mcp-tiered-code-intelligence` skill.

## Common Commands

```bash
# Check both adapter and backend health
../mcp/scripts/mcp-status.sh

# List indexed projects
../mcp/scripts/mcp-stdio-call.py cbm list_projects

# Example only: substitute the identifier returned by discovery for your scope.
../mcp/scripts/mcp-stdio-call.py cbm index_status --args '{"project":"flipperAgent-apps"}'

# Search symbols
../mcp/scripts/mcp-stdio-call.py cbm search_graph --args '{"project":"flipperAgent-apps","name_pattern":".*Handler.*","label":"Function"}'

# Trace call chain
../mcp/scripts/mcp-stdio-call.py cbm trace_path --args '{"project":"flipperAgent-apps","function_name":"X","direction":"both"}'

# Run a Cypher-like query
../mcp/scripts/mcp-stdio-call.py cbm query_graph --args '{"project":"flipperAgent-apps","query":"MATCH (f:Function) RETURN f.name LIMIT 5"}'

# Detect changes vs git HEAD
../mcp/scripts/mcp-stdio-call.py cbm detect_changes --args '{"project":"flipperAgent-apps"}'
```

## Keeping the Index Fresh

Indexing is operator-only and deliberately opt-in. After reviewing the mounted
checkout and tool arguments, an operator may run:

```bash
../mcp/scripts/mcp-index.sh --dry-run
MCP_ALLOW_INDEX=1 ../mcp/scripts/mcp-index.sh
# To maintain one service only:
MCP_ALLOW_INDEX=1 ../mcp/scripts/mcp-index.sh --service cbm
```

The environment gate records opt-in, not authorization by itself. The script
validates mounts and uses the operator CLIs inside existing containers. CBM indexes
apps, individual libraries/models, tests, scripts, and configs sequentially in fast
mode. It stops on a failed scope; do not retry an OOM scope repeatedly or raise caps.
Use smaller scopes within the authorized task or report incomplete coverage.

GitNexus uses index-only mode with two parse workers and the `flipperAgent` alias.
It updates the generated `.gitnexus` index and registry but skips AI instruction
injection. Use `--force-gitnexus` only after explicitly deciding to rebuild generated
data following an incompatible/failed index; force is never automatic in the script.
Indexing does not install FTS or enable embeddings/PDG, restart containers, or alter
adapter permissions. Verify catalogs and representative queries over MCP afterward;
report exclusions, unavailable capabilities, and dirty-working-tree provenance.

Agents must not run indexing as a routine post-change action. If results look
stale, report the freshness evidence and fall back to direct source inspection.
