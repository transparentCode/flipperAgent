---
goal: Redesign optimization layer with per-model optimizer folders, CLI runner, monitoring script, cron scheduling, and param write-back
stage: architect-to-coder
date_created: 2026-05-25
last_updated: 2026-05-25
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, optimization, per-model-optimizer, cli, cron, param-writeback]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Architect → Coder: Optimization Layer Redesign v1

## Objective

Redesign the optimization layer so that each model can define its own optimization technique, objective function, scoring logic, and default config — while keeping shared infrastructure (`OptunaRunner`, `TrialStore`) in `libs/optimization/`. Add a CLI runner script, monitoring script, cron scheduling config, and automatic param write-back to `configs/models.yaml`.

## Scope Boundaries

### In Scope
- Restructure model files into packages with co-located optimizer files
- Add `BaseOptimizer` ABC and `OptimizerRegistry` to shared optimization infrastructure
- Add `GenericOptimizer` fallback for models without custom optimizers
- Add `param_writeback.py` for atomic config write-back
- Minor additive change to `OptunaRunner.run()` (optional `objective_fn` param)
- New Pydantic contracts: `ScheduleEntry`, `OptimizationDefaults`, `OptimizationConfig`
- CLI runner script (`scripts/run_optimization.py`)
- Monitoring script (`scripts/monitor_optimization.py`)
- New config file (`configs/optimization.yaml`)
- Per-model optimizer implementations for MeanReversion, TrendFollowing, Momentum
- Update `libs/models/__init__.py` for new package structure
- Update existing tests for new import paths

### Out of Scope (Explicit Non-Goals)
- No changes to `BaseModel`, `ModelMeta`, or `ModelRegistry`
- No changes to `TrialStore` or `trial_store.py`
- No changes to `StrategyWorker`, `ModelManager`, or any app-level code
- No backtester implementation — the CLI accepts a backtest function / data path
- No persistent worker or daemon — optimization is offline CLI + cron only
- No changes to `configs/models.yaml` structure (only write-back writes to it)
- No Docker/Kubernetes CronJob manifests — document crontab usage only
- No git auto-commit on write-back

## Affected Symbols, Modules, and Execution Flows

### Modified Files
| File | Change | Risk |
|------|--------|------|
| `src/libs/models/mean_reversion.py` | Delete after moving to `mean_reversion/model.py` | LOW |
| `src/libs/models/trend_following.py` | Delete after moving to `trend_following/model.py` | LOW |
| `src/libs/models/momentum.py` | Delete after moving to `momentum/model.py` | LOW |
| `src/libs/models/__init__.py` | Update auto-import paths | LOW |
| `src/libs/optimization/runner.py` | Add optional `objective_fn` param to `run()` | LOW |
| `src/libs/optimization/__init__.py` | Add new exports | LOW |
| `src/libs/contracts/schemas.py` | Add `ScheduleEntry`, `OptimizationDefaults`, `OptimizationConfig` | LOW |
| `tests/models/test_optimization.py` | Verify imports still work (should be unchanged) | LOW |

### New Files
| File | Purpose |
|------|---------|
| `src/libs/optimization/base_optimizer.py` | `BaseOptimizer` ABC |
| `src/libs/optimization/optimizer_registry.py` | `OptimizerRegistry` + `GenericOptimizer` |
| `src/libs/optimization/param_writeback.py` | Atomic param write-back to YAML |
| `src/libs/models/mean_reversion/__init__.py` | Re-export `MeanReversionModel` |
| `src/libs/models/mean_reversion/model.py` | Model class (moved) |
| `src/libs/models/mean_reversion/optimizer.py` | `MeanReversionOptimizer` |
| `src/libs/models/trend_following/__init__.py` | Re-export `TrendFollowingModel` |
| `src/libs/models/trend_following/model.py` | Model class (moved) |
| `src/libs/models/trend_following/optimizer.py` | `TrendFollowingOptimizer` |
| `src/libs/models/momentum/__init__.py` | Re-export `MomentumModel` |
| `src/libs/models/momentum/model.py` | Model class (moved) |
| `src/libs/models/momentum/optimizer.py` | `MomentumOptimizer` |
| `scripts/run_optimization.py` | CLI runner |
| `scripts/monitor_optimization.py` | Study progress viewer |
| `configs/optimization.yaml` | Schedule + defaults config |

