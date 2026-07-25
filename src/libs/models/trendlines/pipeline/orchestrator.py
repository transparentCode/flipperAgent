"""Runtime orchestrator for the trendline extractor -> fitter pipeline."""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from libs.models.trendlines.config import TrendlinePipelineConfig
from libs.models.trendlines.contracts import TrendlineFitResult
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
) -> TrendlineFitResult:
    """Run the registered trendline pipeline using one extractor and one fitter."""

    mode = normalize_execution_mode(execution_mode)
    resolved_extractor, extractor_name, capabilities = _resolve_extractor(
        extractor,
        dict(extractor_kwargs or {}),
        mode,
    )
    resolved_fitter, fitter_name = _resolve_fitter(fitter, dict(fitter_kwargs or {}))

    pivots = resolved_extractor.extract(df)
    result = resolved_fitter.fit(df, pivots)

    metadata = dict(result.metadata)
    metadata["pipeline"] = {
        "extractor": extractor_name,
        "fitter": fitter_name,
        "n_high_pivots": pivots.n_highs,
        "n_low_pivots": pivots.n_lows,
        "execution_mode": mode.value,
        **capabilities_to_metadata(capabilities),
    }
    result.metadata = metadata
    return result


def run_trendline_pipeline_from_config(
    df: pd.DataFrame,
    config: TrendlinePipelineConfig,
    *,
    execution_mode: TrendlineExecutionMode | str = TrendlineExecutionMode.RUNTIME,
) -> TrendlineFitResult:
    """Run the trendline pipeline from a typed config contract."""

    return run_trendline_pipeline(
        df,
        extractor=config.extractor,
        fitter=config.fitter,
        extractor_kwargs=config.extractor_params,
        fitter_kwargs=config.fitter_params,
        execution_mode=execution_mode,
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
    ), None


__all__ = ["execute_trendline_pipeline", "run_trendline_pipeline", "run_trendline_pipeline_from_config"]
