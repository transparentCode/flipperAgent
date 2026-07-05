---
name: write-quant-handoff
description: 'Write a concrete quant handoff document into `plans/` using the shared handoff format. Use when: saving an architect-to-coder handoff, persisting a coder execution summary, writing review findings, creating an approval package, or turning an in-chat handoff into a durable markdown document.'
argument-hint: 'Which handoff stage and what topic should be documented?'
user-invocable: true
---

> Canonical skill: `.agents/skills/quant-write-handoff/SKILL.md`

# Write Quant Handoff

## When to Use
- Persisting an architect-to-coder handoff into a markdown file.
- Saving a coder execution summary for later review.
- Writing a review findings package for the coder or architect.
- Preparing an approval package for final sign-off.
- Converting an in-chat handoff into a durable document under `plans/`.

## Goals
- Create a concrete handoff document that another agent or human can use without guessing.
- Reuse the shared format from `../quant-handoff/SKILL.md`.
- Keep blast radius, scope boundaries, validation, and residual risk explicit.

## Required Workflow
1. Retrieve relevant prior context from available memory systems before drafting the handoff.
2. Inspect the repository and gather the exact scope, touched files or modules, and any existing approved decisions.
3. If the handoff touches existing code, use codebase intelligence tools repository context, impact analysis, execution flows, and change detection when available to capture blast radius accurately.
4. Select the correct stage template from `../quant-handoff/SKILL.md`:
   - architect to coder
   - coder to reviewer
   - reviewer to coder or architect
   - reviewer to approval gate
   - approval gate decision
5. Write the handoff document into `plans/` at the repository root. Create the directory first if it does not exist.
6. Remove placeholders and ensure the document is actionable, stage-correct, and complete enough for the next agent to act without guessing.

## File Naming Convention
- Save files in `plans/`.
- Use stage-first names so the workflow is obvious from the path.
- Preferred patterns:
  - `architect-to-coder-<topic>-v1.md`
  - `coder-to-review-<topic>-v1.md`
  - `review-to-architect-<topic>-v1.md`
  - `review-to-approval-<topic>-v1.md`
  - `approval-decision-<topic>-v1.md`

## Required Front Matter
```md
---
goal: [Concise handoff goal]
stage: [architect-to-coder|coder-to-review|review-to-architect|review-to-approval|approval-decision]
date_created: [YYYY-MM-DD]
last_updated: [YYYY-MM-DD]
owner: [Agent or user responsible for the handoff]
status: 'Draft'|'Ready'|'Needs Revision'|'Approved'
tags: [handoff, quant, optional-topic-tags]
source_agent: [Agent or user producing the handoff]
target_agent: [Next agent or human consumer]
---
```

## Document Body Requirements
- Include only the sections required for the chosen handoff stage from `../quant-handoff/SKILL.md`.
- Always state what was not changed when that reduces ambiguity.
- Always include blast radius, or explicitly state that it was not applicable.
- Always separate blocking issues from non-blocking follow-ups.
- Always state whether the package is complete enough for the next agent to act without guessing.

## Validation Checklist
- The file is inside `plans/`.
- The file name reflects the correct workflow stage.
- The front matter is complete and valid.
- The body matches the selected stage template.
- There is no placeholder text left in the document.
- Blast radius and validation are covered when relevant.