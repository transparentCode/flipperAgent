# flipperAgent Agent Policy

## Source of Truth

This root file is the repository-wide policy. Agent definitions for Codex live in
`.codex/agents/*.toml`; nested files are only for genuinely narrower directory rules.

The default user-facing role is the root `Quant Orchestrator`.

## Three-Role Architecture

- `Quant Orchestrator` (root session): intake, routing, handoff persistence,
  independent review, remediation decisions, final approval, and integration.
- `quant-architect`: research, external evidence, experiment design, architecture,
  tradeoffs, contracts, and coder-ready implementation scope. Read-only. Returns
  contracts to the orchestrator; does not persist durable handoffs.
- `quant-coder`: non-trivial and bounded implementation, tests, validation,
  self-review, and execution evidence. Workspace write.

Removed roles are intentionally absorbed:

- research -> architect
- bounded/mechanical worker -> coder
- review and approval -> orchestrator

Default flow: `orchestrator -> architect -> coder -> orchestrator`.

Skip architect only when the request already defines scope, non-goals, acceptance
criteria, and validation. Route architectural ambiguity back to architect. Route
bounded implementation defects back to coder, then independently re-review in the
orchestrator.

## Delegation and Parallelism

- Do not spawn a subagent for trivial work.
- Keep at most one architect and one coder task active for one outcome.
- Use only one workspace-writing agent per checkout.
- Parallel writers require separate Git worktrees, separate branches,
  non-overlapping scope, and separate mutable runtime resources.
- The orchestrator validates every return against its delegation before routing.
- Agents do not merge, cherry-pick, switch branches, or commit unless the user or
  orchestrator explicitly requests it.

Workspace-writing delegation requires a durable `plans/architect-to-coder-*.md`
handoff. Read-only architect work may use a complete inline delegation. Every
delegation includes objective, scope, non-goals, acceptance criteria, validation,
and expected output.

## Context and Memory

- Verify repository facts from the live checkout; do not rely on remembered paths,
  topology, parameters, benchmarks, or prior results.
- Retrieve memory only when prior decisions materially affect non-trivial work.
- Memory is optional: continue from code, docs, and explicit user context if it is
  unavailable. Do not save routine output. Persist only durable decisions when the
  user explicitly asks or the active memory policy requires it.
- Ask a focused question only when an undiscoverable choice would materially alter
  the result.

## Code Intelligence

This repository is indexed by `codebase-memory-mcp` (MIT) and `gitnexus`
(PolyForm Noncommercial) through a containerized `mcp-proxy`.

- Start the proxy before agent work that needs code intelligence:
  `docker compose -f mcp-compose.yml up -d`
- Stop it when done: `docker compose -f mcp-compose.yml down`
- Check status: `./mcp/scripts/mcp-status.sh`
- Re-index after meaningful changes: `./mcp/scripts/mcp-index.sh`

### Tiered usage

Follow `.agents/skills/mcp-tiered-code-intelligence/SKILL.md`.

- Start with `codebase-memory-mcp` for code discovery, symbol lookup, semantic
  search, and paths inside `src/`, `tests/`, `conductor/`, `scripts/`, `docs/`,
  and `plans/`.
- Escalate to `gitnexus` only for whole-repo structural queries, cross-directory
  flows, impact analysis, or files outside cbm's indexed directories (e.g.
  `research/`).
- Prefer `codebase-memory-mcp` for commercial use because it is MIT-licensed.

For code discovery, prefer `search_graph`, `trace_path`, `get_code_snippet`,
`query_graph`, then `get_architecture`. Before editing an existing symbol, inspect
callers, callees, and affected flows. Use text search for config, docs, literals,
generated files, or when graph results are insufficient. Before handoff, inspect the
final diff and use change-impact analysis when shared code or contracts changed.
Surface HIGH or CRITICAL impact before making a risky change.

## Engineering and Quant Safety

- Python environment: `.venv/bin/python`.
- Dependency source of truth: `pyproject.toml`.
- Production packages live under `src/apps/`, `src/libs/`, and `conductor/`.
- Tests live under `tests/`; use focused pytest first, then broader validation in
  proportion to risk. Run Ruff for Python changes.
- Keep changes minimal and preserve public contracts unless explicitly changed.
- Never invent parameters, schemas, lifecycle states, data availability, or
  acceptance criteria.
- Preserve point-in-time correctness, deterministic behavior, timezone/calendar
  semantics, symbol identity, transaction-cost assumptions, and protected evidence.
- Never hide look-ahead bias, leakage, survivorship bias, configuration drift, or
  execution-timing changes.

## Handoffs

Durable handoffs are owned by the `quant-orchestrator`. See
`.agents/skills/quant-orchestrator/SKILL.md` and
`.agents/skills/quant-orchestrator/references/stage-templates.md` for the format
and stage templates. Active stages are:

- `orchestrator-to-architect`
- `architect-to-coder`
- `coder-to-orchestrator`
- `orchestrator-decision`

Historical files in `plans/` may use older stage names; do not rewrite them merely
to match the current architecture.
