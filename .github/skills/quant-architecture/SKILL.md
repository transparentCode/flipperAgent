---
name: quant-architecture
description: 'Quant architecture planning workflow for research systems, data pipelines, strategy infrastructure, and experiment design. Use when comparing architectural options, designing quant data flows, reasoning about tradeoffs, or preparing a coder handoff.'
user-invocable: true
---

> Canonical skill: `.agents/skills/quant-architect/SKILL.md`

# Quant Architecture Planning

## When to Use
- Designing or revising a quantitative research pipeline.
- Comparing storage, compute, orchestration, or feature-engineering approaches.
- Turning a research objective into an architecture plan with clear tradeoffs.
- Preparing a coding handoff for a quant implementation agent.

## Procedure
1. Start with memory retrieval from the available MCP systems before proposing any architecture.
2. If the plan touches existing code, read codebase intelligence tools repository context first and check whether the index is fresh enough for impact analysis.
3. Define the operating context explicitly:
   - asset universe
   - venue or market structure
   - data frequency and latency needs
   - backtest versus live requirements
   - reproducibility and audit expectations
4. Break the system into slices:
   - ingestion
   - normalization
   - storage
   - feature and indicator computation
   - labeling
   - backtesting and simulation
   - evaluation and reporting
5. Use codebase intelligence tools impact analysis and process views to map blast radius and affected execution flows for the symbols, modules, and interfaces most likely to change.
6. For each slice, compare at least two viable options and document:
   - expected benefit
   - cost or complexity
   - operational risk
   - failure mode
   - reason for selection or rejection
7. Check quant-specific safety concerns:
   - point-in-time correctness
   - leakage and survivorship bias
   - transaction cost realism
   - calendar, timezone, and symbol mapping correctness
   - versioning and reproducibility
8. Produce a handoff package for the coding agent with module boundaries, interfaces, acceptance criteria, a blast-radius summary, and a validation plan.

## Output Expectations
- Include explicit tradeoffs, not just a preferred design.
- Call out assumptions and unknowns separately.
- Include codebase intelligence tools blast radius and affected execution flows when the architecture interacts with existing code.
- Prefer minimal architecture that preserves research speed and future extensibility.
- Save final decisions and open questions back to memory when the MCP systems are available.