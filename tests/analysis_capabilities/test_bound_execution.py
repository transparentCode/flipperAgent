from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from libs.analysis_capabilities.execution import execute_analysis_capability
from libs.analysis_capabilities.execution.regression import (
    RegressionExecutionRequest,
)
from libs.analysis_capabilities.execution.sr import SRExecutionRequest
from libs.analysis_capabilities.execution.trendlines import (
    TrendlinesExecutionRequest,
)
from libs.analysis_capabilities.invocation import (
    AnalysisBindingError,
    AnalysisInvocationContext,
    AnalysisSeriesIdentity,
    AnalysisSourceAttestation,
    execute_bound_analysis_capability,
)
from libs.analysis_capabilities.ta.abcd_pattern_geometry import (
    ABCDPatternGeometryRequest,
)
from libs.analysis_capabilities.ta.anchored_vwap_path import (
    AnchoredVWAPPathRequest,
)
from libs.analysis_capabilities.ta.cypher_pattern_geometry import (
    CypherPatternGeometryRequest,
)
from libs.analysis_capabilities.ta.elliott_correction_wave_geometry import (
    ElliottCorrectionWaveGeometryRequest,
)
from libs.analysis_capabilities.ta.elliott_impulse_wave_geometry import (
    ElliottImpulseWaveGeometryRequest,
)
from libs.analysis_capabilities.ta.fibonacci_geometry import (
    FibonacciGeometryRequest,
)
from libs.analysis_capabilities.ta.fibonacci_trend_extension_geometry import (
    FibonacciTrendExtensionRequest,
)
from libs.analysis_capabilities.ta.head_shoulders_pattern_geometry import (
    HeadShouldersPatternGeometryRequest,
)
from libs.analysis_capabilities.ta.parallel_channel_geometry import (
    ParallelChannelBar,
    ParallelChannelGeometryRequest,
)
from libs.analysis_capabilities.ta.swing_anchors import (
    SwingAnchor,
    SwingAnchorBar,
    SwingAnchorRequest,
)
from libs.analysis_capabilities.ta.three_drives_pattern_geometry import (
    ThreeDrivesPatternGeometryRequest,
)
from libs.analysis_capabilities.ta.traditional_pivot_geometry import (
    TraditionalPivotGeometryRequest,
    TraditionalPivotReference,
)
from libs.analysis_capabilities.ta.triangle_pattern_geometry import (
    TrianglePatternGeometryRequest,
)
from libs.analysis_capabilities.ta.vwap_geometry import (
    VWAPBar,
    VWAPGeometryRequest,
)
from libs.analysis_capabilities.ta.xabcd_pattern_geometry import (
    XABCDPatternGeometryRequest,
)
from libs.models.sr import (
    AssociationConfig,
    ClosedBar,
    DetectionConfig,
    LifecycleConfig,
    ResolvedSRConfig,
    RuntimeConfig,
    SRStateKey,
    create_initial_state,
)
from libs.models.trendlines import TrendlineBar
from libs.regression.config.resolver import ConfigResolver

ROOT = Path(__file__).resolve().parents[2]
_START = datetime(2026, 1, 1, tzinfo=UTC)
_REGRESSION_CONFIG = ROOT / "src" / "libs" / "regression" / "config" / "regression.yaml"


def _series(
    *,
    asset: str = "BTCUSDT",
    venue: str = "binance",
    timeframe: str = "1h",
) -> AnalysisSeriesIdentity:
    return AnalysisSeriesIdentity(
        asset=asset,
        venue=venue,
        instrument_id=f"{venue}:{asset}",
        timeframe=timeframe,
    )


def _context(
    series: AnalysisSeriesIdentity,
    market_as_of: datetime,
    *,
    request_available_at: datetime | None = None,
    source_available_at: datetime | None = None,
    volume_unit: str | None = None,
) -> AnalysisInvocationContext:
    request_available_at = request_available_at or (market_as_of + timedelta(minutes=1))
    return AnalysisInvocationContext(
        source=AnalysisSourceAttestation(
            series=series,
            source_type="fixture",
            source_provider=None,
            source_timeframe=None,
            source_revision="synthetic-r2-1",
            source_slice_sha256="c" * 64,
            source_available_at=source_available_at or market_as_of,
            volume_unit=volume_unit,
        ),
        market_as_of=market_as_of,
        request_available_at=request_available_at,
        evaluation_at=max(request_available_at, market_as_of) + timedelta(minutes=1),
    )


def _trendlines_request() -> TrendlinesExecutionRequest:
    history = tuple(
        TrendlineBar(
            closed_at=_START + timedelta(hours=index),
            open=100.0 + index * 0.05,
            high=101.0 + index * 0.05,
            low=99.0 + index * 0.05,
            close=100.5 + index * 0.05,
        )
        for index in range(305)
    )
    return TrendlinesExecutionRequest(history)


