"""Runtime composition for the ingestion acquisition and repair loop."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

from apps.ingestion_app.domain.candle import CandleObservation, CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.observability import IngestionObservability
from apps.ingestion_app.planning import IngestionPlan, LanePlan
from apps.ingestion_app.providers.base import (
    LiveCandleProvider,
    LiveStreamInterrupted,
    TransportDeadlineExceeded,
)
from apps.ingestion_app.runtime.state import (
    DesiredRuntimeState,
    RuntimeSnapshot,
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
)
from apps.ingestion_app.services.time_alignment import aligned_bucket_start
from apps.ingestion_app.storage.repository import (
    CandleCommitStatus,
    CandleRepository,
)
from libs.common.enums import SystemComponent
from libs.common.exceptions import DataIngestionError
from libs.common.logging.logger_utils import bind_logger

_LOGGER = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)


def _require_utc(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise DataIngestionError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise DataIngestionError(f"{field_name} must be timezone-aware UTC")
    return value


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
        reconnect_sleep_fn: Callable[[float], Awaitable[None]] | None = None,
        observability: IngestionObservability | None = None,
    ) -> None:
        if not isinstance(plan, IngestionPlan):
            raise TypeError("plan must be IngestionPlan")
        if not callable(getattr(live_provider, "stream_closed_candles", None)):
            raise TypeError("live_provider must expose stream_closed_candles")
        if not isinstance(getattr(live_provider, "provider_id", None), str):
            raise DataIngestionError("live provider must expose a provider_id")
        if not live_provider.provider_id.strip():
            raise DataIngestionError("live provider ID must be non-empty")
        if now_fn is not None and not callable(now_fn):
            raise TypeError("now_fn must be callable")
        if reconnect_sleep_fn is not None and not callable(reconnect_sleep_fn):
            raise TypeError("reconnect_sleep_fn must be callable")
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
        self._reconnect_sleep = reconnect_sleep_fn or asyncio.sleep
        self._contexts = plan.lanes
        self._contexts_by_lane = plan.lanes_by_lane
        self._subscriptions = MappingProxyType(
            {context.lane: context.live_symbol for context in self._contexts}
        )

        self._last_error: str | None = None
        self._fatal_error: str | None = None
        self._fatal_exception: BaseException | None = None
        self._state = RuntimeState.STOPPED
        self._stop_requested = False
        self._active_task: asyncio.Task[None] | None = None

    @property
    def active_lanes(self) -> tuple[MarketLane, ...]:
        return tuple(context.lane for context in self._contexts)

    def snapshot(self) -> SupervisorSnapshot:
        """Return the current status without performing I/O."""
        self._sync_transport_quarantine()
        return SupervisorSnapshot(
            state=self._state,
            last_error=self._last_error,
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
        if not isinstance(request, RecoveryRequest):
            raise TypeError("request must be a RecoveryRequest")
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
        if (
            aligned_bucket_start(
                candle.open_time,
                context.base_duration,
                self.plan.alignment_origin,
            )
            != candle.open_time
        ):
            raise DataIngestionError(
                "latest canonical base candle is off the base grid"
            )

    async def _prepare_live_connection(self) -> datetime:
        """Repair bounded base history and latest closed HTFs before opening WS."""
        alignment_origin = self.plan.alignment_origin
        while True:
            as_of = _require_utc(self._now(), field_name="runtime as_of")
            current_closed_boundary = aligned_bucket_start(
                as_of,
                self._contexts[0].base_duration,
                alignment_origin,
            )
            catch_up_requests: list[RecoveryRequest] = []

            for context in self._contexts:
                latest = await self.repository.fetch_latest_candle(
                    lane=context.lane,
                    before=current_closed_boundary,
                )
                if latest is not None:
                    self._validate_latest_base_candle(
                        latest,
                        context=context,
                        before=current_closed_boundary,
                    )
                    self.observability.record_base_last_close(
                        context.lane,
                        latest.close_time,
                    )
                startup_floor = current_closed_boundary - context.lookback_duration
                if latest is None:
                    since = startup_floor
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
                if since < current_closed_boundary:
                    catch_up_requests.append(
                        RecoveryRequest(
                            lane=context.lane,
                            since=since,
                            until=current_closed_boundary,
                            reason="runtime_catchup",
                        )
                    )

            await self._execute_recovery_closure(catch_up_requests)

            htf_requests: list[RecoveryRequest] = []
            for context in self._contexts:
                htf_requests.extend(
                    await self.htf_service.reconcile_latest_closed_buckets(
                        base_lane=context.lane,
                        base_duration=context.base_duration,
                        target_durations=context.target_durations,
                        alignment_origin=alignment_origin,
                        as_of=as_of,
                    )
                )
            await self._execute_recovery_closure(htf_requests)

            settled_as_of = _require_utc(
                self._now(),
                field_name="runtime settled_as_of",
            )
            settled_boundary = aligned_bucket_start(
                settled_as_of,
                self._contexts[0].base_duration,
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
        if not isinstance(observation, CandleObservation):
            raise DataIngestionError("live provider returned a non-observation")
        context = self._contexts_by_lane.get(observation.lane)
        if context is None:
            raise DataIngestionError(
                f"live observation targets an unknown runtime lane: {observation.lane}"
            )
        if observation.provider_id != self.live_provider.provider_id:
            raise DataIngestionError("live observation has the wrong provider ID")
        if observation.lane.timeframe != self.plan.base_timeframe:
            raise DataIngestionError("live observation is not on the base timeframe")
        return context

    async def _run_live_cycle(self) -> None:
        self._set_state(RuntimeState.STARTING)
        connection_anchor = await self._prepare_live_connection()
        stream = None
        try:
            stream = self.live_provider.stream_closed_candles(
                self._subscriptions,
                base_timeframe=self.plan.base_timeframe,
                timeframe_duration=self._contexts[0].base_duration,
                alignment_origin=self.plan.alignment_origin,
                connection_anchor=connection_anchor,
            )
            async for observation in stream:
                context = self._validate_live_observation(observation)
                status = await self.ingestion_service.commit_observation(observation)
                if status is CandleCommitStatus.CONFLICT:
                    raise DataIngestionError(
                        f"live canonical conflict for {observation.lane} "
                        f"at {observation.open_time}"
                    )
                if status not in {
                    CandleCommitStatus.INSERTED,
                    CandleCommitStatus.DUPLICATE,
                }:
                    raise DataIngestionError("live commit returned an invalid status")

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
            raise DataIngestionError("live stream ended unexpectedly")
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
        """Retry completed provider exhaustion without masking fatal failures."""
        try:
            await self._run_live_or_interruption_cycle()
        except RecoveryExhaustedError as exc:
            self._set_state(RuntimeState.RECOVERING)
            self._last_error = str(exc)
            _LOGGER.warning(
                "ingestion recovery providers exhausted; retrying after %ss: %s",
                self.plan.reconnect_backoff_seconds,
                exc,
            )
            await self._reconnect_sleep(self.plan.reconnect_backoff_seconds)

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


__all__ = [
    # Compatibility re-exports; state ownership lives in runtime.state.
    "DesiredRuntimeState",
    "RuntimeSnapshot",
    "RuntimeState",
    "RuntimeSupervisor",
    "SupervisorSnapshot",
]
