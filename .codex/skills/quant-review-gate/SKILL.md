---
name: quant-review-gate
description: Review-stage skill for quant implementations. Use when validating correctness, blast radius handling, quant safety constraints, and validation completeness before approval.
---

# Quant Review Gate

## Workflow
1. Compare implementation against approved handoff/request.
2. Retrieve memory context for prior constraints when needed.
3. Check changed scope and GitNexus blast radius.
4. Verify validation sufficiency.
5. Return findings by severity with clear owner (`coder` vs `architect`).

## Output Schema
1. Review Scope
2. Findings by Severity
3. Blast Radius and Affected Flows
4. Validation Gaps or Confirmations
5. Approval Status
6. Recommended Handoff

## Token Rules
- Findings first, summary second.
- Keep non-blockers brief.
- Load `references/review-checklist.md` only if needed.
