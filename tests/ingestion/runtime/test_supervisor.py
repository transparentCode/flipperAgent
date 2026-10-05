from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace
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
from apps.ingestion_app.services.candle_ingestion import canonicalize_observation
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.services.recovery import (
    RecoveryEngine,
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
SOL_LANE = MarketLane("binance", "SOL-TEST-PERP", "1m")


def _settings(
    *,
    target_timeframes: tuple[str, ...] = (),
    include_eth: bool = False,
    include_sol: bool = False,
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
    if include_sol:
        assets["SOL"] = {
            "asset": "SOL",
            "enabled": True,
            "instruments": {
                "SOL-TEST-PERP": {
                    "venue": "binance",
                    "market_type": "perpetual",
                    "base_asset": "SOL",
                    "quote_asset": "USDT",
                    "settlement_asset": "USDT",
                    "live_provider": "binance_native",
                    "historical_providers": [
                        "binance_native",
                        "ccxt_binance",
                    ],
                    "provider_symbols": {
                        "binance_native": "SOLUSDT",
                        "ccxt_binance": "SOL/USDT:USDT",
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
        materialize_count: int = 0,
    ) -> None:
        self.latest_requests = latest_requests
        self.missing_requests = missing_requests
        self.live_requests = live_requests
        self.materialize_count = materialize_count
        self.latest_calls: list[dict[str, object]] = []
        self.missing_calls: list[dict[str, object]] = []
        self.live_calls: list[dict[str, object]] = []
        self.materialize_calls: list[dict[str, object]] = []

    async def reconcile_latest_closed_buckets(self, **kwargs: object):
        self.latest_calls.append(kwargs)
        return self.latest_requests

    async def reconcile_missing_closed_buckets(self, **kwargs: object):
        self.missing_calls.append(kwargs)
        return self.missing_requests

    async def materialize_complete_missing_buckets(self, **kwargs: object):
        self.materialize_calls.append(kwargs)
        return self.materialize_count

    async def process_base_candle(self, candle: CanonicalCandle, **kwargs: object):
        self.live_calls.append({"candle": candle, **kwargs})
        return self.live_requests


class _MemoryRepository:
    def __init__(self, candles: tuple[CanonicalCandle, ...] = ()) -> None:
        self.candles = list(candles)
        self.range_calls: list[tuple[MarketLane, datetime, datetime]] = []
        # Latest-candle reads, kept apart from the ranges existing tests assert on.
        self.latest_calls: list[tuple[MarketLane, datetime]] = []

    async def fetch_latest_candle(
        self,
        *,
        lane: MarketLane,
        before: datetime,
    ) -> CanonicalCandle | None:
        self.latest_calls.append((lane, before))
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

    async def fetch_candle_open_times(
        self,
        *,
        lane: MarketLane,
        since: datetime,
        until: datetime,
    ) -> tuple[datetime, ...]:
        return tuple(
            sorted(
                candle.open_time
                for candle in self.candles
                if candle.lane == lane and since <= candle.open_time < until
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
        *,
        first_page_minutes: int = 30,
    ) -> None:
        self.repository = repository
        self.htf_service = htf_service
        self.first_page_minutes = first_page_minutes
        self.calls: list[tuple[RecoveryRequest, ...]] = []
        self.first_page_failed = False
        self.history_start_calls: list[tuple[MarketLane, datetime, datetime]] = []

    async def find_history_start(
        self,
        lane: MarketLane,
        *,
        plan: object,
        since: datetime,
        until: datetime,
    ) -> datetime | None:
        del plan
        self.history_start_calls.append((lane, since, until))
        return since

    async def recover_closure(self, requests, *, plan) -> None:
        batch = tuple(requests)
        self.calls.append(batch)
        for request in batch:
            if request.reason != "runtime_catchup":
                continue
            stop_at = request.until
            if not self.first_page_failed:
                stop_at = min(
                    request.until,
                    request.since + timedelta(minutes=self.first_page_minutes),
                )
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
        history_starts: dict[MarketLane, datetime | None] | None = None,
    ) -> None:
        self.follow_ups = follow_ups or {}
        self.gate = gate
        self.on_call = on_call
        self.history_starts = history_starts or {}
        self.calls: list[RecoveryRequest] = []
        self.history_start_calls: list[tuple[MarketLane, datetime, datetime]] = []
        self.active = 0
        self.max_active = 0

    async def find_history_start(
        self,
        lane: MarketLane,
        *,
        plan: object,
        since: datetime,
        until: datetime,
    ) -> datetime | None:
        del plan
        self.history_start_calls.append((lane, since, until))
        if lane in self.history_starts:
            return self.history_starts[lane]
        # Default: the lane's history reaches back to the startup floor.
        return since

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
    assert htf.materialize_calls[0]["since"] == BOUNDARY - timedelta(days=120)
    assert htf.materialize_calls[0]["before"] == BOUNDARY - timedelta(weeks=1)


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
async def test_startup_retry_rebuilds_derived_history_over_configured_window() -> None:
    settings = _settings(target_timeframes=("15m", "1h"), startup_history_days=1)
    plan = compile_ingestion_plan(
        settings,
        live_provider_ids={"binance_native"},
        historical_provider_ids={"binance_native", "ccxt_binance"},
    )
    lane_plan = plan.lanes[0]
    assert lane_plan.history_floor_duration > lane_plan.lookback_duration
    repository = _MemoryRepository()
    ingestion = _PersistingIngestion(repository)
    htf = HTFAggregationService(
        repository=repository,  # type: ignore[arg-type]
        ingestion_service=ingestion,  # type: ignore[arg-type]
    )
    recovery = _PartialPageRecovery(repository, htf, first_page_minutes=360)
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
        if task.done():
            task.result()
            pytest.fail("supervisor exited before opening the live stream")
        await asyncio.sleep(0)
    supervisor.stop()
    await asyncio.wait_for(task, timeout=1)

    window_start = BOUNDARY - lane_plan.history_floor_duration
    assert recovery.first_page_failed is True
    assert recovery.calls[0] == (
        RecoveryRequest(
            lane=LANE,
            since=window_start,
            until=BOUNDARY,
            reason="runtime_catchup",
        ),
    )
    assert recovery.calls[1] == (
        RecoveryRequest(
            lane=LANE,
            since=window_start + timedelta(hours=6),
            until=BOUNDARY,
            reason="runtime_catchup",
        ),
    )
    for timeframe, duration in lane_plan.target_durations.items():
        expected_starts = tuple(
            window_start + index * duration
            for index in range((BOUNDARY - window_start) // duration)
        )
        actual_starts = tuple(
            sorted(
                candle.open_time
                for candle in repository.candles
                if candle.lane == MarketLane(LANE.venue, LANE.instrument_id, timeframe)
            )
        )
        assert actual_starts == expected_starts, (
            f"{timeframe}: {len(actual_starts)} of {len(expected_starts)} "
            "closed derived buckets exist"
        )


def _base_candles(start: datetime, count: int) -> tuple[CanonicalCandle, ...]:
    return tuple(
        _canonical(close_time=start + (index + 1) * timedelta(minutes=1))
        for index in range(count)
    )


def _supervisor_with_real_htf(
    settings: object,
    repository: _MemoryRepository,
) -> tuple[RuntimeSupervisor, _PersistingIngestion, _Recovery]:
    plan = compile_ingestion_plan(
        settings,
        live_provider_ids={"binance_native"},
        historical_provider_ids={"binance_native", "ccxt_binance"},
    )
    ingestion = _PersistingIngestion(repository)
    recovery = _Recovery()
    supervisor = RuntimeSupervisor(
        plan=plan,
        live_provider=_LiveProvider([_Stream()]),
        repository=repository,  # type: ignore[arg-type]
        ingestion_service=ingestion,  # type: ignore[arg-type]
        htf_service=HTFAggregationService(
            repository=repository,  # type: ignore[arg-type]
            ingestion_service=ingestion,  # type: ignore[arg-type]
        ),
        recovery_engine=recovery,  # type: ignore[arg-type]
        now_fn=lambda: NOW,
    )
    return supervisor, ingestion, recovery


@pytest.mark.asyncio
async def test_shallow_database_prepares_without_recovering_older_history() -> None:
    shallow_start = BOUNDARY - timedelta(hours=3)
    repository = _MemoryRepository(
        (
            *_base_candles(shallow_start, 180),
            *(
                _derived_candle(
                    LANE,
                    shallow_start + index * timedelta(minutes=15),
                    timedelta(minutes=15),
                )
                for index in range(12)
            ),
        )
    )
    supervisor, ingestion, recovery = _supervisor_with_real_htf(
        _settings(target_timeframes=("15m",), startup_history_days=1),
        repository,
    )

    assert await supervisor._prepare_live_connection() == BOUNDARY

    assert recovery.calls == []
    assert min(candle.open_time for candle in repository.candles) == shallow_start
    assert all(
        attempt.open_time >= BOUNDARY - timedelta(minutes=15)
        for attempt in ingestion.commit_attempts
    )


@pytest.mark.asyncio
async def test_older_missing_base_candle_is_skipped_without_blocking_startup() -> None:
    window_start = BOUNDARY - timedelta(days=1)
    gap_open = BOUNDARY - timedelta(hours=12) + timedelta(minutes=7)
    repository = _MemoryRepository(
        tuple(
            candle
            for candle in _base_candles(window_start, 1440)
            if candle.open_time != gap_open
        )
    )
    supervisor, _, recovery = _supervisor_with_real_htf(
        _settings(target_timeframes=("15m", "1h"), startup_history_days=1),
        repository,
    )

    assert await supervisor._prepare_live_connection() == BOUNDARY

    assert recovery.calls == []
    gap_bucket_start = BOUNDARY - timedelta(hours=12)
    for timeframe, duration in supervisor.plan.lanes[0].target_durations.items():
        expected_starts = tuple(
            start
            for start in (
                window_start + index * duration
                for index in range(timedelta(days=1) // duration)
            )
            if start != gap_bucket_start
        )
        actual_starts = tuple(
            sorted(
                candle.open_time
                for candle in repository.candles
                if candle.lane == MarketLane(LANE.venue, LANE.instrument_id, timeframe)
            )
        )
        assert actual_starts == expected_starts, timeframe


@pytest.mark.asyncio
async def test_unset_startup_history_does_not_rebuild_older_buckets() -> None:
    supervisor, _, _, htf, _, _ = _supervisor(
        settings=_settings(target_timeframes=("1h",)),
        repository=_Repository(),
    )

    await supervisor._prepare_live_connection()

    assert htf.materialize_calls == []


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


# ---------------------------------------------------------------------------
# History-start probe on an empty lane during startup preparation
# ---------------------------------------------------------------------------

_LONG_HISTORY_SETTINGS = {
    "target_timeframes": ("1w",),
    "startup_history_days": 120,
    "candle_days": 400,
}
_SHORT_SETTINGS = {"target_timeframes": ("15m", "1h"), "startup_history_days": 1}
_HISTORY_WARNING = "history starts after the startup floor"


def _history_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if _HISTORY_WARNING in record.getMessage()
    ]


@pytest.mark.asyncio
async def test_empty_lane_catches_up_from_the_probed_first_candle(
    caplog: pytest.LogCaptureFixture,
) -> None:
    floor = BOUNDARY - timedelta(days=120)
    first_open = BOUNDARY - timedelta(days=30)
    recovery = _Recovery(history_starts={LANE: first_open})
    supervisor, *_ = _supervisor(
        settings=_settings(**_LONG_HISTORY_SETTINGS),
        repository=_Repository(),
        recovery=recovery,
    )

    with caplog.at_level(logging.WARNING):
        await supervisor._prepare_live_connection()

    assert recovery.history_start_calls == [(LANE, floor, BOUNDARY)]
    assert recovery.calls == [
        RecoveryRequest(
            lane=LANE,
            since=first_open,
            until=BOUNDARY,
            reason="runtime_catchup",
        )
    ]
    (warning,) = _history_warnings(caplog)
    for fragment in (
        str(LANE),
        str(floor),
        str(first_open),
        str(first_open - floor),
    ):
        assert fragment in warning


@pytest.mark.asyncio
async def test_probe_at_the_floor_starts_there_without_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    floor = BOUNDARY - timedelta(days=120)
    recovery = _Recovery(history_starts={LANE: floor})
    supervisor, *_ = _supervisor(
        settings=_settings(**_LONG_HISTORY_SETTINGS),
        repository=_Repository(),
        recovery=recovery,
    )

    with caplog.at_level(logging.WARNING):
        await supervisor._prepare_live_connection()

    assert recovery.calls[0].since == floor
    assert _history_warnings(caplog) == []


@pytest.mark.asyncio
async def test_probe_without_a_candle_excludes_the_only_lane_and_fails_as_before() -> (
    None
):
    floor = BOUNDARY - timedelta(days=120)
    recovery = _Recovery(history_starts={LANE: None})
    supervisor, *_ = _supervisor(
        settings=_settings(**_LONG_HISTORY_SETTINGS),
        repository=_Repository(),
        recovery=recovery,
    )

    with pytest.raises(RecoveryExhaustedError, match="no closed candle") as raised:
        await supervisor._prepare_live_connection()

    assert raised.value.lane == LANE
    assert recovery.history_start_calls == [(LANE, floor, BOUNDARY)]
    assert recovery.calls == []
    assert supervisor.snapshot().excluded_lanes == ()


@pytest.mark.asyncio
async def test_lane_with_a_stored_candle_is_not_probed() -> None:
    stale = _canonical(close_time=BOUNDARY - timedelta(days=200))
    for latest in (_canonical(close_time=BOUNDARY - timedelta(minutes=3)), stale):
        recovery = _Recovery(history_starts={LANE: BOUNDARY - timedelta(days=30)})
        supervisor, *_ = _supervisor(
            settings=_settings(**_LONG_HISTORY_SETTINGS),
            repository=_Repository({LANE: latest}),
            recovery=recovery,
        )

        await supervisor._prepare_live_connection()

        assert recovery.history_start_calls == []
        assert [call.since for call in recovery.calls] == [
            max(latest.close_time, BOUNDARY - timedelta(days=120))
        ]


@pytest.mark.asyncio
async def test_only_the_empty_lane_is_probed_when_lanes_differ() -> None:
    floor = BOUNDARY - timedelta(days=120)
    first_open = BOUNDARY - timedelta(days=30)
    eth_latest = _canonical(ETH_LANE, close_time=BOUNDARY - timedelta(minutes=2))
    recovery = _Recovery(history_starts={LANE: first_open})
    supervisor, *_ = _supervisor(
        settings=_settings(include_eth=True, **_LONG_HISTORY_SETTINGS),
        repository=_Repository({ETH_LANE: eth_latest}),
        recovery=recovery,
    )

    await supervisor._prepare_live_connection()

    assert recovery.history_start_calls == [(LANE, floor, BOUNDARY)]
    assert sorted(recovery.calls, key=lambda request: request.lane.instrument_id) == [
        RecoveryRequest(
            lane=LANE, since=first_open, until=BOUNDARY, reason="runtime_catchup"
        ),
        RecoveryRequest(
            lane=ETH_LANE,
            since=eth_latest.close_time,
            until=BOUNDARY,
            reason="runtime_catchup",
        ),
    ]


class _ListedProvider:
    """In-memory historical provider: a lane has candles only from its listing."""

    def __init__(
        self,
        listed: dict[MarketLane, datetime],
        provider_id: str = "binance_native",
    ) -> None:
        self.listed = listed
        self.provider_id = provider_id
        self.requests: list[tuple[MarketLane, datetime, datetime, int]] = []

    async def fetch_closed_candles(
        self,
        *,
        lane: MarketLane,
        provider_symbol: str,
        timeframe_duration: timedelta,
        since: datetime,
        until: datetime,
        limit: int,
    ) -> tuple[CandleObservation, ...]:
        del provider_symbol
        self.requests.append((lane, since, until, limit))
        open_time = max(since, self.listed[lane])
        rows: list[CandleObservation] = []
        while open_time < until and len(rows) < limit:
            rows.append(
                replace(
                    _observation(lane, open_time=open_time),
                    provider_id=self.provider_id,
                )
            )
            open_time += timeframe_duration
        return tuple(rows)


class _StoringIngestion(_PersistingIngestion):
    async def commit_observation(
        self, observation: CandleObservation
    ) -> CandleCommitStatus:
        return self.repository.insert(canonicalize_observation(observation))


def _real_stack(
    settings: object,
    *,
    listed: dict[MarketLane, datetime],
    now: datetime = NOW,
    reconnect_sleep_fn: Callable[[float], object] | None = None,
) -> tuple[
    RuntimeSupervisor,
    _MemoryRepository,
    _ListedProvider,
    _ListedProvider,
    _LiveProvider,
]:
    """Real supervisor, recovery engine and HTF service over in-memory storage."""
    plan = compile_ingestion_plan(
        settings,
        live_provider_ids={"binance_native"},
        historical_provider_ids={"binance_native", "ccxt_binance"},
    )
    repository = _MemoryRepository()
    ingestion = _StoringIngestion(repository)
    htf = HTFAggregationService(
        repository=repository,  # type: ignore[arg-type]
        ingestion_service=ingestion,  # type: ignore[arg-type]
    )
    historical = _ListedProvider(listed)
    fallback = _ListedProvider(listed, "ccxt_binance")
    engine = RecoveryEngine(
        providers={"binance_native": historical, "ccxt_binance": fallback},  # type: ignore[dict-item]
        repository=repository,  # type: ignore[arg-type]
        ingestion_service=ingestion,  # type: ignore[arg-type]
        htf_service=htf,
        max_concurrency=2,
        page_limit=500,
        max_attempts_per_provider=1,
        retry_backoff_seconds=0,
        rest_finalization_grace_seconds=0,
        now_fn=lambda: now,
    )
    live = _LiveProvider([_Stream()])
    supervisor = RuntimeSupervisor(
        plan=plan,
        live_provider=live,
        repository=repository,  # type: ignore[arg-type]
        ingestion_service=ingestion,  # type: ignore[arg-type]
        htf_service=htf,
        recovery_engine=engine,
        now_fn=lambda: now,
        reconnect_sleep_fn=reconnect_sleep_fn,  # type: ignore[arg-type]
    )
    return supervisor, repository, historical, fallback, live


def _stored_starts(
    repository: _MemoryRepository, lane: MarketLane
) -> tuple[datetime, ...]:
    return tuple(
        sorted(candle.open_time for candle in repository.candles if candle.lane == lane)
    )


def _complete_bucket_starts(
    first: datetime, boundary: datetime, duration: timedelta
) -> tuple[datetime, ...]:
    start = aligned_bucket_start(first, duration, ORIGIN)
    if start < first:
        start += duration
    starts: list[datetime] = []
    while start + duration <= boundary:
        starts.append(start)
        start += duration
    return tuple(starts)


def _assert_history_starts_at(
    supervisor: RuntimeSupervisor,
    repository: _MemoryRepository,
    lane: MarketLane,
    *,
    first: datetime,
    boundary: datetime,
) -> None:
    """Base candles run contiguously from `first`; only complete buckets exist."""
    assert _stored_starts(repository, lane) == tuple(
        first + index * timedelta(minutes=1)
        for index in range((boundary - first) // timedelta(minutes=1))
    )
    for timeframe, duration in supervisor.plan.lanes_by_lane[
        lane
    ].target_durations.items():
        derived_lane = MarketLane(lane.venue, lane.instrument_id, timeframe)
        assert _stored_starts(repository, derived_lane) == _complete_bucket_starts(
            first, boundary, duration
        ), timeframe


@pytest.mark.parametrize(
    "listed_ago",
    [
        timedelta(minutes=37),
        timedelta(hours=5, minutes=20),
        timedelta(hours=23, minutes=50),
    ],
)
@pytest.mark.asyncio
async def test_lane_listed_inside_the_window_prepares_in_one_cycle(
    listed_ago: timedelta,
) -> None:
    first = BOUNDARY - listed_ago
    floor = BOUNDARY - timedelta(days=1)
    supervisor, repository, historical, fallback, _ = _real_stack(
        _settings(**_SHORT_SETTINGS), listed={LANE: first}
    )

    assert await supervisor._prepare_live_connection() == BOUNDARY

    _assert_history_starts_at(
        supervisor, repository, LANE, first=first, boundary=BOUNDARY
    )
    assert historical.requests[0] == (LANE, floor, BOUNDARY, 1)
    assert all(since >= first for _, since, _, _ in historical.requests[1:])
    assert fallback.requests == []


@pytest.mark.asyncio
async def test_lane_listed_inside_the_window_opens_the_websocket_without_a_retry() -> (
    None
):
    first = BOUNDARY - timedelta(hours=5, minutes=20)

    async def forbid_retry(_seconds: float) -> None:
        raise AssertionError("startup needed a retry cycle")

    supervisor, repository, _, _, live = _real_stack(
        _settings(**_SHORT_SETTINGS),
        listed={LANE: first},
        reconnect_sleep_fn=forbid_retry,
    )

    task = asyncio.create_task(supervisor.run())
    while not live.calls:
        if task.done():
            task.result()
            pytest.fail("supervisor exited before opening the live stream")
        await asyncio.sleep(0)
    supervisor.stop()
    await asyncio.wait_for(task, timeout=1)

    assert supervisor.snapshot().last_error is None
    assert min(_stored_starts(repository, LANE)) == first


@pytest.mark.asyncio
async def test_a_late_listed_lane_does_not_hold_back_a_lane_with_full_history() -> None:
    floor = BOUNDARY - timedelta(days=1)
    eth_first = BOUNDARY - timedelta(hours=5, minutes=20)
    supervisor, repository, _, _, _ = _real_stack(
        _settings(include_eth=True, **_SHORT_SETTINGS),
        listed={LANE: floor - timedelta(days=10), ETH_LANE: eth_first},
    )

    assert await supervisor._prepare_live_connection() == BOUNDARY

    _assert_history_starts_at(
        supervisor, repository, LANE, first=floor, boundary=BOUNDARY
    )
    _assert_history_starts_at(
        supervisor, repository, ETH_LANE, first=eth_first, boundary=BOUNDARY
    )


@pytest.mark.asyncio
async def test_full_history_cold_start_stores_base_candles_from_exactly_the_floor() -> (
    None
):
    # A boundary that is not on any target grid, so the first 15m and 1h buckets
    # straddle the floor.
    now = datetime(2026, 8, 9, 10, 17, 30, tzinfo=UTC)
    boundary = datetime(2026, 8, 9, 10, 17, tzinfo=UTC)
    floor = boundary - timedelta(days=1)
    supervisor, repository, historical, fallback, _ = _real_stack(
        _settings(**_SHORT_SETTINGS),
        listed={LANE: floor - timedelta(days=10)},
        now=now,
    )

    assert await supervisor._prepare_live_connection() == boundary

    _assert_history_starts_at(
        supervisor, repository, LANE, first=floor, boundary=boundary
    )
    assert all(since >= floor for _, since, _, _ in historical.requests)
    assert fallback.requests == []


# ---------------------------------------------------------------------------
# Lane fault isolation: one instrument that cannot be prepared is excluded and
# repaired in the background instead of holding every instrument out of live
# ingestion.
# ---------------------------------------------------------------------------

_RETRY = 60.0
_OLD_CLOSE = BOUNDARY - timedelta(minutes=5)


class _Clock:
    def __init__(self) -> None:
        self.value = NOW

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


class _QueueStream:
    """A live stream the test feeds one item at a time."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[object] = asyncio.Queue()
        self.closed = False

    def put(self, item: object) -> None:
        self.queue.put_nowait(item)

    def __aiter__(self) -> _QueueStream:
        return self

    async def __anext__(self) -> CandleObservation:
        item = await self.queue.get()
        if isinstance(item, BaseException):
            raise item
        return item  # type: ignore[return-value]

    async def aclose(self) -> None:
        self.closed = True


class _LaneHTF(_HTF):
    """Returns the live follow-up only for the faulty lane."""

    async def process_base_candle(self, candle: CanonicalCandle, **kwargs: object):
        self.live_calls.append({"candle": candle, **kwargs})
        return self.live_requests if candle.lane == ETH_LANE else ()


def _exhausted(request: RecoveryRequest) -> BaseException:
    return RecoveryExhaustedError(
        f"synthetic exhaustion for {request.lane}", lane=request.lane
    )


def _interruption(*lanes: MarketLane) -> LiveStreamInterrupted:
    return LiveStreamInterrupted(
        reason="websocket_disconnected",
        recovery_requests=tuple(
            RecoveryRequest(
                lane=lane,
                since=BOUNDARY - timedelta(minutes=1),
                until=BOUNDARY,
                reason="websocket_disconnected",
            )
            for lane in lanes
        ),
    )


class _Rig:
    """A supervisor over BTC (healthy) and one or two lanes that can fail."""

    def __init__(
        self,
        *,
        include_sol: bool = False,
        old_lanes: tuple[MarketLane, ...] = (ETH_LANE,),
        empty_lanes: tuple[MarketLane, ...] = (),
        history_starts: dict[MarketLane, datetime | None] | None = None,
        persistent: dict[MarketLane, object] | None = None,
        scripts: dict[MarketLane, list[object]] | None = None,
        repair_free_sleeps: int = 1,
        stream_count: int = 2,
        backoff: float = 3,
        htf: _HTF | None = None,
    ) -> None:
        self.clock = _Clock()
        self.persistent = persistent or {}
        self.scripts = scripts or {}
        self.reconnect_sleeps: list[float] = []
        self.reconnect_snapshots: list[SupervisorSnapshot] = []
        self.repair_sleeps: list[float] = []
        self.repair_gate = asyncio.Event()
        self.repair_free_sleeps = repair_free_sleeps
        self.repair_cancelled = 0
        self.streams = [_QueueStream() for _ in range(stream_count)]
        self.provider = _LiveProvider(list(self.streams))  # type: ignore[arg-type]
        lanes = [LANE, ETH_LANE, *([SOL_LANE] if include_sol else [])]
        latest = {
            lane: _canonical(
                lane,
                close_time=_OLD_CLOSE if lane in old_lanes else BOUNDARY,
            )
            for lane in lanes
            if lane not in empty_lanes
        }
        self.recovery = _Recovery(
            on_call=self._on_call,
            history_starts=history_starts,
        )
        self.on_reconnect_sleep: Callable[[], None] | None = None
        self.supervisor, *_ = _supervisor(
            settings=_settings(
                include_eth=True,
                include_sol=include_sol,
                reconnect_backoff_seconds=backoff,
            ),
            repository=_Repository(latest),
            recovery=self.recovery,
            htf=htf,
            provider=self.provider,  # type: ignore[arg-type]
            now_fn=self.clock,
            reconnect_sleep_fn=self._reconnect_sleep,
        )
        self.supervisor._repair_sleep = self._repair_sleep

    def _on_call(self, request: RecoveryRequest) -> None:
        failure = self.persistent.get(request.lane)
        if failure is None:
            script = self.scripts.get(request.lane)
            failure = script.pop(0) if script else None
        if failure is not None:
            error = failure(request)  # type: ignore[operator]
            if error is not None:
                raise error

    async def _reconnect_sleep(self, seconds: float) -> None:
        self.reconnect_sleeps.append(seconds)
        self.reconnect_snapshots.append(self.supervisor.snapshot())
        self.clock.advance(120)
        if self.on_reconnect_sleep is not None:
            self.on_reconnect_sleep()
        await asyncio.sleep(0)

    async def _repair_sleep(self, seconds: float) -> None:
        self.repair_sleeps.append(seconds)
        self.clock.advance(seconds)
        try:
            if len(self.repair_sleeps) > self.repair_free_sleeps:
                await self.repair_gate.wait()
            else:
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            self.repair_cancelled += 1
            raise

    def start(self) -> asyncio.Task[None]:
        return asyncio.create_task(self.supervisor.run())

    async def until(self, predicate: Callable[[], bool]) -> None:
        async def wait() -> None:
            while not predicate():
                await asyncio.sleep(0.001)

        await asyncio.wait_for(wait(), timeout=2)

    async def finish(self, task: asyncio.Task[None]) -> None:
        self.supervisor.stop()
        await asyncio.wait_for(task, timeout=2)
        assert self.supervisor._repair_task is None
        assert not [
            item
            for item in asyncio.all_tasks()
            if item.get_name() == "ingestion-lane-repair"
        ]


def _excluded(supervisor: RuntimeSupervisor) -> dict[MarketLane, object]:
    return {
        MarketLane(fault.venue, fault.instrument_id, "1m"): fault
        for fault in supervisor.snapshot().excluded_lanes
    }


@pytest.mark.asyncio
async def test_all_healthy_lanes_have_no_exclusions_or_repair_task() -> None:
    rig = _Rig(old_lanes=())
    task = rig.start()
    rig.streams[0].put(_observation(LANE))
    await rig.until(lambda: rig.supervisor.snapshot().state is RuntimeState.LIVE)

    assert rig.supervisor.snapshot().excluded_lanes == ()
    assert rig.supervisor._repair_task is None
    assert set(rig.provider.calls[0]) == {LANE, ETH_LANE}
    assert rig.repair_sleeps == []
    await rig.finish(task)


@pytest.mark.asyncio
async def test_startup_probe_without_a_candle_excludes_only_that_lane() -> None:
    rig = _Rig(
        old_lanes=(),
        empty_lanes=(ETH_LANE,),
        history_starts={ETH_LANE: None},
    )

    anchor = await rig.supervisor._prepare_live_connection()

    assert anchor == BOUNDARY
    assert tuple(context.lane for context in rig.supervisor._admitted) == (LANE,)
    ((lane, fault),) = _excluded(rig.supervisor).items()
    assert lane == ETH_LANE
    assert fault.reason == "no_closed_candle_in_window"
    assert fault.detail == ""
    assert fault.excluded_since == NOW
    assert fault.next_retry_at == NOW + timedelta(seconds=_RETRY)
    assert [call.lane for call in rig.recovery.calls] == []
    assert rig.supervisor.active_lanes == (LANE, ETH_LANE)


@pytest.mark.asyncio
async def test_startup_exhaustion_excludes_the_lane_and_the_rest_goes_live() -> None:
    rig = _Rig(persistent={ETH_LANE: _exhausted})
    task = rig.start()
    rig.streams[0].put(_observation(LANE))
    await rig.until(lambda: rig.supervisor.snapshot().state is RuntimeState.LIVE)

    assert rig.reconnect_sleeps == []
    assert set(rig.provider.calls[0]) == {LANE}
    ((lane, fault),) = _excluded(rig.supervisor).items()
    assert lane == ETH_LANE
    assert fault.reason == "recovery_exhausted"
    assert "synthetic exhaustion" in fault.detail
    assert rig.supervisor.snapshot().last_error is None
    await rig.finish(task)


@pytest.mark.asyncio
async def test_excluded_lane_rejoins_after_repair_without_backoff() -> None:
    rig = _Rig(scripts={ETH_LANE: [_exhausted, _exhausted]}, repair_free_sleeps=5)
    task = rig.start()
    rig.streams[0].put(_observation(LANE))
    await rig.until(lambda: rig.supervisor.snapshot().state is RuntimeState.LIVE)
    await rig.until(lambda: rig.supervisor._repair_task.done())

    assert rig.supervisor._ready_to_rejoin == {ETH_LANE}
    assert len(rig.provider.calls) == 1
    assert set(rig.supervisor._admitted_by_lane) == {LANE}

    rig.streams[0].put(_observation(LANE))
    await rig.until(lambda: len(rig.provider.calls) == 2)
    rig.streams[1].put(_observation(ETH_LANE))
    await rig.until(lambda: rig.supervisor.snapshot().state is RuntimeState.LIVE)

    assert set(rig.provider.calls[1]) == {LANE, ETH_LANE}
    assert rig.supervisor.snapshot().excluded_lanes == ()
    assert rig.supervisor._ready_to_rejoin == set()
    assert rig.reconnect_sleeps == []
    assert rig.streams[0].closed
    await rig.finish(task)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_delay"),
    [
        (_exhausted, _RETRY),
        (lambda request: RecoveryRateLimitedError(retry_after_seconds=90), 90.0),
        (lambda request: RecoveryRateLimitedError(retry_after_seconds=10), _RETRY),
        (lambda request: asyncpg.PostgresConnectionError("db down"), _RETRY),
    ],
)
async def test_failing_repair_reschedules_without_restarting_the_stream(
    failure: Callable[[RecoveryRequest], BaseException],
    expected_delay: float,
) -> None:
    rig = _Rig(scripts={ETH_LANE: [_exhausted, failure]})
    task = rig.start()
    rig.streams[0].put(_observation(LANE))
    await rig.until(lambda: rig.supervisor.snapshot().state is RuntimeState.LIVE)
    await rig.until(lambda: len(rig.repair_sleeps) == 2)

    fault = _excluded(rig.supervisor)[ETH_LANE]
    attempted_at = NOW + timedelta(seconds=_RETRY)
    assert rig.repair_sleeps[0] == _RETRY
    assert fault.excluded_since == NOW
    assert fault.next_retry_at == attempted_at + timedelta(seconds=expected_delay)
    assert rig.repair_sleeps[1] == expected_delay
    assert len(rig.provider.calls) == 1
    assert rig.reconnect_sleeps == []
    assert rig.supervisor._ready_to_rejoin == set()
    await rig.finish(task)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        TransportDeadlineExceeded(
            provider_id="binance_native",
            operation="REST klines",
            timeout_seconds=30,
        ),
        DataIngestionError("synthetic non-availability failure"),
    ],
)
async def test_fatal_repair_error_surfaces_after_the_next_observation(
    error: BaseException,
) -> None:
    rig = _Rig(scripts={ETH_LANE: [_exhausted, lambda request: error]})
    task = rig.start()
    rig.streams[0].put(_observation(LANE))
    await rig.until(lambda: rig.supervisor.snapshot().state is RuntimeState.LIVE)
    await rig.until(lambda: rig.supervisor._repair_failure is not None)

    assert not task.done()
    rig.streams[0].put(_observation(LANE))
    with pytest.raises(type(error)) as raised:
        await asyncio.wait_for(task, timeout=2)

    assert raised.value is error
    assert rig.supervisor.snapshot().state is RuntimeState.ERROR
    assert rig.supervisor.quarantined is isinstance(error, TransportDeadlineExceeded)
    assert rig.streams[0].closed
    assert rig.reconnect_sleeps == []
    assert rig.supervisor._repair_task is None


@pytest.mark.asyncio
async def test_interruption_recovery_exhaustion_excludes_the_lane_next_cycle() -> None:
    rig = _Rig(old_lanes=(), persistent={ETH_LANE: _exhausted})
    rig.streams[0].put(_interruption(LANE, ETH_LANE))
    task = rig.start()
    await rig.until(lambda: len(rig.provider.calls) == 2)
    rig.streams[1].put(_observation(LANE))
    await rig.until(lambda: rig.supervisor.snapshot().state is RuntimeState.LIVE)

    assert rig.reconnect_sleeps == [3]
    assert set(rig.provider.calls[0]) == {LANE, ETH_LANE}
    assert set(rig.provider.calls[1]) == {LANE}
    assert set(_excluded(rig.supervisor)) == {ETH_LANE}
    await rig.finish(task)


@pytest.mark.asyncio
async def test_live_followup_exhaustion_excludes_the_lane_next_cycle() -> None:
    follow_up = RecoveryRequest(
        lane=ETH_LANE,
        since=BOUNDARY - timedelta(minutes=1),
        until=BOUNDARY,
        reason="htf_incomplete:1h",
    )
    rig = _Rig(
        old_lanes=(),
        persistent={ETH_LANE: _exhausted},
        htf=_LaneHTF(live_requests=(follow_up,)),
    )
    rig.streams[0].put(_observation(ETH_LANE))
    task = rig.start()
    await rig.until(lambda: len(rig.provider.calls) == 2)
    rig.streams[1].put(_observation(LANE))
    await rig.until(lambda: rig.supervisor.snapshot().state is RuntimeState.LIVE)

    assert rig.reconnect_sleeps == [3]
    assert set(rig.provider.calls[1]) == {LANE}
    assert set(_excluded(rig.supervisor)) == {ETH_LANE}
    await rig.finish(task)


@pytest.mark.asyncio
async def test_every_lane_faulty_behaves_as_before_and_retries_every_lane() -> None:
    rig = _Rig(
        old_lanes=(LANE, ETH_LANE),
        persistent={LANE: _exhausted, ETH_LANE: _exhausted},
        backoff=3,
    )
    rig.on_reconnect_sleep = lambda: (
        rig.supervisor.stop() if len(rig.reconnect_sleeps) == 2 else None
    )
    task = rig.start()
    await asyncio.wait_for(task, timeout=2)

    assert rig.provider.calls == []
    assert rig.reconnect_sleeps == [3, 3]
    first = rig.reconnect_snapshots[0]
    assert first.state is RuntimeState.RECOVERING
    assert first.last_error is not None
    assert "synthetic exhaustion" in first.last_error
    assert first.excluded_lanes == ()
    assert rig.supervisor.snapshot().excluded_lanes == ()
    attempted = [call.lane for call in rig.recovery.calls]
    assert attempted.count(LANE) >= 2
    assert attempted.count(ETH_LANE) >= 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_sleep"),
    [
        (lambda request: RecoveryRateLimitedError(retry_after_seconds=7), 7.0),
        (lambda request: asyncpg.PostgresConnectionError("db down"), 3.0),
    ],
)
async def test_rate_limit_and_storage_outage_do_not_exclude_a_lane(
    failure: Callable[[RecoveryRequest], BaseException],
    expected_sleep: float,
) -> None:
    rig = _Rig(scripts={ETH_LANE: [failure]})
    rig.on_reconnect_sleep = rig.supervisor.stop
    task = rig.start()
    await asyncio.wait_for(task, timeout=2)

    assert rig.reconnect_sleeps == [expected_sleep]
    assert rig.reconnect_snapshots[0].excluded_lanes == ()
    assert rig.reconnect_snapshots[0].state is RuntimeState.RECOVERING
    assert rig.supervisor.snapshot().excluded_lanes == ()
    assert rig.provider.calls == []


@pytest.mark.asyncio
async def test_exhaustion_without_a_lane_is_not_isolated() -> None:
    rig = _Rig(
        persistent={ETH_LANE: lambda request: RecoveryExhaustedError("anonymous")}
    )

    with pytest.raises(RecoveryExhaustedError, match="anonymous") as raised:
        await rig.supervisor._prepare_live_connection()

    assert raised.value.lane is None
    assert rig.supervisor.snapshot().excluded_lanes == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("healthy", [LANE, ETH_LANE, SOL_LANE])
async def test_two_faulty_lanes_are_both_excluded_in_either_order(
    healthy: MarketLane,
) -> None:
    lanes = (LANE, ETH_LANE, SOL_LANE)
    rig = _Rig(
        include_sol=True,
        old_lanes=lanes,
        persistent={lane: _exhausted for lane in lanes if lane != healthy},
    )

    await rig.supervisor._prepare_live_connection()

    assert [
        fault.instrument_id for fault in rig.supervisor.snapshot().excluded_lanes
    ] == [lane.instrument_id for lane in lanes if lane != healthy]
    assert tuple(context.lane for context in rig.supervisor._admitted) == (healthy,)
    healthy_requests = {call for call in rig.recovery.calls if call.lane == healthy}
    assert healthy_requests == {
        RecoveryRequest(
            lane=healthy,
            since=BOUNDARY - timedelta(minutes=1),
            until=BOUNDARY,
            reason="runtime_catchup",
        )
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("how", ["stop", "cancel", "interruption"])
async def test_repair_task_is_cancelled_and_awaited_when_the_live_loop_ends(
    how: str,
) -> None:
    rig = _Rig(persistent={ETH_LANE: _exhausted}, repair_free_sleeps=0)
    task = rig.start()
    await rig.until(lambda: len(rig.repair_sleeps) == 1)
    assert rig.supervisor._repair_task is not None

    if how == "stop":
        await rig.finish(task)
    elif how == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
        assert rig.supervisor._repair_task is None
    else:
        rig.on_reconnect_sleep = lambda: setattr(
            rig, "cancelled_at_reconnect", rig.repair_cancelled
        )
        rig.streams[0].put(_interruption())
        await rig.until(lambda: len(rig.provider.calls) == 2)
        assert rig.cancelled_at_reconnect == 1  # type: ignore[attr-defined]
        await rig.finish(task)

    assert rig.repair_cancelled >= 1
    assert not [
        item
        for item in asyncio.all_tasks()
        if item.get_name() == "ingestion-lane-repair"
    ]
    assert rig.streams[0].closed


def test_lane_exclusion_gauge_reports_every_planned_lane() -> None:
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader

    reader = InMemoryMetricReader()
    meter = MeterProvider(metric_readers=[reader]).get_meter("test")
    observability = IngestionObservability(meter=meter)
    observability.set_lane_exclusions((LANE, ETH_LANE), (ETH_LANE,))

    def observed() -> dict[str, int]:
        data = reader.get_metrics_data()
        values: dict[str, int] = {}
        for resource in data.resource_metrics:
            for scope in resource.scope_metrics:
                for metric in scope.metrics:
                    if metric.name != "ingestion.lane.excluded":
                        continue
                    for point in metric.data.data_points:
                        values[point.attributes["instrument_id"]] = point.value
        return values

    assert observed() == {"BTC-TEST-PERP": 0, "ETH-TEST-PERP": 1}
    observability.set_lane_exclusions((LANE, ETH_LANE), ())
    assert observed() == {"BTC-TEST-PERP": 0, "ETH-TEST-PERP": 0}
