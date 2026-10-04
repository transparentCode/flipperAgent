from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import asyncpg
import pytest

from apps.ingestion_app.domain.candle import CandleObservation, CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.domain.time_alignment import aligned_bucket_start
from apps.ingestion_app.observability import IngestionObservability
from apps.ingestion_app.planning import compile_ingestion_plan
from apps.ingestion_app.providers.base import (
    LiveStreamInterrupted,
    TransportDeadlineExceeded,
)
from apps.ingestion_app.runtime.state import RuntimeState, SupervisorSnapshot
from apps.ingestion_app.runtime.supervisor import RuntimeSupervisor
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.services.recovery import (
    RecoveryExhaustedError,
    RecoveryRateLimitedError,
)
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
    reconnect_backoff_seconds: float = 0,
    startup_history_days: int | None = None,
    candle_days: int = 90,
) -> object:
    timeframe_values = {"1m": {"duration_seconds": 60}}
    for timeframe in target_timeframes:
        timeframe_values[timeframe] = {
            "duration_seconds": {
                "15m": 900,
                "1h": 3600,
                "2h": 7200,
                "1w": 604800,
            }[timeframe]
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
                "startup_history_days": startup_history_days,
            },
            "websocket": {
                "stream_url": "wss://fstream.binance.com/market",
                "queue_maxsize": 10,
            },
            "runtime": {"reconnect_backoff_seconds": reconnect_backoff_seconds},
            "server": {"host": "127.0.0.1", "port": 8003},
            "publication": {
                "batch_size": 500,
                "idle_sleep_seconds": 1,
                "error_backoff_seconds": 1,
                "stream_maxlen": 1000,
                "stream_approximate": True,
            },
            "retention": {
                "candle_days": candle_days,
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
        missing_requests: tuple[RecoveryRequest, ...] = (),
        live_requests: tuple[RecoveryRequest, ...] = (),
    ) -> None:
        self.latest_requests = latest_requests
        self.missing_requests = missing_requests
        self.live_requests = live_requests
        self.latest_calls: list[dict[str, object]] = []
        self.missing_calls: list[dict[str, object]] = []
        self.live_calls: list[dict[str, object]] = []

    async def reconcile_latest_closed_buckets(self, **kwargs: object):
        self.latest_calls.append(kwargs)
        return self.latest_requests

    async def reconcile_missing_closed_buckets(self, **kwargs: object):
        self.missing_calls.append(kwargs)
        return self.missing_requests

    async def process_base_candle(self, candle: CanonicalCandle, **kwargs: object):
        self.live_calls.append({"candle": candle, **kwargs})
        return self.live_requests


class _MemoryRepository:
    def __init__(self, candles: tuple[CanonicalCandle, ...] = ()) -> None:
        self.candles = list(candles)
        self.range_calls: list[tuple[MarketLane, datetime, datetime]] = []

    async def fetch_latest_candle(
        self,
        *,
        lane: MarketLane,
        before: datetime,
    ) -> CanonicalCandle | None:
        matches = [
            candle
            for candle in self.candles
            if candle.lane == lane and candle.close_time <= before
        ]
        return max(matches, key=lambda candle: candle.open_time, default=None)

    async def fetch_candles(
        self,
        *,
        lane: MarketLane,
        since: datetime,
        until: datetime,
    ) -> tuple[CanonicalCandle, ...]:
        self.range_calls.append((lane, since, until))
        return tuple(
            sorted(
                (
                    candle
                    for candle in self.candles
                    if candle.lane == lane and since <= candle.open_time < until
                ),
                key=lambda candle: candle.open_time,
            )
        )

    def insert(self, candle: CanonicalCandle) -> CandleCommitStatus:
        if any(
            existing.lane == candle.lane and existing.open_time == candle.open_time
            for existing in self.candles
        ):
            return CandleCommitStatus.DUPLICATE
        self.candles.append(candle)
        return CandleCommitStatus.INSERTED


def _derived_candle(
    lane: MarketLane,
    open_time: datetime,
    duration: timedelta,
) -> CanonicalCandle:
    return CanonicalCandle(
        lane=MarketLane(lane.venue, lane.instrument_id, "15m"),
        open_time=open_time,
        close_time=open_time + duration,
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal(100),
        volume=Decimal(15),
        taker_buy_base=Decimal(10),
        source_type="derived",
        source_provider=None,
        source_timeframe="1m",
    )


