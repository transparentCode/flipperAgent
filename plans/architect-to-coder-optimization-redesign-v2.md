---
goal: Redesign optimization layer with per-model optimizer packages, minimal backtester, param auditing/benchmarking, in-memory Optuna studies, and co-located CLI scripts
stage: architect-to-coder
date_created: 2026-05-25
last_updated: 2026-05-25
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, optimization, per-model-optimizer, backtester, param-auditing, cli, cron]
source_agent: Quant Research Architect
target_agent: Coder Agent
supersedes: plans/architect-to-coder-optimization-redesign-v1.md
---

# Architect → Coder: Optimization Layer Redesign v2

## Changes from v1

| Area | v1 Decision | v2 Decision (user-directed) |
|------|-------------|----------------------------|
| Backtester | Out of scope / placeholder `NotImplementedError` | Minimal backtester in `libs/optimization/backtester.py` — replays candles through `model.batch_evaluate()`, computes Sharpe, max drawdown, win rate |
| Monitor storage | TimescaleDB `TrialStore` query | In-memory Optuna study object — monitor reads from study directly |
| Cron overlap | File lock / `fcntl.flock` | Dropped — single CLI script invoked by cron, no locking needed |
| Param write-back target | Direct write to `configs/models.yaml` | Write to **separate** `configs/optimized_params.yaml`. Add auditing/benchmarking step that compares new vs current params and shows performance delta before adoption |
| Script location | Top-level `scripts/` directory | **Co-located** inside each model package: `mean_reversion/scripts/optimize.py`, `mean_reversion/scripts/monitor.py` |
| Shared vs per-model scripts | Shared CLI dispatching to per-model optimizers | **Hybrid** — thin shared entry point + per-model scripts (see recommendation below) |

## Objective

Redesign the optimization layer so that each model is a self-contained package with co-located optimization scripts, a custom optimizer, and a shared backtester for scoring. Add an auditing/benchmarking workflow for param adoption decisions. Keep shared infra (`OptunaRunner`, backtester, param auditing) in `libs/optimization/`.

## Scope Boundaries

### In Scope
- Restructure model files into packages with co-located optimizer and scripts
- Add `BaseOptimizer` ABC and `OptimizerRegistry` to shared optimization infra
- Add `GenericOptimizer` fallback for models without custom optimizers
- **New:** Minimal `Backtester` in `libs/optimization/backtester.py`
- **New:** `ParamAuditor` in `libs/optimization/param_auditor.py` — benchmark new vs current params
- **New:** `param_writeback.py` writes to `configs/optimized_params.yaml` (not `models.yaml`)
- Minor additive change to `OptunaRunner.run()` (optional `objective_fn` param, expose `study` object)
- New Pydantic contracts: `ScheduleEntry`, `OptimizationDefaults`, `OptimizationConfig`, `BacktestResult`, `ParamAuditReport`
- Per-model `scripts/optimize.py` and `scripts/monitor.py` co-located in model packages
- Thin shared entry point `scripts/run_optimization.py` that dispatches to per-model scripts
- New config file `configs/optimization.yaml`
- Per-model optimizer implementations for MeanReversion, TrendFollowing, Momentum
- Update `libs/models/__init__.py` for new package structure
- Update existing tests for new import paths

### Out of Scope (Explicit Non-Goals)
- No changes to `BaseModel`, `ModelMeta`, or `ModelRegistry`
- No changes to `TrialStore` or `trial_store.py` (monitor uses in-memory study, not DB)
- No changes to `StrategyWorker`, `ModelManager`, or any app-level code
- No persistent worker or daemon — optimization is offline CLI + cron only
- No changes to `configs/models.yaml` structure (write-back goes to separate file)
- No Docker/Kubernetes CronJob manifests — document crontab usage only
- No git auto-commit on write-back
- No cron overlap locking — single invocation assumed

## Script Co-location: Architecture Recommendation

**Recommendation: Hybrid approach — per-model scripts + thin shared dispatcher.**

### Structure

```
src/libs/models/mean_reversion/
├── __init__.py
├── model.py                    # MeanReversionModel
├── optimizer.py                # MeanReversionOptimizer
└── scripts/
    ├── __init__.py             # empty
    ├── optimize.py             # CLI runner for this model
    └── monitor.py              # Monitor for this model

src/libs/optimization/          # Shared infra
├── __init__.py
├── base_optimizer.py           # BaseOptimizer ABC
├── backtester.py               # Minimal backtester
├── objective.py                # (existing) make_objective, build_suggest
├── optimizer_registry.py       # OptimizerRegistry + GenericOptimizer
├── param_auditor.py            # ParamAuditReport — compare new vs current
├── param_writeback.py          # Write to configs/optimized_params.yaml
├── runner.py                   # (existing) OptunaRunner
├── schemas.py                  # (existing) re-exports
└── trial_store.py              # (existing, untouched)

scripts/
└── run_optimization.py         # Thin shared dispatcher (optional convenience)
```

### Tradeoffs

| Approach | Pros | Cons |
|----------|------|------|
| **Per-model only** (no shared script) | Maximum self-containment; each model is discoverable as a standalone unit; model authors own their scripts | Duplication of boilerplate (arg parsing, config merge); harder to invoke "optimize all models" |
| **Shared script only** (top-level dispatches) | Single entry point; no boilerplate duplication; easy "optimize all" | Scripts detached from model context; model author must edit a central file; less discoverable |
| **Hybrid** (recommended) | Per-model scripts own model-specific logic; shared dispatcher enables "optimize all" and cron convenience; minimal duplication because per-model scripts import shared `OptimizationCLI` helper | Slightly more files; two ways to invoke (direct or via dispatcher) |

**Chosen: Hybrid.** Each model package has its own `scripts/optimize.py` and `scripts/monitor.py` that can be run directly. A thin `scripts/run_optimization.py` dispatcher can invoke per-model scripts for cron convenience. Per-model scripts import a shared `OptimizationCLI` base class from `libs/optimization/` to eliminate boilerplate duplication.

## Affected Symbols, Modules, and Execution Flows

### Modified Files

| File | Change | Risk |
|------|--------|------|
| `src/libs/models/mean_reversion.py` | Delete after moving to `mean_reversion/model.py` | LOW |
| `src/libs/models/trend_following.py` | Delete after moving to `trend_following/model.py` | LOW |
| `src/libs/models/momentum.py` | Delete after moving to `momentum/model.py` | LOW |
| `src/libs/models/__init__.py` | Update auto-import paths | LOW |
| `src/libs/optimization/runner.py` | Add optional `objective_fn` param, expose `study` property | LOW |
| `src/libs/optimization/__init__.py` | Add new exports | LOW |
| `src/libs/contracts/schemas.py` | Add `ScheduleEntry`, `OptimizationDefaults`, `OptimizationConfig`, `BacktestResult`, `ParamAuditReport` | LOW |
| `tests/models/test_optimization.py` | Verify imports still work | LOW |

