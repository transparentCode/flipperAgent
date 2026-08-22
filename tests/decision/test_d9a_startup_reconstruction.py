from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.decision_app.data.resolver import DataPolicy, DataResolver, DataSourceCatalog
from apps.decision_app.domain.market_state import MarketSeriesKey, TimeframeGrid
from apps.decision_app.features.planning import (
    FeatureCatalog,
    FeatureHistoryRequirement,
    FeaturePolicy,
    SharedFeatureDefinition,
    compile_feature_plan,
)
from apps.decision_app.planning.catalog import PluginCatalog
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
from apps.decision_app.storage.market_history import (
    InMemoryCanonicalMarketHistoryRepository,
)
from apps.decision_app.transport.ingestion import canonical_ingestion_stream_key
from libs.contracts.decision import (
    CausalBarView,
    DecisionContext,
    FeatureRequirement,
    ModelArtifact,
    ModelOutcome,
    ModelRequestContext,
    ModelSpec,
)

BASE = datetime(2026, 1, 5, tzinfo=UTC)
GRID = TimeframeGrid(
    alignment_origin=BASE,
    durations={"1h": timedelta(hours=1)},
)
SERIES = MarketSeriesKey(
    asset="BTCUSDT",
    venue="binance",
    instrument_id="BTC-USDT-PERP",
    timeframe="1h",
)


SPEC = ModelSpec(
    name="counter",
    version="1",
    stateful=True,
    output_kind="analytical",
    produces_artifact_type="counter.v1",
    supported_trigger_modes=("on_bar_close",),
)


class CounterPlugin:
    spec = SPEC

    def data_requests(
        self, base_context: ModelRequestContext, state_snapshot: object | None = None
    ):
        return ()

    def evaluate(self, context: DecisionContext, state_snapshot: object | None = None):
        count = 0 if state_snapshot is None else int(state_snapshot)
        return ModelOutcome(
            artifact=ModelArtifact(
                binding_id=context.binding_id,
                lane_id=context.lane_id,
                asset=context.asset,
                decision_timeframe=context.decision_timeframe,
                trigger_timeframe=context.trigger_timeframe,
                market_as_of=context.market_as_of,
                artifact_type="counter.v1",
                value={"count": count + 1},
            ),
            proposed_next_state=count + 1,
        )


FEATURE_SPEC = ModelSpec(
    name="feature-counter",
    version="1",
    stateful=False,
    output_kind="analytical",
    produces_artifact_type="counter.v1",
    supported_trigger_modes=("on_bar_close",),
    intrinsic_feature_requirements=(FeatureRequirement(name="FIXED"),),
)


class FeatureGapPlugin(CounterPlugin):
    spec = FEATURE_SPEC


