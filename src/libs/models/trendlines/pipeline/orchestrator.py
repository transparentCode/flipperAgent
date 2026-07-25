"""Runtime orchestrator for the trendline extractor -> fitter pipeline."""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from libs.models.trendlines.config import TrendlinePipelineConfig
from libs.models.trendlines.contracts import TrendlineFitResult
from libs.models.trendlines.registry import build_extractor, build_fitter


def _resolve_extractor(extractor: object, extractor_kwargs: dict[str, Any]) -> tuple[object, str]:
    if isinstance(extractor, str):
        normalized = extractor.strip().lower()
        return build_extractor(normalized, **extractor_kwargs), normalized
    return extractor, extractor.__class__.__name__


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
) -> TrendlineFitResult:
    """Run the registered trendline pipeline using one extractor and one fitter."""

    resolved_extractor, extractor_name = _resolve_extractor(extractor, dict(extractor_kwargs or {}))
    resolved_fitter, fitter_name = _resolve_fitter(fitter, dict(fitter_kwargs or {}))

    pivots = resolved_extractor.extract(df)
    result = resolved_fitter.fit(df, pivots)

    metadata = dict(result.metadata)
    metadata["pipeline"] = {
        "extractor": extractor_name,
        "fitter": fitter_name,
        "n_high_pivots": pivots.n_highs,
        "n_low_pivots": pivots.n_lows,
    }
    result.metadata = metadata
    return result


def run_trendline_pipeline_from_config(
    df: pd.DataFrame,
    config: TrendlinePipelineConfig,
) -> TrendlineFitResult:
    """Run the trendline pipeline from a typed config contract."""

    return run_trendline_pipeline(
        df,
        extractor=config.extractor,
        fitter=config.fitter,
        extractor_kwargs=config.extractor_params,
        fitter_kwargs=config.fitter_params,
    )


def execute_trendline_pipeline(
    df: pd.DataFrame,
    *,
    config: TrendlinePipelineConfig | Mapping[str, Any] | None = None,
    extractor: object = "fractal",
    fitter: object = "pathfinding",
    extractor_kwargs: dict[str, Any] | None = None,
    fitter_kwargs: dict[str, Any] | None = None,
) -> tuple[TrendlineFitResult, TrendlinePipelineConfig | None]:
    """Run the trendline pipeline from either a config contract or direct components."""

    resolved_config: TrendlinePipelineConfig | None = None
    if config is not None:
        resolved_config = (
            config
            if isinstance(config, TrendlinePipelineConfig)
            else TrendlinePipelineConfig.from_dict(dict(config))
        )
        return run_trendline_pipeline_from_config(df, resolved_config), resolved_config

    return run_trendline_pipeline(
        df,
        extractor=extractor,
        fitter=fitter,
        extractor_kwargs=extractor_kwargs,
        fitter_kwargs=fitter_kwargs,
    ), None


__all__ = ["execute_trendline_pipeline", "run_trendline_pipeline", "run_trendline_pipeline_from_config"]
