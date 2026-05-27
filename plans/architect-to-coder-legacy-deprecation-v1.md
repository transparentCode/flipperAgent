---
goal: Gradual migration of SqueezeBreakout and MeanReversion from binary threshold models to the scoring model framework via LegacyScoringAdapter
stage: architect-to-coder
date_created: 2026-05-27
last_updated: 2026-05-27
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, legacy-deprecation, migration, scoring-model, phase-5, c-plus]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Architect-to-Coder Handoff: Legacy Model Deprecation — Phase 5 of C-Plus Plan

## 1. Objective

Introduce a `LegacyScoringAdapter` that wraps any `BaseModel` instance and adapts its binary `ModelOutput(direction, conviction)` → `ScoringOutput(edge_score)` via `direction * conviction` normalization. This lets legacy binary models (SqueezeBreakout, MeanReversion) participate directly in the scoring model pipeline and SelectionLayer scoring path — enabling a gradual, config-driven, and reversible migration from the binary threshold framework to the continuous scoring framework.

### Why This Matters

The SelectionLayer already normalizes both `ModelOutput` and `ScoringOutput` into `SelectionCandidate`. However, binary models flow through the `ModelManager → SelectionLayer.normalize_model_output()` path (tagged `source_type="threshold"`), while scoring models flow through `ScoringModelManager → SelectionLayer.normalize_scoring_output()` path (tagged `source_type="scoring"`). These paths apply different filtering rules (e.g., `min_edge_threshold` only applies to scoring outputs). The adapter unifies the pipeline so legacy models can be evaluated under the same scoring rules as native scoring models.

### Prior Decisions (from Memory)

- **C-Plus Architecture (2026-05-27)**: Hybrid evolutionary approach. Phase 5 is "gradual legacy deprecation" — the current task.
- **Phase 1 Complete**: SelectionLayer, ScoringModel ABC, EngineeredFeatureManager, 6 engineered features, 3 selection strategies. 564 tests pass.
- **Phase 3B Complete**: SqueezeBreakout model + MeanReversion enhanced model with SS voters. 486+ tests pass.
- **Native Scoring Models Active**: RegimePullbackScorer and DivergenceEdgeScorer are deployed under `scoring_models:` config.
- **TrendFollowing and Momentum are NOT targeted** for this phase — they are lower priority and can follow the same pattern later.

---

## 2. Scope Boundaries

### In Scope
- `LegacyScoringAdapter` class that wraps a `BaseModel` → `ScoringModel` interface
- `migration_mode` config field in `models.yaml` per model entry
- `ModelManager` changes to partition models by migration mode
- `StrategyWorker` changes to route adapted model outputs through the scoring pipeline
- Comparison logging for A/B validation (shadow mode)
- Unit tests for adapter, config parsing, and comparison logging
- Integration tests validating adapted output equivalence

### Out of Scope (Explicit Non-Goals)
- Rewriting SqueezeBreakout or MeanReversion as native `ScoringModel` subclasses (Phase 2 of deprecation)
- Modifying any existing model evaluation logic (SB and MR code is read-only)
- Modifying SelectionLayer, ScoringModelManager, or ScoringModel ABC
- Modifying RegimePullbackScorer or DivergenceEdgeScorer
- TrendFollowing or Momentum migration (follow-up, same pattern)
- Optimization/backtest integration for adapted models
- Risk, execution, or portfolio layer changes

---

## 3. Affected Symbols, Modules, and Execution Flows

### Current Execution Flow (Before)

```
StrategyWorker.process_features()
├── ModelManager.evaluate(feature_vec) → list[ModelOutput]
│   └── SqueezeBreakout.evaluate() → ModelOutput(direction, conviction)
│   └── MeanReversion.evaluate() → ModelOutput(direction, conviction)
├── ScoringModelManager.evaluate(feature_vec) → list[ScoringOutput]
│   └── RegimePullbackScorer.evaluate() → ScoringOutput(edge_score)
│   └── DivergenceEdgeScorer.evaluate() → ScoringOutput(edge_score)
└── SelectionLayer.select(model_outputs, scoring_outputs, feature_vec)
    ├── normalize_model_output(mo) → SelectionCandidate(source_type="threshold")
    └── normalize_scoring_output(so) → SelectionCandidate(source_type="scoring")
```

