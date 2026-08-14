"""Offline model execution, explicit state transactions, and causal rewarm.

D6 deliberately stops at prepared model outcomes.  Decision policy, publication,
lane watermarks, and infrastructure remain later-phase responsibilities.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Literal

from apps.decision_app.contracts import ResolvedModelBinding
from apps.decision_app.data import (
    BindingDataRequest,
    DataError,
    DataPlan,
    DataRequestError,
    DataResolution,
    DataResolver,
    materialize_data_request,
    validate_data_plan_against_lane,
)
from apps.decision_app.feature_engine import FeatureEngine, FeatureResolution
from apps.decision_app.features import FeaturePlan, validate_feature_plan_against_lane
from apps.decision_app.market_state import TimeframeGrid
from apps.decision_app.planner import ResolvedLanePlan
from apps.decision_app.runtime_plugins import RuntimePluginCatalog
from apps.decision_app.state import (
    BindingRuntimeState,
    LaneExecutionIdentity,
    LaneStateStore,
    PreparedStateTransition,
    StateCommitReceipt,
)
from apps.decision_app.view import LaneMarketView
from libs.contracts.decision import (
    DataMode,
    DataRequirement,
    DecisionContext,
    DecisionModelPlugin,
    ModelArtifact,
    ModelOutcome,
    ModelRequestContext,
    require_utc,
)

BindingExecutionStatus = Literal["EXECUTED", "UNAVAILABLE", "BLOCKED", "INVALID"]


class ModelRuntimeError(ValueError):
    """Base error for D6 runtime construction and execution failures."""


class RuntimeExecutionError(ModelRuntimeError):
    """Raised when a plugin violates the D6 runtime contract."""


class StateTransactionError(ModelRuntimeError):
    """Raised when a prepared state transaction is stale or inconsistent."""


class RewarmError(ModelRuntimeError):
    """Raised when causal reconstruction cannot complete atomically."""


def _require_non_empty(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _normalize_ids(values: Sequence[str], *, field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field_name} must be a sequence of strings")
    normalized = tuple(
        _require_non_empty(value, field_name=field_name) for value in values
    )
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must not contain duplicates")
    return tuple(sorted(normalized))


def _normalize_blockers(values: Sequence[str]) -> tuple[str, ...]:
    return _normalize_ids(values, field_name="state commit blockers")


@dataclass(frozen=True, slots=True, kw_only=True)
class BindingExecutionResult:
    """One binding's deterministic result for one lane/as-of."""

    binding_id: str
    status: BindingExecutionStatus
    outcome: ModelOutcome | None = None
    reason: str | None = None
    blocked_dependency_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_non_empty(self.binding_id, field_name="binding_id")
        if self.status not in {"EXECUTED", "UNAVAILABLE", "BLOCKED", "INVALID"}:
            raise ValueError("binding execution status is not supported")
        if self.status == "EXECUTED":
            if not isinstance(self.outcome, ModelOutcome):
                raise ValueError("EXECUTED result requires a ModelOutcome")
        elif self.outcome is not None:
            raise ValueError("non-executed result must not carry an outcome")
        if self.reason is not None:
            _require_non_empty(self.reason, field_name="execution reason")
        if self.status == "BLOCKED":
            object.__setattr__(
                self,
                "blocked_dependency_ids",
                _normalize_blockers(self.blocked_dependency_ids),
            )
        elif self.blocked_dependency_ids:
            raise ValueError("only BLOCKED results may carry dependency blockers")


