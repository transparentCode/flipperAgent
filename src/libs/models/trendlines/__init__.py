"""Trendlines — plug-and-play module for trendline detection, fitting,
boundary adaptation, and native signal extraction.

Canonical library namespace: ``libs.models.trendlines``. Compatibility imports
remain available through ``app.trendlines``.
"""

# --- Contracts ---
from app.trendlines.contracts import PivotSet, Trendline, TrendlineFitResult
from app.trendlines.config import TrendlinePipelineConfig

# --- Registry ---
from app.trendlines.registry import build_extractor, build_fitter, list_extractors, list_fitters

# --- Pipeline orchestration ---
from app.trendlines.pipeline import (
    execute_trendline_pipeline,
    run_trendline_pipeline,
    run_trendline_pipeline_from_config,
)

# --- Facade (preferred for consumers) ---
from app.trendlines.api import (
    TrendlineOutput,
    fit_and_signal,
    fit_oscillator_to_boundary,
    fit_trendlines,
    fit_trendlines_to_boundary,
    optimize_trendlines,
)

__all__ = [
    # Contracts
    "PivotSet",
    "Trendline",
    "TrendlineFitResult",
    "TrendlinePipelineConfig",
    # Registry
    "build_extractor",
    "build_fitter",
    "list_extractors",
    "list_fitters",
    # Pipeline
    "execute_trendline_pipeline",
    "run_trendline_pipeline",
    "run_trendline_pipeline_from_config",
    # Facade
    "TrendlineOutput",
    "fit_and_signal",
    "fit_oscillator_to_boundary",
    "fit_trendlines",
    "fit_trendlines_to_boundary",
    "optimize_trendlines",
]
