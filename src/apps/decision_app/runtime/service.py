"""ASGI-owned D9C service shell around the approved D9A/D9B primitives."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from time import perf_counter
from typing import Any, Literal, Protocol

from apps.decision_app.observability import DecisionObservability, observe_best_effort
from apps.decision_app.runtime.deadlines import (
    CleanupBudget,
    CleanupTimeout,
    Deadline,
    OperationTimeout,
    cleanup_with_timeout,
    require_remaining,
    run_until,
)
from apps.decision_app.runtime.lifecycle import (
    LifecycleNotificationReader,
    LifecycleReadResult,
)
from apps.decision_app.runtime.live import DecisionPollResult
from apps.decision_app.transport.live_input import (
    FORWARD_CANONICAL_MARKET_GAP_REASON,
    InputTransportError,
)
from libs.contracts.decision import FrozenMapping, deep_freeze, require_utc

ServiceState = Literal[
    "STARTING",
    "RUNNING",
    "PAUSED",
    "REBUILDING",
    "DEGRADED",
    "ERROR",
    "STOPPING",
    "STOPPED",
]
DesiredState = Literal["RUNNING", "PAUSED"]
RebuildSource = Literal[
    "LIFECYCLE_RECONCILIATION",
    "MANUAL",
    "INPUT_RECONSTRUCTION",
]

_CONTROL_STATES = frozenset({"PAUSED", "REBUILDING", "STOPPING", "STOPPED", "ERROR"})


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value.strip()


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionRuntimeGeneration:
    """A fully constructed D9A/D9B runtime generation."""

    generation_id: int
    created_at: datetime
    startup: Any
    live_runtime: Any

    def __post_init__(self) -> None:
        if (
            isinstance(self.generation_id, bool)
            or not isinstance(self.generation_id, int)
            or self.generation_id <= 0
        ):
            raise ValueError("generation_id must be a positive integer")
        require_utc(self.created_at, field_name="generation.created_at")
        if (
            getattr(getattr(self.startup, "snapshot", None), "status", None)
            != "STARTUP_READY"
        ):
            raise ValueError("generation startup must be STARTUP_READY")
        if not callable(getattr(self.live_runtime, "poll_once", None)):
            raise TypeError("generation.live_runtime must provide poll_once()")
        if not hasattr(self.live_runtime, "lanes") or not hasattr(
            self.live_runtime, "input"
        ):
            raise TypeError("generation.live_runtime must expose lanes and input")


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionServiceSnapshot:
    """Bounded cached service evidence exposed to the control plane."""

    service_state: ServiceState
    desired_state: DesiredState
    generation_id: int | None
    started_at: datetime | None
    last_poll_at: datetime | None
    last_rebuild_at: datetime | None
    last_lifecycle_event_at: datetime | None
    last_error: str | None
    configured_asset_count: int
    configured_lane_count: int
    active_lane_count: int
    lane_status_counts: Mapping[str, int]
    blocked_stream_count: int
    lifecycle_cursor: str
    lanes: Mapping[str, Any]
    inputs: Mapping[str, Any]
    last_lifecycle_evidence: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.service_state not in {
            "STARTING",
            "RUNNING",
            "PAUSED",
            "REBUILDING",
            "DEGRADED",
            "ERROR",
            "STOPPING",
            "STOPPED",
        }:
            raise ValueError("unsupported service state")
        if self.desired_state not in {"RUNNING", "PAUSED"}:
            raise ValueError("unsupported desired state")
        for field_name in (
            "started_at",
            "last_poll_at",
            "last_rebuild_at",
            "last_lifecycle_event_at",
        ):
            value = getattr(self, field_name)
            if value is not None:
                require_utc(value, field_name=field_name)
        if self.last_error is not None:
            _text(self.last_error, field_name="last_error")
        for field_name in (
            "configured_asset_count",
            "configured_lane_count",
            "active_lane_count",
            "blocked_stream_count",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        _text(self.lifecycle_cursor, field_name="lifecycle_cursor")
        object.__setattr__(
            self,
            "lane_status_counts",
            FrozenMapping(dict(sorted(self.lane_status_counts.items()))),
        )
        for field_name in ("lanes", "inputs", "last_lifecycle_evidence"):
            object.__setattr__(self, field_name, deep_freeze(getattr(self, field_name)))

    @property
    def ready(self) -> bool:
        return (
            self.generation_id is not None
            and self.desired_state == "RUNNING"
            and self.service_state in {"RUNNING", "DEGRADED"}
        )


class GenerationFactory(Protocol):
    """Exact async factory contract for one fresh runtime generation."""

    async def __call__(
        self,
        *,
        reason: str,
        generation_id: int,
    ) -> DecisionRuntimeGeneration: ...


class DecisionControlError(RuntimeError):
    """Raised when an admitted control cannot finish within its budget."""


class DecisionService:
    """Own exactly one market task and one lifecycle notification task."""

    def __init__(
        self,
        *,
        generation_factory: GenerationFactory,
        lifecycle_reader: LifecycleNotificationReader | None = None,
        configured_asset_count: int = 0,
        configured_lane_count: int = 0,
        block_ms: int = 1000,
        generation_timeout_seconds: float | None = None,
        control_wait_timeout_seconds: float | None = None,
        cleanup_timeout_seconds: float | None = None,
        now_fn: Callable[[], datetime] | None = None,
        observability: DecisionObservability | None = None,
    ) -> None:
        if not callable(generation_factory):
            raise TypeError("generation_factory must be callable")
        if lifecycle_reader is not None and not callable(
            getattr(lifecycle_reader, "read_once", None)
        ):
            raise TypeError("lifecycle_reader must provide read_once()")
        if isinstance(block_ms, bool) or not isinstance(block_ms, int) or block_ms < 0:
            raise ValueError("block_ms must be a non-negative integer")
        for name, value in (
            ("generation_timeout_seconds", generation_timeout_seconds),
            ("control_wait_timeout_seconds", control_wait_timeout_seconds),
            ("cleanup_timeout_seconds", cleanup_timeout_seconds),
        ):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(float(value))
                or value <= 0
            ):
                raise ValueError(f"{name} must be finite and positive")
        for name, value in (
            ("configured_asset_count", configured_asset_count),
            ("configured_lane_count", configured_lane_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        self._generation_factory = generation_factory
        self._lifecycle_reader = lifecycle_reader
        self._configured_asset_count = configured_asset_count
        self._configured_lane_count = configured_lane_count
        self._block_ms = block_ms
        self._generation_timeout_seconds = generation_timeout_seconds
        self._control_wait_timeout_seconds = control_wait_timeout_seconds
        self._cleanup_timeout_seconds = cleanup_timeout_seconds
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        if observability is not None and not isinstance(
            observability, DecisionObservability
        ):
            raise TypeError("observability must be DecisionObservability or None")
        self._observability = observability
        self._transition_lock = asyncio.Lock()
        self._wake_event = asyncio.Event()
        self._clock_wait_event = asyncio.Event()
        self._poll_idle = asyncio.Event()
        self._poll_idle.set()
        self._stop_event = asyncio.Event()
        self._market_task: asyncio.Task[Any] | None = None
        self._lifecycle_task: asyncio.Task[Any] | None = None
        self._generation: DecisionRuntimeGeneration | None = None
        self._generation_number = 0
        self._desired_state: DesiredState = "RUNNING"
        self._service_state: ServiceState = "STARTING"
        self._started_at: datetime | None = None
        self._last_poll_at: datetime | None = None
        self._last_rebuild_at: datetime | None = None
        self._last_lifecycle_event_at: datetime | None = None
        self._last_error: str | None = None
        self._market_error: str | None = None
        self._lifecycle_error: str | None = None
        self._last_poll_result: DecisionPollResult | None = None
        self._last_lane_transactions: dict[str, Any] = {}
        self._last_lifecycle_evidence: LifecycleReadResult | None = None
        self._rebuild_requested = False
        self._rebuild_reason: str | None = None
        self._rebuild_source: RebuildSource | None = None
        self._poll_active = False
        self._retained_cleanup_tasks: set[asyncio.Task[Any]] = set()

    @property
    def generation(self) -> DecisionRuntimeGeneration | None:
        return self._generation

    @property
    def market_task(self) -> asyncio.Task[Any] | None:
        return self._market_task

    @property
    def lifecycle_task(self) -> asyncio.Task[Any] | None:
        return self._lifecycle_task

    @property
    def service_state(self) -> ServiceState:
        return self._service_state

    @property
    def desired_state(self) -> DesiredState:
        return self._desired_state

    async def start(
        self,
        generation: DecisionRuntimeGeneration | None = None,
        *,
        deadline: Deadline | None = None,
    ) -> DecisionServiceSnapshot:
        """Install the initial generation and start the two service tasks."""

        async with self._transition_lock:
            if self._service_state not in {"STARTING", "STOPPED"}:
                raise RuntimeError("decision service is already started")
            if self._service_state == "STOPPED":
                self._stop_event = asyncio.Event()
                self._wake_event = asyncio.Event()
                self._clock_wait_event = asyncio.Event()
                self._poll_idle = asyncio.Event()
                self._poll_idle.set()
            self._desired_state = "RUNNING"
            self._service_state = "STARTING"
            self._sync_observability()
            self._last_error = None
            self._market_error = None
            self._lifecycle_error = None
            self._rebuild_requested = False
            self._rebuild_reason = None
            self._rebuild_source = None
            if generation is None:
                try:
                    generation = await self._build_generation(
                        "initial",
                        deadline=deadline,
                    )
                except asyncio.CancelledError:
                    self._service_state = (
                        "STOPPING" if self._stop_event.is_set() else "ERROR"
                    )
                    self._last_error = "initial generation build cancelled"
                    self._sync_observability()
                    raise
                except Exception as exc:
                    self._generation = None
                    self._service_state = (
                        "STOPPING" if self._stop_event.is_set() else "ERROR"
                    )
                    self._last_error = f"initial generation build failed: {exc}"
                    self._sync_observability()
                    raise
            if self._stop_event.is_set():
                self._service_state = "STOPPING"
                self._last_error = "initial generation rejected after stop intent"
                self._sync_observability()
                raise DecisionControlError(self._last_error)
            if deadline is not None:
                require_remaining(deadline, operation="initial generation install")
            self._install_generation(generation)
            self._started_at = self._now()
            self._service_state = "RUNNING"
            self._sync_observability()
            self._market_task = asyncio.create_task(
                self._market_loop(), name="decision-market-loop"
            )
            if self._lifecycle_reader is not None:
                self._lifecycle_task = asyncio.create_task(
                    self._lifecycle_loop(), name="decision-lifecycle-loop"
                )
        return self.snapshot()

    async def stop(
        self,
        *,
        cleanup_budget: CleanupBudget | None = None,
    ) -> DecisionServiceSnapshot:
        """Stop with bounded drainage and finite owned-task cleanup."""

        if self._service_state == "STOPPED":
            return self.snapshot()
        deadline = self._control_deadline()
        # Explicit stop is the sole control allowed to latch intent before
        # admission.  A concurrent rebuild cannot later start another poll.
        self._desired_state = "PAUSED"
        self._service_state = "STOPPING"
        self._stop_event.set()
        self._signal_control_waiters()
        self._sync_observability()
        drainage_failed = False
        try:
            async with self._transition_scope(deadline):
                self._service_state = "STOPPING"
                self._sync_observability()
                await self._wait_for_poll_idle(deadline, operation="stop drainage")
        except OperationTimeout as exc:
            drainage_failed = True
            self._last_error = f"stop control timed out: {exc}"
            self._sync_observability()
        except asyncio.CancelledError:
            # A disconnected control caller must not cancel an in-flight
            # publication before the stop drainage boundary.  Stop intent is
            # already latched; the owned loops will observe it and finish the
            # current poll, while a later owner can perform cleanup.
            self._service_state = "STOPPING"
            self._sync_observability()
            raise

        lifecycle_task = self._lifecycle_task
        if lifecycle_task is not None and not lifecycle_task.done():
            lifecycle_task.cancel()
        if drainage_failed and self._market_task is not None:
            self._market_task.cancel()
        cleanup_deadline = None
        if cleanup_budget is None and self._cleanup_timeout_seconds is not None:
            cleanup_budget = CleanupBudget(self._cleanup_timeout_seconds)
        if cleanup_budget is not None:
            cleanup_deadline = cleanup_budget.deadline()
        lifecycle_stopped = await self._await_task(
            lifecycle_task,
            deadline=cleanup_deadline,
            operation="lifecycle task cleanup",
        )
        market_stopped = await self._await_task(
            self._market_task,
            deadline=cleanup_deadline,
            operation="market task cleanup",
        )
        if not lifecycle_stopped or not market_stopped:
            self._last_error = "Decision shutdown is unclean; owned task remains active"
            self._sync_observability()
            return self.snapshot()
        try:
            async with self._transition_scope(cleanup_deadline):
                self._service_state = "STOPPED"
                self._lifecycle_task = None
                self._market_task = None
                self._sync_observability()
        except OperationTimeout:
            self._last_error = (
                "Decision shutdown could not acquire final transition ownership"
            )
            self._sync_observability()
        return self.snapshot()

    async def pause(self) -> DecisionServiceSnapshot:
        deadline = self._control_deadline()
        admitted = False
        try:
            async with self._transition_scope(deadline):
                self._ensure_control_available()
                if self._generation is None:
                    raise RuntimeError(
                        "decision service has no safe runtime generation"
                    )
                self._desired_state = "PAUSED"
                admitted = True
                self._signal_control_waiters()
                # Keep the transition lock through the bounded poll boundary.
                await self._wait_for_poll_idle(deadline, operation="pause drainage")
                if self._service_state not in {"STOPPING", "STOPPED"}:
                    self._service_state = "PAUSED"
                self._sync_observability()
                return self.snapshot()
        except OperationTimeout as exc:
            if admitted:
                self._latch_control_timeout("pause", exc)
            raise DecisionControlError(f"pause control timed out: {exc}") from exc
        except asyncio.CancelledError:
            if admitted:
                self._desired_state = "PAUSED"
                if self._service_state not in {"STOPPING", "STOPPED"}:
                    self._service_state = "PAUSED"
                self._signal_control_waiters()
                self._sync_observability()
            raise

    async def resume(self) -> DecisionServiceSnapshot:
        return await self._manual_rebuild("resume")

    async def reconnect(self) -> DecisionServiceSnapshot:
        return await self._manual_rebuild("reconnect")

    def snapshot(self) -> DecisionServiceSnapshot:
        generation = self._generation
        runtime = None if generation is None else generation.live_runtime
        lanes: dict[str, Any] = {}
        status_counts: dict[str, int] = {}
        if runtime is not None:
            for lane_id, lane in runtime.lanes.items():
                status = lane.status
                status_counts[status] = status_counts.get(status, 0) + 1
                watermark = lane.finalizer.watermark
                last_result = self._last_lane_transactions.get(lane_id)
                lanes[lane_id] = {
                    "lane_id": lane_id,
                    "status": status,
                    "reason": lane.reason,
                    "pending_trigger_cutoff": lane.pending_trigger_cutoff,
                    "watermark": {
                        "latest_market_as_of": watermark.latest_market_as_of,
                        "last_disposition": watermark.last_disposition,
                    },
                    "last_transaction": None
                    if last_result is None
                    else {
                        "trigger_cutoff": last_result.trigger_cutoff,
                        "policy_status": last_result.policy_status,
                        "publication_outcome": last_result.publication_outcome,
                        "finalization_status": last_result.finalization_status,
                        "checkpoint_result": last_result.checkpoint_result,
                        "reason": last_result.reason,
                    },
                }
        inputs: dict[str, Any] = {}
        blocked_count = 0
        if runtime is not None:
            blocked = runtime.input.blocked_streams
            blocked_count = len(blocked)
            for stream_key, cursor in runtime.input.cursors.items():
                inputs[stream_key] = {
                    "latest_stream_id": cursor.latest_stream_id,
                    "latest_market_as_of": cursor.latest_market_as_of,
                    "blocked_reason": blocked.get(stream_key),
                }
            relay = getattr(runtime, "price_relay", None)
            if relay is not None:
                inputs["price_relay"] = {
                    relay_id: {
                        "stream_key": plan.stream_key,
                        "asset": plan.asset,
                        "timeframe": plan.timeframe,
                        "latest_market_as_of": progress.latest_market_as_of,
                        "continuity_status": progress.continuity_status,
                        "gap_evidence": progress.gap_evidence,
                    }
                    for relay_id, plan in relay.plans.items()
                    for progress in (relay.progress[relay_id],)
                }
        lifecycle_evidence = self._last_lifecycle_evidence
        return DecisionServiceSnapshot(
            service_state=self._service_state,
            desired_state=self._desired_state,
            generation_id=None if generation is None else generation.generation_id,
            started_at=self._started_at,
            last_poll_at=self._last_poll_at,
            last_rebuild_at=self._last_rebuild_at,
            last_lifecycle_event_at=self._last_lifecycle_event_at,
            last_error=self._last_error,
            configured_asset_count=self._configured_asset_count
            or (
                0
                if generation is None
                else len(generation.startup.snapshot.active_manifest_assets)
            ),
            configured_lane_count=self._configured_lane_count
            or (
                0 if generation is None else len(generation.startup.decision_plan.lanes)
            ),
            active_lane_count=len(lanes),
            lane_status_counts=status_counts,
            blocked_stream_count=blocked_count,
            lifecycle_cursor=(
                getattr(self._lifecycle_reader, "cursor", "0-0")
                if self._lifecycle_reader is not None
                else "0-0"
            ),
            lanes=lanes,
            inputs=inputs,
            last_lifecycle_evidence=(
                {}
                if lifecycle_evidence is None
                else {
                    "cursor": lifecycle_evidence.cursor,
                    "event_ids": lifecycle_evidence.event_ids,
                    "relevant_count": len(lifecycle_evidence.relevant_events),
                    "ignored_symbols": lifecycle_evidence.ignored_symbols,
                    "malformed_ids": lifecycle_evidence.malformed_ids,
                    "reason": lifecycle_evidence.reason,
                }
            ),
        )

    async def _manual_rebuild(self, reason: str) -> DecisionServiceSnapshot:
        deadline = self._control_deadline()
        admitted = False
        try:
            async with self._transition_scope(deadline):
                self._ensure_control_available()
                self._desired_state = "RUNNING"
                # Mark the old generation unusable before waiting.  The market
                # loop does not own the transition lock while polling, so this
                # state gate prevents a new old-generation transaction.
                self._service_state = "REBUILDING"
                self._rebuild_requested = True
                self._rebuild_reason = reason
                self._rebuild_source = "MANUAL"
                admitted = True
                self._signal_control_waiters()
                self._sync_observability()
                await self._wait_for_poll_idle(
                    deadline,
                    operation=f"{reason} drainage",
                )
                await self._rebuild_locked(reason)
                return self.snapshot()
        except OperationTimeout as exc:
            if admitted:
                self._latch_control_timeout(reason, exc)
            raise DecisionControlError(f"{reason} control timed out: {exc}") from exc
        except asyncio.CancelledError:
            if admitted:
                if self._stop_event.is_set():
                    self._service_state = "STOPPING"
                else:
                    # The cancelled caller no longer owns the rebuild
                    # coroutine.  Keep the transition explicitly pending so
                    # the market loop can take the retained request under the
                    # transition lock; never claim RUNNING.
                    self._service_state = "REBUILDING"
                    self._rebuild_requested = True
                    self._rebuild_reason = reason
                    self._rebuild_source = "MANUAL"
                self._signal_control_waiters()
                self._sync_observability()
            raise

    async def _build_generation(
        self,
        reason: str,
        *,
        deadline: Deadline | None = None,
    ) -> DecisionRuntimeGeneration:
        next_id = self._generation_number + 1
        if self._stop_event.is_set():
            raise DecisionControlError(
                f"{reason} generation rejected after stop intent"
            )
        generation_deadline = (
            deadline
            if deadline is not None
            else (
                None
                if self._generation_timeout_seconds is None
                else Deadline.after(self._generation_timeout_seconds)
            )
        )
        if generation_deadline is not None:
            require_remaining(
                generation_deadline,
                operation=f"{reason} generation build",
            )
        factory = self._generation_factory
        build = factory(reason=reason, generation_id=next_id)
        if generation_deadline is None:
            generation = await build
        else:
            generation = await run_until(
                build,
                generation_deadline,
                operation=f"{reason} generation build",
            )
            # A cancellation-resistant factory may swallow the timeout
            # cancellation and return a candidate after the deadline.  Never
            # install that late candidate.
            require_remaining(
                generation_deadline,
                operation=f"{reason} generation build",
            )
        if self._stop_event.is_set():
            raise DecisionControlError(
                f"{reason} generation completed after stop intent"
            )
        if not isinstance(generation, DecisionRuntimeGeneration):
            raise TypeError("generation_factory must return DecisionRuntimeGeneration")
        if generation.generation_id != next_id:
            raise ValueError(
                "generation_factory returned an unexpected generation_id: "
                f"{generation.generation_id} != {next_id}"
            )
        return generation

    def _install_generation(
        self,
        generation: DecisionRuntimeGeneration,
    ) -> None:
        if not isinstance(generation, DecisionRuntimeGeneration):
            raise TypeError("generation must be DecisionRuntimeGeneration")
        self._generation = generation
        self._generation_number = generation.generation_id
        self._last_lane_transactions.clear()
        self._last_rebuild_at = self._now()
        if self._observability is not None:
            observe_best_effort(
                self._observability.replace_generation,
                runtime=generation.live_runtime,
                input_series=getattr(
                    generation.startup.snapshot,
                    "series_positions",
                    {},
                ),
            )

    async def _rebuild_locked(
        self,
        reason: str,
    ) -> None:
        self._service_state = "REBUILDING"
        self._last_error = None
        self._market_error = None
        self._wake_event.clear()
        if self._observability is not None:
            observe_best_effort(self._observability.clear_generation)
        self._sync_observability()
        started = perf_counter()
        try:
            generation = await self._build_generation(reason)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if self._stop_event.is_set() or self._service_state == "STOPPING":
                self._service_state = "STOPPING"
                self._last_error = (
                    f"generation rebuild abandoned after stop intent: {exc}"
                )
                self._rebuild_requested = False
                self._rebuild_reason = None
                self._rebuild_source = None
                self._sync_observability()
                return
            self._generation = None
            self._service_state = "ERROR"
            self._last_error = f"generation rebuild failed: {exc}"
            self._rebuild_requested = False
            self._rebuild_reason = None
            self._rebuild_source = None
            if self._observability is not None:
                observe_best_effort(self._observability.clear_generation)
                observe_best_effort(
                    self._observability.record_rebuild,
                    outcome="failure",
                    duration_ms=(perf_counter() - started) * 1000.0,
                )
            self._sync_observability()
            return
        if self._observability is not None:
            observe_best_effort(
                self._observability.record_rebuild,
                outcome="success",
                duration_ms=(perf_counter() - started) * 1000.0,
            )
        if self._stop_event.is_set() or self._service_state == "STOPPING":
            self._service_state = "STOPPING"
            self._last_error = "late generation rejected after stop intent"
            self._sync_observability()
            return
        self._install_generation(generation)
        self._rebuild_requested = False
        self._rebuild_reason = None
        self._rebuild_source = None
        if self._desired_state == "PAUSED":
            self._service_state = "PAUSED"
        elif self._lifecycle_error is not None:
            self._service_state = "DEGRADED"
            self._last_error = self._lifecycle_error
        else:
            self._service_state = "RUNNING"
        self._wake_event.set()
        self._sync_observability()

    async def _market_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._rebuild_requested:
                async with self._transition_lock:
                    if self._stop_event.is_set():
                        continue
                    if not self._rebuild_requested:
                        continue
                    reason = self._rebuild_reason or "requested"
                    await self._rebuild_locked(reason)
                continue
            if self._service_state in {
                "STARTING",
                "REBUILDING",
                "STOPPING",
                "ERROR",
            }:
                await self._wait_for_wake()
                continue
            generation = self._generation
            if generation is None:
                self._service_state = "ERROR"
                await self._wait_for_wake()
                continue
            self._poll_active = True
            self._poll_idle.clear()
            poll_started = perf_counter()
            evaluate_lanes = self._desired_state == "RUNNING"
            transport_error = False
            wait_for_wake = False
            try:
                result = await generation.live_runtime.poll_once(
                    evaluate_lanes=evaluate_lanes
                )
            except asyncio.CancelledError:
                raise
            except InputTransportError as exc:
                if self._service_state not in _CONTROL_STATES:
                    self._service_state = "DEGRADED"
                self._market_error = f"market input transport failed: {exc}"
                self._last_error = self._market_error
                self._sync_observability()
                transport_error = True
            except Exception as exc:  # noqa: BLE001
                if self._service_state not in _CONTROL_STATES:
                    self._service_state = "ERROR"
                self._market_error = f"market poll failed: {exc}"
                self._last_error = self._market_error
                self._sync_observability()
                wait_for_wake = True
            finally:
                if self._observability is not None:
                    observe_best_effort(
                        self._observability.record_poll_duration,
                        (perf_counter() - poll_started) * 1000.0,
                    )
                self._poll_active = False
                self._poll_idle.set()
            if wait_for_wake:
                await self._wait_for_wake()
                continue
            if transport_error:
                await self._pace_transport_error()
                continue
            self._last_poll_at = self._now()
            self._last_poll_result = result
            for lane_id, lane_result in result.lane_results.items():
                if any(
                    value is not None
                    for value in (
                        lane_result.trigger_cutoff,
                        lane_result.policy_status,
                        lane_result.publication_outcome,
                        lane_result.finalization_status,
                        lane_result.checkpoint_result,
                    )
                ):
                    self._last_lane_transactions[lane_id] = lane_result
            self._classify_poll_result(result)
            self._sync_observability()
            self._wake_event.set()
            if result.clock_waiting:
                await self._wait_for_clock_catchup(
                    allow_pause_transition=evaluate_lanes
                )
            else:
                # A deterministic test/runtime double may complete poll_once()
                # without transport I/O.  Always yield so controls and
                # lifecycle notifications retain ownership of the event loop.
                await asyncio.sleep(0)

    async def _lifecycle_loop(self) -> None:
        assert self._lifecycle_reader is not None
        while not self._stop_event.is_set():
            try:
                result = await self._lifecycle_reader.read_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                if self._service_state not in _CONTROL_STATES:
                    self._service_state = "DEGRADED"
                self._lifecycle_error = f"lifecycle input failed: {exc}"
                if self._market_error is not None:
                    self._last_error = self._market_error
                elif self._service_state != "ERROR":
                    self._last_error = self._lifecycle_error
                self._sync_observability()
                await self._pace_transport_error()
                continue
            self._lifecycle_error = None
            self._last_lifecycle_evidence = result
            if result.event_ids:
                self._last_lifecycle_event_at = self._now()
            if result.rebuild_requested:
                async with self._transition_lock:
                    if self._service_state not in {"STOPPING", "STOPPED"}:
                        self._rebuild_requested = True
                        self._rebuild_reason = (
                            result.reason or "configured asset lifecycle changed"
                        )
                        self._rebuild_source = "LIFECYCLE_RECONCILIATION"
                self._signal_control_waiters()
                self._sync_observability()
            else:
                await asyncio.sleep(0)

    def _classify_poll_result(self, result: DecisionPollResult) -> None:
        reconstruction = any(
            item.disposition == "RECONSTRUCTION_REQUIRED"
            for item in result.input_results
        ) or any(
            item.status == "RECONSTRUCTION_REQUIRED"
            for item in result.lane_results.values()
        )
        hard_failure = any(
            item.disposition in {"CONFLICT", "MALFORMED"}
            for item in result.input_results
        ) or any(
            item.status in {"INVALID", "HALTED"}
            for item in result.lane_results.values()
        )
        forward_input_gap = any(
            item.disposition == "RECONSTRUCTION_REQUIRED"
            and item.reason == FORWARD_CANONICAL_MARKET_GAP_REASON
            for item in result.input_results
        )
        relay_failure = any(
            item.continuity_status != "CONTINUOUS"
            or item.publication_outcome in {"FAILED", "CONFLICT"}
            for item in result.relay_results.values()
        )
        if hard_failure:
            # A malformed/conflicting input or a halted/invalid lane is an
            # operator-visible fault, not an automatic reconstruction trigger.
            # Preserve an already-requested lifecycle rebuild that arrived
            # while this bounded poll was running, but never create one from
            # the failed poll itself.
            if self._rebuild_source != "LIFECYCLE_RECONCILIATION":
                self._rebuild_requested = False
                self._rebuild_reason = None
                self._rebuild_source = None
            if self._service_state not in _CONTROL_STATES:
                self._service_state = "DEGRADED"
            self._market_error = "D9B reported a non-rebuildable lane or input fault"
            self._last_error = self._market_error
        elif forward_input_gap:
            # Only this exact input-side condition proves that the current
            # direct-cursor position cannot bridge the canonical sequence.
            # Generic lane/input reconstruction remains lane-local below.
            if self._rebuild_source == "LIFECYCLE_RECONCILIATION":
                # Lifecycle reconciliation has stronger authority when it was
                # already admitted while this poll was executing.
                self._rebuild_requested = True
            elif not self._rebuild_requested or self._rebuild_source is None:
                self._rebuild_requested = True
                self._rebuild_reason = FORWARD_CANONICAL_MARKET_GAP_REASON
                self._rebuild_source = "INPUT_RECONSTRUCTION"
            if self._service_state not in _CONTROL_STATES:
                self._service_state = "DEGRADED"
            self._market_error = (
                "D9B reported forward canonical market gap; "
                "durable generation reconstruction requested"
            )
            self._last_error = self._market_error
            self._signal_control_waiters()
        elif reconstruction:
            if self._service_state not in _CONTROL_STATES:
                self._service_state = "DEGRADED"
            self._market_error = "D9B reported reconstruction required"
            self._last_error = self._market_error
        elif relay_failure:
            if self._service_state not in _CONTROL_STATES:
                self._service_state = "DEGRADED"
            self._market_error = "D9D reported price-relay continuity failure"
            self._last_error = self._market_error
        else:
            if self._service_state not in _CONTROL_STATES:
                self._market_error = None
                if self._lifecycle_error is not None:
                    self._service_state = "DEGRADED"
                    self._last_error = self._lifecycle_error
                else:
                    self._service_state = "RUNNING"
                    self._last_error = None

    async def _pace_transport_error(self) -> None:
        if self._block_ms > 0:
            try:
                async with asyncio.timeout(self._block_ms / 1000):
                    await self._stop_event.wait()
            except TimeoutError:
                pass
        else:
            await asyncio.sleep(0)

    def _control_deadline(self) -> Deadline | None:
        if self._control_wait_timeout_seconds is None:
            return None
        return Deadline.after(self._control_wait_timeout_seconds)

    @asynccontextmanager
    async def _transition_scope(self, deadline: Deadline | None):
        acquired = False
        try:
            if deadline is None:
                await self._transition_lock.acquire()
            else:
                await run_until(
                    self._transition_lock.acquire(),
                    deadline,
                    operation="control admission",
                )
            acquired = True
            yield
        finally:
            if acquired:
                self._transition_lock.release()

    async def _wait_for_poll_idle(
        self,
        deadline: Deadline | None,
        *,
        operation: str,
    ) -> None:
        if deadline is None:
            await self._poll_idle.wait()
            return
        await run_until(
            self._poll_idle.wait(),
            deadline,
            operation=operation,
        )

    def _latch_control_timeout(self, reason: str, exc: OperationTimeout) -> None:
        if self._stop_event.is_set() or self._service_state in {"STOPPING", "STOPPED"}:
            self._service_state = "STOPPING"
            self._sync_observability()
            return
        self._service_state = "ERROR"
        self._last_error = f"{reason} control timed out: {exc}"
        self._sync_observability()

    async def _wait_for_clock_catchup(self, *, allow_pause_transition: bool) -> None:
        """Bound clock-wait retries while keeping controls responsive."""

        self._clock_wait_event.clear()
        if (
            self._stop_event.is_set()
            or self._rebuild_requested
            or self._service_state
            in {"STARTING", "REBUILDING", "STOPPING", "STOPPED", "ERROR"}
        ):
            return
        if allow_pause_transition and self._desired_state != "RUNNING":
            return
        cadence_ms = self._block_ms if self._block_ms > 0 else 1000
        try:
            async with asyncio.timeout(cadence_ms / 1000):
                await self._clock_wait_event.wait()
        except TimeoutError:
            pass

    def _signal_control_waiters(self) -> None:
        self._wake_event.set()
        self._clock_wait_event.set()

    async def _wait_for_wake(self) -> None:
        if self._stop_event.is_set():
            return
        await self._wake_event.wait()
        self._wake_event.clear()

    async def _await_task(
        self,
        task: asyncio.Task[Any] | None,
        *,
        deadline: Deadline | None,
        operation: str,
    ) -> bool:
        if task is None:
            return True
        if task.done():
            try:
                task.result()
            except BaseException:  # noqa: BLE001, S110
                pass
            return True
        if deadline is None:
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if task.cancelled():
                    return True
                raise
            except Exception:  # noqa: BLE001
                return True
            return True
        try:
            await cleanup_with_timeout(
                task,
                deadline.remaining(),
                operation=operation,
                retained_tasks=self._retained_cleanup_tasks,
            )
        except asyncio.CancelledError:
            raise
        except CleanupTimeout:
            return task.cancelled()
        except Exception:  # noqa: BLE001
            return True
        return True

    def _ensure_control_available(self) -> None:
        if self._service_state in {"STOPPING", "STOPPED"}:
            raise RuntimeError("decision service is stopping or stopped")

    def _sync_observability(self) -> None:
        if self._observability is None:
            return
        observe_best_effort(
            self._observability.set_service_state,
            self._service_state,
        )
        generation = self._generation
        if generation is None:
            observe_best_effort(self._observability.clear_generation)
        else:
            observe_best_effort(
                self._observability.refresh_runtime,
                generation.live_runtime,
            )

    def _now(self) -> datetime:
        value = self._now_fn()
        require_utc(value, field_name="service time")
        return value


__all__ = [
    "DecisionControlError",
    "DecisionRuntimeGeneration",
    "DecisionService",
    "DecisionServiceSnapshot",
    "DesiredState",
    "GenerationFactory",
    "RebuildSource",
    "ServiceState",
]
