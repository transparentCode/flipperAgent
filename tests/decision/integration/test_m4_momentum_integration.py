from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from apps.decision_app.composition import (
    build_production_composition,
)
from apps.decision_app.domain.market_state import MarketSeriesKey
from apps.decision_app.domain.view import DecisionViewBuilder
from apps.decision_app.features.momentum import calculate_macd, calculate_rsi
from apps.decision_app.features.momentum_integration import (
    MOMENTUM_M3_ARTIFACT_SHA256,
    MOMENTUM_MACD_FEATURE_NAME,
    MOMENTUM_ROUTE_PROFILE_LOCKS,
    MOMENTUM_RSI_FEATURE_NAME,
    momentum_route_profile_digest,
    parse_momentum_binding_parameters,
)
from apps.decision_app.runtime.live import LiveDecisionRuntime
from apps.decision_app.runtime.policy import DecisionPolicy
from apps.decision_app.runtime.startup import DecisionStartupCoordinator
from apps.decision_app.settings import (
    CanonicalInstrument,
    DecisionAssetSettings,
    DecisionConfig,
    DecisionGlobalSettings,
    DecisionLaneSettings,
    DecisionPolicySettings,
)
from apps.decision_app.storage.checkpoints import InMemoryCheckpointRepository
from apps.decision_app.storage.market_history import (
    InMemoryCanonicalMarketHistoryRepository,
)
from apps.decision_app.transport.ingestion import canonical_ingestion_stream_key
from apps.decision_app.transport.signals import ValkeySignalPublisher
from libs.common.config import ConfigManager
from libs.contracts.decision import CausalBarView
from libs.contracts.serialization import valkey_decode
from libs.contracts.signal import TradeSignal
from libs.models.momentum.core import MomentumObservation, evaluate_momentum
from scripts.certify_momentum_decision_m4 import (
    _RecordingCanonicalHistoryRepository,
    build_retention_coverage,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = ROOT / "tests" / "decision" / "fixtures" / "momentum_m4"
M3_ARTIFACT = (
    ROOT
    / "artifacts"
    / "decision_m3"
    / ("m3_momentum_feature_semantics_certification.json")
)
D10_ARTIFACT = (
    ROOT / "artifacts" / "decision_d10" / ("d10_resource_capacity_certification.json")
)
POST_M3_SHA = "e7bce3d5ca2ea46772447cdf003c989124ea1847"
D10_SHA = "2382c92cd83bb29cbab2800c5687ec102d53fe37b213925fa174852a2caa0459"
M3_SHA = "6fcd3d736524b513a63f244a3268478a658924cd571a62a72ec33958ad67972c"


class _EmptyStreamClient:
    async def xrevrange(self, *_args: object, **_kwargs: object) -> list[object]:
        return []

    async def xread(self, *_args: object, **_kwargs: object) -> list[object]:
        return []


class _LiveStreamClient(_EmptyStreamClient):
    def __init__(self) -> None:
        self.pending: list[tuple[str, Mapping[object, object]]] = []

    async def xread(
        self,
        _streams: Mapping[str, str],
        *,
        count: int,
        block: int,
    ) -> list[tuple[str, list[tuple[str, Mapping[object, object]]]]]:
        assert count == 10
        assert block == 1000
        if not self.pending:
            return []
        pending = self.pending
        self.pending = []
        return [
            (
                pending[0][0].split("|", 1)[0],
                [(stream_id, fields) for _, stream_id, fields in pending],
            )
        ]


class _SignalClient:
    def __init__(self) -> None:
        self.entries: dict[str, dict[str, Mapping[object, object]]] = {}
        self.fail_xadd = False

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
        if self.fail_xadd:
            raise RuntimeError("isolated broker unavailable")
        values = self.entries.setdefault(stream, {})
        if id in values:
            raise RuntimeError("duplicate explicit ID")
        values[id] = fields
        return id


class _RecordingPublisher:
    def __init__(self, publisher: ValkeySignalPublisher) -> None:
        self.publisher = publisher
        self.envelopes = []

    async def publish(self, envelope):
        self.envelopes.append(envelope)
        return await self.publisher.publish(envelope)


@pytest.fixture(scope="module")
def fixture_config() -> DecisionConfig:
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(ROOT / "configs"))
    try:
        from apps.decision_app.settings import load_decision_config

        return load_decision_config(
            manager,
            global_file=FIXTURE_ROOT / "global.yaml",
            assets_directory=FIXTURE_ROOT / "assets",
        )
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()