### New Files

| File | Purpose |
|------|---------|
| `src/libs/optimization/base_optimizer.py` | `BaseOptimizer` ABC |
| `src/libs/optimization/optimizer_registry.py` | `OptimizerRegistry` + `GenericOptimizer` |
| `src/libs/optimization/backtester.py` | Minimal backtester for optimization scoring |
| `src/libs/optimization/param_auditor.py` | Compare new params vs current, produce delta report |
| `src/libs/optimization/param_writeback.py` | Atomic write to `configs/optimized_params.yaml` |
| `src/libs/models/mean_reversion/__init__.py` | Re-export `MeanReversionModel` |
| `src/libs/models/mean_reversion/model.py` | Model class (moved) |
| `src/libs/models/mean_reversion/optimizer.py` | `MeanReversionOptimizer` |
| `src/libs/models/mean_reversion/scripts/__init__.py` | Empty |
| `src/libs/models/mean_reversion/scripts/optimize.py` | CLI runner for MeanReversion |
| `src/libs/models/mean_reversion/scripts/monitor.py` | Monitor for MeanReversion |
| `src/libs/models/trend_following/` | Same pattern as mean_reversion |
| `src/libs/models/momentum/` | Same pattern as mean_reversion |
| `scripts/run_optimization.py` | Thin shared dispatcher |
| `configs/optimization.yaml` | Schedule + defaults config |
| `configs/optimized_params.yaml` | Output target for optimized params (created by write-back) |

### Execution Flows Unaffected
- `StrategyWorker` → `ModelManager` → `ModelRegistry.get()` → model: **unchanged** (re-export `__init__.py` preserves import path)
- `SignalWorker` → `FeatureVector` publish: **unchanged**
- All existing indicator, feature, ingestion flows: **unchanged**

## Data Contracts and Interfaces

### New Pydantic Schemas (add to `src/libs/contracts/schemas.py`)

```python
class BacktestResult(BaseModel):
    """Output of a backtest run over historical candles."""
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    total_bars: int = 0
    pnl_series: list[float] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParamAuditReport(BaseModel):
    """Comparison of current vs proposed optimized params."""
    model_name: str
    asset: str
    timeframe: str
    current_params: dict[str, Any]
    proposed_params: dict[str, Any]
    current_metrics: dict[str, float]       # BacktestResult metrics for current params
    proposed_metrics: dict[str, float]      # BacktestResult metrics for proposed params
    deltas: dict[str, float]                # metric_name → (proposed - current)
    recommendation: str                      # "adopt" | "reject" | "review"
    reason: str


class ScheduleEntry(BaseModel):
    """Per-model cron schedule entry."""
    cron: str = Field(..., description="Cron expression (e.g., '0 2 * * 1')")
    assets: list[str] = Field(default_factory=list)
    timeframes: list[str] = Field(default_factory=list)
    n_trials: int | None = None
    sampler: str | None = None
    pruner: str | None = None
    objectives: list[str] | None = None
    directions: list[str] | None = None
    write_back: bool = False


class OptimizationDefaults(BaseModel):
    """Global optimization defaults."""
    n_trials: int = 200
    sampler: str = "TPE"
    pruner: str = "MedianPruner"
    write_back: bool = False


class OptimizationConfig(BaseModel):
    """Top-level optimization config matching configs/optimization.yaml."""
    defaults: OptimizationDefaults = Field(default_factory=OptimizationDefaults)
    schedules: dict[str, ScheduleEntry] = Field(default_factory=dict)
```

### Minimal Backtester (new `src/libs/optimization/backtester.py`)

```python
"""Minimal backtester for optimization scoring.

Replays historical candles through model.batch_evaluate() and computes:
- Sharpe ratio (annualized, assuming bar-level returns)
- Max drawdown
- Win rate
- Total trades

Designed for Optuna objective functions — correctness over speed.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import BacktestResult
from libs.models.base import BaseModel

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)

# Annualization factors by common timeframe labels.
_BARS_PER_YEAR: dict[str, int] = {
    "1m": 525_600,
    "5m": 105_120,
    "15m": 35_040,
    "1h": 8_760,
    "4h": 2_190,
    "1d": 365,
}


class Backtester:
    """Replay historical feature data through a model and score the output.

    Usage in an Optuna objective::

        bt = Backtester(feature_df, timeframe="1h")
        result = bt.run(model)
        return result.sharpe

    Parameters
    ----------
    feature_df : pd.DataFrame
        Historical feature DataFrame.  Must contain a ``close`` column and
        all indicator columns the model expects (same format accepted by
        ``model.batch_evaluate()``).  Index must be monotonically increasing
        (temporal ordering enforced by ``BaseModel``).
    timeframe : str
        Candle timeframe for annualization (e.g. "1h", "4h", "1d").
    cost_bps : float
        Round-trip transaction cost in basis points.  Applied per trade entry.
    """

    def __init__(
        self,
        feature_df: pd.DataFrame,
        timeframe: str = "1h",
        cost_bps: float = 10.0,
    ) -> None:
        if "close" not in feature_df.columns:
            raise ValueError("feature_df must contain a 'close' column")
        self.feature_df = feature_df
        self.timeframe = timeframe
        self.cost_bps = cost_bps
        self._ann_factor = _BARS_PER_YEAR.get(timeframe, 8_760)

    def run(self, model: BaseModel) -> BacktestResult:
        """Execute backtest and return scored result."""
        directions = model.batch_evaluate(self.feature_df)
        close = self.feature_df["close"].values
        returns = np.diff(close) / close[:-1]  # simple bar returns

        # Align directions to returns (direction[i] is applied to returns[i+1])
        pos = directions.values[:-1].astype(float)

        # Per-bar strategy returns
        strategy_returns = pos * returns

        # Subtract transaction costs on position changes
        trades = np.diff(np.concatenate([[0.0], pos]))
        trade_mask = trades != 0
        trade_costs = np.abs(trades) * (self.cost_bps / 10_000.0)
        strategy_returns -= trade_costs[: len(strategy_returns)]

        # Metrics
        total_trades = int(np.sum(trade_mask))
        pnl_series = strategy_returns.tolist()

        sharpe = self._sharpe(strategy_returns)
        max_dd = self._max_drawdown(strategy_returns)
        win_rate = self._win_rate(strategy_returns, trade_mask)

        return BacktestResult(
            sharpe=sharpe,
            max_drawdown=max_dd,
            win_rate=win_rate,
            total_trades=total_trades,
            total_bars=len(close),
            pnl_series=pnl_series,
        )

    # ------------------------------------------------------------------
    # Metric helpers
    # ------------------------------------------------------------------

    def _sharpe(self, returns: np.ndarray) -> float:
        """Annualized Sharpe ratio (risk-free rate = 0)."""
        if len(returns) == 0 or np.std(returns) == 0:
            return 0.0
        return float(
            (np.mean(returns) / np.std(returns)) * math.sqrt(self._ann_factor)
        )

    @staticmethod
    def _max_drawdown(returns: np.ndarray) -> float:
        """Maximum drawdown as a negative fraction (e.g. -0.15 = 15% DD)."""
        if len(returns) == 0:
            return 0.0
        cumulative = np.cumprod(1.0 + returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = (cumulative - running_max) / running_max
        return float(np.min(drawdowns))

    @staticmethod
    def _win_rate(returns: np.ndarray, trade_mask: np.ndarray) -> float:
        """Win rate = fraction of trades with positive return.

        Only bars where a position change occurred are counted as trade
        entry points.  The return on those bars determines win/loss.
        """
        # Trim trade_mask to match returns length
        mask = trade_mask[: len(returns)]
        if np.sum(mask) == 0:
            return 0.0
        trade_returns = returns[mask]
        wins = np.sum(trade_returns > 0)
        return float(wins / len(trade_returns))
```

