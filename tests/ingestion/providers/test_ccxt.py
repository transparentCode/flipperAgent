from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import ccxt.async_support as ccxt
import pytest

import apps.ingestion_app.providers.ccxt as ccxt_module
import apps.ingestion_app.transport.ownership as ownership_module
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.providers.base import (
    ProviderAvailabilityError,
    TransportDeadlineExceeded,
)
from apps.ingestion_app.providers.ccxt import CCXTHistoricalProvider
from libs.common.exceptions import DataIngestionError

LANE = MarketLane("binance", "BTC-USDT-PERP", "1m")
SINCE = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
UNTIL = datetime(2026, 1, 1, 0, 3, tzinfo=UTC)
MINUTE = timedelta(minutes=1)


class _CountingDateTime(datetime):
    calls = 0
    values = (
        SINCE + timedelta(minutes=10),
        SINCE + timedelta(minutes=11),
    )

    @classmethod
    def now(cls, tz: object = None) -> datetime:
        value = cls.values[cls.calls]
        cls.calls += 1
        if tz is not None:
            value = value.astimezone(tz)  # type: ignore[arg-type]
        return cls(
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second,
            value.microsecond,
            tzinfo=value.tzinfo,
        )


def _epoch_milliseconds(value: datetime) -> int:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    elapsed = value - epoch
    return (
        elapsed.days * 86_400_000
        + elapsed.seconds * 1_000
        + elapsed.microseconds // 1_000
    )


def _ohlcv_row(
    open_time: datetime,
    *,
    open_value: object = "100.00",
    high_value: object = "101.00",
    low_value: object = "99.00",
    close_value: object = "100.50",
    volume_value: object = "3.00",
    taker_buy_value: object = "1.25",
    duration: timedelta = MINUTE,
) -> list[object]:
    return [
        _epoch_milliseconds(open_time),
        open_value,
        high_value,
        low_value,
        close_value,
        volume_value,
        _epoch_milliseconds(open_time + duration - timedelta(milliseconds=1)),
        "300.00",
        10,
        taker_buy_value,
        "125.00",
        "0",
    ]


class _FakeExchange:
    def __init__(
        self,
        rows: object = (),
        error: Exception | None = None,
        markets: object = None,
        raw_error: Exception | None = None,
    ) -> None:
        self.rows = rows
        self.error = error
        self.raw_error = raw_error
        self.markets = markets or {
            "BTC/USDT:USDT": {"id": "BTCUSDT"},
        }
        self.calls: list[tuple[str, object]] = []
        self.closed = False
        self.close_calls = 0

    async def load_markets(self) -> object:
        self.calls.append(("load_markets", None))
        if self.error is not None:
            raise self.error
        return self.markets

    def market(self, symbol: str) -> object:
        self.calls.append(("market", symbol))
        return self.markets[symbol]  # type: ignore[index]

    async def fapiPublicGetKlines(self, params: object) -> object:
        self.calls.append(("fapiPublicGetKlines", params))
        if self.raw_error is not None:
            raise self.raw_error
        return self.rows

    async def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class _HeldExchange(_FakeExchange):
    def __init__(self, rows: object = ()) -> None:
        super().__init__(rows)
        self.load_started = asyncio.Event()
        self.release_load = asyncio.Event()
        self.load_call_count = 0
        self.load_cancelled = False
        self.close_started = asyncio.Event()
        self.release_close = asyncio.Event()

    async def load_markets(self) -> object:
        self.load_call_count += 1
        self.calls.append(("load_markets", None))
        self.load_started.set()
        try:
            await self.release_load.wait()
        except asyncio.CancelledError:
            self.load_cancelled = True
            await self.release_load.wait()
        return self.markets

    async def close(self) -> None:
        self.close_calls += 1
        self.close_started.set()
        try:
            await self.release_close.wait()
        except asyncio.CancelledError:
            await self.release_close.wait()
        self.closed = True


