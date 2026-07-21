---
name: create-implementation-plan
description: 'Create an execution-ready implementation plan for a feature, refactor, infrastructure change, or quantitative pipeline change.'
argument-hint: 'What needs to be planned?'
user-invocable: true
---

# Create Implementation Plan

This is a Quant Architect capability. Verify repository context and use memory only
when prior decisions materially matter. For existing code, inspect blast radius and
affected execution flows.

Save plans under `plans/` only when persistence is requested or implementation will
be delegated. Include:

1. objective, constraints, assumptions, and explicit non-goals;
2. selected design and rejected alternatives;
3. ordered tasks with dependencies and exact verified paths/symbols;
4. interfaces, data contracts, compatibility, and rollback needs;
5. acceptance criteria, focused validation, and broader regression checks;
6. risks, unresolved questions, and coder-ready scope.

Do not leave placeholders or invent repository facts. Use the active
`architect-to-coder` handoff format when Quant Coder is the next owner.
