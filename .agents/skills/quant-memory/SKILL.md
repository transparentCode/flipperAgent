---
name: quant-memory
description: Use the local Hindsight MCP memory layer for durable, scoped flipperAgent context. Only quant-orchestrator manages memory; architect and coder receive selected context through handoffs.
---

# Quant Memory

## Ownership

This skill is owned by `quant-orchestrator`. The orchestrator may use Hindsight to:

- recall durable user preferences, project conventions, and non-goals;
- reuse validated architecture decisions and accepted risks from prior sessions;
- disambiguate intake when the current request lacks context;
- retain concise, verified decisions after significant work.

`quant-architect` and `quant-coder` are consumers only. They do not call Hindsight
directly; the orchestrator includes relevant context in their handoff when needed.

## MCP server

Hindsight is the only active durable-memory MCP server for this repository:

- Codex: `.codex/config.toml` under `[mcp_servers.hindsight]`
- VS Code: `.vscode/mcp.json` under `servers.hindsight`
- URL: `http://localhost:8888/mcp`

Do not use a legacy or unregistered memory service. Hindsight is a native
Streamable HTTP endpoint; no central MCP proxy is required.

## Bank and scope

Use the dedicated project bank:

```text
bank_id: flipperagent-main
```

Do not use `test-bank` or another application's bank. Hindsight bank isolation is
the primary scope boundary. Add concise tags when useful, for example:
`project:flipperAgent`, `agent:quant-orchestrator`, and `kind:decision`.

Create or verify `flipperagent-main` before the first durable write. Do not create
additional banks for individual tasks unless the user explicitly requests isolation.

## Default tools

The Codex configuration exposes only these tools:

| Tool | Use when |
|------|----------|
| `list_banks` | Verify available banks during setup or migration. |
| `get_bank` | Verify the project bank and its mission. |
| `get_bank_stats` | Inspect bounded memory health or counts. |
| `create_bank` | Idempotently initialize `flipperagent-main`. |
| `sync_retain` | Store a concise durable fact and wait until it is available. |
| `recall` | Retrieve relevant facts for the current task. |
| `reflect` | Synthesize an answer across memories for a complex question. |
| `list_memories` | Browse or verify stored facts with a bounded limit. |
| `get_memory` | Inspect one known memory during verification. |

Prefer `sync_retain` over asynchronous `retain` when the next step depends on the
fact being immediately available. Use a low recall/reflect budget first and increase
it only when the result is insufficient.

Destructive or maintenance tools—including `delete_bank`, `clear_memories`,
`delete_document`, `delete_mental_model`, `delete_directive`, `update_memory`, and
`invalidate_memory`—are not part of the default agent surface. Do not enable or use
them without explicit user authorization and a separately reviewed task scope.

## What to save

Save only durable, validated information likely to be reused:

- user preferences and stable working conventions;
- accepted architecture decisions, non-goals, and risks;
- high-level blast-radius conclusions;
- concise lessons that will change future routing or review.

Do not save raw code, full diffs, logs, transient tool output, current conversation
context, trivial operations, unverified assumptions, or task state that belongs in a
`plans/` handoff.

## Retrieval discipline

1. Search only when the current request, handoff, or live checkout does not contain
   the needed context and the prior decision materially affects the result.
2. Call `recall` with a focused query, `bank_id="flipperagent-main"`, and a bounded
   budget. Use relevant tags when the memory was tagged.
3. For complex multi-session projects, call `reflect` with a focused question rather
   than dumping all memories into the prompt.
4. Verify retrieved memories against the live checkout, current handoff, or user
   instruction before relying on them. Current user instructions win.
5. Keep memory context concise when delegating; the handoff remains authoritative for
   active task scope and implementation state.

## Suggested flow

### Before a non-trivial task

```text
recall(
    bank_id="flipperagent-main",
    query="<task and the specific prior decision needed>",
    budget="low",
    tags=["project:flipperAgent"],
)
```

For a genuinely complex multi-session project, use `reflect` with the question
`What durable context should inform this task?` and verify the answer before acting.

### After significant work

```text
sync_retain(
    bank_id="flipperagent-main",
    content="Durable decision: <concise verified result>",
    context="project decision",
    tags=["project:flipperAgent", "agent:quant-orchestrator", "kind:decision"],
    metadata={"source": "orchestrator", "verified": "true"},
)
```

Retain the result only after validation and only if it will affect future work.

## Failure handling

If Hindsight is unavailable, continue without memory and report the missing context
only when it materially affects the task. Never invent a memory result, block routine
work, or silently substitute an unregistered memory provider.
