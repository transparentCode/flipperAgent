from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import pytest

import apps.ingestion_app.services.recovery as recovery_module
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.providers.base import LiveStreamInterrupted
from apps.ingestion_app.runtime.supervisor import RuntimeState, RuntimeSupervisor
from apps.ingestion_app.services.recovery import RecoveryEngine
from apps.ingestion_app.storage.repository import CandleCommitStatus
from libs.common.exceptions import DataIngestionError

from .conftest import (
    BASE_DURATION,
    BOUNDARY,
    ORIGIN,
    ActiveMeter,
    BlockingStream,
    ControlledLiveProvider,
    ControlledRepository,
    FakeHistoricalProvider,
    RecordingHTF,
    RecordingIngestion,
    RecordingRecovery,
    canonical,
    observation,
    recovery_request,
    synthetic_lanes,
    synthetic_settings,
    yield_control,
)

RECOVERY_START = datetime(2026, 1, 1, tzinfo=UTC)


class _RecoveryIngestion(RecordingIngestion):
    def __init__(self, repository: ControlledRepository) -> None:
        super().__init__()
        self.repository = repository

    async def commit_observation(self, observed):
        status = await super().commit_observation(observed)
        if status is CandleCommitStatus.INSERTED:
            self.repository.rows[(observed.lane, observed.open_time)] = canonical(
                observed
            )
        return status


def _provider_symbol_map(settings, provider_ids: tuple[str, ...]) -> dict[str, str]:
    return {provider_id: f"SYNTH-{provider_id}" for provider_id in provider_ids}


def _request_for(lane: MarketLane, offset: int = 0) -> RecoveryRequest:
    since = RECOVERY_START + offset * BASE_DURATION
    return recovery_request(lane, since, since + BASE_DURATION)


def _engine(
    settings,
    *,
    repository,
    ingestion,
    htf,
    providers,
    now_fn=None,
    max_concurrency: int | None = None,
):
    return RecoveryEngine(
        providers=providers,
        repository=repository,
        ingestion_service=ingestion,
        htf_service=htf,
        max_concurrency=max_concurrency or settings.recovery.max_concurrency,
        page_limit=settings.recovery.page_limit,
        max_attempts_per_provider=settings.recovery.max_attempts_per_provider,
        retry_backoff_seconds=settings.recovery.retry_backoff_seconds,
        rest_finalization_grace_seconds=settings.recovery.rest_finalization_grace_seconds,
        now_fn=now_fn or (lambda: BOUNDARY + timedelta(hours=1)),
    )


async def _recover_one(
    engine, request, settings, provider_order, provider_symbols, targets=None
):
    return await engine.recover(
        request,
        base_timeframe=settings.base_timeframe,
        base_duration=BASE_DURATION,
        provider_order=provider_order,
        provider_symbols=provider_symbols,
        target_durations=targets or {},
        alignment_origin=ORIGIN,
    )


@pytest.mark.asyncio
async def test_real_recovery_engine_repairs_500_distinct_lanes_with_global_bound() -> (
    None
):
    settings = synthetic_settings(500)
    lanes = synthetic_lanes(settings)
    repository = ControlledRepository()
    ingestion = _RecoveryIngestion(repository)
    htf = RecordingHTF()
    release = asyncio.Event()
    meter = ActiveMeter(target=settings.recovery.max_concurrency, gate=release)
    provider = FakeHistoricalProvider(
        "binance_native",
        lambda lane, since, until: (
            observation(
                lane,
                since,
                provider_id="binance_native",
                provider_symbol="SYNTH-binance_native",
            ),
        ),
        meter=meter,
    )
    engine = _engine(
        settings,
        repository=repository,
        ingestion=ingestion,
        htf=htf,
        providers={"binance_native": provider},
    )
    symbols = _provider_symbol_map(settings, ("binance_native",))
    requests = [_request_for(lane) for lane in lanes]

    async def run_batch() -> None:
        await asyncio.gather(
            *(
                _recover_one(
                    engine,
                    request,
                    settings,
                    ("binance_native",),
                    symbols,
                )
                for request in requests
            )
        )

    batch = asyncio.create_task(run_batch())
    await asyncio.wait_for(meter.ready.wait(), timeout=2)
    assert meter.maximum == settings.recovery.max_concurrency
    release.set()
    await asyncio.wait_for(batch, timeout=10)

    assert len(provider.calls) == 500
    assert len(ingestion.observations) == 500
    assert len(ingestion.canonical_by_key) == 500
    assert meter.maximum <= settings.recovery.max_concurrency
    assert len(htf.affected_calls) == 500
    current = asyncio.current_task()
    assert not [
        task
        for task in asyncio.all_tasks()
        if task is not current
        and task.get_name().startswith("Task-")
        and not task.done()
    ]


