"""Canonical facade API for the trendlines package.

Consumers should prefer these composed functions over manually chaining
the extract → fit → adapt → signal pipeline stages.

Resolution flow (for fit_and_signal):
1. Run extract → fit to get TrendlineFitResult
2. Build AssetProfile from df + fit_result
3. Resolve config: defaults → asset/TF overrides → derived params
4. Build BoundaryResult using resolved boundary config
5. Run signal extractors using resolved signal config
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional

import pandas as pd

from libs.models.trendlines.boundary.adapters import build_boundary_result_from_trendline_result
from libs.models.trendlines.boundary.contracts import BoundaryResult
from libs.models.trendlines.config import TrendlinePipelineConfig, TrendlinesConfig, load_trendlines_config
from libs.models.trendlines.config.resolve import resolve_asset_config
from libs.models.trendlines.contracts import TrendlineFitResult
from libs.models.trendlines.pipeline import (
    execute_trendline_pipeline,
)
from libs.models.trendlines.pivots.capabilities import TrendlineExecutionMode
from libs.models.trendlines.signals.orchestrator import TrendlineSignalOrchestrator

if TYPE_CHECKING:
    from libs.models.trendlines.optimization import (
        TrendlinesOptimizationConfig,
        TrendlinesOptimizationResult,
    )


@dataclass
class TrendlineOutput:
    """Unified output wrapping fit, boundary, and signal results.

    This is the preferred return type for the facade functions.
    Individual stages are accessible via the ``fit_result``,
    ``boundary_result``, and ``signal_output`` fields.
    """

    fit_result: TrendlineFitResult
    boundary_result: Optional[BoundaryResult] = None
    signal_output: Optional[Dict[str, Any]] = None
    config: Optional[TrendlinePipelineConfig] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return self.fit_result.is_valid

    @property
    def composite_direction(self) -> float:
        if self.signal_output is None:
            return 0.0
        return float(self.signal_output.get("composite_direction", 0.0))

    @property
    def composite_confidence(self) -> float:
        if self.signal_output is None:
            return 0.0
        return float(self.signal_output.get("composite_confidence", 0.0))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fit_result": self.fit_result.to_dict(),
            "boundary_result": self.boundary_result.to_dict() if self.boundary_result else None,
            "signal_output": self.signal_output,
            "config": self.config.to_dict() if self.config else None,
            "is_valid": self.is_valid,
            "metadata": dict(self.metadata),
        }


def fit_trendlines(
    df: pd.DataFrame,
    *,
    config: TrendlinePipelineConfig | Mapping[str, Any] | None = None,
    extractor: str = "fractal",
    fitter: str = "pathfinding",
    extractor_kwargs: dict[str, Any] | None = None,
    fitter_kwargs: dict[str, Any] | None = None,
    execution_mode: TrendlineExecutionMode | str = TrendlineExecutionMode.RUNTIME,
) -> TrendlineOutput:
    """Run the core extract → fit pipeline and return a unified output.

    This is the simplest entry point when you only need the raw
    trendline fit result without boundary adaptation or signals.
    """

    fit_result, resolved_config = execute_trendline_pipeline(
        df,
        config=config,
        extractor=extractor,
        fitter=fitter,
        extractor_kwargs=extractor_kwargs,
        fitter_kwargs=fitter_kwargs,
        execution_mode=execution_mode,
    )
    return TrendlineOutput(
        fit_result=fit_result,
        config=resolved_config,
        metadata={"stages_completed": ["extract", "fit"]},
    )


def fit_trendlines_to_boundary(
    df: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    config: TrendlinePipelineConfig | Mapping[str, Any] | None = None,
    extractor: str = "fractal",
    fitter: str = "pathfinding",
    extractor_kwargs: dict[str, Any] | None = None,
    fitter_kwargs: dict[str, Any] | None = None,
    trendline_config: TrendlinePipelineConfig | None = None,
    trendlines_config: TrendlinesConfig | None = None,
    execution_mode: TrendlineExecutionMode | str = TrendlineExecutionMode.RUNTIME,
) -> TrendlineOutput:
    """Run extract → fit → boundary adaptation and return a unified output.

    Use this when you need a ``BoundaryResult`` for consumer-facing
    adapters (e.g., confluence gating, alpha signal extraction).

    If *trendlines_config* is supplied, boundary params (atr_window,
    interaction_tolerance_atr) are resolved via the per-asset/TF config
    hierarchy, including derived params from the DataFrame.
    """

    fit_result, resolved_config = execute_trendline_pipeline(
        df,
        config=config,
        extractor=extractor,
        fitter=fitter,
        extractor_kwargs=extractor_kwargs,
        fitter_kwargs=fitter_kwargs,
        execution_mode=execution_mode,
    )

    # Resolve boundary params from asset/TF config if available
    boundary_kwargs: dict[str, Any] = {}
    asset_profile_dict = None
    if trendlines_config is not None:
        resolved = resolve_asset_config(
            trendlines_config, asset, timeframe, df, fit_result=fit_result
        )
        boundary_kwargs["interaction_tolerance_atr"] = resolved.boundary.interaction_tolerance_atr
        boundary_kwargs["atr_window"] = resolved.boundary.atr_window
        if resolved.profile:
            asset_profile_dict = resolved.profile.to_dict()

    boundary = build_boundary_result_from_trendline_result(
        df,
        asset=asset,
        timeframe=timeframe,
        trendline_result=fit_result,
        trendline_config=trendline_config or resolved_config,
        **boundary_kwargs,
    )

    return TrendlineOutput(
        fit_result=fit_result,
        boundary_result=boundary,
        config=resolved_config,
        metadata={
            "stages_completed": ["extract", "fit", "boundary"],
            "asset_profile": asset_profile_dict,
        },
    )


def fit_oscillator_to_boundary(
    df: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    oscillator_type: str,
    trendlines_config: TrendlinesConfig | None = None,
    execution_mode: TrendlineExecutionMode | str = TrendlineExecutionMode.RUNTIME,
) -> TrendlineOutput:
    """Run extract → fit → boundary for oscillator-space synthetic OHLCV.

    This facade bypasses ``resolve_asset_config()`` (which assumes price data)
    and instead uses the oscillator-specific config resolution path:
    oscillator_defaults → per-oscillator overrides → TF-derived params.

    The ``df`` must already be synthetic OHLCV (from ``prepare_oscillator_df()``).
    Signal extraction is NOT performed — oscillator signals are a future concern.
    """
    from libs.models.trendlines.config.resolve import resolve_oscillator_config

    root_config = trendlines_config or load_trendlines_config()
    resolved = resolve_oscillator_config(root_config, oscillator_type, timeframe, df)

    # Build pipeline config from resolved oscillator params
    osc_pipeline_config = TrendlinePipelineConfig(
        extractor=resolved.extractor,
        fitter=resolved.fitter,
        extractor_params=dict(resolved.extractor_params),
        fitter_params=dict(resolved.fitter_params),
        boundary_params={
            "interaction_tolerance_atr": resolved.interaction_tolerance_atr,
            "atr_window": resolved.atr_window,
        },
    )

    fit_result, runtime_config = execute_trendline_pipeline(
        df,
        config=osc_pipeline_config,
        execution_mode=execution_mode,
    )

    boundary = build_boundary_result_from_trendline_result(
        df,
        asset=asset,
        timeframe=timeframe,
        trendline_result=fit_result,
        trendline_config=runtime_config or osc_pipeline_config,
        interaction_tolerance_atr=resolved.interaction_tolerance_atr,
        atr_window=resolved.atr_window,
    )

    return TrendlineOutput(
        fit_result=fit_result,
        boundary_result=boundary,
        config=runtime_config or osc_pipeline_config,
        metadata={
            "stages_completed": ["extract", "fit", "boundary"],
            "oscillator_type": oscillator_type,
            "is_bounded": resolved.is_bounded,
            "value_range": resolved.value_range,
            "lookback_bars": resolved.lookback_bars,
        },
    )


def fit_and_signal(
    df: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    config: TrendlinePipelineConfig | Mapping[str, Any] | None = None,
    extractor: str = "fractal",
    fitter: str = "pathfinding",
    extractor_kwargs: dict[str, Any] | None = None,
    fitter_kwargs: dict[str, Any] | None = None,
    trendline_config: TrendlinePipelineConfig | None = None,
    trendlines_config: TrendlinesConfig | None = None,
    history: List[BoundaryResult] | None = None,
    context: Dict[str, Any] | None = None,
    execution_mode: TrendlineExecutionMode | str = TrendlineExecutionMode.RUNTIME,
) -> TrendlineOutput:
    """Run the full extract → fit → boundary → signal pipeline.

    This is the highest-level entry point available in the trendlines
    package.  It produces a combined ``TrendlineOutput`` with fit results,
    boundary adaptation, and native signal extraction in one call.

    Resolution flow:
    1. Extract → fit (produce TrendlineFitResult)
    2. Build AssetProfile from df + fit_result
    3. Resolve config (defaults → asset/TF overrides → derived from market data)
    4. Build BoundaryResult using resolved boundary params
    5. Run signal extractors using resolved signal params
    """

    # ── Stage 1+2: Extract → Fit ──
    fit_result, resolved_pipeline_config = execute_trendline_pipeline(
        df,
        config=config,
        extractor=extractor,
        fitter=fitter,
        extractor_kwargs=extractor_kwargs,
        fitter_kwargs=fitter_kwargs,
        execution_mode=execution_mode,
    )

    # ── Stage 3: Resolve config from asset profile ──
    root_config = trendlines_config or load_trendlines_config()
    resolved = resolve_asset_config(
        root_config, asset, timeframe, df, fit_result=fit_result
    )

    # ── Stage 4: Boundary adaptation with resolved params ──
    boundary = build_boundary_result_from_trendline_result(
        df,
        asset=asset,
        timeframe=timeframe,
        trendline_result=fit_result,
        trendline_config=trendline_config or resolved_pipeline_config,
        interaction_tolerance_atr=resolved.boundary.interaction_tolerance_atr,
        atr_window=resolved.boundary.atr_window,
    )

    # ── Stage 5: Signal extraction with resolved params ──
    if boundary is not None and boundary.is_valid:
        orchestrator = TrendlineSignalOrchestrator(resolved_config=resolved)
        signal_output = orchestrator.run(
            boundary,
            history=history,
            context=context,
        )
    else:
        signal_output = {
            "signals": [],
            "composite_direction": 0.0,
            "composite_confidence": 0.0,
            "signal_count": 0,
        }

    return TrendlineOutput(
        fit_result=fit_result,
        boundary_result=boundary,
        signal_output=signal_output,
        config=resolved_pipeline_config,
        metadata={
            "stages_completed": ["extract", "fit", "boundary", "signal"],
            "asset_profile": resolved.profile.to_dict() if resolved.profile else None,
            "resolved_asset": asset,
            "resolved_timeframe": timeframe,
        },
    )


def optimize_trendlines(
    df: pd.DataFrame,
    asset: str,
    timeframe: str,
    config: Optional["TrendlinesOptimizationConfig"] = None,
    n_trials: Optional[int] = None,
    timeout: Optional[int] = None,
    callbacks: Optional[List] = None,
    pipeline_factory: Optional[Any] = None,
) -> "TrendlinesOptimizationResult":
    """Run trendlines Bayesian optimization and return best run output."""
    from libs.models.trendlines.optimization import (
        TrendlinesOptimizationConfig,
        TrendlinesOptimizer,
    )

    opt_cfg = config if config is not None else TrendlinesOptimizationConfig()
    optimizer = TrendlinesOptimizer(config=opt_cfg, pipeline_factory=pipeline_factory)
    return optimizer.optimize(
        df=df,
        asset=asset,
        timeframe=timeframe,
        n_trials=n_trials,
        timeout=timeout,
        callbacks=callbacks,
    )


__all__ = [
    "TrendlineOutput",
    "fit_and_signal",
    "fit_trendlines",
    "fit_trendlines_to_boundary",
    "optimize_trendlines",
]
