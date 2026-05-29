"""Public facade for regression.

Consumer-facing API — all external callers go through these functions.
Follows the v1 pattern from ``app/regression/api.py``.

Functions:
    compute_single_tf()      — single (asset, tf) computation
    compute_single_tf_series() — rolling window (backtest mode)
    compute_mtf()            — multi-timeframe cascade for one asset
    compute_universe()       — batch N-asset orchestration
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from .config.resolver import ConfigResolver
from .config.schema import ResolvedPipelineConfig
from .contracts.context import (
    CascadeContext,
    PipelineRequest,
    RegimeSnapshot,
)
from .contracts.result import (
    MTFOutput,
    RegressionResult,
    UniverseResult,
)
from .pipeline import RegressionPipeline
from .state import NullStateManager, StateManager
from .universe import UniverseOrchestrator


def compute_single_tf(
    df: pd.DataFrame,
    asset: str,
    timeframe: str,
    config: ResolvedPipelineConfig,
    regime: Optional[RegimeSnapshot] = None,
    cascade: Optional[CascadeContext] = None,
    state_manager: Optional[StateManager] = None,
) -> RegressionResult:
    """Compute regression for a single (asset, timeframe).

    This is the primary entrypoint for live tick processing.
    """
    pipeline = RegressionPipeline(config, state_manager or NullStateManager())
    request = PipelineRequest(
        df=df,
        asset=asset,
        timeframe=timeframe,
        mode="fit_last",
        config=config,
        regime=regime,
        cascade=cascade,
    )
    return pipeline.compute(request)


def compute_single_tf_series(
    df: pd.DataFrame,
    asset: str,
    timeframe: str,
    config: ResolvedPipelineConfig,
    regime: Optional[RegimeSnapshot] = None,
    state_manager: Optional[StateManager] = None,
) -> List[RegressionResult]:
    """Compute regression over a rolling window (backtest mode).

    Returns one RegressionResult per bar from window_size to end.
    """
    pipeline = RegressionPipeline(config, state_manager or NullStateManager())
    request = PipelineRequest(
        df=df,
        asset=asset,
        timeframe=timeframe,
        mode="fit_series",
        config=config,
        regime=regime,
    )
    return pipeline.compute_series(request)


def compute_mtf(
    asset: str,
    tf_data: Dict[str, pd.DataFrame],
    resolver: ConfigResolver,
    regime: Optional[RegimeSnapshot] = None,
    state_manager: Optional[StateManager] = None,
) -> MTFOutput:
    """Run multi-timeframe cascade for a single asset.

    Uses the UniverseOrchestrator internally for MTF logic.
    """
    orchestrator = UniverseOrchestrator(resolver, state_manager)
    asset_meta = orchestrator._resolve_asset_meta(asset)
    return orchestrator._run_mtf_cascade(asset, tf_data, regime, asset_meta, "fit_last")


def compute_universe(
    universe_data: Dict[str, Dict[str, pd.DataFrame]],
    resolver: ConfigResolver,
    regime_data: Optional[Dict[str, RegimeSnapshot]] = None,
    state_manager: Optional[StateManager] = None,
    max_workers: int = 4,
    mode: str = "fit_last",
) -> UniverseResult:
    """Process a universe of assets.

    Args:
        universe_data: {asset: {timeframe: DataFrame}}.
        resolver: ConfigResolver with loaded YAML config.
        regime_data: Optional {asset: RegimeSnapshot}.
        state_manager: Optional state manager for stateful plugins.
        max_workers: Thread pool size (unused for now — sequential).
        mode: "fit_last" or "fit_series".

    Returns:
        UniverseResult with per-asset results and statistics.
    """
    orchestrator = UniverseOrchestrator(resolver, state_manager, max_workers)
    return orchestrator.process_universe(universe_data, regime_data, mode)


def optimize_regression(
    df: pd.DataFrame,
    asset: str = "UNKNOWN",
    timeframe: str = "1h",
    resolver: Optional["ConfigResolver"] = None,
    config: Optional["RegressionOptimizationConfig"] = None,
    n_trials: Optional[int] = None,
    timeout: Optional[int] = None,
    callbacks: Optional[list] = None,
) -> "RegressionOptimizationResult":
    """Run MOTPE multi-objective optimization on the regression pipeline.

    Facade that wraps RegressionMOTPEOptimizer for simple one-call usage.

    Args:
        df: OHLCV DataFrame.
        asset: Asset symbol.
        timeframe: Timeframe string.
        resolver: Optional ConfigResolver (for pipeline construction).
        config: V2 optimization config (MOTPE, search space, walk-forward).
        n_trials: Override config.n_trials.
        timeout: Override config.timeout_seconds.
        callbacks: Unused (kept for API compat).

    Returns:
        RegressionOptimizationResult with best params, Pareto front, and benchmarks.
    """
    from app.regression.config.schema import OrchestratorConfig
    from app.regression.optimization.models import (
        RegressionOptimizationConfig as _OptConfig,
    )
    from app.regression.optimization.optimizer import RegressionMOTPEOptimizer
    from app.regression.optimization.pipeline_factory import build_pipeline_factory

    opt_config = config or _OptConfig()

    # Apply CLI-style overrides
    if n_trials is not None:
        opt_config = opt_config.model_copy(update={"n_trials": n_trials})
    if timeout is not None:
        opt_config = opt_config.model_copy(update={"timeout_seconds": timeout})

    # Build resolver if not provided
    if resolver is None:
        resolver = ConfigResolver.from_yaml(
            "app/regression/config/regression.yaml"
        )

    # Resolve orchestrator config for search space building
    orch_config = OrchestratorConfig()
    try:
        resolved = resolver.resolve(asset, timeframe)
        if hasattr(resolved, "orchestrator"):
            orch_config = resolved.orchestrator
    except Exception:
        pass

    pipeline_factory = build_pipeline_factory(resolver)
    optimizer = RegressionMOTPEOptimizer(
        config=opt_config,
        orch_config=orch_config,
        pipeline_factory=pipeline_factory,
    )
    return optimizer.optimize(df, asset=asset, timeframe=timeframe)