@pytest.mark.asyncio
async def test_500_lane_primary_retry_then_fallback_is_exact_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = synthetic_settings(500)
    lanes = synthetic_lanes(settings)
    repository = ControlledRepository()
    ingestion = _RecoveryIngestion(repository)
    htf = RecordingHTF()
    meter = ActiveMeter()
    primary_counts: defaultdict[MarketLane, int] = defaultdict(int)

    def primary_handler(lane, since, until):
        del until
        primary_counts[lane] += 1
        return DataIngestionError("primary synthetic failure")

    primary = FakeHistoricalProvider("binance_native", primary_handler, meter=meter)
    fallback = FakeHistoricalProvider(
        "ccxt_binance",
        lambda lane, since, until: (
            observation(
                lane,
                since,
                provider_id="ccxt_binance",
                provider_symbol="SYNTH-ccxt_binance",
            ),
        ),
        meter=meter,
    )

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(recovery_module.asyncio, "sleep", no_sleep)
    engine = _engine(
        settings,
        repository=repository,
        ingestion=ingestion,
        htf=htf,
        providers={"binance_native": primary, "ccxt_binance": fallback},
    )
    requests = [_request_for(lane) for lane in lanes]
    await asyncio.wait_for(
        asyncio.gather(
            *(
                _recover_one(
                    engine,
                    request,
                    settings,
                    ("binance_native", "ccxt_binance"),
                    _provider_symbol_map(settings, ("binance_native", "ccxt_binance")),
                )
                for request in requests
            )
        ),
        timeout=10,
    )

    assert len(primary.calls) == 500 * settings.recovery.max_attempts_per_provider
    assert len(fallback.calls) == 500
    assert all(
        count == settings.recovery.max_attempts_per_provider
        for count in primary_counts.values()
    )
    assert meter.maximum <= settings.recovery.max_concurrency
    assert len(ingestion.observations) == 500


@pytest.mark.asyncio
async def test_provider_exhaustion_is_fatal_without_retry_infinite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = synthetic_settings(20)

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(recovery_module.asyncio, "sleep", no_sleep)
    repository = ControlledRepository()
    ingestion = _RecoveryIngestion(repository)
    htf = RecordingHTF()
    failure = DataIngestionError("all providers unavailable")
    primary = FakeHistoricalProvider("binance_native", lambda *_args: failure)
    fallback = FakeHistoricalProvider("ccxt_binance", lambda *_args: failure)
    engine = _engine(
        settings,
        repository=repository,
        ingestion=ingestion,
        htf=htf,
        providers={"binance_native": primary, "ccxt_binance": fallback},
    )
    requests = [_request_for(lane) for lane in synthetic_lanes(settings)]
    results = await asyncio.gather(
        *(
            _recover_one(
                engine,
                request,
                settings,
                ("binance_native", "ccxt_binance"),
                _provider_symbol_map(settings, ("binance_native", "ccxt_binance")),
            )
            for request in requests
        ),
        return_exceptions=True,
    )

    assert all(isinstance(result, DataIngestionError) for result in results)
    assert len(primary.calls) == 20 * settings.recovery.max_attempts_per_provider
    assert len(fallback.calls) == 20 * settings.recovery.max_attempts_per_provider


