---
goal: Two-stage automated optimization pipeline with fANOVA screening and OOS gating
stage: architect-to-coder
date_created: 2026-05-29
last_updated: 2026-05-29
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, optimization, fanova, oos-gate, direction-models]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Architect → Coder: Two-Stage Automated Optimizer

## Objective

Create a shared two-stage optimization pipeline in `libs/optim_utils/` that automates the full parameter analysis and deployment workflow currently done manually. The pipeline:

1. **Stage 1 (Screening):** Runs a short Optuna study, computes fANOVA importances, and auto-classifies params into FREEZE vs OPTIMIZE.
2. **Stage 2 (Focused + Gate):** Runs the main study on the reduced search space using `PartialFixedSampler`, then gates deployment on OOS performance.

Must work for all 4 direction models without modifying any per-model optimizer file.

## Scope Boundaries

### In Scope
- One new file: `src/libs/optim_utils/two_stage_optimizer.py`
- One new dataclass: `TwoStageResult` in `src/libs/contracts/optimization.py`
- Config additions to `configs/optimization.yaml` (screening section)
- Tests in `tests/test_two_stage_optimizer.py`

### Explicit Non-Goals
- NOT modifying any per-model optimizer (`mean_reversion/`, `momentum/`, `squeeze_breakout/`, `trend_following/`)
- NOT modifying `OptunaRunner`, `walk_forward.py`, `callbacks.py`, or `objective.py`
- NOT implementing rolling walk-forward or k-fold CV (single-fold 60/20/20 stays)
- NOT adding perturbation sensitivity analysis to the automated pipeline (fANOVA alone is sufficient for screening; perturbation is a human-driven research tool)
- NOT implementing auto-deployment to live configs (the pipeline returns a result; deployment is a separate concern)

## Affected Symbols, Modules, and Execution Flows

### New Symbols
| Symbol | File | Type |
|--------|------|------|
| `TwoStageOptimizer` | `src/libs/optim_utils/two_stage_optimizer.py` | Class |
| `TwoStageResult` | `src/libs/contracts/optimization.py` | Dataclass |
| `ScreeningSummary` | `src/libs/contracts/optimization.py` | Dataclass |

### Consumed (Read-Only, No Changes)
| Symbol | File | Usage |
|--------|------|-------|
| `make_objective()` | Each model's `optimization/optimizer.py` | Called for Stage 1 + Stage 2 objectives |
| `evaluate_oos()` | Each model's `optimization/optimizer.py` | Called for OOS gate |
| `post_process_params()` | Each model's `optimization/optimizer.py` | Applied to best params |
| `STUDY_DEFAULTS` | Each model's `optimization/optimizer.py` | Read for sampler type + directions |
| `MODEL_NAME` | Each model's `optimization/optimizer.py` | Read for model identity |
| `WalkForwardSplitter` | `libs/optim_utils/walk_forward.py` | Creates train/val/OOS split |
| `ConvergenceCallback` | `libs/optim_utils/callbacks.py` | Passed to Stage 2 study |
| `build_suggest` | `libs/optim_utils/objective.py` | Used in focused objective |
| `backtest_multi_tp` | `libs/optim_utils/scoring.py` | Used in focused objective |
| `compute_multi_tp_metrics` | `libs/optim_utils/scoring.py` | Used in focused objective |
| `ModelRegistry` | `libs/models/registry.py` | Model class lookup |
| `BaseModel.meta.hyperparameter_schema` | `libs/models/base.py` | Schema for param defaults |

### Blast Radius
- **Zero** existing code modified. All new code. No d=1 break risk.
- Downstream consumers: future scheduler or CLI that calls `TwoStageOptimizer.run()`.

## Key Design Decision: `PartialFixedSampler`

The critical design problem is: how to run Stage 2 with a reduced search space while reusing per-model `make_objective()` **without modifying it**.

**Solution: `optuna.samplers.PartialFixedSampler`** (confirmed available in Optuna 4.8.0).

This sampler wraps any base sampler (TPE, NSGA-II) and fixes specified params to given values. The per-model objective still calls `build_suggest()` for all params, but `PartialFixedSampler` intercepts and returns fixed values for frozen params. The base sampler only searches over active params.