### Execution Flows Unaffected
- `StrategyWorker` → `ModelManager` → `ModelRegistry.get()` → model: **unchanged** (re-export `__init__.py` preserves import path)
- `SignalWorker` → `FeatureVector` publish: **unchanged**
- All existing indicator, feature, ingestion flows: **unchanged**

## Data Contracts and Interfaces

### New Pydantic Schemas (add to `src/libs/contracts/schemas.py`)

```python
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
    """Registry for per-model optimizers. Mirrors ModelRegistry pattern."""

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

Add optional `objective_fn` parameter to `run()`. Existing callers unaffected.

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

### Param Write-back (new `src/libs/optimization/param_writeback.py`)

```python
"""Atomic param write-back to configs/models.yaml."""

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)

MODELS_CONFIG_PATH = Path("configs/models.yaml")


def write_best_params(
    model_name: str,
    asset: str,
    timeframe: str,
    params: dict[str, Any],
    config_path: Path = MODELS_CONFIG_PATH,
) -> None:
    """Atomically update best params in models.yaml for a given model/asset/tf.

    Steps:
    1. Read current YAML.
    2. Navigate to models.assets.{asset}.timeframes.{tf}.{model_name}.params.
    3. Merge new params over existing.
    4. Write to temp file, then os.replace() for atomicity.
    5. Log before/after diff.
    """
    config = _read_yaml(config_path)

    # Navigate / create path
    models_node = config.setdefault("models", {})
    assets_node = models_node.setdefault("assets", {})
    asset_node = assets_node.setdefault(asset, {})
    tf_node = asset_node.setdefault("timeframes", {}).setdefault(timeframe, {})
    model_node = tf_node.setdefault(model_name, {"enabled": True, "params": {}})

    old_params = dict(model_node.get("params", {}))
    model_node["params"] = {**old_params, **params}

    _write_yaml_atomic(config_path, config)

    logger.info(
        f"Wrote best params for {model_name}/{asset}/{timeframe}: "
        f"old={old_params} new={model_node['params']}"
    )


def _read_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _write_yaml_atomic(path: Path, data: dict[str, Any]) -> None:
    dir_path = path.parent
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
        # Re-suggest if constraint violated
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

### Model Package __init__.py Pattern

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

## CLI Runner Design (`scripts/run_optimization.py`)

