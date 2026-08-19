from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.decision_app.composition import sr_initialization_requirement
from apps.decision_app.data.resolver import DataPolicy, DataResolver, DataSourceCatalog
from apps.decision_app.domain.market_state import MarketSeriesKey, TimeframeGrid
from apps.decision_app.features.definitions import SR_ATR_DEFINITION
from apps.decision_app.features.planning import (
    FeatureCatalog,
    FeatureHistoryRequirement,
    FeaturePolicy,
    SharedFeatureDefinition,
)
from apps.decision_app.planning.catalog import PluginCatalog
from apps.decision_app.runtime.live import LiveDecisionRuntime
from apps.decision_app.runtime.plugins import (
    RuntimePluginCatalog,
    RuntimePluginDefinition,
)
from apps.decision_app.runtime.startup import DecisionStartupCoordinator
from apps.decision_app.settings import (
    CanonicalInstrument,
    DecisionAssetSettings,
    DecisionConfig,
    DecisionGlobalSettings,
    DecisionLaneSettings,
    DecisionPolicySettings,
)
from apps.decision_app.storage.checkpoints import (
    CheckpointSaveResult,
    InMemoryCheckpointRepository,
)
from apps.decision_app.storage.market_history import (
    InMemoryCanonicalMarketHistoryRepository,
)
from apps.decision_app.storage.shadow_progress import (
    InMemoryShadowProgressRepository,
    ShadowProgressSaveResult,
)
from apps.decision_app.transport.ingestion import canonical_ingestion_stream_key
from apps.decision_app.transport.shadow import (
    ShadowPublicationEnvelope,
    ValkeyShadowPublisher,
    build_shadow_envelope,
    shadow_payload_fingerprint,
    shadow_stream_entry_id,
    shadow_stream_key,
)
from apps.decision_app.transport.signals import ValkeySignalPublisher
from libs.contracts.decision import (
    CausalBarView,
    DecisionContext,
    FeatureRequirement,
    ModelArtifact,
    ModelDecision,
    ModelOutcome,
    ModelRequestContext,
    ModelSpec,
)
from libs.contracts.serialization import valkey_decode
from libs.contracts.signal import TradeSignal
from libs.models.sr.adapters.decision_plugin import SR_MODEL_SPEC, SRDecisionPlugin
from tests.decision.test_d9a_real_sr_startup import (
    GRID as SR_GRID,
)
from tests.decision.test_d9a_real_sr_startup import (
    RAW_SR_CONFIG,
)
from tests.decision.test_d9a_real_sr_startup import (
    SERIES as SR_SERIES,
)
from tests.decision.test_d9a_real_sr_startup import (
    _bar as sr_bar,
)
from tests.decision.test_d9a_real_sr_startup import (
    _stream_fields as sr_stream_fields,
)

SIGNAL_BASE = datetime(2026, 2, 1, tzinfo=UTC)
SIGNAL_GRID = TimeframeGrid(
    alignment_origin=SIGNAL_BASE,
    durations={"1h": timedelta(hours=1)},
)
SIGNAL_SERIES = MarketSeriesKey(
    asset="BTCUSDT",
    venue="binance",
    instrument_id="BTC-USDT-PERP",
    timeframe="1h",
)
PROJECTED_BASE = datetime(2026, 2, 1, tzinfo=UTC)
PROJECTED_GRID = TimeframeGrid(
    alignment_origin=PROJECTED_BASE,
    durations={"1h": timedelta(hours=1), "4h": timedelta(hours=4)},
)
PROJECTED_TRIGGER_SERIES = MarketSeriesKey(
    asset="BTCUSDT",
    venue="binance",
    instrument_id="BTC-USDT-PERP",
    timeframe="1h",
)
PROJECTED_DECISION_SERIES = MarketSeriesKey(
    asset="BTCUSDT",
    venue="binance",
    instrument_id="BTC-USDT-PERP",
    timeframe="4h",
)


SIGNAL_SPEC = ModelSpec(
    name="test-decision",
    version="1",
    stateful=False,
    output_kind="decision_capable",
    produces_artifact_type="test-decision.v1",
    supported_trigger_modes=("on_bar_close",),
)


class _SignalPlugin:
    spec = SIGNAL_SPEC

    def data_requests(
        self,
        base_context: ModelRequestContext,
        state_snapshot: object | None = None,
    ) -> tuple[()]:
        return ()

    def evaluate(
        self,
        context: DecisionContext,
        state_snapshot: object | None = None,
    ) -> ModelOutcome:
        decision = ModelDecision(
            binding_id=context.binding_id,
            asset=context.asset,
            decision_timeframe=context.decision_timeframe,
            trigger_timeframe=context.trigger_timeframe,
            market_as_of=context.market_as_of,
            signal_time=context.market_as_of,
            direction_hint=1,
            conviction=0.75,
        )
        return ModelOutcome(
            artifact=ModelArtifact(
                binding_id=context.binding_id,
                lane_id=context.lane_id,
                asset=context.asset,
                decision_timeframe=context.decision_timeframe,
                trigger_timeframe=context.trigger_timeframe,
                market_as_of=context.market_as_of,
                artifact_type=SIGNAL_SPEC.produces_artifact_type,
            ),
            decision=decision,
        )


SIGNAL_HISTORY_SPEC = ModelSpec(
    name="test-decision",
    version="1",
    stateful=False,
    output_kind="decision_capable",
    produces_artifact_type="test-decision.v1",
    supported_trigger_modes=("on_bar_close",),
    intrinsic_feature_requirements=(FeatureRequirement(name="HISTORY"),),
)


class _HistorySignalPlugin(_SignalPlugin):
    spec = SIGNAL_HISTORY_SPEC


def _signal_bar(index: int) -> CausalBarView:
    opened = SIGNAL_BASE + timedelta(hours=index)
    closed = opened + timedelta(hours=1)
    close = Decimal(101 + index)
    return CausalBarView(
        timeframe="1h",
        bar_open_at=opened,
        bar_close_at=closed,
        market_as_of=closed,
        open=close - Decimal(1),
        high=close + Decimal(2),
        low=close - Decimal(2),
        close=close,
        volume=Decimal(10),
        taker_buy_base=Decimal(4),
        closed=True,
    )