def _sr_config(key: SRStateKey, *, pivot_span_bars: int = 1) -> ResolvedSRConfig:
    return ResolvedSRConfig.create(
        version="1",
        asset=key.symbol,
        timeframe=key.timeframe,
        detection=DetectionConfig(
            pivot_span_bars=pivot_span_bars,
            zone_half_width_atr=0.25,
        ),
        association=AssociationConfig(merge_distance_atr=0.5),
        lifecycle=LifecycleConfig(
            touch_tolerance_atr=0.25,
            break_buffer_atr=0.5,
            break_confirm_closes=2,
            max_age_bars=50,
        ),
        runtime=RuntimeConfig(max_active_zones=8),
        field_provenance={
            "detection.pivot_span_bars": "defaults",
            "detection.zone_half_width_atr": "defaults",
            "association.merge_distance_atr": "defaults",
            "lifecycle.touch_tolerance_atr": "defaults",
            "lifecycle.break_buffer_atr": "defaults",
            "lifecycle.break_confirm_closes": "defaults",
            "lifecycle.max_age_bars": "defaults",
            "runtime.max_active_zones": "defaults",
        },
    )


def _sr_request(
    *,
    config: ResolvedSRConfig | None = None,
    previous_state: object | None = None,
    index: int = 0,
) -> SRExecutionRequest:
    key = SRStateKey(venue="binance", symbol="BTCUSDT", timeframe="1h")
    config = config or _sr_config(key)
    return SRExecutionRequest(
        previous_state=previous_state or create_initial_state(key, config),
        closed_bar=ClosedBar(
            state_key=key,
            bar_id=f"bar-{index}",
            closed_at=_START + timedelta(hours=index),
            open=99.75 + index,
            high=100.75 + index,
            low=99.25 + index,
            close=100.0 + index,
            atr_at_close=1.0,
        ),
        resolved_config=config,
    )


def _regression_request() -> RegressionExecutionRequest:
    resolver = ConfigResolver.from_yaml(str(_REGRESSION_CONFIG))
    config = replace(resolver.resolve("BTCUSDT", "1h"), window_size=20)
    index = pd.date_range("2026-01-01", periods=21, freq="1h", tz="UTC")
    frame = pd.DataFrame(
        {
            "close": np.linspace(100.0, 120.0, len(index)),
            "volume": np.full(len(index), 100.0),
        },
        index=index,
    )
    return RegressionExecutionRequest(
        frame=frame,
        asset="BTCUSDT",
        timeframe="1h",
        config=config,
        channel_config=resolver.structural_channel_config,
    )


def _fibonacci_request(
    *, ratios: tuple[float, ...] = (0.25, 0.5)
) -> FibonacciGeometryRequest:
    start = SwingAnchor(
        "swing_low",
        _START,
        _START + timedelta(hours=1),
        100.0,
    )
    end = SwingAnchor(
        "swing_high",
        _START + timedelta(hours=2),
        _START + timedelta(hours=3),
        160.0,
    )
    return FibonacciGeometryRequest(
        start_anchor=start,
        end_anchor=end,
        market_as_of=_START + timedelta(hours=4),
        retracement_ratios=ratios,
        extension_ratios=(1.25, 1.5),
    )


def _swing_request(*, span: int = 1) -> SwingAnchorRequest:
    bars = tuple(
        SwingAnchorBar(
            closed_at=_START + timedelta(hours=index),
            high=10.0 + (20.0 if index == 1 else 0.0),
            low=5.0 - (4.0 if index == 3 else 0.0),
        )
        for index in range(5)
    )
    return SwingAnchorRequest(bars=bars, span=span)


def _traditional_request() -> TraditionalPivotGeometryRequest:
    reference = TraditionalPivotReference(
        opened_at=_START,
        closed_at=_START + timedelta(hours=4),
        high=120.0,
        low=90.0,
        close=99.0,
    )
    return TraditionalPivotGeometryRequest(
        reference=reference,
        market_as_of=_START + timedelta(hours=5),
    )


def _vwap_request() -> VWAPGeometryRequest:
    bars = (
        VWAPBar(_START, 10.0, 8.0, 9.0, 2.0),
        VWAPBar(_START + timedelta(hours=1), 14.0, 10.0, 13.0, 3.0),
    )
    return VWAPGeometryRequest(bars=bars, market_as_of=bars[-1].closed_at)


def _parallel_channel_request() -> ParallelChannelGeometryRequest:
    bars = tuple(
        ParallelChannelBar(_START + timedelta(hours=index)) for index in range(6)
    )
    start = SwingAnchor(
        "swing_low",
        bars[0].closed_at,
        bars[1].closed_at,
        100.0,
    )
    end = SwingAnchor(
        "swing_low",
        bars[2].closed_at,
        bars[3].closed_at,
        104.0,
    )
    offset = SwingAnchor(
        "swing_high",
        bars[1].closed_at,
        bars[2].closed_at,
        110.0,
    )
    return ParallelChannelGeometryRequest(
        bars=bars,
        start_anchor=start,
        end_anchor=end,
        offset_anchor=offset,
        market_as_of=bars[-1].closed_at,
    )


