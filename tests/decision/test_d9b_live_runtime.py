from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.decision_app.composition import sr_initialization_requirement
from apps.decision_app.domain.market_state import MarketSeriesKey, TimeframeGrid
from apps.decision_app.features.definitions import SR_ATR_DEFINITION
from apps.decision_app.features.planning import (
    FeatureCatalog,
    FeatureHistoryRequirement,
    FeaturePolicy,
    SharedFeatureDefinition,
)
from apps.decision_app.observability import DecisionObservability
from apps.decision_app.planning.catalog import PluginCatalog
from apps.decision_app.runtime.deadlines import OperationTimeout
from apps.decision_app.runtime.live import LiveDecisionRuntime
from apps.decision_app.runtime.plugins import (
    RuntimePluginCatalog,
    RuntimePluginDefinition,
    StateInitializationRequirement,
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
from apps.decision_app.storage.effect_skips import (
    InMemoryLaneEffectSkipsRepository,
    LaneEffectSkip,
)
from apps.decision_app.storage.market_history import (
    InMemoryCanonicalMarketHistoryRepository,
)
from apps.decision_app.storage.shadow_progress import (
    InMemoryLaneEffectProgressRepository,
    LaneEffectProgress,
    LaneEffectProgressSaveResult,
)
from apps.decision_app.transport.ingestion import canonical_ingestion_stream_key
from apps.decision_app.transport.live_input import (
    FORWARD_CANONICAL_MARKET_GAP_REASON,
)
from apps.decision_app.transport.shadow import (
    ShadowDecisionObservation,
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
from libs.contracts.serialization import valkey_decode, valkey_encode
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
from tests.decision.test_observability import _Meter

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


STATEFUL_SIGNAL_SPEC = ModelSpec(
    name="test-decision",
    version="1",
    stateful=True,
    output_kind="decision_capable",
    produces_artifact_type="test-decision.v1",
    supported_trigger_modes=("on_bar_close",),
)


class _StatefulSignalPlugin(_SignalPlugin):
    spec = STATEFUL_SIGNAL_SPEC

    def evaluate(
        self,
        context: DecisionContext,
        state_snapshot: object | None = None,
    ) -> ModelOutcome:
        result = super().evaluate(context, state_snapshot)
        previous = 0 if state_snapshot is None else int(state_snapshot)
        return ModelOutcome(
            artifact=result.artifact,
            decision=result.decision,
            proposed_next_state=previous + 1,
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
        self.xread_calls: list[tuple[dict[str, str], int, int | None]] = []
        self.xrange_calls: list[tuple[str, str, str, int]] = []
        self.effect_entries: Mapping[str, Mapping[str, Mapping[object, object]]] = {}

    async def xrange(
        self, stream: str, minimum: str, maximum: str, *, count: int = 1
    ) -> list[tuple[str, Mapping[object, object]]]:
        self.xrange_calls.append((stream, minimum, maximum, count))
        values = self.effect_entries.get(stream, {})
        return [
            (entry_id, fields)
            for entry_id, fields in values.items()
            if entry_id == minimum == maximum
        ][:count]

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
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, Mapping[object, object]]]]]:
        self.xread_calls.append((dict(streams), count, block))
        if not self.pending:
            return []
        pending = self.pending
        self.pending = []
        return [(self.stream, pending)]


class _RecoverableLiveInputClient(_LiveInputClient):
    """Retain unread entries so a bounded poll can defer later cutoffs."""

    async def xread(
        self,
        streams: Mapping[str, str],
        *,
        count: int,
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, Mapping[object, object]]]]]:
        self.xread_calls.append((dict(streams), count, block))
        cursor = streams[self.stream]
        cursor_parts = tuple(int(part) for part in cursor.split("-"))
        pending = [
            entry
            for entry in self.pending
            if tuple(int(part) for part in entry[0].split("-")) > cursor_parts
        ]
        if not pending:
            return []
        return [(self.stream, pending)]


class _MultiStreamInputClient:
    def __init__(
        self, tails: Mapping[str, tuple[str, Mapping[object, object]]]
    ) -> None:
        self.tails = dict(tails)
        self.pending: dict[str, list[tuple[str, Mapping[object, object]]]] = {
            stream: [] for stream in tails
        }
        self.xrange_calls: list[tuple[str, str, str, int]] = []

    async def xrange(
        self, stream: str, minimum: str, maximum: str, *, count: int = 1
    ) -> list[tuple[str, Mapping[object, object]]]:
        self.xrange_calls.append((stream, minimum, maximum, count))
        return []

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


class _FixedLiveResultCheckpointRepository(InMemoryCheckpointRepository):
    """Persists live saves normally but reports a chosen result to the runtime."""

    def __init__(self) -> None:
        super().__init__()
        self.live_result: CheckpointSaveResult | None = None

    async def save(self, checkpoint):
        result = await super().save(checkpoint)
        return self.live_result if self.live_result is not None else result


class _TimeoutLiveCheckpointRepository(InMemoryCheckpointRepository):
    def __init__(self) -> None:
        super().__init__()
        self.fail_live = False

    async def save(self, checkpoint):
        if self.fail_live:
            raise OperationTimeout("checkpoint SQL", 0.01, source="driver")
        return await super().save(checkpoint)


class _TimeoutLiveProgressRepository(InMemoryLaneEffectProgressRepository):
    def __init__(self) -> None:
        super().__init__()
        self.fail_live = False

    async def save(self, progress):
        if self.fail_live:
            raise OperationTimeout("lane-effect progress SQL", 0.01, source="driver")
        return await super().save(progress)


class _RaisingPolicy:
    def evaluate(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("policy boundary failed")


def _sr_coordinator(
    history: InMemoryCanonicalMarketHistoryRepository,
    checkpoints: InMemoryCheckpointRepository,
    stream_client: _LiveInputClient,
) -> DecisionStartupCoordinator:
    return DecisionStartupCoordinator(
        decision_config=_sr_config(),
        plugin_catalog=PluginCatalog([SR_MODEL_SPEC]),
        feature_catalog=FeatureCatalog([SR_ATR_DEFINITION]),
        feature_policy=FeaturePolicy(
            name="operator", version="1", allowed_features=("ATR",)
        ),
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
    effect_progress_repository: InMemoryLaneEffectProgressRepository | None = None,
    effect_skips_repository: InMemoryLaneEffectSkipsRepository | None = None,
    history_capacity: int | None = None,
) -> DecisionStartupCoordinator:
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
        effect_progress_repository=effect_progress_repository,
        effect_skips_repository=effect_skips_repository,
    )


