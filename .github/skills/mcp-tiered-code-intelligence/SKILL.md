---
name: mcp-tiered-code-intelligence
description: 'Choose between codebase-memory-mcp and gitnexus for code intelligence based on query scope, license, and repo coverage.'
user-invocable: true
---

# MCP Tiered Code Intelligence

Canonical skill: `.agents/skills/mcp-tiered-code-intelligence/SKILL.md`.

Two MCP backends are exposed by the containerized `mcp-proxy` on
`http://localhost:9748/servers/{backend}/mcp` (Streamable HTTP):

- `cbm` → `codebase-memory-mcp` (MIT): primary semantic code intelligence.
- `gitnexus` → `gitnexus` (PolyForm Noncommercial): full-repository structural graph.

Legacy SSE endpoints (`/servers/{backend}/sse`) are also available but are not
used by the Codex CLI or VS Code MCP clients. Both clients use Streamable HTTP.

## When to use codebase-memory-mcp

- Default for code discovery, symbol lookup, and semantic search.
- Reading specific code snippets or tracing paths inside `src/`, `tests/`, `scripts/`, `docs/`, or `plans/`.
- Architecture overview, hotspots, cluster detection.
- Cross-impact inside a single project or a few known files.

## When to use gitnexus

- Whole-repo structural queries that span code, configs, research artifacts, and docs.
- Cross-directory or cross-service execution flows.
- Impact analysis, dead-code detection, route maps, cross-repo links.
- When `codebase-memory-mcp` cannot cover files in `research/` or other unindexed directories.

## Rules

1. Start with `codebase-memory-mcp` for all code questions.
2. Escalate to `gitnexus` only when the query needs full-repo graph coverage or `research/` artifacts.
3. Prefer `codebase-memory-mcp` for commercial use because it is MIT-licensed.
4. Keep indexes current: run `./mcp/scripts/mcp-index.sh` after meaningful changes.
5. Check status with `./mcp/scripts/mcp-status.sh` before heavy analysis.
