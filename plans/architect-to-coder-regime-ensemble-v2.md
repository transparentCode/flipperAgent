---
goal: Implement RegimeEnsembleBlender — regime-conditioned model weight blending to break the 0.60-0.66 composite score plateau
stage: architect-to-coder
date_created: 2026-05-31
last_updated: 2026-05-31
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, regime-ensemble, scoring-models, blender]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Architect-to-Coder: Regime Ensemble Blender v2

## Objective

Implement a `RegimeEnsembleBlender` that sits between `ScoringModelManager.evaluate()` and `SelectionLayer.select()` inside `StrategyWorker`. The blender receives per-model `ScoringOutput` objects plus a `RegimeFeatures` snapshot, then produces a single `BlendedScoringOutput` that replaces the raw scoring outputs before they reach the selection layer.

**Why:** The current pipeline weights all scoring models equally regardless of regime. Validation notebook (`research/hypothesis_regime_foundation.ipynb`) proved that regime groups have statistically significant differences in model performance (10 significant t-test pairs at α=0.05), but also revealed two critical issues that v1 failed to handle:

1. **p_trending is bimodal** — 91% of BTC 1h bars have p_trending < 0.3, only 3% > 0.7, AC(1) = 0.7978. Soft blending degenerates into hard switching.
2. **CLEAN_TREND and VOLATILE_TREND have opposite return profiles** — CLEAN_TREND_BULL: +15 bps vs VOLATILE_TREND_BULL: -99 bps at h=12 on BTC 1h. Cannot be grouped together.

## Scope Boundaries

### In Scope
- New module `src/libs/models/blender/` with `RegimeEnsembleBlender`
- New contract `BlendedScoringOutput` in `src/libs/contracts/signal.py`
- Additive `REGIME_TO_GROUP` mapping in `src/libs/regime/aggregation/rule_based.py`
- Integration hook in `src/apps/strategy_app/strategy_worker.py`
- Config section in `configs/models.yaml` under `blender:`
- Unit tests for blender logic
- Integration test for StrategyWorker with blender in the loop

### Out of Scope (Explicit Non-Goals)
- No changes to `BaseModel`, `ScoringModel`, or any existing scoring model (MeanReversion, Momentum, SqueezeBreakout)
- No changes to `RegimeOrchestrator`, `FeatureAggregator`, or any regime pipeline component
- No changes to `SelectionLayer` internals — the blender produces outputs the layer already accepts
- No walk-forward weight learning or optimization — v2 uses static config weights, optimization is a follow-up
- No changes to `SignalWorker` or the feature pipeline
- No new indicators

## Affected Symbols, Modules, and Execution Flows

### New Files
| File | Purpose |
|------|---------|
| `src/libs/models/blender/__init__.py` | Package init |
| `src/libs/models/blender/ensemble.py` | `RegimeEnsembleBlender` class |
| `tests/unit/models/blender/test_ensemble.py` | Unit tests |
| `tests/integration/test_strategy_blender.py` | Integration test |

### Modified Files
| File | Change | Blast Radius |
|------|--------|-------------|
| `src/libs/contracts/signal.py` | Add `BlendedScoringOutput` dataclass | LOW — additive, no existing imports affected |
| `src/libs/regime/aggregation/rule_based.py` | Add `REGIME_TO_GROUP` dict constant | LOW — additive constant, no logic changes |
| `src/apps/strategy_app/strategy_worker.py` | Import blender, call between scoring eval and selection | MEDIUM — core pipeline integration point |
| `configs/models.yaml` | Add `blender:` config section | LOW — new key, existing keys untouched |

### Unchanged (Confirming Zero Blast Radius)
- `src/libs/models/base.py` — BaseModel ABC unchanged
- `src/libs/models/scoring_base.py` — ScoringModel unchanged
- `src/libs/models/mean_reversion/` — unchanged
- `src/libs/models/momentum/` — unchanged
- `src/libs/models/squeeze_breakout/` — unchanged
- `src/libs/selection/selection_layer.py` — unchanged (blender output is compatible with existing `ScoringOutput`)
- `src/libs/regime/` — all regime pipeline code unchanged
- `src/apps/signal_app/` — unchanged

## Data Contracts and Interfaces

### Input: RegimeFeatures (existing, from `src/libs/regime/models.py`)

```python
@dataclass
class RegimeFeatures:
    regime: str              # One of 9 labels (e.g., "CLEAN_TREND_BULL")
    p_trending: float        # HMM posterior [0, 1] — bimodal, use as binary gate
    vol_percentile: float    # [0, 100] — continuous, use for interpolation
    changepoint_prob: float  # [0, 1] — BCPD transition probability
    adaptive_period: int
    position_scale: float
    # ... other fields not consumed by blender
```

