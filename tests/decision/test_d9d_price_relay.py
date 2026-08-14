from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from apps.decision_app.market_state import MarketSeriesKey, TimeframeGrid
from apps.decision_app.price_relay import (
    PriceRelay,
    PriceRelayPublicationAck,
    PriceRelayPublisher,
    build_price_update,
    compile_price_relay_plans,
    price_relay_entry_id,
)
from apps.decision_app.settings import (
    CanonicalInstrument,
    DecisionAssetSettings,
    DecisionConfig,
    DecisionGlobalSettings,
    PriceRelaySettings,
)
from apps.decision_app.storage.market_history import (
    InMemoryCanonicalMarketHistoryRepository,
)
from libs.contracts.decision import CausalBarView
from libs.contracts.schemas import PriceUpdate, valkey_encode

BASE = datetime(2026, 1, 1, tzinfo=UTC)
GRID = TimeframeGrid(
    alignment_origin=BASE,
    durations={"1h": timedelta(hours=1)},
)
SERIES = MarketSeriesKey(
    asset="BTC",
    venue="binance",
    instrument_id="BTC-USDT-PERP",
    timeframe="1h",
)


def _bar(index: int) -> CausalBarView:
    opened = BASE + timedelta(hours=index)
    closed = opened + timedelta(hours=1)
    value = Decimal(100 + index)
    return CausalBarView(
        timeframe="1h",
        bar_open_at=opened,
        bar_close_at=closed,
        market_as_of=closed,
        open=value,
        high=value + 1,
        low=value - 1,
        close=value,
        volume=Decimal(10),
        taker_buy_base=Decimal(5),
        closed=True,
    )


class _Client:
    def __init__(self) -> None:
        self.entries: dict[str, dict[str, dict]] = {}
        self.calls: list[tuple[str, str]] = []
        self.raise_after_insert = False
        self.fail_before_insert = False

    async def xrange(self, stream: str, start: str, end: str):
        entry = self.entries.get(stream, {}).get(start)
        return [] if entry is None else [(start, entry)]

    async def xrevrange(self, stream: str, _start: str, _end: str, count: int = 1):
        values = self.entries.get(stream, {})
        if not values:
            return []
        entry_id = max(values, key=lambda value: tuple(map(int, value.split("-"))))
        return [(entry_id, values[entry_id])][:count]

    async def xadd(self, stream: str, fields: dict, *, id: str, **_kwargs):
        self.calls.append((stream, id))
        if self.fail_before_insert:
            self.fail_before_insert = False
            raise RuntimeError("temporary")
        self.entries.setdefault(stream, {})[id] = fields
        if self.raise_after_insert:
            self.raise_after_insert = False
            raise RuntimeError("response lost")
        return id


def _plan():
    config = DecisionConfig(
        global_settings=DecisionGlobalSettings(),
        assets={
            "BTC": DecisionAssetSettings(
                manifest_asset="BTC",
                decision_asset="BTCUSDT",
                venue="binance",
                instrument_id="BTC-USDT-PERP",
                lanes={},
                price_relay=PriceRelaySettings(enabled=True, timeframes=("1h",)),
            )
        },
        timeframe_grid=GRID,
        instruments={
            "BTC": CanonicalInstrument(
                manifest_asset="BTC",
                instrument_id="BTC-USDT-PERP",
                venue="binance",
                timeframes=("1h",),
                provider_symbols={"binance_native": "BTCUSDT"},
            )
        },
    )
    plans = compile_price_relay_plans(config)
    assert len(plans) == 1
    return plans[0]


def test_relay_only_config_compiles_canonical_series_plan() -> None:
    plan = _plan()
    assert plan.manifest_asset == "BTC"
    assert plan.asset == "BTCUSDT"
    assert plan.instrument_id == "BTC-USDT-PERP"
    assert plan.stream_key == "price_update:BTCUSDT:1h"
    assert not hasattr(plan, "source_lane")


def test_decision_asset_without_lane_requires_an_enabled_relay() -> None:
    with pytest.raises(ValueError, match="lane or an enabled price relay"):
        DecisionAssetSettings(
            manifest_asset="BTC",
            decision_asset="BTCUSDT",
            venue="binance",
            instrument_id="BTC-USDT-PERP",
            lanes={},
        )