def _fibonacci_trend_extension_request() -> FibonacciTrendExtensionRequest:
    start = SwingAnchor(
        "swing_low",
        _START,
        _START + timedelta(hours=1),
        100.0,
    )
    impulse_end = SwingAnchor(
        "swing_high",
        _START + timedelta(hours=2),
        _START + timedelta(hours=3),
        160.0,
    )
    retracement = SwingAnchor(
        "swing_low",
        _START + timedelta(hours=4),
        _START + timedelta(hours=5),
        130.0,
    )
    return FibonacciTrendExtensionRequest(
        start_anchor=start,
        impulse_end_anchor=impulse_end,
        retracement_anchor=retracement,
        market_as_of=_START + timedelta(hours=5),
        extension_ratios=(1.25, 1.5),
    )


def _anchored_vwap_path_request() -> AnchoredVWAPPathRequest:
    bars = (
        VWAPBar(_START, 10.0, 8.0, 9.0, 2.0),
        VWAPBar(_START + timedelta(hours=1), 14.0, 10.0, 13.0, 3.0),
    )
    return AnchoredVWAPPathRequest(bars=bars, market_as_of=bars[-1].closed_at)


def _pattern_bars() -> tuple[ParallelChannelBar, ...]:
    return tuple(
        ParallelChannelBar(_START + timedelta(hours=hour))
        for hour in (0, 1, 2, 5, 6, 9, 10, 14, 18, 19, 20)
    )


def _pattern_anchor(
    bars: tuple[ParallelChannelBar, ...], kind: str, index: int, price: float
) -> SwingAnchor:
    formed_at = bars[index].closed_at
    return SwingAnchor(kind, formed_at, formed_at + timedelta(minutes=5), price)


def _abcd_pattern_request() -> ABCDPatternGeometryRequest:
    bars = _pattern_bars()
    return ABCDPatternGeometryRequest(
        bars=bars,
        a=_pattern_anchor(bars, "swing_low", 1, 100.0),
        b=_pattern_anchor(bars, "swing_high", 3, 140.0),
        c=_pattern_anchor(bars, "swing_low", 5, 120.0),
        d=_pattern_anchor(bars, "swing_high", 8, 150.0),
        market_as_of=bars[-1].closed_at,
    )


def _xabcd_pattern_request() -> XABCDPatternGeometryRequest:
    bars = _pattern_bars()
    return XABCDPatternGeometryRequest(
        bars=bars,
        x=_pattern_anchor(bars, "swing_low", 1, 100.0),
        a=_pattern_anchor(bars, "swing_high", 2, 160.0),
        b=_pattern_anchor(bars, "swing_low", 4, 130.0),
        c=_pattern_anchor(bars, "swing_high", 6, 150.0),
        d=_pattern_anchor(bars, "swing_low", 8, 110.0),
        market_as_of=bars[-1].closed_at,
    )


def _head_shoulders_pattern_request() -> HeadShouldersPatternGeometryRequest:
    bars = _pattern_bars()
    return HeadShouldersPatternGeometryRequest(
        bars=bars,
        left_shoulder=_pattern_anchor(bars, "swing_high", 1, 120.0),
        neck_left=_pattern_anchor(bars, "swing_low", 2, 100.0),
        head=_pattern_anchor(bars, "swing_high", 4, 145.0),
        neck_right=_pattern_anchor(bars, "swing_low", 6, 105.0),
        right_shoulder=_pattern_anchor(bars, "swing_high", 8, 125.0),
        market_as_of=bars[-1].closed_at,
    )


def _triangle_pattern_request() -> TrianglePatternGeometryRequest:
    bars = _pattern_bars()
    return TrianglePatternGeometryRequest(
        bars=bars,
        a=_pattern_anchor(bars, "swing_high", 1, 130.0),
        b=_pattern_anchor(bars, "swing_low", 2, 100.0),
        c=_pattern_anchor(bars, "swing_high", 5, 120.0),
        d=_pattern_anchor(bars, "swing_low", 7, 110.0),
        market_as_of=bars[-1].closed_at,
    )


def _cypher_pattern_request() -> CypherPatternGeometryRequest:
    bars = _pattern_bars()
    return CypherPatternGeometryRequest(
        bars=bars,
        x=_pattern_anchor(bars, "swing_low", 0, 100.0),
        a=_pattern_anchor(bars, "swing_high", 1, 160.0),
        b=_pattern_anchor(bars, "swing_low", 3, 130.0),
        c=_pattern_anchor(bars, "swing_high", 5, 190.0),
        d=_pattern_anchor(bars, "swing_low", 7, 145.0),
        market_as_of=bars[-1].closed_at,
    )


def _three_drives_pattern_request() -> ThreeDrivesPatternGeometryRequest:
    bars = _pattern_bars()
    return ThreeDrivesPatternGeometryRequest(
        bars=bars,
        start=_pattern_anchor(bars, "swing_low", 0, 100.0),
        drive1=_pattern_anchor(bars, "swing_high", 1, 160.0),
        retrace_a=_pattern_anchor(bars, "swing_low", 3, 130.0),
        drive2=_pattern_anchor(bars, "swing_high", 5, 200.0),
        retrace_c=_pattern_anchor(bars, "swing_low", 7, 160.0),
        drive3=_pattern_anchor(bars, "swing_high", 9, 230.0),
        market_as_of=bars[-1].closed_at,
    )


