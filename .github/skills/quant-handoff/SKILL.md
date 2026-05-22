---
name: quant-handoff
description: 'Shared handoff format for Quant Research Architect, Coder Agent, Quant Review Agent, and Quant Approval Gate. Use when: preparing an architect-to-coder handoff, coder execution summary, review findings package, or approval package for quant changes.'
user-invocable: true
---

# Quant Handoff Format

## When to Use
- Preparing a coder handoff from research or architecture work.
- Summarizing completed implementation work for review.
- Returning structured review findings to the coder or architect.
- Preparing a final approval package for sign-off.

## Goals
- Keep agent-to-agent payloads consistent.
- Make blast radius, validation, scope boundaries, and residual risk explicit.
- Reduce ambiguity between architect, coder, reviewer, and approval gate.

## Architect to Coder Template
- Objective
- Scope Boundaries
- Affected Symbols, Modules, and Execution Flows
- Data Contracts or Interfaces
- Implementation Order
- Acceptance Criteria
- Validation Checklist
- Explicit Non-Goals

## Coder to Reviewer Template
- Scope Executed
- Changes Made
- Blast Radius Considered
- Validation Performed
- Not Changed
- Risks or Follow-Up Items

## Reviewer to Coder or Architect Template
- Review Scope
- Findings by Severity
- Blast Radius and Affected Flows
- Validation Gaps or Confirmations
- Approval Status
- Recommended Handoff

## Reviewer to Approval Gate Template
- Reviewed Scope
- Resolved Findings
- Remaining Non-Blocking Follow-Ups
- Blast Radius Confirmation
- Validation Evidence Summary
- Recommended Approval Status

## Approval Gate Template
- Approval Scope
- Blocking Issues
- Blast Radius Confirmation
- Validation Sufficiency
- Approval Decision
- Required Handoff

## Requirements
- Always state what was not changed when that reduces ambiguity.
- Always include blast radius or explicitly say it was not applicable.
- Always separate blocking issues from non-blocking follow-ups.
- Always state whether the package is complete enough for the next agent to act without guessing.