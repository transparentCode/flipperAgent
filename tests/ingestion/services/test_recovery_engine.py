from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

import apps.ingestion_app.services.recovery as recovery_module
from apps.ingestion_app.domain.candle import CandleObservation, CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.services.recovery import RecoveryEngine
from apps.ingestion_app.services.time_alignment import aligned_bucket_start
from apps.ingestion_app.storage.repository import CandleCommitStatus
from libs.common.exceptions import DataIngestionError

ORIGIN = datetime(1970, 1, 5, tzinfo=UTC)
MINUTE = timedelta(minutes=1)
LANE = MarketLane("binance", "BTC-RECOVERY-TEST-PERP", "1m")
OTHER_LANE = MarketLane("binance", "ETH-RECOVERY-TEST-PERP", "1m")


def _observation(
    open_time: datetime,
    *,
    lane: MarketLane = LANE,
    provider_id: str = "binance_native",
) -> CandleObservation:
    return CandleObservation(
        lane=lane,
        provider_id=provider_id,
        provider_symbol="BTCUSDT",
        transport="rest",
        open_time=open_time,
        close_time=open_time + MINUTE,
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal(100),
        volume=Decimal(1),
        taker_buy_base=Decimal(1),
        received_at=open_time + MINUTE,
        provider_close_time=None,
        provider_event_id=None,
    )


def _canonical(observation: CandleObservation) -> CanonicalCandle:
    return CanonicalCandle(
        lane=observation.lane,
        open_time=observation.open_time,
        close_time=observation.close_time,
        open=observation.open,
        high=observation.high,
        low=observation.low,
        close=observation.close,
        volume=observation.volume,
        taker_buy_base=observation.taker_buy_base,
        source_type="provider",
        source_provider=observation.provider_id,
        source_timeframe=None,
    )


def _rows(
    since: datetime,
    until: datetime,
    *,
    lane: MarketLane = LANE,
    provider_id: str = "binance_native",
) -> tuple[CandleObservation, ...]:
    result = []
    open_time = since
    while open_time < until:
        result.append(_observation(open_time, lane=lane, provider_id=provider_id))
        open_time += MINUTE
    return tuple(result)


class _Repository:
    def __init__(self, candles: tuple[CanonicalCandle, ...] = ()) -> None:
        self.rows: dict[tuple[MarketLane, datetime], CanonicalCandle] = {
            (candle.lane, candle.open_time): candle for candle in candles
        }
        self.overrides: dict[
            tuple[MarketLane, datetime, datetime], tuple[CanonicalCandle, ...]
        ] = {}
        self.calls: list[tuple[MarketLane, datetime, datetime]] = []

    def add(self, candle: CanonicalCandle) -> None:
        self.rows[(candle.lane, candle.open_time)] = candle

    async def fetch_candles(
        self,
        *,
        lane: MarketLane,
        since: datetime,
        until: datetime,
    ) -> tuple[CanonicalCandle, ...]:
        self.calls.append((lane, since, until))
        override_key = (lane, since, until)
        if override_key in self.overrides:
            return self.overrides[override_key]
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


class _Ingestion:
    def __init__(
        self,
        repository: _Repository,
        *,
        conflict: bool = False,
    ) -> None:
        self.repository = repository
        self.conflict = conflict
        self.committed: list[CandleObservation] = []

    async def commit_observation(
        self,
        observation: CandleObservation,
    ) -> CandleCommitStatus:
        self.committed.append(observation)
        if self.conflict:
            return CandleCommitStatus.CONFLICT
        key = (observation.lane, observation.open_time)
        if key in self.repository.rows:
            return CandleCommitStatus.DUPLICATE
        self.repository.add(_canonical(observation))
        return CandleCommitStatus.INSERTED


class _HTF:
    def __init__(
        self,
        responses: tuple[RecoveryRequest, ...] = (),
        exception: BaseException | None = None,
    ) -> None:
        self.responses = responses
        self.exception = exception
        self.calls: list[dict[str, Any]] = []

    async def reconcile_affected_buckets(
        self, **kwargs: Any
    ) -> tuple[RecoveryRequest, ...]:
        self.calls.append(kwargs)
        if self.exception is not None:
            raise self.exception
        return self.responses


class _ScriptedProvider:
    def __init__(self, provider_id: str, responses: list[object]) -> None:
        self.provider_id = provider_id
        self.responses = responses
        self.calls: list[tuple[MarketLane, datetime, datetime, int]] = []

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
        del provider_symbol, timeframe_duration
        self.calls.append((lane, since, until, limit))
        response = self.responses.pop(0) if self.responses else ()
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            return response(lane=lane, since=since, until=until)
        return response  # type: ignore[return-value]