### BaseOptimizer Interface (new `src/libs/optimization/base_optimizer.py`)

```python
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

import optuna

from libs.contracts.schemas import ParamDef
from libs.models.base import BaseModel
from libs.models.registry import ModelRegistry
from libs.optimization.objective import build_suggest


class BaseOptimizer(ABC):
    """Abstract base for per-model optimization strategies.

    Each model can subclass this to define custom objective functions,
    scoring logic, default study configuration, and param post-processing.
    Models without a custom optimizer use GenericOptimizer automatically.
    """

    model_name: str  # Must match ModelRegistry key

    def default_study_config(self) -> dict[str, Any]:
        """Return per-model default overrides for StudyConfig fields.

        Keys should match StudyConfig field names: n_trials, sampler, pruner,
        objectives, directions.  The CLI merges these with global defaults.
        """
        return {}

    def build_objective(
        self,
        backtest_fn: Callable[[BaseModel], dict[str, float]],
    ) -> Callable[[optuna.Trial], float | tuple[float, ...]]:
        """Return an Optuna-compatible objective function.

        Override to implement custom scoring, penalties, or constraints.
        Default implementation delegates to make_objective().
        """
        from libs.optimization.objective import make_objective
        return make_objective(self.model_name, backtest_fn)

    def suggest_params(self, trial: optuna.Trial) -> dict[str, Any]:
        """Map hyperparameter_schema to trial.suggest_* calls.

        Override to add custom parameter dependencies, constraints,
        or conditional search spaces.
        """
        model_cls = ModelRegistry.get(self.model_name)
        params: dict[str, Any] = {}
        for pname, pdef in model_cls.meta.hyperparameter_schema.items():
            params[pname] = build_suggest(trial, pname, pdef)
        return params

    def post_process_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Post-process best params before config write-back.

        Override to apply rounding, constraint enforcement, or
        derived parameter computation.
        """
        return params
```

### OptimizerRegistry (new `src/libs/optimization/optimizer_registry.py`)

```python
from __future__ import annotations

from typing import Type

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.optimization.base_optimizer import BaseOptimizer

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)


class GenericOptimizer(BaseOptimizer):
    """Fallback optimizer using model's hyperparameter_schema + make_objective."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name


class OptimizerRegistry:
    """Registry for per-model optimizers.  Mirrors ModelRegistry pattern."""

    _registry: dict[str, Type[BaseOptimizer]] = {}

    @classmethod
    def register(cls, model_name: str):
        """Decorator: @OptimizerRegistry.register("MeanReversion")."""
        def wrapper(optimizer_cls: Type[BaseOptimizer]):
            cls._registry[model_name] = optimizer_cls
            return optimizer_cls
        return wrapper

    @classmethod
    def get(cls, model_name: str) -> Type[BaseOptimizer]:
        if model_name not in cls._registry:
            raise KeyError(f"Optimizer for '{model_name}' not found in registry.")
        return cls._registry[model_name]

    @classmethod
    def get_or_default(cls, model_name: str) -> BaseOptimizer:
        """Return registered optimizer instance, or GenericOptimizer fallback."""
        if model_name in cls._registry:
            return cls._registry[model_name]()
        logger.warning(
            f"No custom optimizer registered for '{model_name}', "
            "using GenericOptimizer fallback."
        )
        return GenericOptimizer(model_name)

    @classmethod
    def list_all(cls) -> list[str]:
        return list(cls._registry.keys())
```

### OptunaRunner Change (modify `src/libs/optimization/runner.py`)

Add optional `objective_fn` parameter to `run()` and expose `study` as an instance property for monitor access.

```python
def run(
    self,
    backtest_fn: Callable[[BaseModel], dict[str, float]] | None = None,
    study_name: str | None = None,
    objective_fn: Callable[[optuna.Trial], float | tuple[float, ...]] | None = None,
) -> list[TrialResult]:
    """Execute the optimization study and return results.

    If *objective_fn* is provided, use it directly.
    Otherwise, build an objective from *backtest_fn* via make_objective().

    The in-memory ``self.study`` object is preserved after this call
    so that monitors can inspect it without requiring DB access.
    """
    study = self.create_study(study_name)

    if objective_fn is not None:
        objective = objective_fn
    elif backtest_fn is not None:
        objective = make_objective(self.config.model_name, backtest_fn)
    else:
        raise ValueError("Either backtest_fn or objective_fn must be provided.")

    logger.info(
        f"Starting optimization: model={self.config.model_name} "
        f"asset={self.config.asset} tf={self.config.timeframe} "
        f"trials={self.config.n_trials}"
    )

    study.optimize(objective, n_trials=self.config.n_trials, show_progress_bar=False)
    return self._extract_results(study)
```

### Param Auditor (new `src/libs/optimization/param_auditor.py`)

