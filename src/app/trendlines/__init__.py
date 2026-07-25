"""Temporary compatibility namespace; scheduled for C3-R1b deletion."""

from __future__ import annotations

from pathlib import Path

_TRENDLINES_ROOT = Path(__file__).resolve().parents[2] / "libs" / "models" / "trendlines"
__path__ = [str(_TRENDLINES_ROOT), *[p for p in globals().get("__path__", [])]]

from libs.models.trendlines.contracts import PivotSet, Trendline, TrendlineFitResult  # noqa: E402
from libs.models.trendlines.config import TrendlinePipelineConfig  # noqa: E402
from libs.models.trendlines.registry import build_extractor, build_fitter, list_extractors, list_fitters  # noqa: E402
from libs.models.trendlines.pipeline import (  # noqa: E402
    execute_trendline_pipeline,
    run_trendline_pipeline,
    run_trendline_pipeline_from_config,
)
from libs.models.trendlines.api import (  # noqa: E402
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