@pytest.mark.asyncio
async def test_same_lane_recovery_is_serialized_while_other_lanes_progress() -> None:
    settings = synthetic_settings(8)
    lanes = synthetic_lanes(settings)
    repository = ControlledRepository()
    ingestion = _RecoveryIngestion(repository)
    htf = RecordingHTF()
    release = asyncio.Event()
    meter = ActiveMeter(target=settings.recovery.max_concurrency, gate=release)
    provider = FakeHistoricalProvider(
        "binance_native",
        lambda lane, since, until: (observation(lane, since),),
        meter=meter,
    )
    engine = _engine(
        settings,
        repository=repository,
        ingestion=ingestion,
        htf=htf,
        providers={"binance_native": provider},
    )
    same_lane_requests = [_request_for(lanes[0], index) for index in range(8)]
    other_lane_requests = [_request_for(lane) for lane in lanes[1:]]

    async def run_batch() -> None:
        await asyncio.gather(
            *(
                _recover_one(
                    engine,
                    request,
                    settings,
                    ("binance_native",),
                    _provider_symbol_map(settings, ("binance_native",)),
                )
                for request in [*same_lane_requests, *other_lane_requests]
            )
        )

    batch = asyncio.create_task(run_batch())
    await asyncio.wait_for(meter.ready.wait(), timeout=2)
    release.set()
    await asyncio.wait_for(batch, timeout=10)

    assert provider.max_active_by_lane[lanes[0]] == 1
    assert meter.maximum <= settings.recovery.max_concurrency
    assert provider.max_active > 1


def _supervisor_for_wave(
    *,
    settings,
    streams,
    repository=None,
    ingestion=None,
    htf=None,
    recovery=None,
    now_fn=None,
    reconnect_sleep_fn=None,
):
    lanes = synthetic_lanes(settings)
    repository = repository or ControlledRepository(
        latest={
            lane: canonical(observation(lane, BOUNDARY - BASE_DURATION))
            for lane in lanes
        }
    )
    ingestion = ingestion or RecordingIngestion()
    htf = htf or RecordingHTF()
    recovery = recovery or RecordingRecovery()
    provider = ControlledLiveProvider(streams)
    supervisor = RuntimeSupervisor(
        settings=settings,
        live_provider=provider,
        repository=repository,
        ingestion_service=ingestion,
        htf_service=htf,
        recovery_engine=recovery,
        now_fn=now_fn or (lambda: BOUNDARY + timedelta(seconds=30)),
        reconnect_sleep_fn=reconnect_sleep_fn,
    )
    return supervisor, provider, ingestion, htf, recovery


@pytest.mark.asyncio
async def test_real_supervisor_processes_500_live_observations_and_reaches_live() -> (
    None
):
    settings = synthetic_settings(500)
    observations = tuple(
        observation(lane, BOUNDARY, transport="websocket")
        for lane in synthetic_lanes(settings)
    )
    stream = BlockingStream(observations=observations)
    supervisor, provider, ingestion, htf, _recovery = _supervisor_for_wave(
        settings=settings,
        streams=[stream],
    )
    task = asyncio.create_task(supervisor.run(), name="certification-live-wave")
    for _ in range(100):
        await yield_control()
        if len(ingestion.observations) == 500:
            break
    assert len(ingestion.observations) == 500
    assert len(htf.live_calls) == 500
    assert supervisor.snapshot().state is RuntimeState.LIVE
    assert len(provider.calls) == 1

    supervisor.stop()
    await asyncio.wait_for(task, timeout=3)
    assert stream.closed