### Input: ScoringOutput (existing, from `src/libs/contracts/signal.py`)

```python
class ScoringOutput(BaseModel):
    model_name: str
    asset: str
    timeframe: str
    timestamp: float
    edge_score: float    # Continuous, signed (+ = bullish, - = bearish)
    conviction: float    # [0, 1]
    metadata: dict[str, Any]
```

### Output: BlendedScoringOutput (NEW)

```python
class BlendedScoringOutput(BaseModel):
    """Single blended output replacing multiple ScoringOutput objects."""
    model_name: str = "regime_ensemble"
    asset: str
    timeframe: str
    timestamp: float
    edge_score: float       # Weighted sum of model edge_scores
    conviction: float       # Mean conviction of contributing models
    regime_group: str       # Which group was active (for logging/debug)
    transition_decay: float # Applied decay factor [0.15, 1.0]
    mtf_scale: float        # Applied MTF scaling factor
    metadata: dict[str, Any] = Field(default_factory=dict)
```

The `BlendedScoringOutput` must be compatible with `SelectionLayer.normalize_scoring_output()`. Since `SelectionLayer` expects `ScoringOutput`, either:
- (a) Have `BlendedScoringOutput` inherit from `ScoringOutput`, or
- (b) Have the blender return a standard `ScoringOutput` with debug info in `metadata`.

**Decision: Option (b)** — return a standard `ScoringOutput` with `regime_group`, `transition_decay`, and `mtf_scale` in `metadata`. This requires zero changes to `SelectionLayer`.

### Mapping: REGIME_TO_GROUP (NEW, in `rule_based.py`)

```python
REGIME_TO_GROUP: dict[str, str] = {
    "CLEAN_TREND_BULL":     "CLEAN_TREND",
    "CLEAN_TREND_BEAR":     "CLEAN_TREND",
    "CLEAN_TREND_FLAT":     "CLEAN_TREND",
    "VOLATILE_TREND_BULL":  "VOLATILE_TREND",
    "VOLATILE_TREND_BEAR":  "VOLATILE_TREND",
    "VOLATILE_TREND_FLAT":  "VOLATILE_TREND",
    "QUIET_MR_RANGE":       "QUIET_RANGE",
    "QUIET_MR_SQUEEZE":     "SQUEEZE",
    "CHOPPY":               "CHOPPY",
}

ENSEMBLE_GROUPS = ["CLEAN_TREND", "VOLATILE_TREND", "QUIET_RANGE", "SQUEEZE", "CHOPPY", "TRANSITION"]
```

Note: `TRANSITION` is not mapped from any 9-regime label — it is dynamically activated via `changepoint_prob` threshold.

## Implementation Order

### Step 1: Add REGIME_TO_GROUP to rule_based.py

Add the `REGIME_TO_GROUP` dict and `ENSEMBLE_GROUPS` list as module-level constants after the existing `NON_TREND_REGIMES` set definition. Purely additive — no existing code changes.

### Step 2: Add BlendedScoringOutput contract (or skip if using option b)

If using option (b): skip this step, the blender returns standard `ScoringOutput`.

### Step 3: Implement RegimeEnsembleBlender

Create `src/libs/models/blender/ensemble.py`:

```python
class RegimeEnsembleBlender:
    """Regime-conditioned model weight blender.
    
    Blending formula:
    1. Determine regime group from 9-regime label via REGIME_TO_GROUP
    2. Check TRANSITION override: if changepoint_prob > entry_threshold (0.70),
       enter transition state; exit when < exit_threshold (0.30)
    3. Look up per-model weights for the active group: W[group][model_name]
    4. Compute blended score: sum(w_i * edge_score_i)
    5. Apply transition decay: score *= max(floor, 1.0 - changepoint_prob)
    6. Apply MTF scaling if mtf_agreement is available
    """
    
    def __init__(self, config: dict):
        # config contains weights, thresholds, etc.
        ...
    
    def blend(
        self,
        scoring_outputs: list[ScoringOutput],
        regime_features: RegimeFeatures,
        mtf_agreement: str | None = None,
    ) -> ScoringOutput:
        ...
```

#### Blending Logic (Pseudocode)

