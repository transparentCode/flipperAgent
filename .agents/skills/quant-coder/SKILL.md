---
name: quant-coder
description: Quant coder execution skill for implementing approved architecture handoffs, strategy logic, indicators, pipeline changes, and validation. Use when writing, modifying, or validating quant code against an approved plan.
user-invocable: true
---

# Quant Coder

## Use When
- An approved architect-to-coder handoff or implementation plan exists.
- The task is to write, modify, or fix quant pipeline, strategy, indicator, data, or infrastructure code.
- Validation (tests, type checks, lint) is required before marking work complete.

## Preconditions
- Read the relevant handoff from `plans/` before writing code.
- Retrieve prior context from the `mem0` memory harness.
- Confirm the codebase-memory index is fresh if the change touches existing symbols.

## Repo Context
- Package layout: `src/flipper_agent/` with `src/libs/` (models, features, risk, execution, portfolio, regime, selection, contracts, common, trendlines) and `src/apps/` (ingestion_app, signal_app, strategy_app, risk_app, execution_app, portfolio_app, alert_app, api_app, scraper_app).
- Pipeline topology: `ingestion → signal → strategy → risk → execution → portfolio`.
- Config files: `configs/*.yaml` (base, models, features, risk, execution, portfolio, alerts, etc.).
- Environment: use `.venv/bin/python` for all Python commands.
- Dependencies: `pyproject.toml` is the source of truth — update it when adding packages.
- Tests: `tests/` directory, run with `.venv/bin/python -m pytest`.
- Lint: `ruff check` from project root.
- Shared cross-cutting code lives under `src/libs/common/` and `src/libs/contracts/`.

## Workflow
1. **Scope check** — restate what is in-scope, out-of-scope, and any explicit non-goals.
2. **Impact analysis** — for changes to existing symbols, use codebase-memory tools (`trace_path`, `search_graph`) to understand callers and callees; surface HIGH/CRITICAL risk before editing.
3. **Minimal change** — implement the smallest safe change that satisfies the handoff.
4. **Type safety** — add or preserve type hints; do not silently widen interfaces.
5. **Quant safety** — avoid look-ahead bias, data leakage, and hidden execution-timing changes.
6. **Tests** — add or update tests for the touched slice; run `.venv/bin/python -m pytest` for the relevant module.
7. **Lint / format** — run `ruff check` from project root.
8. **Evidence** — record what was changed, what was validated, and any residual risk.

## Output Schema
1. Scope Executed
2. Files and Symbols Changed
3. Blast Radius Considered
4. Validation Performed (commands, results, test counts)
5. Not Changed
6. Risks or Follow-Up Items

## Handoff
- If the next step is review, use `quant-write-handoff` to produce a `coder-to-review-<topic>-v1.md` document.

## Token Rules
- Do not rewrite code that is not in scope.
- Do not invent parameters, file paths, or symbols not present in the handoff or repo.
- Prefer small, testable commits over large refactors.