def _signal_fields(index: int) -> dict[str, str]:
    bar = _signal_bar(index)
    payload = {
        "venue": SIGNAL_SERIES.venue,
        "instrument_id": SIGNAL_SERIES.instrument_id,
        "timeframe": SIGNAL_SERIES.timeframe,
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
        "event_id": f"signal-event-{index}",
        "event_type": "candle.committed",
        "schema_version": "1",
        "producer": "ingestion",
        "occurred_at": bar.bar_close_at.isoformat().replace("+00:00", "Z"),
        "payload": json.dumps(payload),
    }


def _projected_bar(key: MarketSeriesKey, index: int) -> CausalBarView:
    duration = PROJECTED_GRID.duration(key.timeframe)
    opened = PROJECTED_BASE + duration * index
    closed = opened + duration
    close = Decimal(200 + index)
    return CausalBarView(
        timeframe=key.timeframe,
        bar_open_at=opened,
        bar_close_at=closed,
        market_as_of=closed,
        open=close - Decimal(1),
        high=close + Decimal(2),
        low=close - Decimal(2),
        close=close,
        volume=Decimal(10),
        taker_buy_base=Decimal(4),
        closed=True,
    )


def _projected_fields(key: MarketSeriesKey, index: int) -> dict[str, str]:
    bar = _projected_bar(key, index)
    payload = {
        "venue": key.venue,
        "instrument_id": key.instrument_id,
        "timeframe": key.timeframe,
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
        "event_id": f"projected-event-{key.timeframe}-{index}",
        "event_type": "candle.committed",
        "schema_version": "1",
        "producer": "ingestion",
        "occurred_at": bar.bar_close_at.isoformat().replace("+00:00", "Z"),
        "payload": json.dumps(payload),
    }


class _LiveInputClient:
    def __init__(self, *, stream: str, tail_index: int, field_factory) -> None:
        self.stream = stream
        self.tail_index = tail_index
        self.field_factory = field_factory
        self.pending: list[tuple[str, Mapping[object, object]]] = []
        self.xread_calls: list[tuple[dict[str, str], int, int]] = []

    async def xrevrange(
        self, stream: str, *_args: object, count: int = 1
    ) -> list[tuple[str, Mapping[object, object]]]:
        assert stream == self.stream
        assert count == 1
        return [(f"{self.tail_index}-0", self.field_factory(self.tail_index))]

    async def xread(
        self,
        streams: Mapping[str, str],
        *,
        count: int,
        block: int,
    ) -> list[tuple[str, list[tuple[str, Mapping[object, object]]]]]:
        self.xread_calls.append((dict(streams), count, block))
        if not self.pending:
            return []
        pending = self.pending
        self.pending = []
        return [(self.stream, pending)]


class _MultiStreamInputClient:
    def __init__(
        self, tails: Mapping[str, tuple[str, Mapping[object, object]]]
    ) -> None:
        self.tails = dict(tails)
        self.pending: dict[str, list[tuple[str, Mapping[object, object]]]] = {
            stream: [] for stream in tails
        }

    async def xrevrange(
        self, stream: str, *_args: object, count: int = 1
    ) -> list[tuple[str, Mapping[object, object]]]:
        assert count == 1
        return [self.tails[stream]]

    async def xread(
        self,
        streams: Mapping[str, str],
        *,
        count: int,
        block: int,
    ) -> list[tuple[str, list[tuple[str, Mapping[object, object]]]]]:
        del streams, count, block
        result = []
        for stream, entries in self.pending.items():
            if entries:
                result.append((stream, entries[:]))
                entries.clear()
        return result


class _IsolatedSignalClient:
    def __init__(self) -> None:
        self.entries: dict[str, dict[str, Mapping[object, object]]] = {}
        self.fail_xadd = False
        self.xadd_calls = 0

    async def xrange(self, stream: str, minimum: str, maximum: str):
        values = self.entries.get(stream, {})
        return [
            (entry_id, fields)
            for entry_id, fields in values.items()
            if entry_id == minimum == maximum
        ]

    async def xrevrange(self, stream: str, *_args: object, count: int = 1):
        values = self.entries.get(stream, {})
        ordered = sorted(
            values,
            key=lambda value: tuple(int(part) for part in value.split("-")),
            reverse=True,
        )
        return [(entry_id, values[entry_id]) for entry_id in ordered[:count]]

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
        self.xadd_calls += 1
        if self.fail_xadd:
            raise RuntimeError("broker unavailable")
        values = self.entries.setdefault(stream, {})
        if id in values:
            raise RuntimeError("duplicate explicit ID")
        if values:
            head = max(
                values,
                key=lambda value: tuple(int(part) for part in value.split("-")),
            )
            if tuple(int(part) for part in id.split("-")) <= tuple(
                int(part) for part in head.split("-")
            ):
                raise RuntimeError("stream ID is not forward")
        values[id] = fields
        return id


class _RaisingPublisher:
    async def publish(self, envelope: object) -> None:
        del envelope
        raise RuntimeError("broker unavailable")


class _FailingLiveCheckpointRepository(InMemoryCheckpointRepository):
    def __init__(self) -> None:
        super().__init__()
        self.fail_live = False

    async def save(self, checkpoint):
        if self.fail_live:
            return CheckpointSaveResult.CONFLICT
        return await super().save(checkpoint)


