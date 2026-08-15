---
goal: Restore MI0 legacy registry order and standalone config-alignment bootstrap behavior
stage: coder-to-orchestrator
date_created: 2026-08-15
last_updated: 2026-08-15
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, models, import-isolation, mi0, remediation]
source_base: 327bd03ca403eb40c8dc3bdb3c7d4380e8588a9b
source_worktree: /Users/kajukatli/.devspace/worktrees/flipperAgent-model-import-isolation-mi0
---

# MI0R — model import isolation remediation

## Result

The two bounded MI0 compatibility defects are remediated without changing the
approved import-isolation architecture:

- explicit legacy bootstrap now preserves the exact pre-MI0 registration order
  and class identity for both registries;
- `ConfigManager.validate_feature_model_alignment()` explicitly bootstraps
  legacy registries at its own standalone validation boundary while importing
  `libs.common.config` remains side-effect-free.

No Momentum math/config, Decision integration, RSI/MACD work, optimizer
semantics, Docker, D11, or registry-getter fallback was introduced.

Terminal status:

`MODEL_PLUGIN_IMPORT_ISOLATION_MI0_REMEDIATION_READY_FOR_REVIEW`

## Source and scope

- source base: `327bd03ca403eb40c8dc3bdb3c7d4380e8588a9b`
- worktree: `/Users/kajukatli/.devspace/worktrees/flipperAgent-model-import-isolation-mi0`
- no remediation commit, merge, push, branch switch, reset, or restore was performed

Changed implementation/test files:

```text
src/libs/models/legacy_bootstrap.py
src/libs/common/config.py
tests/models/test_import_isolation_mi0.py
plans/coder-to-orchestrator-model-import-isolation-mi0-remediation-v1.md
```

## Remediation A — exact registry order

`bootstrap_legacy_model_registries()` now mirrors the original sorted
subpackage traversal. At the `momentum` package position it imports
`momentum.model` and `momentum.strategy_v2` explicitly, because the Momentum
package root remains lazy for Decision imports. Other packages retain their
normal package-root imports. No private registry dictionary is reordered and
`ModelRegistry.auto_discover()` was not modified.

Fresh-process post-remediation tuples are exactly:

```text
ModelRegistry:
(
  DivergenceEdgeScorer,
  KyleTFI,
  MeanReversion,
  Momentum,
  PriceAction,
  RegimeClassification,
  RegimePullbackScorer,
  RegimeRelativeValueScorer,
  SqueezeBreakout,
  SqueezeBreakoutScorer,
  TrendFollowing,
  VPINKyle,
)

StrategyModelRegistry:
(
  DivergenceEdgeV2,
  KyleTFIV2,
  MeanReversionV2,
  MomentumV2,
  PriceActionV2,
  RegimePullbackV2,
  SqueezeBreakoutV2,
  VPINKyleV2,
)
```

The second bootstrap call preserves both exact tuples and every registered
class object. `Momentum` resolves to `MomentumModel`, and `MomentumV2` resolves
to `MomentumV2` with the expected module/legacy identity.

The MI0 regression no longer sorts the expected tuples; it compares the exact
ordered values and checks class identity after repeat bootstrap.

## Remediation B — standalone config alignment

Inside `ConfigManager.validate_feature_model_alignment()`, the method now
lazily imports and calls `bootstrap_legacy_model_registries()` immediately
before reading `ModelRegistry`. This keeps ordinary `libs.common.config`
imports free of model discovery while restoring the method's standalone
legacy validation contract.

Fresh-process evidence:

```text
before validator call: ModelRegistry.list_all() == []
validator call:        Momentum is registered
validator result:      warning says Momentum requires missing MACD
```

The regression uses a minimal in-memory ConfigManager state with an enabled
Momentum model and RSI only. It proves known-model validation is not silently
skipped when no earlier legacy bootstrap occurred. Existing mocked
`tests/test_config_alignment.py` behavior remains green.

## Validation

- MI0 isolation plus config-alignment tests: **16 passed**.
- Broad affected selector including Momentum, MI0, config alignment, legacy
  managers/runtime, optimization, and complete `tests/decision`:
  **533 passed, 1 existing Optuna warning**.
- Additional model/strategy/optimizer compatibility selector:
  **234 passed, 15 existing deprecation warnings**.
- Fresh-process exact-order/class-identity probe: passed.
- Fresh-process config-alignment bootstrap/warning probe: passed.
- Ruff on MI0-owned/new files: passed.
- Ruff import-order check on the newly changed config boundary and migrated
  callers: passed.
- `ruff format --check` on MI0-owned/new files: passed.
- `compileall` on changed model/config/optimization/manager/script/test
  surfaces: passed.
- `git diff --check`: passed.
- Plain exact `import libs.models` registration-intent scan: zero matches.
- Decision plugin fresh-process import isolation: preserved and passed.
- Repository-local cache cleanup: completed after validation.

The full `tests/models` collection remains outside this remediation's scope
because it still encounters the unrelated missing research module
`libs.models.trendlines.workflows.research.binance` during collection. No
trendline research files were modified.

## Two-pass self-review

### Pass 1 — compatibility/correctness

- Exact pre-MI0 registry order is restored for both registries.
- Repeated bootstrap preserves order and class identity.
- Momentum legacy and StrategyModelV2 lookups remain valid.
- Plain `libs.models` import remains empty and Decision plugin import remains
  isolated from legacy modules.
- Config alignment now resolves known models in a fresh standalone process and
  still emits missing-feature warnings.
- Importing `ConfigManager` alone does not bootstrap legacy registries.
- Existing managers, optimizers, Momentum tests, and Decision tests remain
  green.

### Pass 2 — scope/architecture

- The fix uses one existing explicit bootstrap boundary; no new registry or
  plugin framework was added.
- No registry getter fallback, private registry reorder, broad lazy import,
  model math change, Decision integration, or configuration change was added.
- The config validator owns its explicit bootstrap because it is a documented
  standalone legacy model/feature validation boundary.
- No M3 RSI/MACD semantics or Decision integration was started.

## Remaining gates

The orchestrator must still independently review and approve MI0 before merge.
M3 RSI/MACD canonical-semantics certification remains the next authorized
package; Decision Momentum integration remains deferred until that gate passes.

MODEL_PLUGIN_IMPORT_ISOLATION_MI0_REMEDIATION_READY_FOR_REVIEW