```python
# Example: freeze 10 of 13 params, search over 3
frozen_values = {"kama_period": 10, "kama_fast": 5, ...}  # defaults from schema
focused_sampler = optuna.samplers.PartialFixedSampler(
    fixed_params=frozen_values,
    base_sampler=optuna.samplers.TPESampler(seed=42),
)
study = optuna.create_study(sampler=focused_sampler, direction="maximize")
study.optimize(objective, n_trials=200)  # searches only 3 active params
```

**Why this over alternatives:**
- No per-model code changes needed (the objective is unmodified)
- Works with both TPE (single-objective) and NSGA-II (multi-objective TrendFollowing)
- Native Optuna — no monkey-patching or custom Trial wrappers
- Frozen params appear in `study.best_params` for completeness

## Data Contracts / Interfaces

### 1. `TwoStageResult` (add to `src/libs/contracts/optimization.py`)

```python
class ScreeningSummary(BaseModel):
    """Summary of Stage 1 importance screening."""
    screening_trials: int
    importance_threshold: float
    importances: dict[str, float]                  # param_name → fANOVA importance
    frozen_params: dict[str, Any]                  # param_name → frozen value (default)
    active_params: list[str]                       # params that passed screening
    total_params: int
    reduced_params: int


class TwoStageResult(BaseModel):
    """Output of the two-stage automated optimization pipeline."""
    model_name: str
    asset: str
    timeframe: str
    best_params: dict[str, Any]                    # optimized (if deployed) or defaults (if rejected)
    deployed: bool                                 # True = optimized params, False = fell back to defaults
    rejection_reason: Optional[str] = None         # why OOS gate rejected, or None
    screening: ScreeningSummary                    # Stage 1 results
    oos_metrics: dict[str, dict[str, float]]       # {train: {...}, validate: {...}, oos: {...}}
    default_params: dict[str, Any]                 # model defaults for reference
    stage2_best_score: Optional[float] = None      # best objective value from Stage 2
    stage2_n_trials: int = 0                       # actual trials run in Stage 2
```

### 2. `TwoStageOptimizer` (new file `src/libs/optim_utils/two_stage_optimizer.py`)

```python
class TwoStageOptimizer:
    """Automated two-stage optimization: importance screening → focused search + OOS gate."""

    def __init__(
        self,
        screening_trials: int = 50,
        main_trials: int = 200,
        importance_threshold: float = 0.05,
        convergence_patience: int = 50,
        oos_sharpe_ratio: float = 0.50,
        seed: int = 42,
    ):
        """
        Parameters
        ----------
        screening_trials : int
            Number of trials for Stage 1 (fANOVA screening). Default 50.
        main_trials : int
            Number of trials for Stage 2 (focused optimization). Default 200.
        importance_threshold : float
            fANOVA importance below this → param is frozen to its default.
            Default 0.05 (5%).
        convergence_patience : int
            Early stop patience for Stage 2. Default 50.
        oos_sharpe_ratio : float
            OOS Sharpe must be >= this fraction of validate Sharpe to pass gate.
            Default 0.50 (50%).
        seed : int
            Random seed for reproducibility. Default 42.
        """
        ...

    def run(
        self,
        model_name: str,
        feature_df: pd.DataFrame,
        timeframe: str = "1h",
        cost_bps: float = 10.0,
        tp_pcts: tuple[float, ...] = (0.015, 0.03, 0.05),
        tp_portions: tuple[float, ...] = (0.40, 0.30, 0.30),
        sl_pct: float = 0.02,
        trail_to_breakeven: bool = True,
        train_ratio: float = 0.60,
        val_ratio: float = 0.20,
        purge_bars: int = 24,
    ) -> TwoStageResult:
        """Execute the full two-stage pipeline.

        1. Resolve the per-model optimizer module
        2. Run Stage 1 screening
        3. Classify params via fANOVA
        4. Run Stage 2 with PartialFixedSampler on reduced space
        5. OOS gate on best params
        6. Return TwoStageResult (deployed or rejected)
        """
        ...
```

### 3. Config additions to `configs/optimization.yaml`

```yaml
optimization:
  defaults:
    n_trials: 200
    write_back: false
    walk_forward:
      train_ratio: 0.60
      val_ratio: 0.20
      oos_ratio: 0.20
      purge_bars: 24
    convergence_patience: 50
    # --- NEW: two-stage pipeline settings ---
    two_stage:
      screening_trials: 50
      importance_threshold: 0.05
      oos_sharpe_ratio: 0.50
      seed: 42
```

