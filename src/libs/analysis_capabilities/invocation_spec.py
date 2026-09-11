"""Metadata-only invocation contracts for the analysis capability catalog."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from .catalog import list_analysis_capabilities

InvocationStateMode = Literal["stateless", "caller_threaded"]
InvocationCutoffMode = Literal[
    "last_closed_bar",
    "explicit_request_cutoff",
    "native_result_observed_through",
]
InvocationIdentityMode = Literal["source_attested", "native_partial"]


def _nonempty(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _ordered_fields(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple of field names")
    normalized = tuple(
        _nonempty(item, field_name=f"{field_name}[{index}]")
        for index, item in enumerate(value)
    )
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must not contain duplicate names")
    return normalized


@dataclass(frozen=True, slots=True)
class AnalysisInvocationSpec:
    """Immutable metadata describing one capability invocation contract."""

    capability_id: str
    method_version: str
    request_contract: str
    result_contract: str
    request_fields: tuple[str, ...]
    parameter_fields: tuple[str, ...]
    state_mode: InvocationStateMode
    cutoff_mode: InvocationCutoffMode
    identity_mode: InvocationIdentityMode
    required_source_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "capability_id",
            "method_version",
            "request_contract",
            "result_contract",
        ):
            _nonempty(getattr(self, field_name), field_name=field_name)
        _ordered_fields(self.request_fields, field_name="request_fields")
        _ordered_fields(self.parameter_fields, field_name="parameter_fields")
        _ordered_fields(
            self.required_source_fields,
            field_name="required_source_fields",
        )
        if self.state_mode not in ("stateless", "caller_threaded"):
            raise ValueError("state_mode is not a supported invocation mode")
        if self.cutoff_mode not in (
            "last_closed_bar",
            "explicit_request_cutoff",
            "native_result_observed_through",
        ):
            raise ValueError("cutoff_mode is not a supported invocation mode")
        if self.identity_mode not in ("source_attested", "native_partial"):
            raise ValueError("identity_mode is not a supported invocation mode")


_SPECIFICATIONS = (
    AnalysisInvocationSpec(
        capability_id="model.trendlines",
        method_version="trendlines.geometry.v2",
        request_contract=(
            "libs.analysis_capabilities.execution.trendlines.TrendlinesExecutionRequest"
        ),
        result_contract="libs.models.trendlines.TrendlineSnapshot",
        request_fields=("history",),
        parameter_fields=("history_capacity_bars", "pivot_window"),
        state_mode="stateless",
        cutoff_mode="last_closed_bar",
        identity_mode="source_attested",
        required_source_fields=(),
    ),
    AnalysisInvocationSpec(
        capability_id="model.sr",
        method_version="sr.engine.step.schema.1.0",
        request_contract=("libs.analysis_capabilities.execution.sr.SRExecutionRequest"),
        result_contract="libs.analysis_capabilities.execution.sr.SRExecutionResult",
        request_fields=("previous_state", "closed_bar", "resolved_config"),
        parameter_fields=("resolved_config_hash",),
        state_mode="caller_threaded",
        cutoff_mode="last_closed_bar",
        identity_mode="native_partial",
        required_source_fields=(),
    ),
    AnalysisInvocationSpec(
        capability_id="model.regression",
        method_version="regression.context.v1",
        request_contract=(
            "libs.analysis_capabilities.execution.regression.RegressionExecutionRequest"
        ),
        result_contract="libs.regression.contracts.RegressionContextSnapshot",
        request_fields=("frame", "asset", "timeframe", "config", "channel_config"),
        parameter_fields=(
            "channel_config_hash",
            "source_config_hash",
            "window_size",
        ),
        state_mode="stateless",
        cutoff_mode="native_result_observed_through",
        identity_mode="native_partial",
        required_source_fields=(),
    ),
    AnalysisInvocationSpec(
        capability_id="ta.fibonacci_geometry",
        method_version="fibonacci.two_point_linear.v1",
        request_contract=(
            "libs.analysis_capabilities.ta.fibonacci_geometry.FibonacciGeometryRequest"
        ),
        result_contract=(
            "libs.analysis_capabilities.ta.fibonacci_geometry.FibonacciGeometrySnapshot"
        ),
        request_fields=(
            "start_anchor",
            "end_anchor",
            "market_as_of",
            "retracement_ratios",
            "extension_ratios",
        ),
        parameter_fields=("retracement_ratios", "extension_ratios"),
        state_mode="stateless",
        cutoff_mode="explicit_request_cutoff",
        identity_mode="source_attested",
        required_source_fields=(),
    ),
    AnalysisInvocationSpec(
        capability_id="ta.fibonacci_trend_extension_geometry",
        method_version="fibonacci.three_point_trend_extension.v1",
        request_contract=(
            "libs.analysis_capabilities.ta.fibonacci_trend_extension_geometry."
            "FibonacciTrendExtensionRequest"
        ),
        result_contract=(
            "libs.analysis_capabilities.ta.fibonacci_trend_extension_geometry."
            "FibonacciTrendExtensionSnapshot"
        ),
        request_fields=(
            "start_anchor",
            "impulse_end_anchor",
            "retracement_anchor",
            "market_as_of",
            "extension_ratios",
        ),
        parameter_fields=("extension_ratios",),
        state_mode="stateless",
        cutoff_mode="explicit_request_cutoff",
        identity_mode="source_attested",
        required_source_fields=(),
    ),
    AnalysisInvocationSpec(
        capability_id="ta.parallel_channel_geometry",
        method_version="parallel_channel.swing_three_anchor.v1",
        request_contract=(
            "libs.analysis_capabilities.ta.parallel_channel_geometry."
            "ParallelChannelGeometryRequest"
        ),
        result_contract=(
            "libs.analysis_capabilities.ta.parallel_channel_geometry."
            "ParallelChannelGeometrySnapshot"
        ),
        request_fields=(
            "bars",
            "start_anchor",
            "end_anchor",
            "offset_anchor",
            "market_as_of",
        ),
        parameter_fields=(),
        state_mode="stateless",
        cutoff_mode="explicit_request_cutoff",
        identity_mode="source_attested",
        required_source_fields=(),
    ),
    AnalysisInvocationSpec(
        capability_id="ta.swing_anchors",
        method_version="swing_anchors.strict_confirmed.v1",
        request_contract=(
            "libs.analysis_capabilities.ta.swing_anchors.SwingAnchorRequest"
        ),
        result_contract=(
            "libs.analysis_capabilities.ta.swing_anchors.SwingAnchorSnapshot"
        ),
        request_fields=("bars", "span"),
        parameter_fields=("span",),
        state_mode="stateless",
        cutoff_mode="last_closed_bar",
        identity_mode="source_attested",
        required_source_fields=(),
    ),
    AnalysisInvocationSpec(
        capability_id="ta.traditional_pivot_geometry",
        method_version="pivot.traditional.v1",
        request_contract=(
            "libs.analysis_capabilities.ta.traditional_pivot_geometry."
            "TraditionalPivotGeometryRequest"
        ),
        result_contract=(
            "libs.analysis_capabilities.ta.traditional_pivot_geometry."
            "TraditionalPivotGeometrySnapshot"
        ),
        request_fields=("reference", "market_as_of"),
        parameter_fields=(),
        state_mode="stateless",
        cutoff_mode="explicit_request_cutoff",
        identity_mode="source_attested",
        required_source_fields=(),
    ),
    AnalysisInvocationSpec(
        capability_id="ta.vwap_geometry",
        method_version="vwap.explicit_range_hlc3.v1",
        request_contract="libs.analysis_capabilities.ta.vwap_geometry.VWAPGeometryRequest",
        result_contract=(
            "libs.analysis_capabilities.ta.vwap_geometry.VWAPGeometrySnapshot"
        ),
        request_fields=("bars", "market_as_of"),
        parameter_fields=(),
        state_mode="stateless",
        cutoff_mode="explicit_request_cutoff",
        identity_mode="source_attested",
        required_source_fields=("volume_unit",),
    ),
    AnalysisInvocationSpec(
        capability_id="ta.anchored_vwap_path",
        method_version="vwap.anchored_path_hlc3.v1",
        request_contract=(
            "libs.analysis_capabilities.ta.anchored_vwap_path.AnchoredVWAPPathRequest"
        ),
        result_contract=(
            "libs.analysis_capabilities.ta.anchored_vwap_path.AnchoredVWAPPathSnapshot"
        ),
        request_fields=("bars", "market_as_of"),
        parameter_fields=(),
        state_mode="stateless",
        cutoff_mode="explicit_request_cutoff",
        identity_mode="source_attested",
        required_source_fields=("volume_unit",),
    ),
    AnalysisInvocationSpec(
        capability_id="ta.gann_box_geometry",
        method_version="gann.box.bar_price_grid.v1",
        request_contract=(
            "libs.analysis_capabilities.ta.gann_box_geometry.GannBoxGeometryRequest"
        ),
        result_contract=(
            "libs.analysis_capabilities.ta.gann_box_geometry.GannBoxGeometrySnapshot"
        ),
        request_fields=(
            "bars",
            "start",
            "end",
            "price_levels",
            "time_levels",
            "market_as_of",
        ),
        parameter_fields=("price_levels", "time_levels"),
        state_mode="stateless",
        cutoff_mode="explicit_request_cutoff",
        identity_mode="source_attested",
        required_source_fields=(),
    ),
    AnalysisInvocationSpec(
        capability_id="ta.gann_fan_geometry",
        method_version="gann.fan.bar_scale.v1",
        request_contract=(
            "libs.analysis_capabilities.ta.gann_fan_geometry.GannFanGeometryRequest"
        ),
        result_contract=(
            "libs.analysis_capabilities.ta.gann_fan_geometry.GannFanGeometrySnapshot"
        ),
        request_fields=(
            "bars",
            "anchor",
            "price_per_bar",
            "angle_ratios",
            "market_as_of",
        ),
        parameter_fields=("angle_ratios", "price_per_bar"),
        state_mode="stateless",
        cutoff_mode="explicit_request_cutoff",
        identity_mode="source_attested",
        required_source_fields=(),
    ),
    AnalysisInvocationSpec(
        capability_id="ta.volume_profile_geometry",
        method_version="volume_profile.explicit_range_uniform_overlap.v1",
        request_contract=(
            "libs.analysis_capabilities.ta.volume_profile_geometry."
            "VolumeProfileGeometryRequest"
        ),
        result_contract=(
            "libs.analysis_capabilities.ta.volume_profile_geometry."
            "VolumeProfileGeometrySnapshot"
        ),
        request_fields=(
            "bars",
            "market_as_of",
            "row_count",
            "value_area_fraction",
        ),
        parameter_fields=("row_count", "value_area_fraction"),
        state_mode="stateless",
        cutoff_mode="explicit_request_cutoff",
        identity_mode="source_attested",
        required_source_fields=("volume_unit",),
    ),
    AnalysisInvocationSpec(
        capability_id="ta.abcd_pattern_geometry",
        method_version="pattern.abcd.explicit_four_anchor.v1",
        request_contract=(
            "libs.analysis_capabilities.ta.abcd_pattern_geometry."
            "ABCDPatternGeometryRequest"
        ),
        result_contract=(
            "libs.analysis_capabilities.ta.abcd_pattern_geometry."
            "ABCDPatternGeometrySnapshot"
        ),
        request_fields=("bars", "a", "b", "c", "d", "market_as_of"),
        parameter_fields=(),
        state_mode="stateless",
        cutoff_mode="explicit_request_cutoff",
        identity_mode="source_attested",
        required_source_fields=(),
    ),
    AnalysisInvocationSpec(
        capability_id="ta.xabcd_pattern_geometry",
        method_version="pattern.xabcd.explicit_five_anchor.v1",
        request_contract=(
            "libs.analysis_capabilities.ta.xabcd_pattern_geometry."
            "XABCDPatternGeometryRequest"
        ),
        result_contract=(
            "libs.analysis_capabilities.ta.xabcd_pattern_geometry."
            "XABCDPatternGeometrySnapshot"
        ),
        request_fields=("bars", "x", "a", "b", "c", "d", "market_as_of"),
        parameter_fields=(),
        state_mode="stateless",
        cutoff_mode="explicit_request_cutoff",
        identity_mode="source_attested",
        required_source_fields=(),
    ),
    AnalysisInvocationSpec(
        capability_id="ta.head_shoulders_pattern_geometry",
        method_version="pattern.head_shoulders.explicit_five_anchor_neckline.v1",
        request_contract=(
            "libs.analysis_capabilities.ta.head_shoulders_pattern_geometry."
            "HeadShouldersPatternGeometryRequest"
        ),
        result_contract=(
            "libs.analysis_capabilities.ta.head_shoulders_pattern_geometry."
            "HeadShouldersPatternGeometrySnapshot"
        ),
        request_fields=(
            "bars",
            "left_shoulder",
            "neck_left",
            "head",
            "neck_right",
            "right_shoulder",
            "market_as_of",
        ),
        parameter_fields=(),
        state_mode="stateless",
        cutoff_mode="explicit_request_cutoff",
        identity_mode="source_attested",
        required_source_fields=(),
    ),
    AnalysisInvocationSpec(
        capability_id="ta.triangle_pattern_geometry",
        method_version="pattern.triangle.explicit_four_anchor_boundaries.v1",
        request_contract=(
            "libs.analysis_capabilities.ta.triangle_pattern_geometry."
            "TrianglePatternGeometryRequest"
        ),
        result_contract=(
            "libs.analysis_capabilities.ta.triangle_pattern_geometry."
            "TrianglePatternGeometrySnapshot"
        ),
        request_fields=("bars", "a", "b", "c", "d", "market_as_of"),
        parameter_fields=(),
        state_mode="stateless",
        cutoff_mode="explicit_request_cutoff",
        identity_mode="source_attested",
        required_source_fields=(),
    ),
    AnalysisInvocationSpec(
        capability_id="ta.cypher_pattern_geometry",
        method_version="pattern.cypher.explicit_five_anchor_measurements.v1",
        request_contract=(
            "libs.analysis_capabilities.ta.cypher_pattern_geometry."
            "CypherPatternGeometryRequest"
        ),
        result_contract=(
            "libs.analysis_capabilities.ta.cypher_pattern_geometry."
            "CypherPatternGeometrySnapshot"
        ),
        request_fields=("bars", "x", "a", "b", "c", "d", "market_as_of"),
        parameter_fields=(),
        state_mode="stateless",
        cutoff_mode="explicit_request_cutoff",
        identity_mode="source_attested",
        required_source_fields=(),
    ),
    AnalysisInvocationSpec(
        capability_id="ta.three_drives_pattern_geometry",
        method_version="pattern.three_drives.explicit_six_anchor.v1",
        request_contract=(
            "libs.analysis_capabilities.ta.three_drives_pattern_geometry."
            "ThreeDrivesPatternGeometryRequest"
        ),
        result_contract=(
            "libs.analysis_capabilities.ta.three_drives_pattern_geometry."
            "ThreeDrivesPatternGeometrySnapshot"
        ),
        request_fields=(
            "bars",
            "start",
            "drive1",
            "retrace_a",
            "drive2",
            "retrace_c",
            "drive3",
            "market_as_of",
        ),
        parameter_fields=(),
        state_mode="stateless",
        cutoff_mode="explicit_request_cutoff",
        identity_mode="source_attested",
        required_source_fields=(),
    ),
    AnalysisInvocationSpec(
        capability_id="ta.elliott_impulse_wave_geometry",
        method_version="pattern.elliott_impulse.explicit_six_anchor.v1",
        request_contract=(
            "libs.analysis_capabilities.ta.elliott_impulse_wave_geometry."
            "ElliottImpulseWaveGeometryRequest"
        ),
        result_contract=(
            "libs.analysis_capabilities.ta.elliott_impulse_wave_geometry."
            "ElliottImpulseWaveGeometrySnapshot"
        ),
        request_fields=(
            "bars",
            "start",
            "wave1",
            "wave2",
            "wave3",
            "wave4",
            "wave5",
            "market_as_of",
        ),
        parameter_fields=(),
        state_mode="stateless",
        cutoff_mode="explicit_request_cutoff",
        identity_mode="source_attested",
        required_source_fields=(),
    ),
    AnalysisInvocationSpec(
        capability_id="ta.elliott_correction_wave_geometry",
        method_version="pattern.elliott_correction.explicit_four_anchor.v1",
        request_contract=(
            "libs.analysis_capabilities.ta.elliott_correction_wave_geometry."
            "ElliottCorrectionWaveGeometryRequest"
        ),
        result_contract=(
            "libs.analysis_capabilities.ta.elliott_correction_wave_geometry."
            "ElliottCorrectionWaveGeometrySnapshot"
        ),
        request_fields=(
            "bars",
            "start",
            "wave_a",
            "wave_b",
            "wave_c",
            "market_as_of",
        ),
        parameter_fields=(),
        state_mode="stateless",
        cutoff_mode="explicit_request_cutoff",
        identity_mode="source_attested",
        required_source_fields=(),
    ),
)

_SPEC_IDS = tuple(spec.capability_id for spec in _SPECIFICATIONS)
if len(set(_SPEC_IDS)) != len(_SPEC_IDS):
    raise RuntimeError("invocation specs must not contain duplicate capability IDs")
_SPECS_BY_ID = MappingProxyType({spec.capability_id: spec for spec in _SPECIFICATIONS})
_CATALOG_IDS = tuple(entry.capability_id for entry in list_analysis_capabilities())
if tuple(sorted(_SPECS_BY_ID)) != _CATALOG_IDS:
    raise RuntimeError("invocation specs must match the capability catalog exactly")


def get_analysis_invocation_spec(capability_id: str) -> AnalysisInvocationSpec:
    """Return one immutable invocation specification by exact capability ID."""

    if not isinstance(capability_id, str):
        raise TypeError("capability_id must be a string")
    return _SPECS_BY_ID[capability_id]


def list_analysis_invocation_specs() -> tuple[AnalysisInvocationSpec, ...]:
    """Return all invocation specifications in deterministic ID order."""

    return tuple(_SPECS_BY_ID[capability_id] for capability_id in _CATALOG_IDS)


__all__ = (
    "AnalysisInvocationSpec",
    "get_analysis_invocation_spec",
    "list_analysis_invocation_specs",
)
