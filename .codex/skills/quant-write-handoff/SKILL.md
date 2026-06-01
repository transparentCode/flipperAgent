---
name: quant-write-handoff
description: Persist stage handoff packages into plans markdown files. Use when converting architecture, execution, review, or approval outputs into durable, stage-correct documents.
---

# Quant Write Handoff

## Workflow
1. Confirm stage type and consumer.
2. Gather exact scope and latest validated findings.
3. If code paths were touched, include blast radius summary.
4. Write file in `plans/` using stage-first naming.
5. Ensure no placeholders and explicit non-goals/follow-ups.

## File Naming
- `architect-to-coder-<topic>-v1.md`
- `coder-to-review-<topic>-v1.md`
- `review-to-architect-<topic>-v1.md`
- `review-to-approval-<topic>-v1.md`
- `approval-decision-<topic>-v1.md`

## Token Rules
- Use compact sections only for selected stage template.
- Load `references/stage-templates.md` when writing the file.