```python
"""Audit and benchmark proposed params against current params.

Runs the backtester with both current and proposed params on the same
historical data and produces a ParamAuditReport with performance deltas.
The user reviews this before deciding to adopt the new params.
"""

from __future__ import annotations

from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import ParamAuditReport
from libs.models.base import BaseModel
from libs.models.registry import ModelRegistry
from libs.optimization.backtester import Backtester

import pandas as pd

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)

# Thresholds for automatic recommendation
_SHARPE_IMPROVEMENT_THRESHOLD = 0.1     # adopt if Sharpe improves by ≥ 0.1
_DRAWDOWN_DEGRADATION_THRESHOLD = 0.05  # reject if max_dd worsens by > 5pp


class ParamAuditor:
    """Compare current vs proposed params via backtesting.

    Usage::

        auditor = ParamAuditor(feature_df, timeframe="1h")
        report = auditor.audit("MeanReversion", "BTCUSDT", "1h",
                               current_params, proposed_params)
        print(report.recommendation)   # "adopt" / "reject" / "review"
        print(report.deltas)           # {"sharpe": +0.3, "max_drawdown": -0.02, ...}
    """

    def __init__(
        self,
        feature_df: pd.DataFrame,
        timeframe: str = "1h",
        cost_bps: float = 10.0,
    ) -> None:
        self.backtester = Backtester(feature_df, timeframe=timeframe, cost_bps=cost_bps)

    def audit(
        self,
        model_name: str,
        asset: str,
        timeframe: str,
        current_params: dict[str, Any],
        proposed_params: dict[str, Any],
    ) -> ParamAuditReport:
        """Run both param sets through the backtester and compare."""
        model_cls = ModelRegistry.get(model_name)

        # Backtest current
        current_model = model_cls(current_params)
        current_result = self.backtester.run(current_model)
        current_metrics = {
            "sharpe": current_result.sharpe,
            "max_drawdown": current_result.max_drawdown,
            "win_rate": current_result.win_rate,
            "total_trades": float(current_result.total_trades),
        }

        # Backtest proposed
        proposed_model = model_cls(proposed_params)
        proposed_result = self.backtester.run(proposed_model)
        proposed_metrics = {
            "sharpe": proposed_result.sharpe,
            "max_drawdown": proposed_result.max_drawdown,
            "win_rate": proposed_result.win_rate,
            "total_trades": float(proposed_result.total_trades),
        }

        # Compute deltas
        deltas = {
            k: proposed_metrics[k] - current_metrics[k]
            for k in current_metrics
        }

        # Automatic recommendation logic
        recommendation, reason = self._recommend(deltas)

        report = ParamAuditReport(
            model_name=model_name,
            asset=asset,
            timeframe=timeframe,
            current_params=current_params,
            proposed_params=proposed_params,
            current_metrics=current_metrics,
            proposed_metrics=proposed_metrics,
            deltas=deltas,
            recommendation=recommendation,
            reason=reason,
        )

        logger.info(
            f"Param audit for {model_name}/{asset}/{timeframe}: "
            f"recommendation={recommendation}, "
            f"sharpe_delta={deltas['sharpe']:+.4f}, "
            f"dd_delta={deltas['max_drawdown']:+.4f}"
        )

        return report

    @staticmethod
    def _recommend(deltas: dict[str, float]) -> tuple[str, str]:
        """Heuristic recommendation based on metric deltas."""
        sharpe_d = deltas.get("sharpe", 0.0)
        dd_d = deltas.get("max_drawdown", 0.0)

        # max_drawdown is negative, so a more negative delta = worse drawdown
        dd_worsened = dd_d < -_DRAWDOWN_DEGRADATION_THRESHOLD

        if dd_worsened:
            return "reject", (
                f"Drawdown worsened by {abs(dd_d):.4f} "
                f"(threshold: {_DRAWDOWN_DEGRADATION_THRESHOLD})"
            )
        if sharpe_d >= _SHARPE_IMPROVEMENT_THRESHOLD:
            return "adopt", (
                f"Sharpe improved by {sharpe_d:+.4f} "
                f"without significant drawdown degradation"
            )
        return "review", (
            f"Sharpe delta {sharpe_d:+.4f} below auto-adopt threshold "
            f"({_SHARPE_IMPROVEMENT_THRESHOLD}); manual review recommended"
        )
```

### Param Write-back (new `src/libs/optimization/param_writeback.py`)

Writes to `configs/optimized_params.yaml` — **NOT** `configs/models.yaml`.

```python
"""Atomic param write-back to configs/optimized_params.yaml."""

import tempfile
from pathlib import Path
from typing import Any

import yaml

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)

OPTIMIZED_PARAMS_PATH = Path("configs/optimized_params.yaml")


def write_best_params(
    model_name: str,
    asset: str,
    timeframe: str,
    params: dict[str, Any],
    config_path: Path = OPTIMIZED_PARAMS_PATH,
) -> None:
    """Atomically write optimized params to configs/optimized_params.yaml.

    Structure::

        models:
          MeanReversion:
            BTCUSDT:
              1h:
                params: {rsi_oversold: 25, ...}
                optimized_at: "2026-05-25T02:00:00Z"

    Does NOT modify configs/models.yaml.  The user reviews the
    ParamAuditReport and manually copies approved params.
    """
    import os
    from datetime import datetime, timezone

    config = _read_yaml(config_path)

    models_node = config.setdefault("models", {})
    model_node = models_node.setdefault(model_name, {})
    asset_node = model_node.setdefault(asset, {})

    old_params = asset_node.get(timeframe, {}).get("params", {})
    asset_node[timeframe] = {
        "params": {**old_params, **params},
        "optimized_at": datetime.now(timezone.utc).isoformat(),
    }

    _write_yaml_atomic(config_path, config)

    logger.info(
        f"Wrote optimized params for {model_name}/{asset}/{timeframe} "
        f"to {config_path}: old={old_params} new={params}"
    )


def read_current_params(
    model_name: str,
    asset: str,
    timeframe: str,
    models_config_path: Path = Path("configs/models.yaml"),
) -> dict[str, Any]:
    """Read current params from configs/models.yaml for audit comparison."""
    config = _read_yaml(models_config_path)
    try:
        return (
            config["models"]["assets"][asset]["timeframes"][timeframe]
            [model_name]["params"]
        )
    except (KeyError, TypeError):
        # Fall back to model defaults if no per-asset/tf override exists
        return {}


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _write_yaml_atomic(path: Path, data: dict[str, Any]) -> None:
    import os
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(dir_path), suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        os.replace(tmp_path, str(path))
    except Exception:
        os.unlink(tmp_path)
        raise
```

## Per-Model Optimizer Implementations

### MeanReversion Optimizer (`src/libs/models/mean_reversion/optimizer.py`)

```python
"""Per-model optimizer for MeanReversion."""

from __future__ import annotations

from typing import Any, Callable

import optuna

from libs.models.base import BaseModel
from libs.models.registry import ModelRegistry
from libs.optimization.base_optimizer import BaseOptimizer
from libs.optimization.backtester import Backtester
from libs.optimization.optimizer_registry import OptimizerRegistry


@OptimizerRegistry.register("MeanReversion")
class MeanReversionOptimizer(BaseOptimizer):
    model_name = "MeanReversion"

    def default_study_config(self) -> dict[str, Any]:
        return {
            "sampler": "TPE",
            "n_trials": 200,
            "pruner": "MedianPruner",
            "objectives": ["sharpe"],
            "directions": ["maximize"],
        }

    def build_objective(
        self, backtest_fn: Callable[[BaseModel], dict[str, float]]
    ) -> Callable[[optuna.Trial], float | tuple[float, ...]]:
        def objective(trial: optuna.Trial) -> float:
            params = self.suggest_params(trial)
            model = ModelRegistry.get(self.model_name)(params)
            metrics = backtest_fn(model)
            # Mean-reversion scoring: sharpe with drawdown penalty
            sharpe = metrics.get("sharpe", 0.0)
            drawdown = abs(metrics.get("max_drawdown", 0.0))
            return sharpe - 0.5 * drawdown
        return objective
```

