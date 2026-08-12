from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Self

import pytest

from apps.ingestion_app.domain.candle import CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.publication.outbox import build_candle_committed_event
from apps.ingestion_app.storage.repository import (
    CandleCommitStatus,
    CandleRepository,
)

_OPEN_TIME = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)


def _candle(
    *,
    source_type: str = "provider",
    source_provider: str | None = "binance_native",
    source_timeframe: str | None = None,
    taker_buy_base: Decimal | None = Decimal(4),
) -> CanonicalCandle:
    return CanonicalCandle(
        lane=MarketLane("binance", "BTC-TEST-PERP", "1m"),
        open_time=_OPEN_TIME,
        close_time=_OPEN_TIME + timedelta(minutes=1),
        open=Decimal(100),
        high=Decimal(102),
        low=Decimal(99),
        close=Decimal(101),
        volume=Decimal(10),
        taker_buy_base=taker_buy_base,
        source_type=source_type,
        source_provider=source_provider,
        source_timeframe=source_timeframe,
    )


def _row(candle: CanonicalCandle) -> dict[str, object]:
    return {
        "close_time": candle.close_time,
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "volume": candle.volume,
        "taker_buy_base": candle.taker_buy_base,
        "source_type": candle.source_type,
        "source_timeframe": candle.source_timeframe,
    }


class _Transaction:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> Self:
        self.connection.transaction_started = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> bool:
        self.rolled_back = exc_type is not None
        self.committed = exc_type is None
        return False


class _Connection:
    def __init__(
        self,
        *,
        inserted: object | None,
        existing: dict[str, object] | None,
        outbox_error: Exception | None = None,
        range_rows: tuple[dict[str, object], ...] = (),
        latest_row: dict[str, object] | None = None,
    ) -> None:
        self.inserted = inserted
        self.existing = existing
        self.outbox_error = outbox_error
        self.range_rows = range_rows
        self.latest_row = latest_row
        self.transaction_started = False
        self.transaction_context = _Transaction(self)
        self.fetches: list[tuple[str, tuple[object, ...]]] = []
        self.executes: list[tuple[str, tuple[object, ...]]] = []

    def transaction(self) -> _Transaction:
        return self.transaction_context

    async def fetchrow(self, query: str, *args: object) -> object | None:
        self.fetches.append((query, args))
        if "RETURNING venue" in query:
            return self.inserted
        if "LIMIT 1" in query:
            return self.latest_row
        return self.existing

    async def fetch(self, query: str, *args: object) -> tuple[dict[str, object], ...]:
        self.fetches.append((query, args))
        return self.range_rows

    async def execute(self, query: str, *args: object) -> None:
        self.executes.append((query, args))
        if "ingestion.outbox" in query and self.outbox_error is not None:
            raise self.outbox_error


class _Acquire:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _Connection:
        return self.connection

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> bool:
        return False


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def acquire(self) -> _Acquire:
        return _Acquire(self.connection)


async def _commit(
    candle: CanonicalCandle,
    connection: _Connection,
) -> CandleCommitStatus:
    repository = CandleRepository(_Pool(connection))
    return await repository.commit_candle(
        candle,
        build_candle_committed_event(candle),
    )


@pytest.mark.asyncio
async def test_new_candle_inserts_candle_and_outbox() -> None:
    connection = _Connection(inserted={"venue": "binance"}, existing=None)

    status = await _commit(_candle(), connection)

    assert status is CandleCommitStatus.INSERTED
    assert connection.transaction_started
    assert connection.transaction_context.committed
    assert not connection.transaction_context.rolled_back
    assert len(connection.executes) == 1
    assert "ingestion.outbox" in connection.executes[0][0]