### Target Execution Flow (After, with `migration_mode: "adapted"`)

```
StrategyWorker.process_features()
├── ModelManager.evaluate(feature_vec) → list[ModelOutput]
│   └── (models with migration_mode="legacy" only — SB/MR excluded)
├── ModelManager.evaluate_adapted(feature_vec) → list[ScoringOutput]
│   └── LegacyScoringAdapter(SqueezeBreakout).evaluate() → ScoringOutput
│   └── LegacyScoringAdapter(MeanReversion).evaluate() → ScoringOutput
├── ModelManager.evaluate_shadow(feature_vec) → list[ModelOutput]
│   └── (same SB/MR models, for comparison logging only — NOT sent to SelectionLayer)
├── ScoringModelManager.evaluate(feature_vec) → list[ScoringOutput]
│   └── RegimePullbackScorer, DivergenceEdgeScorer (unchanged)
└── SelectionLayer.select(model_outputs=legacy_only, scoring_outputs=native+adapted, feature_vec)
    └── All candidates normalized to SelectionCandidate(source_type="scoring")
```

### Files Modified

| File | Change |
|------|--------|
| `src/apps/strategy_app/model_manager.py` | Add migration_mode parsing in `_load_models()`, add `evaluate_adapted()` and `evaluate_shadow()` methods, partition models into `self.models`, `self.adapted_models`, `self.shadow_models` |
| `src/apps/strategy_app/strategy_worker.py` | Route adapted outputs through scoring pipeline, add comparison logging |
| `configs/models.yaml` | Add `migration_mode` field to SB and MR entries |

### New Files

| File | Purpose |
|------|---------|
| `src/libs/models/legacy_adapter.py` | `LegacyScoringAdapter` class |
| `tests/test_legacy_adapter.py` | Unit tests for adapter |
| `tests/test_migration_workflow.py` | Integration tests for the migration pipeline |

### Files NOT Changed

- `src/libs/models/base.py` — BaseModel ABC untouched
- `src/libs/models/scoring_base.py` — ScoringModel ABC untouched
- `src/libs/models/squeeze_breakout/model.py` — read-only, not modified
- `src/libs/models/mean_reversion/model.py` — read-only, not modified
- `src/libs/models/registry.py` — ModelRegistry untouched
- `src/libs/models/scoring_registry.py` — ScoringModelRegistry untouched
- `src/libs/selection/selection_layer.py` — SelectionLayer untouched
- `src/apps/strategy_app/scoring_model_manager.py` — ScoringModelManager untouched
- `src/libs/models/regime_pullback/` — untouched
- `src/libs/models/divergence_edge/` — untouched

---

## 4. Data Contracts and Interfaces

### 4.1 LegacyScoringAdapter

**Location:** `src/libs/models/legacy_adapter.py`

