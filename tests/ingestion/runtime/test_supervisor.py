from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.ingestion_app.domain.candle import CandleObservation, CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.providers.base import LiveStreamInterrupted
from apps.ingestion_app.runtime.supervisor import (
    DesiredRuntimeState,
    RuntimeState,
    RuntimeSupervisor,
)
from apps.ingestion_app.services.time_alignment import aligned_bucket_start
from apps.ingestion_app.storage.repository import CandleCommitStatus
from libs.common.exceptions import DataIngestionError

ORIGIN = datetime(1970, 1, 5, tzinfo=UTC)
NOW = datetime(2026, 8, 9, 10, 0, 30, tzinfo=UTC)
BOUNDARY = datetime(2026, 8, 9, 10, 0, tzinfo=UTC)
LANE = MarketLane("binance", "BTC-TEST-PERP", "1m")
ETH_LANE = MarketLane("binance", "ETH-TEST-PERP", "1m")


def _settings(
    *,
    target_timeframes: tuple[str, ...] = (),
    include_eth: bool = False,
) -> object:
    timeframe_values = {"1m": {"duration_seconds": 60}}
    for timeframe in target_timeframes:
        timeframe_values[timeframe] = {
            "duration_seconds": {"1h": 3600, "2h": 7200}[timeframe]
        }
    instruments: dict[str, dict[str, object]] = {
        "BTC-TEST-PERP": {
            "venue": "binance",
            "market_type": "perpetual",
            "base_asset": "BTC",
            "quote_asset": "USDT",
            "settlement_asset": "USDT",
            "live_provider": "binance_native",
            "historical_providers": ["binance_native", "ccxt_binance"],
            "provider_symbols": {
                "binance_native": "BTCUSDT",
                "ccxt_binance": "BTC/USDT:USDT",
            },
            "timeframes": ["1m", *target_timeframes],
        }
    }
    assets: dict[str, dict[str, object]] = {
        "BTC": {
            "asset": "BTC",
            "enabled": True,
            "instruments": instruments,
        }
    }
    if include_eth:
        assets["ETH"] = {
            "asset": "ETH",
            "enabled": True,
            "instruments": {
                "ETH-TEST-PERP": {
                    "venue": "binance",
                    "market_type": "perpetual",
                    "base_asset": "ETH",
                    "quote_asset": "USDT",
                    "settlement_asset": "USDT",
                    "live_provider": "binance_native",
                    "historical_providers": [
                        "binance_native",
                        "ccxt_binance",
                    ],
                    "provider_symbols": {
                        "binance_native": "ETHUSDT",
                        "ccxt_binance": "ETH/USDT:USDT",
                    },
                    "timeframes": ["1m", *target_timeframes],
                }
            },
        }

    from apps.ingestion_app.settings import IngestionSettings

    return IngestionSettings.model_validate(
        {
            "base_timeframe": "1m",
            "calendar": {
                "type": "continuous",
                "timezone": "UTC",
                "alignment_origin": "1970-01-05T00:00:00Z",
            },
            "recovery": {
                "max_concurrency": 2,
                "page_limit": 500,
                "max_attempts_per_provider": 1,
                "retry_backoff_seconds": 0,
                "rest_finalization_grace_seconds": 5,
            },
            "websocket": {
                "stream_url": "wss://fstream.binance.com/market",
                "queue_maxsize": 10,
            },
            "runtime": {"reconnect_backoff_seconds": 0},
            "server": {"host": "127.0.0.1", "port": 8003},
            "publication": {
                "batch_size": 500,
                "idle_sleep_seconds": 1,
                "error_backoff_seconds": 1,
                "stream_maxlen": 1000,
                "stream_approximate": True,
            },
            "retention": {
                "candle_days": 90,
                "published_outbox_days": 7,
                "cleanup_interval_seconds": 86400,
                "error_backoff_seconds": 60,
                "outbox_delete_batch_size": 10000,
                "outbox_max_batches_per_run": 100,
            },
            "timeframes": timeframe_values,
            "providers": {
                "binance_native": {"enabled": True},
                "ccxt_binance": {"enabled": True, "exchange_id": "binanceusdm"},
            },
            "assets": assets,
        }
    )


