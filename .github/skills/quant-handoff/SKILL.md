---
name: quant-handoff
description: 'Shared three-role handoff format for Quant Architect, Quant Coder, and Quant Orchestrator.'
user-invocable: true
---

# Quant Handoff

Canonical owner: `quant-orchestrator`.
Canonical skill: `.agents/skills/quant-orchestrator/SKILL.md`.
Stage templates: `.agents/skills/quant-orchestrator/references/stage-templates.md`.

Active stages:

- orchestrator to architect: objective, evidence, constraints, and design questions;
- architect to coder: design, scope, contracts, acceptance criteria, validation;
- coder to orchestrator: changes, blast radius, exact validation, self-review, risks;
- orchestrator decision: findings, evidence sufficiency, approval or remediation.

The orchestrator owns durable handoff persistence under `plans/`. Always state
non-goals, what was not changed, blockers, and whether the next owner can act without
guessing. Preserve historical handoffs that use retired stages.