def _route_parameters(config: DecisionConfig, lane_id: str) -> Mapping[str, object]:
    lane = next(item for item in config.lane_specs() if item.lane_id == lane_id)
    binding = next(item for item in lane.bindings if item.slot_name == "primary")
    return binding.parameters


def _plain_mapping(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_mapping(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_mapping(item) for item in value]
    return value


def _bar_series(
    key: MarketSeriesKey,
    grid,
    *,
    count: int = 544,
    missing_index: int | None = None,
) -> tuple[CausalBarView, ...]:
    duration = grid.duration(key.timeframe)
    start = grid.alignment_origin + duration * 200_000
    bars: list[CausalBarView] = []
    for index in range(count):
        if index == missing_index:
            continue
        opened = start + duration * index
        closed = opened + duration
        close = Decimal(100) + Decimal(index) / Decimal(10)
        bars.append(
            CausalBarView(
                timeframe=key.timeframe,
                bar_open_at=opened,
                bar_close_at=closed,
                market_as_of=closed,
                open=close,
                high=close + Decimal(1),
                low=close - Decimal(1),
                close=close,
                volume=Decimal(10),
                taker_buy_base=Decimal(4),
                closed=True,
            )
        )
    return tuple(bars)


def _series_keys(config: DecisionConfig) -> tuple[MarketSeriesKey, ...]:
    return tuple(
        sorted(
            {
                MarketSeriesKey(
                    asset=lane.asset,
                    venue=lane.venue,
                    instrument_id=lane.instrument_id,
                    timeframe=lane.decision_timeframe,
                )
                for lane in config.lane_specs()
            },
            key=lambda key: (key.asset, key.timeframe),
        )
    )


async def _startup(
    config: DecisionConfig,
    composition,
    *,
    missing: tuple[MarketSeriesKey, int] | None = None,
    histories_override: Mapping[MarketSeriesKey, tuple[CausalBarView, ...]]
    | None = None,
):
    histories = dict(histories_override) if histories_override is not None else {}
    if histories_override is None:
        for key in _series_keys(config):
            missing_index = None
            count = 544
            if missing is not None and key == missing[0]:
                missing_index = missing[1]
            histories[key] = _bar_series(
                key,
                config.timeframe_grid,
                count=count,
                missing_index=missing_index,
            )
    repository = InMemoryCanonicalMarketHistoryRepository(
        histories,
        timeframe_grid=config.timeframe_grid,
    )
    startup = await DecisionStartupCoordinator(
        decision_config=config,
        plugin_catalog=composition.plugin_catalog,
        feature_catalog=composition.feature_catalog,
        feature_policy=composition.feature_policy,
        data_policy=composition.data_policy,
        source_catalog=composition.data_source_catalog,
        runtime_plugin_catalog=composition.runtime_plugin_catalog,
        history_repository=repository,
        stream_client=_EmptyStreamClient(),
        checkpoint_repository=InMemoryCheckpointRepository(),
        data_resolver=composition.data_resolver,
        policy_catalog=composition.policy_catalog,
    ).start()
    return startup, repository, histories


def _view_for(config: DecisionConfig, startup, lane):
    key = MarketSeriesKey(
        asset=lane.asset,
        venue=lane.venue,
        instrument_id=lane.instrument_id,
        timeframe=lane.trigger_timeframe,
    )
    cutoff = startup.snapshot.lane_evidence[lane.lane_id].resume_cutoff
    return DecisionViewBuilder(
        startup.bar_store,
        config.timeframe_grid,
    ).build(
        lane,
        startup.lane_requirements[lane.lane_id],
        cutoff,
        input_read_cursor=startup.snapshot.input_cursors[
            canonical_ingestion_stream_key(key)
        ],
        lane_commit_watermark=startup.snapshot.lane_watermarks[lane.lane_id],
    )


def _event_fields(bar: CausalBarView, key: MarketSeriesKey) -> dict[str, str]:
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
        "source_provider": "binance",
        "source_timeframe": None,
    }
    return {
        "event_id": f"m4-{key.asset}-{key.timeframe}-{bar.bar_open_at.isoformat()}",
        "event_type": "candle.committed",
        "schema_version": "1",
        "producer": "ingestion",
        "occurred_at": bar.bar_close_at.isoformat().replace("+00:00", "Z"),
        "payload": json.dumps(payload),
    }


