"""Materialize configured higher-timeframe candles from canonical base candles."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal

from apps.ingestion_app.domain.candle import CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.domain.time_alignment import aligned_bucket_start, is_aligned
from apps.ingestion_app.services.candle_ingestion import CandleIngestionService
from apps.ingestion_app.storage.repository import (
    CandleCommitStatus,
    CandleRepository,
)
from libs.common.exceptions import DataIngestionError


def _require_positive_duration(value: object, *, field_name: str) -> timedelta:
    if not isinstance(value, timedelta) or value <= timedelta(0):
        raise DataIngestionError(f"{field_name} must be a positive timedelta")
    return value


def _validated_targets(
    *,
    base_timeframe: str,
    base_duration: timedelta,
    target_durations: Mapping[str, timedelta],
) -> tuple[tuple[str, timedelta], ...]:
    if not isinstance(target_durations, Mapping):
        raise DataIngestionError("target_durations must be a mapping")

    targets: list[tuple[str, timedelta]] = []
    for timeframe, duration in target_durations.items():
        if not isinstance(timeframe, str) or not timeframe.strip():
            raise DataIngestionError("target timeframe must be a non-empty string")
        target_duration = _require_positive_duration(
            duration,
            field_name=f"target duration for {timeframe}",
        )
        if timeframe == base_timeframe:
            raise DataIngestionError(
                f"target timeframe '{timeframe}' must differ from base timeframe"
            )
        if target_duration <= base_duration:
            raise DataIngestionError(
                f"target duration for '{timeframe}' must be greater than base duration"
            )
        if target_duration % base_duration != timedelta(0):
            raise DataIngestionError(
                f"target duration for '{timeframe}' must be divisible by base duration"
            )
        targets.append((timeframe, target_duration))

    return tuple(sorted(targets, key=lambda item: (item[1], item[0])))


def _expected_open_times(
    bucket_start: datetime,
    bucket_end: datetime,
    base_duration: timedelta,
) -> tuple[datetime, ...]:
    expected_count = (bucket_end - bucket_start) // base_duration
    return tuple(
        bucket_start + index * base_duration for index in range(expected_count)
    )


def _validate_constituents(
    constituents: tuple[CanonicalCandle, ...],
    *,
    base_lane: MarketLane,
    base_duration: timedelta,
    bucket_start: datetime,
    bucket_end: datetime,
) -> tuple[datetime, ...]:
    for constituent in constituents:
        if constituent.lane != base_lane:
            raise DataIngestionError("HTF constituent belongs to the wrong base lane")
        if constituent.source_type != "provider":
            raise DataIngestionError(
                "HTF aggregation cannot chain derived candle constituents"
            )
        if not bucket_start <= constituent.open_time < bucket_end:
            raise DataIngestionError("HTF constituent is outside its target bucket")
        if constituent.close_time != constituent.open_time + base_duration:
            raise DataIngestionError(
                "HTF constituent close_time does not match base duration"
            )
        if not is_aligned(constituent.open_time, base_duration, bucket_start):
            raise DataIngestionError("HTF constituent open_time is off the base grid")

    return tuple(constituent.open_time for constituent in constituents)


def _build_derived_candle(
    constituents: tuple[CanonicalCandle, ...],
    *,
    base_lane: MarketLane,
    target_timeframe: str,
    base_timeframe: str,
    bucket_start: datetime,
    bucket_end: datetime,
) -> CanonicalCandle:
    first = constituents[0]
    last = constituents[-1]
    taker_buy_values = tuple(constituent.taker_buy_base for constituent in constituents)
    taker_buy_base = (
        None
        if any(value is None for value in taker_buy_values)
        else sum(taker_buy_values, Decimal(0))
    )

    return CanonicalCandle(
        lane=MarketLane(
            base_lane.venue,
            base_lane.instrument_id,
            target_timeframe,
        ),
        open_time=bucket_start,
        close_time=bucket_end,
        open=first.open,
        high=max(constituent.high for constituent in constituents),
        low=min(constituent.low for constituent in constituents),
        close=last.close,
        volume=sum(
            (constituent.volume for constituent in constituents),
            Decimal(0),
        ),
        taker_buy_base=taker_buy_base,
        source_type="derived",
        source_provider=None,
        source_timeframe=base_timeframe,
    )


def _closed_bucket_starts(
    *,
    since: datetime,
    before: datetime,
    as_of: datetime,
    duration: timedelta,
    alignment_origin: datetime,
) -> tuple[datetime, ...]:
    """Return grid bucket starts in [since, before) that are closed by as_of."""
    start = aligned_bucket_start(since, duration, alignment_origin)
    if start < since:
        start += duration
    starts: list[datetime] = []
    while start < before and start + duration <= as_of:
        starts.append(start)
        start += duration
    return tuple(starts)


class HTFAggregationService:
    """Materialize complete HTF buckets directly from canonical base candles."""

    def __init__(
        self,
        *,
        repository: CandleRepository,
        ingestion_service: CandleIngestionService,
    ) -> None:
        self.repository = repository
        self.ingestion_service = ingestion_service

    async def _materialize_bucket(
        self,
        *,
        base_lane: MarketLane,
        base_duration: timedelta,
        target_timeframe: str,
        bucket_start: datetime,
        bucket_end: datetime,
    ) -> RecoveryRequest | None:
        constituents = await self.repository.fetch_candles(
            lane=base_lane,
            since=bucket_start,
            until=bucket_end,
        )
        expected_open_times = _expected_open_times(
            bucket_start,
            bucket_end,
            base_duration,
        )
        actual_open_times = _validate_constituents(
            constituents,
            base_lane=base_lane,
            base_duration=base_duration,
            bucket_start=bucket_start,
            bucket_end=bucket_end,
        )
        if len(actual_open_times) < len(expected_open_times):
            request_since = bucket_start
            if not actual_open_times or actual_open_times[0] != bucket_start:
                # The bucket's first base candle is absent. If any earlier base
                # candle is stored this is a gap in history, repaired as before.
                # If none is, the bucket begins before this lane's stored
                # history: its missing leading candles do not exist, so only a
                # candle missing after the first stored one is still a gap. This
                # relies on one lane's requests being processed in ascending time
                # order under the lane lock (the recovery closure sorts each
                # batch and the lock is FIFO).
                earlier = await self.repository.fetch_latest_candle(
                    lane=base_lane,
                    before=bucket_start,
                )
                if earlier is None:
                    stored_tail = expected_open_times[
                        len(expected_open_times) - len(actual_open_times) :
                    ]
                    if actual_open_times == stored_tail:
                        return None
                    request_since = actual_open_times[0]
            return RecoveryRequest(
                lane=base_lane,
                since=request_since,
                until=bucket_end,
                reason=f"htf_incomplete:{target_timeframe}",
            )
        if len(actual_open_times) > len(expected_open_times):
            raise DataIngestionError(
                f"HTF bucket '{target_timeframe}' contains too many base constituents"
            )
        if actual_open_times != expected_open_times:
            raise DataIngestionError(
                f"HTF bucket '{target_timeframe}' does not match the expected base grid"
            )

        derived = _build_derived_candle(
            constituents,
            base_lane=base_lane,
            target_timeframe=target_timeframe,
            base_timeframe=base_lane.timeframe,
            bucket_start=bucket_start,
            bucket_end=bucket_end,
        )
        status = await self.ingestion_service.commit_candle(derived)
        if status is CandleCommitStatus.CONFLICT:
            raise DataIngestionError(
                f"derived candle conflict for {target_timeframe} at {bucket_start}"
            )
        return None

    async def process_base_candle(
        self,
        candle: CanonicalCandle,
        *,
        base_duration: timedelta,
        target_durations: Mapping[str, timedelta],
        alignment_origin: datetime,
    ) -> tuple[RecoveryRequest, ...]:
        """Process only HTF buckets closed by one committed base candle."""
        if candle.source_type != "provider":
            raise DataIngestionError("HTF aggregation requires a provider base candle")
        targets = _validated_targets(
            base_timeframe=candle.lane.timeframe,
            base_duration=base_duration,
            target_durations=target_durations,
        )
        if candle.close_time != candle.open_time + base_duration:
            raise DataIngestionError(
                "base candle close_time does not match base duration"
            )
        if not is_aligned(candle.open_time, base_duration, alignment_origin):
            raise DataIngestionError("base candle open_time is off the base grid")

        requests: list[RecoveryRequest] = []
        for target_timeframe, target_duration in targets:
            bucket_start = aligned_bucket_start(
                candle.open_time,
                target_duration,
                alignment_origin,
            )
            bucket_end = bucket_start + target_duration
            if candle.close_time != bucket_end:
                continue
            request = await self._materialize_bucket(
                base_lane=candle.lane,
                base_duration=base_duration,
                target_timeframe=target_timeframe,
                bucket_start=bucket_start,
                bucket_end=bucket_end,
            )
            if request is not None:
                requests.append(request)
        return tuple(requests)

    async def reconcile_latest_closed_buckets(
        self,
        *,
        base_lane: MarketLane,
        base_duration: timedelta,
        target_durations: Mapping[str, timedelta],
        alignment_origin: datetime,
        as_of: datetime,
    ) -> tuple[RecoveryRequest, ...]:
        """Recompute exactly one latest closed bucket for every target timeframe."""
        targets = _validated_targets(
            base_timeframe=base_lane.timeframe,
            base_duration=base_duration,
            target_durations=target_durations,
        )

        requests: list[RecoveryRequest] = []
        for target_timeframe, target_duration in targets:
            bucket_end = aligned_bucket_start(
                as_of,
                target_duration,
                alignment_origin,
            )
            bucket_start = bucket_end - target_duration
            request = await self._materialize_bucket(
                base_lane=base_lane,
                base_duration=base_duration,
                target_timeframe=target_timeframe,
                bucket_start=bucket_start,
                bucket_end=bucket_end,
            )
            if request is not None:
                requests.append(request)
        return tuple(requests)

    async def reconcile_missing_closed_buckets(
        self,
        *,
        base_lane: MarketLane,
        base_duration: timedelta,
        target_durations: Mapping[str, timedelta],
        alignment_origin: datetime,
        since: datetime,
        as_of: datetime,
    ) -> tuple[RecoveryRequest, ...]:
        """Build missing closed target buckets inside a bounded time range."""
        targets = _validated_targets(
            base_timeframe=base_lane.timeframe,
            base_duration=base_duration,
            target_durations=target_durations,
        )

        requests: list[RecoveryRequest] = []
        for target_timeframe, target_duration in targets:
            first_start = aligned_bucket_start(
                since,
                target_duration,
                alignment_origin,
            )
            if first_start < since:
                first_start += target_duration
            last_bucket_end = aligned_bucket_start(
                as_of,
                target_duration,
                alignment_origin,
            )
            if first_start >= last_bucket_end:
                continue

            target_lane = MarketLane(
                base_lane.venue,
                base_lane.instrument_id,
                target_timeframe,
            )
            existing_starts = set(
                await self.repository.fetch_candle_open_times(
                    lane=target_lane,
                    since=first_start,
                    until=last_bucket_end,
                )
            )

            bucket_start = first_start
            while bucket_start + target_duration <= as_of:
                bucket_end = bucket_start + target_duration
                if bucket_start not in existing_starts:
                    request = await self._materialize_bucket(
                        base_lane=base_lane,
                        base_duration=base_duration,
                        target_timeframe=target_timeframe,
                        bucket_start=bucket_start,
                        bucket_end=bucket_end,
                    )
                    if request is not None:
                        requests.append(request)
                bucket_start = bucket_end

        return tuple(requests)

    async def materialize_complete_missing_buckets(
        self,
        *,
        base_lane: MarketLane,
        base_duration: timedelta,
        target_durations: Mapping[str, timedelta],
        alignment_origin: datetime,
        since: datetime,
        before: datetime,
        as_of: datetime,
    ) -> int:
        """Build missing closed buckets whose base candles are all already stored.

        Considers buckets that start in ``[since, before)`` and are closed by
        ``as_of``. A bucket with any base candle absent is left alone; no
        recovery request is ever issued. Returns the number of buckets built.
        """
        targets = _validated_targets(
            base_timeframe=base_lane.timeframe,
            base_duration=base_duration,
            target_durations=target_durations,
        )

        built = 0
        base_open_times: tuple[datetime, ...] | None = None
        for target_timeframe, target_duration in targets:
            candidate_starts = _closed_bucket_starts(
                since=since,
                before=before,
                as_of=as_of,
                duration=target_duration,
                alignment_origin=alignment_origin,
            )
            if not candidate_starts:
                continue

            target_lane = MarketLane(
                base_lane.venue,
                base_lane.instrument_id,
                target_timeframe,
            )
            existing_starts = set(
                await self.repository.fetch_candle_open_times(
                    lane=target_lane,
                    since=candidate_starts[0],
                    until=candidate_starts[-1] + target_duration,
                )
            )
            missing_starts = [
                start for start in candidate_starts if start not in existing_starts
            ]
            if not missing_starts:
                continue

            if base_open_times is None:
                base_open_times = await self.repository.fetch_candle_open_times(
                    lane=base_lane,
                    since=since,
                    until=as_of,
                )
            expected_count = target_duration // base_duration
            for start in missing_starts:
                end = start + target_duration
                stored_from = bisect_left(base_open_times, start)
                stored_until = bisect_left(base_open_times, end)
                if stored_until - stored_from != expected_count:
                    continue
                request = await self._materialize_bucket(
                    base_lane=base_lane,
                    base_duration=base_duration,
                    target_timeframe=target_timeframe,
                    bucket_start=start,
                    bucket_end=end,
                )
                if request is None:
                    built += 1

        return built

    async def reconcile_affected_buckets(
        self,
        *,
        base_lane: MarketLane,
        base_duration: timedelta,
        target_durations: Mapping[str, timedelta],
        alignment_origin: datetime,
        since: datetime,
        until: datetime,
        as_of: datetime,
    ) -> tuple[RecoveryRequest, ...]:
        """Reconcile closed target buckets overlapping a bounded base interval."""
        if until <= since:
            raise DataIngestionError("until must be after since")

        targets = _validated_targets(
            base_timeframe=base_lane.timeframe,
            base_duration=base_duration,
            target_durations=target_durations,
        )
        requests: list[RecoveryRequest] = []
        for target_timeframe, target_duration in targets:
            bucket_start = aligned_bucket_start(
                since,
                target_duration,
                alignment_origin,
            )
            while bucket_start < until:
                bucket_end = bucket_start + target_duration
                if bucket_end > since and bucket_end <= as_of:
                    request = await self._materialize_bucket(
                        base_lane=base_lane,
                        base_duration=base_duration,
                        target_timeframe=target_timeframe,
                        bucket_start=bucket_start,
                        bucket_end=bucket_end,
                    )
                    if request is not None:
                        requests.append(request)
                bucket_start = bucket_end

        return tuple(requests)


__all__ = ["HTFAggregationService"]
