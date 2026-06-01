---
name: quant-approval-gate
description: Final approval-stage skill for merge readiness. Use when review is done and a clear approval decision is required with explicit residual risk handling.
---

# Quant Approval Gate

## Workflow
1. Read handoff, coder summary, and review findings.
2. Confirm blast radius understanding for touched shared code.
3. Confirm validation sufficiency.
4. Decide: `Approved`, `Approved with Non-Blocking Follow-Ups`, or `Not Approved`.

## Output Schema
1. Approval Scope
2. Blocking Issues
3. Blast Radius Confirmation
4. Validation Sufficiency
5. Approval Decision
6. Required Handoff

## Token Rules
- Decision-first output.
- No repeated background context.
- Load `references/approval-checklist.md` only if evidence is thin.
