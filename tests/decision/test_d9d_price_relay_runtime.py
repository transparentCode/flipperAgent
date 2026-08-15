"""D9D relay-only live-runtime integration proof."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.decision_app.data.resolver import DataPolicy, DataResolver, DataSourceCatalog
from apps.decision_app.domain.market_state import MarketSeriesKey, TimeframeGrid
from apps.decision_app.features.planning import FeatureCatalog, FeaturePolicy
from apps.decision_app.planning.catalog import PluginCatalog
from apps.decision_app.runtime.lifecycle import LifecycleReadResult
from apps.decision_app.runtime.live import LiveDecisionRuntime
from apps.decision_app.runtime.plugins import RuntimePluginCatalog
from apps.decision_app.runtime.service import DecisionRuntimeGeneration, DecisionService
from apps.decision_app.runtime.startup import DecisionStartupCoordinator
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
from apps.decision_app.transport.ingestion import canonical_ingestion_stream_key
from apps.decision_app.transport.price_relay import (
    PriceRelay,
    compile_price_relay_plans,
)
from libs.contracts.decision import CausalBarView

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
INGESTION_STREAM = canonical_ingestion_stream_key(SERIES)


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


def _ingestion_fields(bar: CausalBarView) -> dict[str, str]:
    payload = {
        "venue": SERIES.venue,
        "instrument_id": SERIES.instrument_id,
        "timeframe": SERIES.timeframe,
        "open_time": bar.bar_open_at.isoformat().replace("+00:00", "Z"),
        "close_time": bar.bar_close_at.isoformat().replace("+00:00", "Z"),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": str(bar.volume),
        "taker_buy_base": str(bar.taker_buy_base),
        "source_type": "provider",
        "source_provider": "test",
        "source_timeframe": None,
    }
    return {
        "event_id": f"relay-event-{bar.bar_open_at.hour}",
        "event_type": "candle.committed",
        "schema_version": "1",
        "producer": "ingestion",
        "occurred_at": bar.bar_close_at.isoformat().replace("+00:00", "Z"),
        "payload": json.dumps(payload),
    }


def _config() -> DecisionConfig:
    return DecisionConfig(
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


class _RelayClient:
    def __init__(self, bars: tuple[CausalBarView, ...]) -> None:
        self.bars = bars
        self.pending = [
            ("1-0", _ingestion_fields(bars[1])),
        ]
        self.price_entries: dict[str, dict[str, Mapping[object, object]]] = {}
        self.fail_price_publish = False

    async def xrevrange(self, stream: str, *_args: object, count: int = 1):
        if stream == INGESTION_STREAM:
            return [("0-0", _ingestion_fields(self.bars[0]))]
        values = self.price_entries.get(stream, {})
        if not values:
            return []
        entry_id = max(
            values,
            key=lambda value: tuple(int(part) for part in value.split("-")),
        )
        return [(entry_id, values[entry_id])][:count]

    async def xrange(self, stream: str, start: str, end: str):
        values = self.price_entries.get(stream, {})
        if start != end or start not in values:
            return []
        return [(start, values[start])]

    async def xread(
        self,
        streams: Mapping[str, str],
        *,
        count: int,
        block: int,
    ):
        del streams, count, block
        if not self.pending:
            return []
        pending, self.pending = self.pending, []
        return [(INGESTION_STREAM, pending)]

    async def xadd(
        self,
        stream: str,
        fields: Mapping[object, object],
        *,
        id: str,
        maxlen: int,
        approximate: bool,
    ) -> str:
        del maxlen, approximate
        if self.fail_price_publish:
            raise RuntimeError("temporary price transport failure")
        self.price_entries.setdefault(stream, {})[id] = fields
        return id


@pytest.mark.asyncio
async def test_relay_only_runtime_publishes_without_model_lanes() -> None:
    bars = (_bar(0), _bar(1))
    history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: (bars[0],)},
        timeframe_grid=GRID,
    )
    stream = _RelayClient(bars)
    source_catalog = DataSourceCatalog([])
    startup = await DecisionStartupCoordinator(
        decision_config=_config(),
        plugin_catalog=PluginCatalog([]),
        feature_catalog=FeatureCatalog([]),
        feature_policy=FeaturePolicy(name="operator", version="1"),
        data_policy=DataPolicy(name="operator", version="1", concepts={}),
        source_catalog=source_catalog,
        runtime_plugin_catalog=RuntimePluginCatalog([]),
        history_repository=history,
        stream_client=stream,
        data_resolver=DataResolver(source_catalog),
    ).start()
    plans = compile_price_relay_plans(_config())
    relay = PriceRelay(
        plans=plans,
        stream_client=stream,
        history_repository=history,
        timeframe_grid=GRID,
        warm_cutoffs={SERIES: bars[0].bar_close_at},
        batch_size=1,
    )

    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=GRID,
        stream_client=stream,
        history_repository=history,
        price_relay=relay,
        batch_size=1,
        block_ms=0,
    )
    result = await runtime.poll_once(evaluate_lanes=False)

    assert startup.snapshot.status == "STARTUP_READY"
    assert not startup.decision_plan.lanes
    assert result.input_results[0].disposition == "INSERTED"
    relay_result = result.relay_results[plans[0].relay_plan_id]
    assert relay_result.continuity_status == "CONTINUOUS"
    assert relay_result.publication_outcome == "PUBLISHED"
    assert tuple(stream.price_entries) == (plans[0].stream_key,)


@pytest.mark.asyncio
async def test_forward_input_gap_marks_same_series_relay_unresolved() -> None:
    bars = (_bar(0), _bar(1), _bar(2))
    history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: (bars[0],)},
        timeframe_grid=GRID,
    )
    stream = _RelayClient(bars)
    stream.pending = [("2-0", _ingestion_fields(bars[2]))]
    startup = await DecisionStartupCoordinator(
        decision_config=_config(),
        plugin_catalog=PluginCatalog([]),
        feature_catalog=FeatureCatalog([]),
        feature_policy=FeaturePolicy(name="operator", version="1"),
        data_policy=DataPolicy(name="operator", version="1", concepts={}),
        source_catalog=DataSourceCatalog([]),
        runtime_plugin_catalog=RuntimePluginCatalog([]),
        history_repository=history,
        stream_client=stream,
        data_resolver=DataResolver(DataSourceCatalog([])),
    ).start()
    plans = compile_price_relay_plans(_config())
    relay = PriceRelay(
        plans=plans,
        stream_client=stream,
        history_repository=history,
        timeframe_grid=GRID,
        warm_cutoffs={SERIES: bars[0].bar_close_at},
        batch_size=1,
    )
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=GRID,
        stream_client=stream,
        history_repository=history,
        price_relay=relay,
        batch_size=1,
        block_ms=0,
    )

    failed = await runtime.poll_once(evaluate_lanes=False)
    relay_id = plans[0].relay_plan_id
    input_result = failed.input_results[0]
    relay_result = failed.relay_results[relay_id]

    assert input_result.disposition == "RECONSTRUCTION_REQUIRED"
    assert "forward canonical market gap" in (input_result.reason or "")
    assert runtime.input.cursor_for(INGESTION_STREAM).latest_stream_id == "0-0"
    assert INGESTION_STREAM in runtime.input.blocked_streams
    assert relay_result.continuity_status == "UNRESOLVED"
    assert relay_result.published_market_as_of == bars[0].bar_close_at
    assert relay_result.publication_outcome is None
    assert relay.progress[relay_id].gap_evidence["input_failure"] is True
    assert not stream.price_entries

    idle = await runtime.poll_once(evaluate_lanes=False)
    assert idle.relay_results[relay_id].continuity_status == "UNRESOLVED"
    assert idle.relay_results[relay_id].publication_outcome is None
    assert not stream.price_entries


@pytest.mark.asyncio
async def test_deferred_malformed_suffix_refreshes_only_final_relay_evidence() -> None:
    bars = (_bar(0), _bar(1), _bar(2))
    startup_history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: (bars[0],)},
        timeframe_grid=GRID,
    )
    full_history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: bars[:2]},
        timeframe_grid=GRID,
    )

    class _History:
        async def fetch_latest_cutoff(self, key):
            return await startup_history.fetch_latest_cutoff(key)

        async def fetch_record_at(self, key, bar_open_at):
            return await full_history.fetch_record_at(key, bar_open_at)

        async def fetch_bars(self, key, **kwargs):
            return await full_history.fetch_bars(key, **kwargs)

    history = _History()
    malformed = _ingestion_fields(bars[2])
    malformed["event_type"] = "not-a-candle"
    stream = _RelayClient(bars)
    stream.pending = [
        ("1-0", _ingestion_fields(bars[1])),
        ("2-0", malformed),
        ("3-0", _ingestion_fields(bars[2])),
    ]
    startup = await DecisionStartupCoordinator(
        decision_config=_config(),
        plugin_catalog=PluginCatalog([]),
        feature_catalog=FeatureCatalog([]),
        feature_policy=FeaturePolicy(name="operator", version="1"),
        data_policy=DataPolicy(name="operator", version="1", concepts={}),
        source_catalog=DataSourceCatalog([]),
        runtime_plugin_catalog=RuntimePluginCatalog([]),
        history_repository=history,
        stream_client=stream,
        data_resolver=DataResolver(DataSourceCatalog([])),
    ).start()
    plans = compile_price_relay_plans(_config())
    relay = PriceRelay(
        plans=plans,
        stream_client=stream,
        history_repository=history,
        timeframe_grid=GRID,
        warm_cutoffs={SERIES: bars[0].bar_close_at},
        batch_size=1,
    )
    reconcile_calls = 0
    original_reconcile_all = relay.reconcile_all

    async def counted_reconcile_all(accepted_bars=None):
        nonlocal reconcile_calls
        reconcile_calls += 1
        return await original_reconcile_all(accepted_bars)

    relay.reconcile_all = counted_reconcile_all
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=GRID,
        stream_client=stream,
        history_repository=history,
        price_relay=relay,
        batch_size=3,
        block_ms=0,
    )

    result = await runtime.poll_once(evaluate_lanes=False)
    relay_id = plans[0].relay_plan_id

    assert [item.disposition for item in result.input_results] == [
        "INSERTED",
        "MALFORMED",
    ]
    assert runtime.input.cursor_for(INGESTION_STREAM).latest_stream_id == "1-0"
    assert INGESTION_STREAM in runtime.input.blocked_streams
    assert reconcile_calls == 1
    assert len(stream.price_entries[plans[0].stream_key]) == 1
    assert result.relay_results[relay_id].publication_outcome == "PUBLISHED"
    assert result.relay_results[relay_id].published_market_as_of == bars[1].bar_close_at
    assert result.relay_results[relay_id].continuity_status == "UNRESOLVED"
    assert "unsupported ingestion event_type" in (
        result.relay_results[relay_id].reason or ""
    )
    assert relay.progress[relay_id].continuity_status == "UNRESOLVED"
    assert relay.progress[relay_id].latest_market_as_of == bars[1].bar_close_at
    assert relay.progress[relay_id].gap_evidence["input_failure"] is True

    idle = await runtime.poll_once(evaluate_lanes=False)
    assert idle.relay_results[relay_id].continuity_status == "UNRESOLVED"
    assert runtime.input.cursor_for(INGESTION_STREAM).latest_stream_id == "1-0"
    assert len(stream.price_entries[plans[0].stream_key]) == 1


@pytest.mark.asyncio
async def test_relay_failure_advances_input_cursor_and_retries_retained_target() -> (
    None
):
    bars = (_bar(0), _bar(1))
    startup_history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: (bars[0],)},
        timeframe_grid=GRID,
    )
    full_history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: bars},
        timeframe_grid=GRID,
    )

    class _History:
        async def fetch_latest_cutoff(self, key):
            return await startup_history.fetch_latest_cutoff(key)

        async def fetch_record_at(self, key, bar_open_at):
            return await full_history.fetch_record_at(key, bar_open_at)

        async def fetch_bars(self, key, **kwargs):
            return await full_history.fetch_bars(key, **kwargs)

    history = _History()
    stream = _RelayClient(bars)
    stream.fail_price_publish = True
    startup = await DecisionStartupCoordinator(
        decision_config=_config(),
        plugin_catalog=PluginCatalog([]),
        feature_catalog=FeatureCatalog([]),
        feature_policy=FeaturePolicy(name="operator", version="1"),
        data_policy=DataPolicy(name="operator", version="1", concepts={}),
        source_catalog=DataSourceCatalog([]),
        runtime_plugin_catalog=RuntimePluginCatalog([]),
        history_repository=history,
        stream_client=stream,
        data_resolver=DataResolver(DataSourceCatalog([])),
    ).start()
    plans = compile_price_relay_plans(_config())
    relay = PriceRelay(
        plans=plans,
        stream_client=stream,
        history_repository=history,
        timeframe_grid=GRID,
        warm_cutoffs={SERIES: bars[0].bar_close_at},
        batch_size=1,
    )
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=GRID,
        stream_client=stream,
        history_repository=history,
        price_relay=relay,
        batch_size=1,
        block_ms=0,
    )

    failed = await runtime.poll_once(evaluate_lanes=False)
    assert failed.input_results[0].disposition == "INSERTED"
    assert runtime.input.cursor_for(INGESTION_STREAM).latest_stream_id == "1-0"
    relay_id = plans[0].relay_plan_id
    assert failed.relay_results[relay_id].publication_outcome == "FAILED"
    assert failed.relay_results[relay_id].continuity_status == "GAP_DETECTED"

    stream.fail_price_publish = False
    retried = await runtime.poll_once(evaluate_lanes=False)
    assert retried.input_results == ()
    assert retried.relay_results[relay_id].publication_outcome == "PUBLISHED"
    assert retried.relay_results[relay_id].continuity_status == "CONTINUOUS"
    assert len(stream.price_entries[plans[0].stream_key]) == 1


@pytest.mark.asyncio
async def test_service_pause_keeps_real_price_relay_polling_without_lanes() -> None:
    bars = (_bar(0), _bar(1), _bar(2))
    history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: (bars[0],)},
        timeframe_grid=GRID,
    )
    stream = _RelayClient(bars)
    startup = await DecisionStartupCoordinator(
        decision_config=_config(),
        plugin_catalog=PluginCatalog([]),
        feature_catalog=FeatureCatalog([]),
        feature_policy=FeaturePolicy(name="operator", version="1"),
        data_policy=DataPolicy(name="operator", version="1", concepts={}),
        source_catalog=DataSourceCatalog([]),
        runtime_plugin_catalog=RuntimePluginCatalog([]),
        history_repository=history,
        stream_client=stream,
        data_resolver=DataResolver(DataSourceCatalog([])),
    ).start()
    plans = compile_price_relay_plans(_config())
    relay = PriceRelay(
        plans=plans,
        stream_client=stream,
        history_repository=history,
        timeframe_grid=GRID,
        warm_cutoffs={SERIES: bars[0].bar_close_at},
        batch_size=1,
    )
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=GRID,
        stream_client=stream,
        history_repository=history,
        price_relay=relay,
        batch_size=1,
        block_ms=0,
    )

    class _ObservedRuntime:
        def __init__(self) -> None:
            self.input = runtime.input
            self.lanes = runtime.lanes
            self.price_relay = runtime.price_relay
            self.evaluate_flags: list[bool] = []

        async def poll_once(self, *, evaluate_lanes: bool = True) -> object:
            self.evaluate_flags.append(evaluate_lanes)
            return await runtime.poll_once(evaluate_lanes=evaluate_lanes)

    observed = _ObservedRuntime()

    async def factory(*, reason: str, generation_id: int) -> DecisionRuntimeGeneration:
        del reason
        return DecisionRuntimeGeneration(
            generation_id=generation_id,
            created_at=BASE,
            startup=startup,
            live_runtime=observed,
        )

    service = DecisionService(
        generation_factory=factory,
        configured_asset_count=1,
        block_ms=0,
        now_fn=lambda: BASE,
    )
    await service.start()
    for _ in range(200):
        if len(stream.price_entries.get(plans[0].stream_key, {})) == 1:
            break
        await asyncio.sleep(0)
    else:
        raise AssertionError("initial relay publication was not observed")

    stream.pending.append(("2-0", _ingestion_fields(bars[2])))
    paused = await service.pause()
    assert paused.service_state == "PAUSED"
    assert paused.desired_state == "PAUSED"

    for _ in range(200):
        if len(stream.price_entries.get(plans[0].stream_key, {})) == 2:
            break
        await asyncio.sleep(0)
    else:
        raise AssertionError("paused relay publication was not observed")

    assert False in observed.evaluate_flags
    await service.stop()


@pytest.mark.asyncio
async def test_paused_lifecycle_rebuild_keeps_fresh_relay_active_and_lanes_disabled() -> (
    None
):
    bars = (_bar(0), _bar(1), _bar(2))

    class _History:
        def __init__(self) -> None:
            self.startup_cutoff = bars[0].bar_close_at
            self.full = InMemoryCanonicalMarketHistoryRepository(
                {SERIES: bars},
                timeframe_grid=GRID,
            )

        async def fetch_latest_cutoff(self, key):
            del key
            return self.startup_cutoff

        async def fetch_record_at(self, key, bar_open_at):
            return await self.full.fetch_record_at(key, bar_open_at)

        async def fetch_bars(self, key, **kwargs):
            return await self.full.fetch_bars(key, **kwargs)

    class _Lifecycle:
        def __init__(self) -> None:
            self.cursor = "0-0"
            self.release = asyncio.Event()
            self.sent = False

        async def read_once(self):
            if not self.sent:
                await self.release.wait()
                self.sent = True
                self.cursor = "1-0"
                return LifecycleReadResult(
                    cursor=self.cursor,
                    event_ids=("1-0",),
                    relevant_events=(object(),),  # type: ignore[arg-type]
                )
            await asyncio.sleep(0)
            return LifecycleReadResult(cursor=self.cursor)

    history = _History()
    lifecycle = _Lifecycle()
    stream = _RelayClient(bars)
    runtimes: list[tuple[int, object]] = []
    plans = compile_price_relay_plans(_config())

    async def factory(*, reason: str, generation_id: int) -> DecisionRuntimeGeneration:
        del reason
        startup = await DecisionStartupCoordinator(
            decision_config=_config(),
            plugin_catalog=PluginCatalog([]),
            feature_catalog=FeatureCatalog([]),
            feature_policy=FeaturePolicy(name="operator", version="1"),
            data_policy=DataPolicy(name="operator", version="1", concepts={}),
            source_catalog=DataSourceCatalog([]),
            runtime_plugin_catalog=RuntimePluginCatalog([]),
            history_repository=history,
            stream_client=stream,
            data_resolver=DataResolver(DataSourceCatalog([])),
        ).start()
        relay = PriceRelay(
            plans=plans,
            stream_client=stream,
            history_repository=history,
            timeframe_grid=GRID,
            warm_cutoffs={SERIES: bars[0 if generation_id == 1 else 1].bar_close_at},
            batch_size=1,
        )
        runtime = LiveDecisionRuntime(
            startup=startup,
            timeframe_grid=GRID,
            stream_client=stream,
            history_repository=history,
            price_relay=relay,
            batch_size=1,
            block_ms=0,
        )
        runtime._evaluate_flags = []
        original_poll = runtime.poll_once

        async def observed_poll(*, evaluate_lanes: bool = True):
            runtime._evaluate_flags.append(evaluate_lanes)
            return await original_poll(evaluate_lanes=evaluate_lanes)

        runtime.poll_once = observed_poll
        runtimes.append((generation_id, runtime))
        return DecisionRuntimeGeneration(
            generation_id=generation_id,
            created_at=BASE,
            startup=startup,
            live_runtime=runtime,
        )

    service = DecisionService(
        generation_factory=factory,
        lifecycle_reader=lifecycle,
        configured_asset_count=1,
        block_ms=0,
        now_fn=lambda: BASE,
    )
    await service.start()
    for _ in range(200):
        if len(stream.price_entries.get(plans[0].stream_key, {})) == 1:
            break
        await asyncio.sleep(0)
    else:
        raise AssertionError("initial relay publication was not observed")

    paused = await service.pause()
    assert paused.service_state == "PAUSED"
    assert paused.desired_state == "PAUSED"
    history.startup_cutoff = bars[1].bar_close_at
    lifecycle.release.set()

    for _ in range(200):
        if service.snapshot().generation_id == 2:
            break
        await asyncio.sleep(0)
    else:
        raise AssertionError("lifecycle generation rebuild was not observed")

    stream.pending.append(("2-0", _ingestion_fields(bars[2])))
    for _ in range(200):
        if len(stream.price_entries.get(plans[0].stream_key, {})) == 2:
            break
        await asyncio.sleep(0)
    else:
        raise AssertionError("fresh paused generation did not relay price")

    snapshot = service.snapshot()
    assert snapshot.service_state == "PAUSED"
    assert snapshot.desired_state == "PAUSED"
    assert runtimes[1][1].lanes == {}
    assert all(
        evaluate is False
        for runtime in runtimes[1:]
        for evaluate in getattr(runtime, "_evaluate_flags", ())
    )
    await service.stop()