class _LaneBlockingProvider(_ScriptedProvider):
    def __init__(self) -> None:
        super().__init__("binance_native", [])
        self.started_events = [asyncio.Event() for _ in range(3)]
        self.release_events = [asyncio.Event() for _ in range(3)]
        self.started_count = 0
        self.active = 0
        self.max_active = 0

    async def fetch_closed_candles(
        self, **kwargs: Any
    ) -> tuple[CandleObservation, ...]:
        call_index = self.started_count
        self.started_count += 1
        self.calls.append(
            (kwargs["lane"], kwargs["since"], kwargs["until"], kwargs["limit"])
        )
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.started_events[call_index].set()
        try:
            await self.release_events[call_index].wait()
            return _rows(
                kwargs["since"],
                kwargs["until"],
                lane=kwargs["lane"],
            )
        finally:
            self.active -= 1


def _engine(
    repository: _Repository,
    ingestion: _Ingestion,
    htf: _HTF,
    providers: dict[str, _ScriptedProvider],
    *,
    max_concurrency: int = 1,
    page_limit: int = 500,
    max_attempts: int = 1,
    backoff: int = 0,
    rest_finalization_grace: int = 0,
    now_fn: Any = None,
    settlement_sleep_fn: Any = None,
) -> RecoveryEngine:
    return RecoveryEngine(
        providers=providers,  # type: ignore[arg-type]
        repository=repository,  # type: ignore[arg-type]
        ingestion_service=ingestion,  # type: ignore[arg-type]
        htf_service=htf,  # type: ignore[arg-type]
        max_concurrency=max_concurrency,
        page_limit=page_limit,
        max_attempts_per_provider=max_attempts,
        retry_backoff_seconds=backoff,
        rest_finalization_grace_seconds=rest_finalization_grace,
        now_fn=now_fn,
        settlement_sleep_fn=settlement_sleep_fn,
    )


def _request(
    since: datetime,
    until: datetime,
    *,
    lane: MarketLane = LANE,
) -> RecoveryRequest:
    return RecoveryRequest(lane=lane, since=since, until=until, reason="test")


async def _wait_for_lane_users(
    engine: RecoveryEngine,
    expected: int,
) -> object:
    for _ in range(100):
        entry = engine._lane_locks.get(LANE)
        if entry is not None and entry.users == expected:
            return entry
        await asyncio.sleep(0)
    raise AssertionError(f"lane lock users did not reach {expected}")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_concurrency", 0),
        ("page_limit", False),
        ("max_attempts_per_provider", -1),
        ("retry_backoff_seconds", "1"),
        ("rest_finalization_grace_seconds", -1),
    ],
)
def test_engine_limits_reject_invalid_values(field: str, value: object) -> None:
    kwargs: dict[str, object] = {
        "max_concurrency": 1,
        "page_limit": 2,
        "max_attempts_per_provider": 1,
        "retry_backoff_seconds": 0,
        "rest_finalization_grace_seconds": 0,
    }
    kwargs[field] = value
    with pytest.raises((TypeError, ValueError)):
        RecoveryEngine(
            providers={},  # type: ignore[arg-type]
            repository=object(),  # type: ignore[arg-type]
            ingestion_service=object(),  # type: ignore[arg-type]
            htf_service=object(),  # type: ignore[arg-type]
            **kwargs,  # type: ignore[arg-type]
        )


def test_effective_until_excludes_forming_base_candle() -> None:
    started = datetime(2026, 1, 1, 0, 2, 30, tzinfo=UTC)

    effective_until = recovery_module._effective_until(
        until=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
        base_duration=MINUTE,
        alignment_origin=ORIGIN,
        request_started_at=started,
    )

    assert effective_until == datetime(2026, 1, 1, 0, 2, tzinfo=UTC)