```python
"""LegacyScoringAdapter — wraps a BaseModel to emit ScoringOutput."""

from __future__ import annotations

from typing import Any

import pandas as pd

from libs.contracts.schemas import FeatureVector
from libs.contracts.signal import ScoringOutput
from libs.models.base import BaseModel, ModelMeta
from libs.models.scoring_base import ScoringModel


class LegacyScoringAdapter(ScoringModel):
    """Wraps a BaseModel instance to participate in the scoring pipeline.

    Converts ModelOutput(direction, conviction) → ScoringOutput(edge_score)
    where edge_score = direction * conviction.
    """

    def __init__(self, wrapped: BaseModel) -> None:
        # Do NOT call super().__init__() — we delegate everything to wrapped
        self._wrapped = wrapped
        self.params = wrapped.params

    @property
    def meta(self) -> ModelMeta:
        return self._wrapped.meta

    def _defaults(self) -> dict[str, Any]:
        return self._wrapped._defaults()

    def validate_features(self, available: set[str]) -> list[str]:
        return self._wrapped.validate_features(available)

    def validate_required_fields(self, available: set[str]) -> list[str]:
        return self._wrapped.validate_required_fields(available)

    def evaluate(self, features: FeatureVector) -> ScoringOutput:
        """Evaluate wrapped model, convert ModelOutput → ScoringOutput."""
        model_output = self._wrapped.evaluate(features)
        edge_score = float(model_output.direction) * model_output.conviction
        return ScoringOutput(
            model_name=model_output.model_name,
            asset=model_output.asset,
            timeframe=model_output.timeframe,
            timestamp=model_output.timestamp,
            edge_score=edge_score,
            conviction=model_output.conviction,
            metadata={
                **model_output.metadata,
                "_adapted": True,
                "_original_direction": model_output.direction,
            },
        )

    def batch_evaluate(self, feature_df: pd.DataFrame) -> pd.Series:
        """Batch evaluate via wrapped model's batch_evaluate.

        BaseModel.batch_evaluate() returns int directions (-1, 0, 1).
        In adapted mode, these are treated as edge_scores with implicit
        conviction=1.0, preserving ranking order.
        """
        return self._wrapped.batch_evaluate(feature_df).astype(float)
```

**Design rationale:**
- Does NOT call `super().__init__()` because `ScoringModel.__init__()` expects `params: dict` and would overwrite the wrapped model's internal state.
- `meta` is a property delegating to the wrapped model, not a class attribute. This is safe because `ScoringModel.validate_features()` reads `self.meta`, and the property returns the wrapped model's meta.
- `model_name` in the output preserves the original name (e.g., `"SqueezeBreakout"`, not `"SqueezeBreakout_adapted"`). The `_adapted: True` metadata flag distinguishes adapted outputs. This matters because SelectionLayer overlap-penalized strategy uses `model_name` for deduplication — we want the adapted output to replace, not duplicate, the legacy output.
- `batch_evaluate()` returns float directions for optimization compatibility. Phase 2 (native_scoring rewrite) will add proper continuous edge_scores.

### 4.2 Config Schema: `migration_mode`

**Location:** `configs/models.yaml`

Add an optional `migration_mode` field to each model config entry:

```yaml
models:
  assets:
    BTCUSDT:
      timeframes:
        1h:
          SqueezeBreakout:
            enabled: true
            migration_mode: adapted   # NEW — "legacy" | "adapted" | "native_scoring"
            comparison_logging: true   # NEW — emit shadow comparison logs
            params:
              kama_fast_period: 15
              # ... existing params unchanged ...
          MeanReversion:
            enabled: true
            migration_mode: adapted   # NEW
            comparison_logging: true   # NEW
            params:
              rsi_oversold: 30
              # ... existing params unchanged ...
```

**Migration mode semantics:**

| Mode | ModelManager behavior | Scoring pipeline | SelectionLayer input |
|------|----------------------|------------------|---------------------|
| `"legacy"` (default) | Loaded into `self.models`, evaluated normally | Not involved | `ModelOutput` → `normalize_model_output()` → `source_type="threshold"` |
| `"adapted"` | Loaded into `self.adapted_models` as `LegacyScoringAdapter`. If `comparison_logging: true`, also loaded into `self.shadow_models` (original `BaseModel`). | Adapted output added to scoring pipeline | `ScoringOutput` → `normalize_scoring_output()` → `source_type="scoring"` |
| `"native_scoring"` | Skipped entirely. Model expected in `scoring_models:` config section. | Native ScoringModel handles it | `ScoringOutput` via ScoringModelManager |

**Backward compatibility:** If `migration_mode` is absent, it defaults to `"legacy"`. No existing behavior changes.

### 4.3 Comparison Log Schema

When `comparison_logging: true` and `migration_mode: "adapted"`, the StrategyWorker emits a structured log entry per evaluation:

