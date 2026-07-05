---
name: quant-approval
description: Quant approval gate skill for final merge-readiness and sign-off review after implementation and review are complete. Use when confirming quant changes are safe to approve.
user-invocable: true
---

# Quant Approval Gate

## Use When
- Implementation and review are complete and a final sign-off is needed.
- The user asks whether a quant change is safe to merge or deploy.
- A reviewer-to-approval handoff exists or needs to be produced.

## Preconditions
- Read the review package (`review-to-approval-<topic>-v1.md` or equivalent).
- Read the original architect-to-coder handoff and coder execution summary.
- Retrieve prior context from the `mem0` memory harness.

## Repo Context
- Handoff documents: `plans/` directory.
- Validation commands: `.venv/bin/python -m pytest`, `ruff check`.
- Config: `configs/*.yaml` — confirm no unintended config drift.
- Docker: 10-container topology — if deployment-affecting changes, confirm container compatibility.
- Codebase memory: use `detect_changes` for final scope verification.

## Workflow
1. **Completeness check** — confirm all approved scope items are implemented or explicitly deferred.
2. **Unresolved findings** — verify all blocking issues are resolved; non-blocking items are documented.
3. **Blast radius confirmation** — re-check codebase-memory `trace_path` / `detect_changes` for final scope match.
4. **Validation sufficiency** — confirm tests, lint, and any slice-specific validation passed with evidence.
5. **Residual risk** — identify any remaining risk that is acceptable vs. unacceptable.
6. **Decision** — approve, conditionally approve, or reject with required next steps.

## Output Schema
1. Approval Scope
2. Blocking Issues (must be empty to approve)
3. Blast Radius Confirmation
4. Validation Sufficiency
5. Residual Risk
6. Approval Decision
7. Required Handoff

## Handoff
- If approved, use `quant-write-handoff` to produce `approval-decision-<topic>-v1.md`.
- If rejected, route back to `quant-coder` or `quant-architect` via the appropriate handoff.

## Token Rules
- Do not approve if unresolved blocking issues remain.
- State the decision in one clear sentence.
- Make residual risk explicit even when approving.