async def _wait_for_retained_tasks(
    provider: CCXTHistoricalProvider,
    expected: int,
    *,
    timeout: float = 1.0,
) -> None:
    deadline = time.monotonic() + timeout
    while provider.retained_worker_count != expected:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            pytest.fail(
                f"retained task count did not reach {expected}; "
                f"got {provider.retained_worker_count}"
            )
        await asyncio.sleep(min(0.01, remaining))


async def _wait_for_load_count(
    exchange: _HeldExchange,
    expected: int,
    *,
    timeout: float = 1.0,
) -> None:
    deadline = time.monotonic() + timeout
    while exchange.load_call_count < expected:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            pytest.fail(
                f"load_markets count did not reach {expected}; "
                f"got {exchange.load_call_count}"
            )
        await asyncio.sleep(min(0.01, remaining))


@pytest.mark.asyncio
async def test_ccxt_normalizes_raw_binance_kline_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange = _FakeExchange(
        [
            _ohlcv_row(SINCE + MINUTE),
            _ohlcv_row(SINCE),
        ]
    )
    monkeypatch.setattr(ccxt_module, "datetime", _CountingDateTime)
    since = _CountingDateTime(2026, 1, 1, tzinfo=UTC)
    until = _CountingDateTime(2026, 1, 1, 0, 3, tzinfo=UTC)
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=exchange,
    )

    result = await provider.fetch_closed_candles(
        lane=LANE,
        provider_symbol="BTC/USDT:USDT",
        timeframe_duration=MINUTE,
        since=since,
        until=until,
        limit=10,
    )

    assert [observation.open_time for observation in result] == [
        SINCE,
        SINCE + MINUTE,
    ]
    assert result[0].provider_id == "ccxt_binance"
    assert result[0].provider_symbol == "BTC/USDT:USDT"
    assert result[0].open == Decimal("100.00")
    assert result[0].volume == Decimal("3.00")
    assert result[0].taker_buy_base == Decimal("1.25")
    assert result[0].close_time == SINCE + MINUTE
    assert result[0].provider_close_time == SINCE + MINUTE
    assert result[0].received_at.utcoffset() == timedelta(0)
    assert exchange.calls[0] == ("load_markets", None)
    assert exchange.calls[1] == ("market", "BTC/USDT:USDT")
    assert exchange.calls[2][0] == "fapiPublicGetKlines"
    assert exchange.calls[2][1] == {
        "symbol": "BTCUSDT",
        "interval": "1m",
        "startTime": _epoch_milliseconds(SINCE),
        "endTime": _epoch_milliseconds(UNTIL),
        "limit": 10,
    }
    assert len({observation.received_at for observation in result}) == 1
    assert _CountingDateTime.calls == 2  # request cutoff + one batch sample
    assert result[0].received_at == SINCE + timedelta(minutes=11)


@pytest.mark.asyncio
async def test_ccxt_uses_supplied_duration_without_timeframe_parsing() -> None:
    lane = MarketLane("binance", "BTC-USDT-PERP", "2h")
    duration = timedelta(hours=2)
    open_time = datetime(2026, 1, 1, tzinfo=UTC)
    provider = CCXTHistoricalProvider(
        provider_id="custom_ccxt",
        exchange_id="binanceusdm",
        exchange=_FakeExchange([_ohlcv_row(open_time, duration=duration)]),
    )

    result = await provider.fetch_closed_candles(
        lane=lane,
        provider_symbol="BTC/USDT:USDT",
        timeframe_duration=duration,
        since=open_time,
        until=open_time + duration,
        limit=1,
    )

    assert len(result) == 1
    assert result[0].close_time == open_time + duration
    assert result[0].provider_id == "custom_ccxt"


@pytest.mark.asyncio
async def test_ccxt_filters_half_open_range_forming_rows_and_limit() -> None:
    rows = [
        _ohlcv_row(SINCE - MINUTE),
        _ohlcv_row(SINCE + 2 * MINUTE),
        _ohlcv_row(SINCE),
        _ohlcv_row(SINCE + MINUTE),
        _ohlcv_row(UNTIL),
    ]
    exchange = _FakeExchange(rows)

    result = await CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=exchange,
    ).fetch_closed_candles(
        lane=LANE,
        provider_symbol="BTC/USDT:USDT",
        timeframe_duration=MINUTE,
        since=SINCE,
        until=UNTIL,
        limit=2,
    )

    assert [observation.open_time for observation in result] == [
        SINCE,
        SINCE + MINUTE,
    ]


