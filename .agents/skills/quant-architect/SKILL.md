---
name: quant-architect
description: Lean quant architecture skill for pipeline and system design decisions. Use when defining module boundaries, interfaces, tradeoffs, and coder-ready architecture scope.
user-invocable: true
---

# Quant Architect

## Use When
- The user asks for architecture, design tradeoffs, or pipeline restructuring.
- Scope is not yet implementation-ready and needs a coder handoff package.

## Repo Context
- Pipeline slices map to repo modules:
  - **Ingestion:** `src/apps/ingestion_app/`, `src/libs/common/` (discovery, stream consumer)
  - **Signal:** `src/apps/signal_app/`, `src/libs/features/`
  - **Strategy:** `src/apps/strategy_app/`, `src/libs/models/`
  - **Risk:** `src/apps/risk_app/`, `src/libs/risk/`
  - **Execution:** `src/apps/execution_app/`, `src/libs/execution/`
  - **Portfolio:** `src/apps/portfolio_app/`, `src/libs/portfolio/`
  - **Selection:** `src/libs/selection/`
  - **Regime:** `src/libs/regime/`
  - **Trendlines:** `src/libs/trendlines/`, `src/app/trendlines/`
  - **Alerts:** `src/apps/alert_app/`
  - **API:** `src/apps/api_app/`
  - **Scraper:** `src/apps/scraper_app/`
- Config-driven: `configs/*.yaml` per domain.
- Docker: 10-container topology (db, broker, 6 workers, queue, scheduler).
- Shared code: `src/libs/common/` and `src/libs/contracts/`.
- Handoffs: `plans/` directory.

## Workflow
1. Retrieve relevant prior context from memory.
2. Define constraints and non-goals first.
3. Propose 2-3 options with tradeoffs.
4. If existing code is affected, use codebase-memory tools (`trace_path`, `search_graph`, `get_code_snippet`) to understand impact before finalizing.
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

## Extended Version
An alternate, more verbose version of this skill is available at `.github/skills/quant-architecture/SKILL.md`.
