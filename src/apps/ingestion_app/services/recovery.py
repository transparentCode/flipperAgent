"""Bounded canonical base-candle recovery through configured REST providers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter

from apps.ingestion_app.domain.candle import CandleObservation, CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.observability import IngestionObservability
from apps.ingestion_app.providers.base import HistoricalCandleProvider
from apps.ingestion_app.services.candle_ingestion import CandleIngestionService
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.services.time_alignment import aligned_bucket_start
from apps.ingestion_app.storage.repository import (
    CandleCommitStatus,
    CandleRepository,
)
from libs.common.enums import SystemComponent
from libs.common.exceptions import DataIngestionError
from libs.common.logging.logger_utils import bind_logger

_LOGGER = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)


@dataclass(slots=True)
class _LaneLockEntry:
    lock: asyncio.Lock
    users: int = 0


def _require_utc(value: object, *, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise DataIngestionError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise DataIngestionError(f"{field_name} must be timezone-aware UTC")


def _require_positive_duration(value: object, *, field_name: str) -> timedelta:
    if not isinstance(value, timedelta) or value <= timedelta(0):
        raise DataIngestionError(f"{field_name} must be a positive timedelta")
    return value


def _require_non_empty_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DataIngestionError(f"{field_name} must be a non-empty string")
    return value


def _require_positive_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value


def _require_non_negative_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _expected_open_times(
    page_start: datetime,
    page_end: datetime,
    base_duration: timedelta,
) -> tuple[datetime, ...]:
    elapsed = page_end - page_start
    if elapsed <= timedelta(0) or elapsed % base_duration != timedelta(0):
        raise DataIngestionError("recovery page interval is not base-grid aligned")
    return tuple(
        page_start + index * base_duration for index in range(elapsed // base_duration)
    )


def _validate_canonical_page(
    rows: tuple[CanonicalCandle, ...],
    *,
    lane: MarketLane,
    page_start: datetime,
    page_end: datetime,
    base_duration: timedelta,
    alignment_origin: datetime,
) -> tuple[bool, int]:
    expected_open_times = _expected_open_times(
        page_start,
        page_end,
        base_duration,
    )
    expected = set(expected_open_times)
    actual: list[datetime] = []
    for row in rows:
        if not isinstance(row, CanonicalCandle):
            raise DataIngestionError("repository returned a non-canonical recovery row")
        if row.lane != lane:
            raise DataIngestionError("canonical recovery row belongs to the wrong lane")
        if row.source_type != "provider":
            raise DataIngestionError(
                "recovery page contains a derived canonical base row"
            )
        if not page_start <= row.open_time < page_end:
            raise DataIngestionError("canonical recovery row is outside its page")
        if row.close_time != row.open_time + base_duration:
            raise DataIngestionError(
                "canonical recovery row close_time does not match base duration"
            )
        if (
            aligned_bucket_start(
                row.open_time,
                base_duration,
                alignment_origin,
            )
            != row.open_time
        ):
            raise DataIngestionError("canonical recovery row is off the base grid")
        if row.open_time not in expected:
            raise DataIngestionError("canonical recovery page contains an extra row")
        actual.append(row.open_time)

    if actual != sorted(actual):
        raise DataIngestionError("canonical recovery rows are not ascending")
    if len(actual) != len(set(actual)):
        raise DataIngestionError("canonical recovery page contains duplicate rows")

    missing_count = len(expected - set(actual))
    return missing_count == 0, missing_count


def _validate_provider_observations(
    observations: tuple[CandleObservation, ...],
    *,
    provider_id: str,
    lane: MarketLane,
    page_start: datetime,
    page_end: datetime,
    base_duration: timedelta,
    alignment_origin: datetime,
    request_started_at: datetime,
    limit: int,
) -> None:
    if not isinstance(observations, tuple):
        raise DataIngestionError("provider returned a non-tuple observation result")
    if len(observations) > limit:
        raise DataIngestionError("provider returned more observations than page limit")

    open_times: list[datetime] = []
    for observation in observations:
        if not isinstance(observation, CandleObservation):
            raise DataIngestionError("provider returned a non-observation result")
        if observation.lane != lane:
            raise DataIngestionError(
                "provider returned an observation for the wrong lane"
            )
        if observation.provider_id != provider_id:
            raise DataIngestionError(
                "provider returned an observation with the wrong provider ID"
            )
        if not page_start <= observation.open_time < page_end:
            raise DataIngestionError(
                "provider returned an observation outside its page"
            )
        if observation.close_time != observation.open_time + base_duration:
            raise DataIngestionError(
                "provider returned an observation with invalid close geometry"
            )
        if observation.close_time > request_started_at:
            raise DataIngestionError(
                "provider returned an observation that was not closed at recovery start"
            )
        if (
            aligned_bucket_start(
                observation.open_time,
                base_duration,
                alignment_origin,
            )
            != observation.open_time
        ):
            raise DataIngestionError("provider returned an off-grid observation")
        open_times.append(observation.open_time)

    if open_times != sorted(open_times):
        raise DataIngestionError("provider observations are not ascending")
    if len(open_times) != len(set(open_times)):
        raise DataIngestionError("provider returned duplicate observations")


def _effective_until(
    *,
    until: datetime,
    base_duration: timedelta,
    alignment_origin: datetime,
    request_started_at: datetime,
) -> datetime:
    last_closed_boundary = aligned_bucket_start(
        request_started_at,
        base_duration,
        alignment_origin,
    )
    if until <= last_closed_boundary:
        if aligned_bucket_start(until, base_duration, alignment_origin) != until:
            raise DataIngestionError(
                "historical recovery until must be aligned to the base grid"
            )
        return until
    return last_closed_boundary


def _page_windows(
    since: datetime,
    until: datetime,
    base_duration: timedelta,
    page_limit: int,
) -> tuple[tuple[datetime, datetime], ...]:
    page_span = base_duration * page_limit
    windows: list[tuple[datetime, datetime]] = []
    page_start = since
    while page_start < until:
        page_end = min(page_start + page_span, until)
        windows.append((page_start, page_end))
        page_start = page_end
    return tuple(windows)


def _deduplicate_requests(
    requests: tuple[RecoveryRequest, ...],
) -> tuple[RecoveryRequest, ...]:
    unique: dict[tuple[str, str, str, datetime, datetime, str], RecoveryRequest] = {}
    for request in requests:
        key = (
            request.lane.venue,
            request.lane.instrument_id,
            request.lane.timeframe,
            request.since,
            request.until,
            request.reason,
        )
        unique[key] = request
    return tuple(
        sorted(
            unique.values(),
            key=lambda request: (
                request.since,
                request.until,
                request.reason,
                request.lane.venue,
                request.lane.instrument_id,
                request.lane.timeframe,
            ),
        )
    )


class RecoveryEngine:
    """Execute one bounded base-candle recovery request at a time per lane."""

    def __init__(
        self,
        *,
        providers: Mapping[str, HistoricalCandleProvider],
        repository: CandleRepository,
        ingestion_service: CandleIngestionService,
        htf_service: HTFAggregationService,
        max_concurrency: int,
        page_limit: int,
        max_attempts_per_provider: int,
        retry_backoff_seconds: int,
        rest_finalization_grace_seconds: int,
        now_fn: Callable[[], datetime] | None = None,
        settlement_sleep_fn: Callable[[float], Awaitable[None]] | None = None,
        observability: IngestionObservability | None = None,
    ) -> None:
        self.providers = dict(providers)
        self.repository = repository
        self.ingestion_service = ingestion_service
        self.htf_service = htf_service
        self.max_concurrency = _require_positive_int(
            max_concurrency,
            field_name="max_concurrency",
        )
        self.page_limit = _require_positive_int(page_limit, field_name="page_limit")
        self.max_attempts_per_provider = _require_positive_int(
            max_attempts_per_provider,
            field_name="max_attempts_per_provider",
        )
        self.retry_backoff_seconds = _require_non_negative_int(
            retry_backoff_seconds,
            field_name="retry_backoff_seconds",
        )
        self.rest_finalization_grace_seconds = _require_non_negative_int(
            rest_finalization_grace_seconds,
            field_name="rest_finalization_grace_seconds",
        )
        if now_fn is not None and not callable(now_fn):
            raise TypeError("now_fn must be callable")
        if settlement_sleep_fn is not None and not callable(settlement_sleep_fn):
            raise TypeError("settlement_sleep_fn must be callable")
        self._now = now_fn or (lambda: datetime.now(UTC))
        self._settlement_sleep = settlement_sleep_fn or asyncio.sleep
        self._semaphore = asyncio.Semaphore(self.max_concurrency)
        self._lane_locks: dict[MarketLane, _LaneLockEntry] = {}
        self.observability = observability or IngestionObservability()

    @asynccontextmanager
    async def _lane_guard(self, lane: MarketLane) -> AsyncIterator[None]:
        entry = self._lane_locks.get(lane)
        if entry is None:
            entry = _LaneLockEntry(lock=asyncio.Lock())
            self._lane_locks[lane] = entry
        entry.users += 1

        try:
            async with entry.lock:
                yield
        finally:
            entry.users -= 1
            if entry.users < 0:
                raise RuntimeError(f"lane lock entry usage underflow for {lane}")
            if entry.users == 0 and self._lane_locks.get(lane) is entry:
                del self._lane_locks[lane]

    def _validate_routes(
        self,
        *,
        provider_order: tuple[str, ...],
        provider_symbols: Mapping[str, str],
    ) -> tuple[tuple[str, HistoricalCandleProvider, str], ...]:
        if not isinstance(provider_order, tuple) or not provider_order:
            raise DataIngestionError("provider_order must be a non-empty tuple")
        if len(provider_order) != len(set(provider_order)):
            raise DataIngestionError("provider_order must not contain duplicates")
        if not isinstance(provider_symbols, Mapping):
            raise DataIngestionError("provider_symbols must be a mapping")

        routes: list[tuple[str, HistoricalCandleProvider, str]] = []
        for provider_id in provider_order:
            _require_non_empty_text(provider_id, field_name="provider ID")
            provider = self.providers.get(provider_id)
            if provider is None:
                raise DataIngestionError(
                    f"recovery provider '{provider_id}' is not configured"
                )
            symbol = provider_symbols.get(provider_id)
            _require_non_empty_text(
                symbol,
                field_name=f"provider symbol for {provider_id}",
            )
            if getattr(provider, "provider_id", None) != provider_id:
                raise DataIngestionError(
                    f"provider route '{provider_id}' does not match provider.provider_id"
                )
            routes.append((provider_id, provider, symbol))
        return tuple(routes)

    async def _read_page(
        self,
        *,
        lane: MarketLane,
        page_start: datetime,
        page_end: datetime,
        base_duration: timedelta,
        alignment_origin: datetime,
    ) -> tuple[bool, int]:
        rows = await self.repository.fetch_candles(
            lane=lane,
            since=page_start,
            until=page_end,
        )
        return _validate_canonical_page(
            rows,
            lane=lane,
            page_start=page_start,
            page_end=page_end,
            base_duration=base_duration,
            alignment_origin=alignment_origin,
        )

    async def _recover_page(
        self,
        *,
        request: RecoveryRequest,
        page_start: datetime,
        page_end: datetime,
        base_duration: timedelta,
        alignment_origin: datetime,
        request_started_at: datetime,
        routes: tuple[tuple[str, HistoricalCandleProvider, str], ...],
    ) -> None:
        complete, _ = await self._read_page(
            lane=request.lane,
            page_start=page_start,
            page_end=page_end,
            base_duration=base_duration,
            alignment_origin=alignment_origin,
        )
        if complete:
            return

        safe_rest_time = page_end + timedelta(
            seconds=self.rest_finalization_grace_seconds
        )
        wait_seconds = (safe_rest_time - self._now()).total_seconds()
        if wait_seconds > 0:
            await self._settlement_sleep(wait_seconds)

        for provider_id, provider, provider_symbol in routes:
            for attempt in range(1, self.max_attempts_per_provider + 1):
                try:
                    observations = await provider.fetch_closed_candles(
                        lane=request.lane,
                        provider_symbol=provider_symbol,
                        timeframe_duration=base_duration,
                        since=page_start,
                        until=page_end,
                        limit=self.page_limit,
                    )
                except DataIngestionError as exc:
                    _LOGGER.warning(
                        "recovery provider attempt failed: provider=%s lane=%s "
                        "page=[%s,%s) attempt=%d/%d error=%s",
                        provider_id,
                        request.lane,
                        page_start,
                        page_end,
                        attempt,
                        self.max_attempts_per_provider,
                        exc,
                    )
                    if attempt < self.max_attempts_per_provider:
                        await asyncio.sleep(self.retry_backoff_seconds)
                    continue

                _validate_provider_observations(
                    observations,
                    provider_id=provider_id,
                    lane=request.lane,
                    page_start=page_start,
                    page_end=page_end,
                    base_duration=base_duration,
                    alignment_origin=alignment_origin,
                    request_started_at=request_started_at,
                    limit=self.page_limit,
                )
                for observation in observations:
                    status = await self.ingestion_service.commit_observation(
                        observation
                    )
                    if status is CandleCommitStatus.CONFLICT:
                        raise DataIngestionError(
                            f"canonical recovery conflict for {request.lane} "
                            f"at {observation.open_time}"
                        )

                complete, _ = await self._read_page(
                    lane=request.lane,
                    page_start=page_start,
                    page_end=page_end,
                    base_duration=base_duration,
                    alignment_origin=alignment_origin,
                )
                if complete:
                    return
                if attempt < self.max_attempts_per_provider:
                    await asyncio.sleep(self.retry_backoff_seconds)

        complete, missing_count = await self._read_page(
            lane=request.lane,
            page_start=page_start,
            page_end=page_end,
            base_duration=base_duration,
            alignment_origin=alignment_origin,
        )
        if not complete:
            raise DataIngestionError(
                f"recovery exhausted for lane {request.lane} page "
                f"[{page_start},{page_end}); missing {missing_count} candles"
            )

    async def _recover_impl(
        self,
        request: RecoveryRequest,
        *,
        base_timeframe: str,
        base_duration: timedelta,
        provider_order: tuple[str, ...],
        provider_symbols: Mapping[str, str],
        target_durations: Mapping[str, timedelta],
        alignment_origin: datetime,
    ) -> tuple[RecoveryRequest, ...]:
        """Repair a bounded base interval and reconcile affected closed HTFs."""
        if not isinstance(request, RecoveryRequest):
            raise DataIngestionError("request must be a RecoveryRequest")
        _require_non_empty_text(base_timeframe, field_name="base_timeframe")
        base_duration = _require_positive_duration(
            base_duration,
            field_name="base_duration",
        )
        _require_utc(alignment_origin, field_name="alignment_origin")
        if request.lane.timeframe != base_timeframe:
            raise DataIngestionError(
                "recovery requests must target the configured base timeframe"
            )
        if (
            aligned_bucket_start(
                request.since,
                base_duration,
                alignment_origin,
            )
            != request.since
        ):
            raise DataIngestionError("recovery since must be aligned to the base grid")
        routes = self._validate_routes(
            provider_order=provider_order,
            provider_symbols=provider_symbols,
        )
        if not isinstance(target_durations, Mapping):
            raise DataIngestionError("target_durations must be a mapping")

        request_started_at = self._now()
        effective_until = _effective_until(
            until=request.until,
            base_duration=base_duration,
            alignment_origin=alignment_origin,
            request_started_at=request_started_at,
        )
        if effective_until <= request.since:
            return ()

        if (
            aligned_bucket_start(
                effective_until,
                base_duration,
                alignment_origin,
            )
            != effective_until
        ):
            raise DataIngestionError(
                "effective recovery until must be aligned to the base grid"
            )

        async with self._lane_guard(request.lane), self._semaphore:
            for page_start, page_end in _page_windows(
                request.since,
                effective_until,
                base_duration,
                self.page_limit,
            ):
                await self._recover_page(
                    request=request,
                    page_start=page_start,
                    page_end=page_end,
                    base_duration=base_duration,
                    alignment_origin=alignment_origin,
                    request_started_at=request_started_at,
                    routes=routes,
                )

            follow_ups = await self.htf_service.reconcile_affected_buckets(
                base_lane=request.lane,
                base_duration=base_duration,
                target_durations=target_durations,
                alignment_origin=alignment_origin,
                since=request.since,
                until=effective_until,
                as_of=request_started_at,
            )
        return _deduplicate_requests(follow_ups)

    async def recover(
        self,
        request: RecoveryRequest,
        *,
        base_timeframe: str,
        base_duration: timedelta,
        provider_order: tuple[str, ...],
        provider_symbols: Mapping[str, str],
        target_durations: Mapping[str, timedelta],
        alignment_origin: datetime,
    ) -> tuple[RecoveryRequest, ...]:
        """Trace and measure one bounded recovery without changing its contract."""
        if not isinstance(request, RecoveryRequest):
            raise DataIngestionError("request must be a RecoveryRequest")
        started = perf_counter()
        with self.observability.recovery_span(request) as span:
            try:
                result = await self._recover_impl(
                    request,
                    base_timeframe=base_timeframe,
                    base_duration=base_duration,
                    provider_order=provider_order,
                    provider_symbols=provider_symbols,
                    target_durations=target_durations,
                    alignment_origin=alignment_origin,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.observability.record_recovery(
                    outcome="failure",
                    duration_ms=(perf_counter() - started) * 1000,
                )
                span.record_exception(exc)
                raise
            else:
                self.observability.record_recovery(
                    outcome="success",
                    duration_ms=(perf_counter() - started) * 1000,
                )
                return result


__all__ = ["RecoveryEngine"]