### TrendFollowing Optimizer (`src/libs/models/trend_following/optimizer.py`)

```python
"""Per-model optimizer for TrendFollowing."""

from __future__ import annotations

from typing import Any, Callable

import optuna

from libs.models.base import BaseModel
from libs.models.registry import ModelRegistry
from libs.optimization.base_optimizer import BaseOptimizer
from libs.optimization.optimizer_registry import OptimizerRegistry


@OptimizerRegistry.register("TrendFollowing")
class TrendFollowingOptimizer(BaseOptimizer):
    model_name = "TrendFollowing"

    def default_study_config(self) -> dict[str, Any]:
        return {
            "sampler": "TPE",
            "n_trials": 300,
            "pruner": "MedianPruner",
            "objectives": ["sharpe", "win_rate"],
            "directions": ["maximize", "maximize"],
        }

    def suggest_params(self, trial: optuna.Trial) -> dict[str, Any]:
        """Custom: enforce ema_fast_period < ema_slow_period constraint."""
        params = super().suggest_params(trial)
        if params["ema_fast_period"] >= params["ema_slow_period"]:
            params["ema_slow_period"] = params["ema_fast_period"] + 1
        return params
```

### Momentum Optimizer (`src/libs/models/momentum/optimizer.py`)

```python
"""Per-model optimizer for Momentum."""

from __future__ import annotations

from typing import Any, Callable

import optuna

from libs.models.base import BaseModel
from libs.models.registry import ModelRegistry
from libs.optimization.base_optimizer import BaseOptimizer
from libs.optimization.optimizer_registry import OptimizerRegistry


@OptimizerRegistry.register("Momentum")
class MomentumOptimizer(BaseOptimizer):
    model_name = "Momentum"

    def default_study_config(self) -> dict[str, Any]:
        return {
            "sampler": "TPE",
            "n_trials": 250,
            "pruner": "MedianPruner",
            "objectives": ["sharpe"],
            "directions": ["maximize"],
        }

    def suggest_params(self, trial: optuna.Trial) -> dict[str, Any]:
        """Custom: enforce rsi_short < rsi_long constraint."""
        params = super().suggest_params(trial)
        if params["rsi_short_threshold"] >= params["rsi_long_threshold"]:
            params["rsi_long_threshold"] = params["rsi_short_threshold"] + 1
        return params
```

### Model Package `__init__.py` Pattern

Each model package re-exports for backward compatibility:

```python
# src/libs/models/mean_reversion/__init__.py
from libs.models.mean_reversion.model import MeanReversionModel  # noqa: F401

# Also trigger optimizer self-registration
import libs.models.mean_reversion.optimizer  # noqa: F401
```

### Updated `src/libs/models/__init__.py`

```python
# Ensure all concrete models and their optimizers are imported so they self-register.
import libs.models.mean_reversion  # noqa: F401
import libs.models.trend_following  # noqa: F401
import libs.models.momentum  # noqa: F401
```

## Per-Model CLI Scripts

### Shared CLI Helper (new method on `BaseOptimizer` or standalone — keep in per-model script to avoid over-abstraction in v1)

### MeanReversion CLI (`src/libs/models/mean_reversion/scripts/optimize.py`)

```python
"""CLI runner for MeanReversion optimization.

Usage:
    python -m libs.models.mean_reversion.scripts.optimize \
        --asset BTCUSDT --timeframe 1h --n-trials 200 --audit

Can also be invoked via the shared dispatcher:
    python scripts/run_optimization.py --model MeanReversion --asset BTCUSDT --timeframe 1h
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure src/ is on sys.path when run as a script
_src = str(Path(__file__).resolve().parents[4])
if _src not in sys.path:
    sys.path.insert(0, _src)

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import StudyConfig
from libs.optimization.backtester import Backtester
from libs.optimization.optimizer_registry import OptimizerRegistry
from libs.optimization.param_auditor import ParamAuditor
from libs.optimization.param_writeback import read_current_params, write_best_params
from libs.optimization.runner import OptunaRunner

# Trigger model + optimizer registration
import libs.models  # noqa: F401

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)

MODEL_NAME = "MeanReversion"
CONFIG_FILE_OPTIMIZATION = "configs/optimization.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Run {MODEL_NAME} optimization study"
    )
    parser.add_argument("--asset", required=True, help="Asset symbol (e.g., BTCUSDT)")
    parser.add_argument("--timeframe", required=True, help="Timeframe (e.g., 1h)")
    parser.add_argument("--n-trials", type=int, default=None)
    parser.add_argument("--sampler", default=None)
    parser.add_argument("--pruner", default=None)
    parser.add_argument("--data-path", required=True,
                        help="Path to historical feature CSV/parquet for backtesting")
    parser.add_argument("--cost-bps", type=float, default=10.0,
                        help="Round-trip transaction cost in basis points")
    parser.add_argument("--write-back", action="store_true",
                        help="Write best params to configs/optimized_params.yaml")
    parser.add_argument("--audit", action="store_true",
                        help="Run param audit comparing new vs current params")
    parser.add_argument("--study-name", default=None)
    return parser.parse_args()


def load_feature_data(data_path: str) -> "pd.DataFrame":
    """Load historical feature data for backtesting."""
    import pandas as pd
    path = Path(data_path)
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, parse_dates=True, index_col=0)


def build_study_config(args: argparse.Namespace) -> StudyConfig:
    """Merge CLI args with per-model defaults and global defaults."""
    config_mgr = ConfigManager()
    config_mgr.register_file(CONFIG_FILE_OPTIMIZATION)
    opt_config = config_mgr.get("optimization", {})
    global_defaults = opt_config.get("defaults", {})

    optimizer = OptimizerRegistry.get_or_default(MODEL_NAME)
    model_defaults = optimizer.default_study_config()

    def resolve(cli_val, model_key, global_key, fallback):
        if cli_val is not None:
            return cli_val
        if model_key in model_defaults:
            return model_defaults[model_key]
        if global_key in global_defaults:
            return global_defaults[global_key]
        return fallback

    return StudyConfig(
        model_name=MODEL_NAME,
        asset=args.asset,
        timeframe=args.timeframe,
        n_trials=resolve(args.n_trials, "n_trials", "n_trials", 200),
        sampler=resolve(args.sampler, "sampler", "sampler", "TPE"),
        pruner=resolve(args.pruner, "pruner", "pruner", "MedianPruner"),
        objectives=model_defaults.get("objectives", ["sharpe"]),
        directions=model_defaults.get("directions", ["maximize"]),
    )


def main() -> None:
    args = parse_args()

    # Load historical data
    feature_df = load_feature_data(args.data_path)
    logger.info(f"Loaded {len(feature_df)} bars from {args.data_path}")

    # Build backtester — this is the backtest_fn for Optuna
    backtester = Backtester(feature_df, timeframe=args.timeframe, cost_bps=args.cost_bps)

    def backtest_fn(model):
        result = backtester.run(model)
        return {
            "sharpe": result.sharpe,
            "max_drawdown": result.max_drawdown,
            "win_rate": result.win_rate,
        }

    # Build study config and optimizer
    study_config = build_study_config(args)
    optimizer = OptimizerRegistry.get_or_default(MODEL_NAME)
    objective_fn = optimizer.build_objective(backtest_fn)

    # Run study (in-memory, no DB)
    runner = OptunaRunner(study_config)
    results = runner.run(objective_fn=objective_fn, study_name=args.study_name)

    # Log summary
    completed = [r for r in results if r.state == "COMPLETE"]
    if not completed:
        logger.warning("No completed trials")
        return

    best = max(completed, key=lambda r: list(r.values.values())[0])
    processed_params = optimizer.post_process_params(best.params)
    logger.info(f"Best trial #{best.trial_number}: params={processed_params} values={best.values}")

    # Audit: compare new params vs current
    if args.audit:
        current_params = read_current_params(MODEL_NAME, args.asset, args.timeframe)
        if current_params:
            auditor = ParamAuditor(feature_df, timeframe=args.timeframe, cost_bps=args.cost_bps)
            report = auditor.audit(MODEL_NAME, args.asset, args.timeframe,
                                   current_params, processed_params)
            _print_audit_report(report)
        else:
            logger.info("No current params found in models.yaml — skipping audit (first run)")

    # Write-back to optimized_params.yaml (not models.yaml)
    if args.write_back:
        write_best_params(MODEL_NAME, args.asset, args.timeframe, processed_params)
        logger.info(f"Wrote best params to configs/optimized_params.yaml")

    logger.info(f"Optimization complete: {len(completed)}/{len(results)} trials completed")


def _print_audit_report(report) -> None:
    """Pretty-print the param audit report."""
    print(f"\n{'='*60}")
    print(f"PARAM AUDIT: {report.model_name} / {report.asset} / {report.timeframe}")
    print(f"{'='*60}")
    print(f"Recommendation: {report.recommendation.upper()}")
    print(f"Reason: {report.reason}")
    print(f"\n{'Metric':<20} {'Current':>12} {'Proposed':>12} {'Delta':>12}")
    print(f"{'-'*56}")
    for k in report.current_metrics:
        cur = report.current_metrics[k]
        prop = report.proposed_metrics[k]
        delta = report.deltas[k]
        print(f"{k:<20} {cur:>12.4f} {prop:>12.4f} {delta:>+12.4f}")
    print(f"\nCurrent params:  {report.current_params}")
    print(f"Proposed params: {report.proposed_params}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
```

