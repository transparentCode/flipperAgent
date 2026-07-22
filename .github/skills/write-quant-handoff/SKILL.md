---
name: write-quant-handoff
description: 'Persist a three-role quant handoff under plans for architect-to-coder, coder-to-orchestrator, or orchestrator-decision stages.'
argument-hint: 'Stage and topic to document'
user-invocable: true
---

# Write Quant Handoff

Canonical owner: `quant-orchestrator`.
Canonical skill: `.agents/skills/quant-orchestrator/SKILL.md`.
Stage templates: `.agents/skills/quant-orchestrator/references/stage-templates.md`.

Use one active stage:

- `orchestrator-to-architect-<topic>-vN.md`
- `architect-to-coder-<topic>-vN.md`
- `coder-to-orchestrator-<topic>-vN.md`
- `orchestrator-decision-<topic>-vN.md`

Write under `plans/`, preserve prior evidence, remove placeholders, and include the
scope, non-goals, affected flows, acceptance criteria, validation, blockers, and
residual risk required by the orchestrator-owned stage template.
