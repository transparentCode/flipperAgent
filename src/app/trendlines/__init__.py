"""Compatibility package for migrated trendlines imports."""

from __future__ import annotations

from pathlib import Path

_TRENDLINES_ROOT = Path(__file__).resolve().parents[2] / "libs" / "trendlines"
__path__ = [str(_TRENDLINES_ROOT), *[p for p in globals().get("__path__", [])]]

from app.trendlines.contracts import PivotSet, Trendline, TrendlineFitResult
from app.trendlines.config import TrendlinePipelineConfig
from app.trendlines.registry import build_extractor, build_fitter, list_extractors, list_fitters
from app.trendlines.pipeline import (
    execute_trendline_pipeline,
    run_trendline_pipeline,
    run_trendline_pipeline_from_config,
)
from app.trendlines.api import (
    TrendlineOutput,
    fit_and_signal,
    fit_oscillator_to_boundary,
    fit_trendlines,
    fit_trendlines_to_boundary,
    optimize_trendlines,
)

__all__ = [
    "PivotSet",
    "Trendline",
    "TrendlineFitResult",
    "TrendlinePipelineConfig",
    "build_extractor",
    "build_fitter",
    "list_extractors",
    "list_fitters",
    "execute_trendline_pipeline",
    "run_trendline_pipeline",
    "run_trendline_pipeline_from_config",
    "TrendlineOutput",
    "fit_and_signal",
    "fit_oscillator_to_boundary",
    "fit_trendlines",
    "fit_trendlines_to_boundary",
    "optimize_trendlines",
]