class _RaisingPolicy:
    def evaluate(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("policy boundary failed")


def _sr_coordinator(
    history: InMemoryCanonicalMarketHistoryRepository,
    checkpoints: InMemoryCheckpointRepository,
    stream_client: _LiveInputClient,
) -> DecisionStartupCoordinator:
    source_catalog = DataSourceCatalog([])
    return DecisionStartupCoordinator(
        decision_config=_sr_config(),
        plugin_catalog=PluginCatalog([SR_MODEL_SPEC]),
        feature_catalog=FeatureCatalog([SR_ATR_DEFINITION]),
        feature_policy=FeaturePolicy(
            name="operator", version="1", allowed_features=("ATR",)
        ),
        data_policy=DataPolicy(name="operator", version="1", concepts={}),
        source_catalog=source_catalog,
        runtime_plugin_catalog=RuntimePluginCatalog(
            [
                RuntimePluginDefinition(
                    plugin_name="sr",
                    plugin_version="1",
                    factory=SRDecisionPlugin,
                    initialization_requirement=sr_initialization_requirement,
                )
            ]
        ),
        history_repository=history,
        stream_client=stream_client,
        checkpoint_repository=checkpoints,
        data_resolver=DataResolver(source_catalog),
    )


def _sr_config() -> DecisionConfig:
    lane = DecisionLaneSettings(
        decision_timeframe="1h",
        trigger_timeframe="1h",
        trigger_mode="on_bar_close",
        authority="authoritative",
        risk_profile_key="sr-test",
        policy=DecisionPolicySettings(
            name="passthrough",
            version="1",
            parameters={"source_slot": "sr_primary"},
        ),
        bindings={
            "sr_primary": {
                "plugin": "sr",
                "version": "1",
                "parameters": {"sr_config": RAW_SR_CONFIG},
            }
        },
    )
    asset = DecisionAssetSettings(
        manifest_asset="BTC",
        decision_asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        lanes={"main": lane},
    )
    return DecisionConfig(
        global_settings=DecisionGlobalSettings(),
        assets={"BTC": asset},
        timeframe_grid=SR_GRID,
        instruments={
            "BTC": CanonicalInstrument(
                manifest_asset="BTC",
                instrument_id="BTC-USDT-PERP",
                venue="binance",
                timeframes=("1h",),
            )
        },
    )


def _signal_config(*, authority: str = "authoritative") -> DecisionConfig:
    lane = DecisionLaneSettings(
        decision_timeframe="1h",
        trigger_timeframe="1h",
        trigger_mode="on_bar_close",
        authority=authority,
        risk_profile_key="test-risk" if authority == "authoritative" else None,
        policy=DecisionPolicySettings(
            name="passthrough",
            version="1",
            parameters={"source_slot": "decision"},
        ),
        bindings={
            "decision": {
                "plugin": "test-decision",
                "version": "1",
            }
        },
    )
    asset = DecisionAssetSettings(
        manifest_asset="BTC",
        decision_asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        lanes={"main": lane},
    )
    return DecisionConfig(
        global_settings=DecisionGlobalSettings(),
        assets={"BTC": asset},
        timeframe_grid=SIGNAL_GRID,
        instruments={
            "BTC": CanonicalInstrument(
                manifest_asset="BTC",
                instrument_id="BTC-USDT-PERP",
                venue="binance",
                timeframes=("1h",),
            )
        },
    )


def _signal_coordinator(
    history: InMemoryCanonicalMarketHistoryRepository,
    stream_client: _LiveInputClient,
    *,
    authority: str = "authoritative",
    shadow_progress_repository: InMemoryShadowProgressRepository | None = None,
    history_capacity: int | None = None,
) -> DecisionStartupCoordinator:
    source_catalog = DataSourceCatalog([])
    if history_capacity is None:
        plugin_spec = SIGNAL_SPEC
        feature_catalog = FeatureCatalog([])
        feature_policy = FeaturePolicy(
            name="operator", version="1", allowed_features=()
        )
        plugin_factory = lambda _parameters: _SignalPlugin()
    else:
        plugin_spec = SIGNAL_HISTORY_SPEC
        feature_catalog = FeatureCatalog(
            [
                SharedFeatureDefinition(
                    name="HISTORY",
                    version="1",
                    calculator=lambda _context: 1,
                    history_requirements=(
                        FeatureHistoryRequirement(
                            source="trigger", timeframe=None, bars=history_capacity
                        ),
                    ),
                )
            ]
        )
        feature_policy = FeaturePolicy(
            name="operator", version="1", allowed_features=("HISTORY",)
        )
        plugin_factory = lambda _parameters: _HistorySignalPlugin()
    return DecisionStartupCoordinator(
        decision_config=_signal_config(authority=authority),
        plugin_catalog=PluginCatalog([plugin_spec]),
        feature_catalog=feature_catalog,
        feature_policy=feature_policy,
        data_policy=DataPolicy(name="operator", version="1", concepts={}),
        source_catalog=source_catalog,
        runtime_plugin_catalog=RuntimePluginCatalog(
            [
                RuntimePluginDefinition(
                    plugin_name="test-decision",
                    plugin_version="1",
                    factory=plugin_factory,
                )
            ]
        ),
        history_repository=history,
        stream_client=stream_client,
        data_resolver=DataResolver(source_catalog),
        shadow_progress_repository=shadow_progress_repository,
    )


def _projected_coordinator(
    history: InMemoryCanonicalMarketHistoryRepository,
    stream_client: _MultiStreamInputClient,
) -> DecisionStartupCoordinator:
    lane = DecisionLaneSettings(
        decision_timeframe="4h",
        trigger_timeframe="1h",
        trigger_mode="on_bar_close",
        authority="authoritative",
        risk_profile_key="projected-test",
        policy=DecisionPolicySettings(
            name="passthrough",
            version="1",
            parameters={"source_slot": "decision"},
        ),
        bindings={
            "decision": {
                "plugin": "test-decision",
                "version": "1",
            }
        },
    )
    asset = DecisionAssetSettings(
        manifest_asset="BTC",
        decision_asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        lanes={"main": lane},
    )
    config = DecisionConfig(
        global_settings=DecisionGlobalSettings(),
        assets={"BTC": asset},
        timeframe_grid=PROJECTED_GRID,
        instruments={
            "BTC": CanonicalInstrument(
                manifest_asset="BTC",
                instrument_id="BTC-USDT-PERP",
                venue="binance",
                timeframes=("1h", "4h"),
            )
        },
    )
    source_catalog = DataSourceCatalog([])
    return DecisionStartupCoordinator(
        decision_config=config,
        plugin_catalog=PluginCatalog([SIGNAL_SPEC]),
        feature_catalog=FeatureCatalog([]),
        feature_policy=FeaturePolicy(name="operator", version="1", allowed_features=()),
        data_policy=DataPolicy(name="operator", version="1", concepts={}),
        source_catalog=source_catalog,
        runtime_plugin_catalog=RuntimePluginCatalog(
            [
                RuntimePluginDefinition(
                    plugin_name="test-decision",
                    plugin_version="1",
                    factory=lambda _parameters: _SignalPlugin(),
                )
            ]
        ),
        history_repository=history,
        stream_client=stream_client,
        data_resolver=DataResolver(source_catalog),
    )


@pytest.mark.asyncio
async def test_real_sr_live_no_signal_commits_and_checkpoints_in_order() -> None:
    checkpoints = InMemoryCheckpointRepository()
    history = InMemoryCanonicalMarketHistoryRepository(
        {SR_SERIES: tuple(sr_bar(index) for index in range(50))},
        timeframe_grid=SR_GRID,
    )
    stream = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=49,
        field_factory=sr_stream_fields,
    )
    startup = await _sr_coordinator(history, checkpoints, stream).start()
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SR_GRID,
        stream_client=stream,
        history_repository=history,
        checkpoint_repository=checkpoints,
        now_fn=lambda: datetime(2026, 2, 1, tzinfo=UTC),
    )

    stream.pending.append(("50-0", sr_stream_fields(50)))
    result = await runtime.poll_once()

    lane = result.lane_results["BTCUSDT:main"]
    assert result.input_results[0].disposition == "INSERTED"
    assert lane.status == "LIVE"
    assert lane.policy_status == "NO_SIGNAL"
    assert lane.finalization_status == "COMMITTED"
    assert lane.checkpoint_result == "UPDATED"
    assert runtime.lanes["BTCUSDT:main"].finalizer.watermark.latest_market_as_of == (
        sr_bar(50).market_as_of
    )
    checkpoint = await checkpoints.load(
        next(iter(startup.runtimes.values())).identity,
        expected_binding_ids=next(iter(startup.runtimes.values())).stateful_binding_ids,
    )
    assert checkpoint is not None
    assert checkpoint.market_as_of == sr_bar(50).market_as_of
    binding_id = next(iter(startup.runtimes.values())).stateful_binding_ids[0]
    committed_state = (
        runtime.lanes["BTCUSDT:main"]
        .runtime.state_store.get(binding_id)
        .committed_state
    )
    assert checkpoint.state_by_binding[binding_id] == committed_state

    stream.pending.append(("51-0", sr_stream_fields(51)))
    second = await runtime.poll_once()
    assert second.lane_results["BTCUSDT:main"].finalization_status == "COMMITTED"
    assert second.lane_results["BTCUSDT:main"].checkpoint_result == "UPDATED"
    assert runtime.lanes["BTCUSDT:main"].finalizer.watermark.latest_market_as_of == (
        sr_bar(51).market_as_of
    )


