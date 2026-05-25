---
goal: Redesign optimization layer with fully independent per-model optimizers, no shared backtester, Binance data fetching via libs-local module, and co-located CLI scripts in optimization/ folders
stage: architect-to-coder
date_created: 2026-05-25
last_updated: 2026-05-25
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, optimization, per-model-optimizer, scoring, data-fetcher, cli, cron]
source_agent: Quant Research Architect
target_agent: Coder Agent
supersedes: plans/architect-to-coder-optimization-redesign-v2.md
---

# Architect → Coder: Optimization Layer Redesign v3

## Changes from v2

| Area | v2 Decision | v3 Decision (user-directed) |
|------|-------------|----------------------------|
| Backtester | Standalone `Backtester` class in `libs/optimization/backtester.py` | **Removed.** Scoring lives inline in each model's `optimizer.py` objective function. Shared scoring *utility functions* in `libs/optimization/scoring.py` |
| BaseOptimizer / OptimizerRegistry | `BaseOptimizer` ABC + `OptimizerRegistry` + `GenericOptimizer` fallback | **All removed.** Each model's `optimizer.py` is completely independent — no enforced interface, no registry, no fallback |
| Data fetching | CLI `--data-path` reads CSV/parquet from disk | **Binance live fetch.** New `libs/optimization/data_fetcher.py` uses `binance-futures-connector` SDK directly — no cross-app import from `apps/` |
| Script location | `mean_reversion/scripts/optimize.py` | `mean_reversion/optimization/optimize.py` — `optimization/` folder, not `scripts/` |
| Shared dispatcher | `scripts/run_optimization.py` in top-level `scripts/` | **Optional convenience only.** Primary invocation is `python -m libs.models.mean_reversion.optimization.optimize` |

## Architectural Decisions (addressing user concerns)

### Decision 1: No standalone backtester — scoring in per-model objective functions

**Rationale:** The model already has `batch_evaluate(feature_df) → pd.Series` which returns directions. Computing Sharpe, drawdown, etc. from directions + price returns is straightforward math that belongs in the objective function. Different models may score differently:

- MeanReversion might penalize drawdown heavily (`sharpe - 0.5 * |max_dd|`)
- TrendFollowing might optimize a combined Sharpe + win_rate score
- A future model might use custom metrics entirely

**What we provide instead:** Optional scoring *utility functions* in `libs/optimization/scoring.py`:
- `compute_returns(directions, close_prices, cost_bps) → np.ndarray` — bar-level strategy returns with transaction costs
- `compute_sharpe(returns, ann_factor) → float`
- `compute_max_drawdown(returns) → float`
- `compute_win_rate(returns, trade_mask) → float`

These are pure math — no class, no state, no enforced usage. Each optimizer imports what it needs.

**ParamAuditor updated:** The `ParamAuditor` uses these same scoring utilities for standardized metric comparison (Sharpe, drawdown, win rate) regardless of the model-specific optimization objective. This gives consistent audit reports across models.

### Decision 2: Fully independent per-model optimizers — no ABC, no registry

**Rationale:** Different models may use fundamentally different optimization approaches:
- MeanReversion: NSGA-II multi-objective (Sharpe + drawdown Pareto front)
- TrendFollowing: TPE single-objective with custom pruning
- Momentum: CMA-ES or grid search
- Future models: Bayesian optimization, non-Optuna frameworks, manual grid

An enforced ABC (`BaseOptimizer`) with fixed method signatures (`build_objective`, `suggest_params`, `post_process_params`) constrains models to Optuna's trial-based interface. A registry adds indirection without value when each model is invoked directly.

**What remains shared (optional utilities in `libs/optimization/`):**
- `scoring.py` — metric computation functions
- `runner.py` — `OptunaRunner` as one possible way to run Optuna studies (models can use it or not)
- `objective.py` — `build_suggest()` and `make_objective()` as utilities
- `param_auditor.py` — standardized param comparison
- `param_writeback.py` — atomic write to `configs/optimized_params.yaml`
- `data_fetcher.py` — Binance OHLCV fetch
- `schemas.py`, `trial_store.py` — existing, untouched

**Each model's `optimization/optimizer.py` is a plain Python module** that exports whatever functions it needs. The only contract is: `optimize.py` (the CLI script) produces optimized params and optionally writes them back. There is no shared interface to conform to.

### Decision 3: Data fetching via `libs/optimization/data_fetcher.py`

**Problem:** The existing `BinanceNativeAdapter` lives in `apps/ingestion_app/adapters/binance_native.py`. Importing it from `libs/` would violate the cross-app import boundary.

**Solution:** Create a standalone `libs/optimization/data_fetcher.py` that uses the `binance-futures-connector` SDK directly. This module has zero dependency on `apps/`. It wraps the same underlying SDK that `BinanceNativeAdapter` uses, but is purpose-built for optimization data fetching.

**Why not move the adapter to libs?** The adapter is tightly coupled to ingestion-app concerns (streaming, websocket multiplexing, ingestion-specific error handling). The optimization data fetcher only needs synchronous historical OHLCV fetch — a much simpler interface.

