"""One bounded D9B live input-to-decision transaction.

This is deliberately a poll primitive, not a service supervisor.  It keeps
direct input progress, lane scheduling, D8 finalization, and checkpoint
durability explicit without adding a queue, worker-per-lane task, or replay
framework.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any, Literal

from apps.decision_app.domain.market_state import (
    BarStore,
    MarketSeriesKey,
    TimeframeGrid,
    validate_canonical_bar_geometry,
)
from apps.decision_app.domain.state import LaneExecutionIdentity
from apps.decision_app.domain.view import (
    DecisionViewBuilder,
    MarketViewNotReadyError,
)
from apps.decision_app.features.engine import FeatureEngine
from apps.decision_app.observability import DecisionObservability
from apps.decision_app.planning.planner import ResolvedLanePlan
from apps.decision_app.planning.readiness import (
    compile_lane_causal_history_requirements,
)
from apps.decision_app.runtime.finalization import (
    FinalizationReceipt,
    LaneFinalizer,
)
from apps.decision_app.runtime.models import ModelRuntime
from apps.decision_app.runtime.policy import (
    PASSTHROUGH_V1,
    PRIORITY_V1,
    DecisionPolicy,
    DecisionPolicyCatalog,
)
from apps.decision_app.runtime.startup import DecisionStartupResult
from apps.decision_app.storage.checkpoints import (
    CheckpointSaveResult,
    InMemoryCheckpointRepository,
    LaneStateCheckpoint,
)
from apps.decision_app.storage.shadow_progress import (
    InMemoryLaneEffectProgressRepository,
    LaneEffectProgress,
    LaneEffectProgressSaveResult,
)
from apps.decision_app.transport.ingestion import CanonicalMarketEvent
from apps.decision_app.transport.live_input import (
    DirectCursorInput,
    InputRecordResult,
)
from apps.decision_app.transport.price_relay import PriceRelay, PriceRelayResult
from apps.decision_app.transport.publication import (
    SignalPublicationAck,
    build_signal_envelope,
)
from apps.decision_app.transport.shadow import (
    ShadowPublicationAck,
    build_shadow_envelope,
)
from libs.contracts.decision import FrozenMapping, require_utc

LiveLaneStatus = Literal[
    "LIVE",
    "WAITING",
    "HALTED",
    "RECONSTRUCTION_REQUIRED",
    "INVALID",
]


@dataclass(slots=True)
class _LanePollEvidence:
    """Transaction-local evidence for one lane in one bounded poll."""

    trigger_cutoff: datetime | None = None
    policy_status: str | None = None
    publication_outcome: str | None = None
    finalization_status: str | None = None
    checkpoint_result: str | None = None

    def begin(self, cutoff: datetime) -> None:
        self.trigger_cutoff = cutoff
        self.policy_status = None
        self.publication_outcome = None
        self.finalization_status = None
        self.checkpoint_result = None


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


@dataclass(slots=True)
class LiveLane:
    """Mutable D9B ownership for one authoritative lane."""

    lane: ResolvedLanePlan
    runtime: ModelRuntime
    feature_plan: Any
    market_requirements: Any
    finalizer: LaneFinalizer
    state_inception_at: datetime | None
    startup_catchup_cutoffs: tuple[datetime, ...] = ()
    startup_catchup_index: int = 0
    startup_catchup_store: BarStore | None = None
    startup_catchup_view_builder: DecisionViewBuilder | None = None
    startup_catchup_feature_engine: FeatureEngine | None = None
    pending_trigger_cutoff: datetime | None = None
    reconciliation_attempted: bool = False
    status: LiveLaneStatus = "LIVE"
    reason: str | None = None

    @property
    def lane_id(self) -> str:
        return self.lane.lane_id

    @property
    def identity(self) -> LaneExecutionIdentity:
        return self.runtime.identity


@dataclass(frozen=True, slots=True, kw_only=True)
class LanePollResult:
    """Bounded evidence for one lane after a poll attempt."""

    lane_id: str
    status: LiveLaneStatus
    trigger_cutoff: datetime | None = None
    policy_status: str | None = None
    publication_outcome: str | None = None
    finalization_status: str | None = None
    checkpoint_result: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        _text(self.lane_id, "lane_id")
        if self.status not in {
            "LIVE",
            "WAITING",
            "HALTED",
            "RECONSTRUCTION_REQUIRED",
            "INVALID",
        }:
            raise ValueError("unsupported live lane status")
        if self.trigger_cutoff is not None:
            require_utc(self.trigger_cutoff, field_name="trigger_cutoff")
        if self.reason is not None:
            _text(self.reason, "lane result reason")


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionPollResult:
    """Bounded result of one D9B input poll."""

    input_results: tuple[InputRecordResult, ...]
    lane_results: Mapping[str, LanePollResult]
    cursors: Mapping[str, Any]
    relay_results: Mapping[str, PriceRelayResult] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if any(not isinstance(item, InputRecordResult) for item in self.input_results):
            raise TypeError("input_results must contain InputRecordResult values")
        normalized: dict[str, LanePollResult] = {}
        for lane_id, result in self.lane_results.items():
            if not isinstance(result, LanePollResult) or lane_id != result.lane_id:
                raise ValueError("lane result map key must match lane_id")
            normalized[lane_id] = result
        object.__setattr__(
            self, "lane_results", FrozenMapping(dict(sorted(normalized.items())))
        )
        if not isinstance(self.cursors, Mapping):
            raise TypeError("cursors must be a mapping")
        object.__setattr__(
            self, "cursors", FrozenMapping(dict(sorted(self.cursors.items())))
        )
        normalized_relays: dict[str, PriceRelayResult] = {}
        for relay_id, result in self.relay_results.items():
            if (
                not isinstance(result, PriceRelayResult)
                or relay_id != result.relay_plan_id
            ):
                raise ValueError("relay result map key must match relay_plan_id")
            normalized_relays[relay_id] = result
        object.__setattr__(
            self,
            "relay_results",
            FrozenMapping(dict(sorted(normalized_relays.items()))),
        )


class LiveRuntimeError(ValueError):
    """Base D9B bounded live runtime error."""


class LiveRuntimeHalt(LiveRuntimeError):
    """Raised when a lane cannot safely continue its causal transaction."""


class LiveDecisionRuntime:
    """Serial, bounded live processor for startup-ready lanes."""

    def __init__(
        self,
        *,
        startup: DecisionStartupResult,
        timeframe_grid: TimeframeGrid,
        stream_client: Any,
        history_repository: Any,
        signal_publisher: Any | None = None,
        shadow_publisher: Any | None = None,
        checkpoint_repository: Any | None = None,
        shadow_progress_repository: Any | None = None,
        price_relay: PriceRelay | None = None,
        policy_catalog: DecisionPolicyCatalog | None = None,
        batch_size: int = 10,
        block_ms: int = 1000,
        now_fn: Callable[[], datetime] | None = None,
        observability: DecisionObservability | None = None,
    ) -> None:
        if not isinstance(startup, DecisionStartupResult):
            raise TypeError("startup must be DecisionStartupResult")
        if startup.snapshot.status != "STARTUP_READY":
            raise LiveRuntimeError("D9B requires STARTUP_READY startup evidence")
        if not isinstance(timeframe_grid, TimeframeGrid):
            raise TypeError("timeframe_grid must be TimeframeGrid")
        if not callable(getattr(history_repository, "fetch_bars", None)):
            raise TypeError("history_repository must provide fetch_bars()")
        if signal_publisher is not None and not callable(
            getattr(signal_publisher, "publish", None)
        ):
            raise TypeError("signal_publisher must provide publish()")
        if shadow_publisher is not None and not callable(
            getattr(shadow_publisher, "publish", None)
        ):
            raise TypeError("shadow_publisher must provide publish()")
        if checkpoint_repository is not None and (
            not callable(getattr(checkpoint_repository, "save", None))
            or not callable(getattr(checkpoint_repository, "load", None))
        ):
            raise TypeError("checkpoint_repository must provide load() and save()")
        self._startup = startup
        self._grid = timeframe_grid
        self._store: BarStore = startup.bar_store
        self._history = history_repository
        self._publisher = signal_publisher
        self._shadow_publisher = shadow_publisher
        self._checkpoints = (
            InMemoryCheckpointRepository()
            if checkpoint_repository is None
            else checkpoint_repository
        )
        self._effect_progress = (
            InMemoryLaneEffectProgressRepository()
            if shadow_progress_repository is None
            else shadow_progress_repository
        )
        if not callable(getattr(self._effect_progress, "save", None)):
            raise TypeError("lane effect progress repository must provide save()")
        self._policy = DecisionPolicy(
            DecisionPolicyCatalog([PASSTHROUGH_V1, PRIORITY_V1])
            if policy_catalog is None
            else policy_catalog
        )
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        if observability is not None and not isinstance(
            observability, DecisionObservability
        ):
            raise TypeError("observability must be DecisionObservability or None")
        self._observability = observability
        if price_relay is not None and not isinstance(price_relay, PriceRelay):
            raise TypeError("price_relay must be PriceRelay or None")
        self._price_relay = price_relay
        self._reader = DirectCursorInput(
            stream_client=stream_client,
            startup_positions=startup.snapshot.series_positions,
            bar_store=self._store,
            history_repository=history_repository,
            timeframe_grid=timeframe_grid,
            batch_size=batch_size,
            block_ms=block_ms,
        )
        self._view_builder = DecisionViewBuilder(self._store, timeframe_grid)
        self._lanes: dict[str, LiveLane] = {}
        for lane in startup.decision_plan.lanes:
            evidence = startup.snapshot.lane_evidence[lane.lane_id]
            runtime = startup.runtimes.get(lane.lane_id)
            if evidence.status != "STARTUP_READY" or runtime is None:
                continue
            catchup_store = startup.lane_catchup_stores.get(lane.lane_id)
            catchup_view_builder = None
            catchup_feature_engine = None
            if catchup_store is not None:
                base_feature_engine = getattr(runtime, "_feature_engine", None)
                feature_catalog = getattr(base_feature_engine, "_feature_catalog", None)
                if feature_catalog is None:
                    raise LiveRuntimeError(
                        "startup catch-up runtime has no feature catalog"
                    )
                catchup_view_builder = DecisionViewBuilder(
                    catchup_store, timeframe_grid
                )
                catchup_feature_engine = FeatureEngine(
                    feature_catalog,
                    catchup_store,
                    timeframe_grid,
                )
            self._lanes[lane.lane_id] = LiveLane(
                lane=lane,
                runtime=runtime,
                feature_plan=startup.feature_plans[lane.lane_id],
                market_requirements=startup.lane_requirements[lane.lane_id],
                finalizer=LaneFinalizer(
                    lane,
                    runtime,
                    startup.snapshot.lane_watermarks[lane.lane_id],
                ),
                state_inception_at=evidence.state_inception_at,
                startup_catchup_cutoffs=startup.lane_catchup_cutoffs.get(
                    lane.lane_id, ()
                ),
                startup_catchup_store=catchup_store,
                startup_catchup_view_builder=catchup_view_builder,
                startup_catchup_feature_engine=catchup_feature_engine,
            )
        self._lanes_by_series: dict[MarketSeriesKey, tuple[str, ...]] = {}
        series_lanes: dict[MarketSeriesKey, list[str]] = {}
        for live_lane in self._lanes.values():
            merged = compile_lane_causal_history_requirements(
                live_lane.lane,
                live_lane.feature_plan,
                self._grid,
            )
            for key in merged:
                series_lanes.setdefault(key, []).append(live_lane.lane_id)
        self._lanes_by_series = FrozenMapping(
            {
                key: tuple(sorted(values))
                for key, values in sorted(
                    series_lanes.items(), key=lambda item: item[0].timeframe
                )
            }
        )

    @property
    def input(self) -> DirectCursorInput:
        return self._reader

    @property
    def price_relay(self) -> PriceRelay | None:
        return self._price_relay

    @property
    def lanes(self) -> Mapping[str, LiveLane]:
        return FrozenMapping(dict(sorted(self._lanes.items())))

    async def poll_once(self, *, evaluate_lanes: bool = True) -> DecisionPollResult:
        """Read/process one bounded batch and return bounded evidence."""

        if not isinstance(evaluate_lanes, bool):
            raise TypeError("evaluate_lanes must be bool")

        poll_evidence = {lane_id: _LanePollEvidence() for lane_id in self._lanes}
        if evaluate_lanes and not await self._drain_startup_catchup(poll_evidence):
            lane_results = {
                lane_id: self._lane_result(live_lane, poll_evidence[lane_id])
                for lane_id, live_lane in sorted(self._lanes.items())
            }
            return DecisionPollResult(
                input_results=(),
                lane_results=lane_results,
                cursors=self._reader.cursors,
                relay_results={},
            )

        batch = await self._reader.read_once()
        input_results: list[InputRecordResult] = []
        relay_results: dict[str, PriceRelayResult] = {}
        failed_streams: set[str] = set()
        deferred_failures: dict[str, InputRecordResult] = {}
        for failure in batch.failures:
            # Keep the first parser failure for each stream.  The parser stops
            # at that point, so any later same-stream evidence is not safe to
            # surface as a second failure.
            deferred_failures.setdefault(failure.stream_key, failure)

        records_by_stream: dict[str, list[Any]] = {}
        for pending in batch.records:
            records_by_stream.setdefault(pending.stream_key, []).append(pending)
        positions = {stream_key: 0 for stream_key in records_by_stream}

        def surface_ready_failures() -> None:
            """Block streams only after their valid parsed prefix is handled."""

            for stream_key, failure in sorted(deferred_failures.items()):
                if stream_key in failed_streams:
                    continue
                if positions.get(stream_key, 0) < len(
                    records_by_stream.get(stream_key, ())
                ):
                    continue
                self._reader.block_stream(
                    stream_key,
                    failure.reason or "malformed input",
                )
                input_results.append(failure)
                self._record_input_result(failure, accepted_at=self._now())
                affected_relays = self._mark_series_failure(
                    failure.series_key,
                    failure.reason or "malformed input",
                    observed_target_market_as_of=failure.market_as_of,
                )
                self._refresh_relay_evidence(affected_relays, relay_results)
                failed_streams.add(stream_key)

        def current_heads() -> dict[str, Any]:
            heads: dict[str, Any] = {}
            for stream_key, records in records_by_stream.items():
                if stream_key in failed_streams:
                    continue
                position = positions[stream_key]
                if position < len(records):
                    heads[stream_key] = records[position]
            return heads

        while True:
            heads = current_heads()
            if not heads:
                break
            cutoff = min(pending.event.bar.market_as_of for pending in heads.values())

            # Keep consuming current heads at this cutoff so every series
            # visible at one market cutoff is applied before any lane runs.
            accepted_bars: dict[MarketSeriesKey, Any] = {}
            while True:
                heads = current_heads()
                same_cutoff = [
                    (stream_key, pending)
                    for stream_key, pending in heads.items()
                    if pending.event.bar.market_as_of == cutoff
                ]
                if not same_cutoff:
                    break
                for stream_key, pending in sorted(
                    same_cutoff,
                    key=lambda item: (
                        item[0],
                        tuple(int(part) for part in item[1].stream_id.split("-")),
                    ),
                ):
                    positions[stream_key] += 1
                    if stream_key in failed_streams:
                        continue
                    result = await self._reader.accept(pending)
                    accepted_at = self._now()
                    input_results.append(result)
                    self._record_input_result(result, accepted_at=accepted_at)
                    if result.disposition in {
                        "RECONSTRUCTION_REQUIRED",
                        "CONFLICT",
                        "MALFORMED",
                    }:
                        self._mark_series_failure(
                            pending.event.series_key,
                            result.reason or result.disposition,
                            observed_target_market_as_of=result.market_as_of,
                        )
                        failed_streams.add(stream_key)
                    elif result.disposition == "INSERTED":
                        accepted_bars[pending.event.series_key] = pending.event.bar
                        if evaluate_lanes:
                            self._schedule_trigger(pending.event)
                    elif result.disposition in {"DUPLICATE", "ALREADY_REPRESENTED"}:
                        accepted_bars[pending.event.series_key] = pending.event.bar

            if self._price_relay is not None:
                relay_results.update(
                    await self._price_relay.reconcile_all(accepted_bars)
                )
            if evaluate_lanes:
                await self._attempt_pending_lanes(poll_evidence)
            # A parser failure is the next ordered item only after every
            # valid record from that stream has been consumed.  This keeps a
            # successful prefix transactionally visible even when its suffix
            # is malformed, while still blocking the stream before any later
            # poll can read past the failure.
            surface_ready_failures()
        surface_ready_failures()
        if self._price_relay is not None and not relay_results:
            # A downstream price stream can be behind the startup canonical
            # cutoff even when this XREAD has no new ingestion records.  Give
            # the relay one bounded reconciliation attempt rather than
            # waiting for an unrelated market event.
            relay_results.update(await self._price_relay.reconcile_all())
        lane_results = {
            lane_id: self._lane_result(live_lane, poll_evidence[lane_id])
            for lane_id, live_lane in sorted(self._lanes.items())
        }
        return DecisionPollResult(
            input_results=tuple(input_results),
            lane_results=lane_results,
            cursors=self._reader.cursors,
            relay_results=relay_results,
        )

    async def _drain_startup_catchup(
        self,
        poll_evidence: Mapping[str, _LanePollEvidence],
    ) -> bool:
        """Drain durable lane-effect backlog before accepting newer input."""

        for lane_id in sorted(self._lanes):
            live_lane = self._lanes[lane_id]
            while live_lane.startup_catchup_index < len(
                live_lane.startup_catchup_cutoffs
            ):
                if live_lane.status not in {"LIVE", "WAITING"}:
                    return False
                cutoff = live_lane.startup_catchup_cutoffs[
                    live_lane.startup_catchup_index
                ]
                watermark = live_lane.finalizer.watermark.latest_market_as_of
                if watermark is not None and cutoff <= watermark:
                    live_lane.startup_catchup_index += 1
                    continue
                if live_lane.pending_trigger_cutoff is not None:
                    return False
                live_lane.pending_trigger_cutoff = cutoff
                live_lane.reconciliation_attempted = False
                await self._attempt_lane(live_lane, poll_evidence[lane_id])
                if live_lane.pending_trigger_cutoff is not None:
                    return False
                if live_lane.status not in {"LIVE", "WAITING"}:
                    return False
                if live_lane.finalizer.watermark.latest_market_as_of != cutoff:
                    self._halt_lane(
                        live_lane,
                        "HALTED",
                        "lane effect catch-up did not advance its effect watermark",
                    )
                    return False
                live_lane.startup_catchup_index += 1
                if live_lane.startup_catchup_index >= len(
                    live_lane.startup_catchup_cutoffs
                ):
                    live_lane.startup_catchup_store = None
                    live_lane.startup_catchup_view_builder = None
                    live_lane.startup_catchup_feature_engine = None
        return True

    def _schedule_trigger(self, event: CanonicalMarketEvent) -> None:
        for lane_id in self._lanes_by_series.get(event.series_key, ()):
            live_lane = self._lanes[lane_id]
            if live_lane.status not in {"LIVE", "WAITING"}:
                continue
            if live_lane.market_requirements.trigger_series != event.series_key:
                continue
            watermark = live_lane.finalizer.watermark.latest_market_as_of
            cutoff = event.bar.market_as_of
            if watermark is not None and cutoff <= watermark:
                continue
            pending = live_lane.pending_trigger_cutoff
            if pending is None:
                live_lane.pending_trigger_cutoff = cutoff
                live_lane.reconciliation_attempted = False
            elif cutoff == pending:
                continue
            elif cutoff > pending:
                self._halt_lane(
                    live_lane,
                    "RECONSTRUCTION_REQUIRED",
                    "newer trigger overtook unresolved pending cutoff",
                )

    async def _attempt_pending_lanes(
        self,
        poll_evidence: Mapping[str, _LanePollEvidence],
    ) -> None:
        for lane_id in sorted(self._lanes):
            live_lane = self._lanes[lane_id]
            if live_lane.pending_trigger_cutoff is None:
                continue
            if live_lane.status not in {"LIVE", "WAITING"}:
                continue
            await self._attempt_lane(live_lane, poll_evidence[lane_id])

    async def _attempt_lane(
        self,
        live_lane: LiveLane,
        evidence: _LanePollEvidence,
    ) -> None:
        cutoff = live_lane.pending_trigger_cutoff
        if cutoff is None:
            return
        evidence.begin(cutoff)
        merged = compile_lane_causal_history_requirements(
            live_lane.lane,
            live_lane.feature_plan,
            self._grid,
        )
        catchup_active = (
            live_lane.startup_catchup_store is not None
            and live_lane.startup_catchup_index < len(live_lane.startup_catchup_cutoffs)
            and cutoff
            == live_lane.startup_catchup_cutoffs[live_lane.startup_catchup_index]
        )
        context_store = (
            live_lane.startup_catchup_store if catchup_active else self._store
        )
        if context_store is None:
            self._halt_lane(
                live_lane,
                "HALTED",
                "startup catch-up context store is unavailable",
            )
            return
        ready, fatal_reason = await self._ensure_context(
            live_lane,
            cutoff,
            merged,
            store=context_store,
        )
        if fatal_reason is not None:
            self._halt_lane(live_lane, "RECONSTRUCTION_REQUIRED", fatal_reason)
            return
        if not ready:
            live_lane.status = "WAITING"
            live_lane.reason = "causal context is not ready"
            return
        view_builder = (
            live_lane.startup_catchup_view_builder
            if catchup_active
            else self._view_builder
        )
        if view_builder is None:
            self._halt_lane(
                live_lane,
                "HALTED",
                "startup catch-up view builder is unavailable",
            )
            return
        try:
            view = view_builder.build(
                live_lane.lane,
                live_lane.market_requirements,
                cutoff,
                input_read_cursor=self._reader.cursor_for(
                    live_lane.market_requirements.trigger_series
                ),
                lane_commit_watermark=live_lane.finalizer.watermark,
            )
        except MarketViewNotReadyError:
            live_lane.status = "WAITING"
            live_lane.reason = "lane market view is not ready"
            return
        except Exception as exc:  # noqa: BLE001
            self._halt_lane(live_lane, "INVALID", f"market view failed: {exc}")
            return
        live_lane.status = "LIVE"
        live_lane.reason = None
        resolver_cutoff = self._now()
        previous_feature_engine = None
        try:
            if catchup_active:
                if live_lane.startup_catchup_feature_engine is None:
                    raise LiveRuntimeHalt(
                        "startup catch-up feature engine is unavailable"
                    )
                previous_feature_engine = live_lane.runtime._feature_engine
                live_lane.runtime._feature_engine = (
                    live_lane.startup_catchup_feature_engine
                )
            prepared = await live_lane.runtime.prepare_live(
                view,
                resolver_knowledge_cutoff=resolver_cutoff,
            )
        except Exception as exc:  # noqa: BLE001
            self._halt_lane(live_lane, "INVALID", f"model preparation failed: {exc}")
            return
        finally:
            if previous_feature_engine is not None:
                live_lane.runtime._feature_engine = previous_feature_engine
        decision_ready_at = self._now()
        try:
            evaluation = self._policy.evaluate(
                live_lane.lane,
                prepared,
                decision_ready_at=decision_ready_at,
            )
        except Exception as exc:  # noqa: BLE001
            reason = f"policy evaluation failed: {exc}"
            abort_error = self._abort_prepared(live_lane, prepared, reason)
            if abort_error is not None:
                reason = f"{reason}; {abort_error}"
            self._halt_lane(live_lane, "INVALID", reason)
            return
        evidence.policy_status = evaluation.status
        if self._observability is not None:
            self._observability.record_lane_evaluation(
                lane_id=live_lane.lane_id,
                outcome=evaluation.status,
            )
        if evaluation.status in {"BLOCKED", "INVALID"}:
            try:
                receipt = live_lane.finalizer.abort_policy_failure(prepared, evaluation)
                evidence.finalization_status = receipt.status
            except Exception as exc:  # noqa: BLE001
                self._halt_lane(live_lane, "INVALID", f"policy abort failed: {exc}")
            else:
                self._halt_lane(
                    live_lane, evaluation.status, evaluation.reason or evaluation.status
                )
            return
        try:
            if live_lane.lane.authority == "shadow":
                if self._shadow_publisher is None:
                    raise LiveRuntimeHalt("shadow lane requires a shadow publisher")
                envelope = build_shadow_envelope(
                    live_lane.lane,
                    prepared,
                    evaluation,
                )
                live_lane.finalizer.preflight_shadow(
                    prepared,
                    evaluation,
                    envelope,
                )
                acknowledgement = await self._shadow_publisher.publish(envelope)
                if not isinstance(acknowledgement, ShadowPublicationAck):
                    raise LiveRuntimeHalt(
                        "shadow publisher returned invalid acknowledgement"
                    )
                evidence.publication_outcome = acknowledgement.outcome
                if self._observability is not None:
                    self._observability.record_publication(
                        lane_id=live_lane.lane_id,
                        outcome=acknowledgement.outcome,
                    )
                receipt = live_lane.finalizer.finalize_shadow(
                    prepared,
                    evaluation,
                    envelope,
                    acknowledgement,
                )
            elif evaluation.status == "NO_SIGNAL":
                receipt = live_lane.finalizer.finalize_no_signal(prepared, evaluation)
            else:
                if self._publisher is None:
                    raise LiveRuntimeHalt("SIGNAL requires a signal publisher")
                envelope = build_signal_envelope(
                    live_lane.lane,
                    prepared,
                    evaluation,
                    view,
                )
                live_lane.finalizer.preflight_signal(
                    prepared,
                    evaluation,
                    envelope,
                    lane_market_view=view,
                )
                acknowledgement = await self._publisher.publish(envelope)
                if not isinstance(acknowledgement, SignalPublicationAck):
                    raise LiveRuntimeHalt("publisher returned invalid acknowledgement")
                evidence.publication_outcome = acknowledgement.outcome
                if self._observability is not None:
                    self._observability.record_publication(
                        lane_id=live_lane.lane_id,
                        outcome=acknowledgement.outcome,
                    )
                receipt = live_lane.finalizer.finalize_signal(
                    prepared,
                    evaluation,
                    envelope,
                    acknowledgement,
                    lane_market_view=view,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            reason = f"live finalization failed: {exc}"
            abort_error = self._abort_prepared(live_lane, prepared, reason)
            if abort_error is not None:
                reason = f"{reason}; {abort_error}"
            self._halt_lane(live_lane, "HALTED", reason)
            return
        evidence.finalization_status = receipt.status
        if receipt.status != "COMMITTED":
            self._halt_lane(
                live_lane,
                "RECONSTRUCTION_REQUIRED",
                receipt.reason or "publication finalization aborted",
            )
            return
        checkpoint_result: str | None = None
        if live_lane.runtime.stateful_binding_ids:
            try:
                checkpoint_result = await self._save_checkpoint(live_lane, receipt)
            except Exception as exc:  # noqa: BLE001
                self._halt_lane(
                    live_lane,
                    "HALTED",
                    f"checkpoint durability failed after committed finalization: {exc}",
                )
                return
            evidence.checkpoint_result = checkpoint_result
            if checkpoint_result not in {"UPDATED", "IDENTICAL"}:
                self._halt_lane(
                    live_lane,
                    "HALTED",
                    f"checkpoint durability returned {checkpoint_result} after commit",
                )
                return
        try:
            progress_result = await self._save_effect_progress(live_lane, receipt)
        except Exception as exc:  # noqa: BLE001
            self._halt_lane(
                live_lane,
                "HALTED",
                f"lane effect progress durability failed after committed finalization: {exc}",
            )
            return
        if progress_result not in {"INSERTED", "UPDATED", "IDENTICAL"}:
            self._halt_lane(
                live_lane,
                "HALTED",
                f"lane effect progress durability returned {progress_result} after commit",
            )
            return
        live_lane.pending_trigger_cutoff = None
        live_lane.reconciliation_attempted = False
        live_lane.status = "LIVE"
        live_lane.reason = None

    async def _save_effect_progress(
        self,
        live_lane: LiveLane,
        receipt: FinalizationReceipt,
    ) -> str:
        cutoff = receipt.watermark.latest_market_as_of
        disposition = receipt.watermark.last_disposition
        if cutoff is None or disposition not in {"shadow", "published", "no_signal"}:
            raise LiveRuntimeHalt("committed finalization has no effect disposition")
        progress = LaneEffectProgress.create(
            identity=live_lane.identity,
            market_as_of=cutoff,
            last_disposition=disposition,
            updated_at=self._now(),
        )
        result = await self._effect_progress.save(progress)
        if isinstance(result, LaneEffectProgressSaveResult):
            return result.value
        if isinstance(result, str):
            return result
        raise LiveRuntimeHalt("lane effect progress repository returned invalid result")

    async def _save_shadow_progress(
        self,
        live_lane: LiveLane,
        receipt: FinalizationReceipt,
    ) -> str:
        """Compatibility wrapper for the historical C4B private seam."""

        if live_lane.lane.authority != "shadow":
            raise LiveRuntimeHalt("shadow progress wrapper requires a shadow lane")
        return await self._save_effect_progress(live_lane, receipt)

    async def _ensure_context(
        self,
        live_lane: LiveLane,
        cutoff: datetime,
        merged_requirements: Mapping[MarketSeriesKey, int],
        *,
        store: BarStore,
    ) -> tuple[bool, str | None]:
        missing = self._missing_history(cutoff, merged_requirements, store)
        if not missing:
            return True, None
        trigger_key = live_lane.market_requirements.trigger_series
        if not live_lane.reconciliation_attempted:
            live_lane.reconciliation_attempted = True
            for key in missing:
                if key == trigger_key:
                    continue
                expected = self._grid.expected_closed_cutoff(key.timeframe, cutoff)
                latest = store.latest_cutoff(key)
                if latest is not None and expected <= latest:
                    return False, f"internal retained gap for {key.timeframe}"
                try:
                    bars = await self._history.fetch_bars(
                        key,
                        start=latest,
                        through=expected,
                        limit=merged_requirements[key],
                    )
                except Exception as exc:  # noqa: BLE001
                    return False, f"canonical context resolution failed: {exc}"
                if not bars:
                    continue
                if not self._append_forward_context(store, key, bars, latest, expected):
                    return False, f"canonical context gap for {key.timeframe}"
            missing = self._missing_history(cutoff, merged_requirements, store)
        if missing:
            return False, None
        return True, None

    def _missing_history(
        self,
        cutoff: datetime,
        requirements: Mapping[MarketSeriesKey, int],
        store: BarStore,
    ) -> tuple[MarketSeriesKey, ...]:
        missing: list[MarketSeriesKey] = []
        for key, count in requirements.items():
            expected = self._grid.expected_closed_cutoff(key.timeframe, cutoff)
            try:
                bars = store.bars_at(key, expected, limit=count)
            except KeyError:
                missing.append(key)
                continue
            if len(bars) < count or not bars or bars[-1].market_as_of != expected:
                missing.append(key)
                continue
            try:
                for bar in bars:
                    validate_canonical_bar_geometry(key, bar, self._grid)
                if any(
                    current.bar_open_at != previous.bar_close_at
                    for previous, current in pairwise(bars)
                ):
                    missing.append(key)
            except (TypeError, ValueError):
                missing.append(key)
        return tuple(missing)

    def _append_forward_context(
        self,
        store: BarStore,
        key: MarketSeriesKey,
        bars: Sequence[Any],
        latest: datetime | None,
        expected: datetime,
    ) -> bool:
        normalized = tuple(bars)
        if not normalized:
            return False
        previous_close = None
        if latest is not None:
            previous = store.latest_at_or_before(key, latest)
            previous_close = None if previous is None else previous.bar_close_at
        for bar in normalized:
            try:
                validate_canonical_bar_geometry(key, bar, self._grid)
            except (TypeError, ValueError):
                return False
            if previous_close is not None and bar.bar_open_at != previous_close:
                return False
            previous_close = bar.bar_close_at
        if normalized[-1].market_as_of != expected:
            return False
        try:
            for bar in normalized:
                store.append(key, bar)
        except Exception:  # noqa: BLE001
            return False
        return True

    async def _save_checkpoint(
        self,
        live_lane: LiveLane,
        receipt: FinalizationReceipt,
    ) -> str:
        if receipt.watermark.latest_market_as_of is None:
            raise LiveRuntimeHalt("committed finalization has no watermark cutoff")
        inception = live_lane.state_inception_at
        if inception is None:
            raise LiveRuntimeHalt("stateful lane has no startup inception cutoff")
        states = {
            binding_id: live_lane.runtime.state_store.get(binding_id).committed_state
            for binding_id in live_lane.runtime.stateful_binding_ids
        }
        checkpoint = LaneStateCheckpoint.create(
            identity=live_lane.runtime.identity,
            market_as_of=receipt.watermark.latest_market_as_of,
            state_inception_at=inception,
            state_by_binding=states,
            updated_at=self._now(),
        )
        result = await self._checkpoints.save(checkpoint)
        if isinstance(result, CheckpointSaveResult):
            return result.value
        return _text(result, "checkpoint save result")

    @staticmethod
    def _abort_prepared(
        live_lane: LiveLane,
        prepared: Any,
        reason: str,
    ) -> str | None:
        """Discard an unresolved proposal without masking the original failure."""

        if live_lane.runtime.pending_state_execution is not prepared:
            return None
        try:
            live_lane.runtime.abort_prepared(prepared, reason)
        except Exception as exc:  # noqa: BLE001 - cleanup is best effort
            return f"prepared-state abort failed: {exc}"
        return None

    def _mark_series_failure(
        self,
        series_key: MarketSeriesKey | None,
        reason: str,
        *,
        observed_target_market_as_of: datetime | None = None,
    ) -> tuple[str, ...]:
        if series_key is None:
            return ()
        affected_relays: tuple[str, ...] = ()
        if self._price_relay is not None:
            affected_relays = self._price_relay.mark_input_failure(
                series_key,
                reason=reason,
                observed_target_market_as_of=observed_target_market_as_of,
            )
        for lane_id in self._lanes_by_series.get(series_key, ()):
            self._halt_lane(
                self._lanes[lane_id],
                "RECONSTRUCTION_REQUIRED",
                reason,
            )
        return affected_relays

    def _refresh_relay_evidence(
        self,
        relay_plan_ids: Sequence[str],
        relay_results: dict[str, PriceRelayResult],
    ) -> None:
        if self._price_relay is None:
            return
        for relay_plan_id in relay_plan_ids:
            relay_results[relay_plan_id] = self._price_relay.result_snapshot(
                relay_plan_id,
                previous=relay_results.get(relay_plan_id),
            )

    @staticmethod
    def _halt_lane(
        live_lane: LiveLane,
        status: Literal["HALTED", "RECONSTRUCTION_REQUIRED", "INVALID", "BLOCKED"],
        reason: str,
    ) -> None:
        live_lane.status = "INVALID" if status in {"INVALID", "BLOCKED"} else status
        live_lane.reason = reason

    def _lane_result(
        self,
        live_lane: LiveLane,
        evidence: _LanePollEvidence,
    ) -> LanePollResult:
        return LanePollResult(
            lane_id=live_lane.lane_id,
            status=live_lane.status,
            trigger_cutoff=evidence.trigger_cutoff,
            policy_status=evidence.policy_status,
            publication_outcome=evidence.publication_outcome,
            finalization_status=evidence.finalization_status,
            checkpoint_result=evidence.checkpoint_result,
            reason=live_lane.reason,
        )

    def _record_input_result(
        self,
        result: InputRecordResult,
        *,
        accepted_at: datetime,
    ) -> None:
        if self._observability is not None:
            self._observability.record_input_result(
                result,
                accepted_at=accepted_at,
            )

    def _now(self) -> datetime:
        value = self._now_fn()
        return require_utc(value, field_name="now_fn result")


__all__ = [
    "DecisionPollResult",
    "LanePollResult",
    "LiveDecisionRuntime",
    "LiveLane",
    "LiveLaneStatus",
    "LiveRuntimeError",
    "LiveRuntimeHalt",
]
