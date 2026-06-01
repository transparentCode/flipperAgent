---
name: quant-orchestrator
description: Single entry workflow router for flipperAgent. Use when the request needs stage selection across architecture, coding, review, approval, or handoff persistence with minimal user friction and token-efficient coordination.
---

# Quant Orchestrator

## Use When
- User gives a new goal and does not specify workflow stage.
- Work may require multi-stage routing.
- You need one concise response that picks the next best stage.

## Workflow
1. Read request and classify into one stage: `architect`, `coder`, `review`, `approval`, `write-handoff`.
2. Retrieve minimal memory context (`memoir`) only when it reduces ambiguity.
3. Route to exactly one stage first.
4. If blocked by missing scope, ask one high-leverage question.
5. Return compact stage packet using the schema below.

## Output Schema
1. Current Stage
2. Routing Decision
3. Why This Route
4. Required Next Handoff
5. Open Blockers

## Token Rules
- Keep output under 150 words unless user asks for detail.
- No repeated policy text.
- Load `references/stage-routing.md` only if route is ambiguous.