def _stateful_signal_coordinator(
    history: InMemoryCanonicalMarketHistoryRepository,
    stream_client: _LiveInputClient,
    *,
    checkpoint_repository: InMemoryCheckpointRepository,
    effect_progress_repository: InMemoryLaneEffectProgressRepository,
    effect_skips_repository: InMemoryLaneEffectSkipsRepository,
) -> DecisionStartupCoordinator:
    return DecisionStartupCoordinator(
        decision_config=_signal_config(),
        plugin_catalog=PluginCatalog([STATEFUL_SIGNAL_SPEC]),
        feature_catalog=FeatureCatalog([]),
        feature_policy=FeaturePolicy(name="operator", version="1"),
        runtime_plugin_catalog=RuntimePluginCatalog(
            [
                RuntimePluginDefinition(
                    plugin_name="test-decision",
                    plugin_version="1",
                    factory=lambda _parameters: _StatefulSignalPlugin(),
                    initialization_requirement=lambda _binding: (
                        StateInitializationRequirement(trigger_steps=2)
                    ),
                )
            ]
        ),
        history_repository=history,
        stream_client=stream_client,
        checkpoint_repository=checkpoint_repository,
        effect_progress_repository=effect_progress_repository,
        effect_skips_repository=effect_skips_repository,
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
    return DecisionStartupCoordinator(
        decision_config=config,
        plugin_catalog=PluginCatalog([SIGNAL_SPEC]),
        feature_catalog=FeatureCatalog([]),
        feature_policy=FeaturePolicy(name="operator", version="1", allowed_features=()),
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
    meter = _Meter()
    observability = DecisionObservability(
        meter=meter,
        timeframe_grid=SIGNAL_GRID,
        now_fn=lambda: datetime(2026, 2, 2, 0, 0, tzinfo=UTC),
    )
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        signal_publisher=ValkeySignalPublisher(publisher_client),
        now_fn=lambda: _signal_bar(3).market_as_of + timedelta(seconds=300),
        observability=observability,
    )
    observability.replace_generation(
        runtime=runtime,
        input_series=startup.snapshot.series_positions,
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

    assert len(meter.instruments["decision.input.records_total"].adds) == 1
    assert len(meter.instruments["decision.input.market_latency_ms"].records) == 1
    assert (
        len(meter.instruments["decision.input.canonical_event_latency_ms"].records) == 1
    )
    # Startup's latest retained cutoff is evaluated once, then skipped as stale;
    # the arriving fresh cutoff is evaluated and published once.
    assert len(meter.instruments["decision.lane.evaluation_total"].adds) == 2
    assert (
        meter.instruments["decision.lane.evaluation_total"].adds[0][1]["outcome"]
        == "SIGNAL"
    )
    assert len(meter.instruments["decision.publication.total"].adds) == 1
    assert (
        meter.instruments["decision.publication.total"].adds[0][1]["outcome"]
        == "PUBLISHED"
    )

    await runtime.poll_once()
    assert len(meter.instruments["decision.lane.evaluation_total"].adds) == 2
    assert len(meter.instruments["decision.publication.total"].adds) == 1


@pytest.mark.asyncio
async def test_forward_gap_stops_current_poll_before_stale_lane_evaluation() -> None:
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
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )
    attempted = False

    async def unexpected_lane_attempt(*_args, **_kwargs):
        nonlocal attempted
        attempted = True

    runtime._attempt_pending_lanes = unexpected_lane_attempt
    stream.pending.extend(
        [
            ("4-0", _signal_fields(4)),
            ("5-0", _signal_fields(5)),
        ]
    )

    result = await runtime.poll_once()

    assert len(result.input_results) == 1
    assert result.input_results[0].reason == FORWARD_CANONICAL_MARKET_GAP_REASON
    assert runtime.input.cursor_for(input_stream).latest_stream_id == "2-0"
    assert input_stream in runtime.input.blocked_streams
    assert attempted is False


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
        now_fn=lambda: _signal_bar(3).market_as_of + timedelta(seconds=300),
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
    progress = InMemoryLaneEffectProgressRepository()

    first = await _signal_coordinator(
        history,
        stream,
        authority="shadow",
        effect_progress_repository=progress,
    ).start()
    identity = next(iter(first.runtimes.values())).identity
    resume_cutoff = _signal_bar(3).market_as_of
    assert await progress.load(identity) is None
    assert first.snapshot.lane_watermarks["BTCUSDT:main"].latest_market_as_of is None
    assert first.snapshot.lane_evidence["BTCUSDT:main"].pending_trigger_cutoff == (
        resume_cutoff
    )
    assert stream.xrange_calls == [
        (
            "decision:shadow:BTCUSDT:main",
            shadow_stream_entry_id(resume_cutoff),
            shadow_stream_entry_id(resume_cutoff),
            1,
        )
    ]

    publisher_client = _IsolatedSignalClient()
    stream.effect_entries = publisher_client.entries
    runtime = LiveDecisionRuntime(
        startup=first,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        shadow_publisher=ValkeyShadowPublisher(publisher_client),
        effect_progress_repository=progress,
        now_fn=lambda: resume_cutoff + timedelta(seconds=300),
    )
    first_poll = await runtime.poll_once()
    assert first_poll.lane_results["BTCUSDT:main"].finalization_status == "COMMITTED"
    saved = await progress.load(identity)
    assert saved is not None
    assert saved.market_as_of == resume_cutoff
    assert saved.last_disposition == "shadow"
    assert len(publisher_client.entries["decision:shadow:BTCUSDT:main"]) == 1

    second = await _signal_coordinator(
        history,
        stream,
        authority="shadow",
        effect_progress_repository=progress,
    ).start()
    assert second.snapshot.lane_evidence["BTCUSDT:main"].pending_trigger_cutoff is None
    assert await progress.load(identity) == saved
    second_runtime = LiveDecisionRuntime(
        startup=second,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        shadow_publisher=ValkeyShadowPublisher(publisher_client),
        effect_progress_repository=progress,
        now_fn=lambda: resume_cutoff + timedelta(seconds=300),
    )
    await second_runtime.poll_once()
    assert len(publisher_client.entries["decision:shadow:BTCUSDT:main"]) == 1


@pytest.mark.parametrize("authority", ("authoritative", "shadow"))
@pytest.mark.parametrize(
    ("age_seconds", "expected_outcome"),
    ((300, "PUBLISHED"), (301, "SKIPPED_STALE")),
)
@pytest.mark.asyncio
async def test_signal_freshness_boundary_is_exact_for_authoritative_and_shadow(
    authority: str,
    age_seconds: int,
    expected_outcome: str,
) -> None:
    cutoff = _signal_bar(2).market_as_of
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(3))},
        timeframe_grid=SIGNAL_GRID,
    )
    stream = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=2,
        field_factory=_signal_fields,
    )
    progress = InMemoryLaneEffectProgressRepository()
    skips = InMemoryLaneEffectSkipsRepository()
    startup = await _signal_coordinator(
        history,
        stream,
        authority=authority,
        effect_progress_repository=progress,
        effect_skips_repository=skips,
    ).start()
    publisher_client = _IsolatedSignalClient()
    publication_kwargs = (
        {"signal_publisher": ValkeySignalPublisher(publisher_client)}
        if authority == "authoritative"
        else {"shadow_publisher": ValkeyShadowPublisher(publisher_client)}
    )
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        effect_progress_repository=progress,
        effect_skips_repository=skips,
        now_fn=lambda: cutoff + timedelta(seconds=age_seconds),
        **publication_kwargs,
    )

    result = await runtime.poll_once()
    lane = result.lane_results["BTCUSDT:main"]
    identity = runtime.lanes["BTCUSDT:main"].identity
    saved = await progress.load(identity)

    assert lane.publication_outcome == expected_outcome
    assert lane.finalization_status == "COMMITTED"
    assert runtime.lanes["BTCUSDT:main"].finalizer.watermark.last_disposition == (
        "skipped"
        if age_seconds == 301
        else authority.replace("authoritative", "published")
    )
    assert saved is not None and saved.market_as_of == cutoff
    if age_seconds == 300:
        assert saved.last_disposition == authority.replace("authoritative", "published")
        assert not skips.records
        assert publisher_client.xadd_calls == 1
    else:
        assert saved.last_disposition is None
        assert len(skips.records) == 1
        assert skips.records[0].skipped_from == cutoff
        assert skips.records[0].skipped_through == cutoff
        assert skips.records[0].reason == "stale"
        assert publisher_client.xadd_calls == 0


