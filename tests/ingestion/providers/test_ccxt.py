from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import ccxt.async_support as ccxt
import pytest

from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.providers.ccxt import CCXTHistoricalProvider
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
        self.closed = True


@pytest.mark.asyncio
async def test_ccxt_normalizes_raw_binance_kline_semantics() -> None:
    exchange = _FakeExchange(
        [
            _ohlcv_row(SINCE + MINUTE),
            _ohlcv_row(SINCE),
        ]
    )
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


@pytest.mark.asyncio
async def test_ccxt_sdk_failure_preserves_cause() -> None:
    original = ccxt.NetworkError("network down")
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

    assert raised.value.__cause__ is original


@pytest.mark.asyncio
async def test_ccxt_raw_endpoint_failure_preserves_cause() -> None:
    original = ccxt.NetworkError("raw endpoint down")
    provider = CCXTHistoricalProvider(
        provider_id="ccxt_binance",
        exchange_id="binanceusdm",
        exchange=_FakeExchange(raw_error=original),
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