@pytest.mark.asyncio
async def test_ccxt_rejects_out_of_window_invalid_values_before_window_filtering() -> (
    None
):
    row = _ohlcv_row(SINCE - MINUTE, volume_value="-1.00", taker_buy_value="0")

    with pytest.raises(
        DataIngestionError,
        match="invalid volume/taker-buy values",
    ):
        await CCXTHistoricalProvider(
            provider_id="ccxt_binance",
            exchange_id="binanceusdm",
            exchange=_FakeExchange([row]),
        ).fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTC/USDT:USDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )


@pytest.mark.asyncio
async def test_ccxt_filters_candle_that_is_not_closed_at_request_cutoff() -> None:
    now = datetime.now(UTC)
    forming_open_time = now + timedelta(hours=1)
    exchange = _FakeExchange([_ohlcv_row(forming_open_time)])

    result = await CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=exchange,
    ).fetch_closed_candles(
        lane=LANE,
        provider_symbol="BTC/USDT:USDT",
        timeframe_duration=MINUTE,
        since=now - MINUTE,
        until=now + timedelta(hours=2),
        limit=10,
    )

    assert result == ()


@pytest.mark.asyncio
async def test_ccxt_empty_response_is_empty_tuple_and_close_closes_exchange() -> None:
    exchange = _FakeExchange()
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=exchange,
    )

    result = await provider.fetch_closed_candles(
        lane=LANE,
        provider_symbol="BTC/USDT:USDT",
        timeframe_duration=MINUTE,
        since=SINCE,
        until=UNTIL,
        limit=10,
    )
    await provider.close()

    assert result == ()
    assert exchange.closed is True
    assert exchange.close_calls == 1


@pytest.mark.asyncio
async def test_ccxt_successful_fetch_then_immediate_close_drains_worker() -> None:
    exchange = _FakeExchange()
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=exchange,
    )

    result = await provider.fetch_closed_candles(
        lane=LANE,
        provider_symbol="BTC/USDT:USDT",
        timeframe_duration=MINUTE,
        since=SINCE,
        until=UNTIL,
        limit=10,
    )
    await provider.close()

    assert result == ()
    assert exchange.closed is True
    assert exchange.close_calls == 1
    assert provider.retained_worker_count == 0


@pytest.mark.asyncio
async def test_ccxt_deadline_retains_task_and_quarantines_provider() -> None:
    exchange = _HeldExchange()
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=exchange,
        attempt_timeout_seconds=0.01,
    )
    task = asyncio.create_task(
        provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTC/USDT:USDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )
    )
    await asyncio.wait_for(exchange.load_started.wait(), 1)

    try:
        with pytest.raises(TransportDeadlineExceeded):
            await task
        assert provider.retained_worker_count == 1
        assert provider.quarantined is True
        with pytest.raises(TransportDeadlineExceeded):
            await provider.fetch_closed_candles(
                lane=LANE,
                provider_symbol="BTC/USDT:USDT",
                timeframe_duration=MINUTE,
                since=SINCE,
                until=UNTIL,
                limit=10,
            )
    finally:
        exchange.release_load.set()

    await _wait_for_retained_tasks(provider, 0)
    assert exchange.load_cancelled is False
    assert provider.quarantined is True