def _canonical(
    lane: MarketLane = LANE,
    *,
    close_time: datetime = BOUNDARY,
) -> CanonicalCandle:
    return CanonicalCandle(
        lane=lane,
        open_time=close_time - timedelta(minutes=1),
        close_time=close_time,
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal("100.5"),
        volume=Decimal(1),
        taker_buy_base=Decimal("0.5"),
        source_type="provider",
        source_provider="binance_native",
        source_timeframe=None,
    )


def _observation(
    lane: MarketLane = LANE,
    *,
    open_time: datetime = datetime(2026, 8, 9, 9, 59, tzinfo=UTC),
) -> CandleObservation:
    return CandleObservation(
        lane=lane,
        provider_id="binance_native",
        provider_symbol="BTCUSDT",
        transport="websocket",
        open_time=open_time,
        close_time=open_time + timedelta(minutes=1),
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal("100.5"),
        volume=Decimal(1),
        taker_buy_base=Decimal("0.5"),
        received_at=open_time + timedelta(minutes=1),
        provider_close_time=open_time + timedelta(minutes=1),
        provider_event_id=None,
    )


class _Repository:
    def __init__(self, latest: dict[MarketLane, CanonicalCandle] | None = None) -> None:
        self.latest = latest or {}
        self.latest_calls: list[tuple[MarketLane, datetime]] = []

    async def fetch_latest_candle(
        self,
        *,
        lane: MarketLane,
        before: datetime,
    ) -> CanonicalCandle | None:
        self.latest_calls.append((lane, before))
        return self.latest.get(lane)


class _Ingestion:
    def __init__(
        self, status: CandleCommitStatus = CandleCommitStatus.INSERTED
    ) -> None:
        self.status = status
        self.observations: list[CandleObservation] = []

    async def commit_observation(
        self,
        observation: CandleObservation,
    ) -> CandleCommitStatus:
        self.observations.append(observation)
        return self.status


class _HTF:
    def __init__(
        self,
        *,
        latest_requests: tuple[RecoveryRequest, ...] = (),
        live_requests: tuple[RecoveryRequest, ...] = (),
    ) -> None:
        self.latest_requests = latest_requests
        self.live_requests = live_requests
        self.latest_calls: list[dict[str, object]] = []
        self.live_calls: list[dict[str, object]] = []

    async def reconcile_latest_closed_buckets(self, **kwargs: object):
        self.latest_calls.append(kwargs)
        return self.latest_requests

    async def process_base_candle(self, candle: CanonicalCandle, **kwargs: object):
        self.live_calls.append({"candle": candle, **kwargs})
        return self.live_requests


class _Recovery:
    def __init__(
        self,
        *,
        follow_ups: dict[
            tuple[str, str, str, datetime, datetime, str], tuple[RecoveryRequest, ...]
        ]
        | None = None,
        gate: asyncio.Event | None = None,
        on_call: Callable[[RecoveryRequest], None] | None = None,
    ) -> None:
        self.follow_ups = follow_ups or {}
        self.gate = gate
        self.on_call = on_call
        self.calls: list[RecoveryRequest] = []
        self.active = 0
        self.max_active = 0

    async def recover(self, request: RecoveryRequest, **kwargs: object):
        del kwargs
        self.calls.append(request)
        if self.on_call is not None:
            self.on_call(request)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.gate is not None:
                if self.active >= 2:
                    self.gate.set()
                await self.gate.wait()
            return self.follow_ups.get(
                (
                    request.lane.venue,
                    request.lane.instrument_id,
                    request.lane.timeframe,
                    request.since,
                    request.until,
                    request.reason,
                ),
                (),
            )
        finally:
            self.active -= 1


