from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.decision_app.domain.market_state import (
    AppendResult,
    BarConflictError,
    BarOrderError,
    BarStore,
    BarStoreError,
    MarketSeriesKey,
    TimeframeGeometryError,
    TimeframeGrid,
    compile_bar_store_capacities,
)
from apps.decision_app.planning.planner import (
    DecisionLaneSpec,
    ModelBindingSpec,
    compile_decision_plan,
)
from apps.decision_app.planning.readiness import compile_lane_market_requirements
from libs.contracts.decision import CausalBarView, ModelSpec, WarmupRequirements

BASE = datetime(2026, 1, 5, tzinfo=UTC)


def make_bar(
    timeframe: str,
    bar_open_at: datetime,
    duration: timedelta,
    *,
    value: int = 100,
    taker_buy_base: Decimal | None = Decimal(4),
    closed: bool = True,
) -> CausalBarView:
    bar_close_at = bar_open_at + duration

    return CausalBarView(
        timeframe=timeframe,
        bar_open_at=bar_open_at,
        bar_close_at=bar_close_at,
        market_as_of=bar_close_at if closed else bar_open_at + duration / 2,
        open=Decimal(value),
        high=Decimal(value + 2),
        low=Decimal(value - 2),
        close=Decimal(value + 1),
        volume=Decimal(10),
        taker_buy_base=taker_buy_base,
        closed=closed,
    )


def grid(*durations: tuple[str, timedelta]) -> TimeframeGrid:
    return TimeframeGrid(alignment_origin=BASE, durations=dict(durations))


def make_lane(
    *,
    lane_id: str = "BTCUSDT:4h",
    decision_timeframe: str = "4h",
    trigger_timeframe: str = "4h",
    authority: str = "authoritative",
    plugin_name: str = "BoundaryModel",
) -> DecisionLaneSpec:
    return DecisionLaneSpec(
        lane_id=lane_id,
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        decision_timeframe=decision_timeframe,
        trigger_timeframe=trigger_timeframe,
        trigger_mode="on_bar_close",
        policy_name="default",
        policy_version="1",
        authority=authority,  # type: ignore[arg-type]
        risk_profile_key="btc-default" if authority == "authoritative" else None,
        bindings=(
            ModelBindingSpec(
                slot_name="model",
                plugin_name=plugin_name,
                plugin_version="1",
            ),
        ),
    )


def make_model_spec(warmup: dict[str, int] | None = None) -> ModelSpec:
    return ModelSpec(
        name="BoundaryModel",
        version="1",
        stateful=False,
        output_kind="analytical",
        produces_artifact_type="boundary.v1",
        warmup_requirements=WarmupRequirements(bars_by_timeframe=warmup or {}),
    )


def test_market_series_key_is_hashable_and_identity_is_shared() -> None:
    first = MarketSeriesKey(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        timeframe="1h",
    )
    second = MarketSeriesKey(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        timeframe="1h",
    )
    assert first == second
    assert hash(first) == hash(second)
    assert {first: "shared"}[second] == "shared"
    with pytest.raises(ValueError, match="non-empty"):
        MarketSeriesKey(
            asset="",
            venue="binance",
            instrument_id="BTC-USDT-PERP",
            timeframe="1h",
        )


def test_timeframe_grid_is_explicit_and_utc_aligned() -> None:
    hourly = grid(("1h", timedelta(hours=1)), ("4h", timedelta(hours=4)))
    assert hourly.expected_closed_cutoff("4h", BASE + timedelta(hours=3)) == BASE
    assert hourly.expected_closed_cutoff(
        "4h", BASE + timedelta(hours=4)
    ) == BASE + timedelta(hours=4)
    assert hourly.bucket_bounds("4h", BASE + timedelta(hours=5)) == (
        BASE + timedelta(hours=4),
        BASE + timedelta(hours=8),
    )
    assert hourly.is_boundary("4h", BASE + timedelta(hours=4))
    with pytest.raises(TimeframeGeometryError, match="unknown timeframe"):
        hourly.duration("15m")
    with pytest.raises(ValueError, match="positive"):
        TimeframeGrid(
            alignment_origin=BASE,
            durations={"1h": timedelta(0)},
        )
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        TimeframeGrid(
            alignment_origin=BASE.replace(tzinfo=None),
            durations={"1h": timedelta(hours=1)},
        )


