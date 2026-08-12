from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid5

from apps.ingestion_app.domain.candle import CandleObservation, CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.publication.outbox import OutboxEvent
from apps.ingestion_app.runtime.supervisor import (
    DesiredRuntimeState,
    RuntimeSnapshot,
    RuntimeState,
)
from apps.ingestion_app.settings import IngestionSettings
from apps.ingestion_app.storage.repository import CandleCommitStatus

ORIGIN = datetime(1970, 1, 5, tzinfo=UTC)
BASE_DURATION = timedelta(minutes=1)
BOUNDARY = datetime(2026, 8, 10, 10, 0, tzinfo=UTC)
FULL_TIMEFRAMES = (
    "1m",
    "15m",
    "30m",
    "1h",
    "4h",
    "6h",
    "12h",
    "1d",
    "1w",
)
TIMEFRAME_SECONDS = {
    "1m": 60,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14_400,
    "6h": 21_600,
    "12h": 43_200,
    "1d": 86_400,
    "1w": 604_800,
}


def synthetic_settings(
    count: int = 500,
    *,
    full_timeframes: bool = False,
    generation: int = 0,
    queue_maxsize: int = 1000,
    max_concurrency: int = 4,
    page_limit: int = 500,
    max_attempts_per_provider: int = 2,
    retry_backoff_seconds: int = 1,
    rest_finalization_grace_seconds: int = 5,
) -> IngestionSettings:
    """Build a fully validated synthetic settings snapshot without disk I/O."""
    configured_timeframes = FULL_TIMEFRAMES if full_timeframes else ("1m",)
    assets: dict[str, dict[str, Any]] = {}
    for index in range(count):
        asset = f"G{generation}SYN{index:04d}"
        instrument_id = f"{asset}-USDT-PERP"
        assets[asset] = {
            "asset": asset,
            "enabled": True,
            "instruments": {
                instrument_id: {
                    "venue": "binance",
                    "market_type": "perpetual",
                    "base_asset": asset,
                    "quote_asset": "USDT",
                    "settlement_asset": "USDT",
                    "live_provider": "binance_native",
                    "historical_providers": ["binance_native", "ccxt_binance"],
                    "provider_symbols": {
                        "binance_native": f"{asset}USDT",
                        "ccxt_binance": f"{asset}/USDT:USDT",
                    },
                    "timeframes": list(configured_timeframes),
                }
            },
        }

    return IngestionSettings.model_validate(
        {
            "base_timeframe": "1m",
            "calendar": {
                "type": "continuous",
                "timezone": "UTC",
                "alignment_origin": "1970-01-05T00:00:00Z",
            },
            "recovery": {
                "max_concurrency": max_concurrency,
                "page_limit": page_limit,
                "max_attempts_per_provider": max_attempts_per_provider,
                "retry_backoff_seconds": retry_backoff_seconds,
                "rest_finalization_grace_seconds": rest_finalization_grace_seconds,
            },
            "websocket": {
                "stream_url": "wss://fstream.binance.com/market",
                "queue_maxsize": queue_maxsize,
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
            "timeframes": {
                timeframe: {"duration_seconds": TIMEFRAME_SECONDS[timeframe]}
                for timeframe in configured_timeframes
            },
            "providers": {
                "binance_native": {"enabled": True},
                "ccxt_binance": {"enabled": True, "exchange_id": "binanceusdm"},
            },
            "assets": assets,
        }
    )


def synthetic_lanes(settings: IngestionSettings) -> tuple[MarketLane, ...]:
    return tuple(
        MarketLane(instrument.venue, instrument_id, settings.base_timeframe)
        for asset_name in sorted(settings.assets)
        for instrument_id, instrument in sorted(
            settings.assets[asset_name].instruments.items()
        )
        if settings.assets[asset_name].enabled
    )


def observation(
    lane: MarketLane,
    open_time: datetime,
    *,
    provider_id: str = "binance_native",
    transport: str = "rest",
    provider_symbol: str | None = None,
    value: int = 100,
) -> CandleObservation:
    base = Decimal(value)
    return CandleObservation(
        lane=lane,
        provider_id=provider_id,
        provider_symbol=provider_symbol or lane.instrument_id.replace("-", ""),
        transport=transport,
        open_time=open_time,
        close_time=open_time + BASE_DURATION,
        open=base,
        high=base + Decimal(2),
        low=base - Decimal(1),
        close=base + Decimal(1),
        volume=Decimal(value + 10),
        taker_buy_base=Decimal(value + 5),
        received_at=open_time + BASE_DURATION,
        provider_close_time=(
            open_time + BASE_DURATION if transport == "websocket" else None
        ),
        provider_event_id=None,
    )


def canonical(observed: CandleObservation) -> CanonicalCandle:
    return CanonicalCandle(
        lane=observed.lane,
        open_time=observed.open_time,
        close_time=observed.close_time,
        open=observed.open,
        high=observed.high,
        low=observed.low,
        close=observed.close,
        volume=observed.volume,
        taker_buy_base=observed.taker_buy_base,
        source_type="provider",
        source_provider=observed.provider_id,
        source_timeframe=None,
    )


def recovery_request(
    lane: MarketLane,
    since: datetime,
    until: datetime,
    *,
    reason: str = "certification",
) -> RecoveryRequest:
    return RecoveryRequest(lane=lane, since=since, until=until, reason=reason)


class ControlledRepository:
    def __init__(
        self,
        *,
        latest: Mapping[MarketLane, CanonicalCandle] | None = None,
        rows: tuple[CanonicalCandle, ...] = (),
        range_builder: Callable[
            [MarketLane, datetime, datetime], tuple[CanonicalCandle, ...]
        ]
        | None = None,
    ) -> None:
        self.latest = dict(latest or {})
        self.rows: dict[tuple[MarketLane, datetime], CanonicalCandle] = {
            (row.lane, row.open_time): row for row in rows
        }
        self.range_builder = range_builder
        self.latest_calls: list[tuple[MarketLane, datetime]] = []
        self.range_calls: list[tuple[MarketLane, datetime, datetime]] = []

    async def fetch_latest_candle(
        self,
        *,
        lane: MarketLane,
        before: datetime,
    ) -> CanonicalCandle | None:
        self.latest_calls.append((lane, before))
        if lane in self.latest:
            return self.latest[lane]
        candidates = [
            candle
            for (row_lane, _), candle in self.rows.items()
            if row_lane == lane and candle.close_time <= before
        ]
        return max(candidates, key=lambda candle: candle.open_time, default=None)

    async def fetch_candles(
        self,
        *,
        lane: MarketLane,
        since: datetime,
        until: datetime,
    ) -> tuple[CanonicalCandle, ...]:
        self.range_calls.append((lane, since, until))
        if self.range_builder is not None:
            generated = self.range_builder(lane, since, until)
            for candle in generated:
                self.rows[(candle.lane, candle.open_time)] = candle
            return generated
        return tuple(
            sorted(
                (
                    candle
                    for (row_lane, open_time), candle in self.rows.items()
                    if row_lane == lane and since <= open_time < until
                ),
                key=lambda candle: candle.open_time,
            )
        )


class RecordingIngestion:
    def __init__(self, *, conflict_lane: MarketLane | None = None) -> None:
        self.conflict_lane = conflict_lane
        self.observations: list[CandleObservation] = []
        self.candles: list[CanonicalCandle] = []
        self.canonical_by_key: dict[tuple[MarketLane, datetime], CanonicalCandle] = {}
        self.statuses: list[CandleCommitStatus] = []

    async def commit_observation(
        self,
        observed: CandleObservation,
    ) -> CandleCommitStatus:
        self.observations.append(observed)
        if observed.lane == self.conflict_lane:
            self.statuses.append(CandleCommitStatus.CONFLICT)
            return CandleCommitStatus.CONFLICT
        key = (observed.lane, observed.open_time)
        if key in self.canonical_by_key:
            self.statuses.append(CandleCommitStatus.DUPLICATE)
            return CandleCommitStatus.DUPLICATE
        candle = canonical(observed)
        self.canonical_by_key[key] = candle
        self.statuses.append(CandleCommitStatus.INSERTED)
        return CandleCommitStatus.INSERTED

    async def commit_candle(self, candle: CanonicalCandle) -> CandleCommitStatus:
        self.candles.append(candle)
        key = (candle.lane, candle.open_time)
        if key in self.canonical_by_key:
            self.statuses.append(CandleCommitStatus.DUPLICATE)
            return CandleCommitStatus.DUPLICATE
        self.canonical_by_key[key] = candle
        self.statuses.append(CandleCommitStatus.INSERTED)
        return CandleCommitStatus.INSERTED


class RecordingHTF:
    def __init__(
        self,
        *,
        latest_requests: tuple[RecoveryRequest, ...] = (),
        affected_requests: tuple[RecoveryRequest, ...] = (),
        live_requests: tuple[RecoveryRequest, ...] = (),
    ) -> None:
        self.latest_requests = latest_requests
        self.affected_requests = affected_requests
        self.live_requests = live_requests
        self.latest_calls: list[dict[str, Any]] = []
        self.affected_calls: list[dict[str, Any]] = []
        self.live_calls: list[dict[str, Any]] = []

    async def reconcile_latest_closed_buckets(self, **kwargs: Any):
        self.latest_calls.append(kwargs)
        return self.latest_requests

    async def reconcile_affected_buckets(self, **kwargs: Any):
        self.affected_calls.append(kwargs)
        return self.affected_requests

    async def process_base_candle(self, candle: CanonicalCandle, **kwargs: Any):
        self.live_calls.append({"candle": candle, **kwargs})
        return self.live_requests


class BlockingStream:
    def __init__(
        self,
        *,
        observations: tuple[CandleObservation, ...] = (),
        interruption: BaseException | None = None,
    ) -> None:
        self.observations = list(observations)
        self.interruption = interruption
        self.closed = False
        self.paused = False
        self.close_started = asyncio.Event()
        self.close_finished = asyncio.Event()
        self.release = asyncio.Event()

    def __aiter__(self) -> BlockingStream:
        return self

    async def __anext__(self) -> CandleObservation:
        if self.observations:
            return self.observations.pop(0)
        if self.interruption is not None:
            error = self.interruption
            self.interruption = None
            raise error
        await self.release.wait()
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.close_started.set()
        self.closed = True
        self.release.set()
        self.close_finished.set()


class ControlledLiveProvider:
    provider_id = "binance_native"

    def __init__(self, streams: list[BlockingStream] | None = None) -> None:
        self.streams = list(streams or [])
        self.calls: list[dict[MarketLane, str]] = []
        self.stream_kwargs: list[dict[str, Any]] = []
        self.created_streams: list[BlockingStream] = []

    def stream_closed_candles(
        self,
        subscriptions: Mapping[MarketLane, str],
        **kwargs: Any,
    ) -> BlockingStream:
        self.calls.append(dict(subscriptions))
        self.stream_kwargs.append(dict(kwargs))
        stream = self.streams.pop(0) if self.streams else BlockingStream()
        self.created_streams.append(stream)
        return stream


class RecordingRecovery:
    def __init__(
        self,
        *,
        update_latest: Callable[[RecoveryRequest], None] | None = None,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.calls: list[RecoveryRequest] = []
        self.update_latest = update_latest
        self.gate = gate
        self.active = 0
        self.max_active = 0

    async def recover(self, request: RecoveryRequest, **kwargs: Any):
        del kwargs
        self.calls.append(request)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.gate is not None:
                await self.gate.wait()
            if self.update_latest is not None:
                self.update_latest(request)
            return ()
        finally:
            self.active -= 1


class FakeSupervisor:
    """Small controller-only supervisor; it never allocates external resources."""

    def __init__(
        self, settings: IngestionSettings, records: list[FakeSupervisor]
    ) -> None:
        self.settings = settings
        self.records = records
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False
        self.run_calls = 0
        self.stop_calls = 0
        records.append(self)

    async def run(self) -> None:
        self.run_calls += 1
        self.started.set()
        await self.release.wait()

    def stop(self) -> None:
        self.stop_calls += 1
        self.closed = True
        self.release.set()

    def pause(self) -> None:
        self.paused = True
        self.closed = True
        self.release.set()

    def resume(self) -> None:
        self.paused = False
        self.closed = False
        self.release.clear()

    def snapshot(self) -> RuntimeSnapshot:
        state = RuntimeState.STOPPED if self.closed else RuntimeState.LIVE
        return RuntimeSnapshot(
            desired_state=DesiredRuntimeState.RUNNING,
            state=state,
            last_error=None,
        )

    async def execute_recovery(self, request: RecoveryRequest) -> None:
        del request


class FakeSDKClient:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.subscribe_calls: list[list[str]] = []
        self.stop_calls = 0

    def subscribe(self, streams: list[str]) -> None:
        self.subscribe_calls.append(list(streams))

    def stop(self) -> None:
        self.stop_calls += 1

    def emit(self, message: object) -> None:
        self.kwargs["on_message"](self, message)

    def emit_from_thread(self, message: object) -> None:
        self.kwargs["on_message"](self, message)


class FakeHistoricalProvider:
    def __init__(
        self,
        provider_id: str,
        handler: Callable[[MarketLane, datetime, datetime], Any],
        meter: ActiveMeter | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.handler = handler
        self.meter = meter
        self.calls: list[tuple[MarketLane, datetime, datetime]] = []
        self.active = 0
        self.max_active = 0
        self.active_by_lane: dict[MarketLane, int] = defaultdict(int)
        self.max_active_by_lane: dict[MarketLane, int] = defaultdict(int)

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
        del provider_symbol, timeframe_duration, limit
        self.calls.append((lane, since, until))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.active_by_lane[lane] += 1
        self.max_active_by_lane[lane] = max(
            self.max_active_by_lane[lane],
            self.active_by_lane[lane],
        )
        try:
            if self.meter is not None:
                await self.meter.enter()
            else:
                await asyncio.sleep(0)
            result = self.handler(lane, since, until)
            if isinstance(result, BaseException):
                raise result
            return tuple(result)
        finally:
            if self.meter is not None:
                await self.meter.exit()
            self.active_by_lane[lane] -= 1
            self.active -= 1


class ActiveMeter:
    def __init__(
        self,
        *,
        target: int | None = None,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.active = 0
        self.maximum = 0
        self.target = target
        self.ready = asyncio.Event()
        self.gate = gate

    async def enter(self) -> None:
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        if self.target is not None and self.active >= self.target:
            self.ready.set()
        if self.gate is not None:
            await self.gate.wait()

    async def exit(self) -> None:
        self.active -= 1


def event_for(index: int, *, instrument_id: str | None = None) -> OutboxEvent:
    instrument = instrument_id or f"SYN{index:04d}-USDT-PERP"
    payload = {
        "close": str(index),
        "instrument_id": instrument,
        "open": str(index),
        "timeframe": "1m",
        "venue": "binance",
    }
    return OutboxEvent(
        event_id=uuid5(UUID("00000000-0000-0000-0000-000000000001"), str(index)),
        event_type="candle.committed",
        schema_version=1,
        producer="ingestion",
        occurred_at=datetime(2026, 8, 10, 10, 0, tzinfo=UTC),
        payload_json=json.dumps(payload, separators=(",", ":"), sort_keys=True),
    )


class FakeOutboxRepository:
    def __init__(self, events: list[OutboxEvent]) -> None:
        self.pending = list(events)
        self.fetch_limits: list[int] = []
        self.marked: list[UUID] = []
        self.fetch_calls = 0

    async def fetch_pending_outbox(self, *, limit: int) -> tuple[OutboxEvent, ...]:
        self.fetch_calls += 1
        self.fetch_limits.append(limit)
        return tuple(self.pending[:limit])

    async def mark_outbox_published(
        self,
        *,
        event_id: UUID,
        published_at: datetime,
    ) -> bool:
        del published_at
        self.marked.append(event_id)
        self.pending = [event for event in self.pending if event.event_id != event_id]
        return True


class FakeValkey:
    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.fail_on_call = fail_on_call
        self.calls: list[tuple[str, dict[str, str], int, bool]] = []

    async def xadd(
        self,
        name: str,
        fields: dict[str, str],
        *,
        maxlen: int,
        approximate: bool,
    ) -> str:
        call_number = len(self.calls) + 1
        if self.fail_on_call == call_number:
            raise ConnectionError("synthetic Valkey failure")
        self.calls.append((name, fields, maxlen, approximate))
        return f"{call_number}-0"


async def yield_control() -> None:
    await asyncio.sleep(0)


def minute_rows(
    lane: MarketLane,
    since: datetime,
    until: datetime,
    *,
    value: int = 100,
    provider_id: str = "binance_native",
    transport: str = "rest",
) -> tuple[CanonicalCandle, ...]:
    rows: list[CanonicalCandle] = []
    open_time = since
    offset = 0
    while open_time < until:
        rows.append(
            canonical(
                observation(
                    lane,
                    open_time,
                    provider_id=provider_id,
                    transport=transport,
                    value=value + offset,
                )
            )
        )
        open_time += BASE_DURATION
        offset += 1
    return tuple(rows)


def direct_base_rows(
    lane: MarketLane,
    since: datetime,
    until: datetime,
) -> tuple[CanonicalCandle, ...]:
    return minute_rows(lane, since, until)