@dataclass(frozen=True, slots=True, kw_only=True)
class PreparedLaneExecution:
    """Prepared D6 results awaiting D8 policy/publication authorization."""

    identity: LaneExecutionIdentity
    market_as_of: datetime
    mode: Literal["LIVE"]
    feature_resolution: FeatureResolution
    data_resolution: DataResolution
    binding_results: Mapping[str, BindingExecutionResult]
    stateful_binding_ids: tuple[str, ...]
    prepared_state_transitions: Mapping[str, PreparedStateTransition]
    state_commit_eligible: bool
    state_commit_blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.identity, LaneExecutionIdentity):
            raise TypeError("identity must be LaneExecutionIdentity")
        require_utc(self.market_as_of, field_name="market_as_of")
        if self.mode != "LIVE":
            raise ValueError("PreparedLaneExecution mode must be LIVE")
        if not isinstance(self.feature_resolution, FeatureResolution):
            raise TypeError("feature_resolution must be FeatureResolution")
        if not isinstance(self.data_resolution, DataResolution):
            raise TypeError("data_resolution must be DataResolution")
        if self.feature_resolution.lane_id != self.identity.lane_id:
            raise ValueError("feature resolution lane_id does not match identity")
        if self.feature_resolution.base_lane_revision != (
            self.identity.effective_lane_revision
        ):
            raise ValueError("feature resolution revision does not match identity")
        if self.feature_resolution.feature_plan_fingerprint != (
            self.identity.feature_plan_fingerprint
        ):
            raise ValueError("feature resolution fingerprint does not match identity")
        if self.feature_resolution.market_as_of != self.market_as_of:
            raise ValueError("feature resolution cutoff does not match execution")
        if self.data_resolution.lane_id != self.identity.lane_id:
            raise ValueError("data resolution lane_id does not match identity")
        if self.data_resolution.base_lane_revision != (
            self.identity.effective_lane_revision
        ):
            raise ValueError("data resolution revision does not match identity")
        if self.data_resolution.data_plan_fingerprint != (
            self.identity.data_plan_fingerprint
        ):
            raise ValueError("data resolution fingerprint does not match identity")
        if self.data_resolution.market_as_of != self.market_as_of:
            raise ValueError("data resolution cutoff does not match execution")
        if not isinstance(self.binding_results, Mapping):
            raise TypeError("binding_results must be a mapping")
        results: dict[str, BindingExecutionResult] = {}
        for binding_id, result in self.binding_results.items():
            _require_non_empty(binding_id, field_name="binding result key")
            if not isinstance(result, BindingExecutionResult):
                raise TypeError(
                    "binding_results must contain BindingExecutionResult values"
                )
            if binding_id != result.binding_id:
                raise ValueError("binding result key must match binding_id")
            if result.outcome is not None and result.outcome.artifact.market_as_of != (
                self.market_as_of
            ):
                raise ValueError("binding outcome cutoff does not match execution")
            if result.outcome is not None:
                artifact = result.outcome.artifact
                if artifact.binding_id != binding_id:
                    raise ValueError(
                        "binding outcome artifact binding_id must match result"
                    )
                if artifact.lane_id != self.identity.lane_id:
                    raise ValueError(
                        "binding outcome artifact lane_id must match execution"
                    )
            results[binding_id] = result
        feature_binding_ids = set(self.feature_resolution.bindings)
        data_binding_ids = set(self.data_resolution.bindings)
        if set(results) != feature_binding_ids or set(results) != data_binding_ids:
            raise ValueError(
                "binding_results must exactly match feature and data resolutions"
            )
        stateful_ids = _normalize_ids(
            self.stateful_binding_ids,
            field_name="stateful_binding_ids",
        )
        if not isinstance(self.prepared_state_transitions, Mapping):
            raise TypeError("prepared_state_transitions must be a mapping")
        transitions = dict(self.prepared_state_transitions)
        if not set(transitions) <= set(stateful_ids):
            raise ValueError("prepared transitions must be stateful bindings")
        for binding_id, transition in transitions.items():
            if not isinstance(transition, PreparedStateTransition):
                raise TypeError(
                    "prepared_state_transitions must contain PreparedStateTransition values"
                )
            if binding_id != transition.binding_id:
                raise ValueError("prepared transition key must match binding_id")
            if transition.identity != self.identity:
                raise ValueError("prepared transition identity does not match")
            if transition.market_as_of != self.market_as_of:
                raise ValueError("prepared transition cutoff must match execution")
        if not set(stateful_ids) <= set(results):
            raise ValueError(
                "binding_results must contain every configured stateful binding"
            )
        for binding_id in stateful_ids:
            result = results[binding_id]
            if result.status == "EXECUTED" and binding_id not in transitions:
                raise ValueError(
                    "executed stateful binding must have a prepared transition"
                )
            if result.status != "EXECUTED" and binding_id in transitions:
                raise ValueError(
                    "non-executed stateful binding must not have a transition"
                )
        for binding_id, result in results.items():
            if result.status != "BLOCKED":
                continue
            blocked = set(result.blocked_dependency_ids)
            if not blocked:
                raise ValueError("BLOCKED result must name dependency blockers")
            if binding_id in blocked:
                raise ValueError("BLOCKED result cannot name itself as a blocker")
            if not blocked <= set(results):
                raise ValueError("BLOCKED result contains an unknown dependency")
            if any(
                results[provider_id].status == "EXECUTED" for provider_id in blocked
            ):
                raise ValueError("BLOCKED result cannot name an executed dependency")
        if not isinstance(self.state_commit_eligible, bool):
            raise TypeError("state_commit_eligible must be a bool")
        blockers = _normalize_blockers(self.state_commit_blockers)
        expected_blockers = {
            binding_id
            for binding_id in stateful_ids
            if results[binding_id].status != "EXECUTED"
        }
        if set(blockers) != expected_blockers:
            raise ValueError(
                "state commit blockers must match non-executed stateful bindings"
            )
        expected_eligible = not expected_blockers and set(transitions) == set(
            stateful_ids
        )
        if self.state_commit_eligible != expected_eligible:
            raise ValueError("state_commit_eligible is inconsistent with transitions")
        if self.state_commit_eligible and blockers:
            raise ValueError("eligible state commit must not have blockers")
        object.__setattr__(self, "binding_results", _freeze_result_map(results))
        object.__setattr__(self, "stateful_binding_ids", stateful_ids)
        object.__setattr__(
            self,
            "prepared_state_transitions",
            _freeze_transition_map(transitions),
        )
        object.__setattr__(self, "state_commit_blockers", blockers)