@pytest.mark.asyncio
async def test_stale_stateful_signal_commits_checkpoint_without_publication() -> None:
    checkpoints = InMemoryCheckpointRepository()
    progress = InMemoryLaneEffectProgressRepository()
    skips = InMemoryLaneEffectSkipsRepository()
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(4))},
        timeframe_grid=SIGNAL_GRID,
    )
    stream = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=3,
        field_factory=_signal_fields,
    )
    startup = await _stateful_signal_coordinator(
        history,
        stream,
        checkpoint_repository=checkpoints,
        effect_progress_repository=progress,
        effect_skips_repository=skips,
    ).start()
    identity = next(iter(startup.runtimes.values())).identity
    prior_checkpoint = await checkpoints.load(identity)
    prior_progress = await progress.load(identity)
    assert prior_checkpoint is not None
    assert prior_checkpoint.market_as_of == _signal_bar(3).market_as_of
    assert prior_progress is not None
    assert prior_progress.market_as_of == _signal_bar(3).market_as_of
    assert prior_progress.last_disposition is None

    stream.pending.append(("4-0", _signal_fields(4)))
    publisher_client = _IsolatedSignalClient()
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        signal_publisher=ValkeySignalPublisher(publisher_client),
        checkpoint_repository=checkpoints,
        effect_progress_repository=progress,
        effect_skips_repository=skips,
        now_fn=lambda: _signal_bar(4).market_as_of + timedelta(seconds=301),
    )

    result = await runtime.poll_once()
    lane = result.lane_results["BTCUSDT:main"]
    checkpoint = await checkpoints.load(identity)
    saved_progress = await progress.load(identity)

    assert lane.publication_outcome == "SKIPPED_STALE"
    assert lane.finalization_status == "COMMITTED"
    assert lane.trigger_cutoff == _signal_bar(4).market_as_of
    assert checkpoint is not None
    assert checkpoint.market_as_of == _signal_bar(4).market_as_of
    assert checkpoint.state_payload != prior_checkpoint.state_payload
    assert saved_progress is not None
    assert saved_progress.market_as_of == _signal_bar(4).market_as_of
    assert saved_progress.last_disposition is None
    assert publisher_client.xadd_calls == 0
    stale_skips = [skip for skip in skips.records if skip.reason == "stale"]
    assert len(stale_skips) == 1
    assert stale_skips[0].skipped_from == _signal_bar(4).market_as_of
    assert stale_skips[0].skipped_through == _signal_bar(4).market_as_of


@pytest.mark.asyncio
async def test_foreign_exact_id_is_recorded_as_skip_without_publication_conflict() -> (
    None
):
    cutoff = _signal_bar(3).market_as_of
    stream = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=2,
        field_factory=_signal_fields,
    )
    output_stream = "decision:shadow:BTCUSDT:main"
    output_id = shadow_stream_entry_id(cutoff)
    foreign = ShadowDecisionObservation(
        lane_id="BTCUSDT:main",
        asset="BTCUSDT",
        decision_timeframe="1h",
        trigger_timeframe="1h",
        market_as_of=cutoff,
        decision_ready_at=cutoff + timedelta(seconds=1),
        decision_id="foreign-cutover-identity",
        policy_status="SIGNAL",
        selected_binding_id="BTCUSDT:main/decision/test-decision@1",
        direction_hint=1,
        base_lane_revision="old-lane-revision",
        decision_execution_revision="old-execution-revision",
        feature_plan_fingerprint="old-feature-fingerprint",
        policy_name="passthrough",
        policy_version="1",
    )
    stream.effect_entries = {output_stream: {output_id: valkey_encode(foreign)}}
    progress = InMemoryLaneEffectProgressRepository()
    skips = InMemoryLaneEffectSkipsRepository()
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(4))},
        timeframe_grid=SIGNAL_GRID,
    )
    startup = await _signal_coordinator(
        history,
        stream,
        authority="shadow",
        effect_progress_repository=progress,
        effect_skips_repository=skips,
    ).start()

    assert startup.snapshot.lane_evidence["BTCUSDT:main"].pending_trigger_cutoff is None
    assert (
        startup.snapshot.lane_watermarks["BTCUSDT:main"].latest_market_as_of == cutoff
    )
    saved = await progress.load(next(iter(startup.runtimes.values())).identity)
    assert saved is not None and saved.market_as_of == cutoff
    assert saved.last_disposition is None
    assert len(skips.records) == 1
    assert skips.records[0].reason == "foreign_entry"
    assert skips.records[0].skipped_from == cutoff
    assert skips.records[0].skipped_through == cutoff

    publisher_client = _IsolatedSignalClient()
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        shadow_publisher=ValkeyShadowPublisher(publisher_client),
        effect_progress_repository=progress,
        effect_skips_repository=skips,
        now_fn=lambda: cutoff + timedelta(seconds=300),
    )
    await runtime.poll_once()
    assert publisher_client.xadd_calls == 0