```python
def blend(self, scoring_outputs, regime_features, mtf_agreement=None):
    # 1. Determine group
    base_group = REGIME_TO_GROUP.get(regime_features.regime, "CHOPPY")
    
    # 2. Transition override (hysteresis)
    if not self._in_transition and regime_features.changepoint_prob > self.entry_threshold:
        self._in_transition = True
    elif self._in_transition and regime_features.changepoint_prob < self.exit_threshold:
        self._in_transition = False
    
    active_group = "TRANSITION" if self._in_transition else base_group
    
    # 3. Look up weights
    weights = self.weights[active_group]  # dict[str, float] keyed by model_name
    
    # 4. Weighted sum
    blended_score = 0.0
    total_weight = 0.0
    mean_conviction = 0.0
    for so in scoring_outputs:
        w = weights.get(so.model_name, 0.0)
        blended_score += w * so.edge_score
        total_weight += abs(w)
        mean_conviction += so.conviction
    
    if len(scoring_outputs) > 0:
        mean_conviction /= len(scoring_outputs)
    
    # 5. Transition decay with floor
    decay = max(self.floor, 1.0 - regime_features.changepoint_prob)
    blended_score *= decay
    
    # 6. MTF scaling
    mtf_scale = 1.0
    if mtf_agreement == "CONFIRMING":
        mtf_scale = self.mtf_confirming_scale   # 1.2
    elif mtf_agreement == "CONFLICTING":
        mtf_scale = self.mtf_conflicting_scale  # 0.5
    blended_score *= mtf_scale
    
    return ScoringOutput(
        model_name="regime_ensemble",
        asset=scoring_outputs[0].asset,
        timeframe=scoring_outputs[0].timeframe,
        timestamp=scoring_outputs[0].timestamp,
        edge_score=blended_score,
        conviction=mean_conviction,
        metadata={
            "regime_group": active_group,
            "base_group": base_group,
            "transition_decay": decay,
            "mtf_scale": mtf_scale,
            "in_transition": self._in_transition,
            "weights_used": weights,
            "input_scores": {so.model_name: so.edge_score for so in scoring_outputs},
        },
    )
```

#### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Direction dimension | Gate component only — NOT a weight dimension | edge_score is already signed; doubling to 36 weights halves samples per cell to ~47–91, overfitting risk |
| TRANSITION behavior | Weighted decay with floor=0.15 + hysteresis (enter 0.70, exit 0.30) | Hard gate causes whipsaw on noisy changepoint_prob; floor preserves 15% exposure during regime shifts |
| p_trending usage | Binary gate (> 0.5 → trending) | 91% of bars < 0.3 makes continuous blending degenerate; binary matches empirical bimodal distribution |
| vol_percentile usage | Continuous — separates CLEAN_TREND vs VOLATILE_TREND | AC > 0.97, fully continuous, suitable for group differentiation |
| Blender output | Standard `ScoringOutput` with debug in metadata | Zero changes to SelectionLayer |
| Weight format | Static config dict, no online learning | Optimization is a follow-up; static weights are testable and debuggable |

#### Statefulness

`RegimeEnsembleBlender` has one piece of state: `self._in_transition` (bool). This is the hysteresis flag for the TRANSITION circuit breaker. It must persist across calls within the same `StrategyWorker` instance lifetime. Since `StrategyWorker` is already a long-lived consumer, this is natural — the blender is instantiated once in `__init__`.

### Step 4: Config Section in models.yaml

Add a `blender:` top-level key in `configs/models.yaml`:

```yaml
blender:
  enabled: true
  transition:
    entry_threshold: 0.70
    exit_threshold: 0.30
    floor: 0.15
  mtf:
    confirming_scale: 1.2
    conflicting_scale: 0.5
  weights:
    CLEAN_TREND:
      mean_reversion: 0.15
      momentum: 0.55
      squeeze_breakout: 0.30
    VOLATILE_TREND:
      mean_reversion: 0.50
      momentum: 0.20
      squeeze_breakout: 0.30
    QUIET_RANGE:
      mean_reversion: 0.60
      momentum: 0.10
      squeeze_breakout: 0.30
    SQUEEZE:
      mean_reversion: 0.15
      momentum: 0.25
      squeeze_breakout: 0.60
    CHOPPY:
      mean_reversion: 0.30
      momentum: 0.10
      squeeze_breakout: 0.60
    TRANSITION:
      mean_reversion: 0.33
      momentum: 0.34
      squeeze_breakout: 0.33
```

**Weight rationale:**
- CLEAN_TREND: Momentum dominates (smooth trends), MR minimal
- VOLATILE_TREND: MR dominates (opposite return profile from clean), momentum suppressed
- QUIET_RANGE: MR sweet spot, momentum suppressed
- SQUEEZE: Squeeze-breakout dominates (vol compression → breakout)
- CHOPPY: SB elevated (vol expansion opportunities), momentum minimal
- TRANSITION: Equal weights as baseline (circuit breaker decay handles risk reduction)

These are initial heuristic weights. Walk-forward IC-based optimization is a follow-up task.

### Step 5: Integration in StrategyWorker

Modify `StrategyWorker.__init__()` to instantiate the blender, and `process_features()` to call it.

**Current flow:**
```
ScoringModelManager.evaluate(feature_vec) → list[ScoringOutput]
                                ↓
SelectionLayer.select(model_outputs, scoring_outputs, feature_vec)
```

