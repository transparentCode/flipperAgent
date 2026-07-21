---
name: write-quant-handoff
description: 'Persist a three-role quant handoff under plans for architect-to-coder, coder-to-orchestrator, or orchestrator-decision stages.'
argument-hint: 'Stage and topic to document'
user-invocable: true
---

# Write Quant Handoff

Canonical skill: `.agents/skills/quant-write-handoff/SKILL.md`.

Use one active stage:

- `orchestrator-to-architect-<topic>-vN.md`
- `architect-to-coder-<topic>-vN.md`
- `coder-to-orchestrator-<topic>-vN.md`
- `orchestrator-decision-<topic>-vN.md`

Write under `plans/`, preserve prior evidence, remove placeholders, and include the
scope, non-goals, affected flows, acceptance criteria, validation, blockers, and
residual risk required by the canonical stage template.