## Implementation Order

### Step 1: Add contracts (`src/libs/contracts/optimization.py`)

Add `ScreeningSummary` and `TwoStageResult` to the existing optimization contracts file. Place them after the existing `ParamAuditReport` class.

**Acceptance:** imports work from `libs.contracts.schemas`.

### Step 2: Create `src/libs/optim_utils/two_stage_optimizer.py`

Single file, one class. Full implementation below.

**Acceptance:** `from libs.optim_utils.two_stage_optimizer import TwoStageOptimizer` works.

### Step 3: Add config section to `configs/optimization.yaml`

Add the `two_stage:` block under `defaults:`.

**Acceptance:** existing config parsing still works; new keys parseable.

### Step 4: Write tests (`tests/test_two_stage_optimizer.py`)

**Acceptance:** all tests pass with `pytest tests/test_two_stage_optimizer.py`.

## Detailed Implementation: `two_stage_optimizer.py`

```python
"""Two-stage automated optimizer: fANOVA screening → focused search + OOS gate.

Stage 1: Run a quick screening study (all params, fewer trials), compute
         fANOVA importances, classify params as FREEZE or OPTIMIZE.

Stage 2: Run the main study on the reduced search space using Optuna's
         PartialFixedSampler, then gate deployment on OOS performance.

Works for all 4 direction models without modifying per-model optimizers.
"""

from __future__ import annotations

import importlib
import logging
import re
from typing import Any, Optional

import optuna
import pandas as pd

from libs.contracts.optimization import ScreeningSummary, TwoStageResult
from libs.models.registry import ModelRegistry
from libs.optim_utils.callbacks import ConvergenceCallback
from libs.optim_utils.walk_forward import WalkForwardSplitter

logger = logging.getLogger("app.optimization.two_stage")

# Model name → optimizer module path (snake_case convention).
_MODEL_MODULE_MAP: dict[str, str] = {
    "MeanReversion": "libs.models.mean_reversion.optimization.optimizer",
    "Momentum": "libs.models.momentum.optimization.optimizer",
    "SqueezeBreakout": "libs.models.squeeze_breakout.optimization.optimizer",
    "TrendFollowing": "libs.models.trend_following.optimization.optimizer",
}


def _to_snake(name: str) -> str:
    """CamelCase → snake_case (fallback for unknown models)."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _resolve_optimizer_module(model_name: str):
    """Import and return the per-model optimizer module."""
    module_path = _MODEL_MODULE_MAP.get(model_name)
    if module_path is None:
        module_path = f"libs.models.{_to_snake(model_name)}.optimization.optimizer"
    return importlib.import_module(module_path)


class TwoStageOptimizer:
    """Automated two-stage optimization with importance screening and OOS gating."""

    def __init__(
        self,
        screening_trials: int = 50,
        main_trials: int = 200,
        importance_threshold: float = 0.05,
        convergence_patience: int = 50,
        oos_sharpe_ratio: float = 0.50,
        seed: int = 42,
    ) -> None:
        self.screening_trials = screening_trials
        self.main_trials = main_trials
        self.importance_threshold = importance_threshold
        self.convergence_patience = convergence_patience
        self.oos_sharpe_ratio = oos_sharpe_ratio
        self.seed = seed

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        model_name: str,
        feature_df: pd.DataFrame,
        timeframe: str = "1h",
        cost_bps: float = 10.0,
        tp_pcts: tuple[float, ...] = (0.015, 0.03, 0.05),
        tp_portions: tuple[float, ...] = (0.40, 0.30, 0.30),
        sl_pct: float = 0.02,
        trail_to_breakeven: bool = True,
        train_ratio: float = 0.60,
        val_ratio: float = 0.20,
        purge_bars: int = 24,
    ) -> TwoStageResult:
        """Execute the full two-stage pipeline and return the result."""
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        mod = _resolve_optimizer_module(model_name)
        model_cls = ModelRegistry.get(model_name)
        schema = model_cls.meta.hyperparameter_schema
        default_params = {k: v.default for k, v in schema.items()}
        study_defaults = getattr(mod, "STUDY_DEFAULTS", {})
        is_multi = study_defaults.get("directions") is not None and len(study_defaults.get("directions", [])) > 1

        # Shared kwargs for make_objective / evaluate_oos
        obj_kwargs: dict[str, Any] = dict(
            feature_df=feature_df,
            timeframe=timeframe,
            cost_bps=cost_bps,
            tp_pcts=tp_pcts,
            tp_portions=tp_portions,
            sl_pct=sl_pct,
            trail_to_breakeven=trail_to_breakeven,
            train_ratio=train_ratio,
            val_ratio=val_ratio,
            purge_bars=purge_bars,
        )

        # ── Stage 1: Screening ──
        logger.info(f"[{model_name}] Stage 1: screening with {self.screening_trials} trials")
        screening_objective = mod.make_objective(**obj_kwargs)
        screening_study = self._create_study(model_name, "screening", study_defaults, is_multi)
        screening_study.optimize(screening_objective, n_trials=self.screening_trials)

        importances = self._compute_importances(screening_study, is_multi)
        frozen_params, active_params = self._classify_params(importances, schema)

        screening = ScreeningSummary(
            screening_trials=self.screening_trials,
            importance_threshold=self.importance_threshold,
            importances=importances,
            frozen_params=frozen_params,
            active_params=active_params,
            total_params=len(schema),
            reduced_params=len(active_params),
        )
        logger.info(
            f"[{model_name}] Screening: {len(frozen_params)} frozen, "
            f"{len(active_params)} active (threshold={self.importance_threshold})"
        )

        # ── Stage 2: Focused optimization ──
        logger.info(f"[{model_name}] Stage 2: focused optimization with {self.main_trials} trials")
        main_objective = mod.make_objective(**obj_kwargs)
        main_study = self._create_study(
            model_name, "focused", study_defaults, is_multi,
            fixed_params=frozen_params if frozen_params else None,
        )
        main_study.optimize(
            main_objective,
            n_trials=self.main_trials,
            callbacks=[ConvergenceCallback(patience=self.convergence_patience)],
        )

        # Extract best params
        best_raw = self._extract_best_params(main_study, is_multi)
        best_params = mod.post_process_params(best_raw)
        best_score = self._extract_best_score(main_study, is_multi)

        # ── OOS Gate ──
        splitter = WalkForwardSplitter(
            train_ratio=train_ratio,
            val_ratio=val_ratio,
            oos_ratio=1.0 - train_ratio - val_ratio,
            purge_bars=purge_bars,
        )
        split = splitter.split(len(feature_df))
        oos_results = mod.evaluate_oos(
            feature_df=feature_df,
            params=best_params,
            split=split,
            timeframe=timeframe,
            cost_bps=cost_bps,
            tp_pcts=tp_pcts,
            tp_portions=tp_portions,
            sl_pct=sl_pct,
            trail_to_breakeven=trail_to_breakeven,
        )

        deployed, rejection_reason = self._apply_oos_gate(oos_results)

        if deployed:
            logger.info(f"[{model_name}] OOS gate PASSED — deploying optimized params")
            final_params = best_params
        else:
            logger.warning(f"[{model_name}] OOS gate REJECTED: {rejection_reason} — falling back to defaults")
            final_params = default_params

        # Remove internal degradation_warning key from oos_metrics
        oos_metrics = {k: v for k, v in oos_results.items() if k != "degradation_warning"}

        return TwoStageResult(
            model_name=model_name,
            asset="",  # caller fills if needed
            timeframe=timeframe,
            best_params=final_params,
            deployed=deployed,
            rejection_reason=rejection_reason,
            screening=screening,
            oos_metrics=oos_metrics,
            default_params=default_params,
            stage2_best_score=best_score,
            stage2_n_trials=len([t for t in main_study.trials if t.values is not None or t.value is not None]),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_study(
        self,
        model_name: str,
        stage: str,
        study_defaults: dict,
        is_multi: bool,
        fixed_params: dict[str, Any] | None = None,
    ) -> optuna.Study:
        """Create an Optuna study with appropriate sampler and direction."""
        if is_multi:
            base_sampler = optuna.samplers.NSGAIISampler(seed=self.seed)
            directions = study_defaults.get("directions", ["maximize", "maximize"])
        else:
            base_sampler = optuna.samplers.TPESampler(seed=self.seed)
            directions = None

        sampler = base_sampler
        if fixed_params:
            sampler = optuna.samplers.PartialFixedSampler(
                fixed_params=fixed_params,
                base_sampler=base_sampler,
            )

        name = f"{model_name}_{stage}"
        if is_multi:
            return optuna.create_study(study_name=name, directions=directions, sampler=sampler)
        else:
            return optuna.create_study(study_name=name, direction="maximize", sampler=sampler)

    def _compute_importances(
        self, study: optuna.Study, is_multi: bool
    ) -> dict[str, float]:
        """Compute fANOVA param importances from a completed study."""
        try:
            if is_multi:
                # For multi-objective, target first objective (typically sharpe)
                importances = optuna.importance.get_param_importances(
                    study, target=lambda t: t.values[0]
                )
            else:
                importances = optuna.importance.get_param_importances(study)
        except Exception as exc:
            logger.warning(f"fANOVA failed ({exc}), treating all params as active")
            importances = {}
        return importances

    def _classify_params(
        self,
        importances: dict[str, float],
        schema: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        """Split params into frozen (below threshold) and active (above).

        If fANOVA returned no importances (error), all params are active.
        Params not in fANOVA output (e.g., categorical rarely-sampled) are active.
        """
        frozen: dict[str, Any] = {}
        active: list[str] = []

        if not importances:
            active = list(schema.keys())
            return frozen, active

        for param_name, pdef in schema.items():
            imp = importances.get(param_name, None)
            if imp is not None and imp < self.importance_threshold:
                frozen[param_name] = pdef.default
            else:
                active.append(param_name)

        # Safety: if ALL params frozen, keep the most important one active
        if not active and importances:
            best_param = max(importances, key=importances.get)
            active.append(best_param)
            frozen.pop(best_param, None)

        return frozen, active

    def _extract_best_params(
        self, study: optuna.Study, is_multi: bool
    ) -> dict[str, Any]:
        """Get best params from single- or multi-objective study."""
        if is_multi:
            # From Pareto front, pick trial with highest first objective (sharpe)
            pareto = study.best_trials
            if not pareto:
                return {}
            best_trial = max(pareto, key=lambda t: t.values[0])
            return dict(best_trial.params)
        else:
            return dict(study.best_params)

    def _extract_best_score(
        self, study: optuna.Study, is_multi: bool
    ) -> float | None:
        """Get best score value from the study."""
        if is_multi:
            pareto = study.best_trials
            if not pareto:
                return None
            return max(t.values[0] for t in pareto)
        else:
            return study.best_value

    def _apply_oos_gate(
        self, oos_results: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """Apply OOS gating rules. Returns (deployed, rejection_reason)."""
        val_sharpe = oos_results.get("validate", {}).get("sharpe", 0.0)
        oos_sharpe = oos_results.get("oos", {}).get("sharpe", 0.0)

        # Rule 1: OOS Sharpe negative when validate positive → REJECT
        if val_sharpe > 0 and oos_sharpe < 0:
            return False, (
                f"OOS Sharpe negative ({oos_sharpe:.3f}) while validate "
                f"positive ({val_sharpe:.3f}) — likely overfit"
            )

        # Rule 2: OOS Sharpe < threshold fraction of validate Sharpe → REJECT
        if val_sharpe > 0 and oos_sharpe < self.oos_sharpe_ratio * val_sharpe:
            return False, (
                f"OOS Sharpe ({oos_sharpe:.3f}) < {self.oos_sharpe_ratio:.0%} of "
                f"validate Sharpe ({val_sharpe:.3f}) — excessive degradation"
            )

        # Rule 3: Both negative → REJECT (no edge found)
        if val_sharpe <= 0 and oos_sharpe <= 0:
            return False, (
                f"Both validate ({val_sharpe:.3f}) and OOS ({oos_sharpe:.3f}) "
                f"Sharpe non-positive — no edge detected"
            )

        return True, None
```