@pytest.mark.asyncio
async def test_signal_path_publishes_exact_id_then_finalizes() -> None:
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(3))},
        timeframe_grid=SIGNAL_GRID,
    )
    input_stream = "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h"
    stream = _LiveInputClient(
        stream=input_stream,
        tail_index=2,
        field_factory=_signal_fields,
    )
    startup = await _signal_coordinator(history, stream).start()
    publisher_client = _IsolatedSignalClient()
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        signal_publisher=ValkeySignalPublisher(publisher_client),
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )
    stream.pending.append(("3-0", _signal_fields(3)))
    result = await runtime.poll_once()
    lane = result.lane_results["BTCUSDT:main"]

    assert lane.status == "LIVE"
    assert lane.policy_status == "SIGNAL"
    assert lane.publication_outcome == "PUBLISHED"
    assert lane.finalization_status == "COMMITTED"
    assert runtime.lanes["BTCUSDT:main"].finalizer.watermark.latest_market_as_of == (
        _signal_bar(3).market_as_of
    )
    stream_key = "signals:BTCUSDT:1h"
    entries = publisher_client.entries[stream_key]
    assert tuple(entries) == (
        f"{int(_signal_bar(3).market_as_of.timestamp() * 1000)}-0",
    )
    signal = valkey_decode(next(iter(entries.values())), TradeSignal)
    assert signal.timestamp == _signal_bar(3).market_as_of.timestamp()
    assert signal.model_name == "test-risk"
    assert signal.price == float(_signal_bar(3).close)


@pytest.mark.asyncio
async def test_shadow_signal_uses_only_shadow_transport_and_commits_shadow() -> None:
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(3))},
        timeframe_grid=SIGNAL_GRID,
    )
    input_stream = "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h"
    stream = _LiveInputClient(
        stream=input_stream,
        tail_index=2,
        field_factory=_signal_fields,
    )
    startup = await _signal_coordinator(history, stream, authority="shadow").start()
    publisher_client = _IsolatedSignalClient()
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        shadow_publisher=ValkeyShadowPublisher(publisher_client),
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )

    stream.pending.append(("3-0", _signal_fields(3)))
    result = await runtime.poll_once()
    lane = result.lane_results["BTCUSDT:main"]

    assert lane.policy_status == "SIGNAL"
    assert lane.publication_outcome == "PUBLISHED"
    assert lane.finalization_status == "COMMITTED"
    assert (
        runtime.lanes["BTCUSDT:main"].finalizer.watermark.last_disposition == "shadow"
    )
    assert "decision:shadow:BTCUSDT:main" in publisher_client.entries
    assert not any(key.startswith("signals:") for key in publisher_client.entries)


@pytest.mark.asyncio
async def test_shadow_startup_persists_exact_baseline_without_backfill() -> None:
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(4))},
        timeframe_grid=SIGNAL_GRID,
    )
    stream = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=2,
        field_factory=_signal_fields,
    )
    progress = InMemoryShadowProgressRepository()

    first = await _signal_coordinator(
        history,
        stream,
        authority="shadow",
        shadow_progress_repository=progress,
    ).start()
    identity = next(iter(first.runtimes.values())).identity
    saved = await progress.load(identity)

    assert saved is not None
    assert saved.market_as_of == _signal_bar(3).market_as_of
    assert saved.last_disposition is None
    assert first.lane_catchup_cutoffs["BTCUSDT:main"] == ()
    assert first.snapshot.lane_watermarks["BTCUSDT:main"].latest_market_as_of == (
        _signal_bar(3).market_as_of
    )

    second = await _signal_coordinator(
        history,
        stream,
        authority="shadow",
        shadow_progress_repository=progress,
    ).start()
    assert second.lane_catchup_cutoffs["BTCUSDT:main"] == ()
    assert await progress.load(identity) == saved


