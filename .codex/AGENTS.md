# flipperAgent Codex Router

## Default Entry
- Preferred front door: `quant-orchestrator`.
- Use `quant-architect` for architecture-specific requests.
- Use `quant-research` for research-specific requests.
- Use `quant-write-handoff` only when a durable `plans/` document is requested.

## Token Discipline (Always On)
- Keep responses concise by default.
- Ask at most one clarification question unless blocked.
- Do not restate static policy text.
- Load skill `references/` only when needed.

## Memory + MCP
- Retrieve prior context from `memoir` when it reduces risk.
- Save major decisions or outcomes back to `memoir` at task end.
- Keep MCP server definitions in `.vscode/mcp.json` as source of truth.

## Code Safety
- For code edits on existing symbols, run GitNexus impact before modification.
- Surface HIGH/CRITICAL impact before proceeding.