## How It Integrates With Existing Model Optimizers

**Zero changes to per-model files.** The pipeline dynamically imports each model's optimizer module and calls its existing public API:

```
┌─────────────────────────────┐
│   TwoStageOptimizer.run()   │
│   (libs/optim_utils/)       │
└─────────┬───────────────────┘
          │ importlib.import_module()
          ▼
┌─────────────────────────────────────────┐
│ libs.models.{model}.optimization.optimizer │
│                                           │
│  make_objective()  → Stage 1 + Stage 2    │
│  evaluate_oos()    → OOS gate             │
│  post_process_params() → clean best params│
│  STUDY_DEFAULTS    → sampler/direction    │
│  MODEL_NAME        → logging              │
└───────────────────────────────────────────┘
```

The `PartialFixedSampler` wraps the model's normal sampler (TPE or NSGA-II) and intercepts frozen params at the sampler level. The per-model objective function calls `build_suggest()` for ALL params as usual — it's unaware that some are fixed.

### Model-Specific Behavior Matrix

| Model | Objective | Sampler | Score Formula | Multi-Obj |
|-------|-----------|---------|---------------|-----------|
| MeanReversion | Single | TPE | sharpe - 0.5\|mdd\| | No |
| Momentum | Single | TPE | sharpe - 0.3\|mdd\| | No |
| SqueezeBreakout | Single | TPE | sharpe - 0.5\|mdd\| | No |
| TrendFollowing | Multi | NSGA-II | (sharpe, win_rate) | Yes |