class _Stream:
    def __init__(
        self,
        *,
        observations: tuple[CandleObservation, ...] = (),
        interruption: LiveStreamInterrupted | None = None,
        block_after: bool = True,
        close_started: asyncio.Event | None = None,
        close_gate: asyncio.Event | None = None,
    ) -> None:
        self.observations = list(observations)
        self.interruption = interruption
        self.block_after = block_after
        self.closed = False
        self.release = asyncio.Event()
        self.close_started = close_started
        self.close_gate = close_gate
        self.close_finished = asyncio.Event()

    def __aiter__(self) -> _Stream:
        return self

    async def __anext__(self) -> CandleObservation:
        if self.observations:
            return self.observations.pop(0)
        if self.interruption is not None:
            interruption = self.interruption
            self.interruption = None
            raise interruption
        if self.block_after:
            await self.release.wait()
        raise StopAsyncIteration

    async def aclose(self) -> None:
        if self.close_started is not None:
            self.close_started.set()
        if self.close_gate is not None:
            await self.close_gate.wait()
        self.closed = True
        self.release.set()
        self.close_finished.set()


class _LiveProvider:
    provider_id = "binance_native"

    def __init__(self, streams: list[_Stream]) -> None:
        self.streams = streams
        self.calls: list[dict[MarketLane, str]] = []
        self.stream_kwargs: list[dict[str, object]] = []

    def stream_closed_candles(self, subscriptions, **kwargs: object) -> _Stream:
        self.calls.append(dict(subscriptions))
        self.stream_kwargs.append(dict(kwargs))
        return self.streams.pop(0)


def _supervisor(
    *,
    settings=None,
    repository: _Repository | None = None,
    ingestion: _Ingestion | None = None,
    htf: _HTF | None = None,
    recovery: _Recovery | None = None,
    provider: _LiveProvider | None = None,
    now_fn: Callable[[], datetime] | None = None,
    reconnect_sleep_fn=None,
) -> tuple[RuntimeSupervisor, _Repository, _Ingestion, _HTF, _Recovery, _LiveProvider]:
    repository = repository or _Repository({LANE: _canonical()})
    ingestion = ingestion or _Ingestion()
    htf = htf or _HTF()
    recovery = recovery or _Recovery()
    provider = provider or _LiveProvider([_Stream()])
    supervisor = RuntimeSupervisor(
        settings=settings or _settings(),
        live_provider=provider,
        repository=repository,  # type: ignore[arg-type]
        ingestion_service=ingestion,  # type: ignore[arg-type]
        htf_service=htf,  # type: ignore[arg-type]
        recovery_engine=recovery,  # type: ignore[arg-type]
        now_fn=now_fn or (lambda: NOW),
        reconnect_sleep_fn=reconnect_sleep_fn,
    )
    return supervisor, repository, ingestion, htf, recovery, provider


@pytest.mark.asyncio
async def test_initial_snapshot_and_lane_resolution_are_bounded() -> None:
    supervisor, _, _, _, _, provider = _supervisor(
        settings=_settings(target_timeframes=("1h",))
    )

    snapshot = supervisor.snapshot()

    assert snapshot.desired_state is DesiredRuntimeState.RUNNING
    assert snapshot.state is RuntimeState.STOPPED
    assert snapshot.last_error is None
    await supervisor._prepare_live_connection()
    assert provider.calls == []


@pytest.mark.asyncio
async def test_cold_start_uses_largest_target_as_bounded_floor() -> None:
    repository = _Repository()
    supervisor, _, _, htf, recovery, _ = _supervisor(
        settings=_settings(target_timeframes=("1h",)),
        repository=repository,
    )

    await supervisor._prepare_live_connection()

    assert recovery.calls == [
        RecoveryRequest(
            lane=LANE,
            since=BOUNDARY - timedelta(hours=1),
            until=BOUNDARY,
            reason="runtime_catchup",
        )
    ]
    assert len(htf.latest_calls) == 1