@pytest.mark.asyncio
async def test_identical_candle_is_duplicate_without_new_outbox() -> None:
    candle = _candle()
    connection = _Connection(inserted=None, existing=_row(candle))

    status = await _commit(candle, connection)

    assert status is CandleCommitStatus.DUPLICATE
    assert connection.transaction_context.committed
    assert connection.executes == []
    assert len(connection.fetches) == 2


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("close_time", _OPEN_TIME + timedelta(minutes=2)),
        ("open", Decimal("100.5")),
        ("high", Decimal(103)),
        ("low", Decimal(98)),
        ("close", Decimal("100.5")),
        ("volume", Decimal(11)),
    ],
)
@pytest.mark.asyncio
async def test_core_content_difference_is_conflict(
    field_name: str,
    value: object,
) -> None:
    candle = _candle()
    existing = _row(candle)
    existing[field_name] = value
    connection = _Connection(inserted=None, existing=existing)

    status = await _commit(candle, connection)

    assert status is CandleCommitStatus.CONFLICT
    assert connection.transaction_context.committed
    assert connection.executes == []


@pytest.mark.asyncio
async def test_source_provider_difference_is_duplicate() -> None:
    candle = _candle(source_provider="binance_native")
    connection = _Connection(inserted=None, existing=_row(candle))

    status = await _commit(
        _candle(source_provider="ccxt_binance"),
        connection,
    )

    assert status is CandleCommitStatus.DUPLICATE
    assert connection.executes == []


@pytest.mark.parametrize(
    ("stored_taker_buy_base", "incoming_taker_buy_base"),
    [(None, Decimal(4)), (Decimal(4), None)],
)
@pytest.mark.asyncio
async def test_missing_taker_value_is_duplicate_without_enrichment(
    stored_taker_buy_base: Decimal | None,
    incoming_taker_buy_base: Decimal | None,
) -> None:
    stored = _candle(taker_buy_base=stored_taker_buy_base)
    connection = _Connection(inserted=None, existing=_row(stored))

    status = await _commit(
        _candle(taker_buy_base=incoming_taker_buy_base),
        connection,
    )

    assert status is CandleCommitStatus.DUPLICATE
    assert connection.executes == []


@pytest.mark.asyncio
async def test_different_present_taker_value_is_conflict() -> None:
    stored = _candle(taker_buy_base=Decimal(4))
    connection = _Connection(
        inserted=None,
        existing=_row(stored) | {"taker_buy_base": Decimal(5)},
    )

    status = await _commit(stored, connection)

    assert status is CandleCommitStatus.CONFLICT
    assert connection.executes == []


@pytest.mark.asyncio
async def test_provider_and_derived_candles_conflict() -> None:
    incoming = _candle(
        source_type="derived",
        source_provider=None,
        source_timeframe="1m",
    )
    connection = _Connection(inserted=None, existing=_row(_candle()))

    status = await _commit(incoming, connection)

    assert status is CandleCommitStatus.CONFLICT
    assert connection.executes == []


@pytest.mark.asyncio
async def test_derived_source_timeframe_difference_is_conflict() -> None:
    incoming = _candle(
        source_type="derived",
        source_provider=None,
        source_timeframe="5m",
    )
    stored = _candle(
        source_type="derived",
        source_provider=None,
        source_timeframe="1m",
    )
    connection = _Connection(inserted=None, existing=_row(stored))

    status = await _commit(incoming, connection)

    assert status is CandleCommitStatus.CONFLICT
    assert connection.executes == []


@pytest.mark.asyncio
async def test_outbox_failure_rolls_back_transaction() -> None:
    connection = _Connection(
        inserted={"venue": "binance"},
        existing=None,
        outbox_error=RuntimeError("outbox failure"),
    )

    with pytest.raises(RuntimeError, match="outbox failure"):
        await _commit(_candle(), connection)

    assert connection.transaction_started
    assert connection.transaction_context.rolled_back
    assert not connection.transaction_context.committed
    assert len(connection.executes) == 1


def _range_row(candle: CanonicalCandle) -> dict[str, object]:
    return {
        "venue": candle.lane.venue,
        "instrument_id": candle.lane.instrument_id,
        "timeframe": candle.lane.timeframe,
        "open_time": candle.open_time,
        "close_time": candle.close_time,
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "volume": candle.volume,
        "taker_buy_base": candle.taker_buy_base,
        "source_type": candle.source_type,
        "source_provider": candle.source_provider,
        "source_timeframe": candle.source_timeframe,
    }


