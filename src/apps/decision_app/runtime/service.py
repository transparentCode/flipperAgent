"""ASGI-owned D9C service shell around the approved D9A/D9B primitives."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from apps.decision_app.runtime.lifecycle import (
    LifecycleNotificationReader,
    LifecycleReadResult,
)
from apps.decision_app.runtime.live import DecisionPollResult
from apps.decision_app.transport.live_input import InputTransportError
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
RebuildSource = Literal["LIFECYCLE_RECONCILIATION", "MANUAL"]

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
        now_fn: Callable[[], datetime] | None = None,
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
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self._transition_lock = asyncio.Lock()
        self._wake_event = asyncio.Event()
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
        self._last_poll_result: DecisionPollResult | None = None
        self._last_lane_transactions: dict[str, Any] = {}
        self._last_lifecycle_evidence: LifecycleReadResult | None = None
        self._rebuild_requested = False
        self._rebuild_reason: str | None = None
        self._rebuild_source: RebuildSource | None = None
        self._poll_active = False

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
    ) -> DecisionServiceSnapshot:
        """Install the initial generation and start the two service tasks."""

        async with self._transition_lock:
            if self._service_state not in {"STARTING", "STOPPED"}:
                raise RuntimeError("decision service is already started")
            self._stop_event = asyncio.Event()
            self._wake_event = asyncio.Event()
            self._poll_idle = asyncio.Event()
            self._poll_idle.set()
            self._desired_state = "RUNNING"
            self._service_state = "STARTING"
            self._last_error = None
            self._rebuild_requested = False
            self._rebuild_reason = None
            self._rebuild_source = None
            if generation is None:
                generation = await self._build_generation("initial")
            self._install_generation(generation)
            self._started_at = self._now()
            self._service_state = "RUNNING"
            self._market_task = asyncio.create_task(
                self._market_loop(), name="decision-market-loop"
            )
            if self._lifecycle_reader is not None:
                self._lifecycle_task = asyncio.create_task(
                    self._lifecycle_loop(), name="decision-lifecycle-loop"
                )
        return self.snapshot()

    async def stop(self) -> DecisionServiceSnapshot:
        """Stop after the current bounded poll, without cancelling it."""

        async with self._transition_lock:
            if self._service_state == "STOPPED":
                return self.snapshot()
            self._desired_state = "PAUSED"
            self._service_state = "STOPPING"
            self._stop_event.set()
            self._wake_event.set()
        await self._poll_idle.wait()
        lifecycle_task = self._lifecycle_task
        if lifecycle_task is not None and not lifecycle_task.done():
            lifecycle_task.cancel()
        await self._await_task(lifecycle_task)
        await self._await_task(self._market_task)
        async with self._transition_lock:
            self._service_state = "STOPPED"
            self._lifecycle_task = None
            self._market_task = None
        return self.snapshot()

    async def pause(self) -> DecisionServiceSnapshot:
        async with self._transition_lock:
            self._ensure_control_available()
            if self._generation is None:
                raise RuntimeError("decision service has no safe runtime generation")
            self._desired_state = "PAUSED"
            self._wake_event.set()
            # Keep the transition lock through the bounded poll boundary.  A
            # concurrent resume/reconnect must not change desired_state or
            # install a new polling generation before this pause returns.
            await self._poll_idle.wait()
            if self._service_state not in {"STOPPING", "STOPPED"}:
                self._service_state = "PAUSED"
            return self.snapshot()

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
        async with self._transition_lock:
            self._ensure_control_available()
            self._desired_state = "RUNNING"
            # Mark the old generation unusable before waiting.  The market
            # loop does not own the transition lock while polling, so this
            # state gate is what prevents a paused/reconnecting service from
            # starting one more old-generation transaction.
            self._service_state = "REBUILDING"
            self._rebuild_requested = True
            self._rebuild_reason = reason
            self._rebuild_source = "MANUAL"
            self._wake_event.set()
            await self._poll_idle.wait()
            await self._rebuild_locked(reason)
            return self.snapshot()

    async def _build_generation(self, reason: str) -> DecisionRuntimeGeneration:
        next_id = self._generation_number + 1
        factory = self._generation_factory
        generation = await factory(reason=reason, generation_id=next_id)
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

    async def _rebuild_locked(
        self,
        reason: str,
    ) -> None:
        self._service_state = "REBUILDING"
        self._last_error = None
        self._wake_event.clear()
        try:
            generation = await self._build_generation(reason)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._generation = None
            self._service_state = "ERROR"
            self._last_error = f"generation rebuild failed: {exc}"
            self._rebuild_requested = False
            self._rebuild_reason = None
            self._rebuild_source = None
            return
        self._install_generation(
            generation,
        )
        self._rebuild_requested = False
        self._rebuild_reason = None
        self._rebuild_source = None
        self._service_state = "PAUSED" if self._desired_state == "PAUSED" else "RUNNING"
        self._wake_event.set()

    async def _market_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._service_state in {
                "STARTING",
                "REBUILDING",
                "STOPPING",
                "ERROR",
            }:
                await self._wait_for_wake()
                continue
            if self._rebuild_requested:
                async with self._transition_lock:
                    if self._stop_event.is_set():
                        continue
                    reason = self._rebuild_reason or "requested"
                    await self._rebuild_locked(reason)
                continue
            generation = self._generation
            if generation is None:
                self._service_state = "ERROR"
                await self._wait_for_wake()
                continue
            self._poll_active = True
            self._poll_idle.clear()
            try:
                result = await generation.live_runtime.poll_once(
                    evaluate_lanes=self._desired_state == "RUNNING"
                )
            except asyncio.CancelledError:
                raise
            except InputTransportError as exc:
                if self._service_state not in _CONTROL_STATES:
                    self._service_state = "DEGRADED"
                self._last_error = f"market input transport failed: {exc}"
                await self._pace_transport_error()
                continue
            except Exception as exc:  # noqa: BLE001
                if self._service_state not in _CONTROL_STATES:
                    self._service_state = "ERROR"
                self._last_error = f"market poll failed: {exc}"
                await self._wait_for_wake()
                continue
            finally:
                self._poll_active = False
                self._poll_idle.set()
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
            self._wake_event.set()
            # A deterministic test/runtime double may complete poll_once()
            # without transport I/O.  Always yield so controls and lifecycle
            # notifications retain ownership of the event loop.
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
                self._last_error = f"lifecycle input failed: {exc}"
                await self._pace_transport_error()
                continue
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
                self._wake_event.set()
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
            self._last_error = "D9B reported a non-rebuildable lane or input fault"
        elif reconstruction:
            if self._service_state not in _CONTROL_STATES:
                self._service_state = "DEGRADED"
            self._last_error = "D9B reported reconstruction required"
        elif relay_failure:
            if self._service_state not in _CONTROL_STATES:
                self._service_state = "DEGRADED"
            self._last_error = "D9D reported price-relay continuity failure"
        else:
            if self._service_state not in _CONTROL_STATES:
                self._service_state = "RUNNING"
                self._last_error = None

    async def _pace_transport_error(self) -> None:
        if self._block_ms > 0:
            await asyncio.sleep(self._block_ms / 1000)
        else:
            await asyncio.sleep(0)

    async def _wait_for_wake(self) -> None:
        if self._stop_event.is_set():
            return
        await self._wake_event.wait()
        self._wake_event.clear()

    async def _await_task(self, task: asyncio.Task[Any] | None) -> None:
        if task is None:
            return
        try:
            await task
        except asyncio.CancelledError:
            pass

    def _ensure_control_available(self) -> None:
        if self._service_state in {"STOPPING", "STOPPED"}:
            raise RuntimeError("decision service is stopping or stopped")

    def _now(self) -> datetime:
        value = self._now_fn()
        require_utc(value, field_name="service time")
        return value


__all__ = [
    "DecisionRuntimeGeneration",
    "DecisionService",
    "DecisionServiceSnapshot",
    "DesiredState",
    "GenerationFactory",
    "RebuildSource",
    "ServiceState",
]
