---
goal: Close the Momentum-local scalar/batch numeric parity and plugin immutability defects
stage: coder-to-orchestrator
date_created: 2026-08-15
last_updated: 2026-08-15
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, momentum, remediation, parity, immutability]
source_base: e416c4a1f8c7cef64e7bf2419c9e48ba8016f38e
source_worktree: /Users/kajukatli/.devspace/worktrees/flipperAgent-momentum-plugin-refactor-v2
---

# M2R — Momentum local remediation

## Result

The two approved Momentum-local defects are remediated. No shared model
discovery, Decision integration, feature/config migration, legacy-app change,
or optimizer change was made.

Terminal status:

`MOMENTUM_LOCAL_REFACTOR_REMEDIATION_READY_FOR_REVIEW`

MI0 remains required before full plugin-readiness approval.

## Changes

- Added `coerce_numeric_evidence()` to the Momentum semantic core as the single
  local finite-number vocabulary for `int`, `float`, and `Decimal` evidence.
  It rejects `bool`, non-numeric values, and non-finite values.
- Reused that helper in scalar legacy extraction, batch normalization, core
  observation/result validation, and the thin Decision adapter. RSI domain
  validation and the frozen Momentum equation remain unchanged.
- Made `MomentumDecisionPlugin` a frozen, slotted dataclass with a validated
  immutable `MomentumConfig` captured at construction. No cache or hidden
  mutable state was added.
- Added regressions for Decimal/mixed scalar-vs-batch parity, invalid evidence,
  plugin rebinding, source-mapping mutation, and distinct constructed configs.

## Validation

- Focused `tests/models/momentum`: **55 passed**.
- Affected Momentum/legacy strategy/regime compatibility selection: **322
  passed, 18 existing warnings**.
- Complete `tests/decision`: **361 passed**.
- Ruff check on changed Momentum production/tests: passed.
- Ruff format check on changed Momentum production/tests: passed.
- `compileall` for `src/libs/models/momentum` and `tests/models/momentum`: passed.
- `git diff --check`: passed.
- Existing Momentum import-boundary tests: passed within the focused suite;
  the new adapter has no legacy FeatureVector, infrastructure, or generic
  framework imports.
- Scoped repository cache cleanup completed; no Momentum `__pycache__` or
  bytecode files remain.

The unscoped `tests/models` collection retains the previously documented,
unrelated missing trendline research module; it was not modified or used as a
reason to broaden M2R.

## Review passes

Pass 1 — correctness:

- finite Decimal scalar behavior now matches batch behavior;
- scalar and batch invalid/non-finite/out-of-domain evidence fails closed;
- required MACD-line behavior remains fail-closed;
- the plugin config cannot be rebound and input mappings are materialized at
  construction;
- the existing Momentum equation, config validation, and neutral behavior are
  preserved.

Pass 2 — scope/architecture:

- no global registry/import-isolation change;
- no Decision runtime or integration change;
- no generic numeric parser or plugin immutability framework;
- no legacy `MomentumModel.params` redesign;
- no optimizer/config/legacy-app change;
- no MI0, RSI/MACD canonical-semantics work, or D8/D11 work.

## Remaining gate

`MODEL_PLUGIN_IMPORT_ISOLATION_REQUIRED_BEFORE_DECISION_INTEGRATION` remains
open for the separate MI0 package. This handoff does not claim full Momentum
plugin-readiness approval.

MOMENTUM_LOCAL_REFACTOR_REMEDIATION_READY_FOR_REVIEW