class _PersistingIngestion:
    def __init__(self, repository: _MemoryRepository) -> None:
        self.repository = repository
        self.commit_attempts: list[CanonicalCandle] = []

    async def commit_candle(self, candle: CanonicalCandle) -> CandleCommitStatus:
        self.commit_attempts.append(candle)
        return self.repository.insert(candle)

    async def commit_observation(self, observation: CandleObservation):
        del observation
        raise AssertionError("these startup tests do not consume live observations")


class _PartialPageRecovery:
    def __init__(
        self,
        repository: _MemoryRepository,
        htf_service: HTFAggregationService,
    ) -> None:
        self.repository = repository
        self.htf_service = htf_service
        self.calls: list[tuple[RecoveryRequest, ...]] = []
        self.first_page_failed = False

    async def recover_closure(self, requests, *, plan) -> None:
        batch = tuple(requests)
        self.calls.append(batch)
        for request in batch:
            if request.reason != "runtime_catchup":
                continue
            stop_at = request.until
            if not self.first_page_failed:
                stop_at = min(request.until, request.since + timedelta(minutes=30))
                self.first_page_failed = True
            cursor = request.since
            while cursor < stop_at:
                self.repository.insert(
                    _canonical(close_time=cursor + timedelta(minutes=1))
                )
                cursor += timedelta(minutes=1)
            if stop_at < request.until:
                raise RecoveryExhaustedError("synthetic second-page exhaustion")

            context = plan.lanes_by_lane[request.lane]
            await self.htf_service.reconcile_affected_buckets(
                base_lane=request.lane,
                base_duration=context.base_duration,
                target_durations=context.target_durations,
                alignment_origin=plan.alignment_origin,
                since=request.since,
                until=request.until,
                as_of=request.until,
            )


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

    async def recover_closure(self, requests, *, plan):
        del plan
        pending = list(requests)
        seen = set()
        while pending:
            batch = []
            for request in sorted(
                pending,
                key=lambda item: (
                    item.lane.venue,
                    item.lane.instrument_id,
                    item.lane.timeframe,
                    item.since,
                    item.until,
                    item.reason,
                ),
            ):
                key = (
                    request.lane.venue,
                    request.lane.instrument_id,
                    request.lane.timeframe,
                    request.since,
                    request.until,
                    request.reason,
                )
                if key not in seen:
                    seen.add(key)
                    batch.append(request)
            if not batch:
                return
            results = await asyncio.gather(
                *(self.recover(request) for request in batch)
            )
            pending = [follow_up for result in results for follow_up in result]


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


class _QuarantinedLiveProvider(_LiveProvider):
    lifecycle_quarantined = True
    lifecycle_quarantine_error = DataIngestionError(
        "Binance websocket lifecycle cleanup failed; lifecycle quarantined"
    )


def _supervisor(
    *,
    settings=None,
    repository: _Repository | None = None,
    ingestion: _Ingestion | None = None,
    htf: _HTF | None = None,
    recovery: _Recovery | None = None,
    provider: _LiveProvider | None = None,
    now_fn: Callable[[], datetime] | None = None,
    monotonic_fn: Callable[[], float] | None = None,
    reconnect_sleep_fn=None,
    observability: IngestionObservability | None = None,
) -> tuple[RuntimeSupervisor, _Repository, _Ingestion, _HTF, _Recovery, _LiveProvider]:
    repository = repository or _Repository({LANE: _canonical()})
    ingestion = ingestion or _Ingestion()
    htf = htf or _HTF()
    recovery = recovery or _Recovery()
    provider = provider or _LiveProvider([_Stream()])
    plan = compile_ingestion_plan(
        settings or _settings(),
        live_provider_ids={provider.provider_id},
        historical_provider_ids={"binance_native", "ccxt_binance"},
    )
    supervisor = RuntimeSupervisor(
        plan=plan,
        live_provider=provider,
        repository=repository,  # type: ignore[arg-type]
        ingestion_service=ingestion,  # type: ignore[arg-type]
        htf_service=htf,  # type: ignore[arg-type]
        recovery_engine=recovery,  # type: ignore[arg-type]
        now_fn=now_fn or (lambda: NOW),
        monotonic_fn=monotonic_fn,
        reconnect_sleep_fn=reconnect_sleep_fn,
        observability=observability,
    )
    return supervisor, repository, ingestion, htf, recovery, provider