@pytest.mark.asyncio
async def test_shadow_restart_drains_exact_catchup_before_new_input() -> None:
    progress = InMemoryShadowProgressRepository()
    first_history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(4))},
        timeframe_grid=SIGNAL_GRID,
    )
    first_stream = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=2,
        field_factory=_signal_fields,
    )
    first = await _signal_coordinator(
        first_history,
        first_stream,
        authority="shadow",
        shadow_progress_repository=progress,
        history_capacity=4,
    ).start()
    identity = next(iter(first.runtimes.values())).identity
    baseline = await progress.load(identity)
    assert baseline is not None

    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(8))},
        timeframe_grid=SIGNAL_GRID,
    )
    stream = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=6,
        field_factory=_signal_fields,
    )
    startup = await _signal_coordinator(
        history,
        stream,
        authority="shadow",
        shadow_progress_repository=progress,
        history_capacity=4,
    ).start()

    assert startup.lane_catchup_cutoffs["BTCUSDT:main"] == tuple(
        _signal_bar(index).market_as_of for index in range(4, 8)
    )
    assert startup.snapshot.lane_watermarks["BTCUSDT:main"].latest_market_as_of == (
        baseline.market_as_of
    )

    publisher_client = _IsolatedSignalClient()
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        shadow_publisher=ValkeyShadowPublisher(publisher_client),
        shadow_progress_repository=progress,
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )
    result = await runtime.poll_once()

    lane = result.lane_results["BTCUSDT:main"]
    assert lane.finalization_status == "COMMITTED"
    assert runtime.lanes["BTCUSDT:main"].finalizer.watermark.latest_market_as_of == (
        _signal_bar(7).market_as_of
    )
    saved = await progress.load(identity)
    assert saved is not None
    assert saved.market_as_of == _signal_bar(7).market_as_of
    assert saved.last_disposition == "shadow"
    assert len(publisher_client.entries["decision:shadow:BTCUSDT:main"]) == 4
    assert not any(key.startswith("signals:") for key in publisher_client.entries)

    restarted = await _signal_coordinator(
        history,
        stream,
        authority="shadow",
        shadow_progress_repository=progress,
        history_capacity=4,
    ).start()
    assert restarted.lane_catchup_cutoffs["BTCUSDT:main"] == ()


@pytest.mark.asyncio
async def test_shadow_catchup_exact_id_reconciles_crash_window() -> None:
    progress = InMemoryShadowProgressRepository()
    first_history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(4))},
        timeframe_grid=SIGNAL_GRID,
    )
    first_stream = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=2,
        field_factory=_signal_fields,
    )
    await _signal_coordinator(
        first_history,
        first_stream,
        authority="shadow",
        shadow_progress_repository=progress,
        history_capacity=1,
    ).start()
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(5))},
        timeframe_grid=SIGNAL_GRID,
    )
    stream = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=3,
        field_factory=_signal_fields,
    )
    startup = await _signal_coordinator(
        history,
        stream,
        authority="shadow",
        shadow_progress_repository=progress,
        history_capacity=1,
    ).start()
    publisher_client = _IsolatedSignalClient()
    first_runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        shadow_publisher=ValkeyShadowPublisher(publisher_client),
        shadow_progress_repository=progress,
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )
    # The first process publishes the exact observation but loses the progress
    # write, which is the crash window repaired by the next startup.
    original_save = progress.save
    failed_once = True

    async def fail_progress_save(item):
        nonlocal failed_once
        if failed_once and item.last_disposition == "shadow":
            failed_once = False
            return ShadowProgressSaveResult.CONFLICT
        return await original_save(item)

    progress.save = fail_progress_save  # type: ignore[method-assign]
    result = await first_runtime.poll_once()
    assert result.lane_results["BTCUSDT:main"].status == "HALTED"
    assert len(publisher_client.entries["decision:shadow:BTCUSDT:main"]) == 1

    progress.save = original_save  # type: ignore[method-assign]
    restarted = await _signal_coordinator(
        history,
        stream,
        authority="shadow",
        shadow_progress_repository=progress,
        history_capacity=1,
    ).start()
    assert restarted.lane_catchup_cutoffs["BTCUSDT:main"] == (
        _signal_bar(4).market_as_of,
    )
    second_runtime = LiveDecisionRuntime(
        startup=restarted,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        shadow_publisher=ValkeyShadowPublisher(publisher_client),
        shadow_progress_repository=progress,
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )
    second = await second_runtime.poll_once()
    assert second.lane_results["BTCUSDT:main"].publication_outcome == (
        "ALREADY_IDENTICAL"
    )
    assert len(publisher_client.entries["decision:shadow:BTCUSDT:main"]) == 1
    saved = await progress.load(next(iter(restarted.runtimes.values())).identity)
    assert saved is not None
    assert saved.market_as_of == _signal_bar(4).market_as_of


@pytest.mark.asyncio
async def test_shadow_preflight_failure_never_calls_publisher(monkeypatch) -> None:
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(3))},
        timeframe_grid=SIGNAL_GRID,
    )
    input_stream = "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h"
    stream = _LiveInputClient(
        stream=input_stream,
        tail_index=2,
        field_factory=_signal_fields,
    )
    startup = await _signal_coordinator(history, stream, authority="shadow").start()
    publisher_client = _IsolatedSignalClient()
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        shadow_publisher=ValkeyShadowPublisher(publisher_client),
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )

    import apps.decision_app.runtime.live as live_module

    canonical_builder = build_shadow_envelope

    def forged_builder(lane, prepared, evaluation):
        canonical = canonical_builder(lane, prepared, evaluation)
        observation = canonical.observation.model_copy(update={"policy_version": "999"})
        return ShadowPublicationEnvelope(
            decision_id=observation.decision_id,
            stream_key=shadow_stream_key(observation.lane_id),
            stream_entry_id=shadow_stream_entry_id(observation.market_as_of),
            observation=observation,
            payload_fingerprint=shadow_payload_fingerprint(observation),
        )

    monkeypatch.setattr(live_module, "build_shadow_envelope", forged_builder)
    stream.pending.append(("3-0", _signal_fields(3)))
    result = await runtime.poll_once()

    assert result.lane_results["BTCUSDT:main"].status == "HALTED"
    assert publisher_client.xadd_calls == 0
    assert not publisher_client.entries