@pytest.mark.asyncio
async def test_paging_uses_exact_non_overlapping_time_windows() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = since + 5 * MINUTE
    repository = _Repository()
    ingestion = _Ingestion(repository)
    htf = _HTF()
    provider = _ScriptedProvider(
        "binance_native",
        [lambda **kwargs: _rows(kwargs["since"], kwargs["until"]) for _ in range(3)],
    )
    engine = _engine(
        repository,
        ingestion,
        htf,
        {"binance_native": provider},
        page_limit=2,
    )

    assert (
        await engine.recover(
            _request(since, until),
            base_timeframe="1m",
            base_duration=MINUTE,
            provider_order=("binance_native",),
            provider_symbols={"binance_native": "BTCUSDT"},
            target_durations={},
            alignment_origin=ORIGIN,
        )
        == ()
    )

    assert [(call[1], call[2]) for call in provider.calls] == [
        (since, since + 2 * MINUTE),
        (since + 2 * MINUTE, since + 4 * MINUTE),
        (since + 4 * MINUTE, until),
    ]
    assert len(repository.rows) == 5
    assert len(htf.calls) == 1


@pytest.mark.asyncio
async def test_complete_page_skips_provider_but_reconciles_htf() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = since + 2 * MINUTE
    observations = _rows(since, until)
    repository = _Repository(
        tuple(_canonical(observation) for observation in observations)
    )
    ingestion = _Ingestion(repository)
    htf = _HTF()
    provider = _ScriptedProvider("binance_native", [])
    engine = _engine(repository, ingestion, htf, {"binance_native": provider})

    await engine.recover(
        _request(since, until),
        base_timeframe="1m",
        base_duration=MINUTE,
        provider_order=("binance_native",),
        provider_symbols={"binance_native": "BTCUSDT"},
        target_durations={},
        alignment_origin=ORIGIN,
    )

    assert provider.calls == []
    assert ingestion.committed == []
    assert len(htf.calls) == 1


@pytest.mark.asyncio
async def test_recent_incomplete_page_waits_until_rest_settlement() -> None:
    now = datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)
    page_end = datetime(2026, 1, 1, tzinfo=UTC)
    sleep_calls: list[float] = []

    async def settlement_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    provider = _ScriptedProvider(
        "binance_native",
        [lambda **kwargs: _rows(kwargs["since"], kwargs["until"])],
    )
    repository = _Repository()
    engine = _engine(
        repository,
        _Ingestion(repository),
        _HTF(),
        {"binance_native": provider},
        rest_finalization_grace=5,
        now_fn=lambda: now,
        settlement_sleep_fn=settlement_sleep,
    )

    await engine.recover(
        _request(page_end - MINUTE, page_end),
        base_timeframe="1m",
        base_duration=MINUTE,
        provider_order=("binance_native",),
        provider_symbols={"binance_native": "BTCUSDT"},
        target_durations={},
        alignment_origin=ORIGIN,
    )

    assert sleep_calls == [4.0]
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_historical_incomplete_page_has_no_settlement_wait() -> None:
    now = datetime(2026, 1, 2, tzinfo=UTC)
    page_end = datetime(2026, 1, 1, tzinfo=UTC)
    sleep_calls: list[float] = []

    async def settlement_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    provider = _ScriptedProvider(
        "binance_native",
        [lambda **kwargs: _rows(kwargs["since"], kwargs["until"])],
    )
    repository = _Repository()
    engine = _engine(
        repository,
        _Ingestion(repository),
        _HTF(),
        {"binance_native": provider},
        rest_finalization_grace=5,
        now_fn=lambda: now,
        settlement_sleep_fn=settlement_sleep,
    )

    await engine.recover(
        _request(page_end - MINUTE, page_end),
        base_timeframe="1m",
        base_duration=MINUTE,
        provider_order=("binance_native",),
        provider_symbols={"binance_native": "BTCUSDT"},
        target_durations={},
        alignment_origin=ORIGIN,
    )

    assert sleep_calls == []
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_complete_recent_page_skips_settlement_wait() -> None:
    now = datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)
    page_end = datetime(2026, 1, 1, tzinfo=UTC)
    observations = _rows(page_end - MINUTE, page_end)
    sleep_calls: list[float] = []

    async def settlement_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    repository = _Repository(tuple(_canonical(row) for row in observations))
    provider = _ScriptedProvider("binance_native", [])
    engine = _engine(
        repository,
        _Ingestion(repository),
        _HTF(),
        {"binance_native": provider},
        rest_finalization_grace=5,
        now_fn=lambda: now,
        settlement_sleep_fn=settlement_sleep,
    )

    await engine.recover(
        _request(page_end - MINUTE, page_end),
        base_timeframe="1m",
        base_duration=MINUTE,
        provider_order=("binance_native",),
        provider_symbols={"binance_native": "BTCUSDT"},
        target_durations={},
        alignment_origin=ORIGIN,
    )

    assert sleep_calls == []
    assert provider.calls == []