async def _wait_until_live(supervisor: RuntimeSupervisor) -> None:
    async def wait() -> None:
        while supervisor.snapshot().state is not RuntimeState.LIVE:
            await asyncio.sleep(0.001)

    await asyncio.wait_for(wait(), timeout=1)


@pytest.mark.asyncio
async def test_initial_snapshot_and_lane_resolution_are_bounded() -> None:
    supervisor, _, _, _, _, provider = _supervisor(
        settings=_settings(target_timeframes=("1h",))
    )

    snapshot = supervisor.snapshot()

    assert snapshot.state is RuntimeState.STOPPED
    assert snapshot.last_error is None
    await supervisor._prepare_live_connection()
    assert provider.calls == []


def test_supervisor_not_live_duration_uses_monotonic_generation_clock() -> None:
    clock = [10.0]
    supervisor, *_ = _supervisor(monotonic_fn=lambda: clock[0])

    assert supervisor.snapshot().not_live_seconds == 0

    clock[0] = 15.0
    supervisor._set_state(RuntimeState.STARTING)
    assert supervisor.snapshot().not_live_seconds == 5.0

    clock[0] = 20.0
    supervisor._set_state(RuntimeState.RECOVERING)
    assert supervisor.snapshot().not_live_seconds == 10.0

    clock[0] = 25.0
    supervisor._set_state(RuntimeState.LIVE)
    assert supervisor.snapshot().not_live_seconds is None

    clock[0] = 30.0
    supervisor._set_state(RuntimeState.RECOVERING)
    assert supervisor.snapshot().not_live_seconds == 0.0
    clock[0] = 33.0
    assert supervisor.snapshot().not_live_seconds == 3.0


def test_supervisor_construction_does_not_reset_shared_runtime_live() -> None:
    observability = IngestionObservability()
    observability.set_runtime_live(True)

    supervisor, *_ = _supervisor(observability=observability)

    assert observability._runtime_live is True
    assert supervisor.snapshot().state is RuntimeState.STOPPED


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
    assert htf.missing_calls == [
        {
            "base_lane": LANE,
            "base_duration": timedelta(minutes=1),
            "target_durations": supervisor.plan.lanes[0].target_durations,
            "alignment_origin": ORIGIN,
            "since": BOUNDARY - timedelta(hours=1),
            "as_of": NOW,
        }
    ]


@pytest.mark.asyncio
async def test_configured_startup_history_extends_only_base_catchup_floor() -> None:
    repository = _Repository()
    supervisor, _, _, htf, recovery, _ = _supervisor(
        settings=_settings(
            target_timeframes=("1w",),
            startup_history_days=120,
            candle_days=400,
        ),
        repository=repository,
    )

    await supervisor._prepare_live_connection()

    assert recovery.calls == [
        RecoveryRequest(
            lane=LANE,
            since=BOUNDARY - timedelta(days=120),
            until=BOUNDARY,
            reason="runtime_catchup",
        )
    ]
    assert htf.missing_calls[0]["since"] == BOUNDARY - timedelta(weeks=1)


