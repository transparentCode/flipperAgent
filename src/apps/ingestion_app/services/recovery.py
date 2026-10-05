"""Bounded canonical base-candle recovery through configured REST providers."""

from __future__ import annotations

import asyncio
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    Iterator,
    Mapping,
)
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter

from apps.ingestion_app.domain.candle import CandleObservation, CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.domain.time_alignment import aligned_bucket_start, is_aligned
from apps.ingestion_app.observability import IngestionObservability
from apps.ingestion_app.planning import IngestionPlan
from apps.ingestion_app.providers.base import (
    HistoricalCandleProvider,
    ProviderAvailabilityError,
    ProviderRateLimitedError,
    TransportDeadlineExceeded,
)
from apps.ingestion_app.services.candle_ingestion import CandleIngestionService
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.storage.repository import (
    CandleCommitStatus,
    CandleRepository,
)
from libs.common.enums import SystemComponent
from libs.common.exceptions import DataIngestionError
from libs.common.logging.logger_utils import bind_logger

_LOGGER = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)


class RecoveryExhaustedError(DataIngestionError):
    """All configured providers completed but a recovery page is still incomplete.

    ``lane`` names the lane whose recovery failed when the raiser knows it.
    """

    def __init__(self, message: str = "", *, lane: MarketLane | None = None) -> None:
        super().__init__(message)
        self.lane = lane


class RecoveryRateLimitedError(RecoveryExhaustedError):
    """Recovery is paused until the exchange's rate-limit interval expires."""

    def __init__(self, *, retry_after_seconds: float) -> None:
        self.retry_after_seconds = float(retry_after_seconds)
        super().__init__(
            f"recovery provider is rate limited; retry after "
            f"{self.retry_after_seconds:g}s"
        )


@dataclass(slots=True)
class _LaneLockEntry:
    lock: asyncio.Lock
    users: int = 0


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
        if not is_aligned(row.open_time, base_duration, alignment_origin):
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
    if len(observations) > limit:
        raise DataIngestionError("provider returned more observations than page limit")

    open_times: list[datetime] = []
    for observation in observations:
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
        if not is_aligned(observation.open_time, base_duration, alignment_origin):
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
        if not is_aligned(until, base_duration, alignment_origin):
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
) -> Iterator[tuple[datetime, datetime]]:
    page_span = base_duration * page_limit
    page_start = since
    while page_start < until:
        page_end = min(page_start + page_span, until)
        yield page_start, page_end
        page_start = page_end


def _deduplicate_requests(
    requests: tuple[RecoveryRequest, ...],
) -> tuple[RecoveryRequest, ...]:
    unique: dict[tuple[str, str, str, datetime, datetime, str], RecoveryRequest] = {}
    for request in requests:
        unique[_request_key(request)] = request
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