@pytest.mark.asyncio
async def test_warm_start_recovers_from_latest_durable_close() -> None:
    latest = _canonical(close_time=BOUNDARY - timedelta(minutes=3))
    repository = _Repository({LANE: latest})
    supervisor, _, _, _, recovery, _ = _supervisor(
        settings=_settings(target_timeframes=("1h",)),
        repository=repository,
    )

    await supervisor._prepare_live_connection()

    assert recovery.calls == [
        RecoveryRequest(
            lane=LANE,
            since=latest.close_time,
            until=BOUNDARY,
            reason="runtime_catchup",
        )
    ]


@pytest.mark.asyncio
async def test_pre_connect_maintenance_stabilizes_anchor_before_opening_stream() -> (
    None
):
    clock = {"now": NOW}
    repository = _Repository()
    provider = _LiveProvider([_Stream()])

    def complete_initial_recovery(request: RecoveryRequest) -> None:
        assert not provider.calls
        if request.until == BOUNDARY:
            repository.latest[LANE] = _canonical(close_time=BOUNDARY)
            clock["now"] = BOUNDARY + timedelta(minutes=2, seconds=30)

    recovery = _Recovery(on_call=complete_initial_recovery)
    supervisor, _, _, htf, _, _ = _supervisor(
        settings=_settings(target_timeframes=("1h",)),
        repository=repository,
        recovery=recovery,
        provider=provider,
        now_fn=lambda: clock["now"],
    )

    task = asyncio.create_task(supervisor.run())
    while not provider.calls:
        await asyncio.sleep(0)
    supervisor.stop()
    await asyncio.wait_for(task, timeout=1)

    assert recovery.calls == [
        RecoveryRequest(
            lane=LANE,
            since=BOUNDARY - timedelta(hours=1),
            until=BOUNDARY,
            reason="runtime_catchup",
        ),
        RecoveryRequest(
            lane=LANE,
            since=BOUNDARY,
            until=BOUNDARY + timedelta(minutes=2),
            reason="runtime_catchup",
        ),
    ]
    assert len(htf.latest_calls) == 2
    assert provider.stream_kwargs[0]["connection_anchor"] == (
        BOUNDARY + timedelta(minutes=2)
    )


@pytest.mark.asyncio
async def test_recovery_closure_deduplicates_followups_and_runs_lanes_concurrently() -> (
    None
):
    settings = _settings(include_eth=True)
    gate = asyncio.Event()
    recovery = _Recovery(gate=gate)
    supervisor, _, _, _, _, _ = _supervisor(
        settings=settings,
        repository=_Repository({LANE: _canonical(), ETH_LANE: _canonical(ETH_LANE)}),
        recovery=recovery,
    )
    request_a = RecoveryRequest(
        lane=LANE,
        since=BOUNDARY - timedelta(minutes=2),
        until=BOUNDARY,
        reason="a",
    )
    request_b = RecoveryRequest(
        lane=ETH_LANE,
        since=BOUNDARY - timedelta(minutes=2),
        until=BOUNDARY,
        reason="b",
    )

    task = asyncio.create_task(
        supervisor._execute_recovery_closure((request_a, request_b, request_a))
    )
    await asyncio.wait_for(gate.wait(), timeout=1)
    gate.set()
    await task

    assert recovery.max_active == 2
    assert recovery.calls.count(request_a) == 1
    assert recovery.calls.count(request_b) == 1