For multi-objective (TrendFollowing):
- **fANOVA**: uses `target=lambda t: t.values[0]` to compute importances on the first objective (sharpe)
- **Best params**: selects the Pareto-front trial with highest first objective
- **OOS gate**: gates on `sharpe` from `evaluate_oos()` (same field as single-objective)

## Config Additions

Add under `optimization.defaults` in `configs/optimization.yaml`:

```yaml
    two_stage:
      screening_trials: 50        # Stage 1 trial count
      importance_threshold: 0.05  # fANOVA importance below this → freeze param
      oos_sharpe_ratio: 0.50      # OOS Sharpe must be >= 50% of validate Sharpe
      seed: 42                    # reproducibility seed
```

The coder should NOT create a Pydantic model for this config — it's read as a plain dict by the caller. The `TwoStageOptimizer.__init__()` takes these as explicit keyword arguments.

## Example Usage

```python
import time
import pandas as pd
from libs.optim_utils.data_fetcher import fetch_historical_ohlcv
from libs.optim_utils.scoring_feature_pipeline import build_scoring_feature_df
from libs.optim_utils.two_stage_optimizer import TwoStageOptimizer

# 1. Fetch data + build features
since_ms = int((time.time() - 2 * 365 * 24 * 3600) * 1000)
ohlcv = fetch_historical_ohlcv("BTCUSDT", "1h", since=since_ms, limit=17520)
feature_df = build_scoring_feature_df(ohlcv, "BTCUSDT", "1h")

# 2. Run two-stage pipeline
optimizer = TwoStageOptimizer(
    screening_trials=50,
    main_trials=200,
    importance_threshold=0.05,
    oos_sharpe_ratio=0.50,
)

result = optimizer.run(
    model_name="SqueezeBreakout",
    feature_df=feature_df,
    timeframe="1h",
    cost_bps=10.0,
)

# 3. Inspect result
print(f"Deployed: {result.deployed}")
print(f"Rejection: {result.rejection_reason}")
print(f"Screening: {result.screening.total_params} → {result.screening.reduced_params} params")
print(f"Importances: {result.screening.importances}")
print(f"Frozen: {list(result.screening.frozen_params.keys())}")
print(f"Active: {result.screening.active_params}")
print(f"Best params: {result.best_params}")
print(f"OOS metrics: {result.oos_metrics}")

# 4. Example output (SqueezeBreakout, from evidence):
#    Deployed: False
#    Rejection: OOS Sharpe negative (-0.950) while validate positive (3.040) — likely overfit
#    Screening: 13 → 3 params
#    Frozen: ['kama_period', 'kama_fast', 'kama_slow', 'adx_period', ...]
#    Active: ['mom_period', 'squeeze_lookback', 'ss_threshold']
#    Best params: {defaults}  # fell back because OOS failed
```