@pytest.mark.asyncio
async def test_500_live_wave_mixes_inserted_and_duplicate_but_all_reach_htf() -> None:
    settings = synthetic_settings(500)
    lanes = synthetic_lanes(settings)
    observations = tuple(
        observation(lane, BOUNDARY, transport="websocket") for lane in lanes
    )
    ingestion = RecordingIngestion()
    for observed in observations[:250]:
        ingestion.canonical_by_key[(observed.lane, observed.open_time)] = canonical(
            observed
        )
    stream = BlockingStream(observations=observations)
    supervisor, _provider, _unused, htf, _recovery = _supervisor_for_wave(
        settings=settings,
        streams=[stream],
        ingestion=ingestion,
    )
    task = asyncio.create_task(supervisor.run(), name="certification-mixed-commit")
    for _ in range(100):
        await yield_control()
        if len(ingestion.observations) == 500:
            break
    assert len(ingestion.observations) == 500
    assert len(htf.live_calls) == 500
    assert ingestion.statuses.count(CandleCommitStatus.INSERTED) == 250
    assert ingestion.statuses.count(CandleCommitStatus.DUPLICATE) == 250
    supervisor.stop()
    await asyncio.wait_for(task, timeout=3)


@pytest.mark.asyncio
async def test_live_conflict_at_selected_lane_fails_closed_without_reconnect() -> None:
    settings = synthetic_settings(500)
    lanes = synthetic_lanes(settings)
    selected = lanes[250]
    observations = tuple(
        observation(lane, BOUNDARY, transport="websocket") for lane in lanes
    )
    stream = BlockingStream(observations=observations)
    ingestion = RecordingIngestion(conflict_lane=selected)
    supervisor, provider, _ingestion, _htf, _recovery = _supervisor_for_wave(
        settings=settings,
        streams=[stream],
        ingestion=ingestion,
    )
    task = asyncio.create_task(supervisor.run(), name="certification-conflict")
    with pytest.raises(DataIngestionError):
        await asyncio.wait_for(task, timeout=5)

    assert supervisor.snapshot().state is RuntimeState.ERROR
    assert supervisor.snapshot().last_error
    assert len(provider.created_streams) == 1
    assert stream.closed
    assert len(ingestion.observations) == 251


@pytest.mark.asyncio
async def test_gap_interruption_after_500_lane_wave_does_not_claim_continuity() -> None:
    settings = synthetic_settings(500)
    lanes = synthetic_lanes(settings)
    selected = lanes[0]
    initial_boundary = BOUNDARY + 2 * BASE_DURATION
    interruption = LiveStreamInterrupted(
        reason="websocket_gap_detected",
        recovery_requests=(
            recovery_request(
                selected,
                initial_boundary,
                initial_boundary + BASE_DURATION,
                reason="websocket_gap_detected",
            ),
        ),
    )
    first = BlockingStream(
        observations=tuple(
            observation(lane, initial_boundary, transport="websocket") for lane in lanes
        ),
        interruption=interruption,
    )
    second = BlockingStream()
    latest = {
        lane: canonical(
            observation(
                lane,
                (initial_boundary - 2 * BASE_DURATION)
                if lane == selected
                else initial_boundary - BASE_DURATION,
            )
        )
        for lane in lanes
    }
    repository = ControlledRepository(latest=latest)
    clock = [initial_boundary + timedelta(seconds=30)]

    def update_latest(request: RecoveryRequest) -> None:
        repository.latest[request.lane] = canonical(
            observation(request.lane, request.until - BASE_DURATION)
        )

    recovery = RecordingRecovery(update_latest=update_latest)

    async def advance_clock(_seconds: float) -> None:
        clock[0] += BASE_DURATION

    supervisor, provider, ingestion, _htf, _ = _supervisor_for_wave(
        settings=settings,
        streams=[first, second],
        repository=repository,
        recovery=recovery,
        now_fn=lambda: clock[0],
        reconnect_sleep_fn=advance_clock,
    )
    task = asyncio.create_task(supervisor.run(), name="certification-gap")
    for _ in range(100):
        await yield_control()
        if len(provider.created_streams) == 2:
            break
    assert len(ingestion.observations) == 500
    assert len(provider.created_streams) == 2
    assert any(request.reason == "websocket_gap_detected" for request in recovery.calls)
    assert provider.stream_kwargs[0]["connection_anchor"] == initial_boundary
    assert (
        provider.stream_kwargs[1]["connection_anchor"]
        == initial_boundary + BASE_DURATION
    )

    supervisor.stop()
    await asyncio.wait_for(task, timeout=3)


