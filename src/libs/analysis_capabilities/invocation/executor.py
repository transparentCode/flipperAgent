"""Explicit checked execution over the existing capability dispatcher."""

import math

from ..catalog import get_analysis_capability
from ..execution import execute_analysis_capability
from ..invocation_spec import AnalysisInvocationSpec, get_analysis_invocation_spec
from .contracts import (
    AnalysisBindingError,
    AnalysisInvocationContext,
    AnalysisInvocationResult,
    _parameter_fingerprint,
)


def _float_identity(value: object, *, field_name: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized.hex()


def _ratio_identity(value: object, *, field_name: str) -> str:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    encoded = tuple(
        _float_identity(item, field_name=f"{field_name}[{index}]")
        for index, item in enumerate(value)
    )
    return ",".join(encoded) or "<empty>"


def _binding(condition: bool, message: str) -> None:
    if not condition:
        raise AnalysisBindingError(message)


def _source_fields(
    spec: AnalysisInvocationSpec,
    context: AnalysisInvocationContext,
) -> None:
    for field_name in spec.required_source_fields:
        value = getattr(context.source, field_name)
        _binding(value is not None, f"source.{field_name} is required")


def _source_available_at_least(
    context: AnalysisInvocationContext,
    required_at: object,
    capability_id: str,
) -> None:
    _binding(
        context.source.source_available_at >= required_at,
        f"{capability_id} source is available before its required source datum",
    )


def _parameterized_result(
    spec: AnalysisInvocationSpec,
    context: AnalysisInvocationContext,
    result: object,
    parameters: tuple[tuple[str, str], ...],
    state_fingerprint: str | None = None,
) -> AnalysisInvocationResult:
    return AnalysisInvocationResult(
        capability_id=spec.capability_id,
        method_version=spec.method_version,
        source=context.source,
        market_as_of=context.market_as_of,
        request_available_at=context.request_available_at,
        evaluation_at=context.evaluation_at,
        parameter_identity=parameters,
        parameter_fingerprint=_parameter_fingerprint(spec.method_version, parameters),
        result=result,
        state_fingerprint=state_fingerprint,
    )


def _execute_trendlines(
    request: object,
    context: AnalysisInvocationContext,
) -> tuple[object, tuple[tuple[str, str], ...]]:
    from libs.models.trendlines import HISTORY_CAPACITY_BARS, PIVOT_WINDOW

    from ..execution.trendlines import TrendlinesExecutionRequest

    if not isinstance(request, TrendlinesExecutionRequest):
        raise TypeError("request must be TrendlinesExecutionRequest")
    _binding(bool(request.history), "Trendlines history must not be empty")
    _binding(
        request.history[-1].closed_at == context.market_as_of,
        "Trendlines final close does not match market_as_of",
    )
    _binding(
        context.request_available_at >= request.history[-1].closed_at,
        "Trendlines request is available before its final close",
    )
    _source_available_at_least(
        context,
        request.history[-1].closed_at,
        "model.trendlines",
    )
    result = execute_analysis_capability("model.trendlines", request)
    _binding(
        getattr(result, "market_as_of", None) == context.market_as_of,
        "Trendlines result cutoff does not match market_as_of",
    )
    return result, (
        ("history_capacity_bars", str(HISTORY_CAPACITY_BARS)),
        ("pivot_window", str(PIVOT_WINDOW)),
    )


def _execute_sr(
    request: object,
    context: AnalysisInvocationContext,
) -> tuple[object, tuple[tuple[str, str], ...]]:
    from ..execution.sr import SRExecutionRequest

    if not isinstance(request, SRExecutionRequest):
        raise TypeError("request must be SRExecutionRequest")
    key = request.closed_bar.state_key
    series = context.source.series
    _binding(key.venue == series.venue, "SR venue does not match source series")
    _binding(key.symbol == series.asset, "SR symbol does not match source asset")
    _binding(
        key.timeframe == series.timeframe,
        "SR timeframe does not match source timeframe",
    )
    _binding(
        request.closed_bar.closed_at == context.market_as_of,
        "SR closed bar does not match market_as_of",
    )
    _binding(
        context.request_available_at >= request.closed_bar.closed_at,
        "SR request is available before the closed bar",
    )
    _source_available_at_least(context, request.closed_bar.closed_at, "model.sr")
    result = execute_analysis_capability("model.sr", request)
    snapshot = getattr(result, "snapshot", None)
    _binding(snapshot is not None, "SR result has no snapshot")
    _binding(snapshot.as_of == context.market_as_of, "SR snapshot cutoff mismatch")
    _binding(
        snapshot.state_key == request.closed_bar.state_key,
        "SR snapshot identity does not match the closed bar",
    )
    _binding(
        snapshot.config_hash == request.resolved_config.resolved_config_hash,
        "SR snapshot config hash mismatch",
    )
    return result, (
        ("resolved_config_hash", request.resolved_config.resolved_config_hash),
    )


def _execute_regression(
    request: object,
    context: AnalysisInvocationContext,
) -> tuple[object, tuple[tuple[str, str], ...]]:
    from libs.regression.channel import channel_config_fingerprint

    from ..execution.regression import RegressionExecutionRequest

    if not isinstance(request, RegressionExecutionRequest):
        raise TypeError("request must be RegressionExecutionRequest")
    series = context.source.series
    _binding(request.asset == series.asset, "Regression asset does not match source")
    _binding(
        request.timeframe == series.timeframe,
        "Regression timeframe does not match source",
    )
    channel_hash = channel_config_fingerprint(request.channel_config)
    result = execute_analysis_capability("model.regression", request)
    structural = result.channel.structural
    _binding(structural.asset == request.asset, "Regression result asset mismatch")
    _binding(
        structural.timeframe == request.timeframe,
        "Regression result timeframe mismatch",
    )
    _binding(
        structural.observed_through == context.market_as_of,
        "Regression observed-through cutoff mismatch",
    )
    _binding(
        context.request_available_at >= structural.observed_through,
        "Regression request is available before observed-through",
    )
    _binding(
        structural.source_config_hash == request.config.config_hash,
        "Regression source config hash mismatch",
    )
    _binding(
        result.channel.channel_config_hash == channel_hash,
        "Regression channel config hash mismatch",
    )
    _binding(
        structural.window_size == request.config.window_size,
        "Regression result window size mismatch",
    )
    _source_available_at_least(
        context,
        structural.observed_through,
        "model.regression",
    )
    return result, (
        ("channel_config_hash", channel_hash),
        ("source_config_hash", request.config.config_hash),
        ("window_size", str(request.config.window_size)),
    )


def _execute_fibonacci(
    request: object,
    context: AnalysisInvocationContext,
) -> tuple[object, tuple[tuple[str, str], ...]]:
    from ..ta.fibonacci_geometry import FibonacciGeometryRequest

    if not isinstance(request, FibonacciGeometryRequest):
        raise TypeError("request must be FibonacciGeometryRequest")
    _binding(
        request.market_as_of == context.market_as_of,
        "Fibonacci request cutoff does not match market_as_of",
    )
    _binding(
        context.request_available_at >= request.start_anchor.available_at,
        "Fibonacci request is available before the start anchor",
    )
    _binding(
        context.request_available_at >= request.end_anchor.available_at,
        "Fibonacci request is available before the end anchor",
    )
    _source_available_at_least(
        context,
        max(request.start_anchor.available_at, request.end_anchor.available_at),
        "ta.fibonacci_geometry",
    )
    result = execute_analysis_capability("ta.fibonacci_geometry", request)
    _binding(
        result.market_as_of == context.market_as_of,
        "Fibonacci result cutoff does not match market_as_of",
    )
    return result, (
        (
            "extension_ratios",
            _ratio_identity(request.extension_ratios, field_name="extension_ratios"),
        ),
        (
            "retracement_ratios",
            _ratio_identity(
                request.retracement_ratios, field_name="retracement_ratios"
            ),
        ),
    )


def _execute_swing(
    request: object,
    context: AnalysisInvocationContext,
) -> tuple[object, tuple[tuple[str, str], ...]]:
    from ..ta.swing_anchors import SwingAnchorRequest

    if not isinstance(request, SwingAnchorRequest):
        raise TypeError("request must be SwingAnchorRequest")
    _binding(bool(request.bars), "Swing anchor bars must not be empty")
    _binding(
        request.bars[-1].closed_at == context.market_as_of,
        "Swing final bar does not match market_as_of",
    )
    _binding(
        context.request_available_at >= request.bars[-1].closed_at,
        "Swing request is available before the final bar",
    )
    _source_available_at_least(
        context,
        request.bars[-1].closed_at,
        "ta.swing_anchors",
    )
    result = execute_analysis_capability("ta.swing_anchors", request)
    _binding(
        result.market_as_of == context.market_as_of,
        "Swing result cutoff does not match market_as_of",
    )
    return result, (("span", str(request.span)),)


def _execute_traditional(
    request: object,
    context: AnalysisInvocationContext,
) -> tuple[object, tuple[tuple[str, str], ...]]:
    from ..ta.traditional_pivot_geometry import TraditionalPivotGeometryRequest

    if not isinstance(request, TraditionalPivotGeometryRequest):
        raise TypeError("request must be TraditionalPivotGeometryRequest")
    _binding(
        request.market_as_of == context.market_as_of,
        "Traditional pivot request cutoff does not match market_as_of",
    )
    _binding(
        context.request_available_at >= request.reference.closed_at,
        "Traditional pivot request is available before the reference close",
    )
    _source_available_at_least(
        context,
        request.reference.closed_at,
        "ta.traditional_pivot_geometry",
    )
    result = execute_analysis_capability("ta.traditional_pivot_geometry", request)
    _binding(
        result.market_as_of == context.market_as_of,
        "Traditional pivot result cutoff does not match market_as_of",
    )
    return result, ()


def _execute_vwap(
    request: object,
    context: AnalysisInvocationContext,
) -> tuple[object, tuple[tuple[str, str], ...]]:
    from ..ta.vwap_geometry import VWAPGeometryRequest

    if not isinstance(request, VWAPGeometryRequest):
        raise TypeError("request must be VWAPGeometryRequest")
    _binding(
        request.market_as_of == context.market_as_of,
        "VWAP request cutoff does not match market_as_of",
    )
    _binding(
        context.request_available_at >= request.bars[-1].closed_at,
        "VWAP request is available before the final bar",
    )
    _source_available_at_least(
        context,
        request.bars[-1].closed_at,
        "ta.vwap_geometry",
    )
    result = execute_analysis_capability("ta.vwap_geometry", request)
    _binding(
        result.market_as_of == context.market_as_of,
        "VWAP result cutoff does not match market_as_of",
    )
    return result, ()


def _execute_parallel_channel(
    request: object,
    context: AnalysisInvocationContext,
) -> tuple[object, tuple[tuple[str, str], ...]]:
    from ..ta.parallel_channel_geometry import ParallelChannelGeometryRequest

    if not isinstance(request, ParallelChannelGeometryRequest):
        raise TypeError("request must be ParallelChannelGeometryRequest")
    _binding(
        request.market_as_of == context.market_as_of,
        "Parallel channel request cutoff does not match market_as_of",
    )
    required_at = max(
        request.start_anchor.available_at,
        request.end_anchor.available_at,
        request.offset_anchor.available_at,
    )
    _binding(
        context.request_available_at >= required_at,
        "Parallel channel request is available before an anchor",
    )
    _source_available_at_least(
        context,
        context.market_as_of,
        "ta.parallel_channel_geometry",
    )
    result = execute_analysis_capability("ta.parallel_channel_geometry", request)
    _binding(
        result.market_as_of == context.market_as_of,
        "Parallel channel result cutoff does not match market_as_of",
    )
    return result, ()


def _execute_fibonacci_trend_extension(
    request: object,
    context: AnalysisInvocationContext,
) -> tuple[object, tuple[tuple[str, str], ...]]:
    from ..ta.fibonacci_trend_extension_geometry import (
        FibonacciTrendExtensionRequest,
    )

    if not isinstance(request, FibonacciTrendExtensionRequest):
        raise TypeError("request must be FibonacciTrendExtensionRequest")
    _binding(
        request.market_as_of == context.market_as_of,
        "Fibonacci trend extension request cutoff does not match market_as_of",
    )
    required_at = max(
        request.start_anchor.available_at,
        request.impulse_end_anchor.available_at,
        request.retracement_anchor.available_at,
    )
    _binding(
        context.request_available_at >= required_at,
        "Fibonacci trend extension request is available before an anchor",
    )
    _source_available_at_least(
        context,
        required_at,
        "ta.fibonacci_trend_extension_geometry",
    )
    result = execute_analysis_capability(
        "ta.fibonacci_trend_extension_geometry",
        request,
    )
    _binding(
        result.market_as_of == context.market_as_of,
        "Fibonacci trend extension result cutoff does not match market_as_of",
    )
    return result, (
        (
            "extension_ratios",
            _ratio_identity(request.extension_ratios, field_name="extension_ratios"),
        ),
    )


def _execute_anchored_vwap_path(
    request: object,
    context: AnalysisInvocationContext,
) -> tuple[object, tuple[tuple[str, str], ...]]:
    from ..ta.anchored_vwap_path import AnchoredVWAPPathRequest

    if not isinstance(request, AnchoredVWAPPathRequest):
        raise TypeError("request must be AnchoredVWAPPathRequest")
    _binding(
        request.market_as_of == context.market_as_of,
        "Anchored VWAP path request cutoff does not match market_as_of",
    )
    final_close = request.bars[-1].closed_at
    _binding(
        context.request_available_at >= final_close,
        "Anchored VWAP path request is available before the final bar",
    )
    _source_available_at_least(
        context,
        final_close,
        "ta.anchored_vwap_path",
    )
    result = execute_analysis_capability("ta.anchored_vwap_path", request)
    _binding(
        result.market_as_of == context.market_as_of,
        "Anchored VWAP path result cutoff does not match market_as_of",
    )
    return result, ()


def _execute_gann_fan(
    request: object,
    context: AnalysisInvocationContext,
) -> tuple[object, tuple[tuple[str, str], ...]]:
    from ..ta.gann_fan_geometry import GannFanGeometryRequest

    if not isinstance(request, GannFanGeometryRequest):
        raise TypeError("request must be GannFanGeometryRequest")
    _binding(
        request.market_as_of == context.market_as_of,
        "Gann fan request cutoff does not match market_as_of",
    )
    required_at = max(request.anchor.available_at, request.market_as_of)
    _binding(
        context.request_available_at >= required_at,
        "Gann fan request is available before its required facts",
    )
    _source_available_at_least(
        context,
        request.market_as_of,
        "ta.gann_fan_geometry",
    )
    result = execute_analysis_capability("ta.gann_fan_geometry", request)
    _binding(
        result.market_as_of == context.market_as_of,
        "Gann fan result cutoff does not match market_as_of",
    )
    angle_identity = ",".join(
        f"{ratio.price_units}x{ratio.time_units}" for ratio in request.angle_ratios
    )
    return result, (
        ("angle_ratios", angle_identity),
        (
            "price_per_bar",
            _float_identity(request.price_per_bar, field_name="price_per_bar"),
        ),
    )


def _execute_gann_box(
    request: object,
    context: AnalysisInvocationContext,
) -> tuple[object, tuple[tuple[str, str], ...]]:
    from ..ta.gann_box_geometry import GannBoxGeometryRequest

    if not isinstance(request, GannBoxGeometryRequest):
        raise TypeError("request must be GannBoxGeometryRequest")
    _binding(
        request.market_as_of == context.market_as_of,
        "Gann box request cutoff does not match market_as_of",
    )
    required_at = max(
        request.start.available_at,
        request.end.available_at,
        request.market_as_of,
    )
    _binding(
        context.request_available_at >= required_at,
        "Gann box request is available before its required facts",
    )
    _source_available_at_least(
        context,
        request.market_as_of,
        "ta.gann_box_geometry",
    )
    result = execute_analysis_capability("ta.gann_box_geometry", request)
    _binding(
        result.market_as_of == context.market_as_of,
        "Gann box result cutoff does not match market_as_of",
    )
    return result, (
        (
            "price_levels",
            _ratio_identity(request.price_levels, field_name="price_levels"),
        ),
        (
            "time_levels",
            _ratio_identity(request.time_levels, field_name="time_levels"),
        ),
    )


def _execute_volume_profile(
    request: object,
    context: AnalysisInvocationContext,
) -> tuple[object, tuple[tuple[str, str], ...]]:
    from ..ta.volume_profile_geometry import VolumeProfileGeometryRequest

    if not isinstance(request, VolumeProfileGeometryRequest):
        raise TypeError("request must be VolumeProfileGeometryRequest")
    final_close = request.bars[-1].closed_at
    _binding(
        request.market_as_of == context.market_as_of,
        "Volume profile request cutoff does not match market_as_of",
    )
    _binding(
        context.request_available_at >= final_close,
        "Volume profile request is available before the final bar",
    )
    _source_available_at_least(
        context,
        final_close,
        "ta.volume_profile_geometry",
    )
    result = execute_analysis_capability("ta.volume_profile_geometry", request)
    _binding(
        result.market_as_of == context.market_as_of,
        "Volume profile result cutoff does not match market_as_of",
    )
    return result, (
        ("row_count", str(request.row_count)),
        (
            "value_area_fraction",
            _float_identity(
                request.value_area_fraction,
                field_name="value_area_fraction",
            ),
        ),
    )


def _execute_abcd(
    request: object,
    context: AnalysisInvocationContext,
) -> tuple[object, tuple[tuple[str, str], ...]]:
    from ..ta.abcd_pattern_geometry import ABCDPatternGeometryRequest

    if not isinstance(request, ABCDPatternGeometryRequest):
        raise TypeError("request must be ABCDPatternGeometryRequest")
    _binding(
        request.market_as_of == context.market_as_of,
        "ABCD request cutoff does not match market_as_of",
    )
    required_at = max(
        request.a.available_at,
        request.b.available_at,
        request.c.available_at,
        request.d.available_at,
    )
    _binding(
        context.request_available_at >= required_at,
        "ABCD request is available before an anchor",
    )
    _source_available_at_least(
        context,
        context.market_as_of,
        "ta.abcd_pattern_geometry",
    )
    result = execute_analysis_capability("ta.abcd_pattern_geometry", request)
    _binding(
        result.market_as_of == context.market_as_of,
        "ABCD result cutoff does not match market_as_of",
    )
    return result, ()


def _execute_xabcd(
    request: object,
    context: AnalysisInvocationContext,
) -> tuple[object, tuple[tuple[str, str], ...]]:
    from ..ta.xabcd_pattern_geometry import XABCDPatternGeometryRequest

    if not isinstance(request, XABCDPatternGeometryRequest):
        raise TypeError("request must be XABCDPatternGeometryRequest")
    _binding(
        request.market_as_of == context.market_as_of,
        "XABCD request cutoff does not match market_as_of",
    )
    required_at = max(
        request.x.available_at,
        request.a.available_at,
        request.b.available_at,
        request.c.available_at,
        request.d.available_at,
    )
    _binding(
        context.request_available_at >= required_at,
        "XABCD request is available before an anchor",
    )
    _source_available_at_least(
        context,
        context.market_as_of,
        "ta.xabcd_pattern_geometry",
    )
    result = execute_analysis_capability("ta.xabcd_pattern_geometry", request)
    _binding(
        result.market_as_of == context.market_as_of,
        "XABCD result cutoff does not match market_as_of",
    )
    return result, ()


def _execute_head_shoulders(
    request: object,
    context: AnalysisInvocationContext,
) -> tuple[object, tuple[tuple[str, str], ...]]:
    from ..ta.head_shoulders_pattern_geometry import (
        HeadShouldersPatternGeometryRequest,
    )

    if not isinstance(request, HeadShouldersPatternGeometryRequest):
        raise TypeError("request must be HeadShouldersPatternGeometryRequest")
    _binding(
        request.market_as_of == context.market_as_of,
        "Head & Shoulders request cutoff does not match market_as_of",
    )
    required_at = max(
        request.left_shoulder.available_at,
        request.neck_left.available_at,
        request.head.available_at,
        request.neck_right.available_at,
        request.right_shoulder.available_at,
    )
    _binding(
        context.request_available_at >= required_at,
        "Head & Shoulders request is available before an anchor",
    )
    _source_available_at_least(
        context,
        context.market_as_of,
        "ta.head_shoulders_pattern_geometry",
    )
    result = execute_analysis_capability(
        "ta.head_shoulders_pattern_geometry",
        request,
    )
    _binding(
        result.market_as_of == context.market_as_of,
        "Head & Shoulders result cutoff does not match market_as_of",
    )
    return result, ()


def _execute_triangle(
    request: object,
    context: AnalysisInvocationContext,
) -> tuple[object, tuple[tuple[str, str], ...]]:
    from ..ta.triangle_pattern_geometry import TrianglePatternGeometryRequest

    if not isinstance(request, TrianglePatternGeometryRequest):
        raise TypeError("request must be TrianglePatternGeometryRequest")
    _binding(
        request.market_as_of == context.market_as_of,
        "Triangle request cutoff does not match market_as_of",
    )
    required_at = max(
        request.a.available_at,
        request.b.available_at,
        request.c.available_at,
        request.d.available_at,
    )
    _binding(
        context.request_available_at >= required_at,
        "Triangle request is available before an anchor",
    )
    _source_available_at_least(
        context,
        context.market_as_of,
        "ta.triangle_pattern_geometry",
    )
    result = execute_analysis_capability("ta.triangle_pattern_geometry", request)
    _binding(
        result.market_as_of == context.market_as_of,
        "Triangle result cutoff does not match market_as_of",
    )
    return result, ()


def _execute_cypher(
    request: object,
    context: AnalysisInvocationContext,
) -> tuple[object, tuple[tuple[str, str], ...]]:
    from ..ta.cypher_pattern_geometry import CypherPatternGeometryRequest

    if not isinstance(request, CypherPatternGeometryRequest):
        raise TypeError("request must be CypherPatternGeometryRequest")
    _binding(
        request.market_as_of == context.market_as_of,
        "Cypher request cutoff does not match market_as_of",
    )
    required_at = max(
        request.x.available_at,
        request.a.available_at,
        request.b.available_at,
        request.c.available_at,
        request.d.available_at,
    )
    _binding(
        context.request_available_at >= required_at,
        "Cypher request is available before an anchor",
    )
    _source_available_at_least(
        context,
        context.market_as_of,
        "ta.cypher_pattern_geometry",
    )
    result = execute_analysis_capability("ta.cypher_pattern_geometry", request)
    _binding(
        result.market_as_of == context.market_as_of,
        "Cypher result cutoff does not match market_as_of",
    )
    return result, ()


def _execute_three_drives(
    request: object,
    context: AnalysisInvocationContext,
) -> tuple[object, tuple[tuple[str, str], ...]]:
    from ..ta.three_drives_pattern_geometry import (
        ThreeDrivesPatternGeometryRequest,
    )

    if not isinstance(request, ThreeDrivesPatternGeometryRequest):
        raise TypeError("request must be ThreeDrivesPatternGeometryRequest")
    _binding(
        request.market_as_of == context.market_as_of,
        "Three Drives request cutoff does not match market_as_of",
    )
    required_at = max(
        request.start.available_at,
        request.drive1.available_at,
        request.retrace_a.available_at,
        request.drive2.available_at,
        request.retrace_c.available_at,
        request.drive3.available_at,
    )
    _binding(
        context.request_available_at >= required_at,
        "Three Drives request is available before an anchor",
    )
    _source_available_at_least(
        context,
        context.market_as_of,
        "ta.three_drives_pattern_geometry",
    )
    result = execute_analysis_capability(
        "ta.three_drives_pattern_geometry",
        request,
    )
    _binding(
        result.market_as_of == context.market_as_of,
        "Three Drives result cutoff does not match market_as_of",
    )
    return result, ()


def _execute_elliott_impulse(
    request: object,
    context: AnalysisInvocationContext,
) -> tuple[object, tuple[tuple[str, str], ...]]:
    from ..ta.elliott_impulse_wave_geometry import (
        ElliottImpulseWaveGeometryRequest,
    )

    if not isinstance(request, ElliottImpulseWaveGeometryRequest):
        raise TypeError("request must be ElliottImpulseWaveGeometryRequest")
    _binding(
        request.market_as_of == context.market_as_of,
        "Elliott impulse request cutoff does not match market_as_of",
    )
    required_at = max(
        request.start.available_at,
        request.wave1.available_at,
        request.wave2.available_at,
        request.wave3.available_at,
        request.wave4.available_at,
        request.wave5.available_at,
    )
    _binding(
        context.request_available_at >= required_at,
        "Elliott impulse request is available before an anchor",
    )
    _source_available_at_least(
        context,
        context.market_as_of,
        "ta.elliott_impulse_wave_geometry",
    )
    result = execute_analysis_capability(
        "ta.elliott_impulse_wave_geometry",
        request,
    )
    _binding(
        result.market_as_of == context.market_as_of,
        "Elliott impulse result cutoff does not match market_as_of",
    )
    return result, ()


def _execute_elliott_correction(
    request: object,
    context: AnalysisInvocationContext,
) -> tuple[object, tuple[tuple[str, str], ...]]:
    from ..ta.elliott_correction_wave_geometry import (
        ElliottCorrectionWaveGeometryRequest,
    )

    if not isinstance(request, ElliottCorrectionWaveGeometryRequest):
        raise TypeError("request must be ElliottCorrectionWaveGeometryRequest")
    _binding(
        request.market_as_of == context.market_as_of,
        "Elliott correction request cutoff does not match market_as_of",
    )
    required_at = max(
        request.start.available_at,
        request.wave_a.available_at,
        request.wave_b.available_at,
        request.wave_c.available_at,
    )
    _binding(
        context.request_available_at >= required_at,
        "Elliott correction request is available before an anchor",
    )
    _source_available_at_least(
        context,
        context.market_as_of,
        "ta.elliott_correction_wave_geometry",
    )
    result = execute_analysis_capability(
        "ta.elliott_correction_wave_geometry",
        request,
    )
    _binding(
        result.market_as_of == context.market_as_of,
        "Elliott correction result cutoff does not match market_as_of",
    )
    return result, ()


def execute_bound_analysis_capability(
    capability_id: str,
    request: object,
    context: AnalysisInvocationContext,
) -> AnalysisInvocationResult:
    """Execute one existing capability with checked invocation provenance."""

    get_analysis_capability(capability_id)
    spec = get_analysis_invocation_spec(capability_id)
    if not isinstance(context, AnalysisInvocationContext):
        raise TypeError("context must be AnalysisInvocationContext")
    _source_fields(spec, context)
    if capability_id == "model.trendlines":
        result, parameters = _execute_trendlines(request, context)
    elif capability_id == "model.sr":
        result, parameters = _execute_sr(request, context)
    elif capability_id == "model.regression":
        result, parameters = _execute_regression(request, context)
    elif capability_id == "ta.fibonacci_geometry":
        result, parameters = _execute_fibonacci(request, context)
    elif capability_id == "ta.fibonacci_trend_extension_geometry":
        result, parameters = _execute_fibonacci_trend_extension(request, context)
    elif capability_id == "ta.parallel_channel_geometry":
        result, parameters = _execute_parallel_channel(request, context)
    elif capability_id == "ta.swing_anchors":
        result, parameters = _execute_swing(request, context)
    elif capability_id == "ta.traditional_pivot_geometry":
        result, parameters = _execute_traditional(request, context)
    elif capability_id == "ta.vwap_geometry":
        result, parameters = _execute_vwap(request, context)
    elif capability_id == "ta.anchored_vwap_path":
        result, parameters = _execute_anchored_vwap_path(request, context)
    elif capability_id == "ta.gann_fan_geometry":
        result, parameters = _execute_gann_fan(request, context)
    elif capability_id == "ta.gann_box_geometry":
        result, parameters = _execute_gann_box(request, context)
    elif capability_id == "ta.volume_profile_geometry":
        result, parameters = _execute_volume_profile(request, context)
    elif capability_id == "ta.abcd_pattern_geometry":
        result, parameters = _execute_abcd(request, context)
    elif capability_id == "ta.xabcd_pattern_geometry":
        result, parameters = _execute_xabcd(request, context)
    elif capability_id == "ta.head_shoulders_pattern_geometry":
        result, parameters = _execute_head_shoulders(request, context)
    elif capability_id == "ta.triangle_pattern_geometry":
        result, parameters = _execute_triangle(request, context)
    elif capability_id == "ta.cypher_pattern_geometry":
        result, parameters = _execute_cypher(request, context)
    elif capability_id == "ta.three_drives_pattern_geometry":
        result, parameters = _execute_three_drives(request, context)
    elif capability_id == "ta.elliott_impulse_wave_geometry":
        result, parameters = _execute_elliott_impulse(request, context)
    elif capability_id == "ta.elliott_correction_wave_geometry":
        result, parameters = _execute_elliott_correction(request, context)
    else:
        raise RuntimeError(f"missing bound executor: {capability_id!r}")
    if parameters != tuple(sorted(parameters)):
        raise RuntimeError("bound parameter identity is not sorted")
    state_fingerprint: str | None = None
    if capability_id == "model.sr":
        from libs.models.sr import deterministic_hash

        from ..execution.sr import SRExecutionRequest

        if not isinstance(request, SRExecutionRequest):
            raise TypeError("request must be SRExecutionRequest")
        state_fingerprint = deterministic_hash(request.previous_state)
    return _parameterized_result(
        spec,
        context,
        result,
        parameters,
        state_fingerprint=state_fingerprint,
    )


__all__ = ("execute_bound_analysis_capability",)