def _config_for(plugin_name: str) -> DecisionConfig:
    lane = DecisionLaneSettings(
        decision_timeframe="1h",
        trigger_timeframe="1h",
        trigger_mode="on_bar_close",
        policy=DecisionPolicySettings(
            name="passthrough",
            version="1",
            parameters={"source_slot": "counter"},
        ),
        bindings={
            "counter": {
                "plugin": plugin_name,
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
        timeframe_grid=GRID,
        instruments={
            "BTC": CanonicalInstrument(
                manifest_asset="BTC",
                instrument_id="BTC-USDT-PERP",
                venue="binance",
                timeframes=("1h",),
            )
        },
    )


def _config() -> DecisionConfig:
    return _config_for("counter")


def _stateless_config() -> DecisionConfig:
    return _config_for("feature-counter")


def _bar(index: int):
    opened = BASE + timedelta(hours=index)
    closed = opened + timedelta(hours=1)
    return CausalBarView(
        timeframe="1h",
        bar_open_at=opened,
        bar_close_at=closed,
        market_as_of=closed,
        open=Decimal(100),
        high=Decimal(103),
        low=Decimal(99),
        close=Decimal(101),
        volume=Decimal(10),
        taker_buy_base=Decimal(4),
        closed=True,
    )


def _mixed_bar(
    *,
    timeframe: str,
    opened: datetime,
    duration: timedelta,
) -> CausalBarView:
    closed = opened + duration
    return CausalBarView(
        timeframe=timeframe,
        bar_open_at=opened,
        bar_close_at=closed,
        market_as_of=closed,
        open=Decimal(100),
        high=Decimal(103),
        low=Decimal(99),
        close=Decimal(101),
        volume=Decimal(10),
        taker_buy_base=Decimal(4),
        closed=True,
    )


def _stream_fields(index: int) -> dict[str, str]:
    bar = _bar(index)
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
        "event_id": f"event-{index}",
        "event_type": "candle.committed",
        "schema_version": "1",
        "producer": "ingestion",
        "occurred_at": bar.bar_close_at.isoformat().replace("+00:00", "Z"),
        "payload": json.dumps(payload),
    }


class TailClient:
    def __init__(self, index: int) -> None:
        self.index = index

    async def xrevrange(self, stream: str, *_args: object, count: int = 1):
        assert stream == canonical_ingestion_stream_key(SERIES)
        return [(f"{self.index}-0", _stream_fields(self.index))]


class _FixedSaveResultRepository(InMemoryCheckpointRepository):
    def __init__(self, result: object) -> None:
        super().__init__()
        self.result = result
        self.save_calls = 0

    async def save(self, checkpoint):
        self.save_calls += 1
        return self.result


def _coordinator(history, checkpoints, tail_index: int):
    return DecisionStartupCoordinator(
        decision_config=_config(),
        plugin_catalog=PluginCatalog([SPEC]),
        feature_catalog=FeatureCatalog([]),
        feature_policy=FeaturePolicy(name="operator", version="1"),
        data_policy=DataPolicy(name="operator", version="1"),
        source_catalog=DataSourceCatalog([]),
        runtime_plugin_catalog=RuntimePluginCatalog(
            [
                RuntimePluginDefinition(
                    plugin_name="counter",
                    plugin_version="1",
                    factory=lambda _parameters: CounterPlugin(),
                    initialization_requirement=lambda _binding: (
                        StateInitializationRequirement(trigger_steps=2)
                    ),
                )
            ]
        ),
        history_repository=history,
        stream_client=TailClient(tail_index),
        checkpoint_repository=checkpoints,
        data_resolver=DataResolver(DataSourceCatalog([])),
    )


def _stateless_coordinator(history, checkpoints, tail_index: int):
    return DecisionStartupCoordinator(
        decision_config=_stateless_config(),
        plugin_catalog=PluginCatalog([FEATURE_SPEC]),
        feature_catalog=FeatureCatalog(
            [
                SharedFeatureDefinition(
                    name="FIXED",
                    version="1",
                    calculator=lambda _context: pytest.fail(
                        "startup must not evaluate features"
                    ),
                    history_requirements=(
                        FeatureHistoryRequirement(
                            source="fixed",
                            timeframe="1h",
                            bars=3,
                        ),
                    ),
                )
            ]
        ),
        feature_policy=FeaturePolicy(
            name="operator",
            version="1",
            allowed_features=("FIXED",),
        ),
        data_policy=DataPolicy(name="operator", version="1"),
        source_catalog=DataSourceCatalog([]),
        runtime_plugin_catalog=RuntimePluginCatalog(
            [
                RuntimePluginDefinition(
                    plugin_name="feature-counter",
                    plugin_version="1",
                    factory=lambda _parameters: FeatureGapPlugin(),
                )
            ]
        ),
        history_repository=history,
        stream_client=TailClient(tail_index),
        checkpoint_repository=checkpoints,
        data_resolver=DataResolver(DataSourceCatalog([])),
    )


@pytest.mark.asyncio
async def test_stateless_feature_history_gap_blocks_at_selected_resume_cutoff() -> None:
    healthy_history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: tuple(_bar(index) for index in range(5))},
        timeframe_grid=GRID,
    )
    healthy = await _stateless_coordinator(
        healthy_history,
        InMemoryCheckpointRepository(),
        tail_index=3,
    ).start()
    assert healthy.snapshot.status == "STARTUP_READY"
    assert healthy.snapshot.lane_watermarks

    gap_history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: tuple(_bar(index) for index in (0, 1, 3, 4))},
        timeframe_grid=GRID,
    )
    blocked = await _stateless_coordinator(
        gap_history,
        InMemoryCheckpointRepository(),
        tail_index=3,
    ).start()
    evidence = blocked.snapshot.lane_evidence["BTCUSDT:main"]
    assert blocked.snapshot.status == "STARTUP_BLOCKED"
    assert evidence.status == "BLOCKED"
    assert blocked.snapshot.lane_watermarks == {}
    assert not blocked.runtimes