@pytest.mark.asyncio
async def test_restart_skips_forward_records_one_range_and_evaluates_only_latest() -> (
    None
):
    progress = InMemoryLaneEffectProgressRepository()
    skips = InMemoryLaneEffectSkipsRepository()
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
        effect_progress_repository=progress,
        effect_skips_repository=skips,
        history_capacity=4,
    ).start()
    identity = next(iter(first.runtimes.values())).identity
    first_pending = first.snapshot.lane_evidence["BTCUSDT:main"].pending_trigger_cutoff
    assert first_pending == _signal_bar(3).market_as_of
    first_publisher = _IsolatedSignalClient()
    first_stream.effect_entries = first_publisher.entries
    first_runtime = LiveDecisionRuntime(
        startup=first,
        timeframe_grid=SIGNAL_GRID,
        stream_client=first_stream,
        history_repository=first_history,
        shadow_publisher=ValkeyShadowPublisher(first_publisher),
        effect_progress_repository=progress,
        effect_skips_repository=skips,
        now_fn=lambda: _signal_bar(3).market_as_of + timedelta(seconds=300),
    )
    await first_runtime.poll_once()
    baseline = await progress.load(identity)
    assert baseline is not None
    assert baseline.market_as_of == _signal_bar(3).market_as_of

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
        effect_progress_repository=progress,
        effect_skips_repository=skips,
        history_capacity=4,
    ).start()

    assert startup.snapshot.lane_evidence["BTCUSDT:main"].pending_trigger_cutoff == (
        _signal_bar(7).market_as_of
    )
    assert startup.snapshot.lane_watermarks["BTCUSDT:main"].latest_market_as_of == (
        _signal_bar(6).market_as_of
    )
    assert len(skips.records) == 1
    skip = skips.records[0]
    assert skip.skipped_from == _signal_bar(4).market_as_of
    assert skip.skipped_through == _signal_bar(6).market_as_of
    assert skip.cutoff_count == 3
    assert skip.reason == "restart"

    publisher_client = first_publisher
    stream.effect_entries = publisher_client.entries
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        shadow_publisher=ValkeyShadowPublisher(publisher_client),
        effect_progress_repository=progress,
        effect_skips_repository=skips,
        now_fn=lambda: _signal_bar(7).market_as_of + timedelta(seconds=300),
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
    assert len(publisher_client.entries["decision:shadow:BTCUSDT:main"]) == 2
    assert not any(key.startswith("signals:") for key in publisher_client.entries)

    restarted = await _signal_coordinator(
        history,
        stream,
        authority="shadow",
        effect_progress_repository=progress,
        effect_skips_repository=skips,
        history_capacity=4,
    ).start()
    assert (
        restarted.snapshot.lane_evidence["BTCUSDT:main"].pending_trigger_cutoff is None
    )
    assert len(skips.records) == 1


@pytest.mark.asyncio
async def test_restart_skip_upsert_converges_after_progress_save_crash() -> None:
    progress = InMemoryLaneEffectProgressRepository()
    skips = InMemoryLaneEffectSkipsRepository()
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
        effect_progress_repository=progress,
        effect_skips_repository=skips,
    ).start()
    publisher_client = _IsolatedSignalClient()
    first_stream.effect_entries = publisher_client.entries
    first_runtime = LiveDecisionRuntime(
        startup=first,
        timeframe_grid=SIGNAL_GRID,
        stream_client=first_stream,
        history_repository=first_history,
        shadow_publisher=ValkeyShadowPublisher(publisher_client),
        effect_progress_repository=progress,
        effect_skips_repository=skips,
        now_fn=lambda: _signal_bar(3).market_as_of + timedelta(seconds=300),
    )
    await first_runtime.poll_once()
    prior = await progress.load(first_runtime.lanes["BTCUSDT:main"].identity)
    assert prior is not None and prior.market_as_of == _signal_bar(3).market_as_of

    original_save = progress.save
    fail_next_save = [True]

    async def fail_after_skip_upsert(item):
        if fail_next_save[0]:
            fail_next_save[0] = False
            raise RuntimeError("simulated crash after skip-row upsert")
        return await original_save(item)

    progress.save = fail_after_skip_upsert  # type: ignore[method-assign]
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(8))},
        timeframe_grid=SIGNAL_GRID,
    )
    stream = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=6,
        field_factory=_signal_fields,
    )
    failed = await _signal_coordinator(
        history,
        stream,
        authority="shadow",
        effect_progress_repository=progress,
        effect_skips_repository=skips,
    ).start()
    assert failed.snapshot.status == "STARTUP_BLOCKED"
    assert len(skips.records) == 1
    assert skips.records[0].skipped_from == _signal_bar(4).market_as_of
    assert skips.records[0].skipped_through == _signal_bar(6).market_as_of
    assert await progress.load(first_runtime.lanes["BTCUSDT:main"].identity) == prior

    recovered = await _signal_coordinator(
        history,
        stream,
        authority="shadow",
        effect_progress_repository=progress,
        effect_skips_repository=skips,
    ).start()
    assert recovered.snapshot.status == "STARTUP_READY"
    assert len(skips.records) == 1
    assert skips.records[0].cutoff_count == 3
    advanced = await progress.load(first_runtime.lanes["BTCUSDT:main"].identity)
    assert advanced is not None
    assert advanced.market_as_of == _signal_bar(6).market_as_of
    assert advanced.last_disposition is None


def _signal_stream(tail_index: int) -> _LiveInputClient:
    return _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=tail_index,
        field_factory=_signal_fields,
    )


def _signal_history(bar_count: int) -> InMemoryCanonicalMarketHistoryRepository:
    return InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(bar_count))},
        timeframe_grid=SIGNAL_GRID,
    )


def _ledger_row(
    identity, cutoff_index: int, reason: str, *, through: int | None = None
):
    return LaneEffectSkip(
        identity=identity,
        skipped_from=_signal_bar(cutoff_index).market_as_of,
        skipped_through=_signal_bar(
            cutoff_index if through is None else through
        ).market_as_of,
        cutoff_count=1 if through is None else through - cutoff_index + 1,
        reason=reason,  # type: ignore[arg-type]
    )


async def _stateless_seed(
    reason: str | None = "stale",
    *,
    ledger_through: int | None = None,
    authority: str = "shadow",
):
    """Progress at bar 2 and an optional ledger row at bar 3 (progress + one)."""

    progress = InMemoryLaneEffectProgressRepository()
    skips = InMemoryLaneEffectSkipsRepository()
    first = await _signal_coordinator(
        _signal_history(4),
        _signal_stream(2),
        authority=authority,
        effect_progress_repository=progress,
        effect_skips_repository=skips,
    ).start()
    identity = next(iter(first.runtimes.values())).identity
    assert await progress.load(identity) is None
    await progress.save(
        LaneEffectProgress.create(
            identity=identity,
            market_as_of=_signal_bar(2).market_as_of,
            last_disposition=None,
        )
    )
    assert not skips.records
    if reason is not None:
        await skips.upsert(_ledger_row(identity, 3, reason, through=ledger_through))
    return identity, progress, skips


@pytest.mark.asyncio
async def test_startup_reconciles_stale_row_left_ahead_of_progress_stateless() -> None:
    identity, progress, skips = await _stateless_seed("stale")
    stream = _signal_stream(3)

    startup = await _signal_coordinator(
        _signal_history(5),
        stream,
        authority="shadow",
        effect_progress_repository=progress,
        effect_skips_repository=skips,
    ).start()

    evidence = startup.snapshot.lane_evidence["BTCUSDT:main"]
    saved = await progress.load(identity)
    assert startup.snapshot.status == "STARTUP_READY"
    assert saved is not None and saved.market_as_of == _signal_bar(3).market_as_of
    assert saved.last_disposition is None
    assert evidence.pending_trigger_cutoff == _signal_bar(4).market_as_of
    assert [(r.reason, r.skipped_from, r.skipped_through) for r in skips.records] == [
        (
            "stale",
            _signal_bar(3).market_as_of,
            _signal_bar(3).market_as_of,
        )
    ]
    assert stream.xrange_calls == []