```python
{
    "event": "legacy_migration_comparison",
    "model_name": "SqueezeBreakout",
    "asset": "BTCUSDT",
    "timeframe": "1h",
    "timestamp": 1716825600.0,
    "legacy": {
        "direction": 1,
        "conviction": 0.75,
        "edge_score_implied": 0.75,   # direction * conviction
    },
    "adapted": {
        "edge_score": 0.75,
        "conviction": 0.75,
        "direction_derived": 1,       # sign(edge_score)
    },
    "match": true,                    # legacy.edge_score_implied == adapted.edge_score
}
```

This log enables offline analysis of whether adapted outputs match legacy outputs (they should, by construction). Discrepancies indicate a bug in the adapter.

---

## 5. Implementation Order

### Step 1: LegacyScoringAdapter (new file)

Create `src/libs/models/legacy_adapter.py` with the class shown in §4.1.

**Acceptance criteria:**
- `LegacyScoringAdapter` wraps any `BaseModel` subclass
- `evaluate()` returns `ScoringOutput` with `edge_score = direction * conviction`
- `batch_evaluate()` returns float Series
- `validate_features()` and `validate_required_fields()` delegate correctly
- Metadata includes `_adapted: True` and `_original_direction`
- Does not modify wrapped model state

### Step 2: Unit Tests for Adapter

Create `tests/test_legacy_adapter.py`:
- Test adapter wraps SqueezeBreakoutModel correctly
- Test adapter wraps MeanReversionModel correctly
- Test `evaluate()` returns correct `ScoringOutput` for long/short/flat signals
- Test `edge_score == direction * conviction` invariant
- Test metadata propagation with `_adapted` flag
- Test `batch_evaluate()` returns float Series matching wrapped model's directions
- Test feature validation delegation
- Test adapter does not mutate wrapped model's internal state (e.g., squeeze history, RSI buffers)

### Step 3: ModelManager Migration Mode Support

Modify `src/apps/strategy_app/model_manager.py`:

1. In `_load_models()`, read `migration_mode` from each model config entry (default: `"legacy"`).
2. Partition models into three lists:
   - `self.models: list[BaseModel]` — models with `migration_mode="legacy"` (unchanged behavior)
   - `self.adapted_models: list[LegacyScoringAdapter]` — models with `migration_mode="adapted"`, wrapped in adapter
   - `self.shadow_models: list[BaseModel]` — models with `migration_mode="adapted"` AND `comparison_logging: true` (original unwrapped model for shadow comparison)
3. Models with `migration_mode="native_scoring"` are skipped with a log message.
4. Add `evaluate_adapted()` method:
   ```python
   def evaluate_adapted(self, features: FeatureVector) -> list[ScoringOutput]:
       outputs: list[ScoringOutput] = []
       for adapter in self.adapted_models:
           try:
               output = adapter.evaluate(features)
               outputs.append(output)
           except Exception as e:
               logger.error(f"Adapted model {adapter.meta.name} failed: {e}", exc_info=True)
       return outputs
   ```
5. Add `evaluate_shadow()` method:
   ```python
   def evaluate_shadow(self, features: FeatureVector) -> list[ModelOutput]:
       outputs: list[ModelOutput] = []
       for model in self.shadow_models:
           try:
               output = model.evaluate(features)
               outputs.append(output)
           except Exception as e:
               logger.error(f"Shadow model {model.meta.name} failed: {e}", exc_info=True)
       return outputs
   ```
6. `validate_feature_coverage()` must validate ALL three lists (legacy, adapted, shadow).

