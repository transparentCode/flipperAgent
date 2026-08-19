from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.decision_app.data.resolver import DataPolicy, DataResolver, DataSourceCatalog
from apps.decision_app.domain.state import LaneExecutionIdentity
from apps.decision_app.features.planning import FeatureCatalog, FeaturePolicy
from apps.decision_app.planning.catalog import PluginCatalog
from apps.decision_app.runtime.live import LiveDecisionRuntime
from apps.decision_app.runtime.plugins import (
    RuntimePluginCatalog,
    RuntimePluginDefinition,
)
from apps.decision_app.runtime.startup import DecisionStartupCoordinator
from apps.decision_app.storage.market_history import (
    InMemoryCanonicalMarketHistoryRepository,
)
from apps.decision_app.storage.shadow_progress import (
    InMemoryLaneEffectProgressRepository,
    LaneEffectProgress,
    LaneEffectProgressSaveResult,
)
from apps.decision_app.transport.signals import ValkeySignalPublisher
from libs.contracts.decision import ModelArtifact, ModelOutcome
from tests.decision.test_d9b_live_runtime import (
    SIGNAL_GRID,
    SIGNAL_SERIES,
    SIGNAL_SPEC,
    _IsolatedSignalClient,
    _LiveInputClient,
    _signal_bar,
    _signal_config,
    _signal_coordinator,
    _signal_fields,
)


class _NoSignalPlugin:
    spec = SIGNAL_SPEC

    def data_requests(self, base_context, state_snapshot=None):
        del base_context, state_snapshot
        return ()

    def evaluate(self, context, state_snapshot=None):
        del state_snapshot
        return ModelOutcome(
            artifact=ModelArtifact(
                binding_id=context.binding_id,
                lane_id=context.lane_id,
                asset=context.asset,
                decision_timeframe=context.decision_timeframe,
                trigger_timeframe=context.trigger_timeframe,
                market_as_of=context.market_as_of,
                artifact_type=self.spec.produces_artifact_type,
            ),
            decision=None,
        )


class _FailOnceNoSignalProgress(InMemoryLaneEffectProgressRepository):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    async def save(self, progress):
        if progress.last_disposition == "no_signal" and not self.failed:
            self.failed = True
            return LaneEffectProgressSaveResult.CONFLICT
        return await super().save(progress)


def _no_signal_coordinator(history, stream, progress):
    source_catalog = DataSourceCatalog([])
    return DecisionStartupCoordinator(
        decision_config=_signal_config(authority="authoritative"),
        plugin_catalog=PluginCatalog([_NoSignalPlugin.spec]),
        feature_catalog=FeatureCatalog([]),
        feature_policy=FeaturePolicy(name="operator", version="1", allowed_features=()),
        data_policy=DataPolicy(name="operator", version="1", concepts={}),
        source_catalog=source_catalog,
        runtime_plugin_catalog=RuntimePluginCatalog(
            [
                RuntimePluginDefinition(
                    plugin_name="test-decision",
                    plugin_version="1",
                    factory=lambda _parameters: _NoSignalPlugin(),
                )
            ]
        ),
        history_repository=history,
        stream_client=stream,
        data_resolver=DataResolver(source_catalog),
        shadow_progress_repository=progress,
    )


@pytest.mark.asyncio
async def test_authoritative_first_start_baselines_effect_progress_without_backfill() -> (
    None
):
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(3))}
    )
    stream = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=2,
        field_factory=_signal_fields,
    )
    progress = InMemoryLaneEffectProgressRepository()

    startup = await _signal_coordinator(
        history,
        stream,
        authority="authoritative",
        shadow_progress_repository=progress,
    ).start()

    runtime = next(iter(startup.runtimes.values()))
    saved = await progress.load(runtime.identity)
    assert saved is not None
    assert saved.market_as_of == _signal_bar(2).market_as_of
    assert saved.last_disposition is None
    assert startup.lane_catchup_cutoffs[runtime.lane.lane_id] == ()
    assert (
        startup.snapshot.lane_watermarks[runtime.lane.lane_id].last_disposition is None
    )


@pytest.mark.asyncio
async def test_authoritative_signal_persists_published_effect_progress() -> None:
    history = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(3))}
    )
    stream = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=2,
        field_factory=_signal_fields,
    )
    progress = InMemoryLaneEffectProgressRepository()
    startup = await _signal_coordinator(
        history,
        stream,
        authority="authoritative",
        shadow_progress_repository=progress,
    ).start()
    publisher_client = _IsolatedSignalClient()
    live = LiveDecisionRuntime(
        startup=startup,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream,
        history_repository=history,
        signal_publisher=ValkeySignalPublisher(publisher_client),
        shadow_progress_repository=progress,
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )

    stream.pending.append(("3-0", _signal_fields(3)))
    result = await live.poll_once()

    lane_id = "BTCUSDT:main"
    assert result.lane_results[lane_id].publication_outcome == "PUBLISHED"
    assert result.lane_results[lane_id].finalization_status == "COMMITTED"
    saved = await progress.load(next(iter(startup.runtimes.values())).identity)
    assert saved is not None
    assert saved.market_as_of == _signal_bar(3).market_as_of
    assert saved.last_disposition == "published"