```python
"""CLI runner for offline optimization.

Usage:
    python scripts/run_optimization.py \
        --model MeanReversion \
        --asset BTCUSDT \
        --timeframe 1h \
        --n-trials 200 \
        --write-back

Configuration priority: CLI args > per-model defaults > optimization.yaml defaults > StudyConfig defaults.
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure src/ is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import StudyConfig
from libs.optimization.runner import OptunaRunner
from libs.optimization.optimizer_registry import OptimizerRegistry
from libs.optimization.param_writeback import write_best_params
from libs.optimization.trial_store import TrialStore

# Trigger model + optimizer registration
import libs.models  # noqa: F401

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)

CONFIG_FILE_OPTIMIZATION = "configs/optimization.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run model optimization study")
    parser.add_argument("--model", required=True, help="Model name (e.g., MeanReversion)")
    parser.add_argument("--asset", required=True, help="Asset symbol (e.g., BTCUSDT)")
    parser.add_argument("--timeframe", required=True, help="Timeframe (e.g., 1h)")
    parser.add_argument("--n-trials", type=int, default=None, help="Number of trials")
    parser.add_argument("--sampler", default=None, help="Sampler: TPE or NSGA-II")
    parser.add_argument("--pruner", default=None, help="Pruner: MedianPruner or NopPruner")
    parser.add_argument("--objectives", nargs="+", default=None, help="Objective names")
    parser.add_argument("--directions", nargs="+", default=None, help="Directions: maximize/minimize")
    parser.add_argument("--write-back", action="store_true", help="Write best params to models.yaml")
    parser.add_argument("--study-name", default=None, help="Custom study name")
    return parser.parse_args()


def build_study_config(args: argparse.Namespace) -> StudyConfig:
    """Merge CLI args with per-model defaults and global defaults."""
    config_mgr = ConfigManager()
    config_mgr.register_file(CONFIG_FILE_OPTIMIZATION)
    opt_config = config_mgr.get("optimization", {})
    global_defaults = opt_config.get("defaults", {})

    optimizer = OptimizerRegistry.get_or_default(args.model)
    model_defaults = optimizer.default_study_config()

    def resolve(cli_val, model_val_key, global_val_key, fallback):
        if cli_val is not None:
            return cli_val
        if model_val_key in model_defaults:
            return model_defaults[model_val_key]
        if global_val_key in global_defaults:
            return global_defaults[global_val_key]
        return fallback

    return StudyConfig(
        model_name=args.model,
        asset=args.asset,
        timeframe=args.timeframe,
        n_trials=resolve(args.n_trials, "n_trials", "n_trials", 200),
        sampler=resolve(args.sampler, "sampler", "sampler", "TPE"),
        pruner=resolve(args.pruner, "pruner", "pruner", "MedianPruner"),
        objectives=resolve(args.objectives, "objectives", None, ["sharpe"]),
        directions=resolve(args.directions, "directions", None, ["maximize"]),
    )


def make_backtest_fn(asset: str, timeframe: str):
    """Placeholder: load historical data and return a backtest callable.

    The coder should integrate with the actual backtester or provide
    a data-loading + evaluation pipeline here.
    """
    raise NotImplementedError(
        "Backtest function must be implemented. "
        "It should accept a BaseModel instance and return dict[str, float] of metrics."
    )


def main() -> None:
    args = parse_args()

    study_config = build_study_config(args)
    optimizer = OptimizerRegistry.get_or_default(args.model)

    # Build objective via per-model optimizer
    backtest_fn = make_backtest_fn(args.asset, args.timeframe)
    objective_fn = optimizer.build_objective(backtest_fn)

    # Run study
    runner = OptunaRunner(study_config)
    results = runner.run(objective_fn=objective_fn, study_name=args.study_name)

    # Log summary
    completed = [r for r in results if r.state == "COMPLETE"]
    if completed:
        best = max(completed, key=lambda r: list(r.values.values())[0])
        logger.info(f"Best trial #{best.trial_number}: params={best.params} values={best.values}")

    # Write-back if requested
    if args.write_back and completed:
        best = max(completed, key=lambda r: list(r.values.values())[0])
        processed_params = optimizer.post_process_params(best.params)
        write_best_params(args.model, args.asset, args.timeframe, processed_params)
        logger.info(f"Wrote best params to configs/models.yaml")

    logger.info(f"Optimization complete: {len(completed)}/{len(results)} trials completed")


if __name__ == "__main__":
    main()
```

## Monitoring Script Design (`scripts/monitor_optimization.py`)

