from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.decision_app.catalog import PluginCatalog
from apps.decision_app.contracts import InputReadCursor, LaneCommitWatermark
from apps.decision_app.market_state import (
    BarStore,
    MarketSeriesKey,
    TimeframeGeometryError,
    TimeframeGrid,
    compile_bar_store_capacities,
)
from apps.decision_app.planner import (
    DecisionLaneSpec,
    ModelBindingSpec,
    compile_decision_plan,
)
from apps.decision_app.readiness import (
    LaneMarketRequirements,
    LaneReadinessEvaluator,
    compile_lane_market_requirements,
)
from libs.contracts.decision import CausalBarView, ModelSpec, WarmupRequirements

BASE = datetime(2026, 1, 5, tzinfo=UTC)


def make_bar(
    timeframe: str,
    start: datetime,
    duration: timedelta,
    *,
    value: int = 100,
) -> CausalBarView:
    close = start + duration
    return CausalBarView(
        timeframe=timeframe,
        bar_open_at=start,
        bar_close_at=close,
        market_as_of=close,
        open=Decimal(value),
        high=Decimal(value + 2),
        low=Decimal(value - 2),
        close=Decimal(value + 1),
        volume=Decimal(10),
        taker_buy_base=Decimal(4),
        closed=True,
    )


def make_grid() -> TimeframeGrid:
    return TimeframeGrid(
        alignment_origin=BASE,
        durations={
            "1m": timedelta(minutes=1),
            "1h": timedelta(hours=1),
            "4h": timedelta(hours=4),
        },
    )


