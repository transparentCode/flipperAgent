"""Runtime orchestrator for the trendline extractor -> fitter pipeline."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping

import pandas as pd

from libs.models.trendlines.config import TrendlinePipelineConfig
from libs.models.trendlines.contracts import TrendlineFitResult
from libs.models.trendlines.contracts.identity import (
    TrendlineSourceRef,
    build_checkpoint,
    build_config_id,
    build_snapshot_identity,
    resolve_component_identity_payload,
    resolve_source_ref,
)
from libs.models.trendlines.pivots.base import PivotExtractor
from libs.models.trendlines.pivots.capabilities import (
    ExtractorCapabilities,
    TrendlineExecutionMode,
    capabilities_to_metadata,
    normalize_execution_mode,
    validate_extractor_capabilities,
)
from libs.models.trendlines.registry import (
    build_extractor,
    build_fitter,
    canonical_extractor_name,
    get_registered_extractor_capabilities,
)


def _resolve_extractor(
    extractor: object,
    extractor_kwargs: dict[str, Any],
    execution_mode: TrendlineExecutionMode,
) -> tuple[PivotExtractor, str, ExtractorCapabilities]:
    if isinstance(extractor, str):
        canonical = canonical_extractor_name(extractor)
        resolved = build_extractor(
            extractor,
            execution_mode=execution_mode,
            **extractor_kwargs,
        )
        return resolved, canonical, get_registered_extractor_capabilities(canonical)
    capabilities = validate_extractor_capabilities(extractor, execution_mode)
    return extractor, extractor.__class__.__name__, capabilities


def _resolve_fitter(fitter: object, fitter_kwargs: dict[str, Any]) -> tuple[object, str]:
    if isinstance(fitter, str):
        normalized = fitter.strip().lower()
        return build_fitter(normalized, **fitter_kwargs), normalized
    return fitter, fitter.__class__.__name__


def run_trendline_pipeline(
    df: pd.DataFrame,
    *,
    extractor: object = "fractal",
    fitter: object = "pathfinding",
    extractor_kwargs: dict[str, Any] | None = None,
    fitter_kwargs: dict[str, Any] | None = None,
    execution_mode: TrendlineExecutionMode | str = TrendlineExecutionMode.RUNTIME,
    asset: str | None = None,
    timeframe: str | None = None,
    as_of: Any | None = None,
    source_ref: TrendlineSourceRef | None = None,
    pipeline_config: TrendlinePipelineConfig | None = None,
) -> TrendlineFitResult:
    """Run the registered trendline pipeline using one extractor and one fitter."""

    mode = normalize_execution_mode(execution_mode)
    if (asset is None) != (timeframe is None):
        raise ValueError("asset and timeframe must be supplied together")
    resolved_source = resolve_source_ref(df, as_of=as_of, source_ref=source_ref)
    resolved_extractor, extractor_name, capabilities = _resolve_extractor(
        extractor,
        dict(extractor_kwargs or {}),
        mode,
    )
    resolved_fitter, fitter_name = _resolve_fitter(fitter, dict(fitter_kwargs or {}))
    extractor_identity = resolve_component_identity_payload(
        resolved_extractor,
        role="extractor",
        canonical_name=extractor_name if isinstance(extractor, str) else None,
    )
    fitter_identity = resolve_component_identity_payload(
        resolved_fitter,
        role="fitter",
        canonical_name=fitter_name if isinstance(fitter, str) else None,
    )

    config_id = build_config_id(
        config_payload=asdict(pipeline_config) if pipeline_config is not None else None,
        extractor_name=extractor_name,
        extractor_params=dict(extractor_kwargs or {}),
        extractor_identity=extractor_identity,
        fitter_name=fitter_name,
        fitter_params=dict(fitter_kwargs or {}),
        fitter_identity=fitter_identity,
        execution_mode=mode,
        extractor_capabilities=capabilities,
    )
    checkpoint = build_checkpoint(
        source=resolved_source,
        config_id=config_id,
        execution_mode=mode,
        extractor_finality=capabilities.finality,
    )

    pivots = resolved_extractor.extract(df)
    result = resolved_fitter.fit(df, pivots)

    snapshot_identity = build_snapshot_identity(
        checkpoint=checkpoint,
        stage="fit",
        content_payload=result.to_dict(include_identity=False),
        asset=asset,
        timeframe=timeframe,
    )
    result.checkpoint = checkpoint
    result.snapshot_identity = snapshot_identity

    metadata = dict(result.metadata)
    metadata["pipeline"] = {
        "extractor": extractor_name,
        "fitter": fitter_name,
        "extractor_identity": extractor_identity,
        "fitter_identity": fitter_identity,
        "n_high_pivots": pivots.n_highs,
        "n_low_pivots": pivots.n_lows,
        "execution_mode": mode.value,
        **capabilities_to_metadata(capabilities),
        "source_ref": resolved_source.to_dict(),
        "config_id": config_id,
        "checkpoint_id": checkpoint.checkpoint_id,
        "snapshot_id": snapshot_identity.snapshot_id,
        "revision_id": snapshot_identity.revision_id,
    }
    result.metadata = metadata
    return result


def run_trendline_pipeline_from_config(
    df: pd.DataFrame,
    config: TrendlinePipelineConfig,
    *,
    execution_mode: TrendlineExecutionMode | str = TrendlineExecutionMode.RUNTIME,
    asset: str | None = None,
    timeframe: str | None = None,
    as_of: Any | None = None,
    source_ref: TrendlineSourceRef | None = None,
) -> TrendlineFitResult:
    """Run the trendline pipeline from a typed config contract."""

    return run_trendline_pipeline(
        df,
        extractor=config.extractor,
        fitter=config.fitter,
        extractor_kwargs=config.extractor_params,
        fitter_kwargs=config.fitter_params,
        execution_mode=execution_mode,
        asset=asset,
        timeframe=timeframe,
        as_of=as_of,
        source_ref=source_ref,
        pipeline_config=config,
    )


def execute_trendline_pipeline(
    df: pd.DataFrame,
    *,
    config: TrendlinePipelineConfig | Mapping[str, Any] | None = None,
    extractor: object = "fractal",
    fitter: object = "pathfinding",
    extractor_kwargs: dict[str, Any] | None = None,
    fitter_kwargs: dict[str, Any] | None = None,
    execution_mode: TrendlineExecutionMode | str = TrendlineExecutionMode.RUNTIME,
    asset: str | None = None,
    timeframe: str | None = None,
    as_of: Any | None = None,
    source_ref: TrendlineSourceRef | None = None,
) -> tuple[TrendlineFitResult, TrendlinePipelineConfig | None]:
    """Run the trendline pipeline from either a config contract or direct components."""

    resolved_config: TrendlinePipelineConfig | None = None
    if config is not None:
        resolved_config = (
            config
            if isinstance(config, TrendlinePipelineConfig)
            else TrendlinePipelineConfig.from_dict(dict(config))
        )
        return (
            run_trendline_pipeline_from_config(
                df,
                resolved_config,
                execution_mode=execution_mode,
                asset=asset,
                timeframe=timeframe,
                as_of=as_of,
                source_ref=source_ref,
            ),
            resolved_config,
        )

    return run_trendline_pipeline(
        df,
        extractor=extractor,
        fitter=fitter,
        extractor_kwargs=extractor_kwargs,
        fitter_kwargs=fitter_kwargs,
        execution_mode=execution_mode,
        asset=asset,
        timeframe=timeframe,
        as_of=as_of,
        source_ref=source_ref,
    ), None


__all__ = ["execute_trendline_pipeline", "run_trendline_pipeline", "run_trendline_pipeline_from_config"]