@pytest.mark.asyncio
async def test_ten_disconnect_cycles_repair_elapsed_tail_before_each_new_anchor() -> (
    None
):
    settings = synthetic_settings(500)
    lanes = synthetic_lanes(settings)
    clock = [BOUNDARY + timedelta(seconds=30)]
    latest = {
        lane: canonical(observation(lane, BOUNDARY - BASE_DURATION)) for lane in lanes
    }
    repository = ControlledRepository(latest=latest)
    expected_anchors = [BOUNDARY + index * BASE_DURATION for index in range(11)]
    streams: list[BlockingStream] = []
    for index in range(10):
        anchor = expected_anchors[index]
        streams.append(
            BlockingStream(
                interruption=LiveStreamInterrupted(
                    reason="websocket_disconnected",
                    recovery_requests=tuple(
                        recovery_request(
                            lane,
                            anchor,
                            anchor + BASE_DURATION,
                            reason="websocket_disconnected",
                        )
                        for lane in lanes
                    ),
                )
            )
        )
    streams.append(BlockingStream())

    def update_latest(request: RecoveryRequest) -> None:
        repository.latest[request.lane] = canonical(
            observation(request.lane, request.until - BASE_DURATION)
        )

    async def advance_clock(_seconds: float) -> None:
        clock[0] += BASE_DURATION

    recovery = RecordingRecovery(update_latest=update_latest)
    supervisor, provider, _ingestion, _htf, _ = _supervisor_for_wave(
        settings=settings,
        streams=streams,
        repository=repository,
        recovery=recovery,
        now_fn=lambda: clock[0],
        reconnect_sleep_fn=advance_clock,
    )
    task = asyncio.create_task(supervisor.run(), name="certification-ten-disconnects")
    for _ in range(2000):
        await yield_control()
        if len(provider.created_streams) == 11:
            break
    assert len(provider.created_streams) == 11
    assert len(recovery.calls) == 10 * 500
    assert [
        kwargs["connection_anchor"] for kwargs in provider.stream_kwargs
    ] == expected_anchors
    assert supervisor.snapshot().state is not RuntimeState.ERROR

    supervisor.stop()
    await asyncio.wait_for(task, timeout=5)
    assert all(stream.closed for stream in provider.created_streams)


@pytest.mark.asyncio
async def test_pause_stop_and_outer_cancel_release_500_lane_recovery() -> None:
    settings = synthetic_settings(500)
    lanes = synthetic_lanes(settings)
    requests = tuple(
        recovery_request(lane, BOUNDARY, BOUNDARY + BASE_DURATION, reason="cert")
        for lane in lanes
    )
    for action in ("pause", "stop", "cancel"):
        gate = asyncio.Event()
        recovery = RecordingRecovery(gate=gate)
        stream = BlockingStream(
            interruption=LiveStreamInterrupted(
                reason="websocket_disconnected",
                recovery_requests=requests,
            )
        )
        supervisor, _provider, _ingestion, _htf, _ = _supervisor_for_wave(
            settings=settings,
            streams=[stream],
            recovery=recovery,
        )
        task = asyncio.create_task(supervisor.run(), name=f"certification-{action}")
        for _ in range(100):
            await yield_control()
            if recovery.calls:
                break
        assert recovery.calls
        if action == "pause":
            supervisor.pause()
        elif action == "stop":
            supervisor.stop()
        else:
            task.cancel()
        gate.set()
        if action == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=3)
        elif action == "pause":
            for _ in range(20):
                await yield_control()
                if supervisor.snapshot().state is RuntimeState.STOPPED:
                    break
            assert supervisor.snapshot().state is RuntimeState.STOPPED
            supervisor.stop()
            await asyncio.wait_for(task, timeout=3)
        else:
            await asyncio.wait_for(task, timeout=3)
        assert stream.closed
        assert supervisor.snapshot().state is RuntimeState.STOPPED
