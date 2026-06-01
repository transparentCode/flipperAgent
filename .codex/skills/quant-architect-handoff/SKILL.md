---
name: quant-architect-handoff
description: Quant research and architecture planning skill that produces coder-ready handoffs. Use when designing or changing quant pipelines, strategy components, data contracts, or execution flow boundaries.
---

# Quant Architect Handoff

## Workflow
1. Retrieve relevant memory context first.
2. Build a context ledger (objective, assets, frequency, constraints).
3. If existing code is touched, inspect GitNexus context and impact.
4. Compare options and pick one with explicit tradeoffs.
5. Produce coder-ready handoff with non-goals and validation criteria.

## Output Schema
1. Context Retrieved
2. Confirmed Facts
3. Open Questions
4. Architecture Plan
5. Tradeoffs and Rejected Options
6. Blast Radius and Affected Flows
7. Risks and Validation Checks
8. Coder Handoff Package

## Token Rules
- Keep main response concise; move deep checklists to references.
- Ask only essential questions.
- Load `references/` only as needed.