@pytest.mark.asyncio
async def test_shadow_lane_without_shadow_publisher_fails_closed() -> None:
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(3))},
        timeframe_grid=SIGNAL_GRID,
    )
    input_stream = "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h"
    stream = _LiveInputClient(
        stream=input_stream,
        tail_index=2,
        field_factory=_signal_fields,
    )
    startup = await _signal_coordinator(history, stream, authority="shadow").start()
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )
    baseline_watermark = runtime.lanes["BTCUSDT:main"].finalizer.watermark

    stream.pending.append(("3-0", _signal_fields(3)))
    result = await runtime.poll_once()
    lane = result.lane_results["BTCUSDT:main"]

    assert lane.status == "HALTED"
    assert lane.publication_outcome is None
    assert lane.finalization_status is None
    assert runtime.lanes["BTCUSDT:main"].finalizer.watermark == baseline_watermark
    assert baseline_watermark.last_disposition is None


@pytest.mark.asyncio
async def test_valid_prefix_commits_before_later_malformed_suffix() -> None:
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(3))},
        timeframe_grid=SIGNAL_GRID,
    )
    input_stream = "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h"
    stream = _LiveInputClient(
        stream=input_stream,
        tail_index=2,
        field_factory=_signal_fields,
    )
    startup = await _signal_coordinator(history, stream).start()
    publisher_client = _IsolatedSignalClient()
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        signal_publisher=ValkeySignalPublisher(publisher_client),
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )

    malformed = _signal_fields(4)
    malformed["event_type"] = "not-a-candle"
    stream.pending.extend(
        [
            ("3-0", _signal_fields(3)),
            ("4-0", malformed),
            ("5-0", _signal_fields(5)),
        ]
    )

    result = await runtime.poll_once()
    lane = result.lane_results["BTCUSDT:main"]

    assert [(item.stream_id, item.disposition) for item in result.input_results] == [
        ("3-0", "INSERTED"),
        ("4-0", "MALFORMED"),
    ]
    assert lane.status == "RECONSTRUCTION_REQUIRED"
    assert lane.trigger_cutoff == _signal_bar(3).market_as_of
    assert lane.policy_status == "SIGNAL"
    assert lane.publication_outcome == "PUBLISHED"
    assert lane.finalization_status == "COMMITTED"
    assert runtime.input.cursor_for(input_stream).latest_stream_id == "3-0"
    assert runtime.input.blocked_streams[input_stream]
    assert len(publisher_client.entries["signals:BTCUSDT:1h"]) == 1

    # The suffix was never parsed and the blocked stream is not read again;
    # the committed prefix transaction remains the only publication.
    stream.pending.append(("5-0", _signal_fields(5)))
    after_failure = await runtime.poll_once()
    assert not after_failure.input_results
    assert after_failure.lane_results["BTCUSDT:main"].status == (
        "RECONSTRUCTION_REQUIRED"
    )
    assert runtime.input.cursor_for(input_stream).latest_stream_id == "3-0"
    assert len(publisher_client.entries["signals:BTCUSDT:1h"]) == 1


@pytest.mark.asyncio
async def test_live_input_preserves_per_stream_transport_order() -> None:
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(3))},
        timeframe_grid=SIGNAL_GRID,
    )
    input_stream = "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h"
    stream = _LiveInputClient(
        stream=input_stream,
        tail_index=0,
        field_factory=_signal_fields,
    )
    startup = await _signal_coordinator(history, stream).start()
    publisher_client = _IsolatedSignalClient()
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        signal_publisher=ValkeySignalPublisher(publisher_client),
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )

    stream.pending.extend(
        [
            ("10-0", _signal_fields(3)),
            ("11-0", _signal_fields(2)),
        ]
    )
    result = await runtime.poll_once()

    assert [item.disposition for item in result.input_results] == [
        "INSERTED",
        "ALREADY_REPRESENTED",
    ]
    lane = result.lane_results["BTCUSDT:main"]
    assert lane.status == "LIVE"
    assert lane.trigger_cutoff == _signal_bar(3).market_as_of
    assert lane.finalization_status == "COMMITTED"
    assert runtime.input.cursor_for(input_stream).latest_stream_id == "11-0"
    assert len(publisher_client.entries["signals:BTCUSDT:1h"]) == 1


@pytest.mark.asyncio
async def test_lane_poll_evidence_is_transaction_local() -> None:
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(3))},
        timeframe_grid=SIGNAL_GRID,
    )
    input_stream = "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h"
    stream = _LiveInputClient(
        stream=input_stream,
        tail_index=2,
        field_factory=_signal_fields,
    )
    startup = await _signal_coordinator(history, stream).start()
    publisher_client = _IsolatedSignalClient()
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        signal_publisher=ValkeySignalPublisher(publisher_client),
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )

    stream.pending.append(("3-0", _signal_fields(3)))
    successful = await runtime.poll_once()
    success_lane = successful.lane_results["BTCUSDT:main"]
    assert success_lane.trigger_cutoff == _signal_bar(3).market_as_of
    assert success_lane.publication_outcome == "PUBLISHED"
    assert success_lane.finalization_status == "COMMITTED"

    idle = await runtime.poll_once()
    idle_lane = idle.lane_results["BTCUSDT:main"]
    assert idle_lane.trigger_cutoff is None
    assert idle_lane.policy_status is None
    assert idle_lane.publication_outcome is None
    assert idle_lane.finalization_status is None
    assert idle_lane.checkpoint_result is None

    runtime._publisher = _RaisingPublisher()
    stream.pending.append(("4-0", _signal_fields(4)))
    failed = await runtime.poll_once()
    failed_lane = failed.lane_results["BTCUSDT:main"]

    assert failed_lane.status == "HALTED"
    assert failed_lane.trigger_cutoff == _signal_bar(4).market_as_of
    assert failed_lane.policy_status == "SIGNAL"
    assert failed_lane.publication_outcome is None
    assert failed_lane.finalization_status is None
    assert failed_lane.checkpoint_result is None


