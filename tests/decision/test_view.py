from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.decision_app.domain.contracts import InputReadCursor, LaneCommitWatermark
from apps.decision_app.domain.market_state import (
    BarStore,
    MarketSeriesKey,
    TimeframeGrid,
    compile_bar_store_capacities,
)
from apps.decision_app.domain.view import (
    DecisionViewBuilder,
    LaneMarketView,
    MarketViewNotReadyError,
)
from apps.decision_app.planning.catalog import PluginCatalog
from apps.decision_app.planning.planner import (
    DecisionLaneSpec,
    ModelBindingSpec,
    compile_decision_plan,
)
from apps.decision_app.planning.readiness import compile_lane_market_requirements
from libs.contracts.decision import CausalBarView, ModelSpec, WarmupRequirements

BASE = datetime(2026, 1, 5, tzinfo=UTC)


def make_grid() -> TimeframeGrid:
    return TimeframeGrid(
        alignment_origin=BASE,
        durations={
            "1m": timedelta(minutes=1),
            "1h": timedelta(hours=1),
            "4h": timedelta(hours=4),
        },
    )


def make_bar(
    timeframe: str,
    start: datetime,
    duration: timedelta,
    *,
    value: Decimal = Decimal(100),
    volume: Decimal = Decimal(10),
    taker_buy_base: Decimal | None = Decimal(4),
) -> CausalBarView:
    close = start + duration
    return CausalBarView(
        timeframe=timeframe,
        bar_open_at=start,
        bar_close_at=close,
        market_as_of=close,
        open=value,
        high=value + Decimal(2),
        low=value - Decimal(2),
        close=value + Decimal(1),
        volume=volume,
        taker_buy_base=taker_buy_base,
        closed=True,
    )


def make_plan(
    *,
    decision_timeframe: str,
    trigger_timeframe: str,
    warmup: dict[str, int] | None = None,
):
    spec = ModelSpec(
        name="Model",
        version="1",
        stateful=False,
        output_kind="analytical",
        produces_artifact_type="model.v1",
        warmup_requirements=WarmupRequirements(bars_by_timeframe=warmup or {}),
    )
    lane = DecisionLaneSpec(
        lane_id=f"BTCUSDT:{decision_timeframe}",
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        decision_timeframe=decision_timeframe,
        trigger_timeframe=trigger_timeframe,
        trigger_mode="on_bar_close",
        policy_name="default",
        policy_version="1",
        authority="authoritative",
        risk_profile_key="btc-default",
        bindings=(
            ModelBindingSpec(
                slot_name="model",
                plugin_name="Model",
                plugin_version="1",
            ),
        ),
    )
    return compile_decision_plan(PluginCatalog([spec]), [lane])


def make_builder(plan):
    grid = make_grid()
    requirements = compile_lane_market_requirements(plan.lanes[0], grid)
    store = BarStore(compile_bar_store_capacities(plan, grid))
    return store, requirements, grid, DecisionViewBuilder(store, grid)


def progress(market_as_of: datetime, lane_id: str):
    return {
        "input_read_cursor": InputReadCursor(
            stream_key="offline:BTCUSDT",
            latest_market_as_of=market_as_of,
        ),
        "lane_commit_watermark": LaneCommitWatermark(lane_id=lane_id),
    }


def test_direct_view_uses_canonical_closed_decision_bar() -> None:
    plan = make_plan(decision_timeframe="1h", trigger_timeframe="1h")
    store, requirements, grid, builder = make_builder(plan)
    canonical = make_bar("1h", BASE + timedelta(hours=10), timedelta(hours=1))
    store.append(requirements.decision_series, canonical)
    view = builder.build_direct(
        plan.lanes[0],
        requirements,
        BASE + timedelta(hours=11),
        **progress(BASE + timedelta(hours=11), plan.lanes[0].lane_id),
    )
    assert view.decision_bar is canonical
    assert view.decision_bar.closed is True
    assert view.decision_bar.market_as_of == BASE + timedelta(hours=11)
    assert view.causal_bar_views["1h"] == (canonical,)
    assert view.decision_bar_closed is True
    assert grid.is_boundary("1h", view.market_as_of)


