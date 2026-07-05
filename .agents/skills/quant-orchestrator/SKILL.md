---
name: quant-orchestrator
description: Single core skill for flipperAgent quant workflow. Use for intake, architecture shaping, coding execution, review reasoning, and approval decisions in one token-efficient flow.
user-invocable: true
---

# Quant Orchestrator Core

## Use When
- Any quant task where stage is not explicitly fixed.
- End-to-end workflow is needed without loading multiple specialist skills.

## Modes
- `research`: define hypotheses, experiment plan, and decision criteria. Supports deep web research via `search-specialist`.
- `architecture`: clarify objective, constraints, tradeoffs, and coder-ready scope.
- `coder`: implement smallest safe code changes against an approved handoff and validate narrowly.
- `review`: list findings by severity and check blast radius/validation gaps.
- `approval`: issue clear decision with residual risk.
- `write-handoff`: persist stage package in `plans/`.

## Repo Context
- Pipeline: `ingestion → signal → strategy → risk → execution → portfolio` (see `src/apps/`).
- Libs: `src/libs/` (models, features, risk, execution, portfolio, regime, selection, contracts, common, trendlines).
- Config: `configs/*.yaml` per domain.
- Environment: `.venv/bin/python`, `pyproject.toml`, `pytest`, `ruff`.
- Handoffs: `plans/` directory.
- Memory: `mem0` for prior context retrieval.

## Workflow
1. Classify request into one mode.
2. Pull minimal memory context from `mem0` only when useful.
3. If code edits are needed, use codebase-memory tools to verify blast radius before modifying symbols.
4. Execute mode-specific work in concise form.
5. Ask at most one clarifying question when blocked.

### Subagent Routing
- If the mode requires specialist execution, invoke the matching subagent with a stage-correct handoff package.
- If the subagent returns ambiguity, route to `quant-architect` before re-executing.
- Persist every subagent outcome via `quant-write-handoff` when it produces a durable artifact.
- Do not spawn multiple subagents for the same task unless explicitly designed.

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
