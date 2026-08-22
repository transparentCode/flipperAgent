---
name: quant-coder
description: Sole implementation skill for approved flipperAgent changes, from small mechanical fixes through non-trivial quantitative and infrastructure work. Use to edit code, add tests, validate behavior, self-review, and return execution evidence.
---

# Quant Coder

## Preconditions

- For delegated workspace writes, read the approved durable handoff under
  `plans/`. An inline contract is acceptable only for read-only analysis or
  trivial work performed by the root session itself; it does not replace a
  durable handoff for delegated writes.
- Confirm objective, scope, non-goals, acceptance criteria, and validation.
- If these require design judgment, return the task to `quant-architect`.

## Repository Context

- Production packages: `src/apps/` and `src/libs/`.
- Configuration: `configs/`.
- Environment: `.venv/bin/python`.
- Dependencies: `pyproject.toml`.
- Tests: `tests/`; lint with Ruff.

Verify paths and symbols from the live checkout before acting.

## Workflow

1. Inspect repository status and preserve unrelated user changes.
2. Use the `mcp-tiered-code-intelligence` skill to inspect callers, callees, and
   affected flows before editing existing symbols. Start with `codebase-memory-mcp`;
   escalate to `gitnexus` only for whole-repo structural impact. Surface HIGH or
   CRITICAL risk.
3. Make the smallest safe change. This includes bounded tests, docs, config wiring,
   and local fixes formerly assigned to a separate worker.
4. Preserve typing, contracts, determinism, point-in-time correctness, data identity,
   timing semantics, and configuration behavior.
5. Add or update focused tests. Run focused validation first, then broader checks in
   proportion to risk. Run Ruff for Python changes.
6. Inspect the final diff and self-review for scope drift, leakage, hidden behavior,
   failure paths, compatibility, and test gaps.
7. Return exact changed files, commands and results, unresolved risks, and anything
   not completed. If the orchestrator requests a `coder-to-orchestrator` handoff,
   provide it in the orchestrator-owned format under `plans/`.

## Constraints

- Do not invent parameters, schemas, lifecycle states, paths, or test results.
- Do not redesign architecture or broaden scope without architect approval.
- Do not modify unrelated files, protected evidence, or shared runtime state outside
  the delegated task.
- Do not switch branches, merge, or commit unless explicitly requested.

Load `references/coder-checklist.md` when you want a structured walkthrough of the
implementation and self-review steps.