@pytest.mark.asyncio
async def test_cancellation_during_settlement_wait_prevents_provider_request() -> None:
    now = datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)
    page_end = datetime(2026, 1, 1, tzinfo=UTC)
    sleep_started = asyncio.Event()

    async def settlement_sleep(_delay: float) -> None:
        sleep_started.set()
        await asyncio.Event().wait()

    repository = _Repository()
    provider = _ScriptedProvider("binance_native", [])
    engine = _engine(
        repository,
        _Ingestion(repository),
        _HTF(),
        {"binance_native": provider},
        rest_finalization_grace=5,
        now_fn=lambda: now,
        settlement_sleep_fn=settlement_sleep,
    )
    task = asyncio.create_task(
        engine.recover(
            _request(page_end - MINUTE, page_end),
            base_timeframe="1m",
            base_duration=MINUTE,
            provider_order=("binance_native",),
            provider_symbols={"binance_native": "BTCUSDT"},
            target_durations={},
            alignment_origin=ORIGIN,
        )
    )
    await sleep_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert provider.calls == []


@pytest.mark.asyncio
async def test_primary_provider_success_does_not_call_fallback() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = since + 2 * MINUTE
    primary = _ScriptedProvider(
        "binance_native",
        [lambda **kwargs: _rows(kwargs["since"], kwargs["until"])],
    )
    fallback = _ScriptedProvider("ccxt_binance", [])
    repository = _Repository()
    ingestion = _Ingestion(repository)
    engine = _engine(
        repository,
        ingestion,
        _HTF(),
        {"binance_native": primary, "ccxt_binance": fallback},
    )

    await engine.recover(
        _request(since, until),
        base_timeframe="1m",
        base_duration=MINUTE,
        provider_order=("binance_native", "ccxt_binance"),
        provider_symbols={"binance_native": "BTCUSDT", "ccxt_binance": "BTC/USDT:USDT"},
        target_durations={},
        alignment_origin=ORIGIN,
    )

    assert len(primary.calls) == 1
    assert fallback.calls == []
    assert {candle.source_provider for candle in repository.rows.values()} == {
        "binance_native"
    }


@pytest.mark.asyncio
async def test_primary_failures_are_bounded_before_fallback() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = since + 2 * MINUTE
    primary = _ScriptedProvider(
        "binance_native",
        [DataIngestionError("primary failure"), DataIngestionError("primary failure")],
    )
    fallback = _ScriptedProvider(
        "ccxt_binance",
        [
            lambda **kwargs: _rows(
                kwargs["since"], kwargs["until"], provider_id="ccxt_binance"
            )
        ],
    )
    repository = _Repository()
    ingestion = _Ingestion(repository)
    engine = _engine(
        repository,
        ingestion,
        _HTF(),
        {"binance_native": primary, "ccxt_binance": fallback},
        max_attempts=2,
    )

    await engine.recover(
        _request(since, until),
        base_timeframe="1m",
        base_duration=MINUTE,
        provider_order=("binance_native", "ccxt_binance"),
        provider_symbols={"binance_native": "BTCUSDT", "ccxt_binance": "BTC/USDT:USDT"},
        target_durations={},
        alignment_origin=ORIGIN,
    )

    assert len(primary.calls) == 2
    assert len(fallback.calls) == 1
    assert {candle.source_provider for candle in repository.rows.values()} == {
        "ccxt_binance"
    }


@pytest.mark.asyncio
async def test_partial_primary_result_is_completed_by_fallback() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = since + 4 * MINUTE
    primary = _ScriptedProvider(
        "binance_native",
        [lambda **kwargs: _rows(kwargs["since"], kwargs["since"] + MINUTE)],
    )
    fallback = _ScriptedProvider(
        "ccxt_binance",
        [
            lambda **kwargs: _rows(
                kwargs["since"], kwargs["until"], provider_id="ccxt_binance"
            )
        ],
    )
    repository = _Repository()
    ingestion = _Ingestion(repository)
    engine = _engine(
        repository,
        ingestion,
        _HTF(),
        {"binance_native": primary, "ccxt_binance": fallback},
    )

    await engine.recover(
        _request(since, until),
        base_timeframe="1m",
        base_duration=MINUTE,
        provider_order=("binance_native", "ccxt_binance"),
        provider_symbols={"binance_native": "BTCUSDT", "ccxt_binance": "BTC/USDT:USDT"},
        target_durations={},
        alignment_origin=ORIGIN,
    )

    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1
    assert len(repository.rows) == 4
    assert repository.rows[(LANE, since)].source_provider == "binance_native"
    assert repository.rows[(LANE, since + MINUTE)].source_provider == "ccxt_binance"


