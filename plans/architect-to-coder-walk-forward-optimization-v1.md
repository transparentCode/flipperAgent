---
goal: Add walk-forward validation, convergence callback, purge bars, and automated OOS evaluation to direction model optimization pipeline
stage: architect-to-coder
date_created: 2026-05-29
last_updated: 2026-05-29
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, optimization, walk-forward, overfitting, direction-models]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Walk-Forward Optimization Infrastructure for Direction Models

## Objective

Upgrade the 4 direction model optimizers (MeanReversion, Momentum, SqueezeBreakout, TrendFollowing) from full-dataset optimization to proper walk-forward validation with purge bars, early-stop convergence, and automated OOS evaluation. This directly addresses the proven overfitting problem (SqueezeBreakout: optimized Sharpe +0.26 vs defaults +0.89; MeanReversion: 3/5 assets negative OOS Sharpe).

The improvements are implemented as **shared infrastructure in `libs/optim_utils/`** and consumed by each model's optimizer — not the other way around.

## Scope Boundaries

### In Scope
- Walk-forward 3-way split (Train → Validate → OOS) with configurable purge bars
- Early-stop convergence callback for single and multi-objective studies
- Automated OOS evaluation with overfitting detection
- Integration into all 4 direction model optimizers
- Backward compatibility: existing `make_objective()` signatures unchanged

### Explicit Non-Goals
- DO NOT adopt MOTPE 3-objective scoring from regression module
- DO NOT adopt HarmonicStabilitySelector / MetaFilterSelector
- DO NOT adopt adaptive thresholds or data-derived constraint floors
- DO NOT adopt benchmark module separation or pipeline_factory pattern
- DO NOT change the scoring functions (`backtest_multi_tp`, `compute_multi_tp_metrics`)
- DO NOT change the hyperparameter search space mechanism (`build_suggest`)
- DO NOT add cross-asset validation or multi-asset optimization
- DO NOT refactor `OptunaRunner` — wrap it, don't replace it

## Affected Symbols, Modules, and Execution Flows

### Files to CREATE (new shared infrastructure)

| File | Purpose | ~Lines |
|------|---------|--------|
| `src/libs/optim_utils/walk_forward.py` | WalkForwardSplitter — 3-way temporal splits with purge bars | ~80 |
| `src/libs/optim_utils/callbacks.py` | ConvergenceCallback — early stop for single + multi-objective | ~50 |

### Files to MODIFY (model optimizers)

| File | Change |
|------|--------|
| `src/libs/models/mean_reversion/optimization/optimizer.py` | Wrap `make_objective()` to operate on train split; add OOS eval |
| `src/libs/models/momentum/optimization/optimizer.py` | Same pattern |
| `src/libs/models/squeeze_breakout/optimization/optimizer.py` | Same pattern |
| `src/libs/models/trend_following/optimization/optimizer.py` | Same pattern (multi-objective variant) |
| `src/libs/optim_utils/runner.py` | Accept `callbacks` list in `OptunaRunner.run()` |
| `configs/optimization.yaml` | Add walk-forward defaults |

### Files NOT Changed
- `src/libs/optim_utils/scoring.py` — scoring functions untouched
- `src/libs/optim_utils/objective.py` — `build_suggest()` and generic `make_objective()` untouched
- `src/libs/optim_utils/cv.py` — existing purged k-fold stays (used by scoring models)
- `src/libs/regression/optimization/*` — reference only, not modified

### Existing Related Code
- `src/libs/optim_utils/cv.py` has `purged_kfold_cv()` — 2-way train/test, used by scoring models. Walk-forward 3-way is a separate concept; do NOT merge them.
- `src/libs/optim_utils/scoring.py` has `split_temporal()` — simple ratio split with no purge. The walk-forward splitter replaces this for optimization but `split_temporal()` stays for other uses.

---

## Data Contracts and Interfaces

### 1. `WalkForwardSplitter` — `libs/optim_utils/walk_forward.py`