def _elliott_impulse_wave_request() -> ElliottImpulseWaveGeometryRequest:
    bars = _pattern_bars()
    return ElliottImpulseWaveGeometryRequest(
        bars=bars,
        start=_pattern_anchor(bars, "swing_low", 0, 100.0),
        wave1=_pattern_anchor(bars, "swing_high", 1, 160.0),
        wave2=_pattern_anchor(bars, "swing_low", 3, 130.0),
        wave3=_pattern_anchor(bars, "swing_high", 5, 200.0),
        wave4=_pattern_anchor(bars, "swing_low", 7, 160.0),
        wave5=_pattern_anchor(bars, "swing_high", 9, 230.0),
        market_as_of=bars[-1].closed_at,
    )


def _elliott_correction_wave_request() -> ElliottCorrectionWaveGeometryRequest:
    bars = _pattern_bars()
    return ElliottCorrectionWaveGeometryRequest(
        bars=bars,
        start=_pattern_anchor(bars, "swing_low", 0, 100.0),
        wave_a=_pattern_anchor(bars, "swing_high", 2, 140.0),
        wave_b=_pattern_anchor(bars, "swing_low", 3, 130.0),
        wave_c=_pattern_anchor(bars, "swing_high", 7, 135.0),
        market_as_of=bars[-1].closed_at,
    )