@pytest.mark.asyncio
async def test_startup_captures_tail_before_db_ahead_warmup_and_reconstructs() -> None:
    bars = tuple(_bar(index) for index in range(5))
    history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: bars}, timeframe_grid=GRID
    )
    checkpoints = InMemoryCheckpointRepository()
    result = await _coordinator(history, checkpoints, tail_index=3).start()

    position = result.snapshot.series_positions[SERIES]
    cursor = result.snapshot.input_cursors[position.stream_key]
    assert result.snapshot.status == "STARTUP_READY"
    assert position.captured_tail_id == "3-0"
    assert position.captured_tail_market_as_of == bars[3].market_as_of
    assert position.warm_cutoff == bars[4].market_as_of
    assert cursor.latest_stream_id == "3-0"
    assert cursor.latest_market_as_of == bars[4].market_as_of
    assert result.snapshot.lane_watermarks["BTCUSDT:main"].last_disposition is None
    assert result.snapshot.lane_evidence["BTCUSDT:main"].replay_step_count == 2


@pytest.mark.asyncio
async def test_checkpointed_restart_replays_only_next_contiguous_transition() -> None:
    checkpoints = InMemoryCheckpointRepository()
    first_history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: tuple(_bar(index) for index in range(5))},
        timeframe_grid=GRID,
    )
    first = await _coordinator(first_history, checkpoints, tail_index=3).start()
    first_checkpoint = await checkpoints.load(
        next(iter(first.runtimes.values())).identity
    )
    assert first_checkpoint is not None
    assert first_checkpoint.market_as_of == _bar(4).market_as_of

    second_history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: tuple(_bar(index) for index in range(6))},
        timeframe_grid=GRID,
    )
    second = await _coordinator(second_history, checkpoints, tail_index=5).start()
    second_checkpoint = await checkpoints.load(
        next(iter(second.runtimes.values())).identity
    )
    assert second_checkpoint is not None
    assert second_checkpoint.market_as_of == _bar(5).market_as_of
    assert second.snapshot.lane_evidence["BTCUSDT:main"].checkpoint_loaded is True
    assert second.snapshot.lane_evidence["BTCUSDT:main"].replay_step_count == 1


@pytest.mark.asyncio
async def test_checkpoint_retention_gap_blocks_without_reset() -> None:
    checkpoints = InMemoryCheckpointRepository()
    initial = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: tuple(_bar(index) for index in range(5))},
        timeframe_grid=GRID,
    )
    await _coordinator(initial, checkpoints, tail_index=3).start()
    gap_history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: tuple(_bar(index) for index in (0, 1, 2, 3, 4, 6))},
        timeframe_grid=GRID,
    )
    result = await _coordinator(gap_history, checkpoints, tail_index=5).start()
    assert result.snapshot.status == "STARTUP_BLOCKED"
    assert "bridge" in (result.snapshot.lane_evidence["BTCUSDT:main"].reason or "")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "save_result",
    [
        CheckpointSaveResult.INSERTED,
        CheckpointSaveResult.UPDATED,
        CheckpointSaveResult.IDENTICAL,
    ],
)
async def test_safe_checkpoint_save_results_allow_startup(
    save_result: CheckpointSaveResult,
) -> None:
    repository = _FixedSaveResultRepository(save_result)
    history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: tuple(_bar(index) for index in range(5))},
        timeframe_grid=GRID,
    )

    result = await _coordinator(history, repository, tail_index=3).start()

    assert result.snapshot.status == "STARTUP_READY"
    assert result.runtimes
    assert result.snapshot.lane_watermarks
    assert (
        result.snapshot.lane_evidence["BTCUSDT:main"].checkpoint_save_result
        == save_result.value
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "save_result",
    [CheckpointSaveResult.CONFLICT, CheckpointSaveResult.REJECTED_OLDER],
)
async def test_unsafe_checkpoint_save_results_block_before_runtime_and_watermark(
    save_result: CheckpointSaveResult,
) -> None:
    repository = _FixedSaveResultRepository(save_result)
    history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: tuple(_bar(index) for index in range(5))},
        timeframe_grid=GRID,
    )

    result = await _coordinator(history, repository, tail_index=3).start()
    evidence = result.snapshot.lane_evidence["BTCUSDT:main"]

    assert result.snapshot.status == "STARTUP_BLOCKED"
    assert evidence.status == "BLOCKED"
    assert evidence.checkpoint_save_result is None
    assert "checkpoint persistence" in (evidence.reason or "")
    assert save_result.value in (evidence.reason or "")
    assert not result.runtimes
    assert not result.snapshot.lane_watermarks