def test_relay_timeframe_must_be_a_canonical_instrument_series() -> None:
    with pytest.raises(ValueError, match="unknown .* timeframe"):
        DecisionConfig(
            global_settings=DecisionGlobalSettings(),
            assets={
                "BTC": DecisionAssetSettings(
                    manifest_asset="BTC",
                    decision_asset="BTCUSDT",
                    venue="binance",
                    instrument_id="BTC-USDT-PERP",
                    lanes={},
                    price_relay=PriceRelaySettings(
                        enabled=True,
                        timeframes=("30m",),
                    ),
                )
            },
            timeframe_grid=GRID,
            instruments={
                "BTC": CanonicalInstrument(
                    manifest_asset="BTC",
                    instrument_id="BTC-USDT-PERP",
                    venue="binance",
                    timeframes=("1h",),
                    provider_symbols={"binance_native": "BTCUSDT"},
                )
            },
        )


def test_current_risk_routes_compile_without_model_lanes() -> None:
    route_grid = TimeframeGrid(
        alignment_origin=BASE,
        durations={
            "30m": timedelta(minutes=30),
            "1h": timedelta(hours=1),
            "4h": timedelta(hours=4),
        },
    )
    routes = {
        "BTC": ("BTCUSDT", "BTC-USDT-PERP", ("1h", "4h")),
        "ETH": ("ETHUSDT", "ETH-USDT-PERP", ("4h",)),
        "XRP": ("XRPUSDT", "XRP-USDT-PERP", ("1h",)),
        "SOL": ("SOLUSDT", "SOL-USDT-PERP", ("1h",)),
        "BNB": ("BNBUSDT", "BNB-USDT-PERP", ("30m",)),
        "DOGE": ("DOGEUSDT", "DOGE-USDT-PERP", ("4h",)),
    }
    assets = {
        manifest_asset: DecisionAssetSettings(
            manifest_asset=manifest_asset,
            decision_asset=decision_asset,
            venue="binance",
            instrument_id=instrument_id,
            lanes={},
            price_relay=PriceRelaySettings(enabled=True, timeframes=timeframes),
        )
        for manifest_asset, (
            decision_asset,
            instrument_id,
            timeframes,
        ) in routes.items()
    }
    instruments = {
        manifest_asset: CanonicalInstrument(
            manifest_asset=manifest_asset,
            instrument_id=instrument_id,
            venue="binance",
            timeframes=timeframes,
            provider_symbols={"binance_native": decision_asset},
        )
        for manifest_asset, (
            decision_asset,
            instrument_id,
            timeframes,
        ) in routes.items()
    }
    plans = compile_price_relay_plans(
        DecisionConfig(
            global_settings=DecisionGlobalSettings(),
            assets=assets,
            timeframe_grid=route_grid,
            instruments=instruments,
        )
    )

    assert {(plan.asset, plan.timeframe, plan.stream_key) for plan in plans} == {
        ("BTCUSDT", "1h", "price_update:BTCUSDT:1h"),
        ("BTCUSDT", "4h", "price_update:BTCUSDT:4h"),
        ("ETHUSDT", "4h", "price_update:ETHUSDT:4h"),
        ("XRPUSDT", "1h", "price_update:XRPUSDT:1h"),
        ("SOLUSDT", "1h", "price_update:SOLUSDT:1h"),
        ("BNBUSDT", "30m", "price_update:BNBUSDT:30m"),
        ("DOGEUSDT", "4h", "price_update:DOGEUSDT:4h"),
    }


@pytest.mark.asyncio
async def test_exact_price_update_id_is_idempotent_and_ambiguous_safe() -> None:
    plan = _plan()
    bar = _bar(0)
    client = _Client()
    publisher = PriceRelayPublisher(client)

    first = await publisher.publish(plan, bar)
    second = await publisher.publish(plan, bar)
    assert first.outcome == "PUBLISHED"
    assert second.outcome == "ALREADY_IDENTICAL"
    assert first.stream_entry_id == price_relay_entry_id(bar)
    assert build_price_update(plan, bar).timestamp == int(BASE.timestamp() * 1000)

    client.raise_after_insert = True
    third = await publisher.publish(plan, _bar(1))
    assert third.outcome == "ALREADY_IDENTICAL"


