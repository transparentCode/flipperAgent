from __future__ import annotations

import asyncio
import threading
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from binance.error import ClientError, ServerError
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import SSLError

import apps.ingestion_app.providers.binance_native as native_module
import apps.ingestion_app.runtime.blocking as blocking_module
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.providers.base import (
    ProviderAvailabilityError,
    TransportDeadlineExceeded,
)
from apps.ingestion_app.providers.binance_native import (
    BinanceNativeHistoricalProvider,
)
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


def _raw_kline(
    open_time: datetime,
    *,
    duration: timedelta = MINUTE,
    open_value: object = "100.00",
    high_value: object = "101.00",
    low_value: object = "99.00",
    close_value: object = "100.50",
    volume_value: object = "3.00",
    taker_value: object = "1.25",
) -> list[object]:
    provider_close_time = open_time + duration - timedelta(milliseconds=1)
    return [
        _epoch_milliseconds(open_time),
        open_value,
        high_value,
        low_value,
        close_value,
        volume_value,
        _epoch_milliseconds(provider_close_time),
        "300.00",
        10,
        taker_value,
        "125.00",
        "0",
    ]


class _FakeBinanceClient:
    def __init__(self, rows: object = (), error: Exception | None = None) -> None:
        self.rows = rows
        self.error = error
        self.calls: list[tuple[object, ...]] = []
        self.call_thread_ids: list[int] = []
        self.session = _FakeSession()

    def klines(self, *args: object, **kwargs: object) -> object:
        self.calls.append((*args, kwargs))
        self.call_thread_ids.append(threading.get_ident())
        if self.error is not None:
            raise self.error
        return self.rows


class _FakeSession:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _HeldBinanceClient(_FakeBinanceClient):
    def __init__(self, rows: object = ()) -> None:
        super().__init__(rows)
        self.klines_started = threading.Event()
        self.release_klines = threading.Event()
        self.klines_call_count = 0
        self._count_lock = threading.Lock()

    def klines(self, *args: object, **kwargs: object) -> object:
        with self._count_lock:
            self.klines_call_count += 1
        self.klines_started.set()
        self.release_klines.wait(5)
        return super().klines(*args, **kwargs)


async def _wait_for_retained_workers(
    provider: BinanceNativeHistoricalProvider,
    expected: int,
    *,
    timeout: float = 1.0,
) -> None:
    deadline = time.monotonic() + timeout
    while provider.retained_worker_count != expected:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            pytest.fail(
                f"retained worker count did not reach {expected}; "
                f"got {provider.retained_worker_count}"
            )
        await asyncio.sleep(min(0.01, remaining))


async def _wait_for_call_count(
    client: _HeldBinanceClient,
    expected: int,
    *,
    timeout: float = 1.0,
) -> None:
    deadline = time.monotonic() + timeout
    while client.klines_call_count < expected:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            pytest.fail(
                f"SDK call count did not reach {expected}; "
                f"got {client.klines_call_count}"
            )
        await asyncio.sleep(min(0.01, remaining))


@pytest.mark.asyncio
async def test_binance_close_closes_http_session() -> None:
    client = _FakeBinanceClient()

    await BinanceNativeHistoricalProvider(client).close()

    assert client.session.closed is True


