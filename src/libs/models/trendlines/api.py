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
from libs.models.trendlines.contracts.identity import (
    TrendlineCheckpoint,
    TrendlineSnapshotIdentity,
    TrendlineSnapshotStage,
    TrendlineSourceRef,
    build_snapshot_identity,
)
from libs.models.trendlines.pipeline import (
    execute_trendline_pipeline,
)
from libs.models.trendlines.pivots.capabilities import TrendlineExecutionMode
from libs.models.trendlines.signals.context import (
    TrendlineSignalInputs,
    validate_signal_inputs,
)
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
    checkpoint: TrendlineCheckpoint | None = None
    snapshot_identity: TrendlineSnapshotIdentity | None = None

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
            "checkpoint": self.checkpoint.to_dict() if self.checkpoint else None,
            "snapshot_identity": (
                self.snapshot_identity.to_dict() if self.snapshot_identity else None
            ),
        }


def _validate_scope(asset: str | None, timeframe: str | None) -> None:
    if (asset is None) != (timeframe is None):
        raise ValueError("asset and timeframe must be supplied together")


def _identity_metadata(
    checkpoint: TrendlineCheckpoint,
    snapshot_identity: TrendlineSnapshotIdentity,
) -> dict[str, Any]:
    return {
        "source_ref": checkpoint.source.to_dict(),
        "checkpoint_id": checkpoint.checkpoint_id,
        "snapshot_id": snapshot_identity.snapshot_id,
        "revision_id": snapshot_identity.revision_id,
        "snapshot_stage": snapshot_identity.stage.value,
        "snapshot_finality": snapshot_identity.finality.value,
    }