@pytest.mark.asyncio
async def test_same_cutoff_context_and_trigger_are_applied_before_evaluation() -> None:
    trigger_stream = canonical_ingestion_stream_key(PROJECTED_TRIGGER_SERIES)
    decision_stream = canonical_ingestion_stream_key(PROJECTED_DECISION_SERIES)
    history = InMemoryCanonicalMarketHistoryRepository(
        {
            PROJECTED_TRIGGER_SERIES: tuple(
                _projected_bar(PROJECTED_TRIGGER_SERIES, index) for index in range(7)
            ),
            PROJECTED_DECISION_SERIES: (_projected_bar(PROJECTED_DECISION_SERIES, 0),),
        },
        timeframe_grid=PROJECTED_GRID,
    )
    stream = _MultiStreamInputClient(
        {
            trigger_stream: ("6-0", _projected_fields(PROJECTED_TRIGGER_SERIES, 6)),
            decision_stream: ("0-0", _projected_fields(PROJECTED_DECISION_SERIES, 0)),
        }
    )
    startup = await _projected_coordinator(history, stream).start()
    publisher_client = _IsolatedSignalClient()
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=PROJECTED_GRID,
        stream_client=stream,
        history_repository=history,
        signal_publisher=ValkeySignalPublisher(publisher_client),
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )

    # Return the trigger first even though the stream-key sort order is not
    # the same as the transport response order.
    stream.pending[trigger_stream].append(
        ("10-0", _projected_fields(PROJECTED_TRIGGER_SERIES, 7))
    )
    stream.pending[decision_stream].append(
        ("20-0", _projected_fields(PROJECTED_DECISION_SERIES, 1))
    )

    result = await runtime.poll_once()
    lane = result.lane_results["BTCUSDT:main"]

    assert [item.disposition for item in result.input_results] == [
        "INSERTED",
        "INSERTED",
    ]
    assert lane.status == "LIVE"
    assert (
        lane.trigger_cutoff == _projected_bar(PROJECTED_TRIGGER_SERIES, 7).market_as_of
    )
    assert lane.finalization_status == "COMMITTED"
    assert len(publisher_client.entries["signals:BTCUSDT:4h"]) == 1


@pytest.mark.asyncio
async def test_pending_trigger_evaluates_after_context_stream_catches_up() -> None:
    trigger_stream = canonical_ingestion_stream_key(PROJECTED_TRIGGER_SERIES)
    decision_stream = canonical_ingestion_stream_key(PROJECTED_DECISION_SERIES)
    history = InMemoryCanonicalMarketHistoryRepository(
        {
            PROJECTED_TRIGGER_SERIES: tuple(
                _projected_bar(PROJECTED_TRIGGER_SERIES, index) for index in range(7)
            ),
            PROJECTED_DECISION_SERIES: (_projected_bar(PROJECTED_DECISION_SERIES, 0),),
        },
        timeframe_grid=PROJECTED_GRID,
    )
    stream = _MultiStreamInputClient(
        {
            trigger_stream: ("6-0", _projected_fields(PROJECTED_TRIGGER_SERIES, 6)),
            decision_stream: ("0-0", _projected_fields(PROJECTED_DECISION_SERIES, 0)),
        }
    )
    startup = await _projected_coordinator(history, stream).start()
    publisher_client = _IsolatedSignalClient()
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=PROJECTED_GRID,
        stream_client=stream,
        history_repository=history,
        signal_publisher=ValkeySignalPublisher(publisher_client),
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )

    stream.pending[trigger_stream].append(
        ("10-0", _projected_fields(PROJECTED_TRIGGER_SERIES, 7))
    )
    waiting = await runtime.poll_once()
    waiting_lane = waiting.lane_results["BTCUSDT:main"]
    assert waiting_lane.status == "WAITING"
    assert waiting_lane.finalization_status is None
    assert not publisher_client.entries

    stream.pending[decision_stream].append(
        ("20-0", _projected_fields(PROJECTED_DECISION_SERIES, 1))
    )
    ready = await runtime.poll_once()
    ready_lane = ready.lane_results["BTCUSDT:main"]
    assert ready_lane.status == "LIVE"
    assert ready_lane.finalization_status == "COMMITTED"
    assert len(publisher_client.entries["signals:BTCUSDT:4h"]) == 1


@pytest.mark.asyncio
async def test_pending_trigger_overrun_halts_without_skipping_state() -> None:
    trigger_stream = canonical_ingestion_stream_key(PROJECTED_TRIGGER_SERIES)
    decision_stream = canonical_ingestion_stream_key(PROJECTED_DECISION_SERIES)
    history = InMemoryCanonicalMarketHistoryRepository(
        {
            PROJECTED_TRIGGER_SERIES: tuple(
                _projected_bar(PROJECTED_TRIGGER_SERIES, index) for index in range(7)
            ),
            PROJECTED_DECISION_SERIES: (_projected_bar(PROJECTED_DECISION_SERIES, 0),),
        },
        timeframe_grid=PROJECTED_GRID,
    )
    stream = _MultiStreamInputClient(
        {
            trigger_stream: ("6-0", _projected_fields(PROJECTED_TRIGGER_SERIES, 6)),
            decision_stream: ("0-0", _projected_fields(PROJECTED_DECISION_SERIES, 0)),
        }
    )
    startup = await _projected_coordinator(history, stream).start()
    publisher_client = _IsolatedSignalClient()
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=PROJECTED_GRID,
        stream_client=stream,
        history_repository=history,
        signal_publisher=ValkeySignalPublisher(publisher_client),
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )

    stream.pending[trigger_stream].append(
        ("10-0", _projected_fields(PROJECTED_TRIGGER_SERIES, 7))
    )
    waiting = await runtime.poll_once()
    assert waiting.lane_results["BTCUSDT:main"].status == "WAITING"
    baseline_watermark = runtime.lanes["BTCUSDT:main"].finalizer.watermark

    stream.pending[trigger_stream].append(
        ("11-0", _projected_fields(PROJECTED_TRIGGER_SERIES, 8))
    )
    overrun = await runtime.poll_once()
    lane = overrun.lane_results["BTCUSDT:main"]

    assert lane.status == "RECONSTRUCTION_REQUIRED"
    assert lane.finalization_status is None
    assert not publisher_client.entries
    assert runtime.lanes["BTCUSDT:main"].finalizer.watermark == baseline_watermark