## Acceptance Criteria

1. **`TwoStageOptimizer.run()`** completes for all 4 models: MeanReversion, Momentum, SqueezeBreakout, TrendFollowing.
2. **Stage 1 screening** reduces search space (verified: frozen count > 0 for models with > 3 params).
3. **Stage 2** runs with `PartialFixedSampler` — frozen params are constant across all trials (verified in test by checking trial params).
4. **OOS gate** correctly rejects when:
   - OOS Sharpe negative and validate positive
   - OOS Sharpe < 50% of validate Sharpe
   - Both Sharpe values non-positive
5. **OOS gate** correctly deploys when OOS Sharpe passes all rules.
6. **`TwoStageResult`** contains all required fields and is JSON-serializable (Pydantic `.model_dump()`).
7. **No per-model optimizer files are modified.**
8. **Backward-compatible:** existing `OptunaRunner`, `ConvergenceCallback`, `WalkForwardSplitter` unchanged.
9. **All existing tests pass** (`pytest tests/` excluding e2e).

## Validation Checklist

- [ ] `ScreeningSummary` and `TwoStageResult` added to `libs/contracts/optimization.py` and re-exported via `schemas.py`
- [ ] `two_stage_optimizer.py` created in `libs/optim_utils/`
- [ ] `configs/optimization.yaml` has `two_stage` section under `defaults`
- [ ] fANOVA gracefully handles errors (falls back to all-active)
- [ ] `PartialFixedSampler` used for Stage 2 (not a custom objective wrapper)
- [ ] Multi-objective (TrendFollowing) handled: NSGA-II base sampler, `target` for fANOVA, Pareto front selection
- [ ] Safety: if all params would be frozen, at least the most important one stays active
- [ ] OOS gate rules match spec (3 rejection rules)
- [ ] `post_process_params()` applied to best params before OOS evaluation
- [ ] Logging at INFO level for stage transitions and decisions

