from datetime import UTC, datetime, timedelta

from libs.analysis_capabilities.execution import execute_analysis_capability
from libs.analysis_capabilities.execution.sr import SRExecutionRequest, execute_sr
from libs.analysis_capabilities.execution.trendlines import (
    TrendlinesExecutionRequest,
    execute_trendlines,
)
from libs.analysis_capabilities.ta.swing_anchors import (
    SwingAnchorBar,
    SwingAnchorRequest,
    compute_swing_anchors,
)
from libs.models.sr import (
    AssociationConfig,
    ClosedBar,
    DetectionConfig,
    LifecycleConfig,
    ResolvedSRConfig,
    RuntimeConfig,
    SREngine,
    SRStateKey,
    create_initial_state,
)
from libs.models.trendlines import TrendlineBar, analyze_trendlines

START = datetime(2026, 9, 10, tzinfo=UTC)


def _trendline_history() -> tuple[TrendlineBar, ...]:
    return tuple(
        TrendlineBar(
            closed_at=START + timedelta(hours=index),
            open=100.0 + ((index % 8) - 3) * 2 + (index // 8) * 0.1 + 1,
            high=100.0 + ((index % 8) - 3) * 2 + (index // 8) * 0.1 + 3,
            low=100.0 + ((index % 8) - 3) * 2 + (index // 8) * 0.1 - 3,
            close=100.0 + ((index % 8) - 3) * 2 + (index // 8) * 0.1 + 0.5,
        )
        for index in range(30)
    )


def test_nonempty_trendlines_adapter_and_dispatcher_have_exact_parity() -> None:
    history = _trendline_history()
    request = TrendlinesExecutionRequest(history)
    direct = analyze_trendlines(history)

    assert direct.support.structural is not None
    assert direct.support.secondary is not None
    assert direct.resistance.structural is not None
    assert direct.resistance.secondary is not None
    assert execute_trendlines(request) == direct
    assert execute_analysis_capability("model.trendlines", request) == direct


def _sr_config(key: SRStateKey) -> ResolvedSRConfig:
    return ResolvedSRConfig.create(
        version="1",
        asset=key.symbol,
        timeframe=key.timeframe,
        detection=DetectionConfig(pivot_span_bars=1, zone_half_width_atr=0.25),
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


def _sr_bar(key: SRStateKey, index: int, close: float) -> ClosedBar:
    return ClosedBar(
        state_key=key,
        bar_id=f"r1-bar-{index}",
        closed_at=START + timedelta(hours=index),
        open=close - 0.5,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        atr_at_close=1.0,
    )


def test_nonempty_sr_adapter_and_dispatcher_have_exact_stateful_parity() -> None:
    key = SRStateKey(venue="binance", symbol="BTCUSDT", timeframe="1h")
    config = _sr_config(key)
    state = create_initial_state(key, config)
    engine = SREngine()
    saw_zone = False
    saw_event = False
    for index, close in enumerate((100, 105, 102, 108, 103, 107, 101, 109, 102)):
        bar = _sr_bar(key, index, close)
        direct = engine.step(state, bar, config)
        request = SRExecutionRequest(state, bar, config)
        adapted = execute_sr(request)
        dispatched = execute_analysis_capability("model.sr", request)
        assert (adapted.next_state, adapted.snapshot, adapted.events) == direct
        assert dispatched == adapted
        saw_zone = saw_zone or bool(adapted.snapshot.zones)
        saw_event = saw_event or bool(adapted.events)
        state = adapted.next_state
    assert saw_zone
    assert saw_event


def test_swing_prefixes_equal_the_available_subset_of_full_history() -> None:
    bars = tuple(
        SwingAnchorBar(
            START + timedelta(hours=index),
            high,
            low,
        )
        for index, (high, low) in enumerate(
            ((10, 5), (20, 8), (12, 6), (11, 1), (13, 7), (22, 9), (14, 4))
        )
    )
    full = compute_swing_anchors(SwingAnchorRequest(bars, span=1))
    for end in range(2, len(bars) + 1):
        prefix = bars[:end]
        snapshot = compute_swing_anchors(SwingAnchorRequest(prefix, span=1))
        expected = tuple(
            anchor
            for anchor in full.anchors
            if anchor.available_at <= snapshot.market_as_of
        )
        assert snapshot.anchors == expected