def _next_bar(
    key: MarketSeriesKey, bars: tuple[CausalBarView, ...], grid
) -> CausalBarView:
    previous = bars[-1]
    duration = grid.duration(key.timeframe)
    opened = previous.bar_close_at
    close = previous.close + Decimal("0.1")
    return CausalBarView(
        timeframe=key.timeframe,
        bar_open_at=opened,
        bar_close_at=opened + duration,
        market_as_of=opened + duration,
        open=previous.close,
        high=close + Decimal(1),
        low=previous.close - Decimal(1),
        close=close,
        volume=Decimal(10),
        taker_buy_base=Decimal(4),
        closed=True,
    )


def test_m3_route_locks_are_recomputed_from_protected_artifact(
    fixture_config: DecisionConfig,
) -> None:
    artifact = json.loads(M3_ARTIFACT.read_text())
    assert M3_ARTIFACT.stat().st_size > 0
    assert MOMENTUM_M3_ARTIFACT_SHA256 == M3_SHA
    for lane in fixture_config.lane_specs():
        parameters = _route_parameters(fixture_config, lane.lane_id)
        envelope = parse_momentum_binding_parameters(
            parameters,
            expected_asset=lane.asset,
            expected_decision_timeframe=lane.decision_timeframe,
        )
        route = f"{lane.asset}/{lane.decision_timeframe}"
        route_artifact = next(
            item
            for item in artifact["routes"]
            if f"{item['asset']}/{item['timeframe']}" == route
        )
        expected = momentum_route_profile_digest(
            asset=lane.asset,
            decision_timeframe=lane.decision_timeframe,
            model_config=envelope.model_config,
            feature_profile=envelope.feature_profile,
        )
        assert expected == MOMENTUM_ROUTE_PROFILE_LOCKS[route]
        assert (
            route_artifact["recommended_candidate"]["horizon"]["rsi_bars"]
            == envelope.feature_profile.rsi_history_bars
        )
        assert (
            route_artifact["recommended_candidate"]["horizon"]["macd_bars"]
            == envelope.feature_profile.macd_history_bars
        )


def test_composition_is_conditional_and_exact(fixture_config: DecisionConfig) -> None:
    composition = build_production_composition(fixture_config)
    assert {(item.name, item.version) for item in composition.plugin_catalog} == {
        ("momentum", "1"),
        ("sr", "1"),
    }
    assert {
        (item.plugin_name, item.plugin_version)
        for item in composition.runtime_plugin_catalog
    } == {("momentum", "1"), ("sr", "1")}
    assert {(item.name, item.version) for item in composition.feature_catalog} == {
        ("ATR", "1"),
        ("MACD", "1"),
        ("RSI", "1"),
    }
    assert (
        composition.feature_catalog.resolve("RSI").history_requirements[0].bars == 208
    )
    assert (
        composition.feature_catalog.resolve("MACD").history_requirements[0].bars == 544
    )


