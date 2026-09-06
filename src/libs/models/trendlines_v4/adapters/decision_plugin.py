"""Stable V1 Decision-adapter facade over the versioned implementation."""

from libs.models.trendlines_v4 import core as _core

from .decision import common as _common
from .decision import v1 as _v1

HISTORY_CAPACITY_BARS = _common.HISTORY_CAPACITY_BARS
TRENDLINES_STATE_SCHEMA_VERSION = _common.TRENDLINES_STATE_SCHEMA_VERSION
_decode_state = _common._decode_state
_encode_state = _common._encode_state
_finite_positive_float = _common._finite_positive_float
_line_value = _common._line_value
_to_trendline_bar = _common._to_trendline_bar
_validate_decision_context = _common._validate_decision_context
_validate_request_context = _common._validate_request_context
TRENDLINES_ARTIFACT_TYPE = _v1.TRENDLINES_ARTIFACT_TYPE
TRENDLINES_MODEL_SPEC = _v1.TRENDLINES_MODEL_SPEC
TRENDLINES_PLUGIN_NAME = _v1.TRENDLINES_PLUGIN_NAME
TRENDLINES_PLUGIN_VERSION = _v1.TRENDLINES_PLUGIN_VERSION
TrendlinesV4DecisionPlugin = _v1.TrendlinesV4DecisionPlugin
_side_value = _v1._side_value
_snapshot_value = _v1._snapshot_value
trendlines_initialization_requirement = _v1.trendlines_initialization_requirement
PIVOT_WINDOW = _core.PIVOT_WINDOW
SideGeometry = _core.SideGeometry
TrendlineBar = _core.TrendlineBar
TrendlineGeometry = _core.TrendlineGeometry
TrendlineSnapshot = _core.TrendlineSnapshot
analyze_trendlines = _core.analyze_trendlines

__all__ = [
    "TRENDLINES_ARTIFACT_TYPE",
    "TRENDLINES_MODEL_SPEC",
    "TRENDLINES_PLUGIN_NAME",
    "TRENDLINES_PLUGIN_VERSION",
    "TRENDLINES_STATE_SCHEMA_VERSION",
    "TrendlinesV4DecisionPlugin",
    "trendlines_initialization_requirement",
]