@pytest.mark.asyncio
async def test_unsupported_checkpoint_save_result_fails_closed() -> None:
    repository = _FixedSaveResultRepository("INSERTED")
    history = InMemoryCanonicalMarketHistoryRepository(
        {SERIES: tuple(_bar(index) for index in range(5))},
        timeframe_grid=GRID,
    )

    result = await _coordinator(history, repository, tail_index=3).start()
    evidence = result.snapshot.lane_evidence["BTCUSDT:main"]

    assert result.snapshot.status == "STARTUP_BLOCKED"
    assert evidence.status == "BLOCKED"
    assert "unsupported result" in (evidence.reason or "")
    assert not result.runtimes
    assert not result.snapshot.lane_watermarks


@dataclass(frozen=True, slots=True)
class _Manifest:
    symbol: str
    source: str
    enabled: bool
    desired_state: str


class _ManifestStore:
    def __init__(self, states: dict[str, str]) -> None:
        self.states = states
        self.asset_reads: list[str] = []
        self.timeframe_reads: list[tuple[str, str]] = []

    async def read_asset(self, symbol: str):
        self.asset_reads.append(symbol)
        return _Manifest(symbol, "ingestion", True, "LIVE")

    async def read_timeframe(self, symbol: str, timeframe: str):
        self.timeframe_reads.append((symbol, timeframe))
        state = self.states.get(timeframe)
        if state is None:
            return None
        return _Manifest(symbol, "ingestion", True, state)


class _IdentityManifestStore:
    def __init__(
        self,
        *,
        assets: tuple[_Manifest, ...] = (),
        timeframes: tuple[tuple[str, str, _Manifest], ...] = (),
    ) -> None:
        self.assets = {manifest.symbol: manifest for manifest in assets}
        self.timeframes = {
            (symbol, timeframe): manifest for symbol, timeframe, manifest in timeframes
        }

    async def read_asset(self, symbol: str):
        return self.assets.get(symbol)

    async def read_timeframe(self, symbol: str, timeframe: str):
        return self.timeframes.get((symbol, timeframe))