def test_projected_view_is_causal_decimal_and_does_not_write_back() -> None:
    plan = make_plan(decision_timeframe="4h", trigger_timeframe="1m")
    store, requirements, _, builder = make_builder(plan)
    decision_history = make_bar("4h", BASE + timedelta(hours=4), timedelta(hours=4))
    store.append(requirements.decision_series, decision_history)
    for index in range(120):
        start = BASE + timedelta(hours=8, minutes=index)
        store.append(
            requirements.trigger_series,
            make_bar(
                "1m",
                start,
                timedelta(minutes=1),
                value=Decimal(100 + index),
                volume=Decimal("0.1"),
                taker_buy_base=None if index == 5 else Decimal("0.04"),
            ),
        )
    before_count = store.retained_count(requirements.decision_series)
    market_as_of = BASE + timedelta(hours=10)
    view = builder.build_projected(
        plan.lanes[0],
        requirements,
        market_as_of,
        **progress(market_as_of, plan.lanes[0].lane_id),
    )
    assert view.decision_bar.closed is False
    assert view.decision_bar.bar_open_at == BASE + timedelta(hours=8)
    assert view.decision_bar.bar_close_at == BASE + timedelta(hours=12)
    assert view.decision_bar.market_as_of == market_as_of
    assert view.decision_bar.market_as_of < view.decision_bar.bar_close_at
    assert view.decision_bar.open == Decimal(100)
    assert view.decision_bar.close == Decimal(220)
    assert view.decision_bar.high == Decimal(221)
    assert view.decision_bar.low == Decimal(98)
    assert view.decision_bar.volume == Decimal("12.0")
    assert view.decision_bar.taker_buy_base is None
    assert store.retained_count(requirements.decision_series) == before_count
    assert all(bar.closed for bar in view.causal_bar_views["4h"])
    assert all(bar.market_as_of <= market_as_of for bar in view.causal_bar_views["1m"])


def test_future_trigger_bars_are_excluded_and_exact_boundary_requires_canonical_htf() -> (
    None
):
    plan = make_plan(decision_timeframe="4h", trigger_timeframe="1m")
    store, requirements, _, builder = make_builder(plan)
    for index in range(240):
        start = BASE + timedelta(hours=8, minutes=index)
        store.append(
            requirements.trigger_series, make_bar("1m", start, timedelta(minutes=1))
        )
    for index in range(4):
        start = BASE + timedelta(hours=12, minutes=index)
        store.append(
            requirements.trigger_series, make_bar("1m", start, timedelta(minutes=1))
        )
    boundary = BASE + timedelta(hours=12)
    with pytest.raises(MarketViewNotReadyError, match="DEGRADED"):
        builder.build(
            plan.lanes[0],
            requirements,
            boundary,
            **progress(boundary, plan.lanes[0].lane_id),
        )
    canonical = make_bar("4h", BASE + timedelta(hours=8), timedelta(hours=4))
    store.append(requirements.decision_series, canonical)
    view = builder.build(
        plan.lanes[0],
        requirements,
        boundary,
        **progress(boundary, plan.lanes[0].lane_id),
    )
    assert view.decision_bar is canonical
    assert view.decision_bar_closed is True
    assert view.causal_bar_views["1m"][-1].market_as_of == boundary
    assert view.causal_bar_views["1m"][-1].bar_open_at == BASE + timedelta(
        hours=11, minutes=59
    )


def test_lane_market_view_nested_values_are_immutable() -> None:
    plan = make_plan(decision_timeframe="1h", trigger_timeframe="1h")
    store, requirements, _, builder = make_builder(plan)
    bar = make_bar("1h", BASE, timedelta(hours=1))
    store.append(requirements.decision_series, bar)
    view = builder.build_direct(
        plan.lanes[0],
        requirements,
        BASE + timedelta(hours=1),
        **progress(BASE + timedelta(hours=1), plan.lanes[0].lane_id),
    )
    assert isinstance(view, LaneMarketView)
    with pytest.raises((AttributeError, TypeError)):
        view.causal_bar_views._data = {}  # type: ignore[attr-defined]
    with pytest.raises((AttributeError, TypeError)):
        view.provenance["new"] = "value"  # type: ignore[index]