@pytest.mark.asyncio
async def test_price_publisher_rejects_conflicts_and_failed_transport() -> None:
    plan = _plan()
    client = _Client()
    publisher = PriceRelayPublisher(client)

    client.entries[plan.stream_key] = {
        price_relay_entry_id(_bar(0)): valkey_encode(build_price_update(plan, _bar(1)))
    }
    conflict = await publisher.publish(plan, _bar(0))
    assert conflict.outcome == "CONFLICT"

    client.entries[plan.stream_key] = {
        price_relay_entry_id(_bar(1)): valkey_encode(build_price_update(plan, _bar(1)))
    }
    head_conflict = await publisher.publish(plan, _bar(0))
    assert head_conflict.outcome == "CONFLICT"

    client.entries.clear()
    client.xadd = AsyncMock(side_effect=RuntimeError("transport unavailable"))
    failed = await publisher.publish(plan, _bar(0))
    assert failed.outcome == "FAILED"


@pytest.mark.asyncio
async def test_bootstrap_records_tail_and_baseline_evidence() -> None:
    plan = _plan()
    bars = tuple(_bar(index) for index in range(3))
    history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: bars},
        timeframe_grid=GRID,
    )

    tail_client = _Client()
    tail_client.entries = {
        plan.stream_key: {
            price_relay_entry_id(bars[0]): valkey_encode(
                build_price_update(plan, bars[0])
            )
        }
    }
    tail_relay = PriceRelay(
        plans=(plan,),
        stream_client=tail_client,
        history_repository=history,
        timeframe_grid=GRID,
        warm_cutoffs={SERIES: bars[0].bar_close_at},
    )
    tail_progress = await tail_relay.bootstrap()
    assert tail_progress[plan.relay_plan_id].continuity_status == "CONTINUOUS"

    baseline_relay = PriceRelay(
        plans=(plan,),
        stream_client=_Client(),
        history_repository=history,
        timeframe_grid=GRID,
        warm_cutoffs={SERIES: bars[0].bar_close_at},
    )
    baseline_progress = await baseline_relay.bootstrap()
    evidence = baseline_progress[plan.relay_plan_id].gap_evidence
    assert evidence["baseline_source"] == "startup_canonical_cutoff"
    assert evidence["downstream_tail_present"] is False


@pytest.mark.asyncio
async def test_bootstrap_tail_behind_or_ahead_fails_closed() -> None:
    plan = _plan()
    bars = tuple(_bar(index) for index in range(3))
    history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: bars},
        timeframe_grid=GRID,
    )
    for tail_index, expected_status in ((0, "GAP_DETECTED"), (2, "UNRESOLVED")):
        client = _Client()
        client.entries = {
            plan.stream_key: {
                price_relay_entry_id(bars[tail_index]): valkey_encode(
                    build_price_update(plan, bars[tail_index])
                )
            }
        }
        relay = PriceRelay(
            plans=(plan,),
            stream_client=client,
            history_repository=history,
            timeframe_grid=GRID,
            warm_cutoffs={SERIES: bars[1].bar_close_at},
        )
        progress = await relay.bootstrap()
        assert progress[plan.relay_plan_id].continuity_status == expected_status


@pytest.mark.asyncio
async def test_malformed_tail_is_unresolved_without_overwrite() -> None:
    plan = _plan()
    client = _Client()
    client.entries = {plan.stream_key: {price_relay_entry_id(_bar(0)): {"bad": "1"}}}
    relay = PriceRelay(
        plans=(plan,),
        stream_client=client,
        history_repository=InMemoryCanonicalMarketHistoryRepository(
            {SERIES: (_bar(0),)},
            timeframe_grid=GRID,
        ),
        timeframe_grid=GRID,
        warm_cutoffs={SERIES: _bar(0).bar_close_at},
    )
    progress = await relay.bootstrap()
    assert progress[plan.relay_plan_id].continuity_status == "UNRESOLVED"
    assert client.entries[plan.stream_key][price_relay_entry_id(_bar(0))] == {
        "bad": "1"
    }


