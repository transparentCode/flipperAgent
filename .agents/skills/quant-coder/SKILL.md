---
name: quant-coder
description: Sole implementation skill for approved flipperAgent changes, from small mechanical fixes through non-trivial quantitative and infrastructure work. Use to edit code, add tests, validate behavior, self-review, and return execution evidence.
---

# Quant Coder

## Preconditions

- Read the approved handoff or complete inline contract.
- Confirm objective, scope, non-goals, acceptance criteria, and validation.
- If these require design judgment, return the task to `quant-architect`.

## Repository Context

- Production packages: `src/apps/`, `src/libs/`, and `conductor/`.
- Configuration: `configs/`.
- Environment: `.venv/bin/python`.
- Dependencies: `pyproject.toml`.
- Tests: `tests/`; lint with Ruff.

Verify paths and symbols from the live checkout before acting.

## Workflow

1. Inspect repository status and preserve unrelated user changes.
2. Use codebase-memory to inspect callers, callees, and affected flows before
   editing existing symbols. Surface HIGH or CRITICAL risk.
3. Make the smallest safe change. This includes bounded tests, docs, config wiring,
   and local fixes formerly assigned to a separate worker.
4. Preserve typing, contracts, determinism, point-in-time correctness, data identity,
   timing semantics, and configuration behavior.
5. Add or update focused tests. Run focused validation first, then broader checks in
   proportion to risk. Run Ruff for Python changes.
6. Inspect the final diff and self-review for scope drift, leakage, hidden behavior,
   failure paths, compatibility, and test gaps.
7. Return exact changed files, commands and results, unresolved risks, and anything
   not completed. Persist a `coder-to-orchestrator` handoff when requested.

## Constraints

- Do not invent parameters, schemas, lifecycle states, paths, or test results.
- Do not redesign architecture or broaden scope without architect approval.
- Do not modify unrelated files, protected evidence, or shared runtime state outside
  the delegated task.
- Do not switch branches, merge, or commit unless explicitly requested.