@pytest.mark.asyncio
async def test_recovery_closure_executes_followups_iteratively_once() -> None:
    request_a = RecoveryRequest(
        lane=LANE,
        since=BOUNDARY - timedelta(minutes=2),
        until=BOUNDARY - timedelta(minutes=1),
        reason="initial",
    )
    request_b = RecoveryRequest(
        lane=LANE,
        since=BOUNDARY - timedelta(minutes=1),
        until=BOUNDARY,
        reason="follow_up",
    )

    def key(request: RecoveryRequest):
        return (
            request.lane.venue,
            request.lane.instrument_id,
            request.lane.timeframe,
            request.since,
            request.until,
            request.reason,
        )

    recovery = _Recovery(
        follow_ups={key(request_a): (request_b,), key(request_b): (request_b,)}
    )
    supervisor, _, _, _, _, _ = _supervisor(recovery=recovery)

    await supervisor._execute_recovery_closure((request_a,))

    assert recovery.calls == [request_a, request_b]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [CandleCommitStatus.INSERTED, CandleCommitStatus.DUPLICATE],
)
async def test_live_inserted_and_duplicate_both_process_htf(
    status: CandleCommitStatus,
) -> None:
    stream = _Stream(observations=(_observation(),))
    provider = _LiveProvider([stream])
    ingestion = _Ingestion(status)
    supervisor, _, _, htf, _, _ = _supervisor(
        provider=provider,
        ingestion=ingestion,
    )

    task = asyncio.create_task(supervisor.run())
    while not ingestion.observations:
        await asyncio.sleep(0)
    supervisor.stop()
    await asyncio.wait_for(task, timeout=1)

    assert htf.live_calls[0]["candle"].source_type == "provider"
    assert supervisor.snapshot().state is RuntimeState.STOPPED


@pytest.mark.asyncio
async def test_live_conflict_is_fatal() -> None:
    stream = _Stream(observations=(_observation(),))
    supervisor, _, _, _, _, _ = _supervisor(
        provider=_LiveProvider([stream]),
        ingestion=_Ingestion(CandleCommitStatus.CONFLICT),
    )

    with pytest.raises(DataIngestionError, match="live canonical conflict"):
        await supervisor.run()

    assert supervisor.snapshot().state is RuntimeState.ERROR
    assert supervisor.snapshot().last_error is not None


@pytest.mark.asyncio
async def test_stream_interruption_recovers_then_catches_up_before_second_stream() -> (
    None
):
    interruption_request = RecoveryRequest(
        lane=LANE,
        since=BOUNDARY - timedelta(minutes=1),
        until=BOUNDARY,
        reason="websocket_disconnected",
    )
    first = _Stream(
        interruption=LiveStreamInterrupted(
            reason="websocket_disconnected",
            recovery_requests=(interruption_request,),
        )
    )
    second = _Stream()
    provider = _LiveProvider([first, second])
    latest = _canonical()
    repository = _Repository({LANE: latest})
    recovery = _Recovery()
    times = iter((NOW, NOW, NOW + timedelta(minutes=2), NOW + timedelta(minutes=2)))
    sleeps: list[float] = []

    async def reconnect_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    supervisor, _, _, _, _, _ = _supervisor(
        settings=_settings(target_timeframes=("1h",)),
        provider=provider,
        repository=repository,
        recovery=recovery,
        now_fn=lambda: next(times),
        reconnect_sleep_fn=reconnect_sleep,
    )

    task = asyncio.create_task(supervisor.run())
    while len(provider.calls) < 2:
        await asyncio.sleep(0)
    supervisor.stop()
    await asyncio.wait_for(task, timeout=1)

    assert sleeps == [0]
    assert recovery.calls[0] == interruption_request
    assert recovery.calls[1] == RecoveryRequest(
        lane=LANE,
        since=BOUNDARY,
        until=BOUNDARY + timedelta(minutes=2),
        reason="runtime_catchup",
    )
    assert first.closed
    assert second.closed