```python
"""Monitor optimization study progress via TimescaleDB.

Usage:
    python scripts/monitor_optimization.py \
        --study-name MeanReversion_BTCUSDT_1h \
        --top-n 10

Outputs: study summary, best trial, top-N table, convergence stats.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor optimization study progress")
    parser.add_argument("--study-name", required=True, help="Study name to monitor")
    parser.add_argument("--top-n", type=int, default=5, help="Number of top trials to show")
    parser.add_argument("--objective-key", default="sharpe", help="Objective key for ranking")
    parser.add_argument("--show-convergence", action="store_true", help="Show convergence stats")
    parser.add_argument("--show-pareto", action="store_true", help="Show Pareto front (multi-obj)")
    return parser.parse_args()


async def run_monitor(args: argparse.Namespace) -> None:
    """Query TimescaleDB for study progress and display results."""
    import asyncpg

    config_mgr = ConfigManager()
    pg_config = config_mgr.get("postgres", {})

    pool = await asyncpg.create_pool(
        host=pg_config.get("host", "localhost"),
        port=pg_config.get("port", 5432),
        user=pg_config.get("user", "flipper"),
        password=pg_config.get("password", "flipperpass"),
        database=pg_config.get("database", "flipper_db"),
    )

    try:
        from libs.optimization.trial_store import TrialStore
        store = TrialStore(pool)

        # Query best trials
        best_trials = await store.query_best(
            study_name=args.study_name,
            objective_key=args.objective_key,
            limit=args.top_n,
        )

        # Summary query
        async with pool.acquire() as conn:
            summary = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) AS total_trials,
                    COUNT(*) FILTER (WHERE state = 'COMPLETE') AS completed,
                    COUNT(*) FILTER (WHERE state = 'PRUNED') AS pruned,
                    COUNT(*) FILTER (WHERE state = 'FAIL') AS failed,
                    MIN(created_at) AS started_at,
                    MAX(created_at) AS last_trial_at
                FROM optimization_trials
                WHERE study_name = $1
                """,
                args.study_name,
            )

        # Display results
        print(f"\n{'='*60}")
        print(f"Study: {args.study_name}")
        print(f"{'='*60}")
        if summary:
            print(f"Total trials:  {summary['total_trials']}")
            print(f"Completed:     {summary['completed']}")
            print(f"Pruned:        {summary['pruned']}")
            print(f"Failed:        {summary['failed']}")
            print(f"Started:       {summary['started_at']}")
            print(f"Last trial:    {summary['last_trial_at']}")

        print(f"\nTop {args.top_n} trials (by {args.objective_key}):")
        print(f"{'-'*60}")
        for i, trial in enumerate(best_trials, 1):
            obj_vals = trial.get("objective_values", {})
            params = trial.get("params", {})
            print(f"  #{i} Trial {trial.get('trial_number', '?')}: "
                  f"objectives={json.dumps(obj_vals)} "
                  f"params={json.dumps(params)}")

        if args.show_convergence and best_trials:
            print(f"\nConvergence: best {args.objective_key} = "
                  f"{best_trials[0].get('objective_values', {}).get(args.objective_key, 'N/A')}")

    finally:
        await pool.close()


def main() -> None:
    args = parse_args()
    asyncio.run(run_monitor(args))


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
```
# MeanReversion: weekly Monday 2am UTC
0 2 * * 1 cd /path/to/flipperAgent && .venv/bin/python scripts/run_optimization.py --model MeanReversion --asset BTCUSDT --timeframe 1h --write-back
```

## Implementation Order

| Step | Task | Dependencies |
|------|------|-------------|
| 1 | Add new Pydantic contracts (`ScheduleEntry`, `OptimizationDefaults`, `OptimizationConfig`) to `libs/contracts/schemas.py` | None |
| 2 | Create `libs/optimization/base_optimizer.py` | Step 1 |
| 3 | Create `libs/optimization/optimizer_registry.py` | Step 2 |
| 4 | Create `libs/optimization/param_writeback.py` | None |
| 5 | Modify `libs/optimization/runner.py` — add `objective_fn` param | None |
| 6 | Update `libs/optimization/__init__.py` with new exports | Steps 2-4 |
| 7 | Restructure `mean_reversion.py` → `mean_reversion/` package | None |
| 8 | Restructure `trend_following.py` → `trend_following/` package | None |
| 9 | Restructure `momentum.py` → `momentum/` package | None |
| 10 | Create per-model `optimizer.py` files (MeanReversion, TrendFollowing, Momentum) | Steps 3, 7-9 |
| 11 | Update `libs/models/__init__.py` (import paths unchanged but verify) | Steps 7-10 |
| 12 | Create `configs/optimization.yaml` | Step 1 |
| 13 | Create `scripts/run_optimization.py` | Steps 3, 5, 6 |
| 14 | Create `scripts/monitor_optimization.py` | Step 4 |
| 15 | Write/update tests | All |
| 16 | Run full test suite, confirm backward compatibility | All |

## Acceptance Criteria

1. **Per-model packages:** Each model is a package (`mean_reversion/`, `trend_following/`, `momentum/`) with `model.py`, `optimizer.py`, and `__init__.py` that re-exports the model class.
2. **Backward-compatible imports:** `from libs.models.mean_reversion import MeanReversionModel` still works.
3. **BaseOptimizer ABC:** Defined in `libs/optimization/base_optimizer.py` with `model_name`, `default_study_config()`, `build_objective()`, `suggest_params()`, `post_process_params()`.
4. **OptimizerRegistry:** `register()`, `get()`, `get_or_default()`, `list_all()`. `get_or_default()` returns `GenericOptimizer` when no custom optimizer is registered.
5. **GenericOptimizer:** Uses `make_objective()` as fallback — any model works without a custom optimizer.
6. **OptunaRunner backward compat:** `runner.run(backtest_fn=fn)` still works. New path: `runner.run(objective_fn=fn)`.
7. **Param write-back:** Atomically updates `configs/models.yaml` via temp file + `os.replace()`.
8. **CLI runner:** `scripts/run_optimization.py` with argparse, config merging (CLI > model > global > defaults).
9. **Monitor script:** `scripts/monitor_optimization.py` queries TimescaleDB, shows study summary and top trials.
10. **Config:** `configs/optimization.yaml` with `defaults` and `schedules` sections, validated by `OptimizationConfig` schema.
11. **All existing tests pass** with no modifications to test logic (only import paths if needed).
12. **No `os.getenv`** — all config via `ConfigManager`.
13. **No `logging.getLogger`** — all logging via `bind_logger`.

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
- [ ] `write_best_params()` atomically updates `models.yaml`
- [ ] CLI `--help` works, all args parse correctly
- [ ] CLI runs with `--model MeanReversion --asset BTCUSDT --timeframe 1h --n-trials 5`
- [ ] Monitor script connects and displays study summary
- [ ] `configs/optimization.yaml` validates against `OptimizationConfig` schema
- [ ] Existing `test_optimization.py` passes without changes
- [ ] No `os.getenv` in any new code
- [ ] No `logging.getLogger` in any new code
- [ ] Full test suite passes: `PYTHONPATH=. .venv/bin/pytest tests/ --ignore=tests/e2e -q`

## New Test Requirements

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
- Objective function calls backtest_fn and applies custom scoring

### `tests/models/test_param_writeback.py`
- `write_best_params()` creates model/asset/tf entry if missing
- `write_best_params()` merges new params over existing
- Atomic write: no corruption on failure (mock `os.replace` to verify)
- Reads back correctly after write

### `tests/models/test_cli_runner.py`
- Arg parsing: all flags parse correctly
- Config merge priority: CLI > model > global > defaults
- Missing `--model` raises error
- `--write-back` flag is boolean

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
5. If custom optimizer added, update `__init__.py` to import it:
   ```python
   import libs.models.volatility_breakout.optimizer  # noqa: F401
   ```

Zero extra work required for basic optimization. Custom scoring is opt-in.

## Risks and Follow-Up Items

| Item | Type | Notes |
|------|------|-------|
| Backtest function placeholder | Follow-up | CLI has `NotImplementedError` — needs actual backtester integration |
| File lock for cron overlap | Follow-up | Add `fcntl.flock` or `filelock` to prevent concurrent studies |
| Write-back validation | Follow-up | After write-back, load model to confirm valid config |
| Monitor Pareto display | Follow-up | `--show-pareto` not fully implemented — needs multi-obj query |
| `generate_crontab.py` helper | Follow-up | Script to emit crontab lines from `optimization.yaml` |
