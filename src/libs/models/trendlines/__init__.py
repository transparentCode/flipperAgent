"""Trendlines — plug-and-play module for trendline detection, fitting,
boundary adaptation, and native signal extraction.

``libs.models.trendlines`` is the sole canonical model namespace.
"""

# --- Contracts ---
from libs.models.trendlines.contracts import PivotSet, Trendline, TrendlineFitResult
from libs.models.trendlines.config import TrendlinePipelineConfig
from libs.models.trendlines.pivots.capabilities import (
    ExtractorCapabilities,
    ExtractorExecutionPolicyError,
    PivotFinality,
    TrendlineExecutionMode,
)

# --- Registry ---
from libs.models.trendlines.registry import (
    build_extractor,
    build_fitter,
    list_extractors,
    list_extractors_for_mode,
    list_fitters,
)

# --- Pipeline orchestration ---
from libs.models.trendlines.pipeline import (
    execute_trendline_pipeline,
    run_trendline_pipeline,
    run_trendline_pipeline_from_config,
)

# --- Facade (preferred for consumers) ---
from libs.models.trendlines.api import (
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
    "ExtractorCapabilities",
    "ExtractorExecutionPolicyError",
    "PivotFinality",
    "TrendlineExecutionMode",
    # Registry
    "build_extractor",
    "build_fitter",
    "list_extractors",
    "list_extractors_for_mode",
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