def test_all_bound_results_equal_existing_dispatcher_results() -> None:
    trendlines = _trendlines_request()
    trendlines_direct = execute_analysis_capability("model.trendlines", trendlines)
    trendlines_bound = execute_bound_analysis_capability(
        "model.trendlines",
        trendlines,
        _context(_series(), trendlines.history[-1].closed_at),
    )

    sr = _sr_request()
    sr_direct = execute_analysis_capability("model.sr", sr)
    sr_bound = execute_bound_analysis_capability(
        "model.sr", sr, _context(_series(), sr.closed_bar.closed_at)
    )

    regression = _regression_request()
    regression_direct = execute_analysis_capability("model.regression", regression)
    regression_cutoff = regression_direct.channel.structural.observed_through
    regression_bound = execute_bound_analysis_capability(
        "model.regression",
        regression,
        _context(_series(), regression_cutoff),
    )

    fibonacci = _fibonacci_request()
    fibonacci_direct = execute_analysis_capability("ta.fibonacci_geometry", fibonacci)
    fibonacci_bound = execute_bound_analysis_capability(
        "ta.fibonacci_geometry",
        fibonacci,
        _context(_series(), fibonacci.market_as_of),
    )

    swing = _swing_request()
    swing_direct = execute_analysis_capability("ta.swing_anchors", swing)
    swing_bound = execute_bound_analysis_capability(
        "ta.swing_anchors",
        swing,
        _context(_series(), swing.bars[-1].closed_at),
    )

    traditional = _traditional_request()
    traditional_direct = execute_analysis_capability(
        "ta.traditional_pivot_geometry", traditional
    )
    traditional_bound = execute_bound_analysis_capability(
        "ta.traditional_pivot_geometry",
        traditional,
        _context(_series(), traditional.market_as_of),
    )

    vwap = _vwap_request()
    vwap_direct = execute_analysis_capability("ta.vwap_geometry", vwap)
    vwap_bound = execute_bound_analysis_capability(
        "ta.vwap_geometry",
        vwap,
        _context(_series(), vwap.market_as_of, volume_unit="base_asset"),
    )

    parallel = _parallel_channel_request()
    parallel_direct = execute_analysis_capability(
        "ta.parallel_channel_geometry", parallel
    )
    parallel_bound = execute_bound_analysis_capability(
        "ta.parallel_channel_geometry",
        parallel,
        _context(_series(), parallel.market_as_of),
    )

    extension = _fibonacci_trend_extension_request()
    extension_direct = execute_analysis_capability(
        "ta.fibonacci_trend_extension_geometry", extension
    )
    extension_bound = execute_bound_analysis_capability(
        "ta.fibonacci_trend_extension_geometry",
        extension,
        _context(_series(), extension.market_as_of),
    )

    anchored_path = _anchored_vwap_path_request()
    anchored_path_direct = execute_analysis_capability(
        "ta.anchored_vwap_path", anchored_path
    )
    anchored_path_bound = execute_bound_analysis_capability(
        "ta.anchored_vwap_path",
        anchored_path,
        _context(
            _series(),
            anchored_path.market_as_of,
            volume_unit="base_asset",
        ),
    )

    abcd = _abcd_pattern_request()
    abcd_direct = execute_analysis_capability("ta.abcd_pattern_geometry", abcd)
    abcd_bound = execute_bound_analysis_capability(
        "ta.abcd_pattern_geometry",
        abcd,
        _context(_series(), abcd.market_as_of),
    )

    xabcd = _xabcd_pattern_request()
    xabcd_direct = execute_analysis_capability("ta.xabcd_pattern_geometry", xabcd)
    xabcd_bound = execute_bound_analysis_capability(
        "ta.xabcd_pattern_geometry",
        xabcd,
        _context(_series(), xabcd.market_as_of),
    )

    head_shoulders = _head_shoulders_pattern_request()
    head_shoulders_direct = execute_analysis_capability(
        "ta.head_shoulders_pattern_geometry", head_shoulders
    )
    head_shoulders_bound = execute_bound_analysis_capability(
        "ta.head_shoulders_pattern_geometry",
        head_shoulders,
        _context(_series(), head_shoulders.market_as_of),
    )

    triangle = _triangle_pattern_request()
    triangle_direct = execute_analysis_capability(
        "ta.triangle_pattern_geometry", triangle
    )
    triangle_bound = execute_bound_analysis_capability(
        "ta.triangle_pattern_geometry",
        triangle,
        _context(_series(), triangle.market_as_of),
    )

    cypher = _cypher_pattern_request()
    cypher_direct = execute_analysis_capability("ta.cypher_pattern_geometry", cypher)
    cypher_bound = execute_bound_analysis_capability(
        "ta.cypher_pattern_geometry",
        cypher,
        _context(_series(), cypher.market_as_of),
    )

    three_drives = _three_drives_pattern_request()
    three_drives_direct = execute_analysis_capability(
        "ta.three_drives_pattern_geometry", three_drives
    )
    three_drives_bound = execute_bound_analysis_capability(
        "ta.three_drives_pattern_geometry",
        three_drives,
        _context(_series(), three_drives.market_as_of),
    )

    elliott_impulse = _elliott_impulse_wave_request()
    elliott_impulse_direct = execute_analysis_capability(
        "ta.elliott_impulse_wave_geometry", elliott_impulse
    )
    elliott_impulse_bound = execute_bound_analysis_capability(
        "ta.elliott_impulse_wave_geometry",
        elliott_impulse,
        _context(_series(), elliott_impulse.market_as_of),
    )

    elliott_correction = _elliott_correction_wave_request()
    elliott_correction_direct = execute_analysis_capability(
        "ta.elliott_correction_wave_geometry", elliott_correction
    )
    elliott_correction_bound = execute_bound_analysis_capability(
        "ta.elliott_correction_wave_geometry",
        elliott_correction,
        _context(_series(), elliott_correction.market_as_of),
    )

    pairs = (
        (trendlines_direct, trendlines_bound),
        (sr_direct, sr_bound),
        (regression_direct, regression_bound),
        (fibonacci_direct, fibonacci_bound),
        (swing_direct, swing_bound),
        (traditional_direct, traditional_bound),
        (vwap_direct, vwap_bound),
        (parallel_direct, parallel_bound),
        (extension_direct, extension_bound),
        (anchored_path_direct, anchored_path_bound),
        (abcd_direct, abcd_bound),
        (xabcd_direct, xabcd_bound),
        (head_shoulders_direct, head_shoulders_bound),
        (triangle_direct, triangle_bound),
        (cypher_direct, cypher_bound),
        (three_drives_direct, three_drives_bound),
        (elliott_impulse_direct, elliott_impulse_bound),
        (elliott_correction_direct, elliott_correction_bound),
    )
    assert all(bound.result == direct for direct, bound in pairs)
    assert all(bound.market_as_of <= bound.evaluation_at for _, bound in pairs)
    assert trendlines_bound.parameter_identity == (
        ("history_capacity_bars", "300"),
        ("pivot_window", "3"),
    )
    assert sr_bound.parameter_identity == (
        ("resolved_config_hash", sr.resolved_config.resolved_config_hash),
    )
    assert tuple(name for name, _ in regression_bound.parameter_identity) == (
        "channel_config_hash",
        "source_config_hash",
        "window_size",
    )
    assert regression_bound.parameter_identity[1][1] == regression.config.config_hash
    assert regression_bound.result.channel.structural.window_size == 20
    assert sr_bound.state_fingerprint is not None
    assert trendlines_bound.state_fingerprint is None
    assert regression_bound.state_fingerprint is None
    assert fibonacci_bound.state_fingerprint is None
    assert swing_bound.state_fingerprint is None
    assert traditional_bound.state_fingerprint is None
    assert vwap_bound.state_fingerprint is None
    assert parallel_bound.state_fingerprint is None
    assert extension_bound.state_fingerprint is None
    assert anchored_path_bound.state_fingerprint is None
    assert abcd_bound.state_fingerprint is None
    assert xabcd_bound.state_fingerprint is None
    assert head_shoulders_bound.state_fingerprint is None
    assert triangle_bound.state_fingerprint is None
    assert cypher_bound.state_fingerprint is None
    assert three_drives_bound.state_fingerprint is None
    assert elliott_impulse_bound.state_fingerprint is None
    assert elliott_correction_bound.state_fingerprint is None
    assert fibonacci_bound.source.source_type == "fixture"
    assert vwap_bound.source.volume_unit == "base_asset"
    assert extension_bound.parameter_identity == (
        (
            "extension_ratios",
            "0x1.4000000000000p+0,0x1.8000000000000p+0",
        ),
    )