**Why not inject via protocol/interface?** Over-engineering for a single concrete implementation. If a second exchange is needed, the data_fetcher module can be extended then.

**API credentials:** Read from `ConfigManager` under a `binance` config key (same credentials the ingestion app uses, loaded from `configs/base.yaml` or environment-injected config files). No `os.getenv`.

### Decision 4: Scripts co-located in `optimization/` folder

Each model is fully self-contained:

```
src/libs/models/mean_reversion/
├── __init__.py
├── model.py
└── optimization/
    ├── __init__.py
    ├── optimizer.py      # Custom objective fn, scoring, study config — fully independent
    ├── optimize.py       # CLI: python -m libs.models.mean_reversion.optimization.optimize
    └── monitor.py        # CLI: python -m libs.models.mean_reversion.optimization.monitor
```

**Invocation:**
```bash
cd /path/to/flipperAgent
PYTHONPATH=src .venv/bin/python -m libs.models.mean_reversion.optimization.optimize \
    --asset BTCUSDT --timeframe 1h --n-trials 200 --audit --write-back
```

## Objective

Redesign the optimization layer so that each model is a self-contained package with co-located optimization scripts and a fully independent optimizer. Remove shared optimizer abstractions (ABC, registry, backtester). Provide optional shared scoring utilities and a Binance data fetcher in `libs/optimization/`. Add param auditing/benchmarking. Keep optimization offline (CLI + cron).

## Scope Boundaries

### In Scope
- Restructure model files into packages with co-located optimizer and `optimization/` folder
- **New:** `libs/optimization/scoring.py` — optional scoring utility functions
- **New:** `libs/optimization/data_fetcher.py` — fetch OHLCV from Binance SDK directly
- **Revised:** `libs/optimization/param_auditor.py` — uses scoring utilities, not Backtester
- Existing: `libs/optimization/param_writeback.py` — write to `configs/optimized_params.yaml`
- Minor additive change to `OptunaRunner.run()` (optional `objective_fn` param, expose `study`)
- New Pydantic contracts: `ScheduleEntry`, `OptimizationDefaults`, `OptimizationConfig`, `ParamAuditReport`
- Per-model `optimization/optimizer.py`, `optimization/optimize.py`, `optimization/monitor.py`
- Optional thin shared dispatcher `scripts/run_optimization.py`
- New config file `configs/optimization.yaml`
- Per-model optimizer implementations for MeanReversion, TrendFollowing, Momentum
- Update `libs/models/__init__.py` for new package structure
- Update existing tests for new import paths

### Out of Scope (Explicit Non-Goals)
- No `BaseOptimizer` ABC — removed
- No `OptimizerRegistry` or `GenericOptimizer` — removed
- No standalone `Backtester` class — removed
- No `BacktestResult` Pydantic schema — removed (scoring returns plain dicts)
- No changes to `BaseModel`, `ModelMeta`, or `ModelRegistry`
- No changes to `TrialStore` or `trial_store.py`
- No changes to `StrategyWorker`, `ModelManager`, or any app-level code
- No persistent worker or daemon — offline CLI + cron only
- No changes to `configs/models.yaml` structure
- No Docker/Kubernetes CronJob manifests
- No cross-app imports between `libs/` and `apps/`

## Affected Symbols, Modules, and Execution Flows

### Modified Files

| File | Change | Risk |
|------|--------|------|
| `src/libs/models/mean_reversion.py` | Delete after moving to `mean_reversion/model.py` | LOW |
| `src/libs/models/trend_following.py` | Delete after moving to `trend_following/model.py` | LOW |
| `src/libs/models/momentum.py` | Delete after moving to `momentum/model.py` | LOW |
| `src/libs/models/__init__.py` | Update auto-import paths | LOW |
| `src/libs/optimization/runner.py` | Add optional `objective_fn` param, expose `study` property | LOW |
| `src/libs/optimization/__init__.py` | Add new exports (scoring, data_fetcher) | LOW |
| `src/libs/contracts/schemas.py` | Add `ScheduleEntry`, `OptimizationDefaults`, `OptimizationConfig`, `ParamAuditReport` | LOW |

### New Files

| File | Purpose |
|------|---------|
| `src/libs/optimization/scoring.py` | Shared scoring utility functions (Sharpe, drawdown, win rate, returns) |
| `src/libs/optimization/data_fetcher.py` | Fetch OHLCV from Binance via SDK — no apps/ dependency |
| `src/libs/optimization/param_auditor.py` | Compare new params vs current via standardized metrics |
| `src/libs/optimization/param_writeback.py` | Atomic write to `configs/optimized_params.yaml` |
| `src/libs/models/mean_reversion/__init__.py` | Re-export `MeanReversionModel` |
| `src/libs/models/mean_reversion/model.py` | Model class (moved from `mean_reversion.py`) |
| `src/libs/models/mean_reversion/optimization/__init__.py` | Empty |
| `src/libs/models/mean_reversion/optimization/optimizer.py` | Custom objective, scoring, study config |
| `src/libs/models/mean_reversion/optimization/optimize.py` | CLI runner |
| `src/libs/models/mean_reversion/optimization/monitor.py` | CLI monitor |
| `src/libs/models/trend_following/` | Same package pattern |
| `src/libs/models/momentum/` | Same package pattern |
| `scripts/run_optimization.py` | Optional thin shared dispatcher |
| `configs/optimization.yaml` | Schedule + defaults config |
| `configs/optimized_params.yaml` | Output target for optimized params (created by write-back) |

