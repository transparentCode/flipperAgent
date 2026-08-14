---
goal: Approve D9D PriceRelay and downstream risk continuity after final evidence remediation
stage: orchestrator-decision
date_created: 2026-08-14
last_updated: 2026-08-14
owner: quant-orchestrator
status: Approved
source_agent: quant-orchestrator
target_agent: user
tags: [handoff, quant, decision-app, d9d, price-relay, risk, continuity, approved]
---

# Decision

`DECISION_APP_D9D_PRICE_RELAY_RISK_CONTINUITY_APPROVED`

D9D is approved after independent review of the final deferred-input-failure relay evidence remediation.

## Verified final behavior

- Valid-prefix PriceUpdate publication remains committed when a later deferred malformed/non-forward suffix blocks the same canonical input stream.
- Matching PriceRelay final continuity becomes `UNRESOLVED` and preserves the last successfully published cutoff.
- `DecisionPollResult.relay_results` is refreshed from final in-memory relay state for affected relay IDs only.
- The earlier `PUBLISHED`/`ALREADY_IDENTICAL` publication outcome and semantically valid target are preserved in the bounded poll evidence.
- Evidence refresh does not call `reconcile_all()`, does not publish a second catch-up batch, and does not mutate unrelated relay plans.
- Idle polls in the failed generation remain `UNRESOLVED` and do not publish further prices for the blocked source.
- Canonical input failure remains distinct from transient downstream publication failure: input failure is generation-terminal `UNRESOLVED`; downstream `FAILED` remains retryable `GAP_DETECTED`.
- Fresh generations may revalidate canonical source continuity and recover normally.

## Independent validation

- Exact final remediation/continuity regressions: 3 passed.
- Focused D9D PriceRelay/runtime/risk surface: 34 passed.
- Complete `tests/decision`: 345 passed.
- Combined risk + signals/integration + commons + execution + architecture guardrails: 402 passed, with one existing OpenTelemetry deprecation warning.
- Scoped Ruff check: passed.
- Ruff format check: 76 files already formatted.
- Compileall: passed.
- `git diff --check`: passed.
- No-network decision import smoke: 35 concrete modules imported successfully.
- Decision architecture scan: exactly two long-lived `asyncio.create_task` sites; no decision-side PEL/consumer groups; no generic model implementation imports; no legacy signal/strategy runtime surface; no D10/deployment/model integration leakage; no production decision asset YAML.
- `.env` remains absent, so live external Timescale/Valkey certification remains environment-blocked. No external state was touched.

## Residual / carry-forward

- Production PriceRelay ownership handoff from legacy signal_app remains a D12 cutover concern; D9D does not authorize dual production publication.
- Real infrastructure certification remains blocked by the absent worktree `.env` and is not a functional D9D blocker.
- D10 resource/capacity certification is the next unstarted package.
- Model/plugin refactoring and integration remain deferred.

No commit, merge, push, branch switch, reset, restore, or D10 implementation was performed during review.