@pytest.mark.asyncio
async def test_startup_retry_repairs_every_closed_htf_bucket_after_partial_pages() -> (
    None
):
    settings = _settings(target_timeframes=("15m", "1h"))
    plan = compile_ingestion_plan(
        settings,
        live_provider_ids={"binance_native"},
        historical_provider_ids={"binance_native", "ccxt_binance"},
    )
    repository = _MemoryRepository()
    ingestion = _PersistingIngestion(repository)
    htf = HTFAggregationService(
        repository=repository,  # type: ignore[arg-type]
        ingestion_service=ingestion,  # type: ignore[arg-type]
    )
    recovery = _PartialPageRecovery(repository, htf)
    provider = _LiveProvider([_Stream()])
    supervisor = RuntimeSupervisor(
        plan=plan,
        live_provider=provider,
        repository=repository,  # type: ignore[arg-type]
        ingestion_service=ingestion,  # type: ignore[arg-type]
        htf_service=htf,
        recovery_engine=recovery,  # type: ignore[arg-type]
        now_fn=lambda: NOW,
        reconnect_sleep_fn=lambda _seconds: asyncio.sleep(0),
    )

    task = asyncio.create_task(supervisor.run())
    while not provider.calls:
        await asyncio.sleep(0)
    supervisor.stop()
    await asyncio.wait_for(task, timeout=1)

    expected_15m_starts = tuple(
        BOUNDARY - timedelta(hours=1) + index * timedelta(minutes=15)
        for index in range(4)
    )
    actual_15m_starts = tuple(
        sorted(
            candle.open_time
            for candle in repository.candles
            if candle.lane == MarketLane(LANE.venue, LANE.instrument_id, "15m")
        )
    )
    assert actual_15m_starts == expected_15m_starts
    assert any(
        candle.lane == MarketLane(LANE.venue, LANE.instrument_id, "1h")
        and candle.open_time == BOUNDARY - timedelta(hours=1)
        for candle in repository.candles
    )
    assert recovery.first_page_failed is True
    assert recovery.calls[0] == (
        RecoveryRequest(
            lane=LANE,
            since=BOUNDARY - timedelta(hours=1),
            until=BOUNDARY,
            reason="runtime_catchup",
        ),
    )
    assert recovery.calls[1] == (
        RecoveryRequest(
            lane=LANE,
            since=BOUNDARY - timedelta(minutes=30),
            until=BOUNDARY,
            reason="runtime_catchup",
        ),
    )