### MeanReversion Monitor (`src/libs/models/mean_reversion/scripts/monitor.py`)

```python
"""Monitor MeanReversion optimization study progress (in-memory).

Usage:
    # Import and call after/during optimization in the same process:
    from libs.models.mean_reversion.scripts.monitor import print_study_summary

    runner = OptunaRunner(config)
    results = runner.run(objective_fn=fn)
    print_study_summary(runner.study, top_n=10)

    # Or standalone against a pickled study:
    python -m libs.models.mean_reversion.scripts.monitor --study-pickle study.pkl --top-n 10
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

_src = str(Path(__file__).resolve().parents[4])
if _src not in sys.path:
    sys.path.insert(0, _src)

import optuna


def print_study_summary(study: optuna.Study, top_n: int = 5) -> None:
    """Print summary of an in-memory Optuna study."""
    trials = study.trials
    completed = [t for t in trials if t.state == optuna.trial.TrialState.COMPLETE]
    pruned = [t for t in trials if t.state == optuna.trial.TrialState.PRUNED]
    failed = [t for t in trials if t.state == optuna.trial.TrialState.FAIL]

    print(f"\n{'='*60}")
    print(f"Study: {study.study_name}")
    print(f"{'='*60}")
    print(f"Total trials:  {len(trials)}")
    print(f"Completed:     {len(completed)}")
    print(f"Pruned:        {len(pruned)}")
    print(f"Failed:        {len(failed)}")

    if not completed:
        print("No completed trials.")
        return

    # Sort by primary objective value
    sorted_trials = sorted(
        completed,
        key=lambda t: t.value if t.value is not None else float("-inf"),
        reverse=True,
    )

    print(f"\nTop {min(top_n, len(sorted_trials))} trials:")
    print(f"{'-'*60}")
    for i, trial in enumerate(sorted_trials[:top_n], 1):
        print(f"  #{i} Trial {trial.number}: "
              f"value={trial.value:.4f} "
              f"params={json.dumps(trial.params, default=str)}")

    best = sorted_trials[0]
    print(f"\nBest: Trial {best.number} — value={best.value:.4f}")
    print(f"  params={json.dumps(best.params, default=str)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor optimization study (in-memory)")
    parser.add_argument("--study-pickle", required=True,
                        help="Path to pickled Optuna study object")
    parser.add_argument("--top-n", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with open(args.study_pickle, "rb") as f:
        study = pickle.load(f)
    print_study_summary(study, top_n=args.top_n)


if __name__ == "__main__":
    main()
```

### TrendFollowing and Momentum Scripts

Follow the same pattern as MeanReversion.  The per-model `scripts/optimize.py` differs only in:
- `MODEL_NAME` constant
- `model_defaults.get("objectives", ...)` for multi-objective models

The coder should copy the MeanReversion scripts as templates, changing only `MODEL_NAME`.

## Shared Dispatcher (`scripts/run_optimization.py`)

Thin dispatcher that delegates to per-model scripts.  Useful for cron.

```python
"""Shared dispatcher — delegates to per-model optimization scripts.

Usage:
    python scripts/run_optimization.py \
        --model MeanReversion \
        --asset BTCUSDT \
        --timeframe 1h \
        --data-path data/features_btcusdt_1h.parquet \
        --audit --write-back

This is a convenience wrapper.  Each model's optimize.py can also be
invoked directly:
    python -m libs.models.mean_reversion.scripts.optimize --asset ...
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Map model name → module path for per-model scripts
_MODEL_SCRIPTS: dict[str, str] = {
    "MeanReversion": "libs.models.mean_reversion.scripts.optimize",
    "TrendFollowing": "libs.models.trend_following.scripts.optimize",
    "Momentum": "libs.models.momentum.scripts.optimize",
}


def main() -> None:
    # Extract --model from argv before delegating
    if "--model" not in sys.argv:
        print("Usage: run_optimization.py --model <ModelName> [other args...]")
        sys.exit(1)

    idx = sys.argv.index("--model")
    if idx + 1 >= len(sys.argv):
        print("Error: --model requires a value")
        sys.exit(1)

    model_name = sys.argv[idx + 1]

    if model_name not in _MODEL_SCRIPTS:
        print(f"Error: Unknown model '{model_name}'. "
              f"Available: {list(_MODEL_SCRIPTS.keys())}")
        sys.exit(1)

    # Remove --model and its value from argv so per-model script doesn't see it
    sys.argv = [sys.argv[0]] + sys.argv[1:idx] + sys.argv[idx + 2:]

    # Import and run per-model script
    module = importlib.import_module(_MODEL_SCRIPTS[model_name])
    module.main()


if __name__ == "__main__":
    main()
```

