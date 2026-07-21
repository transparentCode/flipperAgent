---
name: quant-write-handoff
description: Write durable three-role flipperAgent coordination documents under plans. Use for architect-to-coder contracts, coder-to-orchestrator execution evidence, and orchestrator decisions.
---

# Quant Write Handoff

## Active Stages

- `orchestrator-to-architect-<topic>-vN.md`
- `architect-to-coder-<topic>-vN.md`
- `coder-to-orchestrator-<topic>-vN.md`
- `orchestrator-decision-<topic>-vN.md`

Historical handoffs may use retired stage names. Preserve them as evidence.

## Required Front Matter

```yaml
---
goal: concise outcome
stage: orchestrator-to-architect | architect-to-coder | coder-to-orchestrator | orchestrator-decision
date_created: YYYY-MM-DD
last_updated: YYYY-MM-DD
owner: responsible role or user
status: Draft | Ready | Needs Revision | Approved | Not Approved
source_agent: source role
target_agent: target role or user
tags: [handoff, quant]
---
```

## Requirements

- Save under `plans/`; never overwrite protected prior evidence.
- Include objective, scope, non-goals, affected files/symbols/flows, acceptance
  criteria, validation evidence or plan, blockers, and residual risk as applicable.
- Separate verified facts from assumptions and unresolved questions.
- Remove placeholders. State whether the next owner can act without guessing.
- Load `references/stage-templates.md` only when a full template is needed.