@pytest.mark.asyncio
async def test_stop_interrupts_reconnect_backoff_without_opening_next_stream() -> None:
    interruption_request = RecoveryRequest(
        lane=LANE,
        since=BOUNDARY - timedelta(minutes=1),
        until=BOUNDARY,
        reason="websocket_error",
    )
    first = _Stream(
        interruption=LiveStreamInterrupted(
            reason="websocket_error",
            recovery_requests=(interruption_request,),
        )
    )
    second = _Stream()
    provider = _LiveProvider([first, second])
    sleep_started = asyncio.Event()

    async def reconnect_sleep(seconds: float) -> None:
        del seconds
        sleep_started.set()
        await asyncio.Event().wait()

    supervisor, _, _, _, _, _ = _supervisor(
        provider=provider,
        reconnect_sleep_fn=reconnect_sleep,
    )
    task = asyncio.create_task(supervisor.run())
    await asyncio.wait_for(sleep_started.wait(), timeout=1)

    supervisor.stop()
    await asyncio.wait_for(task, timeout=1)

    assert len(provider.calls) == 1
    assert first.closed
    assert supervisor.snapshot().state is RuntimeState.STOPPED


@pytest.mark.asyncio
async def test_live_htf_followup_recovers_without_restarting_stream() -> None:
    follow_up = RecoveryRequest(
        lane=LANE,
        since=BOUNDARY - timedelta(minutes=1),
        until=BOUNDARY,
        reason="htf_incomplete:1h",
    )
    stream = _Stream(observations=(_observation(),))
    provider = _LiveProvider([stream])
    htf = _HTF(live_requests=(follow_up,))
    recovery = _Recovery()
    supervisor, _, _, _, _, _ = _supervisor(
        provider=provider,
        htf=htf,
        recovery=recovery,
    )

    task = asyncio.create_task(supervisor.run())
    while not recovery.calls:
        await asyncio.sleep(0)
    supervisor.stop()
    await asyncio.wait_for(task, timeout=1)

    assert recovery.calls == [follow_up]
    assert len(provider.calls) == 1
    assert supervisor.snapshot().state is RuntimeState.STOPPED


@pytest.mark.asyncio
async def test_pause_cancels_stream_without_recovery_and_resume_restarts() -> None:
    first = _Stream()
    second = _Stream()
    provider = _LiveProvider([first, second])
    recovery = _Recovery()
    supervisor, _, _, _, _, _ = _supervisor(
        provider=provider,
        recovery=recovery,
    )

    task = asyncio.create_task(supervisor.run())
    while len(provider.calls) < 1:
        await asyncio.sleep(0)
    supervisor.pause()
    await asyncio.sleep(0)
    assert supervisor.snapshot().desired_state is DesiredRuntimeState.PAUSED
    assert supervisor.snapshot().state is RuntimeState.STOPPED
    assert first.closed
    assert not task.done()
    assert recovery.calls == []

    supervisor.resume()
    while len(provider.calls) < 2:
        await asyncio.sleep(0)
    supervisor.stop()
    await asyncio.wait_for(task, timeout=1)

    assert second.closed
    assert supervisor.snapshot().desired_state is DesiredRuntimeState.RUNNING
    assert supervisor.snapshot().state is RuntimeState.STOPPED


