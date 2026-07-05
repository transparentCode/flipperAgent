---
name: quant-review
description: Quant review skill for evaluating implementation output against approved architecture, quant safety constraints, and project guidelines. Use before sign-off or when returning findings to a coder/architect.
user-invocable: true
---

# Quant Review

## Use When
- A coder execution summary or diff needs review against an approved handoff.
- The user asks for a structural or quant-safety review of new code.
- The goal is to catch blocking issues before approval or merge.

## Preconditions
- Read the relevant handoff from `plans/` (architect-to-coder or coder-to-review).
- Retrieve prior context from the `mem0` memory harness.
- Confirm the codebase-memory index is fresh if the change touches existing symbols.

## Repo Context
- Pipeline: `ingestion → signal → strategy → risk → execution → portfolio` (see `src/apps/`).
- Shared contracts: `src/libs/contracts/` — check data contract integrity here.
- Config: `configs/*.yaml` — verify config drift against handoff expectations.
- Tests: `tests/` — run `.venv/bin/python -m pytest` for the touched slice.
- Lint: `ruff check` from project root.
- Quant safety constraints: point-in-time correctness, no look-ahead bias, calendar/timezone/symbol mapping coherence, transaction cost realism.

## Workflow
1. **Scope alignment** — verify the changes match the approved scope and non-goals.
2. **Blast radius** — use codebase-memory tools (`trace_path`, `search_graph`) for all modified symbols; list direct dependents.
3. **Static checks** — run `ruff check`, `pytest` for the touched slice, and any project-specific validation.
4. **Quant safety review**:
   - No look-ahead bias or data leakage.
   - Point-in-time correctness preserved.
   - Calendar, timezone, and symbol mapping unchanged unless explicitly scoped.
   - Transaction cost, slippage, and execution-timing assumptions unchanged unless scoped.
5. **Interface stability** — check type hints, data contracts, and public APIs.
6. **Test coverage** — verify new logic has tests and existing tests still pass.
7. **Findings** — separate blocking issues from non-blocking follow-ups.

## Output Schema
1. Review Scope
2. Findings by Severity (Blocking / Major / Minor)
3. Blast Radius and Affected Flows
4. Validation Gaps or Confirmations
5. Approval Status (Approve / Conditionally Approve / Request Changes)
6. Recommended Handoff

## Handoff
- Use `quant-write-handoff` to produce `review-to-approval-<topic>-v1.md` or `review-to-architect-<topic>-v1.md` as appropriate.

## Token Rules
- Be evidence-first; cite file paths and line evidence where possible.
- Do not approve changes with unresolved HIGH/CRITICAL impact.
- Keep the distinction between blocking and non-blocking issues explicit.