@dataclass(frozen=True, slots=True, kw_only=True)
class RewarmStep:
    """One supplied historical causal view and resolver knowledge cutoff."""

    lane_market_view: LaneMarketView
    resolver_knowledge_cutoff: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.lane_market_view, LaneMarketView):
            raise TypeError("lane_market_view must be a LaneMarketView")
        require_utc(
            self.resolver_knowledge_cutoff,
            field_name="resolver_knowledge_cutoff",
        )
        if self.resolver_knowledge_cutoff < self.lane_market_view.market_as_of:
            raise ValueError(
                "resolver_knowledge_cutoff must be at or after lane market_as_of"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class RewarmResult:
    """Publication-free evidence of a successful causal reconstruction."""

    identity: LaneExecutionIdentity
    starting_market_as_of: datetime | None
    final_market_as_of: datetime
    replay_step_count: int
    reconstructed_binding_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.identity, LaneExecutionIdentity):
            raise TypeError("identity must be LaneExecutionIdentity")
        if self.starting_market_as_of is not None:
            require_utc(
                self.starting_market_as_of,
                field_name="starting_market_as_of",
            )
        require_utc(self.final_market_as_of, field_name="final_market_as_of")
        if isinstance(self.replay_step_count, bool) or not isinstance(
            self.replay_step_count, int
        ):
            raise TypeError("replay_step_count must be an integer")
        if self.replay_step_count <= 0:
            raise ValueError("replay_step_count must be positive")
        object.__setattr__(
            self,
            "reconstructed_binding_ids",
            _normalize_ids(
                self.reconstructed_binding_ids,
                field_name="reconstructed_binding_ids",
            ),
        )


def _freeze_result_map(
    values: Mapping[str, BindingExecutionResult],
) -> Mapping[str, BindingExecutionResult]:
    from libs.contracts.decision import FrozenMapping

    return FrozenMapping(dict(sorted(values.items())))


def _freeze_transition_map(
    values: Mapping[str, PreparedStateTransition],
) -> Mapping[str, PreparedStateTransition]:
    from libs.contracts.decision import FrozenMapping

    return FrozenMapping(dict(sorted(values.items())))


@dataclass(frozen=True, slots=True)
class _RequestPhase:
    requests: tuple[BindingDataRequest, ...]
    unavailable: Mapping[str, str]
    invalid: Mapping[str, str]