@pytest.mark.asyncio
async def test_durable_trigger_without_post_startup_stream_event_is_not_live_trigger() -> (
    None
):
    trigger_stream = canonical_ingestion_stream_key(PROJECTED_TRIGGER_SERIES)
    decision_stream = canonical_ingestion_stream_key(PROJECTED_DECISION_SERIES)
    history = InMemoryCanonicalMarketHistoryRepository(
        {
            PROJECTED_TRIGGER_SERIES: tuple(
                _projected_bar(PROJECTED_TRIGGER_SERIES, index) for index in range(8)
            ),
            PROJECTED_DECISION_SERIES: tuple(
                _projected_bar(PROJECTED_DECISION_SERIES, index) for index in range(2)
            ),
        },
        timeframe_grid=PROJECTED_GRID,
    )
    stream = _MultiStreamInputClient(
        {
            trigger_stream: ("6-0", _projected_fields(PROJECTED_TRIGGER_SERIES, 6)),
            decision_stream: ("1-0", _projected_fields(PROJECTED_DECISION_SERIES, 1)),
        }
    )
    startup = await _projected_coordinator(history, stream).start()
    publisher_client = _IsolatedSignalClient()
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=PROJECTED_GRID,
        stream_client=stream,
        history_repository=history,
        signal_publisher=ValkeySignalPublisher(publisher_client),
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )

    result = await runtime.poll_once()
    lane = result.lane_results["BTCUSDT:main"]

    assert lane.status == "LIVE"
    assert lane.trigger_cutoff is None
    assert lane.finalization_status is None
    assert not publisher_client.entries


@pytest.mark.asyncio
async def test_signal_batch_processes_each_cutoff_before_capacity_eviction() -> None:
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(3))},
        timeframe_grid=SIGNAL_GRID,
    )
    input_stream = "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h"
    stream = _LiveInputClient(
        stream=input_stream,
        tail_index=2,
        field_factory=_signal_fields,
    )
    startup = await _signal_coordinator(history, stream).start()
    publisher_client = _IsolatedSignalClient()
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        signal_publisher=ValkeySignalPublisher(publisher_client),
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )

    stream.pending.extend([("3-0", _signal_fields(3)), ("4-0", _signal_fields(4))])
    result = await runtime.poll_once()

    assert [item.disposition for item in result.input_results] == [
        "INSERTED",
        "INSERTED",
    ]
    lane = result.lane_results["BTCUSDT:main"]
    assert lane.status == "LIVE"
    assert lane.finalization_status == "COMMITTED"
    assert runtime.lanes["BTCUSDT:main"].finalizer.watermark.latest_market_as_of == (
        _signal_bar(4).market_as_of
    )
    assert len(publisher_client.entries["signals:BTCUSDT:1h"]) == 2


@pytest.mark.asyncio
async def test_checkpoint_failure_after_commit_halts_without_rollback() -> None:
    checkpoints = _FailingLiveCheckpointRepository()
    history = InMemoryCanonicalMarketHistoryRepository(
        {SR_SERIES: tuple(sr_bar(index) for index in range(50))},
        timeframe_grid=SR_GRID,
    )
    stream = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=49,
        field_factory=sr_stream_fields,
    )
    startup = await _sr_coordinator(history, checkpoints, stream).start()
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SR_GRID,
        stream_client=stream,
        history_repository=history,
        checkpoint_repository=checkpoints,
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )
    previous_checkpoint = await checkpoints.load(
        next(iter(startup.runtimes.values())).identity
    )
    assert previous_checkpoint is not None
    checkpoints.fail_live = True

    stream.pending.append(("50-0", sr_stream_fields(50)))
    result = await runtime.poll_once()
    lane = result.lane_results["BTCUSDT:main"]

    assert lane.status == "HALTED"
    assert lane.checkpoint_result == "CONFLICT"
    assert "checkpoint durability failed" in (lane.reason or "") or (
        "checkpoint durability returned" in (lane.reason or "")
    )
    assert runtime.input.cursor_for(stream.stream).latest_stream_id == "50-0"
    assert runtime.lanes["BTCUSDT:main"].finalizer.watermark.latest_market_as_of == (
        sr_bar(50).market_as_of
    )
    assert (
        runtime.lanes["BTCUSDT:main"]
        .runtime.state_store.get(
            next(iter(startup.runtimes.values())).stateful_binding_ids[0]
        )
        .committed_market_as_of
        == sr_bar(50).market_as_of
    )
    retained_checkpoint = await checkpoints.load(
        next(iter(startup.runtimes.values())).identity
    )
    assert retained_checkpoint == previous_checkpoint

    stream.pending.append(("51-0", sr_stream_fields(51)))
    after_halt = await runtime.poll_once()
    assert after_halt.input_results[0].disposition == "INSERTED"
    assert after_halt.lane_results["BTCUSDT:main"].status == "HALTED"
    assert runtime.lanes["BTCUSDT:main"].finalizer.watermark.latest_market_as_of == (
        sr_bar(50).market_as_of
    )


@pytest.mark.asyncio
async def test_policy_failure_aborts_unresolved_state_proposal() -> None:
    checkpoints = InMemoryCheckpointRepository()
    history = InMemoryCanonicalMarketHistoryRepository(
        {SR_SERIES: tuple(sr_bar(index) for index in range(50))},
        timeframe_grid=SR_GRID,
    )
    stream = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=49,
        field_factory=sr_stream_fields,
    )
    startup = await _sr_coordinator(history, checkpoints, stream).start()
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SR_GRID,
        stream_client=stream,
        history_repository=history,
        checkpoint_repository=checkpoints,
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )
    runtime._policy = _RaisingPolicy()
    stream.pending.append(("50-0", sr_stream_fields(50)))

    result = await runtime.poll_once()

    lane = result.lane_results["BTCUSDT:main"]
    assert lane.status == "INVALID"
    assert "policy boundary failed" in (lane.reason or "")
    assert runtime.lanes["BTCUSDT:main"].runtime.pending_state_execution is None
    binding_id = next(iter(startup.runtimes.values())).stateful_binding_ids[0]
    state = runtime.lanes["BTCUSDT:main"].runtime.state_store.get(binding_id)
    assert state.health == "DEGRADED"
    assert state.committed_market_as_of == sr_bar(49).market_as_of
    assert runtime.lanes["BTCUSDT:main"].finalizer.watermark.latest_market_as_of == (
        sr_bar(49).market_as_of
    )