### Files NOT Created (removed from v2)

| File | Reason |
|------|--------|
| `src/libs/optimization/backtester.py` | Scoring lives in per-model objective functions |
| `src/libs/optimization/base_optimizer.py` | No enforced ABC |
| `src/libs/optimization/optimizer_registry.py` | No registry needed |

### Execution Flows Unaffected
- `StrategyWorker` → `ModelManager` → `ModelRegistry.get()` → model: **unchanged** (re-export `__init__.py` preserves import path)
- `SignalWorker` → `FeatureVector` publish: **unchanged**
- All existing indicator, feature, ingestion flows: **unchanged**

## Data Contracts and Interfaces

### New Pydantic Schemas (add to `src/libs/contracts/schemas.py`)

```python
class ParamAuditReport(BaseModel):
    """Comparison of current vs proposed optimized params."""
    model_name: str
    asset: str
    timeframe: str
    current_params: dict[str, Any]
    proposed_params: dict[str, Any]
    current_metrics: dict[str, float]       # Standardized metrics for current params
    proposed_metrics: dict[str, float]      # Standardized metrics for proposed params
    deltas: dict[str, float]                # metric_name → (proposed - current)
    recommendation: str                      # "adopt" | "reject" | "review"
    reason: str


class ScheduleEntry(BaseModel):
    """Per-model cron schedule entry."""
    cron: str = Field(..., description="Cron expression (e.g., '0 2 * * 1')")
    assets: list[str] = Field(default_factory=list)
    timeframes: list[str] = Field(default_factory=list)
    n_trials: int | None = None
    write_back: bool = False


class OptimizationDefaults(BaseModel):
    """Global optimization defaults."""
    n_trials: int = 200
    write_back: bool = False


class OptimizationConfig(BaseModel):
    """Top-level optimization config matching configs/optimization.yaml."""
    defaults: OptimizationDefaults = Field(default_factory=OptimizationDefaults)
    schedules: dict[str, ScheduleEntry] = Field(default_factory=dict)
```

**Note:** `ScheduleEntry` no longer has `sampler`, `pruner`, `objectives`, `directions` fields — those are per-model implementation details that don't belong in a shared schema. Each model's optimizer chooses its own technique.

### Scoring Utilities (new `src/libs/optimization/scoring.py`)

```python
"""Scoring utility functions for optimization objective functions.

Pure math — no class, no state, no side effects.
Each model's optimizer imports what it needs.
"""

from __future__ import annotations

import math

import numpy as np


# Annualization factors by common timeframe labels.
BARS_PER_YEAR: dict[str, int] = {
    "1m": 525_600,
    "5m": 105_120,
    "15m": 35_040,
    "1h": 8_760,
    "4h": 2_190,
    "1d": 365,
}


def compute_returns(
    directions: np.ndarray,
    close_prices: np.ndarray,
    cost_bps: float = 10.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute per-bar strategy returns from directions and close prices.

    Parameters
    ----------
    directions : np.ndarray
        Array of positions (-1, 0, 1) from model.batch_evaluate().
    close_prices : np.ndarray
        Array of close prices aligned with directions.
    cost_bps : float
        Round-trip transaction cost in basis points per position change.

    Returns
    -------
    strategy_returns : np.ndarray
        Per-bar strategy returns (len = len(close_prices) - 1).
    trade_mask : np.ndarray
        Boolean mask where position changes occurred.
    """
    bar_returns = np.diff(close_prices) / close_prices[:-1]

    # Direction[i] applied to return[i] (direction at bar i earns return from i to i+1)
    pos = directions[:-1].astype(float)
    strategy_returns = pos * bar_returns

    # Subtract transaction costs on position changes
    trades = np.diff(np.concatenate([[0.0], pos]))
    trade_mask = trades != 0
    trade_costs = np.abs(trades) * (cost_bps / 10_000.0)
    strategy_returns -= trade_costs[: len(strategy_returns)]

    return strategy_returns, trade_mask


def compute_sharpe(
    returns: np.ndarray,
    timeframe: str = "1h",
) -> float:
    """Annualized Sharpe ratio (risk-free rate = 0)."""
    if len(returns) == 0 or np.std(returns) == 0:
        return 0.0
    ann_factor = BARS_PER_YEAR.get(timeframe, 8_760)
    return float((np.mean(returns) / np.std(returns)) * math.sqrt(ann_factor))


def compute_max_drawdown(returns: np.ndarray) -> float:
    """Maximum drawdown as a negative fraction (e.g. -0.15 = 15% DD)."""
    if len(returns) == 0:
        return 0.0
    cumulative = np.cumprod(1.0 + returns)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = (cumulative - running_max) / running_max
    return float(np.min(drawdowns))


def compute_win_rate(returns: np.ndarray, trade_mask: np.ndarray) -> float:
    """Win rate = fraction of trades with positive return."""
    mask = trade_mask[: len(returns)]
    if np.sum(mask) == 0:
        return 0.0
    trade_returns = returns[mask]
    return float(np.sum(trade_returns > 0) / len(trade_returns))
```

