---
name: code-review
description: 'Quant-aware code review workflow for implementation changes. Use when: reviewing quantitative pipeline code, strategy logic, indicators, data contracts, validation coverage, or checking implementation consistency against architecture and style guides.'
user-invocable: true
---

> Canonical quant review skill: `.agents/skills/quant-review/SKILL.md`

# Code Review Procedure

## When to Use
- Whenever a user asks for a structural review of newly authored quant code.
- To verify a module adheres to `flipperAgent` project guidelines, quant safety constraints, and interface expectations.
- To review changes to data pipelines, indicators, backtest logic, or strategy-supporting infrastructure.

## Procedure
1. Identify the new changes (ask the user if not specified).
2. If the change touches existing code, use codebase intelligence tools to inspect blast radius, direct dependents, and affected execution flows before concluding the change is safe.
3. Execute automated checks in narrow or dry-run mode if available (for example `ruff check`, `pytest` for the touched slice, or other relevant validation commands).
4. Check for the following requirements:
   - Proper typing and interface stability.
   - Quant safety: no obvious look-ahead bias, data leakage, or silent changes to execution timing, slippage, or transaction cost assumptions.
   - Data contract integrity: symbol mapping, calendars, timezones, and pipeline expectations remain coherent.
   - Testability and validation coverage for the touched slice.
   - Consistency with the approved architect handoff when one exists.
5. Document the review findings clearly for the user, separating blocking issues from non-blocking follow-ups.

## References
- Refer to `AGENTS.md` for project architecture context.
- Refer to `.github/skills/quant-handoff/SKILL.md` for the shared review-package structure.