@pytest.mark.asyncio
async def test_catchup_is_chronological_and_batch_bounded() -> None:
    plan = _plan()
    bars = tuple(_bar(index) for index in range(3))
    history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: bars},
        timeframe_grid=GRID,
    )
    client = _Client()
    relay = PriceRelay(
        plans=(plan,),
        stream_client=client,
        history_repository=history,
        timeframe_grid=GRID,
        warm_cutoffs={SERIES: bars[0].bar_close_at},
        batch_size=1,
    )
    await relay.bootstrap()
    first = await relay.reconcile(plan.relay_plan_id, bars[2])
    assert first.continuity_status == "GAP_DETECTED"
    assert client.calls == [(plan.stream_key, price_relay_entry_id(bars[1]))]
    second = await relay.reconcile(plan.relay_plan_id, bars[2])
    assert second.continuity_status == "CONTINUOUS"
    assert client.calls[-1] == (plan.stream_key, price_relay_entry_id(bars[2]))


@pytest.mark.asyncio
async def test_catchup_retains_live_target_across_idle_reconciliations() -> None:
    plan = _plan()
    bars = tuple(_bar(index) for index in range(4))
    client = _Client()
    relay = PriceRelay(
        plans=(plan,),
        stream_client=client,
        history_repository=InMemoryCanonicalMarketHistoryRepository(
            {SERIES: bars},
            timeframe_grid=GRID,
        ),
        timeframe_grid=GRID,
        warm_cutoffs={SERIES: bars[0].bar_close_at},
        batch_size=1,
    )

    first = await relay.reconcile_all({SERIES: bars[3]})
    second = await relay.reconcile_all()
    third = await relay.reconcile_all()

    assert first[plan.relay_plan_id].continuity_status == "GAP_DETECTED"
    assert first[plan.relay_plan_id].target_market_as_of == bars[3].bar_close_at
    assert first[plan.relay_plan_id].backlog_bars == 2
    assert second[plan.relay_plan_id].continuity_status == "GAP_DETECTED"
    assert second[plan.relay_plan_id].backlog_bars == 1
    assert third[plan.relay_plan_id].continuity_status == "CONTINUOUS"
    assert third[plan.relay_plan_id].backlog_bars == 0
    assert client.calls == [
        (plan.stream_key, price_relay_entry_id(bars[1])),
        (plan.stream_key, price_relay_entry_id(bars[2])),
        (plan.stream_key, price_relay_entry_id(bars[3])),
    ]


@pytest.mark.asyncio
async def test_transient_failed_publication_retries_exact_next_bar() -> None:
    plan = _plan()
    bars = (_bar(0), _bar(1))
    client = _Client()
    client.fail_before_insert = True
    relay = PriceRelay(
        plans=(plan,),
        stream_client=client,
        history_repository=InMemoryCanonicalMarketHistoryRepository(
            {SERIES: bars},
            timeframe_grid=GRID,
        ),
        timeframe_grid=GRID,
        warm_cutoffs={SERIES: bars[0].bar_close_at},
        batch_size=1,
    )

    failed = await relay.reconcile_all({SERIES: bars[1]})
    retried = await relay.reconcile_all()

    assert failed[plan.relay_plan_id].publication_outcome == "FAILED"
    assert failed[plan.relay_plan_id].continuity_status == "GAP_DETECTED"
    assert failed[plan.relay_plan_id].published_market_as_of == bars[0].bar_close_at
    assert failed[plan.relay_plan_id].target_market_as_of == bars[1].bar_close_at
    assert retried[plan.relay_plan_id].publication_outcome == "PUBLISHED"
    assert retried[plan.relay_plan_id].continuity_status == "CONTINUOUS"
    assert client.calls == [
        (plan.stream_key, price_relay_entry_id(bars[1])),
        (plan.stream_key, price_relay_entry_id(bars[1])),
    ]


