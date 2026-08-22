---
name: mcp-tiered-code-intelligence
description: Choose between codebase-memory-mcp and gitnexus for code intelligence based on query scope, license, and repo coverage.
---

# Tiered Code Intelligence

Two independent per-server Streamable HTTP adapters are available:

- `codebase-memory-mcp` at `http://localhost:9748/mcp` (MIT): default semantic
  discovery and project-scoped call-graph evidence.
- `gitnexus` at `http://localhost:9750/mcp` (PolyForm Noncommercial): optional
  whole-repository structural, PDG, and cross-directory evidence.

There is no central `mcp-proxy`. The raw stdio backends are private inside their
own containers. Each adapter uses an explicit allowlist with default-deny behavior:
`tools/list` exposes only approved tools and every other `tools/call` receives
`FORBIDDEN_BY_POLICY`. Never register or reach around the raw backends as another
MCP server.

## Live Contract

The observed server/build/tool contract is recorded in
`docs/agents/mcp-tool-contract.toml`. When MCP configuration or adapter behavior
changes, run the optional live contract check:

```bash
python3 scripts/verify_agent_policy.py --live
```

Ordinary tests must not require the MCP containers. A live mismatch is a
configuration/operations finding, not evidence that a graph is empty.

## Tiering

Start with CBM for all code questions:

- `list_projects`, then use the returned project identifier on project-scoped calls;
- `search_graph`, `search_code`, `get_code_snippet`, and `get_architecture` for
  discovery;
- `trace_path` for callers/callees, with `direction` set to `inbound`,
  `outbound`, or `both`;
- `query_graph` for a bounded custom graph query;
- `detect_changes` and `index_status` for freshness/scope evidence.

All project-scoped CBM requests must include the live `project` parameter. Do not
copy old examples that omit it or use an unrelated absolute checkout path.

Escalate to GitNexus only when the question genuinely requires whole-repository or
unindexed coverage, cross-directory/service flow, PDG/taint-style reasoning, route
maps, or advanced structural impact. Use `list_repos` first and follow the live
schema for `query`, `cypher`, `context`, `impact`, `trace`, and related tools. The
actual server names are short names such as `context`, `impact`, and `trace`; do
not invent `mcp_gitnexus_*` names from client-generated documentation.

## Exposed Agent Surface

CBM read-only tools:

`list_projects`, `index_status`, `search_graph`, `search_code`, `trace_path`,
`get_code_snippet`, `query_graph`, `get_graph_schema`, `get_architecture`,
`detect_changes`

CBM known operator-only tools, denied to agents by the adapter:

`index_repository`, `delete_project`, `manage_adr`, `ingest_traces`

GitNexus read-only tools:

`list_repos`, `query`, `cypher`, `context`, `detect_changes`, `check`, `impact`,
`explain`, `pdg_query`, `route_map`, `tool_map`, `shape_check`, `api_impact`,
`group_list`, `trace`

GitNexus known operator-only tools, denied to agents by the adapter:

`rename`, `group_sync`

These lists are explicit allowlists, not exhaustive deny-lists: unknown/new tools
from a future backend release are denied by default until the observed contract and
role configuration are deliberately reviewed.

`quant-coder` receives CBM only by default. GitNexus requires explicit,
task-scoped orchestrator enablement; it is not a routine coder dependency.

## Evidence Discipline

Use the following coverage levels:

- **Scout:** quick positive lookup. It cannot support absence, completeness, or
  dead-code claims.
- **Verify:** default for decisions. Confirm relevant paths and source snippets,
  account for pagination and index freshness, and cross-check with source text.
- **Auditor:** bounded exhaustive review. State the scope, index generation,
  skipped/excluded files, pagination, and direct-source fallback before making a
  negative claim.

Graph results accelerate navigation; source code, tests, and explicit runtime
evidence remain authoritative. A missing/stale/partial graph result means
`not found in this query`, never `does not exist`.

For detailed CBM schemas, query patterns, and role-specific workflows, read
`references/cbm-guide.md`. The older CBM workflow skill paths are compatibility
stubs, not separate policy sources.

## Maintenance and Safety

- Check status with `../mcp/scripts/mcp-status.sh` before heavy analysis.
- Do not index, delete projects, mutate ADRs, ingest traces, rename symbols, or
  synchronize groups from an agent session.
- Indexing is an operator action and must be explicitly authorized:
  `MCP_ALLOW_INDEX=1 ../mcp/scripts/mcp-index.sh`.
- After edits, inspect the diff and use `detect_changes` when available; do not
  make routine CI depend on a live MCP service.