@pytest.mark.asyncio
async def test_startup_reconciles_stale_row_at_resume_cutoff() -> None:
    identity, progress, skips = await _stateless_seed("stale")
    stream = _signal_stream(2)

    startup = await _signal_coordinator(
        _signal_history(4),
        stream,
        authority="shadow",
        effect_progress_repository=progress,
        effect_skips_repository=skips,
    ).start()

    saved = await progress.load(identity)
    assert startup.snapshot.status == "STARTUP_READY"
    assert saved is not None and saved.market_as_of == _signal_bar(3).market_as_of
    assert startup.snapshot.lane_evidence["BTCUSDT:main"].pending_trigger_cutoff is None
    assert len(skips.records) == 1 and skips.records[0].reason == "stale"
    assert stream.xrange_calls == []


@pytest.mark.asyncio
async def test_startup_reconciles_foreign_entry_row_whose_stream_entry_is_gone() -> (
    None
):
    identity, progress, skips = await _stateless_seed("foreign_entry")
    stream = _signal_stream(2)
    assert stream.effect_entries == {}

    startup = await _signal_coordinator(
        _signal_history(4),
        stream,
        authority="shadow",
        effect_progress_repository=progress,
        effect_skips_repository=skips,
    ).start()

    saved = await progress.load(identity)
    assert startup.snapshot.status == "STARTUP_READY"
    assert saved is not None and saved.market_as_of == _signal_bar(3).market_as_of
    assert [r.reason for r in skips.records] == ["foreign_entry"]
    assert stream.xrange_calls == []


@pytest.mark.asyncio
async def test_startup_reconciliation_is_idempotent_across_reruns() -> None:
    identity, progress, skips = await _stateless_seed("stale")
    for _ in range(2):
        startup = await _signal_coordinator(
            _signal_history(5),
            _signal_stream(3),
            authority="shadow",
            effect_progress_repository=progress,
            effect_skips_repository=skips,
        ).start()
        assert startup.snapshot.status == "STARTUP_READY"
    assert (await progress.load(identity)).market_as_of == _signal_bar(3).market_as_of
    assert len(skips.records) == 1


def _rows_from_bar(skips: InMemoryLaneEffectSkipsRepository, index: int):
    return [
        (r.reason, r.skipped_from, r.skipped_through)
        for r in skips.records
        if r.skipped_from >= _signal_bar(index).market_as_of
    ]


async def _stateful_seed(reason: str | None = "stale"):
    checkpoints = InMemoryCheckpointRepository()
    progress = InMemoryLaneEffectProgressRepository()
    skips = InMemoryLaneEffectSkipsRepository()
    first = await _stateful_signal_coordinator(
        _signal_history(3),
        _signal_stream(2),
        checkpoint_repository=checkpoints,
        effect_progress_repository=progress,
        effect_skips_repository=skips,
    ).start()
    identity = next(iter(first.runtimes.values())).identity
    assert (await progress.load(identity)).market_as_of == _signal_bar(2).market_as_of
    if reason is not None:
        await skips.upsert(_ledger_row(identity, 3, reason))
    return identity, checkpoints, progress, skips


@pytest.mark.asyncio
async def test_startup_reconciles_stale_row_for_stateful_lane_at_resume_cutoff() -> (
    None
):
    identity, checkpoints, progress, skips = await _stateful_seed()
    stream = _signal_stream(3)

    startup = await _stateful_signal_coordinator(
        _signal_history(4),
        stream,
        checkpoint_repository=checkpoints,
        effect_progress_repository=progress,
        effect_skips_repository=skips,
    ).start()

    saved = await progress.load(identity)
    assert startup.snapshot.status == "STARTUP_READY"
    assert saved is not None and saved.market_as_of == _signal_bar(3).market_as_of
    assert _rows_from_bar(skips, 3) == [
        ("stale", _signal_bar(3).market_as_of, _signal_bar(3).market_as_of)
    ]
    assert stream.xrange_calls == []


@pytest.mark.asyncio
async def test_startup_reconciles_stale_row_for_stateful_lane_then_skips_forward() -> (
    None
):
    identity, checkpoints, progress, skips = await _stateful_seed()
    stream = _signal_stream(4)

    startup = await _stateful_signal_coordinator(
        _signal_history(5),
        stream,
        checkpoint_repository=checkpoints,
        effect_progress_repository=progress,
        effect_skips_repository=skips,
    ).start()

    saved = await progress.load(identity)
    assert startup.snapshot.status == "STARTUP_READY"
    assert saved is not None and saved.market_as_of == _signal_bar(4).market_as_of
    assert _rows_from_bar(skips, 3) == [
        ("stale", _signal_bar(3).market_as_of, _signal_bar(3).market_as_of),
        ("restart_rewarm", _signal_bar(4).market_as_of, _signal_bar(4).market_as_of),
    ]
    assert stream.xrange_calls == []


@pytest.mark.asyncio
async def test_startup_does_not_reconcile_a_restart_row() -> None:
    identity, progress, skips = await _stateless_seed("restart")
    stream = _signal_stream(3)

    startup = await _signal_coordinator(
        _signal_history(5),
        stream,
        authority="shadow",
        effect_progress_repository=progress,
        effect_skips_repository=skips,
    ).start()

    # Today's path: the exact-entry probe runs and the matching row is reused.
    assert startup.snapshot.status == "STARTUP_READY"
    assert stream.xrange_calls
    assert [r.reason for r in skips.records] == ["restart"]
    assert (await progress.load(identity)).market_as_of == _signal_bar(3).market_as_of


@pytest.mark.asyncio
async def test_startup_does_not_reconcile_a_multi_cutoff_row() -> None:
    identity, progress, skips = await _stateless_seed("stale", ledger_through=4)
    stream = _signal_stream(4)

    startup = await _signal_coordinator(
        _signal_history(6),
        stream,
        authority="shadow",
        effect_progress_repository=progress,
        effect_skips_repository=skips,
    ).start()

    # Unchanged behaviour: the probe runs and the restart row conflicts.
    assert startup.snapshot.status == "STARTUP_BLOCKED"
    assert stream.xrange_calls
    assert (await progress.load(identity)).market_as_of == _signal_bar(2).market_as_of


@pytest.mark.asyncio
async def test_startup_blocks_when_ledger_row_is_ahead_of_resumable_history() -> None:
    identity, progress, skips = await _stateless_seed(None)
    await skips.upsert(_ledger_row(identity, 5, "stale"))
    # Progress is at bar 2 but history only reaches bar 3 with progress ahead.
    await progress.save(
        LaneEffectProgress.create(
            identity=identity,
            market_as_of=_signal_bar(4).market_as_of,
            last_disposition=None,
        )
    )
    stream = _signal_stream(2)

    startup = await _signal_coordinator(
        _signal_history(4),
        stream,
        authority="shadow",
        effect_progress_repository=progress,
        effect_skips_repository=skips,
    ).start()

    assert startup.snapshot.status == "STARTUP_BLOCKED"
    assert stream.xrange_calls == []
    assert (await progress.load(identity)).market_as_of == _signal_bar(4).market_as_of