def test_weekly_grid_uses_the_explicit_monday_origin() -> None:
    weekly_origin = datetime(2026, 1, 5, tzinfo=UTC)
    weekly = TimeframeGrid(
        alignment_origin=weekly_origin,
        durations={"1w": timedelta(days=7)},
    )
    sunday = datetime(2026, 1, 11, 23, 0, tzinfo=UTC)
    monday = datetime(2026, 1, 12, tzinfo=UTC)
    assert weekly.expected_closed_cutoff("1w", sunday) == weekly_origin
    assert weekly.bucket_bounds("1w", monday) == (
        monday,
        monday + timedelta(days=7),
    )


def test_bar_store_accepts_only_forward_closed_canonical_bars() -> None:
    key = MarketSeriesKey(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        timeframe="1h",
    )
    store = BarStore({key: 3})
    first = make_bar("1h", BASE, timedelta(hours=1))
    second = make_bar("1h", BASE + timedelta(hours=1), timedelta(hours=1), value=101)
    assert store.append(key, first) is AppendResult.INSERTED
    assert store.append(key, first) is AppendResult.DUPLICATE
    assert store.append(key, second) is AppendResult.INSERTED

    with pytest.raises(BarConflictError):
        store.append(
            key,
            make_bar("1h", BASE + timedelta(hours=1), timedelta(hours=1), value=200),
        )
    with pytest.raises(BarOrderError):
        store.append(key, make_bar("1h", BASE, timedelta(hours=1), value=99))
    with pytest.raises(BarOrderError):
        store.append(
            key,
            make_bar("1h", BASE + timedelta(minutes=30), timedelta(hours=1), value=102),
        )
    with pytest.raises(BarStoreError, match="closed"):
        store.append(
            key,
            make_bar(
                "1h",
                BASE + timedelta(hours=2),
                timedelta(hours=1),
                closed=False,
            ),
        )
    with pytest.raises(BarStoreError, match="timeframe"):
        store.append(key, make_bar("4h", BASE + timedelta(hours=2), timedelta(hours=4)))


def test_bar_store_is_bounded_and_queries_are_causal_immutable_tuples() -> None:
    key = MarketSeriesKey(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        timeframe="1h",
    )
    store = BarStore({key: 2})
    store.append_many(
        key,
        (
            make_bar("1h", BASE, timedelta(hours=1)),
            make_bar("1h", BASE + timedelta(hours=1), timedelta(hours=1), value=101),
            make_bar("1h", BASE + timedelta(hours=2), timedelta(hours=1), value=102),
        ),
    )
    retained = store.bars_at(key, BASE + timedelta(hours=3))
    assert len(retained) == 2
    assert retained[0].bar_open_at == BASE + timedelta(hours=1)
    assert store.retained_count(key) == 2
    assert store.latest_at_or_before(key, BASE + timedelta(hours=2)) == retained[0]
    assert len(store.bars_at(key, BASE + timedelta(hours=3), limit=1)) == 1
    assert isinstance(retained, tuple)
    with pytest.raises(AttributeError):
        retained.append(retained[-1])  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="positive"):
        store.bars_at(key, BASE, limit=0)