@pytest.mark.asyncio
async def test_authoritative_restart_drains_exact_effect_backlog_before_live_input() -> (
    None
):
    history_initial = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(6))}
    )
    stream_initial = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=5,
        field_factory=_signal_fields,
    )
    progress = InMemoryLaneEffectProgressRepository()
    startup_initial = await _signal_coordinator(
        history_initial,
        stream_initial,
        authority="authoritative",
        shadow_progress_repository=progress,
        history_capacity=6,
    ).start()
    initial_client = _IsolatedSignalClient()
    initial_live = LiveDecisionRuntime(
        startup=startup_initial,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream_initial,
        history_repository=history_initial,
        signal_publisher=ValkeySignalPublisher(initial_client),
        shadow_progress_repository=progress,
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )
    stream_initial.pending.append(("6-0", _signal_fields(6)))
    await initial_live.poll_once()

    history_restart = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(10))}
    )
    stream_restart = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=9,
        field_factory=_signal_fields,
    )
    startup_restart = await _signal_coordinator(
        history_restart,
        stream_restart,
        authority="authoritative",
        shadow_progress_repository=progress,
        history_capacity=6,
    ).start()

    assert startup_restart.lane_catchup_cutoffs["BTCUSDT:main"] == tuple(
        _signal_bar(index).market_as_of for index in (7, 8, 9)
    )
    restart_live = LiveDecisionRuntime(
        startup=startup_restart,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream_restart,
        history_repository=history_restart,
        signal_publisher=ValkeySignalPublisher(initial_client),
        shadow_progress_repository=progress,
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )
    result = await restart_live.poll_once()

    assert result.lane_results["BTCUSDT:main"].status == "LIVE"
    assert restart_live.lanes["BTCUSDT:main"].startup_catchup_index == 3
    saved = await progress.load(next(iter(startup_restart.runtimes.values())).identity)
    assert saved is not None
    assert saved.market_as_of == _signal_bar(9).market_as_of
    assert saved.last_disposition == "published"
    entries = initial_client.entries["signals:BTCUSDT:1h"]
    assert tuple(entries) == tuple(
        f"{int(_signal_bar(index).market_as_of.timestamp() * 1000)}-0"
        for index in (6, 7, 8, 9)
    )


@pytest.mark.asyncio
async def test_lane_effect_progress_rejects_contradictory_same_cutoff_disposition() -> (
    None
):
    repository = InMemoryLaneEffectProgressRepository()
    identity = LaneEffectProgress.create(
        identity=LaneExecutionIdentity(
            lane_id="BTCUSDT:main",
            effective_lane_revision="lane-revision",
            feature_plan_fingerprint="feature-fingerprint",
            data_plan_fingerprint="data-fingerprint",
        ),
        market_as_of=datetime(2026, 2, 1, tzinfo=UTC),
    )
    assert await repository.save(identity) == LaneEffectProgressSaveResult.INSERTED
    conflicting = LaneEffectProgress(
        identity=identity.identity,
        market_as_of=identity.market_as_of,
        last_disposition="published",
    )
    assert await repository.save(conflicting) == LaneEffectProgressSaveResult.CONFLICT


@pytest.mark.asyncio
async def test_no_signal_progress_failure_replays_without_signal_side_effect() -> None:
    history_initial = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(3))}
    )
    stream_initial = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=2,
        field_factory=_signal_fields,
    )
    progress = _FailOnceNoSignalProgress()
    startup_initial = await _no_signal_coordinator(
        history_initial, stream_initial, progress
    ).start()
    first_live = LiveDecisionRuntime(
        startup=startup_initial,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream_initial,
        history_repository=history_initial,
        shadow_progress_repository=progress,
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )
    stream_initial.pending.append(("3-0", _signal_fields(3)))
    first = await first_live.poll_once()
    assert first.lane_results["BTCUSDT:main"].policy_status == "NO_SIGNAL"
    assert first.lane_results["BTCUSDT:main"].status == "HALTED"

    history_restart = InMemoryCanonicalMarketHistoryRepository(
        {SIGNAL_SERIES: tuple(_signal_bar(index) for index in range(4))}
    )
    stream_restart = _LiveInputClient(
        stream="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        tail_index=3,
        field_factory=_signal_fields,
    )
    startup_restart = await _no_signal_coordinator(
        history_restart, stream_restart, progress
    ).start()
    restart_live = LiveDecisionRuntime(
        startup=startup_restart,
        timeframe_grid=SIGNAL_GRID,
        stream_client=stream_restart,
        history_repository=history_restart,
        shadow_progress_repository=progress,
        now_fn=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )
    second = await restart_live.poll_once()
    assert second.lane_results["BTCUSDT:main"].policy_status == "NO_SIGNAL"
    assert second.lane_results["BTCUSDT:main"].finalization_status == "COMMITTED"
    saved = await progress.load(next(iter(startup_restart.runtimes.values())).identity)
    assert saved is not None
    assert saved.market_as_of == _signal_bar(3).market_as_of
    assert saved.last_disposition == "no_signal"