class ModelRuntime:
    """Execute one resolved lane without policy, publication, or I/O."""

    def __init__(
        self,
        resolved_lane: ResolvedLanePlan,
        feature_plan: FeaturePlan,
        data_plan: DataPlan,
        feature_engine: FeatureEngine,
        data_resolver: DataResolver,
        runtime_plugin_catalog: RuntimePluginCatalog,
        timeframe_grid: TimeframeGrid,
        state_store: LaneStateStore | None = None,
    ) -> None:
        if not isinstance(resolved_lane, ResolvedLanePlan):
            raise TypeError("resolved_lane must be a ResolvedLanePlan")
        if not isinstance(feature_plan, FeaturePlan):
            raise TypeError("feature_plan must be a FeaturePlan")
        if not isinstance(data_plan, DataPlan):
            raise TypeError("data_plan must be a DataPlan")
        if not isinstance(feature_engine, FeatureEngine):
            raise TypeError("feature_engine must be a FeatureEngine")
        if not isinstance(data_resolver, DataResolver):
            raise TypeError("data_resolver must be a DataResolver")
        if not isinstance(runtime_plugin_catalog, RuntimePluginCatalog):
            raise TypeError("runtime_plugin_catalog must be a RuntimePluginCatalog")
        if not isinstance(timeframe_grid, TimeframeGrid):
            raise TypeError("timeframe_grid must be a TimeframeGrid")
        timeframe_grid.duration(resolved_lane.trigger_timeframe)
        validate_feature_plan_against_lane(feature_plan, resolved_lane)
        validate_data_plan_against_lane(data_plan, resolved_lane)
        identity = LaneExecutionIdentity(
            lane_id=resolved_lane.lane_id,
            effective_lane_revision=resolved_lane.effective_lane_revision,
            feature_plan_fingerprint=feature_plan.feature_plan_fingerprint,
            data_plan_fingerprint=data_plan.data_plan_fingerprint,
        )
        stateful_ids = tuple(
            sorted(
                binding.binding_id
                for binding in resolved_lane.bindings.values()
                if binding.model_spec.stateful
            )
        )
        if state_store is None:
            state_store = LaneStateStore(identity, stateful_ids)
        elif not isinstance(state_store, LaneStateStore):
            raise TypeError("state_store must be a LaneStateStore")
        state_store.assert_identity(identity)
        if state_store.stateful_binding_ids != stateful_ids:
            raise ValueError("state store stateful binding IDs do not match lane")

        plugins: dict[str, DecisionModelPlugin] = {}
        instance_ids: set[int] = set()
        bindings_by_id = {
            binding.binding_id: binding for binding in resolved_lane.bindings.values()
        }
        for binding_id in resolved_lane.execution_order:
            binding = bindings_by_id[binding_id]
            plugin = runtime_plugin_catalog.instantiate(binding)
            if id(plugin) in instance_ids:
                raise ValueError("runtime plugin instance cannot be reused by bindings")
            instance_ids.add(id(plugin))
            if plugin.spec != binding.model_spec:
                raise ValueError("runtime plugin spec must match resolved binding")
            plugins[binding_id] = plugin

        self._lane = resolved_lane
        self._feature_plan = feature_plan
        self._data_plan = data_plan
        self._feature_engine = feature_engine
        self._data_resolver = data_resolver
        self._timeframe_grid = timeframe_grid
        self._plugins = plugins
        self._bindings_by_id = bindings_by_id
        self._identity = identity
        self._state_store = state_store
        self._pending_state_execution: PreparedLaneExecution | None = None

    @property
    def lane(self) -> ResolvedLanePlan:
        return self._lane

    @property
    def identity(self) -> LaneExecutionIdentity:
        return self._identity

    @property
    def state_store(self) -> LaneStateStore:
        return self._state_store

    @property
    def stateful_binding_ids(self) -> tuple[str, ...]:
        return self._state_store.stateful_binding_ids

    @property
    def pending_state_execution(self) -> PreparedLaneExecution | None:
        """The one unresolved LIVE state proposal, if any."""

        return self._pending_state_execution

    async def prepare_live(
        self,
        lane_market_view: LaneMarketView,
        *,
        resolver_knowledge_cutoff: datetime,
    ) -> PreparedLaneExecution:
        """Prepare one LIVE evaluation; never commits proposed state."""

        self._validate_lane_market_view(lane_market_view)
        require_utc(
            resolver_knowledge_cutoff,
            field_name="resolver_knowledge_cutoff",
        )
        if resolver_knowledge_cutoff < lane_market_view.market_as_of:
            raise ValueError(
                "resolver_knowledge_cutoff must be at or after market_as_of"
            )
        if self.stateful_binding_ids:
            if self._pending_state_execution is not None:
                raise StateTransactionError(
                    "stateful prepared execution is pending finalization"
                )
            self._validate_next_live_cutoff(lane_market_view.market_as_of)
        try:
            feature_resolution = self._feature_engine.compute(
                self._feature_plan,
                self._lane,
                lane_market_view,
            )
        except asyncio.CancelledError:
            self._degrade_live_stateful("feature_resolution_cancelled")
            raise
        except Exception:
            self._degrade_live_stateful("feature_resolution_failed")
            raise

        try:
            request_phase = self._request_phase(
                lane_market_view,
                feature_resolution,
                mode="LIVE",
                resolver_knowledge_cutoff=resolver_knowledge_cutoff,
                candidate_binding_ids=set(self._bindings_by_id),
                state_records=self._state_store.records,
            )
            data_resolution = await self._resolve_requests(
                request_phase.requests,
                mode="LIVE",
                market_as_of=lane_market_view.market_as_of,
                resolver_knowledge_cutoff=resolver_knowledge_cutoff,
            )
        except asyncio.CancelledError:
            self._degrade_live_stateful("data_resolution_cancelled")
            raise
        except Exception:
            self._degrade_live_stateful("data_resolution_failed")
            raise

        results, transitions = self._execute_bindings(
            lane_market_view,
            feature_resolution,
            data_resolution,
            request_phase,
            mode="LIVE",
            candidate_binding_ids=set(self._bindings_by_id),
            state_records=self._state_store.records,
        )
        blockers = tuple(
            binding_id
            for binding_id in self.stateful_binding_ids
            if results[binding_id].status != "EXECUTED"
        )
        prepared = PreparedLaneExecution(
            identity=self._identity,
            market_as_of=lane_market_view.market_as_of,
            mode="LIVE",
            feature_resolution=feature_resolution,
            data_resolution=data_resolution,
            binding_results=results,
            stateful_binding_ids=self.stateful_binding_ids,
            prepared_state_transitions=transitions,
            state_commit_eligible=not blockers,
            state_commit_blockers=blockers,
        )
        if prepared.prepared_state_transitions:
            self._pending_state_execution = prepared
        return prepared

    async def prepare(
        self,
        lane_market_view: LaneMarketView,
        *,
        resolver_knowledge_cutoff: datetime,
    ) -> PreparedLaneExecution:
        """Compatibility spelling for the explicit LIVE preparation operation."""

        return await self.prepare_live(
            lane_market_view,
            resolver_knowledge_cutoff=resolver_knowledge_cutoff,
        )

    def commit_prepared(
        self,
        prepared: PreparedLaneExecution,
        disposition: Literal["published", "no_signal"],
    ) -> StateCommitReceipt:
        """Commit only after a future policy/publication boundary authorizes it."""

        if not isinstance(prepared, PreparedLaneExecution):
            raise TypeError("prepared must be PreparedLaneExecution")
        self._validate_prepared_transaction(prepared)
        if not prepared.state_commit_eligible:
            raise StateTransactionError("prepared execution is not commit eligible")
        try:
            receipt = self._state_store.commit(
                self._identity,
                prepared.market_as_of,
                prepared.prepared_state_transitions,
                disposition,
            )
        except (TypeError, ValueError) as exc:
            raise StateTransactionError(str(exc)) from exc
        self._pending_state_execution = None
        return receipt

    def validate_prepared_commit(self, prepared: PreparedLaneExecution) -> None:
        """Expose the pure D6 commit preflight for the D8 finalization boundary."""

        if not isinstance(prepared, PreparedLaneExecution):
            raise TypeError("prepared must be PreparedLaneExecution")
        self._validate_prepared_transaction(prepared)
        if not prepared.state_commit_eligible:
            raise StateTransactionError("prepared execution is not commit eligible")

    def abort_prepared(self, prepared: PreparedLaneExecution, reason: str) -> None:
        """Discard proposals and force transition-bearing stateful bindings to rewarm."""

        if not isinstance(prepared, PreparedLaneExecution):
            raise TypeError("prepared must be PreparedLaneExecution")
        self._validate_prepared_transaction(prepared)
        try:
            self._state_store.abort(
                self._identity,
                prepared.prepared_state_transitions,
                reason,
            )
        except (TypeError, ValueError) as exc:
            raise StateTransactionError(str(exc)) from exc
        if prepared.prepared_state_transitions:
            self._pending_state_execution = None

    async def rewarm(self, steps: Sequence[RewarmStep]) -> RewarmResult:
        """Causally reconstruct state through the same model execution chain."""

        if isinstance(steps, (str, bytes)) or not isinstance(steps, Sequence):
            raise TypeError("steps must be a sequence of RewarmStep values")
        normalized_steps = tuple(steps)
        if any(not isinstance(step, RewarmStep) for step in normalized_steps):
            raise TypeError("steps must contain RewarmStep values")
        if self._pending_state_execution is not None:
            raise RewarmError(
                "cannot rewarm while a prepared state execution is pending"
            )
        if not self.stateful_binding_ids:
            raise RewarmError("rewarm requires at least one stateful binding")
        baseline = self._rewarm_baseline()
        if not normalized_steps:
            raise RewarmError("rewarm requires at least one replay step")
        self._validate_rewarm_steps(normalized_steps, baseline)
        closure = self._stateful_ancestor_closure()
        shadow = {
            binding_id: self._state_store.get(binding_id)
            for binding_id in self.stateful_binding_ids
        }
        starting_cutoff = baseline
        final_cutoff: datetime | None = None
        try:
            for step in normalized_steps:
                view = step.lane_market_view
                feature_resolution = self._feature_engine.compute(
                    self._feature_plan,
                    self._lane,
                    view,
                )
                request_phase = self._request_phase(
                    view,
                    feature_resolution,
                    mode="REPLAY",
                    resolver_knowledge_cutoff=step.resolver_knowledge_cutoff,
                    candidate_binding_ids=closure,
                    state_records=shadow,
                    rewarm=True,
                )
                data_resolution = await self._resolve_requests(
                    request_phase.requests,
                    mode="REPLAY",
                    market_as_of=view.market_as_of,
                    resolver_knowledge_cutoff=step.resolver_knowledge_cutoff,
                )
                results, transitions = self._execute_bindings(
                    view,
                    feature_resolution,
                    data_resolution,
                    request_phase,
                    mode="REPLAY",
                    candidate_binding_ids=closure,
                    state_records=shadow,
                    rewarm=True,
                )
                failed = [
                    binding_id
                    for binding_id in self._ordered_binding_ids(closure)
                    if results[binding_id].status != "EXECUTED"
                ]
                if failed:
                    raise RewarmError(
                        "rewarm step failed for bindings: " + ", ".join(failed)
                    )
                for binding_id in self.stateful_binding_ids:
                    if binding_id not in closure:
                        continue
                    transition = transitions.get(binding_id)
                    if transition is None:
                        raise RewarmError(
                            f"rewarm stateful binding {binding_id} produced no state"
                        )
                    shadow[binding_id] = replace(
                        shadow[binding_id],
                        health="LIVE",
                        committed_market_as_of=view.market_as_of,
                        committed_state=transition.proposed_next_state,
                        last_failure_reason=None,
                    )
                final_cutoff = view.market_as_of
        except asyncio.CancelledError:
            raise
        except RewarmError:
            raise
        except (DataError, RuntimeExecutionError, ValueError) as exc:
            raise RewarmError(f"causal rewarm failed: {exc}") from exc

        if final_cutoff is None:
            raise RewarmError("rewarm produced no final cutoff")
        self._state_store.install_rewarm(self._identity, shadow)
        return RewarmResult(
            identity=self._identity,
            starting_market_as_of=starting_cutoff,
            final_market_as_of=final_cutoff,
            replay_step_count=len(normalized_steps),
            reconstructed_binding_ids=self._ordered_binding_ids(closure),
        )

    def _request_phase(
        self,
        lane_market_view: LaneMarketView,
        feature_resolution: FeatureResolution,
        *,
        mode: DataMode,
        resolver_knowledge_cutoff: datetime,
        candidate_binding_ids: set[str],
        state_records: Mapping[str, BindingRuntimeState],
        rewarm: bool = False,
    ) -> _RequestPhase:
        requests: list[BindingDataRequest] = []
        unavailable: dict[str, str] = {}
        invalid: dict[str, str] = {}
        for binding_id in self._ordered_binding_ids(candidate_binding_ids):
            binding = self._bindings_by_id[binding_id]
            feature_binding = feature_resolution.bindings.get(binding_id)
            if feature_binding is None:
                invalid[binding_id] = "missing_feature_resolution"
                if not rewarm:
                    self._mark_invalid_if_stateful(binding, invalid[binding_id])
                continue
            if not feature_binding.available:
                unavailable[binding_id] = "required_feature_unavailable"
                if not rewarm:
                    self._mark_degraded_if_initialized(binding, unavailable[binding_id])
                continue
            state_record = state_records.get(binding_id)
            if (
                binding.model_spec.stateful
                and not rewarm
                and (state_record is None or state_record.health != "LIVE")
            ):
                unavailable[binding_id] = "state_rewarm_required"
                continue
            state_snapshot = (
                state_record.committed_state
                if binding.model_spec.stateful and state_record is not None
                else None
            )
            context = self._request_context(
                binding,
                lane_market_view,
                feature_binding.features,
                mode=mode,
                upstream_artifacts={},
            )
            try:
                dynamic = self._validate_dynamic_requirements(
                    self._plugins[binding_id].data_requests(
                        context,
                        state_snapshot,
                    ),
                    binding,
                )
            except Exception:  # noqa: BLE001 - plugin contract boundary
                invalid[binding_id] = "data_requests_invalid"
                if not rewarm:
                    self._mark_invalid_if_stateful(binding, invalid[binding_id])
                continue
            for requirement in dynamic:
                route = self._data_plan.routes.get(requirement.concept)
                if route is None:
                    if requirement.required:
                        unavailable[binding_id] = "required_data_unrouted"
                        if not rewarm:
                            self._mark_degraded_if_initialized(
                                binding,
                                unavailable[binding_id],
                            )
                    continue
                try:
                    request = materialize_data_request(
                        resolved_lane=self._lane,
                        resolved_binding=binding,
                        data_plan=self._data_plan,
                        dynamic_requirement=requirement,
                        mode=mode,
                        market_as_of=lane_market_view.market_as_of,
                        resolver_knowledge_cutoff=resolver_knowledge_cutoff,
                    )
                except DataRequestError:
                    invalid[binding_id] = "dynamic_data_request_invalid"
                    if not rewarm:
                        self._mark_invalid_if_stateful(binding, invalid[binding_id])
                    break
                requests.append(
                    BindingDataRequest(binding_id=binding_id, request=request)
                )
        return _RequestPhase(
            requests=tuple(requests),
            unavailable=unavailable,
            invalid=invalid,
        )

    async def _resolve_requests(
        self,
        requests: Sequence[BindingDataRequest],
        *,
        mode: DataMode,
        market_as_of: datetime,
        resolver_knowledge_cutoff: datetime,
    ) -> DataResolution:
        return await self._data_resolver.resolve(
            self._data_plan,
            self._lane,
            requests,
            mode=mode,
            market_as_of=market_as_of,
            resolver_knowledge_cutoff=resolver_knowledge_cutoff,
        )

    def _execute_bindings(
        self,
        lane_market_view: LaneMarketView,
        feature_resolution: FeatureResolution,
        data_resolution: DataResolution,
        request_phase: _RequestPhase,
        *,
        mode: DataMode,
        candidate_binding_ids: set[str],
        state_records: Mapping[str, BindingRuntimeState],
        rewarm: bool = False,
    ) -> tuple[dict[str, BindingExecutionResult], dict[str, PreparedStateTransition]]:
        results: dict[str, BindingExecutionResult] = {}
        transitions: dict[str, PreparedStateTransition] = {}
        for binding_id in self._ordered_binding_ids(candidate_binding_ids):
            binding = self._bindings_by_id[binding_id]
            if binding_id in request_phase.invalid:
                results[binding_id] = BindingExecutionResult(
                    binding_id=binding_id,
                    status="INVALID",
                    reason=request_phase.invalid[binding_id],
                )
                continue
            if binding_id in request_phase.unavailable:
                results[binding_id] = BindingExecutionResult(
                    binding_id=binding_id,
                    status="UNAVAILABLE",
                    reason=request_phase.unavailable[binding_id],
                )
                continue
            data_binding = data_resolution.bindings.get(binding_id)
            if data_binding is None or not data_binding.available:
                reason = "required_data_unavailable"
                results[binding_id] = BindingExecutionResult(
                    binding_id=binding_id,
                    status="UNAVAILABLE",
                    reason=reason,
                )
                if not rewarm:
                    self._mark_degraded_if_initialized(binding, reason)
                continue
            blocked = tuple(
                provider_id
                for provider_id in binding.dependencies.values()
                if provider_id not in results
                or results[provider_id].status != "EXECUTED"
            )
            if blocked:
                results[binding_id] = BindingExecutionResult(
                    binding_id=binding_id,
                    status="BLOCKED",
                    reason="dependency_unavailable",
                    blocked_dependency_ids=blocked,
                )
                if not rewarm:
                    self._mark_degraded_if_initialized(
                        binding, "dependency_unavailable"
                    )
                continue
            upstream = {
                dependency_slot: results[provider_id].outcome.artifact
                for dependency_slot, provider_id in binding.dependencies.items()
            }
            feature_binding = feature_resolution.bindings[binding_id]
            state_record = state_records.get(binding_id)
            state_snapshot = (
                state_record.committed_state
                if binding.model_spec.stateful and state_record is not None
                else None
            )
            context = self._decision_context(
                binding,
                lane_market_view,
                feature_binding.features,
                data_binding.snapshots,
                upstream,
                mode=mode,
            )
            try:
                outcome = self._plugins[binding_id].evaluate(
                    context,
                    state_snapshot,
                )
                self._validate_outcome(binding, lane_market_view, outcome)
            except Exception:  # noqa: BLE001 - plugin contract boundary
                results[binding_id] = BindingExecutionResult(
                    binding_id=binding_id,
                    status="INVALID",
                    reason="evaluate_invalid",
                )
                if not rewarm:
                    self._mark_invalid_if_stateful(binding, "evaluate_invalid")
                continue
            results[binding_id] = BindingExecutionResult(
                binding_id=binding_id,
                status="EXECUTED",
                outcome=outcome,
            )
            if binding.model_spec.stateful:
                if state_record is None:
                    raise RuntimeExecutionError(
                        f"stateful binding {binding_id} has no state record"
                    )
                transitions[binding_id] = PreparedStateTransition(
                    identity=self._identity,
                    binding_id=binding_id,
                    market_as_of=lane_market_view.market_as_of,
                    base_state_record=state_record,
                    proposed_next_state=outcome.proposed_next_state,
                )
        return results, transitions

    @staticmethod
    def _validate_dynamic_requirements(
        returned: object,
        binding: ResolvedModelBinding,
    ) -> tuple[DataRequirement, ...]:
        if isinstance(returned, (str, bytes)) or not isinstance(returned, Sequence):
            raise RuntimeExecutionError(
                f"binding {binding.slot_name} data_requests must return a sequence"
            )
        declared = {
            requirement.concept: requirement
            for requirement in binding.effective_data_requirements
        }
        seen: set[str] = set()
        normalized: list[DataRequirement] = []
        for requirement in returned:
            if not isinstance(requirement, DataRequirement):
                raise RuntimeExecutionError(
                    f"binding {binding.slot_name} returned a non-DataRequirement"
                )
            if requirement.concept in seen:
                raise RuntimeExecutionError(
                    f"binding {binding.slot_name} returned duplicate data concept"
                )
            seen.add(requirement.concept)
            if declared.get(requirement.concept) != requirement:
                raise RuntimeExecutionError(
                    f"binding {binding.slot_name} returned undeclared or drifted "
                    f"data concept {requirement.concept}"
                )
            normalized.append(requirement)
        return tuple(normalized)

    def _request_context(
        self,
        binding: ResolvedModelBinding,
        view: LaneMarketView,
        features: Mapping[str, Any],
        *,
        mode: DataMode,
        upstream_artifacts: Mapping[str, ModelArtifact],
    ) -> ModelRequestContext:
        return ModelRequestContext(
            asset=self._lane.asset,
            venue=self._lane.venue,
            instrument_id=self._lane.instrument_id,
            lane_id=self._lane.lane_id,
            binding_id=binding.binding_id,
            market_as_of=view.market_as_of,
            trigger_timeframe=self._lane.trigger_timeframe,
            decision_timeframe=self._lane.decision_timeframe,
            trigger_mode=self._lane.trigger_mode,
            decision_bar=view.decision_bar,
            decision_bar_closed=view.decision_bar_closed,
            causal_bar_views=view.causal_bar_views,
            shared_features=features,
            upstream_artifacts=upstream_artifacts,
            provenance=self._provenance(mode),
        )

    def _decision_context(
        self,
        binding: ResolvedModelBinding,
        view: LaneMarketView,
        features: Mapping[str, Any],
        external_data: Mapping[str, Any],
        upstream_artifacts: Mapping[str, ModelArtifact],
        *,
        mode: DataMode,
    ) -> DecisionContext:
        return DecisionContext(
            asset=self._lane.asset,
            venue=self._lane.venue,
            instrument_id=self._lane.instrument_id,
            lane_id=self._lane.lane_id,
            binding_id=binding.binding_id,
            market_as_of=view.market_as_of,
            trigger_timeframe=self._lane.trigger_timeframe,
            decision_timeframe=self._lane.decision_timeframe,
            trigger_mode=self._lane.trigger_mode,
            decision_bar=view.decision_bar,
            decision_bar_closed=view.decision_bar_closed,
            causal_bar_views=view.causal_bar_views,
            shared_features=features,
            external_data=external_data,
            upstream_artifacts=upstream_artifacts,
            provenance=self._provenance(mode),
        )

    def _provenance(self, mode: DataMode) -> Mapping[str, str]:
        return {
            "lane_id": self._identity.lane_id,
            "effective_lane_revision": self._identity.effective_lane_revision,
            "feature_plan_fingerprint": self._identity.feature_plan_fingerprint,
            "data_plan_fingerprint": self._identity.data_plan_fingerprint,
            "mode": mode,
        }

    def _validate_outcome(
        self,
        binding: ResolvedModelBinding,
        view: LaneMarketView,
        outcome: object,
    ) -> None:
        if not isinstance(outcome, ModelOutcome):
            raise RuntimeExecutionError("plugin evaluate must return ModelOutcome")
        artifact = outcome.artifact
        if artifact.binding_id != binding.binding_id:
            raise RuntimeExecutionError("artifact binding_id does not match binding")
        if artifact.lane_id != self._lane.lane_id:
            raise RuntimeExecutionError("artifact lane_id does not match lane")
        if artifact.asset != self._lane.asset:
            raise RuntimeExecutionError("artifact asset does not match lane")
        if artifact.decision_timeframe != self._lane.decision_timeframe:
            raise RuntimeExecutionError(
                "artifact decision timeframe does not match lane"
            )
        if artifact.trigger_timeframe != self._lane.trigger_timeframe:
            raise RuntimeExecutionError(
                "artifact trigger timeframe does not match lane"
            )
        if artifact.market_as_of != view.market_as_of:
            raise RuntimeExecutionError("artifact market_as_of does not match view")
        if artifact.artifact_type != binding.model_spec.produces_artifact_type:
            raise RuntimeExecutionError("artifact_type does not match model spec")
        if (
            binding.model_spec.output_kind == "analytical"
            and outcome.decision is not None
        ):
            raise RuntimeExecutionError("analytical model cannot emit a decision")
        if not binding.model_spec.stateful and outcome.proposed_next_state is not None:
            raise RuntimeExecutionError("stateless model cannot propose state")

    def _validate_lane_market_view(self, view: LaneMarketView) -> None:
        if not isinstance(view, LaneMarketView):
            raise TypeError("lane_market_view must be a LaneMarketView")
        for field_name in (
            "lane_id",
            "asset",
            "venue",
            "instrument_id",
            "decision_timeframe",
            "trigger_timeframe",
            "trigger_mode",
        ):
            if getattr(view, field_name) != getattr(self._lane, field_name):
                raise ValueError(f"lane market view {field_name} must match lane")

    def _ordered_binding_ids(self, binding_ids: set[str]) -> tuple[str, ...]:
        return tuple(
            binding_id
            for binding_id in self._lane.execution_order
            if binding_id in binding_ids
        )

    def _stateful_ancestor_closure(self) -> set[str]:
        closure = set(self.stateful_binding_ids)
        pending = list(closure)
        while pending:
            binding_id = pending.pop()
            for provider_id in self._bindings_by_id[binding_id].dependencies.values():
                if provider_id not in closure:
                    closure.add(provider_id)
                    pending.append(provider_id)
        return closure

    def _rewarm_baseline(self) -> datetime | None:
        cutoffs = {
            self._state_store.get(binding_id).committed_market_as_of
            for binding_id in self.stateful_binding_ids
        }
        initialized = {cutoff for cutoff in cutoffs if cutoff is not None}
        if initialized and len(initialized) != 1:
            raise RewarmError("stateful binding committed cutoffs are inconsistent")
        if initialized and None in cutoffs:
            raise RewarmError("stateful binding committed cutoffs are inconsistent")
        return next(iter(initialized)) if initialized else None

    def _live_stateful_baseline(self) -> datetime | None:
        cutoffs = {
            self._state_store.get(binding_id).committed_market_as_of
            for binding_id in self.stateful_binding_ids
        }
        initialized = {cutoff for cutoff in cutoffs if cutoff is not None}
        if initialized and (len(initialized) != 1 or None in cutoffs):
            raise StateTransactionError(
                "stateful binding committed cutoffs are inconsistent"
            )
        return next(iter(initialized)) if initialized else None

    def _validate_next_live_cutoff(self, market_as_of: datetime) -> None:
        baseline = self._live_stateful_baseline()
        if baseline is None:
            return
        try:
            trigger_duration = self._timeframe_grid.duration(
                self._lane.trigger_timeframe
            )
        except (TypeError, ValueError) as exc:
            raise StateTransactionError(
                "stateful LIVE trigger timeframe has no approved grid geometry"
            ) from exc
        expected = baseline + trigger_duration
        if market_as_of != expected:
            raise StateTransactionError(
                "stateful LIVE evaluation cutoff must equal the next trigger "
                f"cutoff {expected.isoformat()}"
            )

    def _validate_prepared_transaction(
        self,
        prepared: PreparedLaneExecution,
    ) -> None:
        if prepared.identity != self._identity:
            raise StateTransactionError("prepared execution identity does not match")
        if prepared.stateful_binding_ids != self.stateful_binding_ids:
            raise StateTransactionError(
                "prepared stateful binding IDs do not match runtime"
            )
        if prepared.mode != "LIVE":
            raise StateTransactionError("prepared execution mode must be LIVE")
        if prepared.prepared_state_transitions:
            if self._pending_state_execution is not prepared:
                raise StateTransactionError(
                    "prepared execution is not the current pending state execution"
                )
            self._validate_next_live_cutoff(prepared.market_as_of)

    def _validate_rewarm_steps(
        self,
        steps: Sequence[RewarmStep],
        baseline: datetime | None,
    ) -> None:
        trigger_duration = self._trigger_duration(steps[0].lane_market_view)
        previous: datetime | None = baseline
        for index, step in enumerate(steps):
            view = step.lane_market_view
            self._validate_lane_market_view(view)
            cutoff = view.market_as_of
            if previous is not None:
                expected = previous + trigger_duration
                if cutoff != expected:
                    if index == 0 and baseline is not None:
                        raise RewarmError(
                            "first rewarm step must be exactly after committed cutoff"
                        )
                    raise RewarmError(
                        "rewarm steps must be contiguous trigger intervals"
                    )
            previous = cutoff

    def _trigger_duration(self, view: LaneMarketView) -> timedelta:
        try:
            return self._timeframe_grid.duration(view.trigger_timeframe)
        except (TypeError, ValueError) as exc:
            raise RewarmError(
                "rewarm lane trigger timeframe has no approved grid geometry"
            ) from exc

    def _degrade_live_stateful(self, reason: str) -> None:
        for binding_id in self.stateful_binding_ids:
            record = self._state_store.get(binding_id)
            if record.health in {"LIVE", "DEGRADED"}:
                self._state_store.mark_health(binding_id, "DEGRADED", reason=reason)

    def _mark_degraded_if_initialized(
        self,
        binding: ResolvedModelBinding,
        reason: str,
    ) -> None:
        if not binding.model_spec.stateful:
            return
        record = self._state_store.get(binding.binding_id)
        if record.health == "LIVE":
            self._state_store.mark_health(
                binding.binding_id,
                "DEGRADED",
                reason=reason,
            )

    def _mark_invalid_if_stateful(
        self,
        binding: ResolvedModelBinding,
        reason: str,
    ) -> None:
        if binding.model_spec.stateful:
            self._state_store.mark_health(
                binding.binding_id,
                "INVALID",
                reason=reason,
            )


__all__ = [
    "BindingExecutionResult",
    "BindingExecutionStatus",
    "ModelRuntime",
    "ModelRuntimeError",
    "PreparedLaneExecution",
    "RewarmError",
    "RewarmResult",
    "RewarmStep",
    "RuntimeExecutionError",
    "StateTransactionError",
]