@pytest.mark.parametrize(
    ("capability_id", "factory", "anchor_names"),
    (
        (
            "ta.abcd_pattern_geometry",
            _abcd_pattern_request,
            ("a", "b", "c", "d"),
        ),
        (
            "ta.xabcd_pattern_geometry",
            _xabcd_pattern_request,
            ("x", "a", "b", "c", "d"),
        ),
        (
            "ta.head_shoulders_pattern_geometry",
            _head_shoulders_pattern_request,
            ("left_shoulder", "neck_left", "head", "neck_right", "right_shoulder"),
        ),
        (
            "ta.triangle_pattern_geometry",
            _triangle_pattern_request,
            ("a", "b", "c", "d"),
        ),
        (
            "ta.cypher_pattern_geometry",
            _cypher_pattern_request,
            ("x", "a", "b", "c", "d"),
        ),
        (
            "ta.three_drives_pattern_geometry",
            _three_drives_pattern_request,
            ("start", "drive1", "retrace_a", "drive2", "retrace_c", "drive3"),
        ),
        (
            "ta.elliott_impulse_wave_geometry",
            _elliott_impulse_wave_request,
            ("start", "wave1", "wave2", "wave3", "wave4", "wave5"),
        ),
        (
            "ta.elliott_correction_wave_geometry",
            _elliott_correction_wave_request,
            ("start", "wave_a", "wave_b", "wave_c"),
        ),
    ),
)
def test_pattern_bound_executor_authenticates_source_and_anchor_availability(
    capability_id, factory, anchor_names
) -> None:
    request = factory()
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            capability_id,
            request,
            _context(
                _series(),
                request.market_as_of,
                source_available_at=request.market_as_of - timedelta(seconds=1),
            ),
        )
    latest_anchor_available_at = max(
        getattr(request, name).available_at for name in anchor_names
    )
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            capability_id,
            request,
            _context(
                _series(),
                request.market_as_of,
                request_available_at=latest_anchor_available_at - timedelta(seconds=1),
                source_available_at=latest_anchor_available_at - timedelta(seconds=2),
            ),
        )


def test_bound_identity_and_cutoff_checks_fail_closed() -> None:
    trendlines = _trendlines_request()
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "model.trendlines",
            trendlines,
            _context(_series(), trendlines.history[-1].closed_at - timedelta(hours=1)),
        )

    sr = _sr_request()
    wrong_sr_series = _series(venue="other-venue")
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "model.sr", sr, _context(wrong_sr_series, sr.closed_bar.closed_at)
        )
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "model.sr",
            sr,
            _context(
                _series(),
                sr.closed_bar.closed_at,
                request_available_at=sr.closed_bar.closed_at - timedelta(minutes=1),
                source_available_at=_START - timedelta(days=1),
            ),
        )

    regression = _regression_request()
    regression_direct = execute_analysis_capability("model.regression", regression)
    regression_cutoff = regression_direct.channel.structural.observed_through
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "model.regression",
            replace(regression, asset="ETHUSDT"),
            _context(_series(), regression_cutoff),
        )
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "model.regression",
            regression,
            _context(_series(), regression_cutoff - timedelta(hours=1)),
        )

    fibonacci = _fibonacci_request()
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "ta.fibonacci_geometry",
            fibonacci,
            _context(_series(), fibonacci.market_as_of + timedelta(hours=1)),
        )

    swing = _swing_request()
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "ta.swing_anchors",
            swing,
            _context(_series(), swing.bars[-1].closed_at - timedelta(hours=1)),
        )

    traditional = _traditional_request()
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "ta.traditional_pivot_geometry",
            traditional,
            _context(_series(), traditional.market_as_of - timedelta(hours=1)),
        )

    vwap = _vwap_request()
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "ta.vwap_geometry",
            vwap,
            _context(_series(), vwap.market_as_of),
        )

    parallel = _parallel_channel_request()
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "ta.parallel_channel_geometry",
            parallel,
            _context(_series(), parallel.market_as_of - timedelta(hours=1)),
        )

    extension = _fibonacci_trend_extension_request()
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "ta.fibonacci_trend_extension_geometry",
            extension,
            _context(_series(), extension.market_as_of - timedelta(hours=1)),
        )

    anchored_path = _anchored_vwap_path_request()
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "ta.anchored_vwap_path",
            anchored_path,
            _context(
                _series(),
                anchored_path.market_as_of,
                volume_unit="base_asset",
                source_available_at=anchored_path.market_as_of - timedelta(minutes=1),
            ),
        )


