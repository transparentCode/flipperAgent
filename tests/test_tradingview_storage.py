"""Tests for the detached TradingView derivative persistence boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pandas as pd
import pytest
from pydantic import ValidationError

import apps.scraper_app.providers.tradingview.worker as tradingview_worker
from apps.scraper_app.providers.tradingview.storage import (
    FundingRateRecord,
    OIRecord,
    TradingViewTimescaleWriter,
)


def test_tradingview_timestamps_normalize_to_utc() -> None:
    utc = UTC
    expected = datetime(2023, 11, 14, 22, 13, 20, tzinfo=utc)
    local = timezone(timedelta(hours=5, minutes=30))

    values_and_expected = [
        (1_700_000_000_000, expected),
        (1_700_000_000, expected),
        ("1700000000000", expected),
        ("1700000000", expected),
        (datetime(2023, 11, 14, 22, 13, 20), expected),  # noqa: DTZ001
        (datetime(2023, 11, 15, 3, 43, 20, tzinfo=local), expected),
        ("2023-11-14T22:13:20Z", expected),
    ]

    for timestamp, expected_timestamp in values_and_expected:
        record = OIRecord(
            timestamp=timestamp,
            symbol="BTC",
            open_interest=1.0,
        )
        assert record.timestamp == expected_timestamp
        assert record.timestamp.tzinfo is utc


def test_open_interest_must_be_nonnegative() -> None:
    with pytest.raises(ValidationError):
        OIRecord(timestamp=1_700_000_000, symbol="BTC", open_interest=-1.0)


def test_funding_rate_may_be_negative() -> None:
    record = FundingRateRecord(
        timestamp=1_700_000_000,
        symbol="BTC",
        funding_rate=-0.01,
    )

    assert record.funding_rate == -0.01


class _FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[tuple[object, ...]]]] = []

    async def executemany(self, query, rows) -> None:
        self.calls.append((query, rows))


class _Acquire:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _FakeConnection:
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class _FakePool:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def acquire(self) -> _Acquire:
        return _Acquire(self.connection)


@pytest.mark.asyncio
async def test_writer_passes_utc_datetimes_to_asyncpg() -> None:
    connection = _FakeConnection()
    writer = TradingViewTimescaleWriter(_FakePool(connection))
    expected = datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)

    await writer.insert_open_interest(
        [OIRecord(timestamp=1_700_000_000_000, symbol="BTC", open_interest=12.5)]
    )
    await writer.insert_funding_rate(
        [FundingRateRecord(timestamp=1_700_000_000, symbol="BTC", funding_rate=-0.01)]
    )

    assert len(connection.calls) == 2
    assert connection.calls[0][1][0][0] == expected
    assert isinstance(connection.calls[0][1][0][0], datetime)
    assert connection.calls[1][1][0][0] == expected
    assert isinstance(connection.calls[1][1][0][0], datetime)


class _FakeRedis:
    def __init__(self) -> None:
        self.hset_calls: list[tuple[str, dict[str, str]]] = []
        self.expire_calls: list[tuple[str, int]] = []

    async def hset(self, key: str, *, mapping: dict[str, str]) -> None:
        self.hset_calls.append((key, mapping))

    async def expire(self, key: str, ttl_seconds: int) -> None:
        self.expire_calls.append((key, ttl_seconds))


class _FakeInterceptor:
    async def get_historical_series_batch(self, symbols, timeframe):
        assert timeframe == "1h"
        return {
            symbols[0]: pd.DataFrame(
                {"timestamp": [1_700_000_000_000], "value": [12.5]}
            ),
            symbols[1]: pd.DataFrame({"timestamp": [1_700_000_000], "value": [-0.01]}),
        }


@pytest.mark.asyncio
async def test_derivatives_worker_preserves_valkey_publish_and_normalizes_db_rows(
    monkeypatch,
) -> None:
    derivatives = [
        {
            "symbol": "BINANCE:BTCUSDT_OI",
            "short_name": "BTC OI",
            "data_type": "open_interest",
            "asset": "BTCUSDT",
        },
        {
            "symbol": "BINANCE:BTCUSDT_FUNDING",
            "short_name": "BTC funding",
            "data_type": "funding_rate",
            "asset": "BTCUSDT",
        },
    ]

    def config_get(key: str, default=None):
        return {
            "tradingview.derivatives": derivatives,
            "tradingview.timeframe": "1h",
            "tradingview.staleness_ttl_seconds": 1800,
        }.get(key, default)

    connection = _FakeConnection()
    redis = _FakeRedis()
    monkeypatch.setattr(
        tradingview_worker,
        "config_manager",
        SimpleNamespace(get=config_get),
    )
    monkeypatch.setattr(
        tradingview_worker,
        "_write_runtime_status",
        AsyncMock(),
    )

    await tradingview_worker.fetch_tv_derivatives(
        {
            "redis": redis,
            "db_pool": _FakePool(connection),
            "tv_interceptor": _FakeInterceptor(),
        }
    )

    assert [key for key, _mapping in redis.hset_calls] == [
        "derivatives:latest:BTCUSDT:oi",
        "derivatives:latest:BTCUSDT:funding",
    ]
    assert [key for key, _ttl in redis.expire_calls] == [
        "derivatives:latest:BTCUSDT:oi",
        "derivatives:latest:BTCUSDT:funding",
    ]
    expected = datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)
    assert connection.calls[0][1][0][0] == expected
    assert connection.calls[1][1][0][0] == expected
    assert all(isinstance(rows[0][0], datetime) for _query, rows in connection.calls)