@pytest.mark.asyncio
async def test_first_closed_bar_establishes_no_tail_no_warm_relay() -> None:
    plan = _plan()
    bar = _bar(0)
    client = _Client()
    relay = PriceRelay(
        plans=(plan,),
        stream_client=client,
        history_repository=InMemoryCanonicalMarketHistoryRepository(
            {SERIES: (bar,)},
            timeframe_grid=GRID,
        ),
        timeframe_grid=GRID,
        warm_cutoffs={SERIES: None},
        batch_size=1,
    )

    before = await relay.bootstrap()
    result = await relay.reconcile_all({SERIES: bar})

    assert before[plan.relay_plan_id].continuity_status == "UNRESOLVED"
    assert result[plan.relay_plan_id].continuity_status == "CONTINUOUS"
    assert relay.progress[plan.relay_plan_id].latest_market_as_of == bar.bar_close_at
    assert client.calls == [(plan.stream_key, price_relay_entry_id(bar))]


@pytest.mark.asyncio
async def test_first_bar_failed_publication_retries_from_canonical_history() -> None:
    plan = _plan()
    bar = _bar(0)
    client = _Client()
    client.fail_before_insert = True
    relay = PriceRelay(
        plans=(plan,),
        stream_client=client,
        history_repository=InMemoryCanonicalMarketHistoryRepository(
            {SERIES: (bar,)},
            timeframe_grid=GRID,
        ),
        timeframe_grid=GRID,
        warm_cutoffs={SERIES: None},
        batch_size=1,
    )

    failed = await relay.reconcile_all({SERIES: bar})
    retried = await relay.reconcile_all()

    assert failed[plan.relay_plan_id].continuity_status == "GAP_DETECTED"
    assert retried[plan.relay_plan_id].continuity_status == "CONTINUOUS"
    assert relay.progress[plan.relay_plan_id].latest_market_as_of == bar.bar_close_at
    assert client.calls == [
        (plan.stream_key, price_relay_entry_id(bar)),
        (plan.stream_key, price_relay_entry_id(bar)),
    ]


@pytest.mark.asyncio
async def test_failed_relay_does_not_stop_an_independent_relay_plan() -> None:
    plan = _plan()
    other_plan = replace(
        plan,
        relay_plan_id="ETHUSDT:binance:ETH-USDT-PERP:1h",
        manifest_asset="ETH",
        asset="ETHUSDT",
        instrument_id="ETH-USDT-PERP",
        stream_key="price_update:ETHUSDT:1h",
    )
    other_series = MarketSeriesKey(
        asset="ETH",
        venue="binance",
        instrument_id="ETH-USDT-PERP",
        timeframe="1h",
    )
    bars = (_bar(0), _bar(1))
    client = _Client()
    relay = PriceRelay(
        plans=(plan, other_plan),
        stream_client=client,
        history_repository=InMemoryCanonicalMarketHistoryRepository(
            {SERIES: bars, other_series: bars},
            timeframe_grid=GRID,
        ),
        timeframe_grid=GRID,
        warm_cutoffs={
            SERIES: bars[0].bar_close_at,
            other_series: bars[0].bar_close_at,
        },
        batch_size=1,
    )

    original_publish = relay._publisher.publish

    async def fail_first_plan(current_plan, bar):
        if current_plan.relay_plan_id == plan.relay_plan_id:
            return PriceRelayPublicationAck(
                relay_plan_id=current_plan.relay_plan_id,
                stream_key=current_plan.stream_key,
                stream_entry_id=price_relay_entry_id(bar),
                outcome="FAILED",
                reason="temporary relay failure",
            )
        return await original_publish(current_plan, bar)

    relay._publisher.publish = fail_first_plan
    results = await relay.reconcile_all({SERIES: bars[1], other_series: bars[1]})

    assert results[plan.relay_plan_id].continuity_status == "GAP_DETECTED"
    assert results[plan.relay_plan_id].publication_outcome == "FAILED"
    assert results[other_plan.relay_plan_id].continuity_status == "CONTINUOUS"
    assert results[other_plan.relay_plan_id].publication_outcome == "PUBLISHED"


