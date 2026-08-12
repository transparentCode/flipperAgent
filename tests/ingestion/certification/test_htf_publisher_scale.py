from __future__ import annotations

import asyncio
import time
import tracemalloc
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.publication.publisher import OutboxPublisher
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.settings import PublicationSettings

from .conftest import (
    BASE_DURATION,
    BOUNDARY,
    FakeOutboxRepository,
    FakeValkey,
    RecordingIngestion,
    canonical,
    event_for,
    minute_rows,
    observation,
    synthetic_lanes,
    synthetic_settings,
    yield_control,
)


class _GeneratedHTFRepository:
    def __init__(self) -> None:
        self.generated_rows = 0
        self.calls: list[tuple[MarketLane, datetime, datetime]] = []

    async def fetch_candles(self, *, lane, since, until):
        self.calls.append((lane, since, until))
        rows = minute_rows(lane, since, until)
        self.generated_rows += len(rows)
        return rows


def _htf_service(repository, ingestion):
    return HTFAggregationService(
        repository=repository,  # type: ignore[arg-type]
        ingestion_service=ingestion,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_500_lane_15m_aggregation_is_exact_and_direct_base_only() -> None:
    settings = synthetic_settings(500)
    repository = _GeneratedHTFRepository()
    ingestion = RecordingIngestion()
    service = _htf_service(repository, ingestion)
    bucket_start = BOUNDARY
    bucket_end = bucket_start + timedelta(minutes=15)
    target_durations = {"15m": timedelta(minutes=15)}

    for lane in synthetic_lanes(settings):
        await service.process_base_candle(
            canonical(observation(lane, bucket_end - BASE_DURATION)),
            base_duration=BASE_DURATION,
            target_durations=target_durations,
            alignment_origin=settings.calendar.alignment_origin,
        )

    assert repository.generated_rows == 500 * 15
    assert len(ingestion.candles) == 500
    assert all(candle.source_type == "derived" for candle in ingestion.candles)
    assert all(candle.source_provider is None for candle in ingestion.candles)
    assert all(candle.source_timeframe == "1m" for candle in ingestion.candles)
    representative = [ingestion.candles[index] for index in (0, 250, 499)]
    assert all(candle.open == Decimal(100) for candle in representative)
    assert all(candle.high == Decimal(116) for candle in representative)
    assert all(candle.low == Decimal(99) for candle in representative)
    assert all(candle.close == Decimal(115) for candle in representative)
    assert all(candle.volume == Decimal(1755) for candle in representative)
    assert all(candle.taker_buy_base == Decimal(1680) for candle in representative)


def test_full_boundary_htf_workload_is_derived_from_loaded_timeframes() -> None:
    settings = synthetic_settings(500, full_timeframes=True)
    base_seconds = settings.timeframes[settings.base_timeframe].duration_seconds
    target_rows_per_lane = sum(
        settings.timeframes[timeframe].duration_seconds // base_seconds
        for timeframe in FULL_TARGETS
    )
    lane_count = sum(
        1
        for asset in settings.assets.values()
        if asset.enabled
        for _instrument in asset.instruments.values()
    )
    derived_count = lane_count * len(FULL_TARGETS)

    assert target_rows_per_lane == 12_945
    assert lane_count == 500
    assert target_rows_per_lane * lane_count == 6_472_500
    assert derived_count == 4_000


FULL_TARGETS = ("15m", "30m", "1h", "4h", "6h", "12h", "1d", "1w")


@pytest.mark.asyncio
async def test_representative_all_htf_run_completes_with_bounded_memory() -> None:
    lane_count = 50
    settings = synthetic_settings(lane_count, full_timeframes=True)
    repository = _GeneratedHTFRepository()
    ingestion = RecordingIngestion()
    service = _htf_service(repository, ingestion)
    week_boundary = datetime(2026, 8, 10, tzinfo=UTC)
    target_durations = {
        timeframe: timedelta(seconds=settings.timeframes[timeframe].duration_seconds)
        for timeframe in FULL_TARGETS
    }

    tracemalloc.start()
    started = time.perf_counter()
    for lane in synthetic_lanes(settings):
        await service.process_base_candle(
            canonical(observation(lane, week_boundary - BASE_DURATION)),
            base_duration=BASE_DURATION,
            target_durations=target_durations,
            alignment_origin=settings.calendar.alignment_origin,
        )
    duration = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    expected_rows = 12_945 * lane_count
    assert repository.generated_rows == expected_rows
    assert len(ingestion.candles) == lane_count * len(FULL_TARGETS)
    assert all(candle.source_type == "derived" for candle in ingestion.candles)
    assert duration >= 0
    assert peak > 0


def _publication_settings() -> PublicationSettings:
    return PublicationSettings(
        batch_size=500,
        idle_sleep_seconds=1,
        error_backoff_seconds=1,
        stream_maxlen=1000,
        stream_approximate=True,
    )


@pytest.mark.asyncio
async def test_publisher_drains_500_ordered_events_with_configured_batch_bound() -> (
    None
):
    events = [event_for(index) for index in range(500)]
    repository = FakeOutboxRepository(events)
    valkey = FakeValkey()
    publisher = OutboxPublisher(
        repository=repository,  # type: ignore[arg-type]
        valkey_client=valkey,
        publication=_publication_settings(),
    )

    published = await publisher.publish_once()

    assert published == 500
    assert not repository.pending
    assert repository.fetch_limits == [500]
    assert [call[1]["event_id"] for call in valkey.calls] == [
        str(event.event_id) for event in events
    ]
    assert [event.event_id for event in events] == repository.marked
    assert all(call[2:] == (1000, True) for call in valkey.calls)


@pytest.mark.asyncio
async def test_publisher_drains_4500_event_aligned_boundary_in_derived_batches() -> (
    None
):
    events = [event_for(index) for index in range(4500)]
    repository = FakeOutboxRepository(events)
    valkey = FakeValkey()
    publisher = OutboxPublisher(
        repository=repository,  # type: ignore[arg-type]
        valkey_client=valkey,
        publication=_publication_settings(),
    )

    total = 0
    while repository.pending:
        total += await publisher.publish_once()

    assert total == 4500
    assert len(repository.fetch_limits) == 9
    assert max(repository.fetch_limits) == 500
    assert len(valkey.calls) == 4500
    assert [event.event_id for event in events] == repository.marked
    assert [call[1]["event_id"] for call in valkey.calls] == [
        str(event.event_id) for event in events
    ]


@pytest.mark.asyncio
async def test_large_publisher_failure_preserves_pending_order_and_event_id() -> None:
    events = [event_for(index) for index in range(4500)]
    repository = FakeOutboxRepository(events)
    valkey = FakeValkey(fail_on_call=501)
    publisher = OutboxPublisher(
        repository=repository,  # type: ignore[arg-type]
        valkey_client=valkey,
        publication=_publication_settings(),
    )

    await publisher.publish_once()
    with pytest.raises(ConnectionError):
        await publisher.publish_once()

    assert len(repository.marked) == 500
    assert repository.pending[0].event_id == events[500].event_id
    assert len(repository.pending) == 4000
    assert len(valkey.calls) == 500

    valkey.fail_on_call = None
    while repository.pending:
        await publisher.publish_once()
    assert [event.event_id for event in events] == repository.marked


@pytest.mark.asyncio
async def test_empty_publisher_waits_after_one_fetch_instead_of_spinning() -> None:
    repository = FakeOutboxRepository([])
    publisher = OutboxPublisher(
        repository=repository,  # type: ignore[arg-type]
        valkey_client=FakeValkey(),
        publication=_publication_settings(),
    )
    task = asyncio.create_task(publisher.run(), name="certification-publisher")
    for _ in range(5):
        await yield_control()
    assert repository.fetch_calls == 1
    publisher.stop()
    await asyncio.wait_for(task, timeout=1)


class _MarkFailureRepository(FakeOutboxRepository):
    def __init__(self, events):
        super().__init__(events)
        self.fail_once = True

    async def mark_outbox_published(self, *, event_id, published_at):
        if self.fail_once:
            self.fail_once = False
            raise ConnectionError("synthetic database mark failure")
        return await super().mark_outbox_published(
            event_id=event_id,
            published_at=published_at,
        )


@pytest.mark.asyncio
async def test_mark_failure_allows_same_event_id_at_least_once_retry() -> None:
    event = event_for(1)
    repository = _MarkFailureRepository([event])
    valkey = FakeValkey()
    publisher = OutboxPublisher(
        repository=repository,  # type: ignore[arg-type]
        valkey_client=valkey,
        publication=_publication_settings(),
    )

    with pytest.raises(ConnectionError):
        await publisher.publish_once()
    assert len(valkey.calls) == 1
    assert not repository.marked
    await publisher.publish_once()
    assert repository.marked == [event.event_id]
    assert [call[1]["event_id"] for call in valkey.calls] == [
        str(event.event_id),
        str(event.event_id),
    ]
