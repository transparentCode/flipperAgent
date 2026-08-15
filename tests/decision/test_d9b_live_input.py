from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.decision_app.domain.market_state import (
    BarStore,
    MarketSeriesKey,
    TimeframeGrid,
)
from apps.decision_app.runtime.startup import SeriesStartupPosition
from apps.decision_app.storage.market_history import (
    InMemoryCanonicalMarketHistoryRepository,
)
from apps.decision_app.transport.ingestion import canonical_ingestion_stream_key
from apps.decision_app.transport.live_input import (
    DirectCursorInput,
    compare_stream_ids,
    normalize_stream_id,
)
from libs.contracts.decision import CausalBarView

BASE = datetime(2026, 2, 1, tzinfo=UTC)
GRID = TimeframeGrid(
    alignment_origin=BASE,
    durations={"1h": timedelta(hours=1)},
)


def _key(asset: str = "BTCUSDT") -> MarketSeriesKey:
    return MarketSeriesKey(
        asset=asset,
        venue="binance",
        instrument_id=f"{asset}-PERP",
        timeframe="1h",
    )


def _bar(
    key: MarketSeriesKey, index: int, *, close: int | None = None
) -> CausalBarView:
    opened = BASE + timedelta(hours=index)
    closed = opened + timedelta(hours=1)
    value = Decimal(close if close is not None else 100 + index)
    return CausalBarView(
        timeframe=key.timeframe,
        bar_open_at=opened,
        bar_close_at=closed,
        market_as_of=closed,
        open=value,
        high=value + Decimal(2),
        low=value - Decimal(2),
        close=value + Decimal(1),
        volume=Decimal(10),
        taker_buy_base=Decimal(4),
        closed=True,
    )


def _fields(
    key: MarketSeriesKey, index: int, *, close: int | None = None
) -> dict[str, str]:
    bar = _bar(key, index, close=close)
    payload = {
        "venue": key.venue,
        "instrument_id": key.instrument_id,
        "timeframe": key.timeframe,
        "open_time": bar.bar_open_at.isoformat().replace("+00:00", "Z"),
        "close_time": bar.bar_close_at.isoformat().replace("+00:00", "Z"),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": str(bar.volume),
        "taker_buy_base": str(bar.taker_buy_base),
        "source_type": "provider",
        "source_provider": "test",
        "source_timeframe": None,
    }
    return {
        "event_id": f"event-{index}",
        "event_type": "candle.committed",
        "schema_version": "1",
        "producer": "ingestion",
        "occurred_at": bar.bar_close_at.isoformat().replace("+00:00", "Z"),
        "payload": json.dumps(payload),
    }


class _XRead:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def xread(self, streams, *, count, block):
        self.calls.append((dict(streams), count, block))
        return self.responses.pop(0) if self.responses else []


def _position(
    key: MarketSeriesKey, *, tail: str | None, warm_index: int
) -> SeriesStartupPosition:
    stream = canonical_ingestion_stream_key(key)
    cutoff = _bar(key, warm_index).market_as_of
    return SeriesStartupPosition(
        series_key=key,
        stream_key=stream,
        captured_tail_id=tail,
        captured_tail_market_as_of=(
            None if tail is None else _bar(key, warm_index).market_as_of
        ),
        db_latest_market_as_of=cutoff,
        warm_cutoff=cutoff,
    )


def _reader(
    key: MarketSeriesKey,
    client: _XRead,
    *,
    tail: str | None = "9-0",
    warm_index: int = 0,
    history_indices: tuple[int, ...] = (0,),
) -> DirectCursorInput:
    history = InMemoryCanonicalMarketHistoryRepository(
        {key: tuple(_bar(key, index) for index in history_indices)},
        timeframe_grid=GRID,
    )
    store = BarStore({key: 4})
    for index in history_indices[-4:]:
        store.append(key, _bar(key, index))
    return DirectCursorInput(
        stream_client=client,
        startup_positions={key: _position(key, tail=tail, warm_index=warm_index)},
        bar_store=store,
        history_repository=history,
        timeframe_grid=GRID,
    )


def test_stream_ids_are_normalized_and_compared_numerically() -> None:
    assert normalize_stream_id(b"0002-010") == "2-10"
    assert compare_stream_ids("2-10", "10-0") < 0
    with pytest.raises(ValueError):
        normalize_stream_id("-1-0")


