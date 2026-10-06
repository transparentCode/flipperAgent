---
paths:
  - "plans/**"
  - "artifacts/**"
---

# Durable evidence rules

- `plans/` is durable workflow state. Preserve historical handoffs and decisions; create a new version/stage rather than rewriting prior evidence unless explicitly instructed.
- `artifacts/` may contain frozen or benchmark evidence. Do not modify, regenerate, delete, or normalize an existing artifact unless the active contract names that output and authorizes the change.
- Never treat a historical handoff or artifact as proof of the current checkout. Verify material claims against live source, tests, configuration, and current runtime evidence.
- Keep handoffs concise and actionable: objective, scope, non-goals, verified facts, assumptions, acceptance criteria, validation, blockers, and residual risk.