## Cron Configuration (`configs/optimization.yaml`)

```yaml
optimization:
  defaults:
    n_trials: 200
    sampler: "TPE"
    pruner: "MedianPruner"
    write_back: false

  schedules:
    MeanReversion:
      cron: "0 2 * * 1"           # weekly Monday 2am UTC
      assets: ["BTCUSDT", "ETHUSDT"]
      timeframes: ["1h", "4h"]
      n_trials: 200
      write_back: true
    TrendFollowing:
      cron: "0 3 1 * *"           # monthly 1st 3am UTC
      assets: ["BTCUSDT"]
      timeframes: ["4h"]
      n_trials: 300
      write_back: true
    Momentum:
      cron: "0 2 */14 * *"        # biweekly
      assets: ["BTCUSDT", "ETHUSDT"]
      timeframes: ["4h"]
      n_trials: 250
      write_back: true
```

Cron invocation pattern (document in README or crontab.example):
```bash
# MeanReversion: weekly Monday 2am UTC
0 2 * * 1 cd /path/to/flipperAgent && .venv/bin/python scripts/run_optimization.py \
    --model MeanReversion --asset BTCUSDT --timeframe 1h \
    --data-path data/features_btcusdt_1h.parquet --audit --write-back
```

## Implementation Order

| Step | Task | Dependencies |
|------|------|-------------|
| 1 | Add new Pydantic contracts (`BacktestResult`, `ParamAuditReport`, `ScheduleEntry`, `OptimizationDefaults`, `OptimizationConfig`) to `libs/contracts/schemas.py` | None |
| 2 | Create `libs/optimization/base_optimizer.py` | Step 1 |
| 3 | Create `libs/optimization/optimizer_registry.py` | Step 2 |
| 4 | Create `libs/optimization/backtester.py` | Step 1 |
| 5 | Create `libs/optimization/param_auditor.py` | Steps 1, 4 |
| 6 | Create `libs/optimization/param_writeback.py` | None |
| 7 | Modify `libs/optimization/runner.py` — add `objective_fn` param, expose `study` | None |
| 8 | Update `libs/optimization/__init__.py` with new exports | Steps 2–6 |
| 9 | Restructure `mean_reversion.py` → `mean_reversion/` package | None |
| 10 | Restructure `trend_following.py` → `trend_following/` package | None |
| 11 | Restructure `momentum.py` → `momentum/` package | None |
| 12 | Create per-model `optimizer.py` files (MeanReversion, TrendFollowing, Momentum) | Steps 3, 9–11 |
| 13 | Create per-model `scripts/optimize.py` and `scripts/monitor.py` | Steps 4, 5, 6, 7, 12 |
| 14 | Update `libs/models/__init__.py` (import paths unchanged but verify) | Steps 9–12 |
| 15 | Create `configs/optimization.yaml` | Step 1 |
| 16 | Create `scripts/run_optimization.py` shared dispatcher | Step 13 |
| 17 | Write/update tests | All |
| 18 | Run full test suite, confirm backward compatibility | All |

## Acceptance Criteria

1. **Per-model packages:** Each model is a package (`mean_reversion/`, `trend_following/`, `momentum/`) with `model.py`, `optimizer.py`, `scripts/optimize.py`, `scripts/monitor.py`, and `__init__.py` that re-exports the model class.
2. **Backward-compatible imports:** `from libs.models.mean_reversion import MeanReversionModel` still works.
3. **BaseOptimizer ABC:** Defined in `libs/optimization/base_optimizer.py` with `model_name`, `default_study_config()`, `build_objective()`, `suggest_params()`, `post_process_params()`.
4. **OptimizerRegistry:** `register()`, `get()`, `get_or_default()`, `list_all()`. `get_or_default()` returns `GenericOptimizer` when no custom optimizer is registered.
5. **GenericOptimizer:** Uses `make_objective()` as fallback — any model works without a custom optimizer.
6. **OptunaRunner backward compat:** `runner.run(backtest_fn=fn)` still works. New path: `runner.run(objective_fn=fn)`. `runner.study` is accessible after `run()`.
7. **Backtester:** `Backtester(feature_df, timeframe).run(model)` returns `BacktestResult` with sharpe, max_drawdown, win_rate, total_trades. Includes transaction cost modeling.
8. **Param auditor:** `ParamAuditor.audit()` returns `ParamAuditReport` with current_metrics, proposed_metrics, deltas, recommendation (`adopt`/`reject`/`review`), and reason.
9. **Param write-back:** Atomically writes to `configs/optimized_params.yaml` (NOT `models.yaml`).
10. **Per-model CLI scripts:** Each model has `scripts/optimize.py` with `--asset`, `--timeframe`, `--data-path`, `--audit`, `--write-back` flags.
11. **Monitor reads in-memory:** Monitor uses Optuna study object or pickled study — no TimescaleDB dependency.
12. **Shared dispatcher:** `scripts/run_optimization.py --model X` delegates to per-model script.
13. **Config:** `configs/optimization.yaml` with `defaults` and `schedules` sections, validated by `OptimizationConfig` schema.
14. **All existing tests pass** with no modifications to test logic (only import paths if needed).
15. **No `os.getenv`** — all config via `ConfigManager`.
16. **No `logging.getLogger`** — all logging via `bind_logger`.
17. **No cron locking mechanism** — single CLI invocation assumed.

## Validation Checklist