### Data Fetcher (new `src/libs/optimization/data_fetcher.py`)

```python
"""Fetch historical OHLCV data from Binance for optimization.

Uses binance-futures-connector SDK directly — zero dependency on
apps/ingestion_app adapters. Avoids cross-app imports.

The ingestion app's BinanceNativeAdapter wraps the same SDK but is
tightly coupled to ingestion concerns (streaming, websocket multiplex,
ingestion-specific error types). This module provides only the
synchronous historical fetch needed for optimization.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from binance.um_futures import UMFutures

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

# Binance returns 12 columns per kline row.
_RAW_KLINE_COLUMNS = [
    "timestamp", "open", "high", "low", "close", "volume", "close_time",
    "quote_asset_volume", "number_of_trades", "taker_buy_base_asset_volume",
    "taker_buy_quote_asset_volume", "ignore",
]

# Binance max limit per request.
_MAX_LIMIT = 1500


def fetch_historical_ohlcv(
    symbol: str,
    timeframe: str,
    since: int | None = None,
    until: int | None = None,
    limit: int = 1000,
) -> pd.DataFrame:
    """Fetch historical OHLCV from Binance Futures (synchronous, with pagination).

    Parameters
    ----------
    symbol : str
        Trading pair (e.g. "BTCUSDT").
    timeframe : str
        Kline interval (e.g. "1h", "4h", "1d").
    since : int | None
        Start time in milliseconds (inclusive).
    until : int | None
        End time in milliseconds (inclusive).
    limit : int
        Target number of candles. If > 1500, paginated automatically.

    Returns
    -------
    pd.DataFrame
        Columns: timestamp, open, high, low, close, volume.
        Sorted by timestamp ascending, deduplicated.
    """
    config = ConfigManager()
    binance_cfg = config.get("binance", {})
    client = UMFutures(
        key=binance_cfg.get("api_key"),
        secret=binance_cfg.get("api_secret"),
    )

    all_frames: list[pd.DataFrame] = []
    fetched = 0
    cursor = since

    while fetched < limit:
        batch_limit = min(_MAX_LIMIT, limit - fetched)
        params: dict[str, Any] = {"limit": batch_limit}
        if cursor is not None:
            params["startTime"] = cursor
        if until is not None:
            params["endTime"] = until

        lines = client.klines(symbol, timeframe, **params)
        if not lines:
            break

        df = _parse_klines(lines)
        all_frames.append(df)
        fetched += len(df)

        # Advance cursor past the last returned timestamp
        last_ts = int(df["timestamp"].iloc[-1])
        if cursor is not None and last_ts <= cursor:
            break  # no progress — avoid infinite loop
        cursor = last_ts + 1

        if len(lines) < batch_limit:
            break  # Binance returned fewer than requested — no more data

    if not all_frames:
        logger.warning(f"No data returned for {symbol}/{timeframe}")
        return pd.DataFrame(columns=OHLCV_COLUMNS)

    result = pd.concat(all_frames, ignore_index=True)
    result = result.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    logger.info(f"Fetched {len(result)} candles for {symbol}/{timeframe}")
    return result


def _parse_klines(lines: list[list[Any]]) -> pd.DataFrame:
    """Parse raw Binance kline rows into a DataFrame."""
    df = pd.DataFrame(lines, columns=_RAW_KLINE_COLUMNS)
    df = df[OHLCV_COLUMNS]
    for col in OHLCV_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df
```

### Param Auditor (revised `src/libs/optimization/param_auditor.py`)

Uses scoring utility functions instead of the removed Backtester class.