def make_lane(
    *,
    decision_timeframe: str,
    trigger_timeframe: str,
    warmup: dict[str, int] | None = None,
) -> object:
    return DecisionLaneSpec(
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
    return compile_decision_plan(
        PluginCatalog([spec]),
        [
            make_lane(
                decision_timeframe=decision_timeframe,
                trigger_timeframe=trigger_timeframe,
                warmup=warmup,
            )
        ],
    )


def make_store(plan) -> tuple[BarStore, object, object]:
    grid = make_grid()
    requirements = compile_lane_market_requirements(plan.lanes[0], grid)
    store = BarStore(compile_bar_store_capacities(plan, grid))
    return store, requirements, grid


def evaluate(plan, requirements, store, grid, market_as_of):
    return LaneReadinessEvaluator.evaluate(
        plan.lanes[0],
        requirements,
        store,
        grid,
        market_as_of,
        InputReadCursor(
            stream_key="offline:BTCUSDT",
            latest_market_as_of=market_as_of,
        ),
        LaneCommitWatermark(lane_id=plan.lanes[0].lane_id),
    )


def test_direct_lane_is_live_only_at_its_canonical_cutoff() -> None:
    plan = make_plan(decision_timeframe="1h", trigger_timeframe="1h")
    store, requirements, grid = make_store(plan)
    key = requirements.decision_series
    store.append(key, make_bar("1h", BASE + timedelta(hours=10), timedelta(hours=1)))
    readiness = evaluate(plan, requirements, store, grid, BASE + timedelta(hours=11))
    assert readiness.state == "LIVE"
    assert readiness.required_cutoff == BASE + timedelta(hours=11)

    inside = evaluate(
        plan,
        requirements,
        store,
        grid,
        BASE + timedelta(hours=11, minutes=30),
    )
    assert inside.state == "DEGRADED"
    assert "1h:boundary" in inside.missing_inputs


def test_insufficient_history_is_warming() -> None:
    plan = make_plan(decision_timeframe="1h", trigger_timeframe="1h", warmup={"1h": 3})
    store, requirements, grid = make_store(plan)
    store.append(
        requirements.decision_series,
        make_bar("1h", BASE + timedelta(hours=10), timedelta(hours=1)),
    )
    readiness = evaluate(plan, requirements, store, grid, BASE + timedelta(hours=11))
    assert readiness.state == "WARMING"
    assert "1h:history" in readiness.missing_inputs


def test_sufficient_old_history_but_missing_expected_cutoff_is_degraded() -> None:
    plan = make_plan(decision_timeframe="1h", trigger_timeframe="1h")
    store, requirements, grid = make_store(plan)
    store.append(
        requirements.decision_series,
        make_bar("1h", BASE + timedelta(hours=9), timedelta(hours=1)),
    )
    store.append(
        requirements.decision_series,
        make_bar("1h", BASE + timedelta(hours=10), timedelta(hours=1), value=101),
    )
    readiness = evaluate(plan, requirements, store, grid, BASE + timedelta(hours=12))
    assert readiness.state == "DEGRADED"
    assert "1h:cutoff" in readiness.missing_inputs


def test_4h_context_uses_exact_expected_cutoff_not_arrival_order() -> None:
    plan = make_plan(
        decision_timeframe="1h",
        trigger_timeframe="1h",
        warmup={"4h": 1},
    )
    store, requirements, grid = make_store(plan)
    store.append(
        requirements.decision_series,
        make_bar("1h", BASE + timedelta(hours=10), timedelta(hours=1)),
    )
    four_hour = MarketSeriesKey(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        timeframe="4h",
    )
    store.append(
        four_hour, make_bar("4h", BASE + timedelta(hours=4), timedelta(hours=4))
    )
    assert (
        evaluate(plan, requirements, store, grid, BASE + timedelta(hours=11)).state
        == "LIVE"
    )
    store.append(
        requirements.decision_series,
        make_bar("1h", BASE + timedelta(hours=11), timedelta(hours=1), value=101),
    )
    assert (
        evaluate(plan, requirements, store, grid, BASE + timedelta(hours=12)).state
        == "DEGRADED"
    )


def test_projected_lane_is_live_with_complete_1m_source_coverage() -> None:
    plan = make_plan(decision_timeframe="4h", trigger_timeframe="1m")
    store, requirements, grid = make_store(plan)
    store.append(
        requirements.decision_series,
        make_bar("4h", BASE + timedelta(hours=4), timedelta(hours=4)),
    )
    for index in range(120):
        start = BASE + timedelta(hours=8, minutes=index)
        store.append(
            requirements.trigger_series, make_bar("1m", start, timedelta(minutes=1))
        )
    readiness = evaluate(plan, requirements, store, grid, BASE + timedelta(hours=10))
    assert readiness.state == "LIVE"
    assert readiness.missing_dependencies == ()


@pytest.mark.parametrize("missing", ["start", "middle", "end"])
def test_projected_lane_missing_source_is_degraded(missing: str) -> None:
    plan = make_plan(decision_timeframe="4h", trigger_timeframe="1m")
    store, requirements, grid = make_store(plan)
    store.append(
        requirements.decision_series,
        make_bar("4h", BASE + timedelta(hours=4), timedelta(hours=4)),
    )
    for index in range(120):
        if missing == "start" and index == 0:
            continue
        if missing == "middle" and index == 60:
            continue
        if missing == "end" and index == 119:
            continue
        start = BASE + timedelta(hours=8, minutes=index)
        store.append(
            requirements.trigger_series, make_bar("1m", start, timedelta(minutes=1))
        )
    readiness = evaluate(plan, requirements, store, grid, BASE + timedelta(hours=10))
    assert readiness.state == "DEGRADED"
    assert "1m:projection" in readiness.missing_inputs


def test_projected_lane_at_exact_boundary_requires_canonical_4h_close() -> None:
    plan = make_plan(decision_timeframe="4h", trigger_timeframe="1m")
    store, requirements, grid = make_store(plan)
    for index in range(240):
        start = BASE + timedelta(hours=8, minutes=index)
        store.append(
            requirements.trigger_series, make_bar("1m", start, timedelta(minutes=1))
        )
    readiness = evaluate(plan, requirements, store, grid, BASE + timedelta(hours=12))
    assert readiness.state == "DEGRADED"
    assert "4h:cutoff" in readiness.missing_inputs
    store.append(
        requirements.decision_series,
        make_bar("4h", BASE + timedelta(hours=8), timedelta(hours=4)),
    )
    assert (
        evaluate(plan, requirements, store, grid, BASE + timedelta(hours=12)).state
        == "LIVE"
    )


def test_lane_commit_watermark_does_not_limit_shared_input_progress() -> None:
    plan = make_plan(decision_timeframe="1h", trigger_timeframe="1h")
    store, requirements, grid = make_store(plan)
    latest = BASE + timedelta(hours=11)
    store.append(
        requirements.decision_series,
        make_bar("1h", BASE + timedelta(hours=10), timedelta(hours=1)),
    )
    readiness = LaneReadinessEvaluator.evaluate(
        plan.lanes[0],
        requirements,
        store,
        grid,
        latest,
        InputReadCursor(stream_key="offline:BTCUSDT", latest_market_as_of=latest),
        LaneCommitWatermark(
            lane_id=plan.lanes[0].lane_id,
            latest_market_as_of=BASE + timedelta(hours=9),
        ),
    )
    assert readiness.state == "LIVE"
    assert readiness.input_read_cursor.latest_market_as_of == latest
    assert readiness.lane_commit_watermark.latest_market_as_of == BASE + timedelta(
        hours=9
    )


def test_requirements_must_match_lane_identity_warmup_and_projection_mode() -> None:
    plan = make_plan(decision_timeframe="1h", trigger_timeframe="1h", warmup={"4h": 3})
    store, requirements, grid = make_store(plan)
    eth_series = MarketSeriesKey(
        asset="ETHUSDT",
        venue="binance",
        instrument_id="ETH-USDT-PERP",
        timeframe="1h",
    )
    wrong_identity = LaneMarketRequirements(
        lane_id=plan.lanes[0].lane_id,
        minimum_bars_by_series={eth_series: 1},
        decision_series=eth_series,
        trigger_series=eth_series,
        projected_decision=False,
    )
    with pytest.raises(ValueError, match="decision_series"):
        evaluate(plan, wrong_identity, store, grid, BASE + timedelta(hours=1))

    understated = LaneMarketRequirements(
        lane_id=plan.lanes[0].lane_id,
        minimum_bars_by_series={requirements.decision_series: 1},
        decision_series=requirements.decision_series,
        trigger_series=requirements.trigger_series,
        projected_decision=False,
    )
    with pytest.raises(ValueError, match="warmup"):
        evaluate(plan, understated, store, grid, BASE + timedelta(hours=1))

    projected_plan = make_plan(decision_timeframe="4h", trigger_timeframe="1m")
    projected_store, projected_requirements, projected_grid = make_store(projected_plan)
    wrong_mode = LaneMarketRequirements(
        lane_id=projected_plan.lanes[0].lane_id,
        minimum_bars_by_series=projected_requirements.minimum_bars_by_series,
        decision_series=projected_requirements.decision_series,
        trigger_series=projected_requirements.trigger_series,
        projected_decision=False,
    )
    with pytest.raises(ValueError, match="projected_decision"):
        evaluate(
            projected_plan,
            wrong_mode,
            projected_store,
            projected_grid,
            BASE + timedelta(hours=1),
        )


def test_malformed_canonical_geometry_fails_closed() -> None:
    plan = make_plan(decision_timeframe="1h", trigger_timeframe="1h")
    store, requirements, grid = make_store(plan)
    malformed = make_bar(
        "1h",
        BASE,
        timedelta(minutes=30),
    )
    store.append(requirements.decision_series, malformed)
    with pytest.raises(TimeframeGeometryError, match="duration"):
        evaluate(plan, requirements, store, grid, BASE + timedelta(hours=1))

    shifted = make_bar(
        "1h",
        BASE + timedelta(minutes=30),
        timedelta(hours=1),
    )
    shifted_store, shifted_requirements, shifted_grid = make_store(plan)
    shifted_store.append(shifted_requirements.decision_series, shifted)
    with pytest.raises(TimeframeGeometryError, match="aligned"):
        evaluate(
            plan,
            shifted_requirements,
            shifted_store,
            shifted_grid,
            BASE + timedelta(hours=2),
        )


def test_recent_required_warmup_window_must_be_contiguous() -> None:
    plan = make_plan(decision_timeframe="1h", trigger_timeframe="1h", warmup={"1h": 3})
    store, requirements, grid = make_store(plan)
    store.append(
        requirements.decision_series,
        make_bar("1h", BASE, timedelta(hours=1)),
    )
    store.append(
        requirements.decision_series,
        make_bar("1h", BASE + timedelta(hours=2), timedelta(hours=1), value=102),
    )
    store.append(
        requirements.decision_series,
        make_bar("1h", BASE + timedelta(hours=3), timedelta(hours=1), value=103),
    )
    readiness = evaluate(plan, requirements, store, grid, BASE + timedelta(hours=4))
    assert readiness.state == "DEGRADED"
    assert "1h:history_gap" in readiness.missing_inputs


@pytest.mark.parametrize(
    ("prior_bars", "expected_state"),
    [(4, "DEGRADED"), (1, "WARMING")],
)
def test_projected_boundary_distinguishes_missing_current_from_warmup(
    prior_bars: int,
    expected_state: str,
) -> None:
    plan = make_plan(
        decision_timeframe="4h",
        trigger_timeframe="1m",
        warmup={"4h": 5},
    )
    store, requirements, grid = make_store(plan)
    for index in range(240):
        start = BASE + timedelta(hours=8, minutes=index)
        store.append(
            requirements.trigger_series,
            make_bar("1m", start, timedelta(minutes=1)),
        )
    for index in range(prior_bars):
        start = BASE + timedelta(hours=8 - 4 * (prior_bars - index))
        store.append(
            requirements.decision_series,
            make_bar("4h", start, timedelta(hours=4), value=100 + index),
        )
    readiness = evaluate(plan, requirements, store, grid, BASE + timedelta(hours=12))
    assert readiness.state == expected_state
    if expected_state == "DEGRADED":
        assert "4h:cutoff" in readiness.missing_inputs
    else:
        assert "4h:history" in readiness.missing_inputs