```python
"""Walk-forward 3-way temporal splitting with purge bars."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class WalkForwardSplit:
    """Index boundaries for a single Train / Validate / OOS fold."""
    train_start: int
    train_end: int    # exclusive
    val_start: int
    val_end: int      # exclusive
    oos_start: int
    oos_end: int      # exclusive

    @property
    def train_size(self) -> int:
        return self.train_end - self.train_start

    @property
    def val_size(self) -> int:
        return self.val_end - self.val_start

    @property
    def oos_size(self) -> int:
        return self.oos_end - self.oos_start


class WalkForwardSplitter:
    """Single-fold 3-way temporal split with purge bars.

    Layout:
    |--- train ---|-- purge --|--- validate ---|-- purge --|--- OOS ---|

    Default ratios: 60% train, 20% validate, 20% OOS.
    Purge bars create a gap between splits to prevent look-ahead leakage
    from lagged indicators (default: 24 bars = 1 day for 1h data).

    NOTE: This is a single-fold splitter, NOT a rolling walk-forward.
    Rolling walk-forward is deferred to a future iteration. A single
    proper split already eliminates the full-dataset overfitting problem.
    """

    def __init__(
        self,
        train_ratio: float = 0.60,
        val_ratio: float = 0.20,
        oos_ratio: float = 0.20,
        purge_bars: int = 24,
    ):
        assert abs(train_ratio + val_ratio + oos_ratio - 1.0) < 1e-6
        self.train_ratio = train_ratio
        self.val_ratio = val_ratio
        self.oos_ratio = oos_ratio
        self.purge_bars = purge_bars

    def split(self, n_bars: int) -> WalkForwardSplit:
        """Compute index boundaries for the 3-way split.

        Raises ValueError if dataset is too small to accommodate
        purge gaps and minimum segment sizes.
        """
        min_bars = 100 + 2 * self.purge_bars  # minimum viable dataset
        if n_bars < min_bars:
            raise ValueError(
                f"Insufficient data: {n_bars} bars, need >= {min_bars} "
                f"(100 usable + 2×{self.purge_bars} purge)"
            )

        # Compute segment sizes from usable bars (after removing purge gaps)
        usable = n_bars - 2 * self.purge_bars
        train_size = int(usable * self.train_ratio)
        val_size = int(usable * self.val_ratio)
        # OOS gets the remainder to avoid rounding gaps
        oos_size = usable - train_size - val_size

        train_start = 0
        train_end = train_size
        val_start = train_end + self.purge_bars
        val_end = val_start + val_size
        oos_start = val_end + self.purge_bars
        oos_end = oos_start + oos_size

        return WalkForwardSplit(
            train_start=train_start,
            train_end=train_end,
            val_start=val_start,
            val_end=val_end,
            oos_start=oos_start,
            oos_end=oos_end,
        )
```

**Design Rationale:**
- Single-fold (not rolling) because: (a) direction models are fast to evaluate, (b) the immediate problem is full-dataset optimization, and (c) ~2 years of 1h data (17,520 bars) yields decent segment sizes at 60/20/20 split.
- Purge bars default to 24 (1 day at 1h timeframe) — matches the maximum lookback of any indicator in the direction models.
- The regression module's `WalkForwardValidator` uses rolling multi-fold, but that's designed for regression's heavier compute. Direction models can get full value from a simple 3-way split.

### 2. `ConvergenceCallback` — `libs/optim_utils/callbacks.py`

```python
"""Optuna callbacks for optimization convergence detection."""

from __future__ import annotations

import logging
from typing import Optional

import optuna

logger = logging.getLogger("app.optimization")


class ConvergenceCallback:
    """Early-stop when optimization stagnates.

    For single-objective: stops when best value hasn't improved for
    `patience` consecutive trials.

    For multi-objective: stops when the Pareto front size hasn't
    grown for `patience` consecutive trials.

    Does NOT trigger when no feasible trials exist yet — the optimizer
    should keep exploring rather than stop early with zero results.
    """

    def __init__(self, patience: int = 50):
        self._patience = patience
        # Single-objective tracking
        self._best_value: Optional[float] = None
        # Multi-objective tracking
        self._best_front_size: int = 0
        # Shared
        self._stale_count: int = 0

    def __call__(
        self, study: optuna.Study, trial: optuna.trial.FrozenTrial
    ) -> None:
        is_multi = len(study.directions) > 1

        if is_multi:
            n_pareto = len(study.best_trials)
            if n_pareto == 0:
                return  # no feasible region yet
            if n_pareto > self._best_front_size:
                self._best_front_size = n_pareto
                self._stale_count = 0
            else:
                self._stale_count += 1
        else:
            if trial.value is None:
                return  # pruned or failed trial
            if self._best_value is None or trial.value > self._best_value:
                self._best_value = trial.value
                self._stale_count = 0
            else:
                self._stale_count += 1

        if self._stale_count >= self._patience:
            obj_type = "Pareto front" if is_multi else "best value"
            logger.info(
                f"Early stopping: {obj_type} unchanged for "
                f"{self._patience} trials"
            )
            study.stop()
```

