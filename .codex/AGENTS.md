# flipperAgent - AI Agent Guidelines

## Overview
These are the foundational instructions for any AI assistant working on the `flipperAgent` project.

## Start Here
- Preferred user-facing entry point: `Quant Orchestrator`.
- Treat the specialized quant agents as internal workflow stages coordinated by the orchestrator unless the user explicitly asks to work with a specific specialist.

## Development Environment
- **Ecosystem:** Python.
- **Environment:** The project uses a local virtual environment located in `.venv/`. Agents should activate this environment or use the Python executable within `.venv/bin/python` when running commands or tests.

## Coding Conventions & Workflow
- Maintain modular design by placing core logic in a dedicated module (e.g., `src/` or `flipper_agent/`).
- Make sure to update a `requirements.txt`, `pyproject.toml`, or `Pipfile` when adding dependencies.
- Use `pytest` (or the preferred testing framework) and keep tests easily runnable in a `tests/` folder.
- Follow general Python best practices and PEP 8 guidelines.
- **Link, don't embed:** Refer to [README.md](README.md) for project purpose and architectural overviews.
## Memory & Context Protocol (Applies to ALL Agents)
- **NO PREASSUMPTIONS OR SHORTCUTS:** You must not assume context. If a requirement, constraint, or fact is unclear, do not guess.
- Retrieve mem0 context for non-trivial research, architecture, implementation,
  review, and continuation tasks where prior decisions materially matter.
- Do not block trivial or self-contained work solely because memory is unavailable.
- Persist durable decisions, experiment outcomes, accepted risks, and completed
  phase state; do not save routine command output or transient observations.
- **BUILD CONTEXT WHEN UNCLEAR:** When prior memory is incomplete or ambiguous, ask the user a focused series of related questions to establish facts. State your current understanding and ask for confirmation or correction before proceeding.
- **FACT-CHECK BEFORE ACTING:** Validate assumptions against memory, the codebase, or explicit user input. If contradictions arise, surface them and ask the user to resolve.

## Subagent Lifecycle (Applies to ALL Agents)

### When to Invoke a Subagent
- Use a subagent when the task clearly maps to a specialist role:
  - `quant-research` → hypothesis/experiment design
  - `quant-architect` → architecture and tradeoffs
  - `quant-coder` → implementation against approved handoff
  - `quant-review` → safety and correctness review
  - `quant-approval` → final sign-off
- Do **not** spawn a subagent for trivial one-step tasks you can complete directly.

### Before Invoking
1. Retrieve prior context from `mem0`.
2. Produce a concise, stage-correct handoff package (see `quant-write-handoff` skill).
3. Include: objective, scope boundaries, explicit non-goals, acceptance criteria, and known risks.

### During Subagent Execution
- Do not spawn multiple subagents in parallel for the same task unless explicitly designed.
- Do not interrupt a subagent unless it is blocked or has asked for input.

### After Subagent Returns
1. Validate the output against the handoff's acceptance criteria.
2. Identify unresolved blockers or follow-ups.
3. Decide next action:
   - **Approve** → route to `quant-write-handoff` or next stage.
   - **Revise** → return to the same subagent with specific feedback.
   - **Escalate** → route to `quant-architect` if scope ambiguity is found.
4. Save the outcome to `mem0`.

### Anti-Patterns
- `quant-review → quant-coder` is allowed for bounded implementation remediation.
- Route to `quant-architect` only when review exposes architectural ambiguity,
  scope drift, missing design decisions, or conflicting acceptance criteria.
- After remediation, return to `quant-review` for independent re-review.
- Workspace-writing agents require a durable handoff under `plans/`.
- Read-only research, exploration, and review agents may receive a complete
  inline delegation package from the root orchestrator.
- Every delegation must include objective, scope, non-goals, acceptance
  criteria, and expected output.
- NEVER discard a subagent's findings without recording why.

<!-- codebase-memory:start -->
# Codebase Memory — Code Intelligence

This project is indexed by `codebase-memory-mcp`. Use the codebase-memory tools to understand code, assess impact, and navigate safely.

> If any codebase-memory tool warns the index is stale, run `codebase-memory-mcp cli index_repository '{"repo_path": "/Users/aloobhujia/flipperAgent"}'` in terminal first. The indexed project name is `Users-aloobhujia-flipperAgent`.

## Always Do

- **MUST use codebase-memory before editing any existing symbol.** Before modifying a function, class, or method, query the codebase graph to understand callers, callees, and affected execution paths.
- **MUST verify scope before committing** to confirm your changes only affect expected symbols and files.
- **MUST warn the user** if impact analysis reveals HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `search_graph` and `search_code` to find execution flows instead of relying solely on grep.
- When you need full context on a specific symbol — callers, callees, which flows it participates in — use `get_code_snippet` and `trace_path`.

## When Debugging

1. `search_graph` / `search_code` — find execution flows related to the issue.
2. `trace_path` — see inbound and outbound call chains for a suspect function.
3. `get_code_snippet` — read the source for a symbol by qualified name.
4. For regressions: `detect_changes` — map git diff to affected symbols with risk classification.

## When Refactoring

- **Renaming**: Use careful multi-file review and tests; codebase-memory can help locate all references via `search_graph`.
- **Extracting/Splitting**: Use `trace_path` to see all incoming/outgoing refs, then verify all external callers before moving code.
- After any refactor: review changed files to verify only expected symbols changed.

## Never Do

- NEVER edit a function, class, or method without first understanding its callers and callees.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with naive find-and-replace — trace the call graph first.

## Tools Quick Reference

| Tool | When to use | Example |
|------|-------------|---------|
| `index_repository` | Index or re-index the repo | `index_repository({"repo_path": "/Users/aloobhujia/flipperAgent"})` |
| `search_graph` | Find symbols by name, label, file | `search_graph({"project": "Users-aloobhujia-flipperAgent", "name_pattern": ".*Handler.*", "label": "Function"})` |
| `search_code` | Graph-augmented grep | `search_code({"project": "Users-aloobhujia-flipperAgent", "query": "auth validation"})` |
| `trace_path` | Blast radius / call chain | `trace_path({"project": "Users-aloobhujia-flipperAgent", "function_name": "X", "direction": "both"})` |
| `get_code_snippet` | Read source for a symbol | `get_code_snippet({"project": "Users-aloobhujia-flipperAgent", "qualified_name": "flipperAgent.src.libs.X"})` |
| `get_architecture` | Codebase overview | `get_architecture({"project": "Users-aloobhujia-flipperAgent"})` |
| `detect_changes` | Pre-commit scope check | `detect_changes({"project": "Users-aloobhujia-flipperAgent"})` |
| `query_graph` | Custom Cypher-like queries | `query_graph({"project": "Users-aloobhujia-flipperAgent", "query": "MATCH (f:Function) RETURN f.name LIMIT 5"})` |

## CLI Skill Reference

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.agents/skills/codebase-memory/exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.agents/skills/codebase-memory/impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.agents/skills/codebase-memory/debugging/SKILL.md` |
| Rename / extract / split / refactor | `.agents/skills/codebase-memory/refactoring/SKILL.md` |
| Tools, resources, schema reference | `.agents/skills/codebase-memory/guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.agents/skills/codebase-memory/cli/SKILL.md` |

<!-- codebase-memory:end -->


## Squad Collaboration

This project uses squad for multi-agent collaboration. Run `squad help` for all commands and usage guide.

