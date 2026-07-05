---
name: quant-research
description: Lean quant research skill for hypothesis framing, experiment planning, and evidence synthesis. Use when exploring alpha ideas, indicators, data quality questions, or model-selection direction.
user-invocable: true
---

# Quant Research

## Use When
- The user asks for research plans, signal ideas, or experiment design.
- Work requires hypothesis testing before architecture or coding.
- External literature, market structure, or vendor comparison is needed.

## Repo Context
- Pipeline: `ingestion → signal → strategy → risk → execution → portfolio` (see `src/apps/`).
- Models and indicators live in `src/libs/models/` and `src/libs/features/`.
- Config-driven: `configs/models.yaml`, `configs/features.yaml`, `configs/risk.yaml`.
- Prior research results in `research/alpha_research_results.json`.
- Handoff documents in `plans/`.

## Workflow
1. Retrieve relevant memory context and known constraints.
2. **Web research (when external evidence is needed):**
   - Use the `search-specialist` skill (`.github/skills/search-specialist/SKILL.md`) for deep web research.
   - Formulate 3-5 query variations for coverage; search broadly first, then refine.
   - Fetch full content from promising sources via `fetch_webpage`.
   - Cross-reference key claims across multiple sources.
   - Track contradictions and consensus explicitly.
   - Tie findings back to quant pipeline, strategy research, or architecture decisions.
3. Frame hypothesis and measurable success criteria.
4. Design a minimal experiment matrix.
5. Identify leakage/bias risks and controls.
6. Return ranked next experiments and decision gates.

## Output Schema
1. Research Objective
2. Prior Context (memory + repo)
3. External Evidence (web research summary with sources, if performed)
4. Hypotheses
5. Experiment Plan
6. Data and Bias Controls
7. Decision Criteria
8. Recommended Next Step

## Token Rules
- Keep responses compact and evidence-first.
- Load `references/research-checklist.md` only for deeper analysis.
- When web research is performed, always cite source URLs and credibility assessment.