@pytest.mark.asyncio
async def test_provider_exhaustion_raises_with_missing_count() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = since + 2 * MINUTE
    primary = _ScriptedProvider("binance_native", [()])
    fallback = _ScriptedProvider("ccxt_binance", [()])
    repository = _Repository()
    engine = _engine(
        repository,
        _Ingestion(repository),
        _HTF(),
        {"binance_native": primary, "ccxt_binance": fallback},
    )

    with pytest.raises(DataIngestionError, match="missing 2 candles"):
        await engine.recover(
            _request(since, until),
            base_timeframe="1m",
            base_duration=MINUTE,
            provider_order=("binance_native", "ccxt_binance"),
            provider_symbols={
                "binance_native": "BTCUSDT",
                "ccxt_binance": "BTC/USDT:USDT",
            },
            target_durations={},
            alignment_origin=ORIGIN,
        )
    assert engine._lane_locks == {}


@pytest.mark.asyncio
async def test_canonical_conflict_stops_without_fallback() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = since + MINUTE
    primary = _ScriptedProvider(
        "binance_native",
        [lambda **kwargs: _rows(kwargs["since"], kwargs["until"])],
    )
    fallback = _ScriptedProvider("ccxt_binance", [])
    repository = _Repository()
    engine = _engine(
        repository,
        _Ingestion(repository, conflict=True),
        _HTF(),
        {"binance_native": primary, "ccxt_binance": fallback},
    )

    with pytest.raises(DataIngestionError, match="canonical recovery conflict"):
        await engine.recover(
            _request(since, until),
            base_timeframe="1m",
            base_duration=MINUTE,
            provider_order=("binance_native", "ccxt_binance"),
            provider_symbols={
                "binance_native": "BTCUSDT",
                "ccxt_binance": "BTC/USDT:USDT",
            },
            target_durations={},
            alignment_origin=ORIGIN,
        )
    assert fallback.calls == []
    assert engine._lane_locks == {}


@pytest.mark.parametrize(
    "malformed",
    [
        _observation(datetime(2026, 1, 1, tzinfo=UTC), lane=OTHER_LANE),
        replace(
            _observation(datetime(2026, 1, 1, tzinfo=UTC)),
            provider_id="ccxt_binance",
        ),
        _observation(datetime(2025, 12, 31, 23, 59, tzinfo=UTC)),
        replace(
            _observation(datetime(2026, 1, 1, tzinfo=UTC)),
            close_time=datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
        ),
        _observation(datetime(2026, 1, 1, 0, 0, 30, tzinfo=UTC)),
    ],
)
@pytest.mark.asyncio
async def test_provider_contract_violation_fails_closed(
    malformed: CandleObservation,
) -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = since + MINUTE
    provider = _ScriptedProvider("binance_native", [(malformed,)])
    repository = _Repository()
    engine = _engine(
        repository, _Ingestion(repository), _HTF(), {"binance_native": provider}
    )

    with pytest.raises(DataIngestionError):
        await engine.recover(
            _request(since, until),
            base_timeframe="1m",
            base_duration=MINUTE,
            provider_order=("binance_native",),
            provider_symbols={"binance_native": "BTCUSDT"},
            target_durations={},
            alignment_origin=ORIGIN,
        )
    assert engine._lane_locks == {}


@pytest.mark.asyncio
async def test_future_only_request_does_no_storage_or_provider_work() -> None:
    future_since = aligned_bucket_start(datetime.now(UTC), MINUTE, ORIGIN) + timedelta(
        days=1
    )
    repository = _Repository()
    htf = _HTF()
    provider = _ScriptedProvider("binance_native", [])
    engine = _engine(
        repository, _Ingestion(repository), htf, {"binance_native": provider}
    )

    assert (
        await engine.recover(
            _request(future_since, future_since + MINUTE),
            base_timeframe="1m",
            base_duration=MINUTE,
            provider_order=("binance_native",),
            provider_symbols={"binance_native": "BTCUSDT"},
            target_durations={},
            alignment_origin=ORIGIN,
        )
        == ()
    )
    assert provider.calls == []
    assert repository.calls == []
    assert htf.calls == []


