from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

import apps.ingestion_app.providers.binance_native as provider_module
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.providers.binance_native import (
    BinanceNativeHistoricalProvider,
)
from libs.common.exceptions import DataIngestionError

LANE = MarketLane("binance", "BTC-USDT-PERP", "1m")
SINCE = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
UNTIL = datetime(2026, 1, 1, 0, 3, tzinfo=UTC)
MINUTE = timedelta(minutes=1)


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
        self.session = _FakeSession()

    def klines(self, *args: object, **kwargs: object) -> object:
        self.calls.append((*args, kwargs))
        if self.error is not None:
            raise self.error
        return self.rows


class _FakeSession:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_binance_close_closes_http_session() -> None:
    client = _FakeBinanceClient()

    await BinanceNativeHistoricalProvider(client).close()

    assert client.session.closed is True


@pytest.mark.asyncio
async def test_binance_normalizes_decimal_utc_and_provider_close_evidence() -> None:
    client = _FakeBinanceClient(
        [
            _raw_kline(SINCE + MINUTE),
            _raw_kline(SINCE),
        ]
    )

    result = await BinanceNativeHistoricalProvider(client).fetch_closed_candles(
        lane=LANE,
        provider_symbol="BTCUSDT",
        timeframe_duration=MINUTE,
        since=SINCE,
        until=UNTIL,
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
async def test_binance_sync_sdk_call_is_offloaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeBinanceClient([_raw_kline(SINCE)])
    calls: list[tuple[object, ...]] = []

    async def fake_to_thread(
        function: object,
        *args: object,
        **kwargs: object,
    ) -> object:
        calls.append((function, *args, kwargs))
        return function(*args, **kwargs)  # type: ignore[operator]

    monkeypatch.setattr(provider_module.asyncio, "to_thread", fake_to_thread)

    result = await BinanceNativeHistoricalProvider(client).fetch_closed_candles(
        lane=LANE,
        provider_symbol="BTCUSDT",
        timeframe_duration=MINUTE,
        since=SINCE,
        until=UNTIL,
        limit=10,
    )

    assert len(result) == 1
    assert calls
    assert getattr(calls[0][0], "__self__", None) is client


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
