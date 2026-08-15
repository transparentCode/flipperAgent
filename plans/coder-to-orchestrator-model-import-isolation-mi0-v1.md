---
goal: Remove implicit legacy model discovery and add an explicit legacy bootstrap boundary
stage: coder-to-orchestrator
date_created: 2026-08-15
last_updated: 2026-08-15
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, models, import-isolation, legacy-bootstrap, mi0]
source_base: 327bd03ca403eb40c8dc3bdb3c7d4380e8588a9b
source_worktree: /Users/kajukatli/.devspace/worktrees/flipperAgent-model-import-isolation-mi0
---

# MI0 — model import isolation and explicit legacy bootstrap

## Result

MI0 is implemented in a fresh worktree based on the committed and merged
Momentum/M2R source. Ordinary `libs.models` imports are now side-effect-free;
legacy registry discovery is owned by one explicit bootstrap operation. The
Decision Momentum plugin import remains isolated from legacy model/runtime
modules. No Decision integration, RSI/MACD work, model math, configuration,
Docker, or D11 work was performed.

Terminal status:

`MODEL_PLUGIN_IMPORT_ISOLATION_MI0_READY_FOR_REVIEW`

## Precondition and source

The approved Momentum + M2R worktree was committed and fast-forward merged
into `main` before MI0 work began:

- merge commit: `327bd03ca403eb40c8dc3bdb3c7d4380e8588a9b`
- post-Momentum `main` SHA: `327bd03ca403eb40c8dc3bdb3c7d4380e8588a9b`
- MI0 worktree: `/Users/kajukatli/.devspace/worktrees/flipperAgent-model-import-isolation-mi0`
- MI0 HEAD: `327bd03ca403eb40c8dc3bdb3c7d4380e8588a9b`

The primary checkout was not used for MI0 edits. Its unrelated pre-existing
untracked plan/worktree files were preserved.

## Changes

### Import boundary

- Removed `ModelRegistry.auto_discover()` from `src/libs/models/__init__.py`.
- Added `src/libs/models/legacy_bootstrap.py` with the single public operation
  `bootstrap_legacy_model_registries()`.
- The bootstrap reuses the existing discovery mechanism and explicitly imports
  the decorator-bearing Momentum legacy modules whose package root is now lazy:
  `libs.models.momentum.model` and `libs.models.momentum.strategy_v2`.
- No fallback discovery was added to either registry getter.

### Momentum package root

`src/libs/models/momentum/__init__.py` now keeps the core/config exports eager
and lazily resolves only the legacy `MomentumModel` and `MomentumV2` exports.
The existing public import forms remain supported. The Momentum model-local
optimizer explicitly imports its concrete legacy model because the package root
no longer performs that registration implicitly.

### Explicit legacy callers

The former registration-intent imports were replaced with the explicit
bootstrap at these high-level boundaries:

- `ModelManager`, `ScoringModelManager`, and `UnifiedModelManager`;
- `libs.optim_utils.objective`, `ParamAuditor`, and `TwoStageOptimizer`;
- model optimization entrypoints for Divergence Edge, Mean Reversion,
  Momentum, Regime Pullback, Regime Relative Value, Squeeze Breakout, and
  Trend Following;
- `scripts/batch_optimize.py`, `scripts/mr_optimization_v7.py`, and
  `scripts/sb_2yr_validation.py`.

No low-level registry getter was changed and no generic discovery abstraction
was introduced. A source AST scan found zero plain `import libs.models`
registration-intent imports under `src/` and `scripts/`.

### Exact files changed

Production:

```text
scripts/batch_optimize.py
scripts/mr_optimization_v7.py
scripts/sb_2yr_validation.py
src/apps/strategy_app/models/model_manager.py
src/apps/strategy_app/models/scoring_model_manager.py
src/apps/strategy_app/models/unified_model_manager.py
src/libs/models/__init__.py
src/libs/models/legacy_bootstrap.py
src/libs/models/divergence_edge/optimization/optimize.py
src/libs/models/mean_reversion/optimization/optimize.py
src/libs/models/momentum/__init__.py
src/libs/models/momentum/optimization/optimize.py
src/libs/models/momentum/optimization/optimizer.py
src/libs/models/regime_pullback/optimization/optimize.py
src/libs/models/regime_relative_value/optimization/optimize.py
src/libs/models/squeeze_breakout/optimization/scoring_optimize.py
src/libs/models/trend_following/optimization/optimize.py
src/libs/optim_utils/objective.py
src/libs/optim_utils/param_auditor.py
src/libs/optim_utils/two_stage_optimizer.py
```

Tests and handoff:

```text
tests/models/test_import_isolation_mi0.py
plans/coder-to-orchestrator-model-import-isolation-mi0-v1.md
```

The optimization entrypoint edits are limited to replacing their former
registration-intent package import with the explicit bootstrap; the Momentum
optimizer additionally owns its direct concrete legacy-model import because
the Momentum package root is lazy.

