from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from libs.common.db.timescale_reader import TimescaleReader


def _reader(records: list[dict[str, object]]) -> tuple[TimescaleReader, AsyncMock]:
    pool = MagicMock()
    connection = AsyncMock()
    connection.fetch.return_value = records
    context = AsyncMock()
    context.__aenter__.return_value = connection
    pool.acquire.return_value = context
    return TimescaleReader(pool), connection


@pytest.mark.asyncio
async def test_timescale_reader_reads_ticks_without_legacy_ohlcv_methods() -> None:
    timestamp = datetime.now(UTC)
    reader, connection = _reader(
        [
            {
                "timestamp": timestamp,
                "symbol": "BTCUSDT",
                "side": "buy",
                "price": 50_000.0,
                "size": 0.1,
            }
        ]
    )

    frame = await reader.get_ticks(
        "BTCUSDT",
        int(timestamp.timestamp() * 1000),
        int(timestamp.timestamp() * 1000),
    )

    assert frame.iloc[0]["price"] == 50_000.0
    assert "FROM ticks" in connection.fetch.await_args.args[0]


@pytest.mark.asyncio
async def test_timescale_reader_reads_open_interest() -> None:
    timestamp = datetime.now(UTC)
    reader, connection = _reader(
        [
            {
                "timestamp": timestamp,
                "symbol": "BTCUSDT",
                "open_interest": 123.4,
            }
        ]
    )

    frame = await reader.get_open_interest(
        "BTCUSDT",
        int(timestamp.timestamp() * 1000),
        int(timestamp.timestamp() * 1000),
    )

    assert frame.iloc[0]["open_interest"] == 123.4
    assert "FROM open_interest" in connection.fetch.await_args.args[0]


@pytest.mark.asyncio
async def test_timescale_reader_reads_latest_l2_features() -> None:
    pool = MagicMock()
    connection = AsyncMock()
    connection.fetchrow.return_value = {
        "bid_ask_imbalance": 0.2,
        "depth_ratio": 1.1,
        "spread_bps": 2.0,
        "depth_decay_bid": 0.3,
        "depth_decay_ask": 0.4,
    }
    context = AsyncMock()
    context.__aenter__.return_value = connection
    pool.acquire.return_value = context

    result = await TimescaleReader(pool).get_latest_l2_features("BTCUSDT")

    assert result == {
        "bid_ask_imbalance": 0.2,
        "depth_ratio": 1.1,
        "spread_bps": 2.0,
        "depth_decay_bid": 0.3,
        "depth_decay_ask": 0.4,
    }