@pytest.mark.asyncio
async def test_startup_builds_older_missing_bucket_when_later_bucket_exists() -> None:
    settings = _settings(target_timeframes=("15m", "1h"))
    plan = compile_ingestion_plan(
        settings,
        live_provider_ids={"binance_native"},
        historical_provider_ids={"binance_native", "ccxt_binance"},
    )
    base_candles = tuple(
        _canonical(
            close_time=BOUNDARY
            - timedelta(hours=1)
            + (index + 1) * timedelta(minutes=1)
        )
        for index in range(60)
    )
    repository = _MemoryRepository(
        (
            *base_candles,
            _derived_candle(
                LANE,
                BOUNDARY - timedelta(hours=1),
                timedelta(minutes=15),
            ),
            _derived_candle(
                LANE,
                BOUNDARY - timedelta(minutes=30),
                timedelta(minutes=15),
            ),
            _derived_candle(
                LANE,
                BOUNDARY - timedelta(minutes=15),
                timedelta(minutes=15),
            ),
        )
    )
    ingestion = _PersistingIngestion(repository)
    htf = HTFAggregationService(
        repository=repository,  # type: ignore[arg-type]
        ingestion_service=ingestion,  # type: ignore[arg-type]
    )
    recovery = _Recovery()
    provider = _LiveProvider([_Stream()])
    supervisor = RuntimeSupervisor(
        plan=plan,
        live_provider=provider,
        repository=repository,  # type: ignore[arg-type]
        ingestion_service=ingestion,  # type: ignore[arg-type]
        htf_service=htf,
        recovery_engine=recovery,  # type: ignore[arg-type]
        now_fn=lambda: NOW,
    )

    await supervisor._prepare_live_connection()

    assert recovery.calls == []
    assert any(
        candle.lane == MarketLane(LANE.venue, LANE.instrument_id, "15m")
        and candle.open_time == BOUNDARY - timedelta(minutes=45)
        for candle in repository.candles
    )


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
async def test_plain_live_quarantine_is_error_without_fabricated_deadline() -> None:
    supervisor, _, _, _, _, _ = _supervisor(
        provider=_QuarantinedLiveProvider([_Stream()]),
    )

    snapshot = supervisor.snapshot()
    assert snapshot.state is RuntimeState.ERROR
    assert snapshot.last_error is not None
    assert "cleanup failed" in snapshot.last_error
    assert "exceeded" not in snapshot.last_error

    request = RecoveryRequest(
        lane=LANE,
        since=BOUNDARY - timedelta(minutes=1),
        until=BOUNDARY,
        reason="manual_api",
    )
    with pytest.raises(DataIngestionError, match="cleanup failed"):
        await supervisor.execute_recovery(request)
    supervisor.stop()
    assert supervisor.snapshot().state is RuntimeState.ERROR


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
async def test_interruption_provider_exhaustion_retries_catchup_then_stream() -> None:
    attempts = 0
    retry_started = asyncio.Event()
    release_retry = asyncio.Event()
    interruption_request = RecoveryRequest(
        lane=LANE,
        since=BOUNDARY - timedelta(minutes=1),
        until=BOUNDARY,
        reason="websocket_error",
    )

    def fail_once(request: RecoveryRequest) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RecoveryExhaustedError(
                f"temporary provider outage for {request.lane}"
            )

    async def reconnect_sleep(seconds: float) -> None:
        assert seconds == 3
        retry_started.set()
        await release_retry.wait()

    first = _Stream(
        interruption=LiveStreamInterrupted(
            reason="websocket_error",
            recovery_requests=(interruption_request,),
        )
    )
    second = _Stream()
    provider = _LiveProvider([first, second])
    times = iter((NOW, NOW, NOW + timedelta(minutes=1), NOW + timedelta(minutes=1)))
    supervisor, _, _, _, recovery, _ = _supervisor(
        settings=_settings(reconnect_backoff_seconds=3),
        repository=_Repository({LANE: _canonical()}),
        provider=provider,
        recovery=_Recovery(on_call=fail_once),
        now_fn=lambda: next(times),
        reconnect_sleep_fn=reconnect_sleep,
    )

    task = asyncio.create_task(supervisor.run())
    await asyncio.wait_for(retry_started.wait(), timeout=1)
    snapshot = supervisor.snapshot()
    assert snapshot.state is RuntimeState.RECOVERING
    assert snapshot.last_error is not None
    assert "temporary provider outage" in snapshot.last_error

    release_retry.set()
    while len(provider.calls) < 2:
        await asyncio.sleep(0)
    supervisor.stop()
    await asyncio.wait_for(task, timeout=1)

    assert attempts == 2
    assert recovery.calls == [
        interruption_request,
        RecoveryRequest(
            lane=LANE,
            since=BOUNDARY,
            until=BOUNDARY + timedelta(minutes=1),
            reason="runtime_catchup",
        ),
    ]
    assert len(provider.calls) == 2
    assert first.closed
    assert second.closed
    assert supervisor.snapshot().state is RuntimeState.STOPPED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("backoff", "retry_after", "expected_delay"),
    [(0, 7.5, 7.5), (10, 3, 10)],
)
async def test_rate_limit_waits_exchange_delay_then_retries_to_live(
    backoff: float,
    retry_after: float,
    expected_delay: float,
) -> None:
    attempts = 0
    retry_started = asyncio.Event()
    release_retry = asyncio.Event()
    sleeps: list[float] = []
    interruption_request = RecoveryRequest(
        lane=LANE,
        since=BOUNDARY - timedelta(minutes=1),
        until=BOUNDARY,
        reason="websocket_error",
    )

    def rate_limit_once(request: RecoveryRequest) -> None:
        nonlocal attempts
        del request
        attempts += 1
        if attempts == 1:
            raise RecoveryRateLimitedError(retry_after_seconds=retry_after)

    async def reconnect_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        retry_started.set()
        await release_retry.wait()

    provider = _LiveProvider(
        [
            _Stream(
                interruption=LiveStreamInterrupted(
                    reason="websocket_error",
                    recovery_requests=(interruption_request,),
                )
            ),
            _Stream(observations=(_observation(),)),
        ]
    )
    times = iter((NOW, NOW, NOW + timedelta(minutes=1), NOW + timedelta(minutes=1)))
    supervisor, _, _, _, recovery, _ = _supervisor(
        settings=_settings(reconnect_backoff_seconds=backoff),
        repository=_Repository({LANE: _canonical()}),
        provider=provider,
        recovery=_Recovery(on_call=rate_limit_once),
        now_fn=lambda: next(times),
        reconnect_sleep_fn=reconnect_sleep,
    )

    task = asyncio.create_task(supervisor.run())
    await asyncio.wait_for(retry_started.wait(), timeout=1)
    assert supervisor.snapshot().state is RuntimeState.RECOVERING
    assert supervisor.snapshot().last_error is not None
    assert sleeps == [expected_delay]

    release_retry.set()
    for _ in range(100):
        if supervisor.snapshot().state is RuntimeState.LIVE:
            break
        await asyncio.sleep(0)
    assert len(provider.calls) == 2
    assert supervisor.snapshot().state is RuntimeState.LIVE
    supervisor.stop()
    await asyncio.wait_for(task, timeout=1)
    assert attempts == 2
    assert len(recovery.calls) == 2
    assert supervisor.snapshot().state is RuntimeState.STOPPED