@pytest.mark.asyncio
async def test_unaligned_historical_until_fails_before_network() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = since + MINUTE + timedelta(seconds=30)
    repository = _Repository()
    provider = _ScriptedProvider("binance_native", [])
    engine = _engine(
        repository, _Ingestion(repository), _HTF(), {"binance_native": provider}
    )

    with pytest.raises(DataIngestionError, match="aligned"):
        await engine.recover(
            _request(since, until),
            base_timeframe="1m",
            base_duration=MINUTE,
            provider_order=("binance_native",),
            provider_symbols={"binance_native": "BTCUSDT"},
            target_durations={},
            alignment_origin=ORIGIN,
        )
    assert provider.calls == []
    assert repository.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_order", "provider_symbols", "providers"),
    [
        ((), {"binance_native": "BTCUSDT"}, {"binance_native": "binance_native"}),
        (("binance_native",), {}, {"binance_native": "binance_native"}),
        (
            ("binance_native",),
            {"binance_native": "BTCUSDT"},
            {"binance_native": "wrong_provider_id"},
        ),
    ],
)
async def test_provider_routes_fail_before_network(
    provider_order: tuple[str, ...],
    provider_symbols: dict[str, str],
    providers: dict[str, str],
) -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = since + MINUTE
    repository = _Repository()
    ingestion = _Ingestion(repository)
    provider_objects = {
        key: _ScriptedProvider(value, []) for key, value in providers.items()
    }
    engine = _engine(repository, ingestion, _HTF(), provider_objects)

    with pytest.raises(DataIngestionError):
        await engine.recover(
            _request(since, until),
            base_timeframe="1m",
            base_duration=MINUTE,
            provider_order=provider_order,
            provider_symbols=provider_symbols,
            target_durations={},
            alignment_origin=ORIGIN,
        )
    assert repository.calls == []
    assert ingestion.committed == []


@pytest.mark.asyncio
async def test_non_base_request_is_rejected_before_network() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = since + MINUTE
    provider = _ScriptedProvider("binance_native", [])
    repository = _Repository()
    engine = _engine(
        repository, _Ingestion(repository), _HTF(), {"binance_native": provider}
    )

    with pytest.raises(DataIngestionError, match="base timeframe"):
        await engine.recover(
            _request(since, until, lane=MarketLane("binance", "BTC-TEST", "15m")),
            base_timeframe="1m",
            base_duration=MINUTE,
            provider_order=("binance_native",),
            provider_symbols={"binance_native": "BTCUSDT"},
            target_durations={},
            alignment_origin=ORIGIN,
        )
    assert provider.calls == []
    assert repository.calls == []


@pytest.mark.asyncio
async def test_follow_up_requests_are_deduplicated_without_recursion() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = since + MINUTE
    follow_up = RecoveryRequest(
        lane=LANE,
        since=since,
        until=until,
        reason="htf_incomplete:15m",
    )
    provider = _ScriptedProvider(
        "binance_native",
        [lambda **kwargs: _rows(kwargs["since"], kwargs["until"])],
    )
    repository = _Repository()
    htf = _HTF((follow_up, follow_up))
    engine = _engine(
        repository, _Ingestion(repository), htf, {"binance_native": provider}
    )

    result = await engine.recover(
        _request(since, until),
        base_timeframe="1m",
        base_duration=MINUTE,
        provider_order=("binance_native",),
        provider_symbols={"binance_native": "BTCUSDT"},
        target_durations={},
        alignment_origin=ORIGIN,
    )

    assert result == (follow_up,)
    assert len(htf.calls) == 1
    assert engine._lane_locks == {}


@pytest.mark.asyncio
async def test_provider_failure_reclaims_lane_lock_entry() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = since + MINUTE
    provider = _ScriptedProvider(
        "binance_native",
        [DataIngestionError("provider failed")],
    )
    repository = _Repository()
    engine = _engine(
        repository,
        _Ingestion(repository),
        _HTF(),
        {"binance_native": provider},
    )

    with pytest.raises(DataIngestionError, match="recovery exhausted"):
        await engine.recover(
            _request(since, until),
            base_timeframe="1m",
            base_duration=MINUTE,
            provider_order=("binance_native",),
            provider_symbols={"binance_native": "BTCUSDT"},
            target_durations={},
            alignment_origin=ORIGIN,
        )

    assert engine._lane_locks == {}


