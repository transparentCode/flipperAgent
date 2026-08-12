from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from apps.ingestion_app.publication.outbox import OutboxEvent
from apps.ingestion_app.publication.publisher import OutboxPublisher
from apps.ingestion_app.settings import PublicationSettings
from libs.common.exceptions import DataIngestionError

FIXED_NOW = datetime(2026, 8, 9, 9, 5, tzinfo=UTC)


def _settings(
    *,
    batch_size: int = 500,
    idle_sleep_seconds: int = 1,
    error_backoff_seconds: int = 1,
) -> PublicationSettings:
    return PublicationSettings(
        batch_size=batch_size,
        idle_sleep_seconds=idle_sleep_seconds,
        error_backoff_seconds=error_backoff_seconds,
        stream_maxlen=1000,
        stream_approximate=True,
    )


def _event(
    index: int,
    *,
    instrument_id: str | None = None,
    occurred_at: datetime = datetime(2026, 8, 9, 9, 0, tzinfo=UTC),
) -> OutboxEvent:
    payload = {
        "venue": "binance",
        "instrument_id": instrument_id or f"BTC-TEST-{index}",
        "timeframe": "1m",
        "open": str(index),
    }
    return OutboxEvent(
        event_id=uuid4(),
        event_type="candle.committed",
        schema_version=1,
        producer="ingestion",
        occurred_at=occurred_at,
        payload_json=json.dumps(payload, separators=(",", ":"), sort_keys=True),
    )


class _Repository:
    def __init__(
        self,
        events: list[OutboxEvent],
        *,
        mark_error: Exception | None = None,
        mark_block: asyncio.Event | None = None,
        fetch_error: Exception | None = None,
    ) -> None:
        self.pending = list(events)
        self.mark_error = mark_error
        self.mark_block = mark_block
        self.fetch_error = fetch_error
        self.fetch_calls = 0
        self.mark_calls: list[tuple[object, datetime]] = []
        self.fetch_seen = asyncio.Event()

    async def fetch_pending_outbox(self, *, limit: int) -> tuple[OutboxEvent, ...]:
        self.fetch_calls += 1
        self.fetch_seen.set()
        if self.fetch_error is not None:
            error = self.fetch_error
            self.fetch_error = None
            raise error
        return tuple(self.pending[:limit])

    async def mark_outbox_published(
        self,
        *,
        event_id,
        published_at: datetime,
    ) -> bool:
        if self.mark_block is not None:
            await self.mark_block.wait()
        if self.mark_error is not None:
            error = self.mark_error
            self.mark_error = None
            raise error
        self.mark_calls.append((event_id, published_at))
        self.pending = [event for event in self.pending if event.event_id != event_id]
        return True


class _Valkey:
    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.fail_on_call = fail_on_call
        self.calls: list[tuple[str, dict[str, str], int, bool]] = []

    async def xadd(
        self,
        name: str,
        fields: dict[str, str],
        *,
        maxlen: int,
        approximate: bool,
    ) -> str:
        call_number = len(self.calls) + 1
        if self.fail_on_call == call_number:
            raise ConnectionError("Valkey unavailable")
        self.calls.append((name, fields, maxlen, approximate))
        return "1-0"


def _publisher(
    repository: _Repository,
    valkey: _Valkey,
    *,
    settings: PublicationSettings | None = None,
) -> OutboxPublisher:
    return OutboxPublisher(
        repository=repository,  # type: ignore[arg-type]
        valkey_client=valkey,
        publication=settings or _settings(),
        now_fn=lambda: FIXED_NOW,
    )


@pytest.mark.asyncio
async def test_publish_once_xadds_exact_envelope_and_marks_afterward() -> None:
    event = _event(1)
    repository = _Repository([event])
    valkey = _Valkey()
    publisher = _publisher(repository, valkey)

    assert await publisher.publish_once() == 1

    stream, fields, maxlen, approximate = valkey.calls[0]
    assert stream == "stream:ohlcv:ingestion:binance:BTC-TEST-1:1m"
    assert fields == {
        "event_id": str(event.event_id),
        "event_type": "candle.committed",
        "schema_version": "1",
        "producer": "ingestion",
        "occurred_at": "2026-08-09T09:00:00Z",
        "payload": event.payload_json,
    }
    assert (maxlen, approximate) == (1000, True)
    assert repository.mark_calls == [(event.event_id, FIXED_NOW)]


@pytest.mark.asyncio
async def test_publish_once_encodes_delimiter_in_valid_instrument_identity() -> None:
    event = _event(1, instrument_id="BTC:USDT:PERP")
    repository = _Repository([event])
    valkey = _Valkey()

    assert await _publisher(repository, valkey).publish_once() == 1

    assert valkey.calls[0][0] == ("stream:ohlcv:ingestion:binance:BTC%3AUSDT%3APERP:1m")


@pytest.mark.asyncio
async def test_xadd_failure_leaves_event_unmarked() -> None:
    event = _event(1)
    repository = _Repository([event])
    publisher = _publisher(repository, _Valkey(fail_on_call=1))

    with pytest.raises(ConnectionError, match="Valkey unavailable"):
        await publisher.publish_once()

    assert repository.mark_calls == []
    assert repository.pending == [event]


