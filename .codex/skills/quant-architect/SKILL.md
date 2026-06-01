---
name: quant-architect
description: Lean quant architecture skill for pipeline and system design decisions. Use when defining module boundaries, interfaces, tradeoffs, and coder-ready architecture scope.
---

# Quant Architect

## Use When
- The user asks for architecture, design tradeoffs, or pipeline restructuring.
- Scope is not yet implementation-ready and needs a coder handoff package.

## Workflow
1. Retrieve relevant prior context from memory.
2. Define constraints and non-goals first.
3. Propose 2-3 options with tradeoffs.
4. If existing code is affected, run GitNexus impact/context before finalizing.
5. Produce a compact coder-ready architecture handoff.

## Output Schema
1. Architecture Goal
2. Constraints and Non-Goals
3. Options and Tradeoffs
4. Selected Design
5. Blast Radius and Affected Flows
6. Handoff for Implementation

## Token Rules
- Keep architecture response concise and decision-oriented.
- Load `references/architecture-checklist.md` only when risk is high.