**New flow:**
```
ScoringModelManager.evaluate(feature_vec) → list[ScoringOutput]
                                ↓
RegimeEnsembleBlender.blend(scoring_outputs, regime_features, mtf_agreement)
                                ↓  (returns single ScoringOutput)
SelectionLayer.select(model_outputs, [blended_output], feature_vec)
```

**Integration point** (in `process_features`):

```python
scoring_outputs = self.scoring_model_manager.evaluate(feature_vec)

# ... existing adapted_outputs logic ...

# Regime blending (if enabled and regime features available)
if self.blender and "regime" in feature_vec.features:
    from libs.regime.models import RegimeFeatures
    regime_snapshot = feature_vec.features.get("regime_snapshot")
    if regime_snapshot:
        blended = self.blender.blend(
            scoring_outputs=scoring_outputs,
            regime_features=regime_snapshot,
            mtf_agreement=feature_vec.features.get("mtf_agreement"),
        )
        scoring_outputs = [blended]  # Replace raw outputs with blended
```

**Note on regime data availability:** The blender requires `RegimeFeatures` to be present in `feature_vec.features`. This data is produced by the regime pipeline in `SignalWorker` and should already be available as `regime_snapshot` in the feature vector. If it is not currently being published, a small additive change to `SignalWorker` is needed to include it. Verify this during implementation.

### Step 6: Unit Tests

File: `tests/unit/models/blender/test_ensemble.py`

Test cases:
1. **test_clean_trend_weights** — CLEAN_TREND regime applies momentum-heavy weights
2. **test_volatile_trend_weights** — VOLATILE_TREND applies MR-heavy weights
3. **test_transition_entry_hysteresis** — changepoint_prob > 0.70 triggers TRANSITION
4. **test_transition_exit_hysteresis** — changepoint_prob must drop below 0.30 to exit
5. **test_transition_decay_floor** — decay never goes below 0.15
6. **test_mtf_confirming_boost** — MTF agreement multiplies by 1.2
7. **test_mtf_conflicting_penalty** — MTF conflict multiplies by 0.5
8. **test_output_is_scoring_output** — blender returns valid ScoringOutput
9. **test_unknown_regime_falls_back_to_choppy** — unrecognized regime → CHOPPY group
10. **test_empty_scoring_outputs** — graceful handling when no models produce output
11. **test_metadata_contains_debug_info** — regime_group, transition_decay, weights in metadata

### Step 7: Integration Test

File: `tests/integration/test_strategy_blender.py`

Verify that `StrategyWorker.process_features()` with blender enabled produces blended output and that `SelectionLayer` correctly processes the blended `ScoringOutput`.

## Acceptance Criteria

1. `RegimeEnsembleBlender` correctly maps all 9 regime labels to 6 groups
2. TRANSITION hysteresis works: enters at > 0.70, exits at < 0.30, does not oscillate
3. Decay floor of 0.15 is enforced — `blended_score` is never fully suppressed
4. MTF scaling is applied correctly (1.2× confirming, 0.5× conflicting, 1.0× absent)
5. Output is a valid `ScoringOutput` accepted by `SelectionLayer.normalize_scoring_output()`
6. Blender is config-disabled by default (`blender.enabled: false`) until weights are validated
7. All existing tests pass without modification (908+ tests)
8. New unit tests cover all 6 groups, transition hysteresis, decay floor, MTF scaling
9. `metadata` contains `regime_group`, `transition_decay`, `mtf_scale`, `weights_used`, `input_scores`

## Validation Checklist

- [ ] `pytest tests/` passes with all existing + new tests
- [ ] Blender disabled: pipeline behavior identical to pre-change
- [ ] Blender enabled: scoring outputs are blended, selection layer receives single output
- [ ] TRANSITION circuit breaker tested with oscillating changepoint_prob series
- [ ] Config weights sum to ~1.0 per group (not strictly required but good practice)
- [ ] No changes to BaseModel, ScoringModel, or existing model implementations
- [ ] No changes to SelectionLayer internals
- [ ] No changes to regime pipeline

## Residual Risks and Follow-Ups

| Item | Priority | Notes |
|------|----------|-------|
| Walk-forward weight optimization | P1 follow-up | Static weights are heuristic; IC-based walk-forward with ridge regularization λ=0.3 needed |
| PBO (probability of backtest overfitting) | P1 follow-up | Must run after weight optimization to validate out-of-sample stability |
| regime_snapshot availability in feature_vec | Blocking if absent | Verify during implementation; may need small additive change to SignalWorker |
| Per-asset weight overrides | P2 follow-up | BTC vs ETH may have different optimal weights |
| Blender logging/metrics | P2 follow-up | Add Prometheus counters for group activations, transition events |