@pytest.mark.asyncio
async def test_stale_skip_followed_by_failed_progress_save_recovers_on_restart() -> (
    None
):
    cutoff = _signal_bar(2).market_as_of
    history = _signal_history(3)
    stream = _signal_stream(2)
    progress = InMemoryLaneEffectProgressRepository()
    skips = InMemoryLaneEffectSkipsRepository()
    startup = await _signal_coordinator(
        history,
        stream,
        effect_progress_repository=progress,
        effect_skips_repository=skips,
    ).start()
    identity = next(iter(startup.runtimes.values())).identity
    assert await progress.load(identity) is None
    prior = LaneEffectProgress.create(
        identity=identity,
        market_as_of=_signal_bar(1).market_as_of,
        last_disposition=None,
    )
    await progress.save(prior)

    original_save = progress.save

    async def fail_once(item):
        progress.save = original_save  # type: ignore[method-assign]
        raise RuntimeError("simulated crash between skip row and progress save")

    progress.save = fail_once  # type: ignore[method-assign]
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        signal_publisher=ValkeySignalPublisher(_IsolatedSignalClient()),
        effect_progress_repository=progress,
        effect_skips_repository=skips,
        now_fn=lambda: cutoff + timedelta(seconds=301),
    )
    await runtime.poll_once()
    assert [r.reason for r in skips.records] == ["stale"]
    assert await progress.load(identity) == prior

    restarted = await _signal_coordinator(
        history,
        _signal_stream(2),
        effect_progress_repository=progress,
        effect_skips_repository=skips,
    ).start()

    assert restarted.snapshot.status == "STARTUP_READY"
    saved = await progress.load(identity)
    assert saved is not None and saved.market_as_of == cutoff
    assert [r.reason for r in skips.records] == ["stale"]


@pytest.mark.asyncio
async def test_restart_pending_cutoff_retries_clock_wait_without_duplicate_effects() -> (
    None
):
    progress = InMemoryLaneEffectProgressRepository()
    skips = InMemoryLaneEffectSkipsRepository()
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
        effect_progress_repository=progress,
        effect_skips_repository=skips,
        history_capacity=4,
    ).start()
    first_identity = next(iter(first.runtimes.values())).identity
    first_publisher = _IsolatedSignalClient()
    first_stream.effect_entries = first_publisher.entries
    first_runtime = LiveDecisionRuntime(
        startup=first,
        timeframe_grid=SIGNAL_GRID,
        stream_client=first_stream,
        history_repository=first_history,
        shadow_publisher=ValkeyShadowPublisher(first_publisher),
        effect_progress_repository=progress,
        effect_skips_repository=skips,
        now_fn=lambda: _signal_bar(3).market_as_of + timedelta(seconds=300),
    )
    await first_runtime.poll_once()
    baseline = await progress.load(first_identity)
    assert baseline is not None and baseline.market_as_of == _signal_bar(3).market_as_of

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
        effect_progress_repository=progress,
        effect_skips_repository=skips,
        history_capacity=4,
    ).start()
    assert startup.snapshot.lane_watermarks["BTCUSDT:main"].latest_market_as_of == (
        _signal_bar(6).market_as_of
    )

    publisher_client = first_publisher
    stream.effect_entries = publisher_client.entries
    clock = [_signal_bar(7).market_as_of - timedelta(minutes=1)]
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        shadow_publisher=ValkeyShadowPublisher(publisher_client),
        effect_progress_repository=progress,
        effect_skips_repository=skips,
        now_fn=lambda: clock[0],
    )

    waiting = await runtime.poll_once()
    waiting_lane = waiting.lane_results["BTCUSDT:main"]
    assert waiting_lane.status == "WAITING"
    assert waiting_lane.reason == "decision clock is behind lane market cutoff"
    assert runtime.lanes["BTCUSDT:main"].pending_trigger_cutoff == (
        _signal_bar(7).market_as_of
    )
    assert len(publisher_client.entries["decision:shadow:BTCUSDT:main"]) == 1

    retried = await runtime.poll_once()
    retried_lane = retried.lane_results["BTCUSDT:main"]
    assert retried_lane.status == "WAITING"
    assert retried_lane.reason == "decision clock is behind lane market cutoff"
    assert runtime.lanes["BTCUSDT:main"].pending_trigger_cutoff == (
        _signal_bar(7).market_as_of
    )
    assert len(publisher_client.entries["decision:shadow:BTCUSDT:main"]) == 1

    clock[0] = _signal_bar(7).market_as_of
    completed = await runtime.poll_once()
    completed_lane = completed.lane_results["BTCUSDT:main"]
    assert completed_lane.status == "LIVE"
    assert completed_lane.finalization_status == "COMMITTED"
    assert runtime.lanes["BTCUSDT:main"].pending_trigger_cutoff is None
    assert len(publisher_client.entries["decision:shadow:BTCUSDT:main"]) == 2
    saved = await progress.load(first_identity)
    assert saved is not None
    assert saved.market_as_of == _signal_bar(7).market_as_of


@pytest.mark.asyncio
async def test_shadow_exact_id_reconciles_in_flight_cutoff_crash_window() -> None:
    progress = InMemoryLaneEffectProgressRepository()
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
        effect_progress_repository=progress,
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
        effect_progress_repository=progress,
        history_capacity=1,
    ).start()
    publisher_client = _IsolatedSignalClient()
    first_runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        shadow_publisher=ValkeyShadowPublisher(publisher_client),
        effect_progress_repository=progress,
        now_fn=lambda: _signal_bar(4).market_as_of + timedelta(seconds=300),
    )
    # The first process publishes the exact observation but loses the progress
    # write, which is the crash window repaired by the next startup.
    original_save = progress.save
    failed_once = True

    async def fail_progress_save(item):
        nonlocal failed_once
        if failed_once and item.last_disposition == "shadow":
            failed_once = False
            return LaneEffectProgressSaveResult.CONFLICT
        return await original_save(item)

    progress.save = fail_progress_save  # type: ignore[method-assign]
    result = await first_runtime.poll_once()
    assert result.lane_results["BTCUSDT:main"].status == "HALTED"
    assert len(publisher_client.entries["decision:shadow:BTCUSDT:main"]) == 1

    progress.save = original_save  # type: ignore[method-assign]
    stream.effect_entries = publisher_client.entries
    restarted = await _signal_coordinator(
        history,
        stream,
        authority="shadow",
        effect_progress_repository=progress,
        history_capacity=1,
    ).start()
    assert (
        restarted.snapshot.lane_evidence["BTCUSDT:main"].pending_trigger_cutoff is None
    )
    reconciled_identity = next(iter(restarted.runtimes.values())).identity
    reconciled = await progress.load(reconciled_identity)
    assert reconciled is not None
    assert reconciled.market_as_of == _signal_bar(4).market_as_of
    assert reconciled.last_disposition == "shadow"
    second_runtime = LiveDecisionRuntime(
        startup=restarted,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        shadow_publisher=ValkeyShadowPublisher(publisher_client),
        effect_progress_repository=progress,
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )
    second = await second_runtime.poll_once()
    assert second.lane_results["BTCUSDT:main"].publication_outcome is None
    assert len(publisher_client.entries["decision:shadow:BTCUSDT:main"]) == 1
    saved = await progress.load(next(iter(restarted.runtimes.values())).identity)
    assert saved is not None
    assert saved.market_as_of == _signal_bar(4).market_as_of


