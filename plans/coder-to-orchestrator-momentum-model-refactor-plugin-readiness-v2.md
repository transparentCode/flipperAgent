---
goal: Deliver Momentum plugin-readiness refactor with preserved legacy semantics and a thin DecisionModelPlugin adapter
stage: coder-to-orchestrator
date_created: 2026-08-15
last_updated: 2026-08-15
owner: quant-coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, momentum, model-refactor, plugin-readiness]
source_base: e416c4a1f8c7cef64e7bf2419c9e48ba8016f38e
source_worktree: /Users/kajukatli/.devspace/worktrees/flipperAgent-momentum-plugin-refactor-v2
---

# Momentum plugin-readiness refactor V2

## Scope and changed files

Implemented only the approved Momentum package and focused tests in a fresh detached
worktree based on `e416c4a1f8c7cef64e7bf2419c9e48ba8016f38e`.

Production files changed/added:

```text
src/libs/models/momentum/__init__.py
src/libs/models/momentum/config.py
src/libs/models/momentum/core.py
src/libs/models/momentum/model.py
src/libs/models/momentum/adapters/__init__.py
src/libs/models/momentum/adapters/decision_plugin.py
src/libs/models/momentum/features.py                 deleted after zero-use proof
```

Focused tests added:

```text
tests/models/momentum/test_core.py
tests/models/momentum/test_adapters.py
tests/models/momentum/test_momentum_import_boundaries.py
```

The guard test has a unique basename because the repository already contains another
un-packaged `test_import_boundaries.py`; this avoids pytest module identity collisions.

No changes were made to `src/apps/decision_app`, `configs/decision`,
`configs/models.yaml`, `configs/features.yaml`, `configs/selection.yaml`,
`docker-compose.yml`, signal/strategy/risk/execution apps, optimizer infrastructure,
D7B, D11, or Decision integration. No commit, merge, push, branch switch, reset, or
restore was performed.

## Implementation evidence

`MomentumConfig` is frozen and strictly validates keys, integer RSI thresholds,
boolean line-gate configuration, threshold domains/order, and finite non-negative
histogram magnitude. `MomentumObservation`, `MomentumResult`, and
`evaluate_momentum()` are pure deterministic model-owned semantics. Existing strict
threshold boundaries, histogram sign/magnitude, optional same-sign line confirmation,
conviction, and signed score are preserved.

`MomentumModel` remains registered as `Momentum`, retains its original `ModelMeta`,
hyperparameter schema/defaults, required fields, and output metadata. It translates
legacy feature payloads through the core and fails closed for malformed/missing,
non-finite, or out-of-domain evidence. Its pandas batch path preserves BaseModel
ordering/alignment checks, fixes missing `MACD_line` fail-open behavior, and matches
scalar direction semantics. `MomentumV2` remains registered and delegates through the
same path.

`MomentumDecisionPlugin` is a thin structural shared-contract adapter. Its intrinsic
spec is: `momentum@1`, stateless, `decision_capable`, artifact
`momentum.signal.v1`, `on_bar_close`, required features `RSI@1` and `MACD@1`, no
external data, no dependencies, and empty plugin warmup.

It requires a closed causal bar, exact feature versions/cutoffs, finite RSI in
`[0, 100]`, and finite MACD histogram/line evidence. It requests no data, accepts no
state, emits a bounded deterministic artifact, emits a decision only for long/short,
and emits no proposed state. It does not import legacy FeatureVector/ModelOutput,
StrategyModelV2, decision_app, or infrastructure clients.

`test_core.py` freezes explicit finite golden outputs for default, active BTC 1h,
active BTC 4h, and boundary cases. It loads the live `configs/models.yaml` and verifies
the unchanged active maps: BTCUSDT/1h `70,34,true,0.70`, BTCUSDT/4h
`61,37,true,0.35`, and ETHUSDT/4h `55,45,false,0.00` with inherited defaults.

The pre-edit targeted smoke baseline was `11 passed, 106 deselected` under the original
combined `-k` command. Golden expectations are explicit constants, not implementation
outputs. Before deleting the duplicate package manifest, active
sources/tests/scripts/configs were searched and no caller existed; the final scan is
zero references.

## Validation evidence

The worktree has no local `.venv`; commands used the primary interpreter:

```text
/Users/kajukatli/projects/flipperAgent/.venv/bin/python
```

Results:

```text
tests/models/momentum                                      52 passed
Momentum/model/strategy/regime/selection compatibility   319 passed, 18 warnings
tests/decision                                           361 passed
```

The 319-test command covered `tests/models/test_*.py`, Momentum tests,
`tests/test_legacy_adapter.py`, `tests/test_regime_v2.py`, `tests/test_selection_layer.py`,
`tests/commons/test_model_runtime_contract.py`, and
`tests/signals/test_signal_runtime_pairs.py`. Warnings were existing
LegacyScoringAdapter and OpenTelemetry deprecations.

The unscoped `tests/models` collection remains blocked by this unrelated pre-existing
error:

```text
tests/models/trendlines/test_binance_research_loader.py
ModuleNotFoundError: libs.models.trendlines.workflows.research.binance
```

No trendline file was changed. Static and boundary results:

```text
Ruff changed-files check                  passed
Ruff changed-files format check           passed
compileall Momentum package + tests       passed
git diff --check                          passed
import-boundary AST scan                  passed
retired duplicate-manifest scan            0 matches
Momentum package/test .pyc scan           empty
```

The code-intelligence index was refreshed after implementation. No live or network
infrastructure was used.

## Two-pass self-review

### Pass 1 — correctness and quant safety

Confirmed valid finite math and exact boundary parity; score/conviction invariants;
scalar/batch parity; missing-line, invalid-type, non-finite, and RSI-domain fail-closed
behavior; exact plugin feature cutoff/version validation; deterministic repeated plugin
evaluation; neutral output without a ModelDecision; and MomentumV2 delegation through
one semantic core. No timestamp conversion, data access, look-ahead, or state was added.

### Pass 2 — architecture and simplicity

Confirmed one model-owned core, thin legacy wrappers, no generic adapter framework, no
Decision feature/registry/config work, no optimizer redesign, no infrastructure imports
in config/core/adapter, no legacy runtime bridge, and no unrelated model/SR changes.
The deletion was limited to the proven-dead duplicate manifest.

## Residual risks and deferred gates

No profitability, alpha-quality, live parity, or production-cutover claim is made.
These remain explicit later gates:

```text
MOMENTUM_RSI_MACD_CANONICAL_FEATURE_SEMANTICS_REQUIRED_BEFORE_INTEGRATION
MOMENTUM_OPTIMIZER_ACTIVE_CONFIG_NAMESPACE_REVIEW_REQUIRED
SR_MODEL_STATE_GROWTH_REVIEW_REQUIRED_BEFORE_PRODUCTION_CUTOVER
```

The next integration package must select and prove canonical recursive Wilder/EMA
RSI/MACD semantics before wiring Decision shared features or registering this plugin.
D7B was deliberately deferred.

## Final state

The worktree remains detached at the approved base with only expected uncommitted
Momentum package, focused tests, deletion, and this handoff. The primary checkout and
earlier R0 worktree were not modified. No commit, merge, push, branch switch, reset,
or restore was performed.

MOMENTUM_PLUGIN_INTERFACE_REFACTOR_READY_FOR_REVIEW
