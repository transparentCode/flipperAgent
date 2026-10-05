"""Runtime composition for the ingestion acquisition and repair loop."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

from apps.ingestion_app.domain.candle import CandleObservation, CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.domain.time_alignment import aligned_bucket_start, is_aligned
from apps.ingestion_app.observability import IngestionObservability
from apps.ingestion_app.planning import IngestionPlan, LanePlan
from apps.ingestion_app.providers.base import (
    LiveCandleProvider,
    LiveStreamInterrupted,
    TransportDeadlineExceeded,
)
from apps.ingestion_app.runtime.state import (
    LaneFault,
    RuntimeState,
    SupervisorSnapshot,
)
from apps.ingestion_app.services.candle_ingestion import (
    CandleIngestionService,
    canonicalize_observation,
)
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.services.recovery import (
    RecoveryEngine,
    RecoveryExhaustedError,
    RecoveryRateLimitedError,
)
from apps.ingestion_app.storage.repository import (
    CandleCommitStatus,
    CandleRepository,
    is_storage_availability_error,
)
from libs.common.enums import SystemComponent
from libs.common.exceptions import DataIngestionError
from libs.common.logging.logger_utils import bind_logger

_LOGGER = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)

# How long an instrument whose history cannot be prepared waits before its next
# background repair attempt. A rate-limit delay longer than this is honoured.
_EXCLUDED_LANE_RETRY_SECONDS = 60.0
_REASON_NO_CLOSED_CANDLE = "no_closed_candle_in_window"
_REASON_RECOVERY_EXHAUSTED = "recovery_exhausted"


class RuntimeSupervisor:
    """Compose bounded recovery, live commits, and HTF processing."""

    def __init__(
        self,
        *,
        plan: IngestionPlan,
        live_provider: LiveCandleProvider,
        repository: CandleRepository,
        ingestion_service: CandleIngestionService,
        htf_service: HTFAggregationService,
        recovery_engine: RecoveryEngine,
        now_fn: Callable[[], datetime] | None = None,
        monotonic_fn: Callable[[], float] | None = None,
        reconnect_sleep_fn: Callable[[float], Awaitable[None]] | None = None,
        repair_sleep_fn: Callable[[float], Awaitable[None]] | None = None,
        observability: IngestionObservability | None = None,
    ) -> None:
        if not plan.lanes:
            raise DataIngestionError("no enabled ingestion runtime lanes")
        if any(
            lane_plan.live_provider_id != live_provider.provider_id
            for lane_plan in plan.lanes
        ):
            raise DataIngestionError(
                "compiled runtime plan contains a live provider not owned by the "
                "injected provider"
            )

        self.plan = plan
        self.live_provider = live_provider
        self.repository = repository
        self.ingestion_service = ingestion_service
        self.htf_service = htf_service
        self.recovery_engine = recovery_engine
        self.observability = observability or IngestionObservability()
        self._now = now_fn or (lambda: datetime.now(UTC))
        self._monotonic = monotonic_fn or time.monotonic
        self._reconnect_sleep = reconnect_sleep_fn or asyncio.sleep
        self._repair_sleep = repair_sleep_fn or asyncio.sleep
        self._contexts = plan.lanes
        self._contexts_by_lane = plan.lanes_by_lane

        self._last_error: str | None = None
        self._fatal_error: str | None = None
        self._fatal_exception: BaseException | None = None
        self._state = RuntimeState.STOPPED
        self._not_live_since = self._monotonic()
        self._stop_requested = False
        self._active_task: asyncio.Task[None] | None = None

        # Lane fault isolation, scoped to this supervisor generation: lanes held
        # out of live ingestion, and those whose background repair succeeded.
        self._excluded: dict[MarketLane, LaneFault] = {}
        self._ready_to_rejoin: set[MarketLane] = set()
        self._admitted: tuple[LanePlan, ...] = self._contexts
        self._admitted_by_lane: dict[MarketLane, LanePlan] = dict(
            self._contexts_by_lane
        )
        self._repair_task: asyncio.Task[None] | None = None
        self._repair_failure: BaseException | None = None
        self._publish_excluded_lanes()

    @property
    def active_lanes(self) -> tuple[MarketLane, ...]:
        return tuple(context.lane for context in self._contexts)

    def snapshot(self) -> SupervisorSnapshot:
        """Return the current status without performing I/O."""
        self._sync_transport_quarantine()
        not_live_seconds = None
        if self._state is not RuntimeState.LIVE and self._not_live_since is not None:
            not_live_seconds = max(0.0, self._monotonic() - self._not_live_since)
        return SupervisorSnapshot(
            state=self._state,
            last_error=self._last_error,
            not_live_seconds=not_live_seconds,
            excluded_lanes=tuple(
                self._excluded[context.lane]
                for context in self._contexts
                if context.lane in self._excluded
            ),
        )

    @property
    def quarantined(self) -> bool:
        self._sync_transport_quarantine()
        return self._fatal_error is not None

    def _sync_transport_quarantine(self) -> None:
        if self._fatal_error is not None:
            return
        if not bool(getattr(self.live_provider, "lifecycle_quarantined", False)):
            return
        quarantine_error = getattr(
            self.live_provider,
            "lifecycle_quarantine_error",
            None,
        )
        if not isinstance(quarantine_error, BaseException):
            quarantine_error = DataIngestionError(
                "ingestion live lifecycle is quarantined"
            )
        self._latch_fatal(quarantine_error)

    def _latch_fatal(self, error: BaseException) -> None:
        if self._fatal_exception is None:
            self._fatal_exception = error
        self._fatal_error = str(error)
        self._last_error = self._fatal_error
        self._set_state(RuntimeState.ERROR)

    def _set_state(self, state: RuntimeState) -> None:
        if self._fatal_error is not None and state is not RuntimeState.ERROR:
            state = RuntimeState.ERROR
        previous_state = self._state
        if state is RuntimeState.LIVE:
            self._not_live_since = None
        elif previous_state is RuntimeState.LIVE or self._not_live_since is None:
            self._not_live_since = self._monotonic()
        self._state = state
        self.observability.set_runtime_live(state is RuntimeState.LIVE)

    def stop(self) -> None:
        """Request intentional shutdown of this one runtime generation."""
        self._sync_transport_quarantine()
        self._stop_requested = True
        if self._fatal_error is None and (
            self._active_task is None or self._active_task.done()
        ):
            self._set_state(RuntimeState.STOPPED)
        self._cancel_active_task()
        _LOGGER.info("ingestion runtime stop requested")

    async def execute_recovery(self, request: RecoveryRequest) -> None:
        """Execute one offline recovery closure without starting the live loop."""
        self._sync_transport_quarantine()
        if self._active_task is not None and not self._active_task.done():
            raise RuntimeError(
                "cannot execute recovery while the supervisor is running"
            )

        if self._fatal_error is not None:
            if self._fatal_exception is not None:
                raise self._fatal_exception
            raise DataIngestionError("ingestion runtime is quarantined")

        self._set_state(RuntimeState.RECOVERING)
        self._last_error = None
        try:
            await self._execute_recovery_closure((request,))
        except asyncio.CancelledError:
            if self._fatal_error is None:
                self._set_state(RuntimeState.STOPPED)
            raise
        except TransportDeadlineExceeded as exc:
            self._latch_fatal(exc)
            raise
        except Exception as exc:
            self._set_state(RuntimeState.ERROR)
            self._last_error = str(exc)
            raise
        else:
            self._set_state(RuntimeState.STOPPED)

    def _cancel_active_task(self) -> None:
        task = self._active_task
        try:
            current_task = asyncio.current_task()
        except RuntimeError:
            current_task = None
        if task is None or task.done() or task is current_task:
            return
        task.cancel()

    def _validate_latest_base_candle(
        self,
        candle: CanonicalCandle,
        *,
        context: LanePlan,
        before: datetime,
    ) -> None:
        if candle.lane != context.lane:
            raise DataIngestionError(
                "latest canonical candle belongs to the wrong lane"
            )
        if candle.source_type != "provider":
            raise DataIngestionError(
                "latest canonical base candle must be provider sourced"
            )
        if candle.close_time <= candle.open_time:
            raise DataIngestionError("latest canonical candle has invalid time bounds")
        if candle.close_time > before:
            raise DataIngestionError(
                "latest canonical candle is after the closed boundary"
            )
        if candle.close_time != candle.open_time + context.base_duration:
            raise DataIngestionError(
                "latest canonical base candle has invalid duration geometry"
            )
        if not is_aligned(
            candle.open_time,
            context.base_duration,
            self.plan.alignment_origin,
        ):
            raise DataIngestionError(
                "latest canonical base candle is off the base grid"
            )

    def _publish_excluded_lanes(self) -> None:
        self.observability.set_lane_exclusions(
            (context.lane for context in self._contexts),
            self._excluded,
        )

    def _exclude_lane(self, lane: MarketLane, *, reason: str, detail: str) -> None:
        now = self._now()
        next_retry_at = now + timedelta(seconds=_EXCLUDED_LANE_RETRY_SECONDS)
        self._excluded[lane] = LaneFault(
            venue=lane.venue,
            instrument_id=lane.instrument_id,
            reason=reason,
            detail=detail,
            excluded_since=now,
            next_retry_at=next_retry_at,
        )
        self._ready_to_rejoin.discard(lane)
        self._publish_excluded_lanes()
        _LOGGER.warning(
            "runtime lane excluded from live ingestion: lane=%s reason=%s "
            "next_retry_at=%s detail=%s",
            lane,
            reason,
            next_retry_at,
            detail,
        )

    def _clear_exclusions(self) -> None:
        self._excluded.clear()
        self._ready_to_rejoin.clear()
        self._publish_excluded_lanes()

    async def _prepare_lanes(
        self,
        contexts: tuple[LanePlan, ...],
        *,
        as_of: datetime,
        boundary: datetime,
        empty_lanes: list[MarketLane],
    ) -> None:
        """Repair base history and closed HTFs of ``contexts`` up to ``boundary``.

        A lane with no closed candle in its startup window is appended to
        ``empty_lanes`` and skipped; the caller decides what that means.
        """
        alignment_origin = self.plan.alignment_origin
        catch_up_requests: list[RecoveryRequest] = []

        for context in contexts:
            latest = await self.repository.fetch_latest_candle(
                lane=context.lane,
                before=boundary,
            )
            if latest is not None:
                self._validate_latest_base_candle(
                    latest,
                    context=context,
                    before=boundary,
                )
                self.observability.record_base_last_close(
                    context.lane,
                    latest.close_time,
                )
            startup_floor = boundary - context.history_floor_duration
            if latest is None:
                first_open = await self.recovery_engine.find_history_start(
                    context.lane,
                    plan=self.plan,
                    since=startup_floor,
                    until=boundary,
                )
                if first_open is None:
                    empty_lanes.append(context.lane)
                    continue
                if first_open > startup_floor:
                    _LOGGER.warning(
                        "runtime lane history starts after the startup "
                        "floor: lane=%s floor=%s first_candle=%s "
                        "shortfall=%s",
                        context.lane,
                        startup_floor,
                        first_open,
                        first_open - startup_floor,
                    )
                since = first_open
            else:
                if latest.close_time < startup_floor:
                    _LOGGER.warning(
                        "runtime startup catch-up bounded: lane=%s latest_close=%s "
                        "floor=%s",
                        context.lane,
                        latest.close_time,
                        startup_floor,
                    )
                since = max(latest.close_time, startup_floor)
            if since < boundary:
                catch_up_requests.append(
                    RecoveryRequest(
                        lane=context.lane,
                        since=since,
                        until=boundary,
                        reason="runtime_catchup",
                    )
                )

        await self._execute_recovery_closure(catch_up_requests)

        prepared = tuple(
            context for context in contexts if context.lane not in empty_lanes
        )
        for context in prepared:
            if context.history_floor_duration <= context.lookback_duration:
                continue
            rebuilt = await self.htf_service.materialize_complete_missing_buckets(
                base_lane=context.lane,
                base_duration=context.base_duration,
                target_durations=context.target_durations,
                alignment_origin=alignment_origin,
                since=boundary - context.history_floor_duration,
                before=boundary - context.lookback_duration,
                as_of=as_of,
            )
            if rebuilt:
                _LOGGER.info(
                    "runtime rebuilt older derived buckets from stored base "
                    "candles: lane=%s count=%d",
                    context.lane,
                    rebuilt,
                )

        htf_requests: list[RecoveryRequest] = []
        for context in prepared:
            htf_requests.extend(
                await self.htf_service.reconcile_latest_closed_buckets(
                    base_lane=context.lane,
                    base_duration=context.base_duration,
                    target_durations=context.target_durations,
                    alignment_origin=alignment_origin,
                    as_of=as_of,
                )
            )
            htf_requests.extend(
                await self.htf_service.reconcile_missing_closed_buckets(
                    base_lane=context.lane,
                    base_duration=context.base_duration,
                    target_durations=context.target_durations,
                    alignment_origin=alignment_origin,
                    since=boundary - context.lookback_duration,
                    as_of=as_of,
                )
            )
        await self._execute_recovery_closure(htf_requests)

    async def _prepare_admitted_lanes(
        self,
        *,
        as_of: datetime,
        boundary: datetime,
    ) -> tuple[LanePlan, ...]:
        """Prepare every lane that can be prepared; exclude those that cannot."""
        for lane in tuple(self._ready_to_rejoin):
            self._excluded.pop(lane, None)
        self._ready_to_rejoin.clear()
        self._publish_excluded_lanes()
        candidates = tuple(
            context for context in self._contexts if context.lane not in self._excluded
        )
        last_error: RecoveryExhaustedError | None = None
        while candidates:
            empty_lanes: list[MarketLane] = []
            failure: RecoveryExhaustedError | None = None
            try:
                await self._prepare_lanes(
                    candidates,
                    as_of=as_of,
                    boundary=boundary,
                    empty_lanes=empty_lanes,
                )
            except RecoveryExhaustedError as exc:
                candidate_lanes = {context.lane for context in candidates}
                if (
                    isinstance(exc, RecoveryRateLimitedError)
                    or exc.lane not in candidate_lanes
                ):
                    raise
                failure = exc
            for lane in empty_lanes:
                self._exclude_lane(lane, reason=_REASON_NO_CLOSED_CANDLE, detail="")
                last_error = RecoveryExhaustedError(
                    f"no closed candle exists in the startup window for lane {lane}",
                    lane=lane,
                )
            if failure is not None:
                assert failure.lane is not None
                self._exclude_lane(
                    failure.lane,
                    reason=_REASON_RECOVERY_EXHAUSTED,
                    detail=str(failure),
                )
                last_error = failure
            candidates = tuple(
                context for context in candidates if context.lane not in self._excluded
            )
            if failure is None:
                # Every remaining lane was fully prepared in this pass.
                break
        if not candidates:
            self._clear_exclusions()
            if last_error is None:
                raise DataIngestionError("no runtime lane could be prepared")
            raise last_error
        return candidates

    async def _prepare_live_connection(self) -> datetime:
        """Repair bounded base history and closed HTFs before opening WS."""
        base_duration = self._contexts[0].base_duration
        alignment_origin = self.plan.alignment_origin
        while True:
            as_of = self._now()
            current_closed_boundary = aligned_bucket_start(
                as_of,
                base_duration,
                alignment_origin,
            )
            self._admitted = await self._prepare_admitted_lanes(
                as_of=as_of,
                boundary=current_closed_boundary,
            )
            self._admitted_by_lane = {
                context.lane: context for context in self._admitted
            }

            settled_as_of = self._now()
            settled_boundary = aligned_bucket_start(
                settled_as_of,
                base_duration,
                alignment_origin,
            )
            if settled_boundary <= current_closed_boundary:
                return current_closed_boundary
            _LOGGER.info(
                "runtime pre-connect boundary advanced during maintenance: "
                "repaired=%s current=%s",
                current_closed_boundary,
                settled_boundary,
            )

    async def _execute_recovery_closure(
        self,
        requests: Iterable[RecoveryRequest],
    ) -> None:
        await self.recovery_engine.recover_closure(requests, plan=self.plan)

    def _validate_live_observation(
        self,
        observation: CandleObservation,
    ) -> LanePlan:
        context = self._admitted_by_lane.get(observation.lane)
        if context is None:
            raise DataIngestionError(
                f"live observation targets an unknown runtime lane: {observation.lane}"
            )
        if observation.provider_id != self.live_provider.provider_id:
            raise DataIngestionError("live observation has the wrong provider ID")
        if observation.lane.timeframe != self.plan.base_timeframe:
            raise DataIngestionError("live observation is not on the base timeframe")
        return context

    async def _repair_lane(self, lane: MarketLane) -> None:
        """Run one background repair attempt for an excluded lane."""
        context = self._contexts_by_lane[lane]
        as_of = self._now()
        boundary = aligned_bucket_start(
            as_of,
            self._contexts[0].base_duration,
            self.plan.alignment_origin,
        )
        empty_lanes: list[MarketLane] = []
        reason = self._excluded[lane].reason
        retry_delay = _EXCLUDED_LANE_RETRY_SECONDS
        try:
            await self._prepare_lanes(
                (context,),
                as_of=as_of,
                boundary=boundary,
                empty_lanes=empty_lanes,
            )
            detail = ""
            if empty_lanes:
                reason = _REASON_NO_CLOSED_CANDLE
            else:
                self._ready_to_rejoin.add(lane)
                _LOGGER.info(
                    "runtime lane repaired and ready to rejoin live ingestion: lane=%s",
                    lane,
                )
                return
        except TransportDeadlineExceeded:
            raise
        except RecoveryExhaustedError as exc:
            reason = _REASON_RECOVERY_EXHAUSTED
            detail = str(exc)
            if isinstance(exc, RecoveryRateLimitedError):
                retry_delay = max(retry_delay, exc.retry_after_seconds)
        except Exception as exc:
            if not is_storage_availability_error(exc):
                raise
            detail = str(exc)

        now = self._now()
        fault = self._excluded[lane]
        self._excluded[lane] = LaneFault(
            venue=fault.venue,
            instrument_id=fault.instrument_id,
            reason=reason,
            detail=detail,
            excluded_since=fault.excluded_since,
            next_retry_at=now + timedelta(seconds=retry_delay),
        )
        _LOGGER.warning(
            "runtime lane repair failed; retrying at %s: lane=%s reason=%s detail=%s",
            self._excluded[lane].next_retry_at,
            lane,
            reason,
            detail,
        )

    def _pending_repairs(self) -> list[LaneFault]:
        return [
            self._excluded[context.lane]
            for context in self._contexts
            if context.lane in self._excluded
            and context.lane not in self._ready_to_rejoin
        ]

    async def _repair_excluded_lanes(self) -> None:
        """Retry excluded lanes in the background until each one is repaired."""
        try:
            while True:
                now = self._now()
                for context in self._contexts:
                    fault = self._excluded.get(context.lane)
                    if (
                        fault is not None
                        and context.lane not in self._ready_to_rejoin
                        and fault.next_retry_at <= now
                    ):
                        await self._repair_lane(context.lane)
                pending = self._pending_repairs()
                if not pending:
                    return
                delay = (
                    min(fault.next_retry_at for fault in pending) - self._now()
                ).total_seconds()
                await self._repair_sleep(max(0.0, delay))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            # Surfaced by the live loop after its next observation.
            self._repair_failure = exc

    async def _stop_repair(self) -> None:
        task = self._repair_task
        self._repair_task = None
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _run_live_cycle(self) -> None:
        self._set_state(RuntimeState.STARTING)
        connection_anchor = await self._prepare_live_connection()
        subscriptions = MappingProxyType(
            {context.lane: context.live_symbol for context in self._admitted}
        )
        stream = None
        try:
            stream = self.live_provider.stream_closed_candles(
                subscriptions,
                base_timeframe=self.plan.base_timeframe,
                timeframe_duration=self._contexts[0].base_duration,
                alignment_origin=self.plan.alignment_origin,
                connection_anchor=connection_anchor,
            )
            self._repair_failure = None
            if self._excluded:
                self._repair_task = asyncio.create_task(
                    self._repair_excluded_lanes(),
                    name="ingestion-lane-repair",
                )
            async for observation in stream:
                context = self._validate_live_observation(observation)
                status = await self.ingestion_service.commit_observation(observation)
                if status is CandleCommitStatus.CONFLICT:
                    raise DataIngestionError(
                        f"live canonical conflict for {observation.lane} "
                        f"at {observation.open_time}"
                    )

                follow_ups = await self.htf_service.process_base_candle(
                    canonicalize_observation(observation),
                    base_duration=context.base_duration,
                    target_durations=context.target_durations,
                    alignment_origin=self.plan.alignment_origin,
                )
                self.observability.record_base_last_close(
                    context.lane,
                    observation.close_time,
                )
                self._set_state(RuntimeState.LIVE)
                self._last_error = None
                if follow_ups:
                    self._set_state(RuntimeState.RECOVERING)
                    await self._execute_recovery_closure(follow_ups)
                    self._set_state(RuntimeState.LIVE)
                if self._repair_failure is not None:
                    raise self._repair_failure
                if self._ready_to_rejoin:
                    _LOGGER.info(
                        "runtime lanes repaired; reconnecting to admit them: lanes=%s",
                        sorted(str(lane) for lane in self._ready_to_rejoin),
                    )
                    return
            raise DataIngestionError("live stream ended unexpectedly")
        finally:
            try:
                await self._stop_repair()
            finally:
                if stream is not None:
                    close = getattr(stream, "aclose", None)
                    if close is not None:
                        await close()

    async def _handle_stream_interruption(
        self,
        interruption: LiveStreamInterrupted,
    ) -> None:
        if self._stop_requested:
            self._set_state(RuntimeState.STOPPED)
            return
        self._set_state(RuntimeState.RECOVERING)
        _LOGGER.warning(
            "live stream interrupted: reason=%s recovery_requests=%d",
            interruption.reason,
            len(interruption.recovery_requests),
        )
        await self._execute_recovery_closure(interruption.recovery_requests)
        if self._stop_requested:
            self._set_state(RuntimeState.STOPPED)
            return
        await self._reconnect_sleep(self.plan.reconnect_backoff_seconds)
        _LOGGER.info("ingestion runtime reconnect cycle ready")

    async def _run_live_or_interruption_cycle(self) -> None:
        """Run live work and turn a stream interruption into bounded repair."""
        try:
            await self._run_live_cycle()
        except LiveStreamInterrupted as interruption:
            await self._handle_stream_interruption(interruption)

    async def _run_recoverable_cycle(self) -> None:
        """Retry provider exhaustion and storage outages without masking failures."""
        try:
            await self._run_live_or_interruption_cycle()
        except RecoveryExhaustedError as exc:
            self._set_state(RuntimeState.RECOVERING)
            self._last_error = str(exc)
            retry_delay = self.plan.reconnect_backoff_seconds
            rate_limited = isinstance(exc, RecoveryRateLimitedError)
            if rate_limited:
                retry_delay = max(retry_delay, exc.retry_after_seconds)
            _LOGGER.warning(
                "ingestion recovery %s; retrying after %ss: %s",
                "rate limited" if rate_limited else "providers exhausted",
                retry_delay,
                exc,
            )
            await self._reconnect_sleep(retry_delay)
        except Exception as exc:
            if isinstance(
                exc, TransportDeadlineExceeded
            ) or not is_storage_availability_error(exc):
                raise
            self._set_state(RuntimeState.RECOVERING)
            self._last_error = str(exc)
            retry_delay = self.plan.reconnect_backoff_seconds
            _LOGGER.warning(
                "ingestion storage unavailable (%s); retrying after %ss: %s",
                type(exc).__name__,
                retry_delay,
                exc,
            )
            await self._reconnect_sleep(retry_delay)

    async def run(self) -> None:
        """Run until stopped, or propagate a fatal runtime error."""
        if self._active_task is not None and not self._active_task.done():
            raise RuntimeError("RuntimeSupervisor is already running")
        if self._stop_requested:
            self._set_state(RuntimeState.STOPPED)
            return

        self._active_task = asyncio.current_task()
        _LOGGER.info("ingestion runtime starting")
        try:
            while not self._stop_requested:
                try:
                    await self._run_recoverable_cycle()
                except asyncio.CancelledError:
                    if self._stop_requested:
                        return
                    self._set_state(RuntimeState.STOPPED)
                    raise
                except TransportDeadlineExceeded as exc:
                    self._latch_fatal(exc)
                    raise
                except Exception as exc:
                    self._set_state(RuntimeState.ERROR)
                    self._last_error = str(exc)
                    _LOGGER.error("ingestion runtime failed: %s", exc)
                    raise
        finally:
            self._active_task = None
            if self._fatal_error is None and self._state is not RuntimeState.ERROR:
                self._set_state(RuntimeState.STOPPED)
            _LOGGER.info("ingestion runtime stopped")


__all__ = ["RuntimeSupervisor"]