@pytest.mark.asyncio
async def test_ccxt_cancellation_releases_only_after_task_finishes() -> None:
    exchange = _HeldExchange()
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=exchange,
        attempt_timeout_seconds=1,
    )
    task = asyncio.create_task(
        provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTC/USDT:USDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )
    )
    await asyncio.wait_for(exchange.load_started.wait(), 1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert provider.quarantined is False
    assert provider.retained_worker_count == 1

    exchange.release_load.set()
    await _wait_for_retained_tasks(provider, 0)

    result = await provider.fetch_closed_candles(
        lane=LANE,
        provider_symbol="BTC/USDT:USDT",
        timeframe_duration=MINUTE,
        since=SINCE,
        until=UNTIL,
        limit=10,
    )
    assert result == ()


@pytest.mark.asyncio
async def test_ccxt_wait_until_idle_returns_for_idle_provider() -> None:
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=_FakeExchange(),
    )

    await asyncio.wait_for(provider.wait_until_idle(), 1)


@pytest.mark.asyncio
async def test_ccxt_wait_until_idle_waits_for_retained_task() -> None:
    exchange = _HeldExchange()
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=exchange,
        attempt_timeout_seconds=1,
    )
    task = asyncio.create_task(
        provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTC/USDT:USDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )
    )
    await asyncio.wait_for(exchange.load_started.wait(), 1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    idle = asyncio.create_task(provider.wait_until_idle())
    await asyncio.sleep(0)
    assert not idle.done()
    assert provider.retained_worker_count == 1

    exchange.release_load.set()
    await asyncio.wait_for(idle, 1)
    assert provider.retained_worker_count == 0
    assert provider.quarantined is False


@pytest.mark.asyncio
async def test_ccxt_idle_wait_cancellation_does_not_release_or_quarantine() -> None:
    exchange = _HeldExchange()
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=exchange,
        attempt_timeout_seconds=1,
    )
    task = asyncio.create_task(
        provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTC/USDT:USDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )
    )
    await asyncio.wait_for(exchange.load_started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    idle = asyncio.create_task(provider.wait_until_idle())
    await asyncio.sleep(0)
    idle.cancel()
    with pytest.raises(asyncio.CancelledError):
        await idle
    assert provider.retained_worker_count == 1
    assert provider.quarantined is False

    exchange.release_load.set()
    await asyncio.wait_for(provider.wait_until_idle(), 1)


@pytest.mark.asyncio
async def test_ccxt_idle_wait_deadline_quarantines_retained_task() -> None:
    exchange = _HeldExchange()
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=exchange,
        attempt_timeout_seconds=0.01,
    )
    task = asyncio.create_task(
        provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTC/USDT:USDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )
    )
    await asyncio.wait_for(exchange.load_started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    with pytest.raises(TransportDeadlineExceeded) as raised:
        await provider.wait_until_idle()
    assert raised.value.operation == "historical provider quiescence"
    assert provider.quarantined is True

    exchange.release_load.set()
    await _wait_for_retained_tasks(provider, 0)


@pytest.mark.asyncio
async def test_ccxt_idle_wait_fails_closed_for_existing_quarantine() -> None:
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=_FakeExchange(),
    )
    provider._quarantine()

    with pytest.raises(TransportDeadlineExceeded) as raised:
        await provider.wait_until_idle()

    assert raised.value.operation == "quarantined historical provider quiescence"


@pytest.mark.asyncio
async def test_ccxt_idle_wait_rechecks_exact_deadline_before_quarantine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=_FakeExchange(),
    )
    idle_results = iter((False, True))

    class _Clock:
        values = iter((0.0, 1.0))

        @classmethod
        def monotonic(cls) -> float:
            return next(cls.values)

    monkeypatch.setattr(ownership_module, "time", _Clock)
    monkeypatch.setattr(provider._ownership, "is_idle", lambda: next(idle_results))

    await provider.wait_until_idle()

    assert provider.quarantined is False


