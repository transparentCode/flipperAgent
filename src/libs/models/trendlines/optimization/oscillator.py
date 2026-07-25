"""Oscillator trendlines optimization.

Adapts the price-space optimizer (TrendlinesOptimizer) for oscillator-space
trendlines. The core 5-tier objective (longevity, touch accuracy, penetration
gate, pivot density, fold stability) is reused — it operates on Trendline
objects which are scale-agnostic.

Key differences from price optimization:
- Search space: only interaction_tolerance_atr + categorical extractor/fitter
  params. Signal params (asymmetry, convergence, wick, squeeze) are irrelevant
  in oscillator space.
- Pipeline factory: uses oscillator-specific config from YAML, not
  resolve_asset_config().
- YAML write-back: results go to oscillator_overrides.{type}, not
  assets.{asset}.timeframes.{tf}.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Callable, Dict, Optional

import pandas as pd

from libs.models.trendlines.optimization.models import (
    TrendlinesOptimizationConfig,
    TrendlinesOptimizationResult,
)
from libs.models.trendlines.optimization.optimizer import TrendlinesOptimizer

logger = logging.getLogger("libs.models.trendlines.optimization")


def _oscillator_pipeline_factory(
    params: dict,
    asset: str,
    timeframe: str,
):
    """Pipeline factory for oscillator trendlines optimization."""
    from libs.models.trendlines import TrendlinePipelineConfig, build_extractor
    from libs.models.trendlines.pipeline import run_trendline_pipeline_from_config

    def run(train_df: pd.DataFrame):
        left_w = params.get("left_window", 5)
        right_w = params.get("right_window", 5)
        pivot_w = params.get("pivot_window", 2)
        fitter_name = params.get("fitter", "ensemble")

        config = TrendlinePipelineConfig(
            extractor="fractal",
            fitter=fitter_name,
            extractor_params={"window_left": left_w, "window_right": right_w},
            fitter_params={"pivot_window": pivot_w},
        )
        fit_result = run_trendline_pipeline_from_config(train_df, config)

        extractor = build_extractor(config.extractor, **config.extractor_params)
        pivots = extractor.extract(train_df)
        n_pivots = pivots.n_highs + pivots.n_lows

        return fit_result, n_pivots

    return run


@dataclasses.dataclass
class OscillatorOptimizationConfig(TrendlinesOptimizationConfig):
    """Search space for oscillator trendline optimization.

    Overrides the price defaults to use oscillator-appropriate ranges:
    - interaction_tolerance_atr: wider range (0.5 — 3.0) since oscillator ATR is small
    - Signal params (asymmetry, convergence, wick, squeeze) are fixed — not optimized
    """

    # Oscillator-appropriate search range
    interaction_tolerance_atr: tuple = (0.5, 3.0)

    # Signal params are NOT optimized for oscillators — fix at defaults
    asymmetry_threshold: tuple = (0.3, 0.3)
    convergence_rate_threshold: tuple = (0.2, 0.2)
    wick_rejection_ratio: tuple = (0.5, 0.5)
    squeeze_threshold: tuple = (3.0, 3.0)

    # Smaller walk-forward windows for oscillator (less data needed)
    train_bars: int = 500
    test_bars: int = 150
    step_bars: int = 150
    purge_bars: int = 5
    min_train_bars: int = 300

    # Default run settings
    n_trials: int = 30
    timeout_seconds: int = 600


def optimize_oscillator_trendlines(
    df: pd.DataFrame,
    asset: str,
    timeframe: str,
    oscillator_type: str,
    config: Optional[OscillatorOptimizationConfig] = None,
    n_trials: Optional[int] = None,
    timeout: Optional[int] = None,
    callbacks: Optional[list] = None,
) -> TrendlinesOptimizationResult:
    """Run oscillator trendline optimization.

    Parameters
    ----------
    df : pd.DataFrame
        Synthetic OHLCV from prepare_oscillator_df(). Must have DatetimeIndex.
    asset : str
        Asset name (for result metadata).
    timeframe : str
        Timeframe (for result metadata and TF-derived params).
    oscillator_type : str
        Oscillator type ("rsi", "macd") — used for YAML write-back.
    config : OscillatorOptimizationConfig, optional
        Search space and run settings. Defaults to oscillator-appropriate ranges.
    n_trials : int, optional
        Override number of trials.
    timeout : int, optional
        Override timeout in seconds.
    callbacks : list, optional
        Optuna callbacks for monitoring.

    Returns
    -------
    TrendlinesOptimizationResult
        Result with best params. Use apply_oscillator_result() to write to YAML.
    """
    opt_cfg = config or OscillatorOptimizationConfig()
    optimizer = TrendlinesOptimizer(
        config=opt_cfg,
        pipeline_factory=_oscillator_pipeline_factory,
    )
    result = optimizer.optimize(
        df=df,
        asset=asset,
        timeframe=timeframe,
        n_trials=n_trials,
        timeout=timeout,
        callbacks=callbacks,
    )
    # Tag the result with oscillator metadata
    result.best_params["_oscillator_type"] = oscillator_type
    return result


def apply_oscillator_result(
    result: TrendlinesOptimizationResult,
    yaml_path: str,
    oscillator_type: str,
) -> None:
    """Write optimized oscillator params to trendlines.yaml.

    Writes to ``oscillator_overrides.{type}`` section instead of the
    price ``assets.{asset}.timeframes.{tf}`` section.
    """
    import yaml

    with open(yaml_path) as f:
        cfg = yaml.safe_load(f) or {}

    # Extract the oscillator-relevant keys
    osc_keys = {"interaction_tolerance_atr"}
    overrides = {
        k: round(v, 6) if isinstance(v, float) else v
        for k, v in result.best_params.items()
        if k in osc_keys
    }

    # Map categorical params to oscillator defaults format
    if "left_window" in result.best_params:
        ep = overrides.setdefault("extractor_params", {})
        ep["window_left"] = result.best_params["left_window"]
    if "right_window" in result.best_params:
        ep = overrides.setdefault("extractor_params", {})
        ep["window_right"] = result.best_params["right_window"]
    if "pivot_window" in result.best_params:
        fp = overrides.setdefault("fitter_params", {})
        fp["pivot_window"] = result.best_params["pivot_window"]

    if not overrides:
        return

    osc_overrides = cfg.setdefault("oscillator_overrides", {})
    osc_block = osc_overrides.setdefault(oscillator_type.lower(), {})
    osc_block.update(overrides)

    with open(yaml_path, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

    logger.info(
        "Applied oscillator optimization results to %s [oscillator_overrides.%s]",
        yaml_path, oscillator_type,
    )