def test_no_momentum_composition_keeps_sr_only_shape() -> None:
    grid = __import__(
        "apps.decision_app.domain.market_state",
        fromlist=["TimeframeGrid"],
    ).TimeframeGrid(
        alignment_origin=datetime(2026, 1, 5, tzinfo=UTC),
        durations={"1h": timedelta(hours=1)},
    )
    lane = DecisionLaneSettings(
        decision_timeframe="1h",
        trigger_timeframe="1h",
        trigger_mode="on_bar_close",
        bindings={
            "primary": {
                "plugin": "sr",
                "version": "1",
                "parameters": {"sr_config": {}},
            }
        },
        policy=DecisionPolicySettings(
            name="passthrough",
            version="1",
            parameters={"source_slot": "primary"},
        ),
    )
    asset = DecisionAssetSettings(
        manifest_asset="BTC",
        decision_asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        lanes={"sr": lane},
    )
    config = DecisionConfig(
        global_settings=DecisionGlobalSettings(),
        assets={"BTC": asset},
        timeframe_grid=grid,
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
    composition = build_production_composition(config)
    assert [item.name for item in composition.plugin_catalog] == ["sr"]
    assert [
        (item.plugin_name, item.plugin_version)
        for item in composition.runtime_plugin_catalog
    ] == [("sr", "1")]
    assert [item.name for item in composition.feature_catalog] == ["ATR"]


@pytest.mark.parametrize("mutation", ["unknown", "sha", "digest", "route"])
def test_momentum_binding_drift_fails_closed(
    fixture_config: DecisionConfig,
    mutation: str,
) -> None:
    source = copy.deepcopy(
        _plain_mapping(_route_parameters(fixture_config, "BTCUSDT:momentum_1h"))
    )
    if mutation == "unknown":
        source["unexpected"] = True
    elif mutation == "sha":
        source["certification"]["m3_artifact_sha256"] = "0" * 64
    elif mutation == "digest":
        source["certification"]["route_profile_sha256"] = "0" * 64
    else:
        source["certification"]["asset"] = "ETHUSDT"
    with pytest.raises((TypeError, ValueError)):
        parse_momentum_binding_parameters(
            source,
            expected_asset="BTCUSDT",
            expected_decision_timeframe="1h",
        )


@pytest.mark.asyncio
async def test_d4_feature_and_momentum_runtime_parity(
    fixture_config: DecisionConfig,
) -> None:
    composition = build_production_composition(fixture_config)
    startup, _repository, histories = await _startup(fixture_config, composition)
    assert startup.snapshot.status == "STARTUP_READY"
    assert all(
        evidence.status == "STARTUP_READY"
        for evidence in startup.snapshot.lane_evidence.values()
    )
    assert startup.bar_store.capacities
    assert set(startup.bar_store.capacities.values()) == {544}

    for lane in startup.decision_plan.lanes:
        view = _view_for(fixture_config, startup, lane)
        prepared = await startup.runtimes[lane.lane_id].prepare_live(
            view,
            resolver_knowledge_cutoff=view.market_as_of + timedelta(seconds=1),
        )
        envelope = parse_momentum_binding_parameters(
            _route_parameters(fixture_config, lane.lane_id),
            expected_asset=lane.asset,
            expected_decision_timeframe=lane.decision_timeframe,
        )
        profile = envelope.feature_profile
        bars = histories[
            MarketSeriesKey(
                asset=lane.asset,
                venue=lane.venue,
                instrument_id=lane.instrument_id,
                timeframe=lane.decision_timeframe,
            )
        ]
        rsi_bars = bars[-profile.rsi_history_bars :]
        macd_bars = bars[-profile.macd_history_bars :]
        expected_rsi = calculate_rsi(
            [float(bar.close) for bar in rsi_bars],
            period=profile.rsi_period,
        )
        expected_macd = calculate_macd(
            [float(bar.close) for bar in macd_bars],
            fast_period=profile.macd_fast_period,
            slow_period=profile.macd_slow_period,
            signal_period=profile.macd_signal_period,
        )
        features = prepared.feature_resolution.shared_features
        assert features[MOMENTUM_RSI_FEATURE_NAME].version == "1"
        assert features[MOMENTUM_RSI_FEATURE_NAME].market_as_of == view.market_as_of
        assert features[MOMENTUM_RSI_FEATURE_NAME].value == expected_rsi
        assert features[MOMENTUM_MACD_FEATURE_NAME].value == {
            "line": expected_macd.line,
            "signal": expected_macd.signal,
            "histogram": expected_macd.histogram,
        }
        result = next(iter(prepared.binding_results.values()))
        assert result.status == "EXECUTED"
        assert result.outcome is not None
        observation = MomentumObservation(
            rsi=expected_rsi,
            macd_histogram=expected_macd.histogram,
            macd_line=expected_macd.line,
        )
        expected = evaluate_momentum(observation, envelope.model_config)
        assert result.outcome.artifact.artifact_type == "momentum.signal.v1"
        assert result.outcome.artifact.market_as_of == view.market_as_of
        assert result.outcome.artifact.value == {
            "direction": expected.direction,
            "conviction": expected.conviction,
            "score": expected.score,
        }
        if expected.direction == 0:
            assert result.outcome.decision is None
        else:
            assert result.outcome.decision is not None
            assert result.outcome.decision.direction_hint == expected.direction
            assert result.outcome.decision.conviction == expected.conviction
        policy = DecisionPolicy(composition.policy_catalog).evaluate(
            lane,
            prepared,
            decision_ready_at=view.market_as_of + timedelta(seconds=1),
        )
        assert policy.status == ("SIGNAL" if expected.direction else "NO_SIGNAL")


@pytest.mark.asyncio
async def test_route_tail_isolated_from_over_retained_history(
    fixture_config: DecisionConfig,
) -> None:
    composition = build_production_composition(fixture_config)
    base_startup, _base_repository, base_histories = await _startup(
        fixture_config,
        composition,
    )
    target_lane = next(
        lane
        for lane in base_startup.decision_plan.lanes
        if lane.lane_id == "BTCUSDT:momentum_1h"
    )
    base_view = _view_for(fixture_config, base_startup, target_lane)
    base_prepared = await base_startup.runtimes[target_lane.lane_id].prepare_live(
        base_view,
        resolver_knowledge_cutoff=base_view.market_as_of + timedelta(seconds=1),
    )

    key = MarketSeriesKey(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        timeframe="1h",
    )
    altered_outer = list(base_histories[key])
    altered_outer[0] = replace(
        altered_outer[0],
        close=altered_outer[0].close + Decimal("0.1"),
    )
    altered_inner = list(base_histories[key])
    altered_inner[-1] = replace(
        altered_inner[-1],
        close=altered_inner[-1].close + Decimal(1),
    )
    outer_histories = dict(base_histories)
    outer_histories[key] = tuple(altered_outer)
    inner_histories = dict(base_histories)
    inner_histories[key] = tuple(altered_inner)
    outer_startup, _outer_repository, _ = await _startup(
        fixture_config,
        composition,
        histories_override=outer_histories,
    )
    inner_startup, _inner_repository, _ = await _startup(
        fixture_config,
        composition,
        histories_override=inner_histories,
    )
    outer_view = _view_for(fixture_config, outer_startup, target_lane)
    inner_view = _view_for(fixture_config, inner_startup, target_lane)
    outer_prepared = await outer_startup.runtimes[target_lane.lane_id].prepare_live(
        outer_view,
        resolver_knowledge_cutoff=outer_view.market_as_of + timedelta(seconds=1),
    )
    inner_prepared = await inner_startup.runtimes[target_lane.lane_id].prepare_live(
        inner_view,
        resolver_knowledge_cutoff=inner_view.market_as_of + timedelta(seconds=1),
    )
    assert outer_prepared.feature_resolution.shared_features == (
        base_prepared.feature_resolution.shared_features
    )
    assert inner_prepared.feature_resolution.shared_features != (
        base_prepared.feature_resolution.shared_features
    )


@pytest.mark.asyncio
async def test_m4_interior_feature_history_gap_blocks_eth_startup(
    fixture_config: DecisionConfig,
) -> None:
    composition = build_production_composition(fixture_config)
    eth_key = MarketSeriesKey(
        asset="ETHUSDT",
        venue="binance",
        instrument_id="ETH-USDT-PERP",
        timeframe="4h",
    )
    startup, _repository, _histories = await _startup(
        fixture_config,
        composition,
        missing=(eth_key, 10),
    )
    assert startup.snapshot.status == "STARTUP_BLOCKED"
    lane = next(item for item in startup.decision_plan.lanes if item.asset == "ETHUSDT")
    eth_evidence = startup.snapshot.lane_evidence[lane.lane_id]
    assert eth_evidence.status == "BLOCKED"
    assert eth_evidence.resume_cutoff is None
    assert lane.lane_id not in startup.runtimes
    assert lane.lane_id not in startup.snapshot.lane_watermarks
    assert all(
        startup.snapshot.lane_evidence[lane_id].status == "STARTUP_READY"
        for lane_id in ("BTCUSDT:momentum_1h", "BTCUSDT:momentum_4h")
    )


def test_retention_days_cover_certified_eth_history(
    fixture_config: DecisionConfig,
) -> None:
    evidence = build_retention_coverage(fixture_config)
    assert evidence["status"] == "PASS"
    assert evidence["required_bars"] == 544
    assert evidence["minimum_whole_days"] == 91
    assert evidence["configured_retention_days"] == 91
    assert evidence["configured_bar_capacity"] == 546
    assert evidence["ninety_day_bar_capacity"] == 540
    assert evidence["margin_hours"] == pytest.approx(4.0)
    assert all(
        item["configured_retention_includes_oldest_open"] for item in evidence["phases"]
    )
    assert any(
        not item["ninety_day_includes_oldest_open"] for item in evidence["phases"]
    )


@pytest.mark.asyncio
async def test_isolated_live_signal_publication_is_exact_id_and_idempotent(
    fixture_config: DecisionConfig,
) -> None:
    composition = build_production_composition(fixture_config)
    startup, _repository, histories = await _startup(fixture_config, composition)
    key = MarketSeriesKey(
        asset="ETHUSDT",
        venue="binance",
        instrument_id="ETH-USDT-PERP",
        timeframe="4h",
    )
    new_bar = _next_bar(key, histories[key], fixture_config.timeframe_grid)
    stream_key = canonical_ingestion_stream_key(key)
    stream = _LiveStreamClient()
    stream.pending.append(
        (
            f"{stream_key}|{new_bar.bar_open_at}",
            "1-0",
            _event_fields(new_bar, key),
        )
    )
    signal_client = _SignalClient()
    durable_repository = _RecordingCanonicalHistoryRepository(
        histories,
        fixture_config.timeframe_grid,
    )
    publisher = _RecordingPublisher(
        ValkeySignalPublisher(
            signal_client,
            stream_maxlen=1000,
            stream_approximate=True,
        )
    )
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=fixture_config.timeframe_grid,
        stream_client=stream,
        history_repository=durable_repository,
        signal_publisher=publisher,
        batch_size=10,
        block_ms=1000,
        now_fn=lambda: new_bar.market_as_of + timedelta(seconds=1),
    )
    poll = await runtime.poll_once()
    lane_id = "ETHUSDT:momentum_4h"
    result = poll.lane_results[lane_id]
    assert result.policy_status == "SIGNAL"
    assert result.publication_outcome == "PUBLISHED"
    assert result.finalization_status == "COMMITTED"
    signal_stream = "signals:ETHUSDT:4h"
    assert len(signal_client.entries[signal_stream]) == 1
    entry_id, fields = next(iter(signal_client.entries[signal_stream].items()))
    signal = valkey_decode(dict(fields), TradeSignal)
    assert signal.asset == "ETHUSDT"
    assert signal.timeframe == "4h"
    assert signal.timestamp == new_bar.bar_close_at.timestamp()
    assert signal.model_name == "m4-eth-4h"
    assert entry_id.endswith("-0")

    assert len(publisher.envelopes) == 1
    durable_repository.append(key, new_bar)
    stream.pending.append(
        (
            f"{stream_key}|{new_bar.bar_open_at}",
            "2-0",
            _event_fields(new_bar, key),
        )
    )
    duplicate_poll = await runtime.poll_once()
    duplicate_input = next(
        item for item in duplicate_poll.input_results if item.disposition == "DUPLICATE"
    )
    duplicate_result = duplicate_poll.lane_results[lane_id]
    assert duplicate_input.reason == "exact retained canonical duplicate"
    assert duplicate_result.status == "LIVE"
    assert duplicate_result.trigger_cutoff is None
    assert duplicate_result.policy_status is None
    assert duplicate_result.publication_outcome is None
    assert duplicate_result.finalization_status is None
    assert len(publisher.envelopes) == 1
    assert len(signal_client.entries[signal_stream]) == 1

    envelope = publisher.envelopes[0]
    duplicate = await runtime._publisher.publish(envelope)
    assert duplicate.outcome == "ALREADY_IDENTICAL"
    assert len(signal_client.entries[signal_stream]) == 1