**Design Rationale:**
- Single class handles both single- and multi-objective — detects mode from `study.directions`.
- Patience default 50 matches regression module's proven setting.
- Adapted from regression's `_ConvergenceCallback` but generalized for single-objective (which regression doesn't use).

### 3. OOS Evaluation — `evaluate_oos()` function

This is a thin helper function added to each model optimizer (NOT a shared class), because OOS evaluation uses the same model+backtest pattern already in `make_objective()`. A shared version would require abstracting over model-specific scoring functions, which adds complexity for no benefit.

```python
def evaluate_oos(
    feature_df: pd.DataFrame,
    params: dict[str, Any],
    split: WalkForwardSplit,
    timeframe: str = "1h",
    cost_bps: float = 10.0,
    tp_pcts: tuple[float, ...] = (0.015, 0.03, 0.05),
    tp_portions: tuple[float, ...] = (0.40, 0.30, 0.30),
    sl_pct: float = 0.02,
    trail_to_breakeven: bool = True,
) -> dict[str, dict[str, float]]:
    """Run the model with given params on train, validate, and OOS segments.

    Returns
    -------
    dict with keys "train", "validate", "oos", each containing the
    metrics dict from compute_multi_tp_metrics(). Also includes
    "degradation_warning" (bool) if OOS Sharpe < 50% of validate Sharpe.
    """
```

### 4. Changes to `OptunaRunner.run()` — `libs/optim_utils/runner.py`

Add `callbacks` parameter to the `run()` method:

```python
def run(
    self,
    backtest_fn=None,
    objective_fn=None,
    study_name=None,
    callbacks: list | None = None,   # NEW — list of Optuna callbacks
) -> list[TrialResult]:
```

Pass `callbacks` to `study.optimize()`:

```python
study.optimize(
    objective,
    n_trials=self.config.n_trials,
    show_progress_bar=False,
    callbacks=callbacks or [],  # NEW
)
```

### 5. Config Schema — `configs/optimization.yaml`

Add walk-forward defaults under the `optimization.defaults` key:

```yaml
optimization:
  defaults:
    n_trials: 200
    write_back: false
    # Walk-forward validation (NEW)
    walk_forward:
      train_ratio: 0.60
      val_ratio: 0.20
      oos_ratio: 0.20
      purge_bars: 24
    convergence_patience: 50
```

These are defaults; each model schedule can override them.

---

## Implementation Order

### Phase 1: Shared Infrastructure (no model changes)

**Step 1.1: Create `src/libs/optim_utils/walk_forward.py`**
- `WalkForwardSplit` dataclass
- `WalkForwardSplitter` class with `split(n_bars) -> WalkForwardSplit`
- Unit tests: correct split boundaries, purge gap sizes, insufficient data error

**Step 1.2: Create `src/libs/optim_utils/callbacks.py`**
- `ConvergenceCallback` class
- Unit tests: single-objective early stop, multi-objective early stop, no stop when front is empty

**Step 1.3: Add `callbacks` param to `OptunaRunner.run()`**
- Add `callbacks: list | None = None` to signature
- Pass to `study.optimize()`
- No behavioral change when `callbacks=None`

### Phase 2: Model Optimizer Integration (one model at a time)

For each of the 4 model optimizers, apply the same pattern. Start with **MeanReversion** as the reference implementation, then apply to the other 3.

**Step 2.1: MeanReversion optimizer** (reference)