@pytest.mark.asyncio
async def test_stop_cancels_rate_limit_wait() -> None:
    retry_started = asyncio.Event()
    never_release = asyncio.Event()

    def rate_limit(request: RecoveryRequest) -> None:
        raise RecoveryRateLimitedError(retry_after_seconds=30)

    async def reconnect_sleep(seconds: float) -> None:
        assert seconds == 30
        retry_started.set()
        await never_release.wait()

    request = RecoveryRequest(
        lane=LANE,
        since=BOUNDARY - timedelta(minutes=1),
        until=BOUNDARY,
        reason="websocket_error",
    )
    provider = _LiveProvider(
        [
            _Stream(
                interruption=LiveStreamInterrupted(
                    reason="websocket_error",
                    recovery_requests=(request,),
                )
            )
        ]
    )
    supervisor, _, _, _, recovery, _ = _supervisor(
        provider=provider,
        recovery=_Recovery(on_call=rate_limit),
        reconnect_sleep_fn=reconnect_sleep,
    )

    task = asyncio.create_task(supervisor.run())
    await asyncio.wait_for(retry_started.wait(), timeout=1)
    assert supervisor.snapshot().state is RuntimeState.RECOVERING
    supervisor.stop()
    await asyncio.wait_for(task, timeout=1)
    assert len(recovery.calls) == 1
    assert len(provider.calls) == 1
    assert supervisor.snapshot().state is RuntimeState.STOPPED


@pytest.mark.asyncio
async def test_stop_interrupts_provider_exhaustion_retry_backoff() -> None:
    retry_started = asyncio.Event()
    never_release = asyncio.Event()

    def exhaust_provider(request: RecoveryRequest) -> None:
        raise RecoveryExhaustedError(f"temporary provider outage for {request.lane}")

    async def reconnect_sleep(seconds: float) -> None:
        assert seconds == 0
        retry_started.set()
        await never_release.wait()

    provider = _LiveProvider([_Stream()])
    supervisor, _, _, _, recovery, _ = _supervisor(
        repository=_Repository(),
        provider=provider,
        recovery=_Recovery(on_call=exhaust_provider),
        reconnect_sleep_fn=reconnect_sleep,
    )

    task = asyncio.create_task(supervisor.run())
    await asyncio.wait_for(retry_started.wait(), timeout=1)
    supervisor.stop()
    await asyncio.wait_for(task, timeout=1)

    assert len(recovery.calls) == 1
    assert provider.calls == []
    snapshot = supervisor.snapshot()
    assert snapshot.state is RuntimeState.STOPPED
    assert snapshot.last_error is not None


@pytest.mark.asyncio
async def test_non_exhaustion_recovery_error_remains_fatal() -> None:
    failure = DataIngestionError("canonical recovery invariant failed")

    def fail_recovery(request: RecoveryRequest) -> None:
        del request
        raise failure

    supervisor, _, _, _, _, _ = _supervisor(
        repository=_Repository(),
        recovery=_Recovery(on_call=fail_recovery),
    )

    with pytest.raises(DataIngestionError) as raised:
        await supervisor.run()

    assert raised.value is failure
    snapshot = supervisor.snapshot()
    assert snapshot.state is RuntimeState.ERROR
    assert snapshot.last_error == str(failure)