def fit_trendlines(
    df: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    config: TrendlinePipelineConfig | Mapping[str, Any] | None = None,
    extractor: str = "fractal",
    fitter: str = "pathfinding",
    extractor_kwargs: dict[str, Any] | None = None,
    fitter_kwargs: dict[str, Any] | None = None,
    execution_mode: TrendlineExecutionMode | str = TrendlineExecutionMode.RUNTIME,
    as_of: Any | None = None,
    source_ref: TrendlineSourceRef | None = None,
) -> TrendlineOutput:
    """Run the core extract → fit pipeline and return a unified output.

    This is the simplest entry point when you only need the raw
    trendline fit result without boundary adaptation or signals.
    """

    _validate_scope(asset, timeframe)
    fit_result, resolved_config = execute_trendline_pipeline(
        df,
        config=config,
        extractor=extractor,
        fitter=fitter,
        extractor_kwargs=extractor_kwargs,
        fitter_kwargs=fitter_kwargs,
        execution_mode=execution_mode,
        asset=asset,
        timeframe=timeframe,
        as_of=as_of,
        source_ref=source_ref,
    )
    if fit_result.checkpoint is None or fit_result.snapshot_identity is None:
        raise RuntimeError("trendline pipeline did not produce fit snapshot identity")
    return TrendlineOutput(
        fit_result=fit_result,
        config=resolved_config,
        metadata={
            "stages_completed": ["extract", "fit"],
            **_identity_metadata(fit_result.checkpoint, fit_result.snapshot_identity),
        },
        checkpoint=fit_result.checkpoint,
        snapshot_identity=fit_result.snapshot_identity,
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
    as_of: Any | None = None,
    source_ref: TrendlineSourceRef | None = None,
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
        asset=asset,
        timeframe=timeframe,
        as_of=as_of,
        source_ref=source_ref,
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

    if fit_result.checkpoint is None:
        raise RuntimeError("trendline pipeline did not produce checkpoint identity")
    boundary_identity = build_snapshot_identity(
        checkpoint=fit_result.checkpoint,
        stage=TrendlineSnapshotStage.BOUNDARY,
        content_payload={
            "boundary": boundary.to_dict(include_identity=False),
            "boundary_config": {
                "adapter": boundary.metadata.get("trendlines", {}).get("adapter", {}),
                "pipeline_config": trendline_config or resolved_config,
                "resolved_asset_profile": asset_profile_dict,
            },
        },
        asset=asset,
        timeframe=timeframe,
    )
    boundary.snapshot_identity = boundary_identity
    boundary.__post_init__()

    return TrendlineOutput(
        fit_result=fit_result,
        boundary_result=boundary,
        config=resolved_config,
        metadata={
            "stages_completed": ["extract", "fit", "boundary"],
            "asset_profile": asset_profile_dict,
            **_identity_metadata(fit_result.checkpoint, boundary_identity),
        },
        checkpoint=fit_result.checkpoint,
        snapshot_identity=boundary_identity,
    )


def fit_oscillator_to_boundary(
    df: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    oscillator_type: str,
    trendlines_config: TrendlinesConfig | None = None,
    execution_mode: TrendlineExecutionMode | str = TrendlineExecutionMode.RUNTIME,
    as_of: Any | None = None,
    source_ref: TrendlineSourceRef | None = None,
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
        asset=asset,
        timeframe=timeframe,
        as_of=as_of,
        source_ref=source_ref,
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

    if fit_result.checkpoint is None:
        raise RuntimeError("trendline pipeline did not produce checkpoint identity")
    boundary_identity = build_snapshot_identity(
        checkpoint=fit_result.checkpoint,
        stage=TrendlineSnapshotStage.BOUNDARY,
        content_payload={
            "boundary": boundary.to_dict(include_identity=False),
            "oscillator_config": resolved,
        },
        asset=asset,
        timeframe=timeframe,
    )
    boundary.snapshot_identity = boundary_identity
    boundary.__post_init__()

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
            **_identity_metadata(fit_result.checkpoint, boundary_identity),
        },
        checkpoint=fit_result.checkpoint,
        snapshot_identity=boundary_identity,
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
    signal_inputs: TrendlineSignalInputs,
    execution_mode: TrendlineExecutionMode | str = TrendlineExecutionMode.RUNTIME,
    as_of: Any | None = None,
    source_ref: TrendlineSourceRef | None = None,
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
        asset=asset,
        timeframe=timeframe,
        as_of=as_of,
        source_ref=source_ref,
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

    if fit_result.checkpoint is None:
        raise RuntimeError("trendline pipeline did not produce checkpoint identity")
    boundary_identity = build_snapshot_identity(
        checkpoint=fit_result.checkpoint,
        stage=TrendlineSnapshotStage.BOUNDARY,
        content_payload={
            "boundary": boundary.to_dict(include_identity=False),
            "resolved_config": resolved,
        },
        asset=asset,
        timeframe=timeframe,
    )
    boundary.snapshot_identity = boundary_identity
    boundary.__post_init__()

    # ── Stage 5: Signal extraction with resolved params ──
    validation = validate_signal_inputs(df, boundary, signal_inputs)
    if boundary is not None and boundary.is_valid:
        orchestrator = TrendlineSignalOrchestrator(resolved_config=resolved)
        signal_output = orchestrator.run(
            boundary,
            signal_inputs=signal_inputs,
            frame=df,
            validation=validation,
        )
    else:
        signal_output = {
            "signals": [],
            "composite_direction": 0.0,
            "composite_confidence": 0.0,
            "signal_count": 0,
            **validation.metadata(),
        }

    signal_identity = build_snapshot_identity(
        checkpoint=fit_result.checkpoint,
        stage=TrendlineSnapshotStage.SIGNAL,
        content_payload={
            "boundary": boundary.to_dict(include_identity=False),
            "signal_output": signal_output,
            "resolved_config": resolved,
        },
        asset=asset,
        timeframe=timeframe,
    )

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
            **_identity_metadata(fit_result.checkpoint, signal_identity),
            **validation.metadata(),
        },
        checkpoint=fit_result.checkpoint,
        snapshot_identity=signal_identity,
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
