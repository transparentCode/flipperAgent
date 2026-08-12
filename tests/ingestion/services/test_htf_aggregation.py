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
    ) -> None:
        self.candles_by_range = candles_by_range or {}
        self.calls: list[tuple[MarketLane, datetime, datetime]] = []

    async def fetch_candles(
        self,
        *,
        lane: MarketLane,
        since: datetime,
        until: datetime,
    ) -> tuple[CanonicalCandle, ...]:
        self.calls.append((lane, since, until))
        return self.candles_by_range.get((since, until), ())


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
    repository = _Repository()
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
    repository = _Repository()
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
        (Decimal(100), Decimal(105), Decimal(99), Decimal(102), Decimal(1)),
        (Decimal(102), Decimal(106), Decimal(101), Decimal(104), Decimal(2)),
        (Decimal(104), Decimal(107), Decimal(103), Decimal(106), Decimal(4)),
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
    assert derived.volume == Decimal(7)
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
    repository = _Repository()
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