@pytest.mark.asyncio
async def test_shadow_progress_sql_timeout_after_commit_halts_without_rewind() -> None:
    progress = _TimeoutLiveProgressRepository()
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(3))},
        timeframe_grid=SIGNAL_GRID,
    )
    stream = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=2,
        field_factory=_signal_fields,
    )
    startup = await _signal_coordinator(
        history,
        stream,
        authority="shadow",
        effect_progress_repository=progress,
    ).start()
    identity = next(iter(startup.runtimes.values())).identity
    previous_progress = await progress.load(identity)
    assert previous_progress is None

    publisher_client = _IsolatedSignalClient()
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        shadow_publisher=ValkeyShadowPublisher(publisher_client),
        effect_progress_repository=progress,
        now_fn=lambda: _signal_bar(2).market_as_of + timedelta(seconds=300),
    )
    progress.fail_live = True

    result = await runtime.poll_once()
    lane = result.lane_results["BTCUSDT:main"]

    assert lane.publication_outcome == "PUBLISHED"
    assert lane.finalization_status == "COMMITTED"
    assert lane.status == "HALTED"
    assert "lane effect progress durability failed after committed finalization" in (
        lane.reason or ""
    )
    assert runtime.lanes["BTCUSDT:main"].finalizer.watermark.latest_market_as_of == (
        _signal_bar(2).market_as_of
    )
    assert await progress.load(identity) == previous_progress


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
        now_fn=lambda: _signal_bar(3).market_as_of + timedelta(seconds=300),
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
        now_fn=lambda: _signal_bar(2).market_as_of + timedelta(seconds=300),
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
    clock = [_signal_bar(3).market_as_of + timedelta(seconds=300)]
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        signal_publisher=ValkeySignalPublisher(publisher_client),
        now_fn=lambda: clock[0],
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
        now_fn=lambda: _signal_bar(3).market_as_of + timedelta(seconds=300),
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
    clock = [_signal_bar(3).market_as_of + timedelta(seconds=300)]
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        signal_publisher=ValkeySignalPublisher(publisher_client),
        now_fn=lambda: clock[0],
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
    clock[0] = _signal_bar(4).market_as_of + timedelta(seconds=300)
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
        now_fn=lambda: (
            _projected_bar(PROJECTED_TRIGGER_SERIES, 7).market_as_of
            + timedelta(seconds=300)
        ),
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
        now_fn=lambda: (
            _projected_bar(PROJECTED_TRIGGER_SERIES, 7).market_as_of
            + timedelta(seconds=300)
        ),
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
async def test_clock_behind_waits_and_retries_on_idle_poll() -> None:
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(3))},
        timeframe_grid=SIGNAL_GRID,
    )
    input_stream = "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h"
    stream = _RecoverableLiveInputClient(
        stream=input_stream,
        tail_index=2,
        field_factory=_signal_fields,
    )
    startup = await _signal_coordinator(history, stream).start()
    publisher_client = _IsolatedSignalClient()
    clock = [_signal_bar(3).market_as_of]
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        signal_publisher=ValkeySignalPublisher(publisher_client),
        now_fn=lambda: clock[0],
    )

    stream.pending.append(("3-0", _signal_fields(3)))
    initially_live = await runtime.poll_once()
    initially_live_lane = initially_live.lane_results["BTCUSDT:main"]

    assert initially_live_lane.status == "LIVE"
    assert initially_live_lane.finalization_status == "COMMITTED"
    assert runtime.lanes["BTCUSDT:main"].finalizer.watermark.latest_market_as_of == (
        _signal_bar(3).market_as_of
    )
    assert len(publisher_client.entries["signals:BTCUSDT:1h"]) == 1

    clock[0] = _signal_bar(4).market_as_of - timedelta(minutes=1)
    stream.pending.append(("4-0", _signal_fields(4)))
    waiting = await runtime.poll_once()
    waiting_lane = waiting.lane_results["BTCUSDT:main"]

    assert waiting_lane.status == "WAITING"
    assert waiting_lane.reason == "decision clock is behind lane market cutoff"
    assert waiting_lane.policy_status is None
    assert waiting_lane.finalization_status is None
    assert runtime.lanes["BTCUSDT:main"].pending_trigger_cutoff == (
        _signal_bar(4).market_as_of
    )
    assert runtime.lanes["BTCUSDT:main"].finalizer.watermark.latest_market_as_of == (
        _signal_bar(3).market_as_of
    )
    assert len(publisher_client.entries["signals:BTCUSDT:1h"]) == 1

    idle = await runtime.poll_once()
    idle_lane = idle.lane_results["BTCUSDT:main"]
    assert not idle.input_results
    assert idle_lane.status == "WAITING"
    assert idle_lane.policy_status is None
    assert idle_lane.finalization_status is None
    assert runtime.input.cursor_for(input_stream).latest_stream_id == "4-0"
    assert len(publisher_client.entries["signals:BTCUSDT:1h"]) == 1

    extra_idle = await runtime.poll_once()
    extra_idle_lane = extra_idle.lane_results["BTCUSDT:main"]
    assert not extra_idle.input_results
    assert extra_idle_lane.status == "WAITING"
    assert extra_idle_lane.finalization_status is None
    assert runtime.lanes["BTCUSDT:main"].finalizer.watermark.latest_market_as_of == (
        _signal_bar(3).market_as_of
    )
    assert len(publisher_client.entries["signals:BTCUSDT:1h"]) == 1

    clock[0] = _signal_bar(4).market_as_of
    ready = await runtime.poll_once()
    ready_lane = ready.lane_results["BTCUSDT:main"]
    assert not ready.input_results
    assert ready_lane.status == "LIVE"
    assert ready_lane.finalization_status == "COMMITTED"
    assert runtime.lanes["BTCUSDT:main"].pending_trigger_cutoff is None
    assert len(publisher_client.entries["signals:BTCUSDT:1h"]) == 2


@pytest.mark.asyncio
async def test_clock_wait_defers_newer_batch_cutoff_until_catchup() -> None:
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(3))},
        timeframe_grid=SIGNAL_GRID,
    )
    input_stream = "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h"
    stream = _RecoverableLiveInputClient(
        stream=input_stream,
        tail_index=2,
        field_factory=_signal_fields,
    )
    startup = await _signal_coordinator(history, stream).start()
    publisher_client = _IsolatedSignalClient()
    clock = [_signal_bar(3).market_as_of - timedelta(minutes=1)]
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        signal_publisher=ValkeySignalPublisher(publisher_client),
        now_fn=lambda: clock[0],
    )

    stream.pending.extend([("3-0", _signal_fields(3)), ("4-0", _signal_fields(4))])
    first = await runtime.poll_once()
    first_lane = first.lane_results["BTCUSDT:main"]
    assert [item.stream_id for item in first.input_results] == ["3-0"]
    assert first_lane.status == "WAITING"
    assert runtime.input.cursor_for(input_stream).latest_stream_id == "3-0"
    assert not publisher_client.entries

    idle = await runtime.poll_once()
    idle_lane = idle.lane_results["BTCUSDT:main"]
    assert not idle.input_results
    assert idle_lane.status == "WAITING"
    assert runtime.input.cursor_for(input_stream).latest_stream_id == "3-0"
    assert not publisher_client.entries

    clock[0] = _signal_bar(3).market_as_of
    first_caught_up = await runtime.poll_once()
    caught_up_lane = first_caught_up.lane_results["BTCUSDT:main"]
    assert [item.stream_id for item in first_caught_up.input_results] == ["4-0"]
    assert caught_up_lane.status == "WAITING"
    assert caught_up_lane.trigger_cutoff == _signal_bar(4).market_as_of
    assert caught_up_lane.finalization_status is None
    assert runtime.input.cursor_for(input_stream).latest_stream_id == "4-0"
    assert len(publisher_client.entries["signals:BTCUSDT:1h"]) == 1

    clock[0] = _signal_bar(4).market_as_of
    second_caught_up = await runtime.poll_once()
    second_lane = second_caught_up.lane_results["BTCUSDT:main"]
    assert not second_caught_up.input_results
    assert second_lane.status == "LIVE"
    assert second_lane.finalization_status == "COMMITTED"
    assert runtime.lanes["BTCUSDT:main"].pending_trigger_cutoff is None
    assert len(publisher_client.entries["signals:BTCUSDT:1h"]) == 2