@pytest.mark.asyncio
async def test_input_failure_invalidates_only_matching_relay_plan() -> None:
    plan = _plan()
    other_plan = replace(
        plan,
        relay_plan_id="ETHUSDT:binance:ETH-USDT-PERP:1h",
        manifest_asset="ETH",
        asset="ETHUSDT",
        instrument_id="ETH-USDT-PERP",
        stream_key="price_update:ETHUSDT:1h",
    )
    other_series = MarketSeriesKey(
        asset="ETH",
        venue="binance",
        instrument_id="ETH-USDT-PERP",
        timeframe="1h",
    )
    bars = (_bar(0), _bar(1))
    client = _Client()
    history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: bars, other_series: bars},
        timeframe_grid=GRID,
    )
    relay = PriceRelay(
        plans=(plan, other_plan),
        stream_client=client,
        history_repository=history,
        timeframe_grid=GRID,
        warm_cutoffs={
            SERIES: bars[0].bar_close_at,
            other_series: bars[0].bar_close_at,
        },
        batch_size=1,
    )

    relay.mark_input_failure(
        SERIES,
        reason="forward canonical market gap",
        observed_target_market_as_of=bars[1].market_as_of,
    )
    results = await relay.reconcile_all({other_series: bars[1]})

    assert results[plan.relay_plan_id].continuity_status == "UNRESOLVED"
    assert results[plan.relay_plan_id].publication_outcome is None
    assert relay.progress[plan.relay_plan_id].gap_evidence["input_failure"] is True
    assert results[other_plan.relay_plan_id].continuity_status == "CONTINUOUS"
    assert results[other_plan.relay_plan_id].publication_outcome == "PUBLISHED"


@pytest.mark.asyncio
async def test_input_failure_before_bootstrap_stays_unresolved_until_fresh_generation() -> (
    None
):
    plan = _plan()
    bar = _bar(0)
    history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: (bar,)},
        timeframe_grid=GRID,
    )
    client = _Client()
    relay = PriceRelay(
        plans=(plan,),
        stream_client=client,
        history_repository=history,
        timeframe_grid=GRID,
        warm_cutoffs={SERIES: None},
        batch_size=1,
    )

    relay.mark_input_failure(SERIES, reason="forward canonical market gap")
    blocked = await relay.reconcile_all({SERIES: bar})

    assert blocked[plan.relay_plan_id].continuity_status == "UNRESOLVED"
    assert client.calls == []

    fresh = PriceRelay(
        plans=(plan,),
        stream_client=client,
        history_repository=history,
        timeframe_grid=GRID,
        warm_cutoffs={SERIES: None},
        batch_size=1,
    )
    recovered = await fresh.reconcile_all({SERIES: bar})

    assert recovered[plan.relay_plan_id].continuity_status == "CONTINUOUS"
    assert recovered[plan.relay_plan_id].publication_outcome == "PUBLISHED"


@pytest.mark.asyncio
async def test_missing_canonical_bar_is_unresolved_without_progress() -> None:
    plan = _plan()
    bars = (_bar(0), _bar(2))
    history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: bars},
        timeframe_grid=GRID,
    )
    relay = PriceRelay(
        plans=(plan,),
        stream_client=_Client(),
        history_repository=history,
        timeframe_grid=GRID,
        warm_cutoffs={SERIES: bars[0].bar_close_at},
        batch_size=2,
    )
    await relay.bootstrap()
    result = await relay.reconcile(plan.relay_plan_id, bars[1])
    assert result.continuity_status == "UNRESOLVED"
    assert (
        relay.progress[plan.relay_plan_id].latest_market_as_of == bars[0].bar_close_at
    )


@pytest.mark.asyncio
async def test_backlog_over_stream_retention_does_not_publish_partial_history() -> None:
    plan = _plan()
    bars = tuple(_bar(index) for index in range(4))
    client = _Client()
    relay = PriceRelay(
        plans=(plan,),
        stream_client=client,
        history_repository=InMemoryCanonicalMarketHistoryRepository(
            {SERIES: bars},
            timeframe_grid=GRID,
        ),
        timeframe_grid=GRID,
        warm_cutoffs={SERIES: bars[0].bar_close_at},
        stream_maxlen=2,
        batch_size=2,
    )
    await relay.bootstrap()
    result = await relay.reconcile(plan.relay_plan_id, bars[3])
    assert result.continuity_status == "UNRESOLVED"
    assert client.calls == []


def test_price_update_wire_contract_remains_unchanged() -> None:
    update = PriceUpdate(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1_000,
        open=1,
        high=2,
        low=0,
        close=1.5,
        volume=4,
    )
    assert float(valkey_encode(update)["timestamp"]) == 1000.0