def _feature_plan_for_manifest_gate():
    feature_spec = ModelSpec(
        name="feature-counter",
        version="1",
        stateful=True,
        output_kind="analytical",
        produces_artifact_type="counter.v1",
        supported_trigger_modes=("on_bar_close",),
        intrinsic_feature_requirements=(FeatureRequirement(name="FIXED"),),
    )
    lane_spec = DecisionLaneSettings(
        decision_timeframe="1h",
        trigger_timeframe="1h",
        trigger_mode="on_bar_close",
        policy=DecisionPolicySettings(
            name="passthrough",
            version="1",
            parameters={"source_slot": "counter"},
        ),
        bindings={"counter": {"plugin": "feature-counter", "version": "1"}},
    )
    asset = DecisionAssetSettings(
        manifest_asset="BTC",
        decision_asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        lanes={"main": lane_spec},
    )
    config = DecisionConfig(
        global_settings=DecisionGlobalSettings(),
        assets={"BTC": asset},
        timeframe_grid=TimeframeGrid(
            alignment_origin=BASE,
            durations={"1h": timedelta(hours=1), "4h": timedelta(hours=4)},
        ),
        instruments={
            "BTC": CanonicalInstrument(
                manifest_asset="BTC",
                instrument_id="BTC-USDT-PERP",
                venue="binance",
                timeframes=("1h", "4h"),
            )
        },
    )
    plan = __import__(
        "apps.decision_app.planning.planner", fromlist=["compile_decision_plan"]
    ).compile_decision_plan(PluginCatalog([feature_spec]), config.lane_specs())
    feature_plan = compile_feature_plan(
        plan.lanes[0],
        FeatureCatalog(
            [
                SharedFeatureDefinition(
                    name="FIXED",
                    version="1",
                    calculator=lambda context: 1,
                    history_requirements=(
                        FeatureHistoryRequirement(
                            source="fixed", timeframe="4h", bars=1
                        ),
                    ),
                )
            ]
        ),
        FeaturePolicy(name="operator", version="1", allowed_features=("FIXED",)),
        config.timeframe_grid,
    )
    return config, plan, {plan.lanes[0].lane_id: feature_plan}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("states", "expected_active"),
    [
        ({"1h": "LIVE", "4h": "LIVE"}, True),
        ({"1h": "LIVE", "4h": "STOPPED"}, False),
        ({"1h": "LIVE"}, False),
        ({"1h": "LIVE", "4h": "LIVE", "2h": "STOPPED"}, True),
    ],
)
async def test_manifest_gate_uses_compiled_feature_timeframes(
    states: dict[str, str], expected_active: bool
) -> None:
    config, plan, feature_plans = _feature_plan_for_manifest_gate()
    store = _ManifestStore(states)
    coordinator = DecisionStartupCoordinator(
        decision_config=config,
        plugin_catalog=PluginCatalog(
            [next(iter(plan.lanes[0].bindings.values())).model_spec]
        ),
        feature_catalog=FeatureCatalog([]),
        feature_policy=FeaturePolicy(name="operator", version="1"),
        data_policy=DataPolicy(name="operator", version="1"),
        source_catalog=DataSourceCatalog([]),
        runtime_plugin_catalog=RuntimePluginCatalog([]),
        history_repository=InMemoryCanonicalMarketHistoryRepository(
            {}, timeframe_grid=config.timeframe_grid
        ),
        manifest_store=store,
    )

    active = await coordinator._active_manifest_assets(plan, feature_plans)

    assert ("BTCUSDT" in active) is expected_active
    assert store.asset_reads == ["BTCUSDT"]
    assert {symbol for symbol, _timeframe in store.timeframe_reads} == {"BTCUSDT"}


def _manifest(
    symbol: str,
    *,
    source: str = "ingestion",
    enabled: bool = True,
    desired_state: str = "LIVE",
) -> _Manifest:
    return _Manifest(symbol, source, enabled, desired_state)


