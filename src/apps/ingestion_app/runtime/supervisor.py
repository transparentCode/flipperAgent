"""Runtime composition for the ingestion acquisition and repair loop."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType

from apps.ingestion_app.domain.candle import CandleObservation, CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.observability import IngestionObservability
from apps.ingestion_app.providers.base import (
    LiveCandleProvider,
    LiveStreamInterrupted,
)
from apps.ingestion_app.services.candle_ingestion import (
    CandleIngestionService,
    canonicalize_observation,
)
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.services.recovery import RecoveryEngine
from apps.ingestion_app.services.time_alignment import aligned_bucket_start
from apps.ingestion_app.settings import IngestionSettings
from apps.ingestion_app.storage.repository import (
    CandleCommitStatus,
    CandleRepository,
)
from libs.common.enums import SystemComponent
from libs.common.exceptions import DataIngestionError
from libs.common.logging.logger_utils import bind_logger

_LOGGER = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)


class DesiredRuntimeState(StrEnum):
    """Runtime-wide desired state controlled by pause and resume."""

    RUNNING = "running"
    PAUSED = "paused"


class RuntimeState(StrEnum):
    """Observed state of the in-memory runtime supervisor."""

    STOPPED = "stopped"
    STARTING = "starting"
    LIVE = "live"
    RECOVERING = "recovering"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    """Read-only runtime status for future control-plane consumers."""

    desired_state: DesiredRuntimeState
    state: RuntimeState
    last_error: str | None


@dataclass(frozen=True, slots=True)
class _LaneContext:
    lane: MarketLane
    live_symbol: str
    provider_order: tuple[str, ...]
    provider_symbols: Mapping[str, str]
    target_durations: Mapping[str, timedelta]
    base_duration: timedelta
    lookback_duration: timedelta


def _require_utc(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise DataIngestionError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise DataIngestionError(f"{field_name} must be timezone-aware UTC")
    return value


def _request_key(
    request: RecoveryRequest,
) -> tuple[str, str, str, datetime, datetime, str]:
    return (
        request.lane.venue,
        request.lane.instrument_id,
        request.lane.timeframe,
        request.since,
        request.until,
        request.reason,
    )


class RuntimeSupervisor:
    """Compose bounded recovery, live commits, and HTF processing."""

    def __init__(
        self,
        *,
        settings: IngestionSettings,
        live_provider: LiveCandleProvider,
        repository: CandleRepository,
        ingestion_service: CandleIngestionService,
        htf_service: HTFAggregationService,
        recovery_engine: RecoveryEngine,
        now_fn: Callable[[], datetime] | None = None,
        reconnect_sleep_fn: Callable[[float], Awaitable[None]] | None = None,
        observability: IngestionObservability | None = None,
    ) -> None:
        if not isinstance(settings, IngestionSettings):
            raise TypeError("settings must be IngestionSettings")
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

        self.settings = settings
        self.live_provider = live_provider
        self.repository = repository
        self.ingestion_service = ingestion_service
        self.htf_service = htf_service
        self.recovery_engine = recovery_engine
        self.observability = observability or IngestionObservability()
        self._now = now_fn or (lambda: datetime.now(UTC))
        self._reconnect_sleep = reconnect_sleep_fn or asyncio.sleep
        self._contexts = self._resolve_lane_contexts()
        self._contexts_by_lane = {context.lane: context for context in self._contexts}
        self._subscriptions = MappingProxyType(
            {context.lane: context.live_symbol for context in self._contexts}
        )

        self._desired_state = DesiredRuntimeState.RUNNING
        self._set_state(RuntimeState.STOPPED)
        self._last_error: str | None = None
        self._stop_requested = False
        self._control_event = asyncio.Event()
        self._active_task: asyncio.Task[None] | None = None
        self._control_cancel_requested = False

    def _resolve_lane_contexts(self) -> tuple[_LaneContext, ...]:
        base_timeframe = self.settings.base_timeframe
        base_duration = timedelta(
            seconds=self.settings.timeframes[base_timeframe].duration_seconds
        )
        contexts: list[_LaneContext] = []
        seen_lanes: set[MarketLane] = set()

        for asset_name in sorted(self.settings.assets):
            asset = self.settings.assets[asset_name]
            if not asset.enabled:
                continue
            for instrument_id in sorted(asset.instruments):
                instrument = asset.instruments[instrument_id]
                if instrument.live_provider != self.live_provider.provider_id:
                    raise DataIngestionError(
                        f"instrument '{instrument_id}' live provider "
                        f"'{instrument.live_provider}' does not match injected "
                        f"provider '{self.live_provider.provider_id}'"
                    )
                if not instrument.historical_providers:
                    raise DataIngestionError(
                        f"instrument '{instrument_id}' has no historical providers"
                    )

                lane = MarketLane(
                    instrument.venue,
                    instrument_id,
                    base_timeframe,
                )
                if lane in seen_lanes:
                    raise DataIngestionError(f"duplicate enabled runtime lane: {lane}")
                seen_lanes.add(lane)

                provider_symbols = dict(instrument.provider_symbols)
                for provider_id in instrument.historical_providers:
                    if provider_id not in provider_symbols:
                        raise DataIngestionError(
                            f"instrument '{instrument_id}' has no symbol for "
                            f"historical provider '{provider_id}'"
                        )
                live_symbol = provider_symbols.get(instrument.live_provider)
                if not isinstance(live_symbol, str) or not live_symbol.strip():
                    raise DataIngestionError(
                        f"instrument '{instrument_id}' has no live provider symbol"
                    )

                target_durations = {
                    timeframe: timedelta(
                        seconds=self.settings.timeframes[timeframe].duration_seconds
                    )
                    for timeframe in instrument.timeframes
                    if timeframe != base_timeframe
                }
                target_durations = dict(
                    sorted(
                        target_durations.items(),
                        key=lambda item: (item[1], item[0]),
                    )
                )
                lookback_duration = max(
                    target_durations.values(),
                    default=base_duration,
                )
                contexts.append(
                    _LaneContext(
                        lane=lane,
                        live_symbol=live_symbol,
                        provider_order=tuple(instrument.historical_providers),
                        provider_symbols=MappingProxyType(provider_symbols),
                        target_durations=MappingProxyType(target_durations),
                        base_duration=base_duration,
                        lookback_duration=lookback_duration,
                    )
                )

        if not contexts:
            raise DataIngestionError("no enabled ingestion runtime lanes")
        return tuple(
            sorted(
                contexts,
                key=lambda context: (
                    context.lane.venue,
                    context.lane.instrument_id,
                    context.lane.timeframe,
                ),
            )
        )

    def snapshot(self) -> RuntimeSnapshot:
        """Return the current status without performing I/O."""
        return RuntimeSnapshot(
            desired_state=self._desired_state,
            state=self._state,
            last_error=self._last_error,
        )

    def _set_state(self, state: RuntimeState) -> None:
        self._state = state
        self.observability.set_runtime_live(state is RuntimeState.LIVE)

    def pause(self) -> None:
        """Request a runtime-wide pause and cancel active work cleanly."""
        self._desired_state = DesiredRuntimeState.PAUSED
        if self._active_task is None or self._active_task.done():
            self._set_state(RuntimeState.STOPPED)
        self._control_event.set()
        self._cancel_active_task()
        _LOGGER.info("ingestion runtime pause requested")

    def resume(self) -> None:
        """Request a fresh startup/catch-up cycle."""
        if self._stop_requested:
            return
        self._desired_state = DesiredRuntimeState.RUNNING
        self._last_error = None
        self._control_event.set()
        _LOGGER.info("ingestion runtime resume requested")

    def stop(self) -> None:
        """Request process-level shutdown."""
        self._stop_requested = True
        if self._active_task is None or self._active_task.done():
            self._set_state(RuntimeState.STOPPED)
        self._control_event.set()
        self._cancel_active_task()
        _LOGGER.info("ingestion runtime stop requested")

    async def execute_recovery(self, request: RecoveryRequest) -> None:
        """Execute one offline recovery closure without starting the live loop."""
        if not isinstance(request, RecoveryRequest):
            raise TypeError("request must be a RecoveryRequest")
        if self._active_task is not None and not self._active_task.done():
            raise RuntimeError(
                "cannot execute recovery while the supervisor is running"
            )

        self._set_state(RuntimeState.RECOVERING)
        self._last_error = None
        try:
            await self._execute_recovery_closure((request,))
        except asyncio.CancelledError:
            self._set_state(RuntimeState.STOPPED)
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
        self._control_cancel_requested = True
        task.cancel()

    def _consume_control_cancellation(self) -> bool:
        if not self._control_cancel_requested:
            return False
        self._control_cancel_requested = False
        self._set_state(RuntimeState.STOPPED)
        return True

    def _validate_latest_base_candle(
        self,
        candle: CanonicalCandle,
        *,
        context: _LaneContext,
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
                self.settings.calendar.alignment_origin,
            )
            != candle.open_time
        ):
            raise DataIngestionError(
                "latest canonical base candle is off the base grid"
            )

    async def _prepare_live_connection(self) -> datetime:
        """Repair bounded base history and latest closed HTFs before opening WS."""
        alignment_origin = self.settings.calendar.alignment_origin
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

    async def _execute_recovery_request(
        self,
        request: RecoveryRequest,
    ) -> tuple[RecoveryRequest, ...]:
        context = self._contexts_by_lane.get(request.lane)
        if context is None:
            raise DataIngestionError(
                f"recovery request targets unknown runtime lane: {request.lane}"
            )
        follow_ups = await self.recovery_engine.recover(
            request,
            base_timeframe=self.settings.base_timeframe,
            base_duration=context.base_duration,
            provider_order=context.provider_order,
            provider_symbols=context.provider_symbols,
            target_durations=context.target_durations,
            alignment_origin=self.settings.calendar.alignment_origin,
        )
        if not isinstance(follow_ups, tuple) or not all(
            isinstance(follow_up, RecoveryRequest) for follow_up in follow_ups
        ):
            raise DataIngestionError(
                "recovery engine returned invalid follow-up requests"
            )
        return follow_ups

    async def _execute_recovery_closure(
        self,
        requests: Iterable[RecoveryRequest],
    ) -> None:
        pending = list(requests)
        seen: set[tuple[str, str, str, datetime, datetime, str]] = set()
        while pending:
            batch: list[RecoveryRequest] = []
            for request in sorted(pending, key=_request_key):
                if not isinstance(request, RecoveryRequest):
                    raise DataIngestionError(
                        "recovery worklist contains a non-RecoveryRequest"
                    )
                key = _request_key(request)
                if key in seen:
                    continue
                seen.add(key)
                batch.append(request)
            pending = []
            if not batch:
                continue

            tasks = [
                asyncio.create_task(self._execute_recovery_request(request))
                for request in batch
            ]
            try:
                results = await asyncio.gather(*tasks)
            except BaseException:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
            for follow_ups in results:
                pending.extend(follow_ups)

    def _validate_live_observation(
        self,
        observation: CandleObservation,
    ) -> _LaneContext:
        if not isinstance(observation, CandleObservation):
            raise DataIngestionError("live provider returned a non-observation")
        context = self._contexts_by_lane.get(observation.lane)
        if context is None:
            raise DataIngestionError(
                f"live observation targets an unknown runtime lane: {observation.lane}"
            )
        if observation.provider_id != self.live_provider.provider_id:
            raise DataIngestionError("live observation has the wrong provider ID")
        if observation.lane.timeframe != self.settings.base_timeframe:
            raise DataIngestionError("live observation is not on the base timeframe")
        return context

    async def _run_live_cycle(self) -> None:
        self._set_state(RuntimeState.STARTING)
        connection_anchor = await self._prepare_live_connection()
        stream = None
        try:
            stream = self.live_provider.stream_closed_candles(
                self._subscriptions,
                base_timeframe=self.settings.base_timeframe,
                timeframe_duration=self._contexts[0].base_duration,
                alignment_origin=self.settings.calendar.alignment_origin,
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
                    alignment_origin=self.settings.calendar.alignment_origin,
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
        if self._stop_requested or self._desired_state is DesiredRuntimeState.PAUSED:
            self._set_state(RuntimeState.STOPPED)
            return
        self._set_state(RuntimeState.RECOVERING)
        _LOGGER.warning(
            "live stream interrupted: reason=%s recovery_requests=%d",
            interruption.reason,
            len(interruption.recovery_requests),
        )
        await self._execute_recovery_closure(interruption.recovery_requests)
        if self._stop_requested or self._desired_state is DesiredRuntimeState.PAUSED:
            self._set_state(RuntimeState.STOPPED)
            return
        await self._reconnect_sleep(self.settings.runtime.reconnect_backoff_seconds)
        _LOGGER.info("ingestion runtime reconnect cycle ready")

    async def run(self) -> None:
        """Run until stopped, or propagate a fatal runtime error."""
        if self._active_task is not None and not self._active_task.done():
            raise RuntimeError("RuntimeSupervisor is already running")
        if self._stop_requested:
            self._set_state(RuntimeState.STOPPED)
            return

        self._active_task = asyncio.current_task()
        self._control_cancel_requested = False
        _LOGGER.info("ingestion runtime starting")
        try:
            while True:
                if self._stop_requested:
                    self._set_state(RuntimeState.STOPPED)
                    return
                try:
                    if self._desired_state is DesiredRuntimeState.PAUSED:
                        self._set_state(RuntimeState.STOPPED)
                        self._control_event.clear()
                        await self._control_event.wait()
                        continue
                    await self._run_live_cycle()
                except LiveStreamInterrupted as interruption:
                    try:
                        await self._handle_stream_interruption(interruption)
                    except asyncio.CancelledError:
                        if self._consume_control_cancellation():
                            if self._stop_requested:
                                return
                            continue
                        self._set_state(RuntimeState.STOPPED)
                        raise
                    except Exception as exc:
                        self._set_state(RuntimeState.ERROR)
                        self._last_error = str(exc)
                        _LOGGER.error("ingestion runtime failed: %s", exc)
                        raise
                except asyncio.CancelledError:
                    if self._consume_control_cancellation():
                        if self._stop_requested:
                            return
                        continue
                    self._set_state(RuntimeState.STOPPED)
                    raise
                except Exception as exc:
                    self._set_state(RuntimeState.ERROR)
                    self._last_error = str(exc)
                    _LOGGER.error("ingestion runtime failed: %s", exc)
                    raise
        finally:
            self._active_task = None
            if self._state is not RuntimeState.ERROR:
                self._set_state(RuntimeState.STOPPED)
            _LOGGER.info("ingestion runtime stopped")


__all__ = [
    "DesiredRuntimeState",
    "RuntimeSnapshot",
    "RuntimeState",
    "RuntimeSupervisor",
]