@pytest.mark.asyncio
async def test_stale_durable_startup_cutoff_is_skipped_without_publication() -> None:
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
    assert (
        lane.trigger_cutoff == _projected_bar(PROJECTED_TRIGGER_SERIES, 7).market_as_of
    )
    assert lane.publication_outcome == "SKIPPED_STALE"
    assert lane.finalization_status == "COMMITTED"
    assert runtime.lanes["BTCUSDT:main"].finalizer.watermark.latest_market_as_of == (
        _projected_bar(PROJECTED_TRIGGER_SERIES, 7).market_as_of
    )
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
    skips = InMemoryLaneEffectSkipsRepository()
    startup = await _signal_coordinator(
        history, stream, effect_skips_repository=skips
    ).start()
    publisher_client = _IsolatedSignalClient()
    meter = _Meter()
    observability = DecisionObservability(
        meter=meter,
        timeframe_grid=SIGNAL_GRID,
        now_fn=lambda: datetime(2026, 2, 2, 0, 0, tzinfo=UTC),
    )
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        signal_publisher=ValkeySignalPublisher(publisher_client),
        effect_skips_repository=skips,
        now_fn=lambda: _signal_bar(4).market_as_of + timedelta(seconds=300),
        observability=observability,
    )
    observability.replace_generation(
        runtime=runtime,
        input_series=startup.snapshot.series_positions,
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
    assert tuple(publisher_client.entries["signals:BTCUSDT:1h"]) == (
        f"{int(_signal_bar(4).market_as_of.timestamp() * 1000)}-0",
    )
    assert [skip.skipped_from for skip in skips.records] == [
        _signal_bar(2).market_as_of,
        _signal_bar(3).market_as_of,
    ]
    assert all(skip.reason == "stale" for skip in skips.records)
    evaluation_adds = meter.instruments["decision.lane.evaluation_total"].adds
    publication_adds = meter.instruments["decision.publication.total"].adds
    assert len(evaluation_adds) == 3
    assert [attributes["outcome"] for _value, attributes in evaluation_adds] == [
        "SIGNAL",
        "SIGNAL",
        "SIGNAL",
    ]
    assert len(publication_adds) == 1
    assert [attributes["outcome"] for _value, attributes in publication_adds] == [
        "PUBLISHED",
    ]

    await runtime.poll_once()
    assert len(meter.instruments["decision.lane.evaluation_total"].adds) == 3
    assert len(meter.instruments["decision.publication.total"].adds) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failing_hook",
    ("record_input_result", "record_lane_evaluation", "record_publication"),
)
async def test_observability_failure_cannot_abort_authoritative_signal(
    failing_hook: str,
) -> None:
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(3))},
        timeframe_grid=SIGNAL_GRID,
    )
    stream = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=2,
        field_factory=_signal_fields,
    )
    startup = await _signal_coordinator(history, stream).start()
    publisher_client = _IsolatedSignalClient()
    observability = DecisionObservability(
        meter=_Meter(),
        timeframe_grid=SIGNAL_GRID,
        now_fn=lambda: _signal_bar(3).market_as_of + timedelta(seconds=300),
    )

    def fail_telemetry(*_args, **_kwargs) -> None:
        raise RuntimeError("synthetic telemetry failure")

    setattr(observability, failing_hook, fail_telemetry)
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        signal_publisher=ValkeySignalPublisher(publisher_client),
        now_fn=lambda: _signal_bar(3).market_as_of + timedelta(seconds=300),
        observability=observability,
    )
    observability.replace_generation(
        runtime=runtime,
        input_series=startup.snapshot.series_positions,
    )
    stream.pending.append(("3-0", _signal_fields(3)))

    result = await runtime.poll_once()
    lane = result.lane_results["BTCUSDT:main"]

    assert result.input_results[0].disposition == "INSERTED"
    assert lane.policy_status == "SIGNAL"
    assert lane.publication_outcome == "PUBLISHED"
    assert lane.finalization_status == "COMMITTED"
    assert tuple(publisher_client.entries["signals:BTCUSDT:1h"]) == (
        f"{int(_signal_bar(3).market_as_of.timestamp() * 1000)}-0",
    )
    assert runtime.input.cursor_for(SIGNAL_SERIES).latest_stream_id == "3-0"


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
@pytest.mark.parametrize(
    ("live_result", "expected_status"),
    [
        (CheckpointSaveResult.INSERTED, "LIVE"),
        (CheckpointSaveResult.REJECTED_OLDER, "HALTED"),
    ],
)
async def test_live_checkpoint_inserted_after_commit_continues_with_warning(
    caplog, live_result: CheckpointSaveResult, expected_status: str
) -> None:
    checkpoints = _FixedLiveResultCheckpointRepository()
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
    checkpoints.live_result = live_result
    caplog.set_level(logging.WARNING)

    stream.pending.append(("50-0", sr_stream_fields(50)))
    result = await runtime.poll_once()
    lane = result.lane_results["BTCUSDT:main"]

    assert lane.status == expected_status
    assert lane.checkpoint_result == live_result.value
    events = [getattr(record, "event", None) for record in caplog.records]
    if live_result is CheckpointSaveResult.INSERTED:
        assert lane.reason is None
        assert "decision.lane.checkpoint_reinserted" in events
        assert "decision.lane.halted" not in events
    else:
        assert f"checkpoint durability returned {live_result.value}" in (
            lane.reason or ""
        )
        assert "decision.lane.checkpoint_reinserted" not in events


@pytest.mark.asyncio
async def test_checkpoint_sql_timeout_after_commit_halts_without_rollback() -> None:
    checkpoints = _TimeoutLiveCheckpointRepository()
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
    assert lane.checkpoint_result is None
    assert "checkpoint durability failed after committed finalization" in (
        lane.reason or ""
    )
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
    assert await checkpoints.load(next(iter(startup.runtimes.values())).identity) == (
        previous_checkpoint
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