def _manifest_gate_coordinator(store: _IdentityManifestStore):
    config, plan, feature_plans = _feature_plan_for_manifest_gate()
    coordinator = DecisionStartupCoordinator(
        decision_config=config,
        plugin_catalog=PluginCatalog(
            [next(iter(plan.lanes[0].bindings.values())).model_spec]
        ),
        feature_catalog=FeatureCatalog([]),
        feature_policy=FeaturePolicy(name="operator", version="1"),
        data_policy=DataPolicy(name="operator", version="1"),
        source_catalog=DataSourceCatalog([]),
        runtime_plugin_catalog=RuntimePluginCatalog([]),
        history_repository=InMemoryCanonicalMarketHistoryRepository(
            {}, timeframe_grid=config.timeframe_grid
        ),
        manifest_store=store,
    )
    return coordinator, plan, feature_plans


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "assets", "timeframes", "expected_active"),
    [
        (
            "canonical runtime manifest and timeframes",
            (_manifest("BTCUSDT"),),
            (
                ("BTCUSDT", "1h", _manifest("BTCUSDT")),
                ("BTCUSDT", "4h", _manifest("BTCUSDT")),
            ),
            True,
        ),
        ("missing runtime manifest", (), (), False),
        (
            "wrong source",
            (_manifest("BTCUSDT", source="operator"),),
            (
                ("BTCUSDT", "1h", _manifest("BTCUSDT")),
                ("BTCUSDT", "4h", _manifest("BTCUSDT")),
            ),
            False,
        ),
        (
            "non-live runtime manifest",
            (_manifest("BTCUSDT", desired_state="STOPPED"),),
            (
                ("BTCUSDT", "1h", _manifest("BTCUSDT")),
                ("BTCUSDT", "4h", _manifest("BTCUSDT")),
            ),
            False,
        ),
        (
            "missing required timeframe",
            (_manifest("BTCUSDT"),),
            (("BTCUSDT", "1h", _manifest("BTCUSDT")),),
            False,
        ),
        (
            "stale config key alone",
            (_manifest("BTC"),),
            (
                ("BTC", "1h", _manifest("BTC")),
                ("BTC", "4h", _manifest("BTC")),
            ),
            False,
        ),
        (
            "canonical runtime identity wins over stale key",
            (_manifest("BTC"), _manifest("BTCUSDT")),
            (
                ("BTC", "1h", _manifest("BTC")),
                ("BTC", "4h", _manifest("BTC")),
                ("BTCUSDT", "1h", _manifest("BTCUSDT")),
                ("BTCUSDT", "4h", _manifest("BTCUSDT")),
            ),
            True,
        ),
    ],
)
async def test_manifest_gate_is_fail_closed_on_runtime_identity(
    case: str,
    assets: tuple[_Manifest, ...],
    timeframes: tuple[tuple[str, str, _Manifest], ...],
    expected_active: bool,
) -> None:
    del case
    store = _IdentityManifestStore(assets=assets, timeframes=timeframes)
    coordinator, plan, feature_plans = _manifest_gate_coordinator(store)

    active = await coordinator._active_manifest_assets(plan, feature_plans)

    assert ("BTCUSDT" in active) is expected_active


MIXED_GRID = TimeframeGrid(
    alignment_origin=BASE,
    durations={"1h": timedelta(hours=1), "4h": timedelta(hours=4)},
)
MIXED_1H = MarketSeriesKey(
    asset="BTCUSDT",
    venue="binance",
    instrument_id="BTC-USDT-PERP",
    timeframe="1h",
)
MIXED_4H = MarketSeriesKey(
    asset="BTCUSDT",
    venue="binance",
    instrument_id="BTC-USDT-PERP",
    timeframe="4h",
)
MIXED_SPEC = ModelSpec(
    name="mixed-counter",
    version="1",
    stateful=True,
    output_kind="analytical",
    produces_artifact_type="counter.v1",
    supported_trigger_modes=("on_bar_close",),
    intrinsic_feature_requirements=(FeatureRequirement(name="FIXED"),),
)


class _MixedCounterPlugin(CounterPlugin):
    spec = MIXED_SPEC


class _RecordingHistory(InMemoryCanonicalMarketHistoryRepository):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls: list[dict[str, object]] = []

    async def fetch_bars(self, key, **kwargs):
        self.calls.append({"key": key, **kwargs})
        return await super().fetch_bars(key, **kwargs)


def _mixed_config() -> DecisionConfig:
    lane = DecisionLaneSettings(
        decision_timeframe="4h",
        trigger_timeframe="4h",
        trigger_mode="on_bar_close",
        policy=DecisionPolicySettings(
            name="passthrough",
            version="1",
            parameters={"source_slot": "counter"},
        ),
        bindings={"counter": {"plugin": "mixed-counter", "version": "1"}},
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
        timeframe_grid=MIXED_GRID,
        instruments={
            "BTC": CanonicalInstrument(
                manifest_asset="BTC",
                instrument_id="BTC-USDT-PERP",
                venue="binance",
                timeframes=("1h", "4h"),
            )
        },
    )


def _mixed_stream_fields(key: MarketSeriesKey, bar: CausalBarView) -> dict[str, str]:
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
        "event_id": f"event-{key.timeframe}-{bar.bar_close_at.isoformat()}",
        "event_type": "candle.committed",
        "schema_version": "1",
        "producer": "ingestion",
        "occurred_at": bar.bar_close_at.isoformat().replace("+00:00", "Z"),
        "payload": json.dumps(payload),
    }


