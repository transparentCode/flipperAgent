# flipperAgent Codex Router

## Default Entry
- Preferred front door: `quant-orchestrator` skill.
- Treat specialist skills as internal stages unless user explicitly asks for a specific stage.

## Token Discipline (Always On)
- Keep responses concise by default.
- Ask at most one clarification question unless blocked.
- Do not restate static policies or long checklists in normal responses.
- Load skill `references/` files only when needed for the current task.
- Prefer fixed output schemas over long prose.

## Stage Routing
- Use `quant-orchestrator` for intake and routing.
- Use `quant-architect-handoff` for research/architecture and coder-ready scope.
- Use `quant-coder-execution` for implementation tasks.
- Use `quant-review-gate` for implementation review and risk findings.
- Use `quant-approval-gate` for final sign-off decisions.
- Use `quant-write-handoff` to persist stage packages into `plans/`.

## Memory + MCP
- Retrieve prior context from `memoir` at task start when it reduces risk.
- Save major decisions and outcomes back to `memoir` at task end.
- Keep MCP servers in `.vscode/mcp.json` as the integration source of truth.

## Code Safety
- For code edits on existing symbols, run GitNexus impact analysis before modification.
- Surface HIGH/CRITICAL impact explicitly before proceeding.