Before (current):
```python
def make_objective(feature_df, timeframe, cost_bps, ...) -> callable:
    close = feature_df["close"].values
    # ... uses full feature_df for both training and scoring
    def objective(trial):
        model = model_cls(params)
        directions = model.batch_evaluate(feature_df)  # FULL dataset
        metrics = compute_multi_tp_metrics(equity_returns, trades, timeframe)
        return metrics["sharpe"] - 0.5 * abs(metrics["max_drawdown"])
    return objective
```

After (walk-forward):
```python
from libs.optim_utils.walk_forward import WalkForwardSplitter, WalkForwardSplit

def make_objective(
    feature_df: pd.DataFrame,
    timeframe: str = "1h",
    cost_bps: float = 10.0,
    tp_pcts: tuple[float, ...] = (0.015, 0.03, 0.05),
    tp_portions: tuple[float, ...] = (0.40, 0.30, 0.30),
    sl_pct: float = 0.02,
    trail_to_breakeven: bool = True,
    *,                              # NEW: keyword-only
    train_ratio: float = 0.60,     # NEW
    val_ratio: float = 0.20,       # NEW
    purge_bars: int = 24,          # NEW
) -> callable:
    """Return an Optuna-compatible objective for MeanReversion.

    Scoring: sharpe - 0.5 * |max_drawdown| using multi-TP backtest.
    Trains on train split, scores on validate split (walk-forward).
    """
    # Split data ONCE before the objective closure
    splitter = WalkForwardSplitter(
        train_ratio=train_ratio,
        val_ratio=val_ratio,
        oos_ratio=1.0 - train_ratio - val_ratio,
        purge_bars=purge_bars,
    )
    split = splitter.split(len(feature_df))

    # Pre-slice for the objective (train is for model warmup context,
    # val is for scoring)
    val_df = feature_df.iloc[split.val_start:split.val_end]
    val_close = val_df["close"].values
    val_high = val_df["high"].values
    val_low = val_df["low"].values

    model_cls = ModelRegistry.get(MODEL_NAME)
    schema = model_cls.meta.hyperparameter_schema

    def objective(trial: optuna.Trial) -> float:
        params: dict[str, Any] = {}
        for pname, pdef in schema.items():
            params[pname] = build_suggest(trial, pname, pdef)

        model = model_cls(params)
        # Score on VALIDATE split only
        directions = model.batch_evaluate(val_df)

        equity_returns, trades = backtest_multi_tp(
            directions.values, val_high, val_low, val_close,
            tp_pcts=tp_pcts, tp_portions=tp_portions,
            sl_pct=sl_pct, commission_bps=cost_bps / 2,
            trail_to_breakeven=trail_to_breakeven,
        )
        metrics = compute_multi_tp_metrics(equity_returns, trades, timeframe)
        return metrics["sharpe"] - 0.5 * abs(metrics["max_drawdown"])

    return objective
```

Key changes:
1. New keyword-only params (`train_ratio`, `val_ratio`, `purge_bars`) with defaults — backward-compatible.
2. `WalkForwardSplitter.split()` called once outside the closure.
3. Objective scores on **validate split** instead of full dataset.
4. Train split is not used inside the objective because direction models are stateless (no fit step). The train split exists for the OOS evaluation report and for future stateful model support.

**Step 2.2: Add `evaluate_oos()` to MeanReversion optimizer**

```python
def evaluate_oos(
    feature_df: pd.DataFrame,
    params: dict[str, Any],
    split: WalkForwardSplit,
    timeframe: str = "1h",
    cost_bps: float = 10.0,
    tp_pcts: tuple[float, ...] = (0.015, 0.03, 0.05),
    tp_portions: tuple[float, ...] = (0.40, 0.30, 0.30),
    sl_pct: float = 0.02,
    trail_to_breakeven: bool = True,
) -> dict[str, dict[str, float]]:
    """Run best params on train, validate, and OOS segments.

    Returns metrics for each segment and a degradation warning.
    """
    model_cls = ModelRegistry.get(MODEL_NAME)
    segments = {
        "train": feature_df.iloc[split.train_start:split.train_end],
        "validate": feature_df.iloc[split.val_start:split.val_end],
        "oos": feature_df.iloc[split.oos_start:split.oos_end],
    }

    results = {}
    model = model_cls(params)

    for seg_name, seg_df in segments.items():
        directions = model.batch_evaluate(seg_df)
        eq_ret, trades = backtest_multi_tp(
            directions.values,
            seg_df["high"].values,
            seg_df["low"].values,
            seg_df["close"].values,
            tp_pcts=tp_pcts, tp_portions=tp_portions,
            sl_pct=sl_pct, commission_bps=cost_bps / 2,
            trail_to_breakeven=trail_to_breakeven,
        )
        results[seg_name] = compute_multi_tp_metrics(eq_ret, trades, timeframe)

    # Degradation check
    val_sharpe = results["validate"]["sharpe"]
    oos_sharpe = results["oos"]["sharpe"]
    results["degradation_warning"] = (
        val_sharpe > 0 and oos_sharpe < 0.5 * val_sharpe
    )

    return results
```