class _MixedTailClient:
    def __init__(self, bars_by_series):
        self._bars_by_series = bars_by_series

    async def xrevrange(self, stream: str, *_args: object, count: int = 1):
        for key, bars in self._bars_by_series.items():
            if stream == canonical_ingestion_stream_key(key):
                bar = bars[-1]
                return [
                    (
                        f"{int(bar.market_as_of.timestamp())}-0",
                        _mixed_stream_fields(key, bar),
                    )
                ]
        raise AssertionError(f"unexpected stream: {stream}")


def _mixed_coordinator(history: _RecordingHistory, tail_bars):
    return DecisionStartupCoordinator(
        decision_config=_mixed_config(),
        plugin_catalog=PluginCatalog([MIXED_SPEC]),
        feature_catalog=FeatureCatalog(
            [
                SharedFeatureDefinition(
                    name="FIXED",
                    version="1",
                    calculator=lambda _context: Decimal(1),
                    history_requirements=(
                        FeatureHistoryRequirement(
                            source="fixed",
                            timeframe="1h",
                            bars=2,
                        ),
                    ),
                )
            ]
        ),
        feature_policy=FeaturePolicy(
            name="operator",
            version="1",
            allowed_features=("FIXED",),
        ),
        data_policy=DataPolicy(name="operator", version="1"),
        source_catalog=DataSourceCatalog([]),
        runtime_plugin_catalog=RuntimePluginCatalog(
            [
                RuntimePluginDefinition(
                    plugin_name="mixed-counter",
                    plugin_version="1",
                    factory=lambda _parameters: _MixedCounterPlugin(),
                    initialization_requirement=lambda _binding: (
                        StateInitializationRequirement(trigger_steps=5)
                    ),
                )
            ]
        ),
        history_repository=history,
        stream_client=_MixedTailClient(tail_bars),
        checkpoint_repository=InMemoryCheckpointRepository(),
        data_resolver=DataResolver(DataSourceCatalog([])),
    )


def _mixed_history(*, missing_1h_index: int | None = None):
    one_hour = tuple(
        _mixed_bar(
            timeframe="1h",
            opened=BASE + timedelta(hours=index),
            duration=timedelta(hours=1),
        )
        for index in range(40)
        if index != missing_1h_index
    )
    four_hour = tuple(
        _mixed_bar(
            timeframe="4h",
            opened=BASE + timedelta(hours=4 * index),
            duration=timedelta(hours=4),
        )
        for index in range(10)
    )
    return {MIXED_1H: one_hour, MIXED_4H: four_hour}


@pytest.mark.asyncio
async def test_mixed_timeframe_reconstruction_uses_lane_range_not_ratio_tail() -> None:
    bars_by_series = _mixed_history()
    history = _RecordingHistory(bars_by_series, timeframe_grid=MIXED_GRID)
    result = await _mixed_coordinator(history, bars_by_series).start()

    assert result.snapshot.status == "STARTUP_READY"
    evidence = result.snapshot.lane_evidence["BTCUSDT:main"]
    assert evidence.replay_step_count == 5
    assert result.snapshot.no_publication is True
    assert result.bar_store.capacity_for(MIXED_1H) == 2
    assert result.bar_store.capacity_for(MIXED_4H) == 1
    assert result.bar_store.retained_count(MIXED_1H) == 2
    assert result.bar_store.retained_count(MIXED_4H) == 1

    reconstruction_1h = [
        call
        for call in history.calls
        if call["key"] == MIXED_1H and call.get("start") is not None
    ]
    assert len(reconstruction_1h) == 1
    assert reconstruction_1h[0]["start"] == BASE + timedelta(hours=22)
    assert reconstruction_1h[0]["through"] == BASE + timedelta(hours=40)


@pytest.mark.asyncio
async def test_mixed_timeframe_pre_replay_gap_blocks_without_shortening_inception() -> (
    None
):
    bars_by_series = _mixed_history(missing_1h_index=22)
    history = _RecordingHistory(bars_by_series, timeframe_grid=MIXED_GRID)
    result = await _mixed_coordinator(history, bars_by_series).start()

    assert result.snapshot.status == "STARTUP_BLOCKED"
    evidence = result.snapshot.lane_evidence["BTCUSDT:main"]
    assert evidence.status == "BLOCKED"
    assert not result.runtimes
    assert not result.snapshot.lane_watermarks