@pytest.mark.asyncio
async def test_db_mark_failure_allows_same_event_to_publish_again() -> None:
    event = _event(1)
    repository = _Repository([event], mark_error=RuntimeError("database down"))
    valkey = _Valkey()
    publisher = _publisher(repository, valkey)

    with pytest.raises(RuntimeError, match="database down"):
        await publisher.publish_once()
    assert repository.pending == [event]

    assert await publisher.publish_once() == 1
    assert len(valkey.calls) == 2
    assert valkey.calls[0][1]["event_id"] == valkey.calls[1][1]["event_id"]


@pytest.mark.asyncio
async def test_cancellation_after_xadd_does_not_mark_event() -> None:
    event = _event(1)
    mark_block = asyncio.Event()
    repository = _Repository([event], mark_block=mark_block)
    valkey = _Valkey()
    publisher = _publisher(repository, valkey)

    task = asyncio.create_task(publisher.publish_once())
    await asyncio.wait_for(repository.fetch_seen.wait(), timeout=1)
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(valkey.calls) == 1
    assert repository.mark_calls == []
    assert repository.pending == [event]


@pytest.mark.asyncio
async def test_publication_stops_on_first_failed_event() -> None:
    events = [_event(1), _event(2), _event(3)]
    repository = _Repository(events)
    valkey = _Valkey(fail_on_call=2)
    publisher = _publisher(repository, valkey)

    with pytest.raises(ConnectionError):
        await publisher.publish_once()

    assert [call[1]["event_id"] for call in valkey.calls] == [str(events[0].event_id)]
    assert repository.mark_calls == [(events[0].event_id, FIXED_NOW)]
    assert repository.pending == events[1:]


@pytest.mark.asyncio
async def test_run_checks_again_immediately_after_non_empty_batch() -> None:
    event = _event(1)
    repository = _Repository([event])
    valkey = _Valkey()
    publisher = _publisher(repository, valkey)
    task = asyncio.create_task(publisher.run())

    await asyncio.wait_for(repository.fetch_seen.wait(), timeout=1)
    while repository.fetch_calls < 2:
        await asyncio.sleep(0)
    publisher.stop()
    await asyncio.wait_for(task, timeout=1)

    assert repository.fetch_calls >= 2
    assert len(valkey.calls) == 1


@pytest.mark.asyncio
async def test_run_stop_interrupts_idle_wait() -> None:
    repository = _Repository([])
    publisher = _publisher(
        repository,
        _Valkey(),
        settings=_settings(idle_sleep_seconds=10),
    )
    task = asyncio.create_task(publisher.run())
    await asyncio.wait_for(repository.fetch_seen.wait(), timeout=1)

    publisher.stop()
    await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_run_waits_after_empty_batch_instead_of_spinning() -> None:
    repository = _Repository([])
    publisher = _publisher(
        repository,
        _Valkey(),
        settings=_settings(idle_sleep_seconds=1),
    )
    task = asyncio.create_task(publisher.run())
    await asyncio.wait_for(repository.fetch_seen.wait(), timeout=1)
    await asyncio.sleep(0)

    assert repository.fetch_calls == 1
    publisher.stop()
    await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_run_failure_uses_error_path_and_stop_is_responsive() -> None:
    repository = _Repository([], fetch_error=ConnectionError("database down"))
    publisher = _publisher(
        repository,
        _Valkey(),
        settings=_settings(error_backoff_seconds=10),
    )
    task = asyncio.create_task(publisher.run())
    await asyncio.wait_for(repository.fetch_seen.wait(), timeout=1)

    publisher.stop()
    await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_run_probes_idle_broker_and_notifies_on_reconnect() -> None:
    class _PingValkey(_Valkey):
        def __init__(self) -> None:
            super().__init__()
            self.ping_calls = 0

        async def ping(self) -> bool:
            self.ping_calls += 1
            if self.ping_calls == 1:
                raise ConnectionError("Valkey unavailable")
            return True

    reconnected = asyncio.Event()
    valkey = _PingValkey()
    publisher = OutboxPublisher(
        repository=_Repository([]),
        valkey_client=valkey,
        publication=_settings(idle_sleep_seconds=1, error_backoff_seconds=1),
        on_connection_restored=reconnected.set,
    )
    task = asyncio.create_task(publisher.run())

    await asyncio.wait_for(reconnected.wait(), timeout=3)
    publisher.stop()
    await asyncio.wait_for(task, timeout=1)
    assert valkey.ping_calls >= 2


@pytest.mark.asyncio
async def test_run_cancellation_propagates() -> None:
    repository = _Repository([], fetch_error=asyncio.CancelledError())
    publisher = _publisher(repository, _Valkey())
    task = asyncio.create_task(publisher.run())

    await asyncio.wait_for(repository.fetch_seen.wait(), timeout=1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_mark_miss_fails_after_successful_xadd() -> None:
    event = _event(1)

    class _MarkMissRepository(_Repository):
        async def mark_outbox_published(self, *, event_id, published_at):
            return False

    repository = _MarkMissRepository([event])
    valkey = _Valkey()
    publisher = _publisher(repository, valkey)

    with pytest.raises(DataIngestionError, match="mark miss"):
        await publisher.publish_once()

    assert len(valkey.calls) == 1