@pytest.mark.asyncio
async def test_isolated_live_publication_failure_does_not_publish(
    fixture_config: DecisionConfig,
) -> None:
    composition = build_production_composition(fixture_config)
    startup, repository, histories = await _startup(fixture_config, composition)
    key = MarketSeriesKey(
        asset="ETHUSDT",
        venue="binance",
        instrument_id="ETH-USDT-PERP",
        timeframe="4h",
    )
    new_bar = _next_bar(key, histories[key], fixture_config.timeframe_grid)
    stream_key = canonical_ingestion_stream_key(key)
    stream = _LiveStreamClient()
    stream.pending.append(
        (
            f"{stream_key}|{new_bar.bar_open_at}",
            "1-0",
            _event_fields(new_bar, key),
        )
    )
    signal_client = _SignalClient()
    signal_client.fail_xadd = True
    runtime = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=fixture_config.timeframe_grid,
        stream_client=stream,
        history_repository=repository,
        signal_publisher=ValkeySignalPublisher(signal_client),
        now_fn=lambda: new_bar.market_as_of + timedelta(seconds=1),
    )
    poll = await runtime.poll_once()
    result = poll.lane_results["ETHUSDT:momentum_4h"]
    assert result.status == "RECONSTRUCTION_REQUIRED"
    assert result.publication_outcome == "FAILED"
    assert result.finalization_status == "ABORTED"
    assert signal_client.entries == {}


@pytest.mark.asyncio
async def test_momentum_runtime_has_no_state_and_no_replay_steps(
    fixture_config: DecisionConfig,
) -> None:
    composition = build_production_composition(fixture_config)
    startup, _repository, _histories = await _startup(fixture_config, composition)
    assert all(
        evidence.replay_step_count == 0
        for evidence in startup.snapshot.lane_evidence.values()
    )
    assert all(
        not runtime.stateful_binding_ids for runtime in startup.runtimes.values()
    )