```python
"""Audit and benchmark proposed params against current params.

Runs model.batch_evaluate() with both param sets on the same historical
data and produces a ParamAuditReport with standardized performance deltas.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import ParamAuditReport
from libs.models.registry import ModelRegistry
from libs.optimization.scoring import (
    compute_max_drawdown,
    compute_returns,
    compute_sharpe,
    compute_win_rate,
)

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)

# Thresholds for automatic recommendation
_SHARPE_IMPROVEMENT_THRESHOLD = 0.1
_DRAWDOWN_DEGRADATION_THRESHOLD = 0.05


class ParamAuditor:
    """Compare current vs proposed params via standardized metrics.

    Uses the shared scoring utilities for consistent metric computation
    across all models — independent of each model's optimization objective.
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

    def _score(self, model) -> dict[str, float]:
        """Run batch_evaluate and compute standardized metrics."""
        directions = model.batch_evaluate(self.feature_df)
        close = self.feature_df["close"].values
        returns, trade_mask = compute_returns(
            directions.values, close, cost_bps=self.cost_bps,
        )
        return {
            "sharpe": compute_sharpe(returns, self.timeframe),
            "max_drawdown": compute_max_drawdown(returns),
            "win_rate": compute_win_rate(returns, trade_mask),
            "total_trades": float(np.sum(trade_mask)),
        }

    def audit(
        self,
        model_name: str,
        asset: str,
        timeframe: str,
        current_params: dict[str, Any],
        proposed_params: dict[str, Any],
    ) -> ParamAuditReport:
        """Run both param sets and compare."""
        model_cls = ModelRegistry.get(model_name)

        current_metrics = self._score(model_cls(current_params))
        proposed_metrics = self._score(model_cls(proposed_params))

        deltas = {k: proposed_metrics[k] - current_metrics[k] for k in current_metrics}
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
        sharpe_d = deltas.get("sharpe", 0.0)
        dd_d = deltas.get("max_drawdown", 0.0)
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

### Param Write-back (unchanged from v2 — `src/libs/optimization/param_writeback.py`)

Writes to `configs/optimized_params.yaml` — NOT `configs/models.yaml`. See v2 for full implementation.

### OptunaRunner Change (modify `src/libs/optimization/runner.py`)

Add optional `objective_fn` parameter to `run()` and expose `study` as instance property. Same as v2 — see v2 for full diff.

## Per-Model Optimizer Implementations

### Key principle: each optimizer is a plain module, not a subclass

Each model's `optimization/optimizer.py` is a standalone module. It exports whatever functions and constants make sense for that model. There is no shared interface to conform to. The only convention is that `optimize.py` imports from `optimizer.py`.

### MeanReversion Optimizer (`src/libs/models/mean_reversion/optimization/optimizer.py`)

```python
"""MeanReversion optimization — custom objective function and study config.

This optimizer uses TPE single-objective with a combined Sharpe + drawdown
penalty score. Different models can use entirely different approaches.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import optuna

from libs.contracts.schemas import ParamDef
from libs.models.registry import ModelRegistry
from libs.optimization.objective import build_suggest
from libs.optimization.scoring import (
    compute_max_drawdown,
    compute_returns,
    compute_sharpe,
)

MODEL_NAME = "MeanReversion"

# Study defaults for this model — the CLI merges with global defaults.
STUDY_DEFAULTS: dict[str, Any] = {
    "n_trials": 200,
    "sampler": "TPE",
    "pruner": "MedianPruner",
    "direction": "maximize",
}


def make_objective(
    feature_df: "pd.DataFrame",
    timeframe: str = "1h",
    cost_bps: float = 10.0,
) -> callable:
    """Return an Optuna-compatible objective for MeanReversion.

    Scoring: sharpe - 0.5 * |max_drawdown|
    The penalty factor reflects mean-reversion's sensitivity to drawdown.
    """
    import pandas as pd

    close = feature_df["close"].values
    model_cls = ModelRegistry.get(MODEL_NAME)
    schema = model_cls.meta.hyperparameter_schema

    def objective(trial: optuna.Trial) -> float:
        # Suggest params from hyperparameter_schema
        params: dict[str, Any] = {}
        for pname, pdef in schema.items():
            params[pname] = build_suggest(trial, pname, pdef)

        # Run model
        model = model_cls(params)
        directions = model.batch_evaluate(feature_df)

        # Score
        returns, _ = compute_returns(directions.values, close, cost_bps)
        sharpe = compute_sharpe(returns, timeframe)
        max_dd = compute_max_drawdown(returns)

        return sharpe - 0.5 * abs(max_dd)

    return objective


def post_process_params(params: dict[str, Any]) -> dict[str, Any]:
    """Round integer params, enforce constraints."""
    result = dict(params)
    for key in ("rsi_oversold", "rsi_overbought", "holding_period"):
        if key in result:
            result[key] = int(round(result[key]))
    return result
```

### TrendFollowing Optimizer (`src/libs/models/trend_following/optimization/optimizer.py`)

```python
"""TrendFollowing optimization — multi-objective NSGA-II example.