@pytest.mark.asyncio
async def test_pause_does_not_publish_stopped_before_stream_cleanup_finishes() -> None:
    close_started = asyncio.Event()
    close_gate = asyncio.Event()
    stream = _Stream(
        observations=(_observation(),),
        close_started=close_started,
        close_gate=close_gate,
    )
    provider = _LiveProvider([stream])
    ingestion = _Ingestion()
    supervisor, _, _, _, _, _ = _supervisor(
        provider=provider,
        ingestion=ingestion,
    )

    task = asyncio.create_task(supervisor.run())
    while supervisor.snapshot().state is not RuntimeState.LIVE:
        await asyncio.sleep(0)

    supervisor.pause()
    await asyncio.wait_for(close_started.wait(), timeout=1)
    assert supervisor.snapshot().desired_state is DesiredRuntimeState.PAUSED
    assert supervisor.snapshot().state is RuntimeState.LIVE
    assert not stream.closed

    close_gate.set()
    await asyncio.wait_for(stream.close_finished.wait(), timeout=1)

    async def wait_for_stopped() -> None:
        while supervisor.snapshot().state is not RuntimeState.STOPPED:
            await asyncio.sleep(0)

    await asyncio.wait_for(wait_for_stopped(), timeout=1)
    assert not task.done()
    supervisor.stop()
    await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_stop_does_not_publish_stopped_before_stream_cleanup_finishes() -> None:
    close_started = asyncio.Event()
    close_gate = asyncio.Event()
    stream = _Stream(
        observations=(_observation(),),
        close_started=close_started,
        close_gate=close_gate,
    )
    provider = _LiveProvider([stream])
    ingestion = _Ingestion()
    supervisor, _, _, _, _, _ = _supervisor(
        provider=provider,
        ingestion=ingestion,
    )

    task = asyncio.create_task(supervisor.run())
    while supervisor.snapshot().state is not RuntimeState.LIVE:
        await asyncio.sleep(0)

    supervisor.stop()
    await asyncio.wait_for(close_started.wait(), timeout=1)
    assert supervisor.snapshot().state is RuntimeState.LIVE
    assert not stream.closed

    close_gate.set()
    await asyncio.wait_for(task, timeout=1)
    assert stream.closed
    assert supervisor.snapshot().state is RuntimeState.STOPPED


@pytest.mark.asyncio
async def test_external_cancellation_closes_stream_and_propagates() -> None:
    stream = _Stream()
    provider = _LiveProvider([stream])
    supervisor, _, _, _, _, _ = _supervisor(provider=provider)
    task = asyncio.create_task(supervisor.run())
    while not provider.calls:
        await asyncio.sleep(0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert stream.closed
    assert supervisor.snapshot().state is RuntimeState.STOPPED


@pytest.mark.asyncio
async def test_invalid_latest_progress_is_rejected() -> None:
    settings = _settings()
    bad_latest = CanonicalCandle(
        lane=LANE,
        open_time=BOUNDARY - timedelta(minutes=2),
        close_time=BOUNDARY - timedelta(minutes=1),
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal("100.5"),
        volume=Decimal(1),
        taker_buy_base=Decimal("0.5"),
        source_type="derived",
        source_provider=None,
        source_timeframe="1m",
    )

    supervisor, _, _, _, _, _ = _supervisor(
        settings=settings,
        repository=_Repository({LANE: bad_latest}),
    )

    with pytest.raises(DataIngestionError, match="provider sourced"):
        await supervisor._prepare_live_connection()


def test_alignment_helper_is_the_same_boundary_used_by_runtime() -> None:
    assert aligned_bucket_start(NOW, timedelta(minutes=1), ORIGIN) == BOUNDARY


@pytest.mark.asyncio
async def test_public_execute_recovery_runs_only_when_supervisor_is_offline() -> None:
    request = RecoveryRequest(
        lane=LANE,
        since=BOUNDARY - timedelta(minutes=1),
        until=BOUNDARY,
        reason="manual_api",
    )
    supervisor, _, _, _, recovery, _ = _supervisor()

    await supervisor.execute_recovery(request)

    assert recovery.calls == [request]
    assert supervisor.snapshot().state is RuntimeState.STOPPED


@pytest.mark.asyncio
async def test_public_execute_recovery_rejects_active_supervisor() -> None:
    provider = _LiveProvider([_Stream()])
    supervisor, _, _, _, _, _ = _supervisor(provider=provider)
    task = asyncio.create_task(supervisor.run())
    while not provider.calls:
        await asyncio.sleep(0)

    request = RecoveryRequest(
        lane=LANE,
        since=BOUNDARY - timedelta(minutes=1),
        until=BOUNDARY,
        reason="manual_api",
    )
    with pytest.raises(RuntimeError, match="while the supervisor is running"):
        await supervisor.execute_recovery(request)

    supervisor.stop()
    await asyncio.wait_for(task, timeout=1)