def test_source_availability_before_each_required_native_fact_rejects() -> None:
    trendlines = _trendlines_request()
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "model.trendlines",
            trendlines,
            _context(
                _series(),
                trendlines.history[-1].closed_at,
                source_available_at=trendlines.history[-1].closed_at
                - timedelta(minutes=1),
            ),
        )

    sr = _sr_request()
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "model.sr",
            sr,
            _context(
                _series(),
                sr.closed_bar.closed_at,
                source_available_at=sr.closed_bar.closed_at - timedelta(minutes=1),
            ),
        )

    regression = _regression_request()
    regression_direct = execute_analysis_capability("model.regression", regression)
    regression_cutoff = regression_direct.channel.structural.observed_through
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "model.regression",
            regression,
            _context(
                _series(),
                regression_cutoff,
                source_available_at=regression_cutoff - timedelta(minutes=1),
            ),
        )

    fibonacci = _fibonacci_request()
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "ta.fibonacci_geometry",
            fibonacci,
            _context(
                _series(),
                fibonacci.market_as_of,
                source_available_at=fibonacci.end_anchor.available_at
                - timedelta(minutes=1),
            ),
        )

    swing = _swing_request()
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "ta.swing_anchors",
            swing,
            _context(
                _series(),
                swing.bars[-1].closed_at,
                source_available_at=swing.bars[-1].closed_at - timedelta(minutes=1),
            ),
        )

    traditional = _traditional_request()
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "ta.traditional_pivot_geometry",
            traditional,
            _context(
                _series(),
                traditional.market_as_of,
                source_available_at=traditional.reference.closed_at
                - timedelta(minutes=1),
            ),
        )

    vwap = _vwap_request()
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "ta.vwap_geometry",
            vwap,
            _context(
                _series(),
                vwap.market_as_of,
                source_available_at=vwap.bars[-1].closed_at - timedelta(minutes=1),
                volume_unit="base_asset",
            ),
        )

    parallel = _parallel_channel_request()
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "ta.parallel_channel_geometry",
            parallel,
            _context(
                _series(),
                parallel.market_as_of,
                source_available_at=parallel.market_as_of - timedelta(minutes=1),
            ),
        )

    extension = _fibonacci_trend_extension_request()
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "ta.fibonacci_trend_extension_geometry",
            extension,
            _context(
                _series(),
                extension.market_as_of,
                source_available_at=extension.retracement_anchor.available_at
                - timedelta(minutes=1),
            ),
        )

    anchored_path = _anchored_vwap_path_request()
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "ta.anchored_vwap_path",
            anchored_path,
            _context(
                _series(),
                anchored_path.market_as_of,
                source_available_at=anchored_path.market_as_of - timedelta(minutes=1),
                volume_unit="base_asset",
            ),
        )


def test_source_availability_at_or_after_native_fact_is_valid() -> None:
    trendlines = _trendlines_request()
    cutoff = trendlines.history[-1].closed_at
    exact = execute_bound_analysis_capability(
        "model.trendlines",
        trendlines,
        _context(_series(), cutoff, source_available_at=cutoff),
    )
    later = execute_bound_analysis_capability(
        "model.trendlines",
        trendlines,
        _context(
            _series(),
            cutoff,
            request_available_at=cutoff + timedelta(hours=2),
            source_available_at=cutoff + timedelta(hours=1),
        ),
    )
    assert exact.result == later.result

    fibonacci = _fibonacci_request()
    fib_source_time = fibonacci.end_anchor.available_at
    fib_bound = execute_bound_analysis_capability(
        "ta.fibonacci_geometry",
        fibonacci,
        _context(
            _series(),
            fibonacci.market_as_of,
            source_available_at=fib_source_time,
        ),
    )
    assert fib_bound.result.market_as_of == fibonacci.market_as_of

    traditional = _traditional_request()
    traditional_bound = execute_bound_analysis_capability(
        "ta.traditional_pivot_geometry",
        traditional,
        _context(
            _series(),
            traditional.market_as_of,
            source_available_at=traditional.reference.closed_at,
        ),
    )
    assert traditional_bound.result.market_as_of == traditional.market_as_of

    parallel = _parallel_channel_request()
    parallel_bound = execute_bound_analysis_capability(
        "ta.parallel_channel_geometry",
        parallel,
        _context(_series(), parallel.market_as_of),
    )
    assert parallel_bound.result.market_as_of == parallel.market_as_of

    extension = _fibonacci_trend_extension_request()
    extension_bound = execute_bound_analysis_capability(
        "ta.fibonacci_trend_extension_geometry",
        extension,
        _context(_series(), extension.market_as_of),
    )
    assert extension_bound.result.market_as_of == extension.market_as_of

    anchored_path = _anchored_vwap_path_request()
    anchored_path_bound = execute_bound_analysis_capability(
        "ta.anchored_vwap_path",
        anchored_path,
        _context(_series(), anchored_path.market_as_of, volume_unit="base_asset"),
    )
    assert anchored_path_bound.result.market_as_of == anchored_path.market_as_of