@pytest.mark.asyncio
async def test_none_tail_uses_zero_zero_and_accepts_forward_record() -> None:
    key = _key()
    stream = canonical_ingestion_stream_key(key)
    client = _XRead([[(stream, [(b"10-0", _fields(key, 1))])]])
    reader = _reader(key, client, tail=None)

    batch = await reader.read_once()

    assert client.calls == [({stream: "0-0"}, 10, 1000)]
    result = await reader.accept(batch.records[0])
    assert result.disposition == "INSERTED"
    assert reader.cursor_for(stream).latest_stream_id == "10-0"


@pytest.mark.asyncio
async def test_db_ahead_event_is_represented_without_re_evaluation() -> None:
    key = _key()
    stream = canonical_ingestion_stream_key(key)
    client = _XRead([[(stream, [("10-0", _fields(key, 1))])]])
    reader = _reader(key, client, tail="9-0", warm_index=1, history_indices=(0, 1))

    batch = await reader.read_once()
    result = await reader.accept(batch.records[0])

    assert result.disposition == "ALREADY_REPRESENTED"
    assert reader.cursor_for(stream).latest_market_as_of == _bar(key, 1).market_as_of


@pytest.mark.asyncio
async def test_late_bar_gap_and_conflict_block_without_cursor_advance() -> None:
    key = _key()
    stream = canonical_ingestion_stream_key(key)
    cases = (
        ("late", _fields(key, 1), "RECONSTRUCTION_REQUIRED", (0, 2), (0, 2)),
        ("gap", _fields(key, 3), "RECONSTRUCTION_REQUIRED", (0,), (0,)),
        (
            "conflict",
            _fields(key, 1, close=999),
            "CONFLICT",
            (0, 1),
            (0, 1),
        ),
    )
    for _name, fields, expected, store_indices, history_indices in cases:
        client = _XRead([[(stream, [("10-0", fields)])]])
        reader = _reader(
            key,
            client,
            tail="9-0",
            warm_index=0,
            history_indices=history_indices,
        )
        batch = await reader.read_once()
        before = reader.cursor_for(stream)
        result = await reader.accept(batch.records[0])
        assert result.disposition == expected
        assert reader.cursor_for(stream) == before
        assert stream in reader.blocked_streams


@pytest.mark.asyncio
async def test_non_forward_record_blocks_only_its_stream() -> None:
    first = _key("BTCUSDT")
    second = _key("ETHUSDT")
    first_stream = canonical_ingestion_stream_key(first)
    second_stream = canonical_ingestion_stream_key(second)
    client = _XRead(
        [
            [
                (first_stream, [("9-0", _fields(first, 1))]),
                (second_stream, [("10-0", _fields(second, 1))]),
            ]
        ]
    )
    history = InMemoryCanonicalMarketHistoryRepository(
        {first: (_bar(first, 0),), second: (_bar(second, 0),)},
        timeframe_grid=GRID,
    )
    store = BarStore({first: 3, second: 3})
    store.append(first, _bar(first, 0))
    store.append(second, _bar(second, 0))
    positions = {
        first: _position(first, tail="9-0", warm_index=0),
        second: _position(second, tail="9-0", warm_index=0),
    }
    reader = DirectCursorInput(
        stream_client=client,
        startup_positions=positions,
        bar_store=store,
        history_repository=history,
        timeframe_grid=GRID,
    )

    batch = await reader.read_once()

    assert len(batch.failures) == 1
    assert batch.failures[0].stream_key == first_stream
    assert len(batch.records) == 1
    assert batch.records[0].stream_key == second_stream


@pytest.mark.asyncio
async def test_malformed_xread_entry_returns_deferred_typed_failure() -> None:
    key = _key()
    stream = canonical_ingestion_stream_key(key)
    client = _XRead([[(stream, [("10-0",)])]])
    reader = _reader(key, client)

    batch = await reader.read_once()

    assert not batch.records
    assert batch.failures[0].disposition == "MALFORMED"
    assert stream not in reader.blocked_streams


@pytest.mark.asyncio
async def test_valid_prefix_survives_deferred_malformed_suffix() -> None:
    key = _key()
    stream = canonical_ingestion_stream_key(key)
    malformed = _fields(key, 2)
    malformed["event_type"] = "not-a-candle"
    client = _XRead(
        [
            [
                (
                    stream,
                    [
                        ("10-0", _fields(key, 1)),
                        ("11-0", malformed),
                        ("12-0", _fields(key, 3)),
                    ],
                )
            ]
        ]
    )
    reader = _reader(key, client, tail="9-0", warm_index=0)

    batch = await reader.read_once()

    assert [pending.stream_id for pending in batch.records] == ["10-0"]
    assert [(failure.stream_id, failure.disposition) for failure in batch.failures] == [
        ("11-0", "MALFORMED")
    ]
    accepted = await reader.accept(batch.records[0])
    assert accepted.disposition == "INSERTED"
    assert reader.cursor_for(stream).latest_stream_id == "10-0"
    assert stream not in reader.blocked_streams

    reader.block_stream(stream, batch.failures[0].reason or "malformed input")
    assert reader.blocked_streams[stream]


@pytest.mark.asyncio
async def test_valid_prefix_survives_non_forward_suffix_and_other_stream_continues() -> (
    None
):
    first = _key("BTCUSDT")
    second = _key("ETHUSDT")
    first_stream = canonical_ingestion_stream_key(first)
    second_stream = canonical_ingestion_stream_key(second)
    client = _XRead(
        [
            [
                (
                    first_stream,
                    [
                        ("10-0", _fields(first, 1)),
                        ("10-0", _fields(first, 2)),
                    ],
                ),
                (
                    second_stream,
                    [
                        ("10-0", _fields(second, 1)),
                        ("11-0", _fields(second, 2)),
                    ],
                ),
            ]
        ]
    )
    history = InMemoryCanonicalMarketHistoryRepository(
        {first: (_bar(first, 0),), second: (_bar(second, 0),)},
        timeframe_grid=GRID,
    )
    store = BarStore({first: 4, second: 4})
    store.append(first, _bar(first, 0))
    store.append(second, _bar(second, 0))
    reader = DirectCursorInput(
        stream_client=client,
        startup_positions={
            first: _position(first, tail="9-0", warm_index=0),
            second: _position(second, tail="9-0", warm_index=0),
        },
        bar_store=store,
        history_repository=history,
        timeframe_grid=GRID,
    )

    batch = await reader.read_once()
    first_pending = next(
        pending for pending in batch.records if pending.stream_key == first_stream
    )
    second_pending = [
        pending for pending in batch.records if pending.stream_key == second_stream
    ]
    first_result = await reader.accept(first_pending)
    second_results = [await reader.accept(pending) for pending in second_pending]

    assert first_result.disposition == "INSERTED"
    assert [result.disposition for result in second_results] == [
        "INSERTED",
        "INSERTED",
    ]
    assert reader.cursor_for(first_stream).latest_stream_id == "10-0"
    assert reader.cursor_for(second_stream).latest_stream_id == "11-0"
    assert first_stream not in reader.blocked_streams
    assert second_stream not in reader.blocked_streams


@pytest.mark.asyncio
async def test_retained_reconciled_context_accepts_exact_delayed_stream_duplicates() -> (
    None
):
    key = _key()
    stream = canonical_ingestion_stream_key(key)
    client = _XRead(
        [
            [
                (
                    stream,
                    [
                        ("10-0", _fields(key, 1)),
                        ("11-0", _fields(key, 2)),
                    ],
                )
            ]
        ]
    )
    reader = _reader(
        key,
        client,
        tail="9-0",
        warm_index=0,
        history_indices=(0, 1, 2),
    )

    batch = await reader.read_once()
    results = [await reader.accept(pending) for pending in batch.records]

    assert [result.disposition for result in results] == ["DUPLICATE", "DUPLICATE"]
    assert reader.cursor_for(stream).latest_stream_id == "11-0"
    assert stream not in reader.blocked_streams
    assert not hasattr(reader, "_accepted_records")


@pytest.mark.asyncio
async def test_input_duplicate_bookkeeping_does_not_grow_with_candle_lifetime() -> None:
    key = _key()
    stream = canonical_ingestion_stream_key(key)
    client = _XRead(
        [
            [
                (
                    stream,
                    [(f"{index}-0", _fields(key, index)) for index in range(1, 1001)],
                )
            ]
        ]
    )
    reader = _reader(
        key,
        client,
        tail="0-0",
        warm_index=0,
        history_indices=(0,),
    )

    batch = await reader.read_once()
    results = [await reader.accept(pending) for pending in batch.records]

    assert len(results) == 1000
    assert all(result.disposition == "INSERTED" for result in results)
    assert reader._bar_store.retained_count(key) == 4
    assert not hasattr(reader, "_accepted_records")