- [ ] `from libs.models.mean_reversion import MeanReversionModel` works
- [ ] `from libs.models.trend_following import TrendFollowingModel` works
- [ ] `from libs.models.momentum import MomentumModel` works
- [ ] `ModelRegistry.list_all()` returns all 3 models
- [ ] `OptimizerRegistry.list_all()` returns all 3 model names
- [ ] `OptimizerRegistry.get_or_default("MeanReversion")` returns `MeanReversionOptimizer`
- [ ] `OptimizerRegistry.get_or_default("UnknownModel")` returns `GenericOptimizer` with warning
- [ ] `OptunaRunner(config).run(backtest_fn=fn)` still works (backward compat)
- [ ] `OptunaRunner(config).run(objective_fn=fn)` works with per-model objective
- [ ] `runner.study` is a valid `optuna.Study` after `run()`
- [ ] `Backtester(feature_df, "1h").run(model)` returns `BacktestResult`
- [ ] `BacktestResult.sharpe` is annualized, handles zero-std edge case
- [ ] `BacktestResult.max_drawdown` is negative fraction
- [ ] Transaction costs are subtracted on position changes
- [ ] `ParamAuditor.audit()` returns `ParamAuditReport` with correct deltas
- [ ] Audit recommendation is "adopt" when Sharpe improves ≥ 0.1 and DD not worsened
- [ ] Audit recommendation is "reject" when DD worsens > 5pp
- [ ] Audit recommendation is "review" in ambiguous cases
- [ ] `write_best_params()` writes to `configs/optimized_params.yaml` (NOT models.yaml)
- [ ] `read_current_params()` reads from `configs/models.yaml`
- [ ] Per-model CLI `--help` works, all args parse correctly
- [ ] `python -m libs.models.mean_reversion.scripts.optimize --asset BTCUSDT --timeframe 1h --data-path test.csv --n-trials 5` runs
- [ ] `scripts/run_optimization.py --model MeanReversion --asset BTCUSDT --timeframe 1h --data-path test.csv` dispatches correctly
- [ ] Monitor `print_study_summary(study)` prints correct stats
- [ ] `configs/optimization.yaml` validates against `OptimizationConfig` schema
- [ ] Existing `test_optimization.py` passes without changes
- [ ] No `os.getenv` in any new code
- [ ] No `logging.getLogger` in any new code
- [ ] Full test suite passes: `PYTHONPATH=. .venv/bin/pytest tests/ --ignore=tests/e2e -q`

## New Test Requirements

### `tests/models/test_backtester.py`
- `Backtester` raises `ValueError` if `feature_df` has no `close` column
- `Backtester.run()` returns `BacktestResult` with all fields populated
- Sharpe is 0.0 when returns have zero std
- Max drawdown is always ≤ 0
- Win rate is 0.0 when no trades are made
- Transaction costs reduce strategy returns vs zero-cost baseline
- Direction alignment: direction[i] applies to return[i+1]
- Known-answer test: synthetic data with predictable directions → expected Sharpe sign

### `tests/models/test_param_auditor.py`
- `ParamAuditor.audit()` returns `ParamAuditReport` with correct field types
- `recommendation` is "adopt" when Sharpe delta ≥ 0.1 and DD not degraded
- `recommendation` is "reject" when DD worsens by > threshold
- `recommendation` is "review" in marginal cases
- `deltas` are correctly computed as `proposed - current`
- Handles case where current params are empty (model defaults used)

### `tests/models/test_base_optimizer.py`
- `BaseOptimizer` cannot be instantiated directly (ABC)
- `GenericOptimizer` can be instantiated with any model name
- `GenericOptimizer.build_objective()` returns a callable
- `GenericOptimizer.suggest_params()` returns params from hyperparameter_schema
- `GenericOptimizer.post_process_params()` is identity by default
- `GenericOptimizer.default_study_config()` returns empty dict

### `tests/models/test_optimizer_registry.py`
- Registration via decorator works
- `get()` returns registered class
- `get()` raises `KeyError` for unknown
- `get_or_default()` returns registered instance
- `get_or_default()` returns `GenericOptimizer` for unknown (with warning log)
- `list_all()` returns all registered names

### `tests/models/test_mean_reversion_optimizer.py`
- `MeanReversionOptimizer.model_name` is "MeanReversion"
- `default_study_config()` returns expected defaults
- `build_objective()` returns callable
- Objective function calls backtest_fn and applies drawdown penalty

### `tests/models/test_param_writeback.py`
- `write_best_params()` creates model/asset/tf entry if missing
- `write_best_params()` merges new params over existing
- `write_best_params()` writes to `optimized_params.yaml` (not `models.yaml`)
- Atomic write: no corruption on failure (mock `os.replace` to verify)
- `read_current_params()` reads from `models.yaml`
- `read_current_params()` returns `{}` when path not found

### `tests/models/test_cli_runner.py`
- Arg parsing: all flags parse correctly (per-model script)
- Config merge priority: CLI > model > global > defaults
- `--audit` flag triggers param auditor
- `--write-back` flag writes to `optimized_params.yaml`
- Shared dispatcher routes to correct per-model script

## Architecture: Adding a New Model (Plug-and-Play Guide)

When adding a new model (e.g., `VolatilityBreakout`):

1. Create `src/libs/models/volatility_breakout/model.py` with model class decorated `@ModelRegistry.register("VolatilityBreakout")`
2. Create `src/libs/models/volatility_breakout/__init__.py`:
   ```python
   from libs.models.volatility_breakout.model import VolatilityBreakoutModel  # noqa: F401
   ```
3. Add to `src/libs/models/__init__.py`:
   ```python
   import libs.models.volatility_breakout  # noqa: F401
   ```
4. **(Optional)** Create `src/libs/models/volatility_breakout/optimizer.py` with custom `@OptimizerRegistry.register("VolatilityBreakout")` — if omitted, `GenericOptimizer` works automatically
5. **(Optional)** Create `src/libs/models/volatility_breakout/scripts/optimize.py` — copy from MeanReversion, change `MODEL_NAME`. If omitted, use shared dispatcher which falls back to `GenericOptimizer`.
6. If custom optimizer added, update `__init__.py` to import it:
   ```python
   import libs.models.volatility_breakout.optimizer  # noqa: F401
   ```
7. Add schedule entry to `configs/optimization.yaml` and model-script mapping to `scripts/run_optimization.py`.

Zero extra work required for basic optimization. Custom scoring, scripts, and param constraints are all opt-in.

## Risks and Follow-Up Items

| Item | Type | Notes |
|------|------|-------|
| Historical feature data availability | Prerequisite | Per-model optimize scripts require `--data-path` — user must provide CSV/parquet of historical features. No data generation pipeline in this scope. |
| Backtester simplicity | Limitation | Backtester uses simple bar-level returns with flat position sizing. No partial fills, order book simulation, or multi-leg positions. Sufficient for Optuna objective comparison but not for production-grade evaluation. |
| Backtester look-ahead | Risk | `batch_evaluate()` uses `holding_period` cooldown that iterates forward — this is safe. But the backtester assumes `directions[i]` acts on `returns[i+1]` (next bar open), which is correct for next-bar entry assumption. Document this assumption. |
| Write-back adoption workflow | Follow-up | Manual step: user reviews `configs/optimized_params.yaml` + audit report, then copies approved params to `models.yaml`. A future `apply_optimized_params.py` script could automate this with a confirmation prompt. |
| Monitor pickled study | Limitation | Standalone monitor requires pickling the study object. For in-process monitoring, call `print_study_summary(runner.study)` directly. |
| Per-model script duplication | Maintenance | Each model's `scripts/optimize.py` has ~80% shared boilerplate. If model count grows beyond 5, extract a `BaseOptimizationCLI` class. For 3 models, copy-paste is acceptable. |
| Multi-objective audit | Follow-up | `ParamAuditor` uses single-objective Sharpe/DD heuristics. For multi-objective models (TrendFollowing with Pareto), audit logic needs extension. |