@pytest.mark.asyncio
async def test_binance_normalizes_decimal_utc_and_provider_close_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeBinanceClient(
        [
            _raw_kline(SINCE + MINUTE),
            _raw_kline(SINCE),
        ]
    )
    monkeypatch.setattr(native_module, "datetime", _CountingDateTime)
    since = _CountingDateTime(2026, 1, 1, tzinfo=UTC)
    until = _CountingDateTime(2026, 1, 1, 0, 3, tzinfo=UTC)

    result = await BinanceNativeHistoricalProvider(client).fetch_closed_candles(
        lane=LANE,
        provider_symbol="BTCUSDT",
        timeframe_duration=MINUTE,
        since=since,
        until=until,
        limit=10,
    )

    assert [observation.open_time for observation in result] == [
        SINCE,
        SINCE + MINUTE,
    ]
    assert result[0].open == Decimal("100.00")
    assert result[0].volume == Decimal("3.00")
    assert result[0].taker_buy_base == Decimal("1.25")
    assert result[0].close_time == SINCE + MINUTE
    assert result[0].provider_close_time == SINCE + MINUTE
    assert result[0].transport == "rest"
    assert result[0].received_at.tzinfo is not None
    assert result[0].received_at.utcoffset() == timedelta(0)

    assert client.calls[0][0:2] == ("BTCUSDT", "1m")
    assert client.calls[0][1] == "1m"
    assert client.calls[0][2]["startTime"] == _epoch_milliseconds(SINCE)
    assert client.calls[0][2]["limit"] == 10
    assert len({observation.received_at for observation in result}) == 1
    assert _CountingDateTime.calls == 2  # request cutoff + one batch sample
    assert result[0].received_at == SINCE + timedelta(minutes=11)


@pytest.mark.asyncio
async def test_binance_rejects_taker_buy_base_above_volume() -> None:
    client = _FakeBinanceClient(
        [_raw_kline(SINCE, volume_value="3.00", taker_value="4.00")]
    )

    with pytest.raises(DataIngestionError, match="invalid candle values"):
        await BinanceNativeHistoricalProvider(client).fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTCUSDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )


@pytest.mark.asyncio
async def test_binance_uses_supplied_duration_without_timeframe_parsing() -> None:
    lane = MarketLane("binance", "BTC-USDT-PERP", "2h")
    duration = timedelta(hours=2)
    open_time = datetime(2026, 1, 1, tzinfo=UTC)
    client = _FakeBinanceClient([_raw_kline(open_time, duration=duration)])

    result = await BinanceNativeHistoricalProvider(client).fetch_closed_candles(
        lane=lane,
        provider_symbol="BTCUSDT",
        timeframe_duration=duration,
        since=open_time,
        until=open_time + duration,
        limit=1,
    )

    assert len(result) == 1
    assert result[0].close_time == open_time + duration
    assert result[0].provider_close_time == open_time + duration