@pytest.mark.asyncio
async def test_storage_availability_error_during_startup_retries_to_live() -> None:
    failure = asyncpg.ConnectionDoesNotExistError("temporary database outage")

    class _FailOnceRepository(_Repository):
        def __init__(self) -> None:
            super().__init__({LANE: _canonical()})
            self.attempts = 0

        async def fetch_latest_candle(self, *, lane, before):
            self.attempts += 1
            if self.attempts == 1:
                raise failure
            return await super().fetch_latest_candle(lane=lane, before=before)

    repository = _FailOnceRepository()
    delays: list[float] = []

    async def reconnect_sleep(seconds: float) -> None:
        assert supervisor.snapshot().state is RuntimeState.RECOVERING
        delays.append(seconds)

    provider = _LiveProvider([_Stream(observations=(_observation(),))])
    supervisor, *_ = _supervisor(
        settings=_settings(reconnect_backoff_seconds=3),
        repository=repository,
        provider=provider,
        reconnect_sleep_fn=reconnect_sleep,
    )
    task = asyncio.create_task(supervisor.run())
    try:
        await _wait_until_live(supervisor)
        assert repository.attempts == 2
        assert delays == [3]
        assert len(provider.calls) == 1
        assert supervisor.snapshot().last_error is None
    finally:
        supervisor.stop()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_storage_availability_error_on_live_commit_closes_stream_then_retries() -> (
    None
):
    failure = ConnectionResetError("database connection reset")
    first_stream = _Stream(observations=(_observation(),))
    second_stream = _Stream(observations=(_observation(),))
    delays: list[float] = []

    class _FailFirstIngestion(_Ingestion):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        async def commit_observation(self, observation: CandleObservation):
            self.attempts += 1
            self.observations.append(observation)
            if self.attempts == 1:
                raise failure
            return self.status

    async def reconnect_sleep(seconds: float) -> None:
        assert supervisor.snapshot().state is RuntimeState.RECOVERING
        assert first_stream.closed
        delays.append(seconds)

    ingestion = _FailFirstIngestion()
    provider = _LiveProvider([first_stream, second_stream])
    supervisor, *_ = _supervisor(
        settings=_settings(reconnect_backoff_seconds=4),
        ingestion=ingestion,
        provider=provider,
        reconnect_sleep_fn=reconnect_sleep,
    )
    task = asyncio.create_task(supervisor.run())
    try:
        await _wait_until_live(supervisor)
        assert first_stream.closed
        assert ingestion.attempts == 2
        assert delays == [4]
        assert len(provider.calls) == 2
    finally:
        supervisor.stop()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_stop_during_storage_availability_backoff_ends_run_cleanly() -> None:
    failure = asyncpg.ConnectionDoesNotExistError("temporary database outage")

    class _FailOnceRepository(_Repository):
        def __init__(self) -> None:
            super().__init__({LANE: _canonical()})
            self.attempts = 0

        async def fetch_latest_candle(self, *, lane, before):
            self.attempts += 1
            if self.attempts == 1:
                raise failure
            return await super().fetch_latest_candle(lane=lane, before=before)

    sleep_started = asyncio.Event()

    async def reconnect_sleep(seconds: float) -> None:
        assert seconds == 5
        sleep_started.set()
        await asyncio.Event().wait()

    repository = _FailOnceRepository()
    provider = _LiveProvider([_Stream(observations=(_observation(),))])
    supervisor, *_ = _supervisor(
        settings=_settings(reconnect_backoff_seconds=5),
        repository=repository,
        provider=provider,
        reconnect_sleep_fn=reconnect_sleep,
    )
    task = asyncio.create_task(supervisor.run())

    await asyncio.wait_for(sleep_started.wait(), timeout=1)
    assert supervisor.snapshot().state is RuntimeState.RECOVERING
    assert supervisor.snapshot().last_error == str(failure)
    supervisor.stop()
    await asyncio.wait_for(task, timeout=1)

    assert repository.attempts == 1
    assert provider.calls == []
    assert supervisor.snapshot().state is RuntimeState.STOPPED