Demonstrates a completely different technique from MeanReversion.
Uses NSGA-II with two objectives: Sharpe + win_rate.
Custom param constraint: ema_fast_period < ema_slow_period.
"""

from __future__ import annotations

from typing import Any

import optuna

from libs.models.registry import ModelRegistry
from libs.optimization.objective import build_suggest
from libs.optimization.scoring import (
    compute_max_drawdown,
    compute_returns,
    compute_sharpe,
    compute_win_rate,
)

MODEL_NAME = "TrendFollowing"

STUDY_DEFAULTS: dict[str, Any] = {
    "n_trials": 300,
    "sampler": "NSGAIISampler",
    "direction": None,  # multi-objective — use directions list
    "directions": ["maximize", "maximize"],
}


def make_objective(
    feature_df: "pd.DataFrame",
    timeframe: str = "1h",
    cost_bps: float = 10.0,
) -> callable:
    """Multi-objective: (sharpe, win_rate)."""
    close = feature_df["close"].values
    model_cls = ModelRegistry.get(MODEL_NAME)
    schema = model_cls.meta.hyperparameter_schema

    def objective(trial: optuna.Trial) -> tuple[float, float]:
        params: dict[str, Any] = {}
        for pname, pdef in schema.items():
            params[pname] = build_suggest(trial, pname, pdef)

        # Enforce constraint: fast < slow
        if params.get("ema_fast_period", 0) >= params.get("ema_slow_period", 1):
            params["ema_slow_period"] = params["ema_fast_period"] + 1

        model = model_cls(params)
        directions = model.batch_evaluate(feature_df)

        returns, trade_mask = compute_returns(directions.values, close, cost_bps)
        sharpe = compute_sharpe(returns, timeframe)
        win_rate = compute_win_rate(returns, trade_mask)

        return sharpe, win_rate

    return objective


def post_process_params(params: dict[str, Any]) -> dict[str, Any]:
    result = dict(params)
    for key in ("ema_fast_period", "ema_slow_period"):
        if key in result:
            result[key] = int(round(result[key]))
    return result
```

### Momentum Optimizer (`src/libs/models/momentum/optimization/optimizer.py`)

Same pattern. Custom objective, custom constraints. See TrendFollowing for template. Key difference: different param constraints (`rsi_short < rsi_long`), single-objective TPE.

### Model Package `__init__.py` Pattern

Each model package re-exports for backward compatibility:

```python
# src/libs/models/mean_reversion/__init__.py
from libs.models.mean_reversion.model import MeanReversionModel  # noqa: F401
```

**Note:** No optimizer auto-registration import needed — there is no registry. The optimizer module is imported only by its own `optimize.py` CLI script.

### Updated `src/libs/models/__init__.py`

```python
# Ensure all concrete models are imported so they self-register with ModelRegistry.
import libs.models.mean_reversion  # noqa: F401
import libs.models.trend_following  # noqa: F401
import libs.models.momentum  # noqa: F401
```

## Per-Model CLI Scripts

### MeanReversion CLI (`src/libs/models/mean_reversion/optimization/optimize.py`)

```python
"""CLI runner for MeanReversion optimization.

Usage:
    PYTHONPATH=src python -m libs.models.mean_reversion.optimization.optimize \
        --asset BTCUSDT --timeframe 1h --n-trials 200 --audit --write-back
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure src/ is on sys.path when run as a script
_src = str(Path(__file__).resolve().parents[4])
if _src not in sys.path:
    sys.path.insert(0, _src)

import optuna

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import StudyConfig
from libs.optimization.data_fetcher import fetch_historical_ohlcv
from libs.optimization.param_auditor import ParamAuditor
from libs.optimization.param_writeback import read_current_params, write_best_params
from libs.optimization.runner import OptunaRunner

# Trigger model registration
import libs.models  # noqa: F401