def test_regression_effective_window_size_closes_native_hash_collision() -> None:
    request_20 = _regression_request()
    request_19 = replace(
        request_20,
        config=replace(request_20.config, window_size=19),
    )
    direct_20 = execute_analysis_capability("model.regression", request_20)
    direct_19 = execute_analysis_capability("model.regression", request_19)
    assert request_20.config.config_hash == request_19.config.config_hash
    assert direct_20 != direct_19

    cutoff = direct_20.channel.structural.observed_through
    bound_20 = execute_bound_analysis_capability(
        "model.regression",
        request_20,
        _context(_series(), cutoff),
    )
    bound_19 = execute_bound_analysis_capability(
        "model.regression",
        request_19,
        _context(_series(), cutoff),
    )
    assert bound_20.result == direct_20
    assert bound_19.result == direct_19
    assert bound_20.parameter_fingerprint != bound_19.parameter_fingerprint
    assert bound_20.parameter_identity[-1] == ("window_size", "20")
    assert bound_19.parameter_identity[-1] == ("window_size", "19")
    assert bound_20.result.channel.structural.window_size == 20
    assert bound_19.result.channel.structural.window_size == 19


def test_sr_previous_state_is_fingerprinted_separately_from_parameters() -> None:
    key = SRStateKey(venue="binance", symbol="BTCUSDT", timeframe="1h")
    config = _sr_config(key)
    initial = create_initial_state(key, config)
    first = execute_analysis_capability(
        "model.sr",
        _sr_request(config=config, previous_state=initial, index=0),
    )
    request_initial = _sr_request(
        config=config,
        previous_state=initial,
        index=1,
    )
    request_after_first = _sr_request(
        config=config,
        previous_state=first.next_state,
        index=1,
    )
    context = _context(_series(), request_initial.closed_bar.closed_at)
    initial_bound = execute_bound_analysis_capability(
        "model.sr", request_initial, context
    )
    threaded_bound = execute_bound_analysis_capability(
        "model.sr", request_after_first, context
    )

    assert initial_bound.parameter_fingerprint == threaded_bound.parameter_fingerprint
    assert initial_bound.state_fingerprint != threaded_bound.state_fingerprint
    assert initial_bound.result != threaded_bound.result


def test_parameter_identity_changes_only_when_native_parameters_change() -> None:
    swing_one = _swing_request(span=1)
    swing_two = _swing_request(span=2)
    swing_one_bound = execute_bound_analysis_capability(
        "ta.swing_anchors",
        swing_one,
        _context(_series(), swing_one.bars[-1].closed_at),
    )
    swing_two_bound = execute_bound_analysis_capability(
        "ta.swing_anchors",
        swing_two,
        _context(_series(), swing_two.bars[-1].closed_at),
    )
    assert (
        swing_one_bound.parameter_fingerprint != swing_two_bound.parameter_fingerprint
    )

    fib_one = _fibonacci_request(ratios=(0.25,))
    fib_two = _fibonacci_request(ratios=(0.5,))
    fib_one_bound = execute_bound_analysis_capability(
        "ta.fibonacci_geometry",
        fib_one,
        _context(_series(), fib_one.market_as_of),
    )
    fib_two_bound = execute_bound_analysis_capability(
        "ta.fibonacci_geometry",
        fib_two,
        _context(_series(), fib_two.market_as_of),
    )
    assert fib_one_bound.parameter_fingerprint != fib_two_bound.parameter_fingerprint

    extension_one = _fibonacci_trend_extension_request()
    extension_two = _fibonacci_trend_extension_request()
    extension_two = replace(extension_two, extension_ratios=(1.5, 2.0))
    extension_one_bound = execute_bound_analysis_capability(
        "ta.fibonacci_trend_extension_geometry",
        extension_one,
        _context(_series(), extension_one.market_as_of),
    )
    extension_two_bound = execute_bound_analysis_capability(
        "ta.fibonacci_trend_extension_geometry",
        extension_two,
        _context(_series(), extension_two.market_as_of),
    )
    assert (
        extension_one_bound.parameter_fingerprint
        != extension_two_bound.parameter_fingerprint
    )

    key = SRStateKey(venue="binance", symbol="BTCUSDT", timeframe="1h")
    sr_one = _sr_request(config=_sr_config(key, pivot_span_bars=1))
    sr_two = _sr_request(config=_sr_config(key, pivot_span_bars=2))
    sr_one_bound = execute_bound_analysis_capability(
        "model.sr", sr_one, _context(_series(), sr_one.closed_bar.closed_at)
    )
    sr_two_bound = execute_bound_analysis_capability(
        "model.sr", sr_two, _context(_series(), sr_two.closed_bar.closed_at)
    )
    assert sr_one_bound.parameter_fingerprint != sr_two_bound.parameter_fingerprint

    traditional = _traditional_request()
    vwap = _vwap_request()
    traditional_bound = execute_bound_analysis_capability(
        "ta.traditional_pivot_geometry",
        traditional,
        _context(_series(), traditional.market_as_of),
    )
    vwap_bound = execute_bound_analysis_capability(
        "ta.vwap_geometry",
        vwap,
        _context(_series(), vwap.market_as_of, volume_unit="quote_asset"),
    )
    assert traditional_bound.parameter_identity == ()
    assert vwap_bound.parameter_identity == ()
    assert traditional_bound.parameter_fingerprint != vwap_bound.parameter_fingerprint