**Step 2.3: Apply pattern to Momentum optimizer**
Same as MeanReversion, plus preserve existing param constraint (`rsi_short_threshold < rsi_long_threshold`).

**Step 2.4: Apply pattern to SqueezeBreakout optimizer**
Same as MeanReversion. No special constraints.

**Step 2.5: Apply pattern to TrendFollowing optimizer**
Same pattern but:
- Multi-objective: returns `tuple[float, float]` (sharpe, win_rate) — unchanged
- `ConvergenceCallback` handles multi-objective automatically via Pareto front tracking
- `evaluate_oos()` returns both objectives for each segment

**Step 2.6: Update `configs/optimization.yaml`**
Add `walk_forward` and `convergence_patience` defaults.

### Phase 3: Wire Callbacks into Runner

Each model's CLI / optimization entry point should pass the convergence callback:

```python
from libs.optim_utils.callbacks import ConvergenceCallback

runner = OptunaRunner(config)
results = runner.run(
    objective_fn=make_objective(feature_df, ...),
    callbacks=[ConvergenceCallback(patience=50)],
)
```

---

## Design Decision: Why Not a Shared `evaluate_oos()`?

Each model optimizer has its own:
- Scoring formula (sharpe - α*|DD|, vs sharpe+win_rate tuple)
- Param constraints (Momentum: rsi thresholds, TrendFollowing: EMA periods)
- Post-processing (`post_process_params`)

A shared `evaluate_oos()` would need to parameterize all of these, making it more complex than 4 copies of a ~25-line function. The per-model pattern is the simpler choice.

## Design Decision: Why Single-Fold, Not Rolling Walk-Forward?

The regression module uses rolling multi-fold walk-forward because regression models are fitted to training data (stateful). Direction models are **stateless** — `batch_evaluate()` uses indicator computations that don't change with training data. A single 60/20/20 split is sufficient to prevent full-dataset overfitting. Rolling walk-forward can be added later if needed.

## Design Decision: Why Train Split Exists If Models Are Stateless

1. **OOS evaluation report** — comparing train vs validate vs OOS metrics requires all three segments.
2. **Future-proofing** — if direction models gain a fit step (e.g., adaptive thresholds), the train split is ready.
3. **Consistency** — the split structure matches the regression module's convention, reducing cognitive load.

---

## Acceptance Criteria

### Functional
- [ ] `WalkForwardSplitter.split()` returns correct index boundaries for various dataset sizes
- [ ] Purge gaps of exactly `purge_bars` exist between all segments
- [ ] `ValueError` raised when dataset is too small
- [ ] `ConvergenceCallback` stops single-objective study after patience trials with no improvement
- [ ] `ConvergenceCallback` stops multi-objective study after patience trials with no Pareto front growth
- [ ] `ConvergenceCallback` does NOT stop when no feasible trials exist
- [ ] Each model's `make_objective()` scores on validate split, not full dataset
- [ ] `evaluate_oos()` returns metrics for all 3 segments
- [ ] Degradation warning fires when OOS Sharpe < 50% of validate Sharpe
- [ ] Existing `make_objective()` signatures accept old positional args without changes
- [ ] `OptunaRunner.run()` accepts and passes callbacks

### Non-Functional
- [ ] No new dependencies — uses only Optuna (already installed) + stdlib
- [ ] Total new code is ≤ 150 lines across the two new files
- [ ] All existing tests pass without modification

---

## Validation Checklist

