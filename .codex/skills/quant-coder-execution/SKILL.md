---
name: quant-coder-execution
description: Implementation-stage coding skill for approved quant handoffs. Use when execution scope is clear and code changes, tests, and validation are required.
---

# Quant Coder Execution

## Workflow
1. Confirm objective and boundaries from user/handoff.
2. Retrieve relevant memory constraints.
3. For touched symbols, run GitNexus impact before edits.
4. Implement smallest safe change set.
5. Run narrow validation quickly and fix local failures.
6. Return execution summary in fixed schema.

## Output Schema
1. Scope Executed
2. Changes Made
3. Blast Radius Considered
4. Validation Performed
5. Not Changed
6. Risks or Follow-up Items

## Token Rules
- No long narrative of commands.
- Report only high-signal diffs and validations.
- Load `references/execution-checklist.md` only for risky edits.