@pytest.mark.asyncio
async def test_binance_filters_half_open_range_forming_rows_and_limit() -> None:
    rows = [
        _raw_kline(SINCE - MINUTE),
        _raw_kline(SINCE + 2 * MINUTE),
        _raw_kline(SINCE),
        _raw_kline(SINCE + MINUTE),
        _raw_kline(UNTIL),
    ]
    client = _FakeBinanceClient(rows)

    result = await BinanceNativeHistoricalProvider(client).fetch_closed_candles(
        lane=LANE,
        provider_symbol="BTCUSDT",
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
async def test_binance_filters_out_of_window_invalid_values_before_candle_validation() -> (
    None
):
    row = _raw_kline(SINCE - MINUTE, volume_value="-1.00", taker_value="0")

    result = await BinanceNativeHistoricalProvider(
        _FakeBinanceClient([row])
    ).fetch_closed_candles(
        lane=LANE,
        provider_symbol="BTCUSDT",
        timeframe_duration=MINUTE,
        since=SINCE,
        until=UNTIL,
        limit=10,
    )

    assert result == ()


@pytest.mark.asyncio
async def test_binance_filters_candle_that_is_not_closed_at_request_cutoff() -> None:
    now = datetime.now(UTC)
    forming_open_time = now + timedelta(hours=1)
    client = _FakeBinanceClient([_raw_kline(forming_open_time)])

    result = await BinanceNativeHistoricalProvider(client).fetch_closed_candles(
        lane=LANE,
        provider_symbol="BTCUSDT",
        timeframe_duration=MINUTE,
        since=now - MINUTE,
        until=now + timedelta(hours=2),
        limit=10,
    )

    assert result == ()


@pytest.mark.asyncio
async def test_binance_empty_response_is_empty_tuple() -> None:
    result = await BinanceNativeHistoricalProvider(
        _FakeBinanceClient()
    ).fetch_closed_candles(
        lane=LANE,
        provider_symbol="BTCUSDT",
        timeframe_duration=MINUTE,
        since=SINCE,
        until=UNTIL,
        limit=10,
    )

    assert result == ()


@pytest.mark.asyncio
async def test_binance_sync_sdk_call_is_offloaded() -> None:
    client = _FakeBinanceClient([_raw_kline(SINCE)])

    result = await BinanceNativeHistoricalProvider(client).fetch_closed_candles(
        lane=LANE,
        provider_symbol="BTCUSDT",
        timeframe_duration=MINUTE,
        since=SINCE,
        until=UNTIL,
        limit=10,
    )

    assert len(result) == 1
    assert client.call_thread_ids
    assert client.call_thread_ids[0] != threading.get_ident()


@pytest.mark.asyncio
async def test_binance_successful_fetch_then_immediate_close_drains_worker() -> None:
    client = _FakeBinanceClient([])
    provider = BinanceNativeHistoricalProvider(client)

    result = await provider.fetch_closed_candles(
        lane=LANE,
        provider_symbol="BTCUSDT",
        timeframe_duration=MINUTE,
        since=SINCE,
        until=UNTIL,
        limit=10,
    )
    await provider.close()

    assert result == ()
    assert client.session.closed is True
    assert provider.retained_worker_count == 0


@pytest.mark.asyncio
async def test_binance_deadline_retains_worker_and_quarantines_provider() -> None:
    client = _HeldBinanceClient([])
    provider = BinanceNativeHistoricalProvider(
        client,
        attempt_timeout_seconds=0.01,
    )
    task = asyncio.create_task(
        provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTCUSDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )
    )
    assert await asyncio.to_thread(client.klines_started.wait, 1)

    try:
        with pytest.raises(TransportDeadlineExceeded):
            await task
        assert provider.retained_worker_count == 1
        assert provider.quarantined is True
        with pytest.raises(TransportDeadlineExceeded):
            await provider.fetch_closed_candles(
                lane=LANE,
                provider_symbol="BTCUSDT",
                timeframe_duration=MINUTE,
                since=SINCE,
                until=UNTIL,
                limit=10,
            )
    finally:
        client.release_klines.set()

    await _wait_for_retained_workers(provider, 0)
    assert provider.quarantined is True


@pytest.mark.asyncio
async def test_binance_cancellation_releases_only_after_worker_finishes() -> None:
    client = _HeldBinanceClient([])
    provider = BinanceNativeHistoricalProvider(
        client,
        attempt_timeout_seconds=1,
    )
    task = asyncio.create_task(
        provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTCUSDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )
    )
    assert await asyncio.to_thread(client.klines_started.wait, 1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert provider.quarantined is False
    assert provider.retained_worker_count == 1

    client.release_klines.set()
    await _wait_for_retained_workers(provider, 0)

    result = await provider.fetch_closed_candles(
        lane=LANE,
        provider_symbol="BTCUSDT",
        timeframe_duration=MINUTE,
        since=SINCE,
        until=UNTIL,
        limit=10,
    )
    assert result == ()


@pytest.mark.asyncio
async def test_binance_close_timeout_does_not_close_session_concurrently() -> None:
    class _HeldSession:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()
            self.close_calls = 0
            self.closed = False

        def close(self) -> None:
            self.close_calls += 1
            self.started.set()
            self.release.wait(5)
            self.closed = True

    client = _FakeBinanceClient([])
    session = _HeldSession()
    client.session = session
    provider = BinanceNativeHistoricalProvider(
        client,
        attempt_timeout_seconds=0.01,
    )

    close_task = asyncio.create_task(provider.close())
    assert await asyncio.to_thread(session.started.wait, 1)
    with pytest.raises(TransportDeadlineExceeded):
        await close_task
    assert session.close_calls == 1
    assert session.closed is False
    assert provider.quarantined is True
    assert provider.retained_worker_count == 1

    session.release.set()
    await _wait_for_retained_workers(provider, 0)
    with pytest.raises(TransportDeadlineExceeded):
        await provider.close()
    assert session.close_calls == 1


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), float("-inf")])
def test_binance_rejects_non_finite_timeout(timeout: float) -> None:
    with pytest.raises(ValueError, match="attempt_timeout_seconds"):
        BinanceNativeHistoricalProvider(attempt_timeout_seconds=timeout)