def test_capacity_plan_uses_shared_max_and_projection_ratio() -> None:
    from apps.decision_app.planning.catalog import PluginCatalog

    first_spec = ModelSpec(
        name="BoundaryModel",
        version="1",
        stateful=False,
        output_kind="analytical",
        produces_artifact_type="boundary.v1",
        warmup_requirements=WarmupRequirements(bars_by_timeframe={"1h": 8}),
    )
    second_spec = ModelSpec(
        name="ShadowModel",
        version="1",
        stateful=False,
        output_kind="analytical",
        produces_artifact_type="boundary.v1",
        warmup_requirements=WarmupRequirements(bars_by_timeframe={"1h": 20}),
    )
    catalog = PluginCatalog([first_spec, second_spec])
    first = make_lane(
        lane_id="BTCUSDT:4h-primary",
        decision_timeframe="4h",
        trigger_timeframe="1m",
        plugin_name="BoundaryModel",
    )
    second = make_lane(
        lane_id="BTCUSDT:4h-shadow",
        decision_timeframe="4h",
        trigger_timeframe="1m",
        authority="shadow",
        plugin_name="ShadowModel",
    )
    plan = compile_decision_plan(catalog, [second, first])
    capacities = compile_bar_store_capacities(
        plan,
        grid(
            ("1m", timedelta(minutes=1)),
            ("1h", timedelta(hours=1)),
            ("4h", timedelta(hours=4)),
        ),
    )
    one_minute = MarketSeriesKey(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        timeframe="1m",
    )
    one_hour = one_minute.__class__(
        asset=one_minute.asset,
        venue=one_minute.venue,
        instrument_id=one_minute.instrument_id,
        timeframe="1h",
    )
    assert capacities[one_minute] == 240
    assert capacities[one_hour] == 20
    assert len(capacities) == 3


def test_projection_capacity_requires_short_integral_trigger_geometry() -> None:
    from apps.decision_app.planning.catalog import PluginCatalog

    catalog = PluginCatalog([make_model_spec()])
    with pytest.raises(TimeframeGeometryError, match="shorter"):
        compile_bar_store_capacities(
            compile_decision_plan(
                catalog,
                [
                    make_lane(
                        decision_timeframe="1h",
                        trigger_timeframe="4h",
                    )
                ],
            ),
            grid(("1h", timedelta(hours=1)), ("4h", timedelta(hours=4))),
        )

    with pytest.raises(TimeframeGeometryError, match="integer multiple"):
        compile_bar_store_capacities(
            compile_decision_plan(
                catalog,
                [
                    make_lane(
                        decision_timeframe="4h",
                        trigger_timeframe="90m",
                    )
                ],
            ),
            grid(("90m", timedelta(minutes=90)), ("4h", timedelta(hours=4))),
        )


def test_zero_warmup_does_not_create_or_raise_a_required_series() -> None:
    from apps.decision_app.planning.catalog import PluginCatalog

    zero_other = compile_decision_plan(
        PluginCatalog([make_model_spec({"4h": 0})]),
        [
            make_lane(
                lane_id="BTCUSDT:1h-zero-other",
                decision_timeframe="1h",
                trigger_timeframe="1h",
            )
        ],
    )
    grid_1h_4h = grid(("1h", timedelta(hours=1)), ("4h", timedelta(hours=4)))
    requirements = compile_lane_market_requirements(
        zero_other.lanes[0],
        grid_1h_4h,
    )
    assert all(key.timeframe != "4h" for key in requirements.minimum_bars_by_series)
    capacities = compile_bar_store_capacities(zero_other, grid_1h_4h)
    assert all(key.timeframe != "4h" for key in capacities)

    zero_base = compile_decision_plan(
        PluginCatalog([make_model_spec({"1h": 0})]),
        [
            make_lane(
                lane_id="BTCUSDT:1h-zero-base",
                decision_timeframe="1h",
                trigger_timeframe="1h",
            )
        ],
    )
    base_requirements = compile_lane_market_requirements(
        zero_base.lanes[0],
        grid_1h_4h,
    )
    base_capacities = compile_bar_store_capacities(zero_base, grid_1h_4h)
    assert dict(base_requirements.minimum_bars_by_series) == {
        base_requirements.decision_series: 1
    }
    assert dict(base_capacities) == {base_requirements.decision_series: 1}