| Check | How |
|-------|-----|
| Walk-forward split correctness | Unit test: verify boundaries for n=17520 (2yr 1h), purge=24 |
| Purge prevents leakage | Unit test: assert `val_start == train_end + purge_bars` |
| Early stop fires | Unit test: mock study with stale trials, verify `study.stop()` called |
| Backward compat | Unit test: call `make_objective(feature_df, "1h", 10.0, ...)` with old positional args |
| OOS degradation detection | Unit test: mock metrics where OOS Sharpe = 0.3 * val Sharpe |
| Integration smoke test | Run `python -m libs.optim_utils.runner` on BTCUSDT 1h with 20 trials |
| Overfitting reduction | Manual: compare SqueezeBreakout OOS Sharpe before/after on same dataset |

---

## Test Requirements

### Unit Tests — `tests/libs/optim_utils/`

**`test_walk_forward.py`**
```
test_split_boundaries_correct()        — verify train+purge+val+purge+oos = n_bars
test_split_ratios_respected()          — verify segment sizes match ratios ± 1 bar
test_purge_gap_exact()                 — val_start == train_end + purge_bars
test_insufficient_data_raises()        — n_bars < min threshold
test_custom_ratios()                   — 70/15/15 split
test_zero_purge()                      — purge_bars=0 is valid
```

**`test_callbacks.py`**
```
test_single_objective_early_stop()     — patience=5, 5 non-improving trials → stop
test_single_objective_no_stop()        — improving trials → no stop
test_multi_objective_early_stop()      — pareto front stagnates → stop
test_multi_objective_no_stop_empty()   — empty front → no stop (keep exploring)
test_callback_resets_on_improvement()  — improvement resets stale counter
```

**`test_model_optimizer_walk_forward.py`** (integration)
```
test_mean_reversion_uses_val_split()   — verify objective sees val_df, not full df
test_trend_following_multi_obj_oos()   — multi-objective OOS eval returns both metrics
test_evaluate_oos_degradation_flag()   — flag set when OOS << validate
test_backward_compat_positional_args() — old-style call without keyword args works
```

---

## Migration Path

### Backward Compatibility
- New keyword-only params (`train_ratio`, `val_ratio`, `purge_bars`) all have defaults.
- Existing callers using `make_objective(feature_df, "1h", 10.0)` continue to work — they now get walk-forward validation by default.
- `OptunaRunner.run()` with no `callbacks` param behaves identically to today.
- `evaluate_oos()` is a new function — no existing code calls it.

### Rollout
1. Merge shared infrastructure (walk_forward.py, callbacks.py, runner change)
2. Merge MeanReversion optimizer change
3. Run optimization on BTCUSDT 1h, compare OOS metrics to current full-dataset results
4. If validated, merge remaining 3 model optimizers
5. Update optimization schedules in `configs/optimization.yaml` if purge or patience defaults need tuning

### Rollback
If walk-forward causes issues, set `train_ratio=1.0, val_ratio=0.0, purge_bars=0` to revert to full-dataset behavior without code changes.

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Validate split too small for sparse signal models | MeanReversion generates 12-70 trades on full dataset; 20% split may produce <15 trades | Monitor trade count in OOS report; increase val_ratio if needed |
| Purge bars waste data on small datasets | 48 bars lost to 2 purge gaps on 1h data | Make purge_bars configurable per-model; 0 is valid |
| Convergence callback stops too early | Patience=50 may be too aggressive for high-dimensional search spaces | Tune per-model via config; start with 50 (proven in regression) |
| Direction models see less data than before | 60% train (used only for OOS comparison) + 20% val (scoring) vs 100% before | Expected — the whole point is preventing overfitting on unseen data |

---

## Blast Radius Summary

- **Direct impact (d=1):** 4 model optimizer files + `OptunaRunner.run()` + config
- **No downstream breakage:** `make_objective()` signatures are backward-compatible; new params are keyword-only with defaults
- **No upstream impact:** No callers of `make_objective()` outside the optimization CLI entries
- **Execution flows affected:** Model optimization CLI (`python -m scripts.optimize`) — the only consumer of `make_objective()` and `OptunaRunner.run()`
- **Risk level: LOW** — additive changes with backward-compatible signatures; no existing behavior changes unless new params are explicitly passed