**Key constraint:** The adapted and shadow model instances must be SEPARATE instances to avoid shared mutable state (e.g., SqueezeBreakout's deque buffers). Load the model class twice from the registry with the same params.

### Step 4: StrategyWorker Routing

Modify `src/apps/strategy_app/strategy_worker.py` `process_features()`:

```python
async def process_features(self, payload: dict) -> None:
    try:
        feature_vec = valkey_decode(payload, FeatureVector)
    except Exception as e:
        logger.error(f"Failed to deserialize feature payload: {e}", exc_info=True)
        return

    # Legacy binary models (migration_mode="legacy" only)
    outputs = self.model_manager.evaluate(feature_vec)

    # Native scoring models (RegimePullbackScorer, DivergenceEdgeScorer, etc.)
    scoring_outputs = self.scoring_model_manager.evaluate(feature_vec)

    # Adapted legacy models (migration_mode="adapted")
    adapted_outputs = self.model_manager.evaluate_adapted(feature_vec)
    scoring_outputs.extend(adapted_outputs)

    # Shadow comparison logging
    shadow_outputs = self.model_manager.evaluate_shadow(feature_vec)
    self._log_migration_comparison(adapted_outputs, shadow_outputs)

    # Run selection layer (unchanged interface)
    selected = self.selection_layer.select(
        model_outputs=outputs,
        scoring_outputs=scoring_outputs,
        feature_vec=feature_vec,
    )
    # ... rest unchanged ...
```

Add the comparison logging helper:

```python
def _log_migration_comparison(
    self,
    adapted: list[ScoringOutput],
    shadow: list[ModelOutput],
) -> None:
    """Log comparison between adapted scoring output and shadow binary output."""
    shadow_by_name = {m.model_name: m for m in shadow}
    for adapted_out in adapted:
        name = adapted_out.model_name
        shadow_out = shadow_by_name.get(name)
        if shadow_out is None:
            continue
        implied_edge = float(shadow_out.direction) * shadow_out.conviction
        match = abs(implied_edge - adapted_out.edge_score) < 1e-9
        logger.info(
            "legacy_migration_comparison",
            model_name=name,
            asset=self.asset,
            timeframe=self.timeframe,
            timestamp=adapted_out.timestamp,
            legacy_direction=shadow_out.direction,
            legacy_conviction=shadow_out.conviction,
            legacy_edge_implied=implied_edge,
            adapted_edge=adapted_out.edge_score,
            adapted_conviction=adapted_out.conviction,
            match=match,
        )
        if not match:
            logger.warning(
                f"Migration mismatch for {name}: "
                f"legacy={implied_edge:.6f} vs adapted={adapted_out.edge_score:.6f}"
            )
```

### Step 5: Config Changes

Update `configs/models.yaml` for the initial rollout. Start with ONE model on ONE asset for validation:

```yaml
# Phase 1 rollout: Adapt SqueezeBreakout on BTCUSDT/1h only
BTCUSDT:
  timeframes:
    1h:
      SqueezeBreakout:
        enabled: true
        migration_mode: adapted       # ← NEW
        comparison_logging: true       # ← NEW
        params: { ... }               # existing params unchanged
      MeanReversion:
        enabled: true
        migration_mode: legacy         # ← keep legacy until SB validated
        params: { ... }
```

After SB is validated on BTCUSDT/1h, expand to remaining assets, then repeat for MR.

### Step 6: Integration Tests

Create `tests/test_migration_workflow.py`:
- Test `ModelManager` with `migration_mode: "legacy"` loads model into `self.models` (backward compat)
- Test `ModelManager` with `migration_mode: "adapted"` loads adapter into `self.adapted_models`
- Test `ModelManager` with `migration_mode: "adapted"` + `comparison_logging: true` also loads shadow model
- Test `ModelManager` with `migration_mode: "native_scoring"` skips the model
- Test `evaluate_adapted()` returns `ScoringOutput` list
- Test `evaluate_shadow()` returns `ModelOutput` list
- Test shadow and adapted instances are separate (no shared state)
- Test that absent `migration_mode` defaults to `"legacy"`
- Test StrategyWorker `process_features()` integrates adapted outputs into scoring pipeline
- Test comparison logging emits `match=True` for correct adapter
- End-to-end: SB in adapted mode + RegimePullbackScorer in native mode → SelectionLayer receives both as scoring candidates

---

## 6. Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| 1 | `LegacyScoringAdapter` wraps any `BaseModel` and returns `ScoringOutput` | Unit test |
| 2 | `edge_score == direction * conviction` invariant holds | Unit test with assertion |
| 3 | `migration_mode` absent → defaults to `"legacy"`, zero behavioral change | Integration test + regression test suite |
| 4 | `migration_mode: "adapted"` → model output enters scoring pipeline, not binary pipeline | Integration test |
| 5 | `migration_mode: "native_scoring"` → model is skipped by ModelManager | Integration test |
| 6 | Shadow comparison logs `match=True` for all adapted models | Integration test + log inspection |
| 7 | Adapted and shadow model instances have separate state (no buffer leakage) | Unit test with stateful model (SB deque buffers) |
| 8 | All existing tests pass without modification | `pytest tests/ -q --ignore=tests/e2e` |
| 9 | `validate_feature_coverage()` covers legacy, adapted, and shadow models | Unit test |
| 10 | Config rollback (switch `"adapted"` → `"legacy"`) restores original behavior | Integration test |

---

## 7. Validation Checklist

### Functional
- [ ] Adapter `evaluate()` for SqueezeBreakout: long signal → positive edge_score
- [ ] Adapter `evaluate()` for SqueezeBreakout: flat signal → edge_score == 0.0
- [ ] Adapter `evaluate()` for MeanReversion: short signal → negative edge_score
- [ ] Adapter `evaluate()` for MeanReversion: flat (ADX above threshold) → edge_score == 0.0
- [ ] Adapter `batch_evaluate()` returns float Series matching directions
- [ ] Comparison logging emits structured log with `match=True`
- [ ] Existing 564+ tests pass unchanged

### Bias and Correctness
- [ ] Adapter does not modify temporal ordering of wrapped model's batch evaluation
- [ ] Adapter does not introduce look-ahead bias (it wraps the model's own evaluate, which is already validated)
- [ ] Shadow model uses SEPARATE instance from adapted model (no shared deque state)

### Operational
- [ ] Default `migration_mode` is `"legacy"` — no behavioral change when field is absent
- [ ] Config toggle `"adapted"` → `"legacy"` is reversible with zero code change
- [ ] Comparison mismatch triggers WARNING-level log, not exception
- [ ] Adapted models appear in boot-time feature coverage validation logs

### Non-Regression
- [ ] SelectionLayer behavior unchanged for legacy-mode models
- [ ] ScoringModelManager behavior unchanged (it doesn't know about adapters)
- [ ] TradeSignal publishing path unchanged for selected candidates
- [ ] Existing binary-path models (TrendFollowing, Momentum) unaffected

---

## 8. Migration Workflow (Operational Runbook)

### Phase 1: Shadow Comparison (this handoff)

1. Deploy with SB `migration_mode: "adapted"` + `comparison_logging: true` on BTCUSDT/1h only.
2. Run for 24-48 hours. Verify all comparison logs show `match=True`.
3. Inspect SelectionLayer treatment: compare ranking/penalties for SB as `source_type="scoring"` vs prior `source_type="threshold"` behavior.
4. If validated, expand to remaining SB asset-TF pairs.
5. Repeat for MR: start BTCUSDT/1h, then expand.

### Phase 2: Disable Comparison Logging

Once all legacy models are validated in adapted mode:
1. Set `comparison_logging: false` (removes shadow model overhead).
2. Models now run only through the scoring pipeline.

### Phase 3: Native Scoring Rewrite (future, out of scope)

1. Rewrite SB and MR as native `ScoringModel` subclasses with continuous edge_scores.
2. Register in `ScoringModelRegistry`.
3. Move config entries from `models:` to `scoring_models:`.
4. Set `migration_mode: "native_scoring"` on the old entries (or remove them).
5. Compare native scoring model IC, Sharpe, and edge_score distribution against adapted model.

---

## 9. Architecture Tradeoffs and Rejected Options

### Option A: Modify SelectionLayer to treat threshold and scoring identically
- **Rejected.** The SelectionLayer already handles both via separate normalize methods. The issue is that downstream config (e.g., `min_edge_threshold`) is only applied to scoring outputs. Unifying there would require changing SelectionLayer's filtering logic, which is higher blast radius.

### Option B: Register adapted models in ScoringModelRegistry
- **Rejected.** The ScoringModelRegistry is decorator-based and expects class-level registration. Runtime instance-wrapping doesn't fit the registry pattern. Instead, the ModelManager owns the adapted instances directly.

### Option C: Run adapted models via ScoringModelManager
- **Rejected.** ScoringModelManager reads from `scoring_models:` config key and uses `ScoringModelRegistry.get()`. It would require config duplication (same model in both `models:` and `scoring_models:` sections) and registry confusion. Keeping the adapter logic in ModelManager is simpler and self-contained.

### Option D: Dual-output (send both binary and scoring to SelectionLayer)
- **Rejected.** Would cause duplicate candidates for the same model, confusing overlap penalties and ranking. Each model should produce exactly one candidate per evaluation.

### Chosen: Adapter in ModelManager with shadow comparison
- **Pros:** Single evaluation path, no SelectionLayer changes, config-reversible, comparison-validated, minimal blast radius.
- **Cons:** ModelManager grows three lists instead of one. Acceptable complexity for a migration mechanism.

---

## 10. Blast Radius and Affected Flows

### Direct Impact (will change)
- `ModelManager._load_models()` — model partitioning logic
- `ModelManager.evaluate()` — only runs legacy-mode models (subset of current)
- `StrategyWorker.process_features()` — routing and comparison logging

### Indirect Impact (must verify)
- `StrategyWorker.start()` → calls `model_manager.validate_feature_coverage()` — must validate all three model lists
- `SelectionLayer.select()` — receives adapted outputs as `ScoringOutput`, which it already handles. No code change needed, but the models' behavior in the scoring pipeline should be monitored.
- Optimization harness — if `batch_evaluate()` is used for adapted models, it returns float instead of int directions. Downstream consumers of `batch_evaluate` must handle float type. Check `src/libs/optimization/` for assumptions.

### No Impact
- Ingestion pipeline
- Feature computation pipeline
- ScoringModelManager and its models
- SelectionLayer code
- Risk, execution, portfolio layers

---

## 11. Risks and Validation Checks

| Risk | Mitigation |
|------|-----------|
| Shared mutable state between adapted and shadow model instances (SB deque buffers) | Instantiate TWO separate model instances from the same class+params |
| Adapted model `model_name` collides with legacy model in SelectionLayer overlap penalties | Preserve same `model_name` — adapted output REPLACES legacy output (model is in adapted list, not legacy list) |
| `batch_evaluate()` type change (int→float) breaks optimization | Verify optimization harness handles float Series; add type guard if needed |
| Config migration_mode typo silently defaults to legacy | Validate `migration_mode` value in `_load_models()`, warn on unrecognized values |
| Performance overhead from shadow evaluation | Shadow is optional (`comparison_logging: true`). Disabled in steady state. |

---

## 12. Explicit Non-Goals

- No changes to model evaluation logic (SB squeeze detection, MR RSI+BB logic, etc.)
- No changes to SelectionLayer, ScoringModel ABC, or ScoringModelManager
- No native ScoringModel rewrites of SB or MR (Phase 2)
- No TrendFollowing or Momentum migration (follow-up task, same pattern)
- No changes to optimization or backtest harness (flag for follow-up if `batch_evaluate` type matters)
- No changes to the signal publishing, risk, execution, or portfolio paths

---

*This package is complete enough for the Coder Agent to implement without guessing. All file locations, interfaces, config schema, implementation order, and acceptance criteria are specified. The adapter design is minimal and additive — no existing code is modified except ModelManager and StrategyWorker, and the changes are backward-compatible by default.*