## Frozen registry inventories

Fresh-process pre-edit baseline and post-bootstrap evidence agree exactly.
The post-bootstrap inventories are:

ModelRegistry:

```text
DivergenceEdgeScorer
KyleTFI
MeanReversion
Momentum
PriceAction
RegimeClassification
RegimePullbackScorer
RegimeRelativeValueScorer
SqueezeBreakout
SqueezeBreakoutScorer
TrendFollowing
VPINKyle
```

StrategyModelRegistry:

```text
DivergenceEdgeV2
KyleTFIV2
MeanReversionV2
MomentumV2
PriceActionV2
RegimePullbackV2
SqueezeBreakoutV2
VPINKyleV2
```

The MI0 regression checks exact names, registration order, class identity,
Momentum lookup, and StrategyModelV2 lookup after two bootstrap calls.

## Fresh-process import evidence

Importing only:

```python
from libs.models.momentum.adapters.decision_plugin import MomentumDecisionPlugin
```

produced this approved `libs.models` footprint:

```text
libs.models
libs.models.momentum
libs.models.momentum.adapters
libs.models.momentum.adapters.decision_plugin
libs.models.momentum.config
libs.models.momentum.core
```

The following were absent from `sys.modules`:

```text
pandas
libs.contracts.signal
libs.models.base
libs.models.registry
libs.models.strategy_model_v2
libs.models.strategy_registry
libs.models.momentum.model
libs.models.momentum.strategy_v2
```

The pre-edit fresh-process plugin import loaded the legacy registry/base and
strategy surfaces, pandas, the Momentum legacy modules, and unrelated concrete
model packages; the post-edit process did not load any of those modules.

Plain `import libs.models` left both concrete registries empty in a fresh
process. Explicit bootstrap populated both inventories, and a second call
preserved names, order, and class identities.

## Validation

- MI0 fresh-process/import-isolation tests: **7 passed**.
- Momentum tests plus MI0 isolation tests: **62 passed**.
- Primary affected managers, optimization, Momentum, and complete
  `tests/decision`: **524 passed, 1 existing Optuna warning**.
- Additional model/strategy/optimizer compatibility selection:
  **234 passed, 15 existing deprecation warnings**.
- `compileall` for changed model, optimization, strategy-manager, script, and
  MI0 test surfaces: passed.
- `git diff --check`: passed.
- Exact plain-import scan and AST guard: zero matches.
- Fresh-process import boundary: passed.
- Repository-local cache cleanup: completed; no MI0 `__pycache__` or
  `.pytest_cache` directories remain.

The full `tests/models` collection was also attempted. Collection remains
blocked by the unrelated pre-existing missing research module:

```text
libs.models.trendlines.workflows.research.binance
```

That research surface was not modified or used as a reason to widen MI0.

### Static validation qualification

The MI0-owned/new files pass Ruff and `ruff format --check`. The migrated
caller import blocks pass the Ruff import-order check. A full diagnostic
comparison against the source base shows no new Ruff diagnostics; existing
non-MI0 findings in the touched legacy files remain unchanged (including
pre-existing formatting, unused-import, logging, and modernization findings).
No unrelated cleanup was mixed into this package.

## Two-pass self-review

### Pass 1 — compatibility and correctness

- `libs.models` no longer performs hidden discovery.
- Decision Momentum import cannot load legacy registries, pandas, signal
  contracts, legacy base classes, or unrelated concrete model packages.
- Both legacy registries retain their exact inventories and class identities.
- Repeated explicit bootstrap is deterministic and repeat-safe.
- Momentum public legacy exports still resolve when explicitly requested.
- Strategy managers and affected optimization entrypoints resolve their models
  through the explicit boundary.
- No model math, configuration, timing, or Decision semantics changed.

### Pass 2 — architecture and scope

- There is one named full-discovery boundary and no getter fallback.
- No registry/plugin framework, entry-point discovery, or generic lazy loader
  was added.
- Only the migrated Momentum package root is lazy; other model families were
  not refactored.
- No Decision registration/integration, RSI/MACD semantics, Docker, D11, or
  legacy application behavior redesign was introduced.
- The remaining full `tests/models` collection issue is an unrelated research
  module gap, not hidden by MI0.

## Deferred gates and residual risk

- `MOMENTUM_RSI_MACD_CANONICAL_FEATURE_SEMANTICS_REQUIRED_BEFORE_INTEGRATION`
  remains open for the next M3 package.
- `SR_MODEL_STATE_GROWTH_REVIEW_REQUIRED_BEFORE_PRODUCTION_CUTOVER` remains
  open from the prior package.
- The unrelated trendline research collection gap remains outside MI0.
- MI0 does not authorize Decision Momentum registration, lane creation,
  LIVE/REPLAY integration testing, deployment, or signal/strategy retirement.

No MI0 commit, merge, push, or external runtime mutation was performed.

MODEL_PLUGIN_IMPORT_ISOLATION_MI0_READY_FOR_REVIEW
