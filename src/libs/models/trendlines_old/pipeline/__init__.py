"""Core pipeline orchestration for trendline extraction and fitting."""

from app.trendlines.pipeline.orchestrator import (
    execute_trendline_pipeline,
    run_trendline_pipeline,
    run_trendline_pipeline_from_config,
)

__all__ = [
    "execute_trendline_pipeline",
    "run_trendline_pipeline",
    "run_trendline_pipeline_from_config",
]
