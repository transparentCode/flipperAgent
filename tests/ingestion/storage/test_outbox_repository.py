from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from apps.ingestion_app.publication.outbox import OutboxEvent
from apps.ingestion_app.storage.repository import CandleRepository


class _Connection:
    def __init__(
        self,
        *,
        pending_rows: tuple[dict[str, object], ...] = (),
        marked_event_id: object | None = None,
        deleted_rows: tuple[dict[str, object], ...] = (),
    ) -> None:
        self.pending_rows = pending_rows
        self.marked_event_id = marked_event_id
        self.deleted_rows = deleted_rows
        self.fetch_calls: list[tuple[str, tuple[object, ...]]] = []
        self.fetchval_calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(self, query: str, *args: object):
        self.fetch_calls.append((query, args))
        if "WITH candidates" in query:
            return self.deleted_rows
        return self.pending_rows

    async def fetchval(self, query: str, *args: object):
        self.fetchval_calls.append((query, args))
        return self.marked_event_id


class _Acquire:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _Connection:
        return self.connection

    async def __aexit__(self, exc_type, exc_value, traceback) -> bool:
        return False


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def acquire(self) -> _Acquire:
        return _Acquire(self.connection)


def _event() -> OutboxEvent:
    return OutboxEvent(
        event_id=uuid4(),
        event_type="candle.committed",
        schema_version=1,
        producer="ingestion",
        occurred_at=datetime(2026, 8, 9, 9, 0, 1, 123456, tzinfo=UTC),
        payload_json=json.dumps(
            {
                "venue": "binance",
                "instrument_id": "BTC-TEST-PERP",
                "timeframe": "1m",
                "close": "101.0",
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
    )


def _row(event: OutboxEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "schema_version": event.schema_version,
        "producer": event.producer,
        "occurred_at": event.occurred_at,
        "payload": json.loads(event.payload_json),
    }


@pytest.mark.asyncio
async def test_fetch_pending_outbox_reconstructs_canonical_json() -> None:
    event = _event()
    connection = _Connection(pending_rows=(_row(event),))
    repository = CandleRepository(_Pool(connection))

    result = await repository.fetch_pending_outbox(limit=10)

    assert result == (event,)
    query, args = connection.fetch_calls[0]
    assert "published_at IS NULL" in query
    assert "ORDER BY occurred_at ASC, event_id ASC" in query
    assert "LIMIT $1" in query
    assert args == (10,)
    assert (
        result[0].payload_json
        == '{"close":"101.0","instrument_id":"BTC-TEST-PERP","timeframe":"1m","venue":"binance"}'
    )


@pytest.mark.parametrize("limit", [0, -1, False, "10", 10.0])
@pytest.mark.asyncio
async def test_fetch_pending_outbox_rejects_non_strict_positive_limit(
    limit: object,
) -> None:
    connection = _Connection()
    repository = CandleRepository(_Pool(connection))

    with pytest.raises((TypeError, ValueError), match="limit"):
        await repository.fetch_pending_outbox(limit=limit)  # type: ignore[arg-type]

    assert connection.fetch_calls == []


@pytest.mark.asyncio
async def test_mark_outbox_published_returns_transition() -> None:
    event_id = uuid4()
    published_at = datetime(2026, 8, 9, 9, 1, tzinfo=UTC)
    connection = _Connection(marked_event_id=event_id)
    repository = CandleRepository(_Pool(connection))

    marked = await repository.mark_outbox_published(
        event_id=event_id,
        published_at=published_at,
    )

    assert marked is True
    query, args = connection.fetchval_calls[0]
    assert "published_at IS NULL" in query
    assert "RETURNING event_id" in query
    assert args == (event_id, published_at)


@pytest.mark.asyncio
async def test_mark_outbox_published_false_does_not_overwrite_existing_mark() -> None:
    event_id = uuid4()
    connection = _Connection(marked_event_id=None)
    repository = CandleRepository(_Pool(connection))

    assert (
        await repository.mark_outbox_published(
            event_id=event_id,
            published_at=datetime(2026, 8, 9, 9, 1, tzinfo=UTC),
        )
        is False
    )


@pytest.mark.parametrize(
    ("event_id", "published_at"),
    [
        ("not-a-uuid", datetime(2026, 8, 9, 9, 1, tzinfo=UTC)),
        (uuid4(), datetime(2026, 8, 9, 9, 1)),  # noqa: DTZ001
        (
            uuid4(),
            datetime(
                2026,
                8,
                9,
                14,
                31,
                tzinfo=timezone(timedelta(hours=5, minutes=30)),
            ),
        ),
    ],
)
@pytest.mark.asyncio
async def test_mark_outbox_published_rejects_invalid_arguments(
    event_id: object,
    published_at: datetime,
) -> None:
    connection = _Connection()
    repository = CandleRepository(_Pool(connection))

    with pytest.raises((TypeError, ValueError)):
        await repository.mark_outbox_published(
            event_id=event_id,  # type: ignore[arg-type]
            published_at=published_at,
        )

    assert connection.fetchval_calls == []


@pytest.mark.asyncio
async def test_delete_published_outbox_before_is_bounded_and_ordered() -> None:
    connection = _Connection(
        deleted_rows=({"event_id": uuid4()}, {"event_id": uuid4()})
    )
    repository = CandleRepository(_Pool(connection))
    cutoff = datetime(2026, 8, 10, tzinfo=UTC)

    deleted = await repository.delete_published_outbox_before(
        cutoff=cutoff,
        limit=2,
    )

    assert deleted == 2
    query, args = connection.fetch_calls[0]
    assert "published_at IS NOT NULL" in query
    assert "published_at < $1" in query
    assert "ORDER BY published_at ASC, event_id ASC" in query
    assert "LIMIT $2" in query
    assert args == (cutoff, 2)


@pytest.mark.parametrize(
    ("cutoff", "limit"),
    [
        (datetime(2026, 8, 10), 1),  # noqa: DTZ001
        (datetime(2026, 8, 10, tzinfo=UTC), 0),
        (datetime(2026, 8, 10, tzinfo=UTC), False),
    ],
)
@pytest.mark.asyncio
async def test_delete_published_outbox_before_rejects_invalid_arguments(
    cutoff: datetime,
    limit: object,
) -> None:
    connection = _Connection()
    repository = CandleRepository(_Pool(connection))

    with pytest.raises((TypeError, ValueError)):
        await repository.delete_published_outbox_before(
            cutoff=cutoff,
            limit=limit,  # type: ignore[arg-type]
        )

    assert connection.fetch_calls == []