# Import this model's optimizer module
from libs.models.mean_reversion.optimization import optimizer as mr_optimizer

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run MeanReversion optimization study"
    )
    parser.add_argument("--asset", required=True, help="Asset symbol (e.g., BTCUSDT)")
    parser.add_argument("--timeframe", required=True, help="Timeframe (e.g., 1h)")
    parser.add_argument("--n-trials", type=int, default=None)
    parser.add_argument("--since", type=int, default=None,
                        help="Start time in ms (Binance timestamp)")
    parser.add_argument("--days", type=int, default=90,
                        help="Number of days of historical data (default: 90)")
    parser.add_argument("--cost-bps", type=float, default=10.0,
                        help="Round-trip transaction cost in basis points")
    parser.add_argument("--write-back", action="store_true",
                        help="Write best params to configs/optimized_params.yaml")
    parser.add_argument("--audit", action="store_true",
                        help="Compare new vs current params")
    parser.add_argument("--study-name", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # --- Fetch data from Binance ---
    import time
    since_ms = args.since
    if since_ms is None:
        since_ms = int((time.time() - args.days * 86400) * 1000)

    logger.info(f"Fetching {args.days}d of {args.timeframe} candles for {args.asset}")
    feature_df = fetch_historical_ohlcv(
        symbol=args.asset,
        timeframe=args.timeframe,
        since=since_ms,
        limit=args.days * 24,  # rough upper bound for 1h candles
    )
    logger.info(f"Fetched {len(feature_df)} candles")

    if len(feature_df) < 50:
        logger.warning("Insufficient data for optimization — need at least 50 candles")
        return

    # --- Build objective from this model's optimizer ---
    objective_fn = mr_optimizer.make_objective(
        feature_df, timeframe=args.timeframe, cost_bps=args.cost_bps,
    )

    # --- Resolve study config ---
    n_trials = args.n_trials or mr_optimizer.STUDY_DEFAULTS.get("n_trials", 200)
    study_config = StudyConfig(
        model_name=mr_optimizer.MODEL_NAME,
        asset=args.asset,
        timeframe=args.timeframe,
        n_trials=n_trials,
        sampler=mr_optimizer.STUDY_DEFAULTS.get("sampler", "TPE"),
        pruner=mr_optimizer.STUDY_DEFAULTS.get("pruner", "MedianPruner"),
        objectives=["score"],
        directions=[mr_optimizer.STUDY_DEFAULTS.get("direction", "maximize")],
    )

    # --- Run Optuna study ---
    runner = OptunaRunner(study_config)
    results = runner.run(objective_fn=objective_fn, study_name=args.study_name)

    completed = [r for r in results if r.state == "COMPLETE"]
    if not completed:
        logger.warning("No completed trials")
        return

    best = max(completed, key=lambda r: list(r.values.values())[0])
    processed_params = mr_optimizer.post_process_params(best.params)
    logger.info(f"Best trial #{best.trial_number}: params={processed_params} values={best.values}")

    # --- Audit ---
    if args.audit:
        current_params = read_current_params(
            mr_optimizer.MODEL_NAME, args.asset, args.timeframe,
        )
        if current_params:
            auditor = ParamAuditor(
                feature_df, timeframe=args.timeframe, cost_bps=args.cost_bps,
            )
            report = auditor.audit(
                mr_optimizer.MODEL_NAME, args.asset, args.timeframe,
                current_params, processed_params,
            )
            _print_audit_report(report)
        else:
            logger.info("No current params in models.yaml — skipping audit (first run)")

    # --- Write-back ---
    if args.write_back:
        write_best_params(
            mr_optimizer.MODEL_NAME, args.asset, args.timeframe, processed_params,
        )
        logger.info("Wrote best params to configs/optimized_params.yaml")

    logger.info(f"Optimization complete: {len(completed)}/{len(results)} trials completed")


def _print_audit_report(report) -> None:
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

### MeanReversion Monitor (`src/libs/models/mean_reversion/optimization/monitor.py`)

Same as v2 but path updated. Reads pickled Optuna study or is called programmatically after `runner.run()`. See v2 for full implementation. Only the module path changes from `mean_reversion.scripts.monitor` to `mean_reversion.optimization.monitor`.

### TrendFollowing and Momentum CLI Scripts

Follow the same pattern as MeanReversion. Each `optimize.py` differs in:
- Which optimizer module it imports (e.g., `from libs.models.trend_following.optimization import optimizer as tf_optimizer`)
- `MODEL_NAME` constant
- Multi-objective handling for TrendFollowing (Pareto front selection instead of scalar max)

The coder should use the MeanReversion script as a template, adjusting the import and best-trial selection.

## Optional Shared Dispatcher (`scripts/run_optimization.py`)

Thin convenience dispatcher for cron. Not required — each model can be invoked directly.

```python
"""Shared dispatcher — delegates to per-model optimization scripts.

Usage:
    PYTHONPATH=src python scripts/run_optimization.py \
        --model MeanReversion --asset BTCUSDT --timeframe 1h --audit --write-back

Each model can also be invoked directly:
    PYTHONPATH=src python -m libs.models.mean_reversion.optimization.optimize --asset ...
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

_MODEL_SCRIPTS: dict[str, str] = {
    "MeanReversion": "libs.models.mean_reversion.optimization.optimize",
    "TrendFollowing": "libs.models.trend_following.optimization.optimize",
    "Momentum": "libs.models.momentum.optimization.optimize",
}


def main() -> None:
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

    sys.argv = [sys.argv[0]] + sys.argv[1:idx] + sys.argv[idx + 2:]
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
    write_back: false

  schedules:
    MeanReversion:
      cron: "0 2 * * 1"           # weekly Monday 2am UTC
      assets: ["BTCUSDT", "ETHUSDT"]
      timeframes: ["1h", "4h"]
      write_back: true
    TrendFollowing:
      cron: "0 3 1 * *"           # monthly 1st 3am UTC
      assets: ["BTCUSDT"]
      timeframes: ["4h"]
      write_back: true
    Momentum:
      cron: "0 2 */14 * *"        # biweekly
      assets: ["BTCUSDT", "ETHUSDT"]
      timeframes: ["4h"]
      write_back: true
```

Cron invocation:
```bash
# MeanReversion: weekly Monday 2am UTC
0 2 * * 1 cd /path/to/flipperAgent && PYTHONPATH=src .venv/bin/python \
    -m libs.models.mean_reversion.optimization.optimize \
    --asset BTCUSDT --timeframe 1h --days 90 --audit --write-back
```

## Implementation Order

| Step | Task | Dependencies |
|------|------|-------------|
| 1 | Add new Pydantic contracts (`ParamAuditReport`, `ScheduleEntry`, `OptimizationDefaults`, `OptimizationConfig`) to `libs/contracts/schemas.py` | None |
| 2 | Create `libs/optimization/scoring.py` | None |
| 3 | Create `libs/optimization/data_fetcher.py` | None |
| 4 | Create `libs/optimization/param_auditor.py` | Steps 1, 2 |
| 5 | Create `libs/optimization/param_writeback.py` | None |
| 6 | Modify `libs/optimization/runner.py` — add `objective_fn` param, expose `study` | None |
| 7 | Update `libs/optimization/__init__.py` with new exports | Steps 2–5 |
| 8 | Restructure `mean_reversion.py` → `mean_reversion/` package | None |
| 9 | Restructure `trend_following.py` → `trend_following/` package | None |
| 10 | Restructure `momentum.py` → `momentum/` package | None |
| 11 | Create per-model `optimization/optimizer.py` files | Steps 2, 8–10 |
| 12 | Create per-model `optimization/optimize.py` and `optimization/monitor.py` | Steps 3, 4, 5, 6, 11 |
| 13 | Update `libs/models/__init__.py` (verify import paths) | Steps 8–11 |
| 14 | Create `configs/optimization.yaml` | Step 1 |
| 15 | Create `scripts/run_optimization.py` shared dispatcher (optional) | Step 12 |
| 16 | Write/update tests | All |
| 17 | Run full test suite, confirm backward compatibility | All |

## Acceptance Criteria

1. **Per-model packages:** Each model is a package (`mean_reversion/`, `trend_following/`, `momentum/`) with `model.py`, `optimization/optimizer.py`, `optimization/optimize.py`, `optimization/monitor.py`, and `__init__.py` that re-exports the model class.
2. **Backward-compatible imports:** `from libs.models.mean_reversion import MeanReversionModel` still works.
3. **No shared optimizer ABC:** No `BaseOptimizer`, no `OptimizerRegistry`, no `GenericOptimizer`.
4. **Fully independent optimizers:** Each model's `optimization/optimizer.py` can use any Optuna sampler, pruner, objective structure, or non-Optuna approach. No enforced method signatures.
5. **Scoring utilities:** `libs/optimization/scoring.py` provides `compute_returns()`, `compute_sharpe()`, `compute_max_drawdown()`, `compute_win_rate()` as optional pure-function utilities.
6. **No standalone Backtester:** Scoring lives inline in each model's optimizer objective function.
7. **Data fetching from Binance:** `libs/optimization/data_fetcher.py` uses `binance-futures-connector` SDK directly. No cross-app imports. Handles pagination for large date ranges.
8. **OptunaRunner backward compat:** `runner.run(backtest_fn=fn)` still works. New: `runner.run(objective_fn=fn)`. `runner.study` accessible after run.
9. **Param auditor:** `ParamAuditor.audit()` uses shared scoring utilities (not Backtester) to produce `ParamAuditReport` with standardized metrics, deltas, and recommendation.
10. **Param write-back:** Atomically writes to `configs/optimized_params.yaml` (NOT `models.yaml`).
11. **CLI scripts in `optimization/`:** Each model has `optimization/optimize.py` with `--asset`, `--timeframe`, `--days`, `--audit`, `--write-back` flags.
12. **Binance data in CLI:** `optimize.py` fetches data via `data_fetcher.fetch_historical_ohlcv()` — no `--data-path` flag needed (though models could add one for offline testing).
13. **Monitor reads in-memory:** Monitor uses Optuna study object or pickled study.
14. **All existing tests pass** with no modifications to test logic (only import paths if needed).
15. **No `os.getenv`** — all config via `ConfigManager`.
16. **No `logging.getLogger`** — all logging via `bind_logger`.
17. **No cross-app imports** — `libs/` never imports from `apps/`.

## Validation Checklist

- [ ] `from libs.models.mean_reversion import MeanReversionModel` works
- [ ] `from libs.models.trend_following import TrendFollowingModel` works
- [ ] `from libs.models.momentum import MomentumModel` works
- [ ] `ModelRegistry.list_all()` returns all 3 models
- [ ] No `BaseOptimizer`, `OptimizerRegistry`, or `GenericOptimizer` files exist
- [ ] `from libs.optimization.scoring import compute_sharpe, compute_returns` works
- [ ] `from libs.optimization.data_fetcher import fetch_historical_ohlcv` works
- [ ] `fetch_historical_ohlcv("BTCUSDT", "1h", since=..., limit=100)` returns DataFrame with OHLCV columns
- [ ] Data fetcher paginates correctly for limit > 1500
- [ ] `OptunaRunner(config).run(backtest_fn=fn)` still works (backward compat)
- [ ] `OptunaRunner(config).run(objective_fn=fn)` works with per-model objective
- [ ] `runner.study` is a valid `optuna.Study` after `run()`
- [ ] MeanReversion optimizer objective returns single float (sharpe - drawdown penalty)
- [ ] TrendFollowing optimizer objective returns tuple (sharpe, win_rate)
- [ ] Per-model optimizers do NOT share a base class
- [ ] `ParamAuditor.audit()` returns `ParamAuditReport` with correct deltas
- [ ] Audit uses `scoring.py` utilities, not a Backtester class
- [ ] `write_best_params()` writes to `configs/optimized_params.yaml` (NOT models.yaml)
- [ ] `read_current_params()` reads from `configs/models.yaml`
- [ ] `python -m libs.models.mean_reversion.optimization.optimize --help` works
- [ ] `python -m libs.models.mean_reversion.optimization.optimize --asset BTCUSDT --timeframe 1h` fetches from Binance and runs
- [ ] No file in `libs/` imports from `apps/`
- [ ] Monitor `print_study_summary(study)` prints correct stats

## Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Binance API rate limits during data fetch | MEDIUM | data_fetcher uses pagination with reasonable batch sizes; add sleep between batches if needed |
| Scoring utility duplication vs ingestion_app constants | LOW | OHLCV column names are duplicated in data_fetcher — acceptable since they're a stable Binance contract, not an internal abstraction |
| Per-model optimizer code duplication | LOW | Some boilerplate (arg parsing, config merge) is repeated across models. Acceptable in v1; extract shared helpers in v2 if duplication becomes painful |
| OptunaRunner assumes Optuna | LOW | Models that want non-Optuna optimization can skip OptunaRunner entirely and create their own study/optimization loop |
| data_fetcher creates a new UMFutures client per call | LOW | Optimization is offline batch — no connection pooling needed |
