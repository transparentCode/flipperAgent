from __future__ import annotations

import pandas as pd
import pytest

from libs.common.exceptions import DataIngestionError
from libs.market_data import BINANCE_KLINE_PAGE_LIMIT, BinanceNativeAdapter


class _FakeClient:
    def __init__(self, rows=None, error: Exception | None = None) -> None:
        self.rows = rows if rows is not None else []
        self.error = error
        self.calls: list[tuple[str, str, dict]] = []

    def klines(self, symbol: str, timeframe: str, **params):
        self.calls.append((symbol, timeframe, params))
        if self.error is not None:
            raise self.error
        return self.rows


def _raw_row() -> list[object]:
    return [
        1_700_000_000_000,
        "100.0",
        "105.0",
        "99.0",
        "104.0",
        "12.5",
        1_700_000_059_999,
        "1250.0",
        42,
        "6.25",
        "625.0",
        "0",
    ]


def _adapter(monkeypatch, client: _FakeClient) -> BinanceNativeAdapter:
    monkeypatch.setattr(
        "libs.market_data.binance_native.UMFutures",
        lambda **kwargs: client,
    )
    return BinanceNativeAdapter(key="key", secret="secret")


def test_empty_response_has_contract_columns(monkeypatch) -> None:
    adapter = _adapter(monkeypatch, _FakeClient())
    result = adapter._fetch_and_parse_klines_sync("BTCUSDT", "1m")
    with_close = adapter._fetch_and_parse_klines_sync(
        "BTCUSDT",
        "1m",
        include_close_time=True,
    )

    assert list(result.columns) == [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "taker_buy_base",
    ]
    assert list(with_close.columns) == [*result.columns, "close_time"]
    assert result.empty


@pytest.mark.asyncio
async def test_historical_row_preserves_native_ohlcv_and_taker_buy(monkeypatch) -> None:
    client = _FakeClient([_raw_row()])
    adapter = _adapter(monkeypatch, client)

    result = await adapter.get_historical_ohlcv(
        "BTCUSDT",
        "1m",
        since=10,
        until=20,
        limit=30,
        include_close_time=True,
    )

    assert result.iloc[0].to_dict() == {
        "timestamp": 1_700_000_000_000,
        "open": 100.0,
        "high": 105.0,
        "low": 99.0,
        "close": 104.0,
        "volume": 12.5,
        "taker_buy_base": 6.25,
        "close_time": 1_700_000_059_999,
    }
    assert client.calls == [
        ("BTCUSDT", "1m", {"startTime": 10, "endTime": 20, "limit": 30})
    ]
    assert all(
        pd.api.types.is_numeric_dtype(result[column]) for column in result.columns
    )


@pytest.mark.asyncio
async def test_historical_errors_are_wrapped(monkeypatch) -> None:
    adapter = _adapter(monkeypatch, _FakeClient(error=RuntimeError("network down")))

    with pytest.raises(DataIngestionError, match="Binance API failed"):
        await adapter.get_historical_ohlcv("BTCUSDT", "1m")


def test_neutral_adapter_has_no_live_websocket_surface(monkeypatch) -> None:
    adapter = _adapter(monkeypatch, _FakeClient())
    assert not hasattr(adapter, "stream_multiplex_socket")
    assert BINANCE_KLINE_PAGE_LIMIT == 1500
