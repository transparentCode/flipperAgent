---
name: quant-memory
description: Use the mem0-local MCP server for durable, scoped memory across flipperAgent sessions. Only the quant-orchestrator should manage memory; architect and coder are consumers only.
---

# Quant Memory

## Ownership

This skill is owned by `quant-orchestrator`. The orchestrator may use memory to:

- recall durable user preferences, project conventions, and non-goals;
- reuse validated architecture decisions and accepted risks from prior sessions;
- disambiguate intake when the current request lacks context.

`quant-architect` and `quant-coder` are **consumers only** when the orchestrator
explicitly includes relevant memory in their handoff. They do not call `add_memory`,
`update_memory`, or `delete_memory` directly.

## MCP server

The `mem0-local` MCP server is configured in:

- `.vscode/mcp.json` under `servers.mem0-local`
- `.codex/config.toml` under `[mcp_servers.mem0-local]`

URL: `http://localhost:8889/mcp`

## Available tools

| Tool | Use when | Who |
|------|----------|-----|
| `add_memory` | A durable fact, preference, decision, or risk needs to survive this session. | orchestrator only |
| `search_memories` | The current task may depend on a prior decision or user preference. | orchestrator, rarely delegated |
| `get_memories` | A specific list of known memories is needed, e.g. for a checkpoint. | orchestrator only |
| `get_memory` | A known memory ID must be verified or updated. | orchestrator only |
| `update_memory` | A prior memory is stale or wrong. | orchestrator only |
| `delete_memory` | A specific memory is obsolete or harmful. | orchestrator only |
| `delete_all_memories` | Scoped purge is required (e.g., project reset). | orchestrator only, with user confirmation |
| `list_entities` | Inspecting memory ownership / scoping. | orchestrator only |
| `delete_entities` | Removing an entity and all its memories. | orchestrator only, with user confirmation |

## Scoping rules

Always scope memory operations to prevent cross-pollution and token bloat:

```
user_id : the human user (do not invent; use the current session user)
app_id  : flipperAgent
agent_id: quant-orchestrator
run_id  : per-session or per-delegation task, used only when isolation is needed
```

- Use `user_id` + `app_id` for project-wide durable facts.
- Use `agent_id` for orchestrator-specific conventions.
- Use `run_id` only for transient task-specific notes that should not leak into the
  global project memory.
- Never use `agent_id: quant-architect` or `agent_id: quant-coder` from the orchestrator;
  those agents do not own durable memory.

## What to save

Save only information that is **durable, validated, and likely to be reused**:

- User preferences (e.g., preferred model risk tolerance, style of reports).
- Project conventions (e.g., "always keep tests under `tests/`", "use Ruff for linting").
- Architecture decisions that recur (e.g., "ingestion adapters are the boundary for
  exchange-specific logic").
- Accepted risks and non-goals from prior handoffs.
- High-level blast-radius conclusions about shared modules.

## What NOT to save

Do not use memory as a log or cache:

- Raw code, full diffs, or file contents.
- Transient tool outputs, terminal logs, or stack traces.
- Per-task implementation details that belong in a `plans/` handoff file.
- Unverified assumptions or speculated facts.
- Anything that can be cheaply recomputed from the live checkout.

## Retrieval discipline

Memory is a retrieval layer, not a prompt dump. Follow these rules:

1. **Search only when needed.** Before a search, ask: "Is this decision missing from the
   request, handoff, or live checkout?"
2. **Use `search_memories` with a clear query and a low `limit` (default 3–5).** Add
   `app_id` and `user_id` filters.
3. **Never inject all memories.** Token-budget memory context. If the model needs a
   memory, prefer a single concise fact over a list.
4. **Verify before acting.** A retrieved memory may be stale. Cross-check against the
   live checkout, the current handoff, or the user before using it to route or decide.
5. **Prefer handoffs for task state.** `plans/` files remain the source of truth for
   active architect/coder contracts. Memory is only for cross-session context.

## Suggested flow

### On session start

```
if user asks about a recurring topic or prior decision:
    search_memories(
        query="relevant topic",
        filters={"AND": [{"user_id": "<user>"}, {"app_id": "flipperAgent"}]},
        limit=5
    )
```

### On durable decision

```
add_memory(
    messages=[{"role": "user", "content": "Durable decision: <concise fact>"}],
    user_id="<user>",
    app_id="flipperAgent",
    agent_id="quant-orchestrator",
    metadata={"topic": "architecture", "source": "handoff", "verified": true}
)
```

### On ambiguity

1. Search memory for a prior related decision.
2. If found, verify it is still current against the live checkout.
3. If not found or stale, ask the user or route to `quant-architect`.

## Anti-patterns

- **Memory loop:** repeatedly saving and retrieving the same fact instead of acting on it.
- **Context dump:** passing a large `get_memories` result into every downstream prompt.
- **Unscoped writes:** missing `user_id` or `app_id`, causing memory leakage.
- **Staleness blindness:** treating a retrieved memory as ground truth without verification.
- **Over-saving:** writing every intermediate thought to memory.

## Error handling

- If `mem0-local` is unreachable, continue without memory. Do not block the task.
- If memory retrieval returns ambiguous results, prefer asking the user over guessing.
- If a saved memory contradicts the current handoff or user instruction, the current
  instruction wins; update or delete the stale memory.