def _request_key(
    request: RecoveryRequest,
) -> tuple[str, str, str, datetime, datetime, str]:
    """Return the stable identity/order key for one closure request."""
    return (
        request.lane.venue,
        request.lane.instrument_id,
        request.lane.timeframe,
        request.since,
        request.until,
        request.reason,
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
        self.max_concurrency = max_concurrency
        self.page_limit = page_limit
        self.max_attempts_per_provider = max_attempts_per_provider
        self.retry_backoff_seconds = retry_backoff_seconds
        self.rest_finalization_grace_seconds = rest_finalization_grace_seconds
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
        routes: list[tuple[str, HistoricalCandleProvider, str]] = []
        for provider_id in provider_order:
            provider = self.providers.get(provider_id)
            if provider is None:
                raise DataIngestionError(
                    f"recovery provider '{provider_id}' is not configured"
                )
            routes.append((provider_id, provider, provider_symbols[provider_id]))
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

        last_provider_error: ProviderAvailabilityError | None = None
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
                except TransportDeadlineExceeded:
                    # Ownership is unresolved at the deadline; retrying or
                    # falling through to another provider could overlap the
                    # still-running SDK operation.
                    raise
                except ProviderRateLimitedError as exc:
                    _LOGGER.warning(
                        "recovery provider rate limited: provider=%s lane=%s "
                        "page=[%s,%s) retry_after=%ss",
                        provider_id,
                        request.lane,
                        page_start,
                        page_end,
                        exc.retry_after_seconds,
                    )
                    raise RecoveryRateLimitedError(
                        retry_after_seconds=exc.retry_after_seconds
                    ) from exc
                except ProviderAvailabilityError as exc:
                    last_provider_error = exc
                    cause = exc.__cause__
                    _LOGGER.warning(
                        "recovery provider attempt failed: provider=%s lane=%s "
                        "page=[%s,%s) attempt=%d/%d cause_type=%s error=%s",
                        provider_id,
                        request.lane,
                        page_start,
                        page_end,
                        attempt,
                        self.max_attempts_per_provider,
                        type(cause).__name__
                        if cause is not None
                        else type(exc).__name__,
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
            error = RecoveryExhaustedError(
                f"recovery exhausted for lane {request.lane} page "
                f"[{page_start},{page_end}); missing {missing_count} candles",
                lane=request.lane,
            )
            if last_provider_error is not None:
                raise error from last_provider_error
            raise error

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
        if request.lane.timeframe != base_timeframe:
            raise DataIngestionError(
                "recovery requests must target the configured base timeframe"
            )
        if not is_aligned(request.since, base_duration, alignment_origin):
            raise DataIngestionError("recovery since must be aligned to the base grid")
        routes = self._validate_routes(
            provider_order=provider_order,
            provider_symbols=provider_symbols,
        )

        request_started_at = self._now()
        effective_until = _effective_until(
            until=request.until,
            base_duration=base_duration,
            alignment_origin=alignment_origin,
            request_started_at=request_started_at,
        )
        if effective_until <= request.since:
            return ()

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

    async def find_history_start(
        self,
        lane: MarketLane,
        *,
        plan: IngestionPlan,
        since: datetime,
        until: datetime,
    ) -> datetime | None:
        """Return the open time of the first closed candle a provider has.

        Probes the lane's providers in order with a one-candle page over
        ``[since, until)``. Returns ``None`` when at least one provider answered
        and none had a candle. Commits nothing and takes no lane lock.
        """
        lane_plan = plan.lanes_by_lane[lane]
        routes = self._validate_routes(
            provider_order=lane_plan.provider_order,
            provider_symbols=lane_plan.provider_symbols,
        )
        request_started_at = self._now()
        last_provider_error: ProviderAvailabilityError | None = None
        answered = False
        for provider_id, provider, provider_symbol in routes:
            for attempt in range(1, self.max_attempts_per_provider + 1):
                try:
                    observations = await provider.fetch_closed_candles(
                        lane=lane,
                        provider_symbol=provider_symbol,
                        timeframe_duration=lane_plan.base_duration,
                        since=since,
                        until=until,
                        limit=1,
                    )
                except TransportDeadlineExceeded:
                    raise
                except ProviderRateLimitedError as exc:
                    raise RecoveryRateLimitedError(
                        retry_after_seconds=exc.retry_after_seconds
                    ) from exc
                except ProviderAvailabilityError as exc:
                    last_provider_error = exc
                    if attempt < self.max_attempts_per_provider:
                        await asyncio.sleep(self.retry_backoff_seconds)
                    continue

                _validate_provider_observations(
                    observations,
                    provider_id=provider_id,
                    lane=lane,
                    page_start=since,
                    page_end=until,
                    base_duration=lane_plan.base_duration,
                    alignment_origin=plan.alignment_origin,
                    request_started_at=request_started_at,
                    limit=1,
                )
                answered = True
                if observations:
                    return observations[0].open_time
                break

        if not answered:
            error = RecoveryExhaustedError(
                f"history-start probe exhausted for lane {lane}",
                lane=lane,
            )
            if last_provider_error is not None:
                raise error from last_provider_error
            raise error
        return None

    async def _recover_closure_request(
        self,
        request: RecoveryRequest,
        *,
        plan: IngestionPlan,
    ) -> tuple[RecoveryRequest, ...]:
        """Run one closure request using the current generation's plan."""
        lane_plan = plan.lanes_by_lane[request.lane]
        return await self.recover(
            request,
            base_timeframe=plan.base_timeframe,
            base_duration=lane_plan.base_duration,
            provider_order=lane_plan.provider_order,
            provider_symbols=lane_plan.provider_symbols,
            target_durations=lane_plan.target_durations,
            alignment_origin=plan.alignment_origin,
        )

    async def _recover_closure_chunk(
        self,
        requests: tuple[RecoveryRequest, ...],
        *,
        plan: IngestionPlan,
    ) -> tuple[tuple[RecoveryRequest, ...], ...]:
        """Execute one bounded chunk and clean up all siblings on failure."""
        tasks: list[asyncio.Task[tuple[RecoveryRequest, ...]]] = []
        try:
            for request in requests:
                tasks.append(
                    asyncio.create_task(
                        self._recover_closure_request(request, plan=plan),
                        name="ingestion-recovery-request",
                    )
                )
            return tuple(await asyncio.gather(*tasks))
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def recover_closure(
        self,
        requests: Iterable[RecoveryRequest],
        *,
        plan: IngestionPlan,
    ) -> None:
        """Close a bounded recovery worklist in deterministic BFS chunks.

        The closure is deliberately scheduled in chunks instead of eagerly
        materializing one task per request.  ``recover`` remains the raw
        single-request primitive and retains the semaphore and lane lock that
        provide the second concurrency bound.
        """
        pending = list(requests)
        seen: set[tuple[str, str, str, datetime, datetime, str]] = set()
        while pending:
            batch_by_key: dict[
                tuple[str, str, str, datetime, datetime, str], RecoveryRequest
            ] = {}
            for request in pending:
                if request.lane not in plan.lanes_by_lane:
                    raise DataIngestionError(
                        f"recovery request targets unknown plan lane: {request.lane}"
                    )
                key = _request_key(request)
                if key not in seen and key not in batch_by_key:
                    batch_by_key[key] = request

            batch = tuple(sorted(batch_by_key.values(), key=_request_key))
            seen.update(_request_key(request) for request in batch)
            if not batch:
                break

            follow_ups: list[RecoveryRequest] = []
            for offset in range(0, len(batch), self.max_concurrency):
                chunk = batch[offset : offset + self.max_concurrency]
                results = await self._recover_closure_chunk(chunk, plan=plan)
                for result in results:
                    follow_ups.extend(result)
            pending = follow_ups


__all__ = [
    "RecoveryEngine",
    "RecoveryExhaustedError",
    "RecoveryRateLimitedError",
]