@pytest.mark.asyncio
async def test_non_availability_database_error_remains_terminal() -> None:
    failure = asyncpg.UniqueViolationError("synthetic constraint violation")
    delays: list[float] = []

    class _FailingRepository(_Repository):
        async def fetch_latest_candle(self, *, lane, before):
            raise failure

    async def reconnect_sleep(seconds: float) -> None:
        delays.append(seconds)

    supervisor, *_ = _supervisor(
        repository=_FailingRepository({LANE: _canonical()}),
        reconnect_sleep_fn=reconnect_sleep,
    )

    with pytest.raises(asyncpg.UniqueViolationError) as raised:
        await supervisor.run()

    assert raised.value is failure
    assert delays == []
    assert supervisor.snapshot().state is RuntimeState.ERROR
    assert supervisor.snapshot().last_error == str(failure)


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
async def test_stop_during_interruption_recovery_is_controlled_cancellation() -> None:
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
    provider = _LiveProvider([first])
    recovery_started = asyncio.Event()
    recovery_gate = asyncio.Event()

    def mark_recovery_started(request: RecoveryRequest) -> None:
        del request
        recovery_started.set()

    recovery = _Recovery(
        gate=recovery_gate,
        on_call=mark_recovery_started,
    )
    supervisor, _, _, _, _, _ = _supervisor(
        provider=provider,
        recovery=recovery,
    )

    task = asyncio.create_task(supervisor.run())
    await asyncio.wait_for(recovery_started.wait(), timeout=1)

    supervisor.stop()
    await asyncio.wait_for(task, timeout=1)

    assert first.closed
    assert supervisor.snapshot().state is RuntimeState.STOPPED
    assert supervisor.snapshot().last_error is None


@pytest.mark.asyncio
async def test_external_cancellation_during_interruption_recovery_propagates() -> None:
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
    provider = _LiveProvider([first])
    recovery_started = asyncio.Event()
    recovery_gate = asyncio.Event()

    def mark_recovery_started(request: RecoveryRequest) -> None:
        del request
        recovery_started.set()

    recovery = _Recovery(
        gate=recovery_gate,
        on_call=mark_recovery_started,
    )
    supervisor, _, _, _, _, _ = _supervisor(
        provider=provider,
        recovery=recovery,
    )

    task = asyncio.create_task(supervisor.run())
    await asyncio.wait_for(recovery_started.wait(), timeout=1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert first.closed
    assert supervisor.snapshot().state is RuntimeState.STOPPED
    assert supervisor.snapshot().last_error is None


@pytest.mark.asyncio
async def test_interruption_recovery_deadline_is_latched_and_propagates() -> None:
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
    deadline = TransportDeadlineExceeded(
        provider_id="binance_native",
        operation="REST klines",
        timeout_seconds=30,
    )

    def fail_recovery(request: RecoveryRequest) -> None:
        del request
        raise deadline

    supervisor, _, _, _, _, _ = _supervisor(
        provider=_LiveProvider([first]),
        recovery=_Recovery(on_call=fail_recovery),
    )

    with pytest.raises(TransportDeadlineExceeded) as raised:
        await supervisor.run()

    assert raised.value is deadline
    assert first.closed
    snapshot = supervisor.snapshot()
    assert snapshot.state is RuntimeState.ERROR
    assert snapshot.last_error == str(deadline)
    assert supervisor.quarantined is True


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
async def test_stop_cancels_stream_without_recovery_and_generation_does_not_restart() -> (
    None
):
    first = _Stream()
    provider = _LiveProvider([first])
    recovery = _Recovery()
    supervisor, _, _, _, _, _ = _supervisor(
        provider=provider,
        recovery=recovery,
    )

    task = asyncio.create_task(supervisor.run())
    while len(provider.calls) < 1:
        await asyncio.sleep(0)
    supervisor.stop()
    await asyncio.wait_for(task, timeout=1)
    assert first.closed
    assert recovery.calls == []
    assert len(provider.calls) == 1
    assert supervisor.snapshot().state is RuntimeState.STOPPED
    assert not hasattr(supervisor, "pause")
    assert not hasattr(supervisor, "resume")


@pytest.mark.asyncio
async def test_supervisor_snapshot_is_observed_only() -> None:
    supervisor, _, _, _, _, _ = _supervisor()

    snapshot = supervisor.snapshot()

    assert isinstance(snapshot, SupervisorSnapshot)
    assert snapshot.state is RuntimeState.STOPPED
    assert not hasattr(snapshot, "desired_state")
    assert not hasattr(supervisor, "pause")
    assert not hasattr(supervisor, "resume")


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