@pytest.mark.asyncio
async def test_fetch_candles_reconstructs_ordered_canonical_rows() -> None:
    first = _candle()
    second = replace(
        first,
        open_time=_OPEN_TIME + timedelta(minutes=1),
        close_time=_OPEN_TIME + timedelta(minutes=2),
        source_type="derived",
        source_provider=None,
        source_timeframe="1m",
    )
    connection = _Connection(
        inserted=None,
        existing=None,
        range_rows=(_range_row(first), _range_row(second)),
    )
    repository = CandleRepository(_Pool(connection))

    rows = await repository.fetch_candles(
        lane=first.lane,
        since=_OPEN_TIME,
        until=_OPEN_TIME + timedelta(minutes=2),
    )

    assert rows == (first, second)
    assert rows[0].open == Decimal(100)
    query, args = connection.fetches[0]
    assert "open_time >= $4" in query
    assert "open_time < $5" in query
    assert "ORDER BY open_time ASC" in query
    assert args == (
        "binance",
        "BTC-TEST-PERP",
        "1m",
        _OPEN_TIME,
        _OPEN_TIME + timedelta(minutes=2),
    )


@pytest.mark.parametrize(
    ("since", "until", "message"),
    [
        (datetime(2026, 8, 9, 9, 0), _OPEN_TIME + timedelta(minutes=1), "since"),  # noqa: DTZ001
        (_OPEN_TIME, datetime(2026, 8, 9, 9, 1), "until"),  # noqa: DTZ001
        (_OPEN_TIME, _OPEN_TIME, "until must be after since"),
    ],
)
@pytest.mark.asyncio
async def test_fetch_candles_rejects_invalid_utc_bounds(
    since: datetime,
    until: datetime,
    message: str,
) -> None:
    connection = _Connection(inserted=None, existing=None)
    repository = CandleRepository(_Pool(connection))

    with pytest.raises((TypeError, ValueError), match=message):
        await repository.fetch_candles(
            lane=MarketLane("binance", "BTC-TEST-PERP", "1m"),
            since=since,
            until=until,
        )

    assert connection.fetches == []


@pytest.mark.asyncio
async def test_fetch_latest_candle_reconstructs_canonical_row() -> None:
    candle = _candle()
    connection = _Connection(
        inserted=None,
        existing=None,
        latest_row=_range_row(candle),
    )
    repository = CandleRepository(_Pool(connection))

    latest = await repository.fetch_latest_candle(
        lane=candle.lane,
        before=candle.close_time,
    )

    assert latest == candle
    query, args = connection.fetches[0]
    assert "close_time <= $4" in query
    assert "ORDER BY open_time DESC" in query
    assert "LIMIT 1" in query
    assert args == (
        "binance",
        "BTC-TEST-PERP",
        "1m",
        candle.close_time,
    )


@pytest.mark.asyncio
async def test_fetch_latest_candle_returns_none_when_no_row_exists() -> None:
    connection = _Connection(inserted=None, existing=None, latest_row=None)
    repository = CandleRepository(_Pool(connection))

    latest = await repository.fetch_latest_candle(
        lane=MarketLane("binance", "BTC-TEST-PERP", "1m"),
        before=_OPEN_TIME,
    )

    assert latest is None


@pytest.mark.parametrize(
    "before",
    [
        datetime(2026, 8, 9, 9, 0),  # noqa: DTZ001
        datetime(2026, 8, 9, 14, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))),
    ],
)
@pytest.mark.asyncio
async def test_fetch_latest_candle_rejects_non_utc_before(before: datetime) -> None:
    connection = _Connection(inserted=None, existing=None)
    repository = CandleRepository(_Pool(connection))

    with pytest.raises((TypeError, ValueError), match="before"):
        await repository.fetch_latest_candle(
            lane=MarketLane("binance", "BTC-TEST-PERP", "1m"),
            before=before,
        )

    assert connection.fetches == []