@pytest.mark.asyncio
async def test_binance_admits_configured_capacity_without_queueing() -> None:
    client = _HeldBinanceClient([])
    provider = BinanceNativeHistoricalProvider(
        client,
        attempt_timeout_seconds=1,
        max_concurrency=4,
    )

    async def fetch() -> tuple[object, ...]:
        return await provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTCUSDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )

    tasks = [asyncio.create_task(fetch()) for _ in range(4)]
    try:
        await _wait_for_call_count(client, 4)
        with pytest.raises(DataIngestionError, match="saturated"):
            await fetch()
        client.release_klines.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks), 2)
    finally:
        client.release_klines.set()
    assert results == [(), (), (), ()]
    assert provider.quarantined is False
    await _wait_for_retained_workers(provider, 0)


@pytest.mark.asyncio
async def test_binance_sdk_timeout_error_is_normal_retryable_error() -> None:
    provider = BinanceNativeHistoricalProvider(
        _FakeBinanceClient(error=TimeoutError("SDK timeout")),
        attempt_timeout_seconds=1,
    )

    with pytest.raises(ProviderAvailabilityError) as raised:
        await provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTCUSDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )

    assert isinstance(raised.value.__cause__, TimeoutError)
    assert provider.quarantined is False
    await _wait_for_retained_workers(provider, 0)


@pytest.mark.asyncio
async def test_binance_server_error_is_provider_availability_failure() -> None:
    original = ServerError(503, "server unavailable")
    provider = BinanceNativeHistoricalProvider(
        _FakeBinanceClient(error=original),
        attempt_timeout_seconds=1,
    )

    with pytest.raises(ProviderAvailabilityError) as raised:
        await provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTCUSDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )

    assert raised.value.__cause__ is original
    assert provider.quarantined is False
    await _wait_for_retained_workers(provider, 0)


@pytest.mark.asyncio
async def test_binance_requests_connection_error_is_retryable() -> None:
    original = RequestsConnectionError("connection reset")
    provider = BinanceNativeHistoricalProvider(
        _FakeBinanceClient(error=original),
        attempt_timeout_seconds=1,
    )

    with pytest.raises(ProviderAvailabilityError) as raised:
        await provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTCUSDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )

    assert raised.value.__cause__ is original
    assert provider.quarantined is False
    await _wait_for_retained_workers(provider, 0)
    assert provider.retained_worker_count == 0


@pytest.mark.asyncio
async def test_binance_requests_ssl_error_remains_fatal() -> None:
    original = SSLError("certificate verification failed")
    provider = BinanceNativeHistoricalProvider(
        _FakeBinanceClient(error=original),
        attempt_timeout_seconds=1,
    )

    with pytest.raises(DataIngestionError) as raised:
        await provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTCUSDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )

    assert not isinstance(raised.value, ProviderAvailabilityError)
    assert raised.value.__cause__ is original
    assert provider.quarantined is False
    await _wait_for_retained_workers(provider, 0)
    assert provider.retained_worker_count == 0


@pytest.mark.asyncio
async def test_binance_client_error_remains_fatal() -> None:
    original = ClientError(401, -2015, "invalid api-key", {})
    provider = BinanceNativeHistoricalProvider(_FakeBinanceClient(error=original))

    with pytest.raises(DataIngestionError) as raised:
        await provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTCUSDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )

    assert not isinstance(raised.value, ProviderAvailabilityError)
    assert raised.value.__cause__ is original
    await _wait_for_retained_workers(provider, 0)


