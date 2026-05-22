# Plans Directory

This directory stores durable quantitative handoff and implementation-planning documents for `flipperAgent`.

## Purpose

- Keep architect, coder, reviewer, and approval handoffs in a stable location.
- Preserve implementation plans and decision packages that should outlive a single chat session.
- Make blast radius, validation, scope boundaries, and follow-up items reviewable from files instead of only chat history.

## Preferred Sources

- Use `.github/skills/write-quant-handoff/` to create stage-specific handoff documents.
- Use `.github/skills/quant-handoff/` as the shared structure for handoff content.
- Use `.github/skills/create-implementation-plan/` for broader execution plans that need phased task breakdowns.

## Naming Conventions

- `architect-to-coder-<topic>-v1.md`
- `coder-to-review-<topic>-v1.md`
- `review-to-architect-<topic>-v1.md`
- `review-to-approval-<topic>-v1.md`
- `approval-decision-<topic>-v1.md`
- `feature-<topic>-v1.md`, `architecture-<topic>-v1.md`, or similar for broader implementation plans

## Expectations

- Keep the file goal and workflow stage explicit in front matter.
- Include blast radius when the document concerns existing code.
- Separate blocking issues from non-blocking follow-ups.
- State what was not changed when that reduces ambiguity.
- Keep documents actionable enough that the next agent or engineer does not need to guess intent.