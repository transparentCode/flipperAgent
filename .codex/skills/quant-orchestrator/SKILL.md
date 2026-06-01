---
name: quant-orchestrator
description: Single core skill for flipperAgent quant workflow. Use for intake, architecture shaping, coding execution, review reasoning, and approval decisions in one token-efficient flow.
---

# Quant Orchestrator Core

## Use When
- Any quant task where stage is not explicitly fixed.
- End-to-end workflow is needed without loading multiple specialist skills.

## Modes
- `research`: define hypotheses, experiment plan, and decision criteria.
- `architecture`: clarify objective, constraints, tradeoffs, and coder-ready scope.
- `execution`: implement smallest safe code changes and validate narrowly.
- `review`: list findings by severity and check blast radius/validation gaps.
- `approval`: issue clear decision with residual risk.

## Workflow
1. Classify request into one mode.
2. Pull minimal memory context only when useful.
3. If code edits are needed, run GitNexus impact before modifying symbols.
4. Execute mode-specific work in concise form.
5. Ask at most one clarifying question when blocked.

## Output Schema
1. Current Mode
2. Decision or Work Performed
3. Blast Radius Notes
4. Validation or Evidence
5. Next Handoff / Next Step

## Token Rules
- Keep default replies compact.
- Do not repeat static policies/checklists.
- Load `references/stage-routing.md` only when mode choice is ambiguous.
