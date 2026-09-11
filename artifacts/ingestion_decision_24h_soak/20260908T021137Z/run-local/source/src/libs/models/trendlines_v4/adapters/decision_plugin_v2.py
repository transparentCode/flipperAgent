"""Stable V2 Decision-adapter facade over the versioned implementation."""

from libs.models.trendlines_v4 import core as _core
from libs.models.trendlines_v4 import core_v2 as _core_v2

from .decision import common as _common
from .decision import v2 as _v2

HISTORY_CAPACITY_BARS = _common.HISTORY_CAPACITY_BARS
_decode_state = _common._decode_state
_encode_state = _common._encode_state
_finite_positive_float = _common._finite_positive_float
_line_value = _common._line_value
_to_trendline_bar = _common._to_trendline_bar
_validate_decision_context = _common._validate_decision_context
_validate_request_context = _common._validate_request_context
TRENDLINES_V2_ARTIFACT_TYPE = _v2.TRENDLINES_V2_ARTIFACT_TYPE
TRENDLINES_V2_MODEL_SPEC = _v2.TRENDLINES_V2_MODEL_SPEC
TRENDLINES_V2_PLUGIN_NAME = _v2.TRENDLINES_V2_PLUGIN_NAME
TRENDLINES_V2_PLUGIN_VERSION = _v2.TRENDLINES_V2_PLUGIN_VERSION
TRENDLINES_V2_STATE_SCHEMA_VERSION = _v2.TRENDLINES_V2_STATE_SCHEMA_VERSION
TrendlinesV4V2DecisionPlugin = _v2.TrendlinesV4V2DecisionPlugin
_side_value = _v2._side_value
_snapshot_value = _v2._snapshot_value
trendlines_v2_initialization_requirement = _v2.trendlines_v2_initialization_requirement
PIVOT_WINDOW = _core_v2.PIVOT_WINDOW
TrendlineGeometry = _core.TrendlineGeometry
GEOMETRY_SCHEMA_VERSION = _core_v2.GEOMETRY_SCHEMA_VERSION
SideGeometryV2 = _core_v2.SideGeometryV2
TrendlineSnapshotV2 = _core_v2.TrendlineSnapshotV2
analyze_trendlines_v2 = _core_v2.analyze_trendlines_v2

__all__ = [
    "TRENDLINES_V2_ARTIFACT_TYPE",
    "TRENDLINES_V2_MODEL_SPEC",
    "TRENDLINES_V2_PLUGIN_NAME",
    "TRENDLINES_V2_PLUGIN_VERSION",
    "TRENDLINES_V2_STATE_SCHEMA_VERSION",
    "TrendlinesV4V2DecisionPlugin",
    "trendlines_v2_initialization_requirement",
]
