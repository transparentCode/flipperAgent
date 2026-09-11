"""Explicit Decision adapter for the Trendlines V4 analytical core."""

from .decision_plugin import (
    TRENDLINES_ARTIFACT_TYPE,
    TRENDLINES_MODEL_SPEC,
    TRENDLINES_PLUGIN_NAME,
    TRENDLINES_PLUGIN_VERSION,
    TRENDLINES_STATE_SCHEMA_VERSION,
    TrendlinesV4DecisionPlugin,
    trendlines_initialization_requirement,
)

__all__ = [
    "TRENDLINES_ARTIFACT_TYPE",
    "TRENDLINES_MODEL_SPEC",
    "TRENDLINES_PLUGIN_NAME",
    "TRENDLINES_PLUGIN_VERSION",
    "TRENDLINES_STATE_SCHEMA_VERSION",
    "TrendlinesV4DecisionPlugin",
    "trendlines_initialization_requirement",
]