@pytest.mark.asyncio
async def test_binance_thread_start_failure_releases_admission_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_start(_thread: threading.Thread) -> None:
        raise RuntimeError("thread start failed")

    monkeypatch.setattr(blocking_module.Thread, "start", fail_start)
    client = _FakeBinanceClient([])
    provider = BinanceNativeHistoricalProvider(client)

    with pytest.raises(DataIngestionError, match="failed to fetch klines"):
        await provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTCUSDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )

    assert provider.retained_worker_count == 0
    assert client.calls == []


@pytest.mark.asyncio
async def test_binance_close_cancellation_does_not_stick_closing_state() -> None:
    class _HeldSession:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()
            self.close_calls = 0
            self.closed = False

        def close(self) -> None:
            self.close_calls += 1
            self.started.set()
            self.release.wait(5)
            self.closed = True

    client = _FakeBinanceClient([])
    session = _HeldSession()
    client.session = session
    provider = BinanceNativeHistoricalProvider(client, attempt_timeout_seconds=1)

    close_task = asyncio.create_task(provider.close())
    assert await asyncio.to_thread(session.started.wait, 1)
    close_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await close_task

    session.release.set()
    await _wait_for_retained_workers(provider, 0)
    await provider.close()
    assert session.close_calls == 1
    assert session.closed is True


@pytest.mark.asyncio
async def test_binance_sdk_failure_preserves_cause() -> None:
    original = RuntimeError("network down")
    with pytest.raises(DataIngestionError) as raised:
        await BinanceNativeHistoricalProvider(
            _FakeBinanceClient(error=original)
        ).fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTCUSDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )

    assert raised.value.__cause__ is original


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
async def test_binance_validates_request_before_network(
    field: str,
    value: object,
    error_type: type[Exception],
) -> None:
    client = _FakeBinanceClient([_raw_kline(SINCE)])
    kwargs: dict[str, object] = {
        "lane": LANE,
        "provider_symbol": "BTCUSDT",
        "timeframe_duration": MINUTE,
        "since": SINCE,
        "until": UNTIL,
        "limit": 10,
    }
    kwargs[field] = value

    with pytest.raises(error_type):
        await BinanceNativeHistoricalProvider(client).fetch_closed_candles(**kwargs)  # type: ignore[arg-type]

    assert client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows",
    [
        [[1, 2, 3]],
        [
            [
                _epoch_milliseconds(SINCE),
                "not-a-number",
                "101",
                "99",
                "100",
                "3",
                _epoch_milliseconds(SINCE + MINUTE - timedelta(milliseconds=1)),
                "300",
                1,
                "1",
                "1",
                "0",
            ]
        ],
    ],
)
async def test_binance_malformed_payload_fails_as_data_ingestion_error(
    rows: list[object],
) -> None:
    with pytest.raises(DataIngestionError):
        await BinanceNativeHistoricalProvider(
            _FakeBinanceClient(rows)
        ).fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTCUSDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )


@pytest.mark.asyncio
async def test_binance_provider_close_mismatch_fails() -> None:
    row = _raw_kline(SINCE)
    row[6] = _epoch_milliseconds(SINCE + timedelta(minutes=2))

    with pytest.raises(DataIngestionError, match="close timestamp"):
        await BinanceNativeHistoricalProvider(
            _FakeBinanceClient([row])
        ).fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTCUSDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )


@pytest.mark.asyncio
async def test_binance_invalid_candle_invariant_is_data_ingestion_error() -> None:
    row = _raw_kline(SINCE, high_value="99.00")

    with pytest.raises(DataIngestionError, match="invalid candle values"):
        await BinanceNativeHistoricalProvider(
            _FakeBinanceClient([row])
        ).fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTCUSDT",
            timeframe_duration=MINUTE,
            since=SINCE,
            until=UNTIL,
            limit=10,
        )