@pytest.mark.asyncio
async def test_ccxt_close_timeout_does_not_close_exchange_concurrently() -> None:
    exchange = _HeldExchange()
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=exchange,
        attempt_timeout_seconds=0.01,
    )

    close_task = asyncio.create_task(provider.close())
    await asyncio.wait_for(exchange.close_started.wait(), 1)
    with pytest.raises(TransportDeadlineExceeded):
        await close_task
    assert exchange.close_calls == 1
    assert exchange.closed is False
    assert provider.quarantined is True
    assert provider.retained_worker_count == 1

    exchange.release_close.set()
    await _wait_for_retained_tasks(provider, 0)
    with pytest.raises(TransportDeadlineExceeded):
        await provider.close()
    assert exchange.close_calls == 1


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), float("-inf")])
def test_ccxt_rejects_non_finite_timeout(timeout: float) -> None:
    with pytest.raises(ValueError, match="attempt_timeout_seconds"):
        CCXTHistoricalProvider(
            provider_id="ccxt_binance",
            exchange_id="binanceusdm",
            exchange=_FakeExchange(),
            attempt_timeout_seconds=timeout,
        )


@pytest.mark.asyncio
async def test_ccxt_admits_configured_capacity_without_queueing() -> None:
    exchange = _HeldExchange()
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=exchange,
        attempt_timeout_seconds=1,
        max_concurrency=4,
    )

    async def fetch() -> tuple[object, ...]:
        return await provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTC/USDT:USDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )

    tasks = [asyncio.create_task(fetch()) for _ in range(4)]
    try:
        await _wait_for_load_count(exchange, 4)
        with pytest.raises(DataIngestionError, match="saturated"):
            await fetch()
        exchange.release_load.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks), 2)
    finally:
        exchange.release_load.set()
    assert results == [(), (), (), ()]
    assert provider.quarantined is False
    await _wait_for_retained_tasks(provider, 0)


@pytest.mark.asyncio
async def test_ccxt_sdk_timeout_error_is_normal_retryable_error() -> None:
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=_FakeExchange(error=TimeoutError("SDK timeout")),
        attempt_timeout_seconds=1,
    )

    with pytest.raises(ProviderAvailabilityError) as raised:
        await provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTC/USDT:USDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )

    assert isinstance(raised.value.__cause__, TimeoutError)
    assert provider.quarantined is False
    await _wait_for_retained_tasks(provider, 0)


@pytest.mark.asyncio
async def test_ccxt_task_start_failure_releases_admission_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()

    def fail_create_task(coroutine, *, name=None, context=None):
        del name, context
        raise RuntimeError("task start failed")

    exchange = _FakeExchange()
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=exchange,
    )

    with monkeypatch.context() as local_monkeypatch:
        local_monkeypatch.setattr(loop, "create_task", fail_create_task)
        with pytest.raises(DataIngestionError, match="failed to fetch"):
            await provider.fetch_closed_candles(
                lane=LANE,
                provider_symbol="BTC/USDT:USDT",
                timeframe_duration=MINUTE,
                since=SINCE,
                until=UNTIL,
                limit=10,
            )

    assert provider.retained_worker_count == 0
    assert exchange.calls == []


@pytest.mark.asyncio
async def test_ccxt_close_cancellation_does_not_stick_closing_state() -> None:
    exchange = _HeldExchange()
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=exchange,
        attempt_timeout_seconds=1,
    )

    close_task = asyncio.create_task(provider.close())
    await asyncio.wait_for(exchange.close_started.wait(), 1)
    close_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await close_task

    exchange.release_close.set()
    await _wait_for_retained_tasks(provider, 0)
    await provider.close()
    assert exchange.close_calls == 1
    assert exchange.closed is True


@pytest.mark.asyncio
async def test_ccxt_sdk_failure_preserves_cause() -> None:
    original = ccxt.NetworkError("network down")
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=_FakeExchange(error=original),
    )

    with pytest.raises(ProviderAvailabilityError) as raised:
        await provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTC/USDT:USDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )

    assert raised.value.__cause__ is original