@pytest.mark.asyncio
async def test_htf_exception_reclaims_lane_lock_entry() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = since + MINUTE
    provider = _ScriptedProvider(
        "binance_native",
        [lambda **kwargs: _rows(kwargs["since"], kwargs["until"])],
    )
    repository = _Repository()
    engine = _engine(
        repository,
        _Ingestion(repository),
        _HTF(exception=DataIngestionError("HTF failed")),
        {"binance_native": provider},
    )

    with pytest.raises(DataIngestionError, match="HTF failed"):
        await engine.recover(
            _request(since, until),
            base_timeframe="1m",
            base_duration=MINUTE,
            provider_order=("binance_native",),
            provider_symbols={"binance_native": "BTCUSDT"},
            target_durations={},
            alignment_origin=ORIGIN,
        )

    assert engine._lane_locks == {}


@pytest.mark.asyncio
async def test_waiters_keep_one_lane_entry_until_all_same_lane_work_finishes() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    provider = _LaneBlockingProvider()
    repository = _Repository()
    engine = _engine(
        repository,
        _Ingestion(repository),
        _HTF(),
        {"binance_native": provider},
    )
    kwargs = {
        "base_timeframe": "1m",
        "base_duration": MINUTE,
        "provider_order": ("binance_native",),
        "provider_symbols": {"binance_native": "BTCUSDT"},
        "target_durations": {},
        "alignment_origin": ORIGIN,
    }

    first = asyncio.create_task(
        engine.recover(_request(since, since + MINUTE), **kwargs)
    )
    await provider.started_events[0].wait()
    second = asyncio.create_task(
        engine.recover(_request(since + MINUTE, since + 2 * MINUTE), **kwargs)
    )
    entry = await _wait_for_lane_users(engine, 2)

    provider.release_events[0].set()
    await provider.started_events[1].wait()
    third = asyncio.create_task(
        engine.recover(_request(since + 2 * MINUTE, since + 3 * MINUTE), **kwargs)
    )
    assert await _wait_for_lane_users(engine, 2) is entry
    assert not provider.started_events[2].is_set()
    assert provider.max_active == 1

    provider.release_events[1].set()
    await provider.started_events[2].wait()
    assert provider.max_active == 1
    provider.release_events[2].set()
    await asyncio.gather(first, second, third)

    assert provider.max_active == 1
    assert engine._lane_locks == {}


@pytest.mark.asyncio
async def test_waiting_task_cancellation_keeps_lane_entry_for_active_and_next_task() -> (
    None
):
    since = datetime(2026, 1, 1, tzinfo=UTC)
    provider = _LaneBlockingProvider()
    repository = _Repository()
    engine = _engine(
        repository,
        _Ingestion(repository),
        _HTF(),
        {"binance_native": provider},
    )
    kwargs = {
        "base_timeframe": "1m",
        "base_duration": MINUTE,
        "provider_order": ("binance_native",),
        "provider_symbols": {"binance_native": "BTCUSDT"},
        "target_durations": {},
        "alignment_origin": ORIGIN,
    }

    first = asyncio.create_task(
        engine.recover(_request(since, since + MINUTE), **kwargs)
    )
    await provider.started_events[0].wait()
    waiting = asyncio.create_task(
        engine.recover(_request(since + MINUTE, since + 2 * MINUTE), **kwargs)
    )
    entry = await _wait_for_lane_users(engine, 2)

    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert engine._lane_locks.get(LANE) is entry
    assert entry.users == 1

    next_task = asyncio.create_task(
        engine.recover(_request(since + MINUTE, since + 2 * MINUTE), **kwargs)
    )
    assert await _wait_for_lane_users(engine, 2) is entry
    assert not provider.started_events[1].is_set()

    provider.release_events[0].set()
    await provider.started_events[1].wait()
    assert provider.max_active == 1
    provider.release_events[1].set()
    await asyncio.gather(first, next_task)

    assert engine._lane_locks == {}


@pytest.mark.asyncio
async def test_holder_cancellation_releases_lane_for_existing_waiter() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    provider = _LaneBlockingProvider()
    repository = _Repository()
    engine = _engine(
        repository,
        _Ingestion(repository),
        _HTF(),
        {"binance_native": provider},
    )
    kwargs = {
        "base_timeframe": "1m",
        "base_duration": MINUTE,
        "provider_order": ("binance_native",),
        "provider_symbols": {"binance_native": "BTCUSDT"},
        "target_durations": {},
        "alignment_origin": ORIGIN,
    }

    holder = asyncio.create_task(
        engine.recover(_request(since, since + MINUTE), **kwargs)
    )
    await provider.started_events[0].wait()
    waiter = asyncio.create_task(
        engine.recover(_request(since + MINUTE, since + 2 * MINUTE), **kwargs)
    )
    entry = await _wait_for_lane_users(engine, 2)

    holder.cancel()
    with pytest.raises(asyncio.CancelledError):
        await holder
    await provider.started_events[1].wait()
    assert engine._lane_locks.get(LANE) is entry
    assert provider.max_active == 1

    provider.release_events[1].set()
    await waiter

    assert engine._lane_locks == {}