## Test Requirements (`tests/test_two_stage_optimizer.py`)

### Unit Tests (mock-based, fast)

1. **`test_classify_params_splits_by_threshold`**
   - Given importances `{"a": 0.40, "b": 0.03, "c": 0.01}` and threshold 0.05
   - Assert `active == ["a"]`, `frozen == {"b": default_b, "c": default_c}`

2. **`test_classify_params_all_important`**
   - All importances above threshold → frozen is empty, active is all params

3. **`test_classify_params_all_frozen_keeps_best`**
   - All importances below threshold → most important stays active (safety)

4. **`test_classify_params_empty_importances`**
   - fANOVA failed → all params active (fallback)

5. **`test_oos_gate_rejects_negative_oos`**
   - validate sharpe +2.0, oos sharpe -0.5 → deployed=False

6. **`test_oos_gate_rejects_excessive_degradation`**
   - validate sharpe +2.0, oos sharpe +0.8 (< 50%) → deployed=False

7. **`test_oos_gate_rejects_both_negative`**
   - validate sharpe -0.5, oos sharpe -1.0 → deployed=False

8. **`test_oos_gate_passes_healthy`**
   - validate sharpe +2.0, oos sharpe +1.5 → deployed=True

9. **`test_oos_gate_passes_edge_case_exactly_50pct`**
   - validate sharpe +2.0, oos sharpe +1.0 (exactly 50%) → deployed=True

10. **`test_resolve_optimizer_module`**
    - Verify all 4 model names resolve to correct modules

### Integration Test (requires data, slower — mark with `@pytest.mark.slow`)

11. **`test_full_pipeline_squeeze_breakout`**
    - Use a small synthetic feature_df (e.g., 500 bars of random data)
    - Run `TwoStageOptimizer.run("SqueezeBreakout", ...)` with `screening_trials=10, main_trials=20`
    - Assert result is a valid `TwoStageResult` with all fields populated
    - Assert `screening.total_params == 13` (SB has 13 params)

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| fANOVA fails on small screening studies | Falls back to all-active → runs full search space (slower but correct) | Handled by try/except in `_compute_importances()` |
| `PartialFixedSampler` with NSGA-II has edge cases | Multi-objective screening might behave differently | Test with TrendFollowing specifically |
| Screening trial count too low → noisy importances | Wrong params frozen | Default 50 trials is conservative; configurable |
| Importance threshold too aggressive | Important params frozen | Default 5% is conservative; user can lower |
| OOS gate too strict → rejects everything | Falls back to defaults (safe behavior) | Ratio configurable; 50% is standard |
| Model not in `_MODEL_MODULE_MAP` | Import fails | Fallback to snake_case convention + clear error |