@pytest.mark.asyncio
async def test_ccxt_raw_endpoint_failure_preserves_cause() -> None:
    original = ccxt.NetworkError("raw endpoint down")
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=_FakeExchange(raw_error=original),
    )

    with pytest.raises(ProviderAvailabilityError) as raised:
        await provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTC/USDT:USDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )

    assert raised.value.__cause__ is original


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "original",
    [
        ccxt.AuthenticationError("invalid credentials"),
        ccxt.BadRequest("invalid request"),
        ccxt.InvalidNonce("invalid nonce"),
    ],
)
async def test_ccxt_deterministic_provider_errors_remain_fatal(
    original: BaseException,
) -> None:
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=_FakeExchange(error=original),
    )

    with pytest.raises(DataIngestionError) as raised:
        await provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTC/USDT:USDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )

    assert not isinstance(raised.value, ProviderAvailabilityError)
    assert raised.value.__cause__ is original


@pytest.mark.asyncio
async def test_ccxt_missing_raw_endpoint_fails_closed() -> None:
    class _NoRawEndpoint(_FakeExchange):
        fapiPublicGetKlines = None

    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=_NoRawEndpoint(),
    )

    with pytest.raises(DataIngestionError, match="fapiPublicGetKlines"):
        await provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTC/USDT:USDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )


@pytest.mark.asyncio
async def test_ccxt_resolves_market_id_before_raw_request() -> None:
    exchange = _FakeExchange(
        [_ohlcv_row(SINCE)],
        markets={"ETH/USDT:USDT": {"id": "ETHUSDT"}},
    )
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=exchange,
    )

    await provider.fetch_closed_candles(
        lane=MarketLane("binance", "ETH-USDT-PERP", "1m"),
        provider_symbol="ETH/USDT:USDT",
        timeframe_duration=MINUTE,
        since=SINCE,
        until=UNTIL,
        limit=10,
    )

    assert exchange.calls[2][1]["symbol"] == "ETHUSDT"  # type: ignore[index]


@pytest.mark.asyncio
async def test_ccxt_market_resolution_failure_fails_closed() -> None:
    exchange = _FakeExchange()
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=exchange,
    )

    with pytest.raises(DataIngestionError, match="could not resolve"):
        await provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="ETH/USDT:USDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "error_type"),
    [
        ("provider_symbol", " ", ValueError),
        ("timeframe_duration", timedelta(0), ValueError),
        ("since", datetime(2026, 1, 1), ValueError),  # noqa: DTZ001
        ("until", SINCE, ValueError),
        ("limit", True, TypeError),
        ("limit", 0, ValueError),
    ],
)
async def test_ccxt_validates_request_before_network(
    field: str,
    value: object,
    error_type: type[Exception],
) -> None:
    exchange = _FakeExchange([_ohlcv_row(SINCE)])
    kwargs: dict[str, object] = {
        "lane": LANE,
        "provider_symbol": "BTC/USDT:USDT",
        "timeframe_duration": MINUTE,
        "since": SINCE,
        "until": UNTIL,
        "limit": 10,
    }
    kwargs[field] = value

    with pytest.raises(error_type):
        await CCXTHistoricalProvider(
            provider_id="ccxt_binance",
            exchange_id="binanceusdm",
            exchange=exchange,
        ).fetch_closed_candles(**kwargs)  # type: ignore[arg-type]

    assert exchange.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows",
    [
        [[1, 2, 3]],
        [[_epoch_milliseconds(SINCE), "not-a-number", "101", "99", "100", "3"]],
    ],
)
async def test_ccxt_malformed_payload_fails_as_data_ingestion_error(
    rows: list[object],
) -> None:
    with pytest.raises(DataIngestionError):
        await CCXTHistoricalProvider(
            provider_id="ccxt_binance",
            exchange_id="binanceusdm",
            exchange=_FakeExchange(rows),
        ).fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTC/USDT:USDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )


@pytest.mark.asyncio
async def test_ccxt_invalid_candle_invariant_is_data_ingestion_error() -> None:
    row = _ohlcv_row(SINCE, high_value="99.00")

    with pytest.raises(DataIngestionError, match="invalid candle values"):
        await CCXTHistoricalProvider(
            provider_id="ccxt_binance",
            exchange_id="binanceusdm",
            exchange=_FakeExchange([row]),
        ).fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTC/USDT:USDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )
