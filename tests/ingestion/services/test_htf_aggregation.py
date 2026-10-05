from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

import pytest

from apps.ingestion_app.domain.candle import CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.storage.repository import CandleCommitStatus
from libs.common.exceptions import DataIngestionError

ORIGIN = datetime(1970, 1, 5, tzinfo=UTC)
BASE_LANE = MarketLane("binance", "BTC-HTF-TEST-PERP", "1m")


def _candle(
    open_time: datetime,
    *,
    open_price: Decimal = Decimal(100),
    high: Decimal = Decimal(101),
    low: Decimal = Decimal(99),
    close: Decimal = Decimal(100),
    volume: Decimal = Decimal(1),
    taker_buy_base: Decimal | None = Decimal(1),
    lane: MarketLane = BASE_LANE,
    source_type: Literal["provider", "derived"] = "provider",
) -> CanonicalCandle:
    return CanonicalCandle(
        lane=lane,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=1),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        taker_buy_base=taker_buy_base,
        source_type=source_type,
        source_provider="binance_native" if source_type == "provider" else None,
        source_timeframe="1m" if source_type == "derived" else None,
    )


class _Repository:
    def __init__(
        self,
        candles_by_range: dict[tuple[datetime, datetime], tuple[CanonicalCandle, ...]]
        | None = None,
        *,
        earlier: tuple[CanonicalCandle, ...] = (),
    ) -> None:
        self.candles_by_range = candles_by_range or {}
        # Stored candles that no range read returns; they are what
        # fetch_latest_candle can find before a bucket.
        self.earlier = earlier
        # Every read in call order, whichever method made it.
        self.calls: list[tuple[MarketLane, datetime, datetime]] = []
        self.candle_calls: list[tuple[MarketLane, datetime, datetime]] = []
        self.open_time_calls: list[tuple[MarketLane, datetime, datetime]] = []
        # Latest-candle reads, kept apart so assertions on `calls` are unchanged.
        self.latest_calls: list[tuple[MarketLane, datetime]] = []

    async def fetch_latest_candle(
        self,
        *,
        lane: MarketLane,
        before: datetime,
    ) -> CanonicalCandle | None:
        self.latest_calls.append((lane, before))
        stored = (
            *self.earlier,
            *(
                candle
                for candles in self.candles_by_range.values()
                for candle in candles
            ),
        )
        matches = [
            candle
            for candle in stored
            if candle.lane == lane and candle.close_time <= before
        ]
        return max(matches, key=lambda candle: candle.open_time, default=None)

    async def fetch_candles(
        self,
        *,
        lane: MarketLane,
        since: datetime,
        until: datetime,
    ) -> tuple[CanonicalCandle, ...]:
        self.calls.append((lane, since, until))
        self.candle_calls.append((lane, since, until))
        return self.candles_by_range.get((since, until), ())

    async def fetch_candle_open_times(
        self,
        *,
        lane: MarketLane,
        since: datetime,
        until: datetime,
    ) -> tuple[datetime, ...]:
        self.calls.append((lane, since, until))
        self.open_time_calls.append((lane, since, until))
        return tuple(
            candle.open_time for candle in self.candles_by_range.get((since, until), ())
        )


class _IngestionService:
    def __init__(
        self,
        status: CandleCommitStatus = CandleCommitStatus.INSERTED,
    ) -> None:
        self.status = status
        self.committed: list[CanonicalCandle] = []

    async def commit_candle(self, candle: CanonicalCandle) -> CandleCommitStatus:
        self.committed.append(candle)
        return self.status


def _service(
    repository: _Repository,
    ingestion: _IngestionService | None = None,
) -> tuple[HTFAggregationService, _IngestionService]:
    ingestion = ingestion or _IngestionService()
    return (
        HTFAggregationService(
            repository=repository,  # type: ignore[arg-type]
            ingestion_service=ingestion,  # type: ignore[arg-type]
        ),
        ingestion,
    )


@pytest.mark.asyncio
async def test_alignment_is_generic_and_targets_are_deterministically_ordered() -> None:
    bucket_end = ORIGIN + timedelta(weeks=1)
    base = _candle(bucket_end - timedelta(minutes=1))
    repository = _Repository(earlier=(_candle(ORIGIN - timedelta(minutes=1)),))
    service, _ = _service(repository)
    target_durations = {
        "1w": timedelta(weeks=1),
        "2h": timedelta(hours=2),
        "15m": timedelta(minutes=15),
        "1d": timedelta(days=1),
        "6h": timedelta(hours=6),
        "30m": timedelta(minutes=30),
        "4h": timedelta(hours=4),
        "1h": timedelta(hours=1),
        "12h": timedelta(hours=12),
    }

    requests = await service.process_base_candle(
        base,
        base_duration=timedelta(minutes=1),
        target_durations=target_durations,
        alignment_origin=ORIGIN,
    )

    expected = tuple(
        RecoveryRequest(
            lane=BASE_LANE,
            since=bucket_end - duration,
            until=bucket_end,
            reason=f"htf_incomplete:{timeframe}",
        )
        for timeframe, duration in sorted(
            target_durations.items(), key=lambda item: (item[1], item[0])
        )
    )
    assert requests == expected
    assert [call[1:] for call in repository.calls] == [
        (request.since, request.until) for request in expected
    ]


@pytest.mark.asyncio
async def test_only_bucket_closing_base_candles_trigger_reads() -> None:
    repository = _Repository(
        earlier=(_candle(datetime(2026, 8, 9, 8, 59, tzinfo=UTC)),)
    )
    service, _ = _service(repository)
    target_durations = {"3m": timedelta(minutes=3), "6m": timedelta(minutes=6)}

    await service.process_base_candle(
        _candle(datetime(2026, 8, 9, 9, 0, tzinfo=UTC)),
        base_duration=timedelta(minutes=1),
        target_durations=target_durations,
        alignment_origin=ORIGIN,
    )
    assert repository.calls == []

    await service.process_base_candle(
        _candle(datetime(2026, 8, 9, 9, 2, tzinfo=UTC)),
        base_duration=timedelta(minutes=1),
        target_durations=target_durations,
        alignment_origin=ORIGIN,
    )

    assert [(call[1], call[2]) for call in repository.calls] == [
        (
            datetime(2026, 8, 9, 9, 0, tzinfo=UTC),
            datetime(2026, 8, 9, 9, 3, tzinfo=UTC),
        )
    ]


def _complete_three_minute_bucket(
    *,
    taker_buy_base: tuple[Decimal | None, Decimal | None, Decimal | None] = (
        Decimal(2),
        Decimal(3),
        Decimal(5),
    ),
) -> tuple[datetime, tuple[CanonicalCandle, ...]]:
    bucket_start = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    values = (
        (Decimal(100), Decimal(105), Decimal(99), Decimal(102), Decimal(2)),
        (Decimal(102), Decimal(106), Decimal(101), Decimal(104), Decimal(3)),
        (Decimal(104), Decimal(107), Decimal(103), Decimal(106), Decimal(5)),
    )
    return bucket_start, tuple(
        _candle(
            bucket_start + index * timedelta(minutes=1),
            open_price=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
            taker_buy_base=taker_buy_base[index],
        )
        for index, (open_price, high, low, close, volume) in enumerate(values)
    )


def _derived_candle(
    bucket_start: datetime,
    *,
    timeframe: str = "3m",
    duration: timedelta = timedelta(minutes=3),
) -> CanonicalCandle:
    return CanonicalCandle(
        lane=MarketLane(BASE_LANE.venue, BASE_LANE.instrument_id, timeframe),
        open_time=bucket_start,
        close_time=bucket_start + duration,
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal(100),
        volume=Decimal(3),
        taker_buy_base=Decimal(2),
        source_type="derived",
        source_provider=None,
        source_timeframe="1m",
    )


@pytest.mark.asyncio
async def test_complete_bucket_aggregates_exact_decimal_values_and_provenance() -> None:
    bucket_start, constituents = _complete_three_minute_bucket()
    bucket_end = bucket_start + timedelta(minutes=3)
    repository = _Repository({(bucket_start, bucket_end): constituents})
    service, ingestion = _service(repository)

    requests = await service.process_base_candle(
        constituents[-1],
        base_duration=timedelta(minutes=1),
        target_durations={"3m": timedelta(minutes=3)},
        alignment_origin=ORIGIN,
    )

    assert requests == ()
    assert len(ingestion.committed) == 1
    derived = ingestion.committed[0]
    assert derived.lane == MarketLane("binance", BASE_LANE.instrument_id, "3m")
    assert derived.open_time == bucket_start
    assert derived.close_time == bucket_end
    assert derived.open == Decimal(100)
    assert derived.high == Decimal(107)
    assert derived.low == Decimal(99)
    assert derived.close == Decimal(106)
    assert derived.volume == Decimal(10)
    assert derived.taker_buy_base == Decimal(10)
    assert derived.source_type == "derived"
    assert derived.source_provider is None
    assert derived.source_timeframe == "1m"


@pytest.mark.asyncio
async def test_any_missing_taker_value_remains_none() -> None:
    bucket_start, constituents = _complete_three_minute_bucket(
        taker_buy_base=(Decimal(2), None, Decimal(5))
    )
    bucket_end = bucket_start + timedelta(minutes=3)
    repository = _Repository({(bucket_start, bucket_end): constituents})
    service, ingestion = _service(repository)

    await service.process_base_candle(
        constituents[-1],
        base_duration=timedelta(minutes=1),
        target_durations={"3m": timedelta(minutes=3)},
        alignment_origin=ORIGIN,
    )

    assert ingestion.committed[0].taker_buy_base is None


@pytest.mark.asyncio
async def test_incomplete_bucket_returns_one_recovery_request_without_commit() -> None:
    bucket_start, constituents = _complete_three_minute_bucket()
    bucket_end = bucket_start + timedelta(minutes=3)
    repository = _Repository({(bucket_start, bucket_end): constituents[:2]})
    service, ingestion = _service(repository)

    requests = await service.process_base_candle(
        constituents[-1],
        base_duration=timedelta(minutes=1),
        target_durations={"3m": timedelta(minutes=3)},
        alignment_origin=ORIGIN,
    )

    assert requests == (
        RecoveryRequest(
            lane=BASE_LANE,
            since=bucket_start,
            until=bucket_end,
            reason="htf_incomplete:3m",
        ),
    )
    assert ingestion.committed == []


_THREE_MINUTES = {"3m": timedelta(minutes=3)}
_SIX_MINUTES = {"6m": timedelta(minutes=6)}
_SIX_MINUTE_START = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_incomplete_bucket_with_first_candle_stored_reads_no_history() -> None:
    bucket_start, constituents = _complete_three_minute_bucket()
    bucket_end = bucket_start + timedelta(minutes=3)
    repository = _Repository({(bucket_start, bucket_end): constituents[:2]})
    service, ingestion = _service(repository)

    requests = await service.process_base_candle(
        constituents[-1],
        base_duration=timedelta(minutes=1),
        target_durations=_THREE_MINUTES,
        alignment_origin=ORIGIN,
    )

    assert requests == (
        RecoveryRequest(
            lane=BASE_LANE,
            since=bucket_start,
            until=bucket_end,
            reason="htf_incomplete:3m",
        ),
    )
    assert repository.latest_calls == []
    assert ingestion.committed == []


@pytest.mark.asyncio
async def test_absent_first_candle_with_earlier_stored_candle_is_a_gap() -> None:
    bucket_start, constituents = _complete_three_minute_bucket()
    bucket_end = bucket_start + timedelta(minutes=3)
    repository = _Repository(
        {(bucket_start, bucket_end): constituents[1:]},
        earlier=(_candle(bucket_start - timedelta(minutes=1)),),
    )
    service, ingestion = _service(repository)

    requests = await service.process_base_candle(
        constituents[-1],
        base_duration=timedelta(minutes=1),
        target_durations=_THREE_MINUTES,
        alignment_origin=ORIGIN,
    )

    assert requests == (
        RecoveryRequest(
            lane=BASE_LANE,
            since=bucket_start,
            until=bucket_end,
            reason="htf_incomplete:3m",
        ),
    )
    assert repository.latest_calls == [(BASE_LANE, bucket_start)]
    assert ingestion.committed == []


@pytest.mark.parametrize("stored_from", [1, 2, 3])
@pytest.mark.asyncio
async def test_bucket_beginning_before_stored_history_is_neither_built_nor_requested(
    stored_from: int,
) -> None:
    bucket_start, constituents = _complete_three_minute_bucket()
    bucket_end = bucket_start + timedelta(minutes=3)
    # The stored candles are the trailing part of the bucket's grid; stored_from=3
    # is the case with no constituent at all.
    repository = _Repository({(bucket_start, bucket_end): constituents[stored_from:]})
    service, ingestion = _service(repository)

    requests = await service.process_base_candle(
        constituents[-1],
        base_duration=timedelta(minutes=1),
        target_durations=_THREE_MINUTES,
        alignment_origin=ORIGIN,
    )

    assert requests == ()
    assert ingestion.committed == []
    assert repository.latest_calls == [(BASE_LANE, bucket_start)]


@pytest.mark.parametrize(
    ("stored_minutes", "request_since_minutes"),
    [
        # The first stored candle is 09:02 and 09:04 is missing after it.
        ((2, 3, 5), 2),
        # Both 09:00 and a later candle are missing: the later one still is a gap.
        ((1, 2, 3, 4), 1),
        ((3,), 3),
    ],
)
@pytest.mark.asyncio
async def test_candle_missing_after_first_stored_one_is_requested_from_it(
    stored_minutes: tuple[int, ...],
    request_since_minutes: int,
) -> None:
    bucket_end = _SIX_MINUTE_START + timedelta(minutes=6)
    stored = tuple(
        _candle(_SIX_MINUTE_START + timedelta(minutes=minute))
        for minute in stored_minutes
    )
    repository = _Repository({(_SIX_MINUTE_START, bucket_end): stored})
    service, ingestion = _service(repository)

    requests = await service.reconcile_latest_closed_buckets(
        base_lane=BASE_LANE,
        base_duration=timedelta(minutes=1),
        target_durations=_SIX_MINUTES,
        alignment_origin=ORIGIN,
        as_of=bucket_end,
    )

    assert requests == (
        RecoveryRequest(
            lane=BASE_LANE,
            since=_SIX_MINUTE_START + timedelta(minutes=request_since_minutes),
            until=bucket_end,
            reason="htf_incomplete:6m",
        ),
    )
    assert repository.latest_calls == [(BASE_LANE, _SIX_MINUTE_START)]
    assert ingestion.committed == []


@pytest.mark.parametrize("stored_minutes", [(4, 5), (5,), ()])
@pytest.mark.asyncio
async def test_trailing_part_of_the_grid_is_skipped_by_latest_reconciliation(
    stored_minutes: tuple[int, ...],
) -> None:
    bucket_end = _SIX_MINUTE_START + timedelta(minutes=6)
    stored = tuple(
        _candle(_SIX_MINUTE_START + timedelta(minutes=minute))
        for minute in stored_minutes
    )
    repository = _Repository({(_SIX_MINUTE_START, bucket_end): stored})
    service, ingestion = _service(repository)

    requests = await service.reconcile_latest_closed_buckets(
        base_lane=BASE_LANE,
        base_duration=timedelta(minutes=1),
        target_durations=_SIX_MINUTES,
        alignment_origin=ORIGIN,
        as_of=bucket_end,
    )

    assert requests == ()
    assert ingestion.committed == []
    assert repository.latest_calls == [(BASE_LANE, _SIX_MINUTE_START)]


@pytest.mark.asyncio
async def test_affected_bucket_beginning_before_stored_history_is_skipped() -> None:
    bucket_start, constituents = _complete_three_minute_bucket()
    bucket_end = bucket_start + timedelta(minutes=3)
    repository = _Repository({(bucket_start, bucket_end): constituents[1:]})
    service, ingestion = _service(repository)

    requests = await service.reconcile_affected_buckets(
        base_lane=BASE_LANE,
        base_duration=timedelta(minutes=1),
        target_durations=_THREE_MINUTES,
        alignment_origin=ORIGIN,
        since=bucket_start + timedelta(minutes=1),
        until=bucket_end,
        as_of=bucket_end,
    )

    assert requests == ()
    assert ingestion.committed == []
    assert repository.latest_calls == [(BASE_LANE, bucket_start)]


@pytest.mark.asyncio
async def test_bucket_that_is_complete_is_still_built_without_history_read() -> None:
    bucket_start, constituents = _complete_three_minute_bucket()
    bucket_end = bucket_start + timedelta(minutes=3)
    repository = _Repository({(bucket_start, bucket_end): constituents})
    service, ingestion = _service(repository)

    requests = await service.process_base_candle(
        constituents[-1],
        base_duration=timedelta(minutes=1),
        target_durations=_THREE_MINUTES,
        alignment_origin=ORIGIN,
    )

    assert requests == ()
    assert len(ingestion.committed) == 1
    assert repository.latest_calls == []


@pytest.mark.asyncio
async def test_equal_row_count_with_wrong_grid_does_not_aggregate() -> None:
    bucket_start, constituents = _complete_three_minute_bucket()
    off_grid = _candle(bucket_start + timedelta(seconds=30))
    bucket_end = bucket_start + timedelta(minutes=3)
    repository = _Repository(
        {(bucket_start, bucket_end): (constituents[0], constituents[1], off_grid)}
    )
    service, ingestion = _service(repository)

    with pytest.raises(DataIngestionError):
        await service.process_base_candle(
            constituents[-1],
            base_duration=timedelta(minutes=1),
            target_durations={"3m": timedelta(minutes=3)},
            alignment_origin=ORIGIN,
        )

    assert ingestion.committed == []


@pytest.mark.parametrize(
    "constituent_change",
    [
        {"close_time": datetime(2026, 8, 9, 9, 3, tzinfo=UTC)},
        {
            "source_type": "derived",
            "source_provider": None,
            "source_timeframe": "1m",
        },
    ],
)
@pytest.mark.asyncio
async def test_malformed_constituent_fails_closed(
    constituent_change: dict[str, object],
) -> None:
    bucket_start, constituents = _complete_three_minute_bucket()
    malformed = replace(constituents[1], **constituent_change)
    bucket_end = bucket_start + timedelta(minutes=3)
    repository = _Repository(
        {(bucket_start, bucket_end): (constituents[0], malformed, constituents[2])}
    )
    service, ingestion = _service(repository)

    with pytest.raises(DataIngestionError):
        await service.process_base_candle(
            constituents[-1],
            base_duration=timedelta(minutes=1),
            target_durations={"3m": timedelta(minutes=3)},
            alignment_origin=ORIGIN,
        )
    assert ingestion.committed == []


@pytest.mark.parametrize(
    "changes",
    [
        {"close_time": datetime(2026, 8, 9, 9, 4, tzinfo=UTC)},
        {
            "open_time": datetime(2026, 8, 9, 9, 0, 30, tzinfo=UTC),
            "close_time": datetime(2026, 8, 9, 9, 1, 30, tzinfo=UTC),
        },
    ],
)
@pytest.mark.asyncio
async def test_malformed_base_geometry_fails_closed(
    changes: dict[str, datetime],
) -> None:
    base = _candle(datetime(2026, 8, 9, 9, 2, tzinfo=UTC))
    malformed = replace(base, **changes)
    service, _ = _service(_Repository())

    with pytest.raises(DataIngestionError):
        await service.process_base_candle(
            malformed,
            base_duration=timedelta(minutes=1),
            target_durations={"3m": timedelta(minutes=3)},
            alignment_origin=ORIGIN,
        )


@pytest.mark.asyncio
async def test_duplicate_is_success_and_conflict_raises() -> None:
    bucket_start, constituents = _complete_three_minute_bucket()
    bucket_end = bucket_start + timedelta(minutes=3)

    duplicate_repo = _Repository({(bucket_start, bucket_end): constituents})
    duplicate_service, duplicate_ingestion = _service(
        duplicate_repo,
        _IngestionService(CandleCommitStatus.DUPLICATE),
    )
    assert (
        await duplicate_service.process_base_candle(
            constituents[-1],
            base_duration=timedelta(minutes=1),
            target_durations={"3m": timedelta(minutes=3)},
            alignment_origin=ORIGIN,
        )
        == ()
    )
    assert len(duplicate_ingestion.committed) == 1

    conflict_repo = _Repository({(bucket_start, bucket_end): constituents})
    conflict_service, _ = _service(
        conflict_repo,
        _IngestionService(CandleCommitStatus.CONFLICT),
    )
    with pytest.raises(DataIngestionError, match="conflict"):
        await conflict_service.process_base_candle(
            constituents[-1],
            base_duration=timedelta(minutes=1),
            target_durations={"3m": timedelta(minutes=3)},
            alignment_origin=ORIGIN,
        )


@pytest.mark.asyncio
async def test_reconciliation_reads_exactly_one_latest_bucket_per_target() -> None:
    repository = _Repository(earlier=(_candle(datetime(2026, 8, 9, 8, 0, tzinfo=UTC)),))
    service, _ = _service(repository)
    as_of = datetime(2026, 8, 9, 9, 18, tzinfo=UTC)
    target_durations = {
        "9m": timedelta(minutes=9),
        "3m": timedelta(minutes=3),
        "6m": timedelta(minutes=6),
    }

    requests = await service.reconcile_latest_closed_buckets(
        base_lane=BASE_LANE,
        base_duration=timedelta(minutes=1),
        target_durations=target_durations,
        alignment_origin=ORIGIN,
        as_of=as_of,
    )

    assert len(requests) == 3
    assert [(call[1], call[2]) for call in repository.calls] == [
        (
            datetime(2026, 8, 9, 9, 15, tzinfo=UTC),
            datetime(2026, 8, 9, 9, 18, tzinfo=UTC),
        ),
        (
            datetime(2026, 8, 9, 9, 12, tzinfo=UTC),
            datetime(2026, 8, 9, 9, 18, tzinfo=UTC),
        ),
        (
            datetime(2026, 8, 9, 9, 9, tzinfo=UTC),
            datetime(2026, 8, 9, 9, 18, tzinfo=UTC),
        ),
    ]


@pytest.mark.asyncio
async def test_missing_closed_bucket_between_existing_rows_is_materialized() -> None:
    first_start = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    missing_start = first_start + timedelta(minutes=3)
    last_start = first_start + timedelta(minutes=6)
    last_end = first_start + timedelta(minutes=9)
    _, missing_constituents = _complete_three_minute_bucket()
    missing_constituents = tuple(
        replace(
            candle,
            open_time=candle.open_time + timedelta(minutes=3),
            close_time=candle.close_time + timedelta(minutes=3),
        )
        for candle in missing_constituents
    )
    target_rows = (
        _derived_candle(first_start),
        _derived_candle(last_start),
    )
    repository = _Repository(
        {
            (first_start, last_end): target_rows,
            (missing_start, missing_start + timedelta(minutes=3)): (
                missing_constituents
            ),
        }
    )
    service, ingestion = _service(repository)

    requests = await service.reconcile_missing_closed_buckets(
        base_lane=BASE_LANE,
        base_duration=timedelta(minutes=1),
        target_durations={"3m": timedelta(minutes=3)},
        alignment_origin=ORIGIN,
        since=first_start,
        as_of=last_end,
    )

    assert requests == ()
    assert [candle.open_time for candle in ingestion.committed] == [missing_start]
    assert repository.calls == [
        (
            MarketLane(BASE_LANE.venue, BASE_LANE.instrument_id, "3m"),
            first_start,
            last_end,
        ),
        (BASE_LANE, missing_start, missing_start + timedelta(minutes=3)),
    ]


@pytest.mark.asyncio
async def test_missing_bucket_scan_reads_open_times_and_base_only_for_gaps() -> None:
    first_start = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    missing_start = first_start + timedelta(minutes=3)
    last_start = first_start + timedelta(minutes=6)
    last_end = first_start + timedelta(minutes=9)
    target_lane = MarketLane(BASE_LANE.venue, BASE_LANE.instrument_id, "3m")
    _, constituents = _complete_three_minute_bucket()
    missing_constituents = tuple(
        replace(
            candle,
            open_time=candle.open_time + timedelta(minutes=3),
            close_time=candle.close_time + timedelta(minutes=3),
        )
        for candle in constituents
    )
    repository = _Repository(
        {
            (first_start, last_end): (
                _derived_candle(first_start),
                _derived_candle(last_start),
            ),
            (missing_start, missing_start + timedelta(minutes=3)): (
                missing_constituents
            ),
        }
    )
    service, ingestion = _service(repository)

    requests = await service.reconcile_missing_closed_buckets(
        base_lane=BASE_LANE,
        base_duration=timedelta(minutes=1),
        target_durations={"3m": timedelta(minutes=3)},
        alignment_origin=ORIGIN,
        since=first_start,
        as_of=last_end,
    )

    assert requests == ()
    assert [candle.open_time for candle in ingestion.committed] == [missing_start]
    assert repository.open_time_calls == [(target_lane, first_start, last_end)]
    assert repository.candle_calls == [
        (BASE_LANE, missing_start, missing_start + timedelta(minutes=3))
    ]
    assert target_lane not in {lane for lane, _, _ in repository.candle_calls}


@pytest.mark.asyncio
async def test_existing_closed_buckets_are_not_recommitted() -> None:
    first_start = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    last_end = first_start + timedelta(minutes=9)
    repository = _Repository(
        {
            (first_start, last_end): tuple(
                _derived_candle(first_start + index * timedelta(minutes=3))
                for index in range(3)
            )
        }
    )
    service, ingestion = _service(repository)

    requests = await service.reconcile_missing_closed_buckets(
        base_lane=BASE_LANE,
        base_duration=timedelta(minutes=1),
        target_durations={"3m": timedelta(minutes=3)},
        alignment_origin=ORIGIN,
        since=first_start,
        as_of=last_end,
    )

    assert requests == ()
    assert ingestion.committed == []
    assert repository.calls == [
        (
            MarketLane(BASE_LANE.venue, BASE_LANE.instrument_id, "3m"),
            first_start,
            last_end,
        )
    ]


@pytest.mark.asyncio
async def test_missing_bucket_with_incomplete_base_returns_recovery_request() -> None:
    first_start = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    missing_start = first_start + timedelta(minutes=3)
    last_start = first_start + timedelta(minutes=6)
    last_end = first_start + timedelta(minutes=9)
    _, constituents = _complete_three_minute_bucket()
    incomplete = tuple(
        replace(
            candle,
            open_time=candle.open_time + timedelta(minutes=3),
            close_time=candle.close_time + timedelta(minutes=3),
        )
        for candle in constituents[:2]
    )
    repository = _Repository(
        {
            (first_start, last_end): (
                _derived_candle(first_start),
                _derived_candle(last_start),
            ),
            (missing_start, missing_start + timedelta(minutes=3)): incomplete,
        }
    )
    service, ingestion = _service(repository)

    requests = await service.reconcile_missing_closed_buckets(
        base_lane=BASE_LANE,
        base_duration=timedelta(minutes=1),
        target_durations={"3m": timedelta(minutes=3)},
        alignment_origin=ORIGIN,
        since=first_start,
        as_of=last_end,
    )

    assert requests == (
        RecoveryRequest(
            lane=BASE_LANE,
            since=missing_start,
            until=missing_start + timedelta(minutes=3),
            reason="htf_incomplete:3m",
        ),
    )
    assert ingestion.committed == []


@pytest.mark.asyncio
async def test_unclosed_bucket_is_not_read_or_materialized() -> None:
    bucket_start = datetime(2026, 8, 9, 9, 6, tzinfo=UTC)
    repository = _Repository()
    service, ingestion = _service(repository)

    requests = await service.reconcile_missing_closed_buckets(
        base_lane=BASE_LANE,
        base_duration=timedelta(minutes=1),
        target_durations={"3m": timedelta(minutes=3)},
        alignment_origin=ORIGIN,
        since=bucket_start,
        as_of=bucket_start + timedelta(minutes=2),
    )

    assert requests == ()
    assert repository.calls == []
    assert ingestion.committed == []


@pytest.mark.asyncio
async def test_off_grid_since_starts_at_next_target_bucket() -> None:
    since = datetime(2026, 8, 9, 9, 1, tzinfo=UTC)
    first_start = datetime(2026, 8, 9, 9, 3, tzinfo=UTC)
    last_end = datetime(2026, 8, 9, 9, 9, tzinfo=UTC)
    repository = _Repository(
        {
            (first_start, last_end): (
                _derived_candle(first_start),
                _derived_candle(first_start + timedelta(minutes=3)),
            )
        }
    )
    service, ingestion = _service(repository)

    requests = await service.reconcile_missing_closed_buckets(
        base_lane=BASE_LANE,
        base_duration=timedelta(minutes=1),
        target_durations={"3m": timedelta(minutes=3)},
        alignment_origin=ORIGIN,
        since=since,
        as_of=datetime(2026, 8, 9, 9, 10, tzinfo=UTC),
    )

    assert requests == ()
    assert ingestion.committed == []
    assert repository.calls == [
        (
            MarketLane(BASE_LANE.venue, BASE_LANE.instrument_id, "3m"),
            first_start,
            last_end,
        )
    ]


TARGET_LANE_3M = MarketLane(BASE_LANE.venue, BASE_LANE.instrument_id, "3m")


def _stored_base_candles(start: datetime, count: int) -> tuple[CanonicalCandle, ...]:
    return tuple(
        _candle(start + index * timedelta(minutes=1)) for index in range(count)
    )


def _bucket_constituent_ranges(
    base: tuple[CanonicalCandle, ...],
    first_start: datetime,
    minutes: int,
) -> dict[tuple[datetime, datetime], tuple[CanonicalCandle, ...]]:
    width = timedelta(minutes=minutes)
    ranges: dict[tuple[datetime, datetime], tuple[CanonicalCandle, ...]] = {}
    for index in range(len(base) // minutes):
        start = first_start + index * width
        ranges[(start, start + width)] = base[index * minutes : (index + 1) * minutes]
    return ranges


async def _materialize_three_minute_buckets(
    service: HTFAggregationService,
    *,
    since: datetime,
    before: datetime,
    as_of: datetime,
) -> int:
    return await service.materialize_complete_missing_buckets(
        base_lane=BASE_LANE,
        base_duration=timedelta(minutes=1),
        target_durations={"3m": timedelta(minutes=3)},
        alignment_origin=ORIGIN,
        since=since,
        before=before,
        as_of=as_of,
    )


@pytest.mark.asyncio
async def test_complete_missing_bucket_is_built_without_recovery_request() -> None:
    first_start = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    missing_start = first_start + timedelta(minutes=3)
    before = first_start + timedelta(minutes=9)
    as_of = first_start + timedelta(minutes=30)
    base = _stored_base_candles(first_start, 9)
    repository = _Repository(
        {
            (first_start, before): (
                _derived_candle(first_start),
                _derived_candle(first_start + timedelta(minutes=6)),
            ),
            (first_start, as_of): base,
            (missing_start, missing_start + timedelta(minutes=3)): base[3:6],
        }
    )
    service, ingestion = _service(repository)

    built = await _materialize_three_minute_buckets(
        service, since=first_start, before=before, as_of=as_of
    )

    assert built == 1
    assert [candle.open_time for candle in ingestion.committed] == [missing_start]
    assert ingestion.committed[0].lane == TARGET_LANE_3M
    assert ingestion.committed[0].source_type == "derived"
    assert repository.open_time_calls == [
        (TARGET_LANE_3M, first_start, before),
        (BASE_LANE, first_start, as_of),
    ]
    assert repository.candle_calls == [
        (BASE_LANE, missing_start, missing_start + timedelta(minutes=3))
    ]


@pytest.mark.asyncio
async def test_missing_bucket_with_absent_base_candle_is_left_alone() -> None:
    first_start = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    before = first_start + timedelta(minutes=6)
    as_of = first_start + timedelta(minutes=30)
    base = tuple(
        candle
        for candle in _stored_base_candles(first_start, 6)
        if candle.open_time != first_start + timedelta(minutes=4)
    )
    repository = _Repository(
        {
            (first_start, before): (_derived_candle(first_start),),
            (first_start, as_of): base,
        }
    )
    service, ingestion = _service(repository)

    built = await _materialize_three_minute_buckets(
        service, since=first_start, before=before, as_of=as_of
    )

    assert built == 0
    assert ingestion.committed == []
    assert repository.candle_calls == []
    assert repository.open_time_calls == [
        (TARGET_LANE_3M, first_start, before),
        (BASE_LANE, first_start, as_of),
    ]


@pytest.mark.parametrize(
    ("since", "before", "as_of"),
    [
        # Off-grid since starts at 09:03; before excludes the closed 09:09 bucket.
        (
            datetime(2026, 8, 9, 9, 1, tzinfo=UTC),
            datetime(2026, 8, 9, 9, 9, tzinfo=UTC),
            datetime(2026, 8, 9, 9, 30, tzinfo=UTC),
        ),
        # as_of excludes the 09:09 bucket, which only closes at 09:12.
        (
            datetime(2026, 8, 9, 9, 3, tzinfo=UTC),
            datetime(2026, 8, 9, 9, 30, tzinfo=UTC),
            datetime(2026, 8, 9, 9, 10, tzinfo=UTC),
        ),
    ],
)
@pytest.mark.asyncio
async def test_complete_bucket_scan_honours_since_before_and_as_of(
    since: datetime,
    before: datetime,
    as_of: datetime,
) -> None:
    first_start = datetime(2026, 8, 9, 9, 3, tzinfo=UTC)
    base = _stored_base_candles(first_start, 6)
    repository = _Repository(
        {
            (first_start, first_start + timedelta(minutes=6)): (),
            (since, as_of): base,
            **_bucket_constituent_ranges(base, first_start, 3),
        }
    )
    service, ingestion = _service(repository)

    built = await _materialize_three_minute_buckets(
        service, since=since, before=before, as_of=as_of
    )

    assert built == 2
    assert [candle.open_time for candle in ingestion.committed] == [
        first_start,
        first_start + timedelta(minutes=3),
    ]
    assert repository.open_time_calls == [
        (TARGET_LANE_3M, first_start, first_start + timedelta(minutes=6)),
        (BASE_LANE, since, as_of),
    ]


@pytest.mark.asyncio
async def test_existing_derived_buckets_skip_base_open_time_read() -> None:
    first_start = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    before = first_start + timedelta(minutes=9)
    repository = _Repository(
        {
            (first_start, before): tuple(
                _derived_candle(first_start + index * timedelta(minutes=3))
                for index in range(3)
            )
        }
    )
    service, ingestion = _service(repository)

    built = await _materialize_three_minute_buckets(
        service,
        since=first_start,
        before=before,
        as_of=first_start + timedelta(minutes=30),
    )

    assert built == 0
    assert ingestion.committed == []
    assert repository.open_time_calls == [(TARGET_LANE_3M, first_start, before)]
    assert repository.candle_calls == []


@pytest.mark.asyncio
async def test_base_open_times_are_read_once_across_target_timeframes() -> None:
    first_start = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    before = first_start + timedelta(minutes=12)
    as_of = first_start + timedelta(minutes=30)
    base = _stored_base_candles(first_start, 12)
    repository = _Repository(
        {
            (first_start, before): (),
            (first_start, as_of): base,
            **_bucket_constituent_ranges(base, first_start, 3),
            **_bucket_constituent_ranges(base, first_start, 6),
        }
    )
    service, ingestion = _service(repository)

    built = await service.materialize_complete_missing_buckets(
        base_lane=BASE_LANE,
        base_duration=timedelta(minutes=1),
        target_durations={"6m": timedelta(minutes=6), "3m": timedelta(minutes=3)},
        alignment_origin=ORIGIN,
        since=first_start,
        before=before,
        as_of=as_of,
    )

    assert built == 6
    assert [
        (candle.lane.timeframe, candle.open_time) for candle in ingestion.committed
    ] == [
        ("3m", first_start),
        ("3m", first_start + timedelta(minutes=3)),
        ("3m", first_start + timedelta(minutes=6)),
        ("3m", first_start + timedelta(minutes=9)),
        ("6m", first_start),
        ("6m", first_start + timedelta(minutes=6)),
    ]
    assert [call for call in repository.open_time_calls if call[0] == BASE_LANE] == [
        (BASE_LANE, first_start, as_of)
    ]


@pytest.mark.asyncio
async def test_affected_range_reconciles_closed_bucket_containing_repaired_candle() -> (
    None
):
    bucket_start = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    bucket_end = bucket_start + timedelta(minutes=15)
    constituents = tuple(
        _candle(bucket_start + index * timedelta(minutes=1)) for index in range(15)
    )
    repository = _Repository({(bucket_start, bucket_end): constituents})
    service, ingestion = _service(repository)

    requests = await service.reconcile_affected_buckets(
        base_lane=BASE_LANE,
        base_duration=timedelta(minutes=1),
        target_durations={"15m": timedelta(minutes=15)},
        alignment_origin=ORIGIN,
        since=bucket_start + timedelta(minutes=5),
        until=bucket_start + timedelta(minutes=6),
        as_of=bucket_end + timedelta(minutes=1),
    )

    assert requests == ()
    assert len(ingestion.committed) == 1
    assert ingestion.committed[0].lane == MarketLane(
        BASE_LANE.venue,
        BASE_LANE.instrument_id,
        "15m",
    )


@pytest.mark.asyncio
async def test_affected_open_bucket_is_skipped() -> None:
    bucket_start = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    repository = _Repository()
    service, ingestion = _service(repository)

    requests = await service.reconcile_affected_buckets(
        base_lane=BASE_LANE,
        base_duration=timedelta(minutes=1),
        target_durations={"15m": timedelta(minutes=15)},
        alignment_origin=ORIGIN,
        since=bucket_start + timedelta(minutes=5),
        until=bucket_start + timedelta(minutes=6),
        as_of=bucket_start + timedelta(minutes=14),
    )

    assert requests == ()
    assert repository.calls == []
    assert ingestion.committed == []


@pytest.mark.asyncio
async def test_affected_incomplete_bucket_returns_follow_up_recovery_request() -> None:
    bucket_start = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    bucket_end = bucket_start + timedelta(minutes=15)
    constituents = tuple(
        _candle(bucket_start + index * timedelta(minutes=1)) for index in range(14)
    )
    repository = _Repository({(bucket_start, bucket_end): constituents})
    service, ingestion = _service(repository)

    requests = await service.reconcile_affected_buckets(
        base_lane=BASE_LANE,
        base_duration=timedelta(minutes=1),
        target_durations={"15m": timedelta(minutes=15)},
        alignment_origin=ORIGIN,
        since=bucket_start + timedelta(minutes=5),
        until=bucket_start + timedelta(minutes=6),
        as_of=bucket_end,
    )

    assert requests == (
        RecoveryRequest(
            lane=BASE_LANE,
            since=bucket_start,
            until=bucket_end,
            reason="htf_incomplete:15m",
        ),
    )
    assert ingestion.committed == []


@pytest.mark.parametrize(
    "target_durations",
    [
        {"1m": timedelta(minutes=1)},
        {"5m": timedelta(minutes=5, seconds=1)},
        {"3m": timedelta(minutes=3, seconds=30)},
    ],
)
@pytest.mark.asyncio
async def test_invalid_target_durations_fail_before_reads(
    target_durations: dict[str, timedelta],
) -> None:
    repository = _Repository()
    service, _ = _service(repository)

    with pytest.raises(DataIngestionError):
        await service.process_base_candle(
            _candle(datetime(2026, 8, 9, 9, 2, tzinfo=UTC)),
            base_duration=timedelta(minutes=1),
            target_durations=target_durations,
            alignment_origin=ORIGIN,
        )

    assert repository.calls == []