@pytest.mark.asyncio
async def test_same_lane_recoveries_are_serialized() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = since + MINUTE

    class _BlockingProvider(_ScriptedProvider):
        def __init__(self) -> None:
            super().__init__("binance_native", [])
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.active = 0
            self.max_active = 0

        async def fetch_closed_candles(
            self, **kwargs: Any
        ) -> tuple[CandleObservation, ...]:
            self.calls.append(
                (kwargs["lane"], kwargs["since"], kwargs["until"], kwargs["limit"])
            )
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.started.set()
            try:
                await self.release.wait()
                return _rows(kwargs["since"], kwargs["until"])
            finally:
                self.active -= 1

    repository = _Repository()
    ingestion = _Ingestion(repository)
    provider = _BlockingProvider()
    engine = _engine(repository, ingestion, _HTF(), {"binance_native": provider})
    kwargs = {
        "base_timeframe": "1m",
        "base_duration": MINUTE,
        "provider_order": ("binance_native",),
        "provider_symbols": {"binance_native": "BTCUSDT"},
        "target_durations": {},
        "alignment_origin": ORIGIN,
    }

    first = asyncio.create_task(engine.recover(_request(since, until), **kwargs))
    await provider.started.wait()
    second = asyncio.create_task(engine.recover(_request(since, until), **kwargs))
    await asyncio.sleep(0)
    assert len(provider.calls) == 1
    provider.release.set()
    await asyncio.gather(first, second)
    assert provider.max_active == 1
    assert engine._lane_locks == {}


@pytest.mark.asyncio
async def test_different_lanes_can_use_global_concurrency_limit() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = since + MINUTE

    class _BlockingProvider(_ScriptedProvider):
        def __init__(self) -> None:
            super().__init__("binance_native", [])
            self.release = asyncio.Event()
            self.started_count = 0
            self.started = asyncio.Event()
            self.active = 0
            self.max_active = 0

        async def fetch_closed_candles(
            self, **kwargs: Any
        ) -> tuple[CandleObservation, ...]:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.started_count += 1
            self.started.set()
            try:
                await self.release.wait()
                return _rows(
                    kwargs["since"],
                    kwargs["until"],
                    lane=kwargs["lane"],
                )
            finally:
                self.active -= 1

    repository = _Repository()
    provider = _BlockingProvider()
    engine = _engine(
        repository,
        _Ingestion(repository),
        _HTF(),
        {"binance_native": provider},
        max_concurrency=2,
    )
    kwargs = {
        "base_timeframe": "1m",
        "base_duration": MINUTE,
        "provider_order": ("binance_native",),
        "provider_symbols": {"binance_native": "BTCUSDT"},
        "target_durations": {},
        "alignment_origin": ORIGIN,
    }

    first = asyncio.create_task(engine.recover(_request(since, until), **kwargs))
    second = asyncio.create_task(
        engine.recover(_request(since, until, lane=OTHER_LANE), **kwargs)
    )
    await provider.started.wait()
    while provider.started_count < 2:
        await asyncio.sleep(0)
    assert provider.max_active == 2
    provider.release.set()
    await asyncio.gather(first, second)
    assert engine._lane_locks == {}


@pytest.mark.asyncio
async def test_cancellation_propagates_from_provider() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = since + MINUTE

    class _CancelledProvider(_ScriptedProvider):
        def __init__(self) -> None:
            super().__init__("binance_native", [])
            self.started = asyncio.Event()

        async def fetch_closed_candles(
            self, **kwargs: Any
        ) -> tuple[CandleObservation, ...]:
            del kwargs
            self.started.set()
            await asyncio.Event().wait()
            return ()

    provider = _CancelledProvider()
    engine = _engine(
        _Repository(),
        _Ingestion(_Repository()),
        _HTF(),
        {"binance_native": provider},
    )
    task = asyncio.create_task(
        engine.recover(
            _request(since, until),
            base_timeframe="1m",
            base_duration=MINUTE,
            provider_order=("binance_native",),
            provider_symbols={"binance_native": "BTCUSDT"},
            target_durations={},
            alignment_origin=ORIGIN,
        )
    )
    await provider.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert engine._lane_locks == {}