def test_cross_timeframe_arrival_order_produces_same_view() -> None:
    plan = make_plan(
        decision_timeframe="1h",
        trigger_timeframe="1h",
        warmup={"4h": 1},
    )
    grid = make_grid()
    requirements = compile_lane_market_requirements(plan.lanes[0], grid)
    capacities = compile_bar_store_capacities(plan, grid)
    first_store = BarStore(capacities)
    second_store = BarStore(capacities)
    one_hour = make_bar("1h", BASE + timedelta(hours=11), timedelta(hours=1))
    four_hour = make_bar("4h", BASE + timedelta(hours=8), timedelta(hours=4))
    one_hour_key = requirements.decision_series
    four_hour_key = MarketSeriesKey(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        timeframe="4h",
    )
    first_store.append(one_hour_key, one_hour)
    first_store.append(four_hour_key, four_hour)
    second_store.append(four_hour_key, four_hour)
    second_store.append(one_hour_key, one_hour)
    first_view = DecisionViewBuilder(first_store, grid).build(
        plan.lanes[0],
        requirements,
        BASE + timedelta(hours=12),
        **progress(BASE + timedelta(hours=12), plan.lanes[0].lane_id),
    )
    second_view = DecisionViewBuilder(second_store, grid).build(
        plan.lanes[0],
        requirements,
        BASE + timedelta(hours=12),
        **progress(BASE + timedelta(hours=12), plan.lanes[0].lane_id),
    )
    assert first_view == second_view


def test_shared_capacity_does_not_expand_lane_visible_history() -> None:
    grid = make_grid()
    model_a = ModelSpec(
        name="ModelA",
        version="1",
        stateful=False,
        output_kind="analytical",
        produces_artifact_type="model.a.v1",
        warmup_requirements=WarmupRequirements(bars_by_timeframe={"1h": 1}),
    )
    model_b = ModelSpec(
        name="ModelB",
        version="1",
        stateful=False,
        output_kind="analytical",
        produces_artifact_type="model.b.v1",
        warmup_requirements=WarmupRequirements(bars_by_timeframe={"1h": 20}),
    )

    def lane(lane_id: str, plugin_name: str, authority: str, risk: str | None):
        return DecisionLaneSpec(
            lane_id=lane_id,
            asset="BTCUSDT",
            venue="binance",
            instrument_id="BTC-USDT-PERP",
            decision_timeframe="1h",
            trigger_timeframe="1h",
            trigger_mode="on_bar_close",
            policy_name="default",
            policy_version="1",
            authority=authority,  # type: ignore[arg-type]
            risk_profile_key=risk,
            bindings=(
                ModelBindingSpec(
                    slot_name="model",
                    plugin_name=plugin_name,
                    plugin_version="1",
                ),
            ),
        )

    combined_plan = compile_decision_plan(
        PluginCatalog([model_a, model_b]),
        [
            lane("BTCUSDT:1h:short", "ModelA", "authoritative", "btc-short"),
            lane("BTCUSDT:1h:long", "ModelB", "shadow", None),
        ],
    )
    long_lane = next(
        lane for lane in combined_plan.lanes if lane.lane_id.endswith(":long")
    )
    short_lane = next(
        lane for lane in combined_plan.lanes if lane.lane_id.endswith(":short")
    )
    short_requirements = compile_lane_market_requirements(short_lane, grid)
    long_requirements = compile_lane_market_requirements(long_lane, grid)
    combined_store = BarStore(compile_bar_store_capacities(combined_plan, grid))
    bars = [
        make_bar(
            "1h",
            BASE + timedelta(hours=index),
            timedelta(hours=1),
            value=Decimal(100 + index),
        )
        for index in range(20)
    ]
    for bar in bars:
        combined_store.append(short_requirements.decision_series, bar)

    market_as_of = BASE + timedelta(hours=20)
    short_view = DecisionViewBuilder(combined_store, grid).build(
        short_lane,
        short_requirements,
        market_as_of,
        **progress(market_as_of, short_lane.lane_id),
    )
    long_view = DecisionViewBuilder(combined_store, grid).build(
        long_lane,
        long_requirements,
        market_as_of,
        **progress(market_as_of, long_lane.lane_id),
    )
    assert combined_store.capacity_for(short_requirements.decision_series) == 20
    assert len(short_view.causal_bar_views["1h"]) == 1
    assert len(long_view.causal_bar_views["1h"]) == 20
    assert short_view.causal_bar_views["1h"] == (bars[-1],)

    short_only_plan = compile_decision_plan(
        PluginCatalog([model_a]),
        [lane("BTCUSDT:1h:short", "ModelA", "authoritative", "btc-short")],
    )
    short_only_requirements = compile_lane_market_requirements(
        short_only_plan.lanes[0],
        grid,
    )
    short_only_store = BarStore(compile_bar_store_capacities(short_only_plan, grid))
    for bar in bars:
        short_only_store.append(short_only_requirements.decision_series, bar)
    short_only_view = DecisionViewBuilder(short_only_store, grid).build(
        short_only_plan.lanes[0],
        short_only_requirements,
        market_as_of,
        **progress(market_as_of, short_only_plan.lanes[0].lane_id),
    )
    assert short_view.causal_bar_views == short_only_view.causal_bar_views
