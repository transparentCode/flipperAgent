"""Deterministic, runtime-free composition planning for decision_app D2."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from heapq import heappop, heappush
from typing import Any

from apps.decision_app.domain.contracts import (
    PublicationAuthority,
    ResolvedModelBinding,
)
from apps.decision_app.domain.identity import (
    binding_config_fingerprint,
    effective_lane_revision,
    make_binding_id,
)
from apps.decision_app.planning.catalog import CatalogError, PluginCatalog
from libs.contracts.decision import (
    FrozenMapping,
    ModelSpec,
    deep_freeze,
)


class PlannerError(ValueError):
    """Raised when static model composition cannot be resolved safely."""


def _require_non_empty(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _freeze_semantic_mapping(
    value: Mapping[str, Any], *, field_name: str
) -> FrozenMapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} keys must be strings")
    frozen = deep_freeze(value)
    if not isinstance(frozen, FrozenMapping):
        raise TypeError(f"{field_name} must be a mapping")
    return frozen


def _freeze_string_mapping(
    value: Mapping[str, str], *, field_name: str
) -> FrozenMapping[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    normalized: dict[str, str] = {}
    for key, item in value.items():
        _require_non_empty(key, field_name=f"{field_name} key")
        normalized[key] = _require_non_empty(item, field_name=f"{field_name}[{key}]")
    return FrozenMapping(dict(sorted(normalized.items())))


def _normalize_specs(
    values: Sequence[ModelBindingSpec], *, field_name: str
) -> tuple[ModelBindingSpec, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field_name} must be a sequence")
    normalized = tuple(values)
    if any(not isinstance(value, ModelBindingSpec) for value in normalized):
        raise TypeError(f"{field_name} must contain ModelBindingSpec values")
    return normalized


@dataclass(frozen=True, slots=True, kw_only=True)
class ModelBindingSpec:
    """Configuration-owned wiring for one named model binding."""

    slot_name: str
    plugin_name: str
    plugin_version: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    dependencies: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.slot_name, field_name="slot_name")
        _require_non_empty(self.plugin_name, field_name="plugin_name")
        _require_non_empty(self.plugin_version, field_name="plugin_version")
        object.__setattr__(
            self,
            "parameters",
            _freeze_semantic_mapping(self.parameters, field_name="parameters"),
        )
        object.__setattr__(
            self,
            "dependencies",
            _freeze_string_mapping(self.dependencies, field_name="dependencies"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionLaneSpec:
    """Configuration-owned static identity and binding topology for one lane."""

    lane_id: str
    asset: str
    venue: str
    instrument_id: str
    decision_timeframe: str
    trigger_timeframe: str
    trigger_mode: str
    policy_name: str
    policy_version: str
    bindings: Sequence[ModelBindingSpec]
    authority: PublicationAuthority = "authoritative"
    risk_profile_key: str | None = None
    policy_parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "lane_id",
            "asset",
            "venue",
            "instrument_id",
            "decision_timeframe",
            "trigger_timeframe",
            "trigger_mode",
            "policy_name",
            "policy_version",
        ):
            _require_non_empty(getattr(self, field_name), field_name=field_name)
        if self.authority not in {"authoritative", "shadow"}:
            raise ValueError("authority must be authoritative or shadow")
        if self.risk_profile_key is not None:
            _require_non_empty(self.risk_profile_key, field_name="risk_profile_key")
        elif self.authority == "authoritative":
            raise ValueError("authoritative lanes require risk_profile_key")

        normalized_bindings = _normalize_specs(self.bindings, field_name="bindings")
        if not normalized_bindings:
            raise ValueError("lane must contain at least one binding")
        slots = [binding.slot_name for binding in normalized_bindings]
        if len(set(slots)) != len(slots):
            raise ValueError("binding slot names must be unique within a lane")
        object.__setattr__(self, "bindings", normalized_bindings)
        object.__setattr__(
            self,
            "policy_parameters",
            _freeze_semantic_mapping(
                self.policy_parameters,
                field_name="policy_parameters",
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedLanePlan:
    """Immutable resolved data for one lane; no runtime objects are present."""

    lane_id: str
    asset: str
    venue: str
    instrument_id: str
    decision_timeframe: str
    trigger_timeframe: str
    trigger_mode: str
    authority: PublicationAuthority
    risk_profile_key: str | None
    policy_name: str
    policy_version: str
    policy_parameters: FrozenMapping[str, Any]
    effective_lane_revision: str
    bindings: Mapping[str, ResolvedModelBinding]
    execution_order: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_non_empty(self.lane_id, field_name="lane_id")
        _require_non_empty(
            self.effective_lane_revision,
            field_name="effective_lane_revision",
        )
        if self.authority not in {"authoritative", "shadow"}:
            raise ValueError("authority must be authoritative or shadow")
        if self.risk_profile_key is not None:
            _require_non_empty(self.risk_profile_key, field_name="risk_profile_key")
        elif self.authority == "authoritative":
            raise ValueError("authoritative lanes require risk_profile_key")
        object.__setattr__(
            self,
            "policy_parameters",
            _freeze_semantic_mapping(
                self.policy_parameters,
                field_name="policy_parameters",
            ),
        )
        if not isinstance(self.bindings, Mapping):
            raise TypeError("bindings must be a mapping")
        normalized: dict[str, ResolvedModelBinding] = {}
        for slot_name, binding in self.bindings.items():
            _require_non_empty(slot_name, field_name="binding slot")
            if not isinstance(binding, ResolvedModelBinding):
                raise TypeError("bindings must contain ResolvedModelBinding values")
            if slot_name != binding.slot_name:
                raise ValueError(
                    f"binding map key {slot_name} must match binding slot "
                    f"{binding.slot_name}"
                )
            if binding.lane_id != self.lane_id:
                raise ValueError(
                    f"binding {slot_name} lane_id must match resolved lane"
                )
            if binding.effective_lane_revision != self.effective_lane_revision:
                raise ValueError(
                    f"binding {slot_name} effective_lane_revision must match "
                    "resolved lane"
                )
            if binding.decision_timeframe != self.decision_timeframe:
                raise ValueError(
                    f"binding {slot_name} decision_timeframe must match resolved lane"
                )
            if binding.trigger_timeframe != self.trigger_timeframe:
                raise ValueError(
                    f"binding {slot_name} trigger_timeframe must match resolved lane"
                )
            if binding.trigger_mode != self.trigger_mode:
                raise ValueError(
                    f"binding {slot_name} trigger_mode must match resolved lane"
                )
            if binding.publication_authority != self.authority:
                raise ValueError(
                    f"binding {slot_name} publication_authority must match resolved lane"
                )
            if binding.risk_profile_key != self.risk_profile_key:
                raise ValueError(
                    f"binding {slot_name} risk_profile_key must match resolved lane"
                )
            normalized[slot_name] = binding
        if not normalized:
            raise ValueError("resolved lane must contain at least one binding")
        order = tuple(self.execution_order)
        if any(not isinstance(binding_id, str) for binding_id in order):
            raise TypeError("execution_order must contain binding IDs")
        binding_ids = {binding.binding_id for binding in normalized.values()}
        if len(order) != len(normalized):
            raise ValueError("execution_order must contain each binding exactly once")
        if len(set(order)) != len(order):
            raise ValueError("execution_order must not contain duplicate binding IDs")
        if set(order) != binding_ids:
            raise ValueError("execution_order must contain each resolved binding once")
        positions = {binding_id: index for index, binding_id in enumerate(order)}
        for slot_name, binding in normalized.items():
            consumer_position = positions[binding.binding_id]
            for dependency_slot, provider_id in binding.dependencies.items():
                if provider_id not in positions:
                    raise ValueError(
                        f"binding {slot_name} dependency {dependency_slot} "
                        f"references foreign binding ID {provider_id}"
                    )
                if positions[provider_id] >= consumer_position:
                    raise ValueError(
                        f"execution_order places dependency {provider_id} "
                        f"after consumer {binding.binding_id}"
                    )
        object.__setattr__(
            self,
            "bindings",
            FrozenMapping(dict(sorted(normalized.items()))),
        )
        object.__setattr__(self, "execution_order", order)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedDecisionPlan:
    """Immutable deterministic plan for all configured lanes."""

    lanes: tuple[ResolvedLanePlan, ...]
    authoritative_routes: Mapping[tuple[str, str], str]

    def __post_init__(self) -> None:
        lanes = tuple(self.lanes)
        if any(not isinstance(lane, ResolvedLanePlan) for lane in lanes):
            raise TypeError("lanes must contain ResolvedLanePlan values")
        lane_ids = [lane.lane_id for lane in lanes]
        if len(set(lane_ids)) != len(lane_ids):
            raise ValueError("resolved decision plan lane IDs must be unique")
        if tuple(lane.lane_id for lane in lanes) != tuple(
            sorted(lane.lane_id for lane in lanes)
        ):
            raise ValueError("lanes must be deterministically ordered")
        expected_routes: dict[tuple[str, str], str] = {}
        for lane in lanes:
            if lane.authority != "authoritative":
                continue
            route = (lane.asset, lane.decision_timeframe)
            if route in expected_routes:
                raise ValueError(
                    "resolved decision plan has multiple authoritative lanes "
                    f"for route {route}"
                )
            expected_routes[route] = lane.lane_id
        if not isinstance(self.authoritative_routes, Mapping):
            raise TypeError("authoritative_routes must be a mapping")
        routes = dict(self.authoritative_routes)
        if any(
            not isinstance(key, tuple)
            or len(key) != 2
            or any(not isinstance(part, str) for part in key)
            or not isinstance(value, str)
            for key, value in routes.items()
        ):
            raise TypeError("authoritative_routes must map string pairs to lane IDs")
        if routes != expected_routes:
            raise ValueError(
                "authoritative_routes must exactly match authoritative lanes"
            )
        object.__setattr__(self, "lanes", lanes)
        object.__setattr__(
            self,
            "authoritative_routes",
            FrozenMapping(dict(sorted(routes.items()))),
        )


class StaticCompositionPlanner:
    """Compile explicit specs into a deterministic static decision plan."""

    def __init__(self, catalog: PluginCatalog) -> None:
        if not isinstance(catalog, PluginCatalog):
            raise TypeError("catalog must be a PluginCatalog")
        self._catalog = catalog

    def compile(self, lane_specs: Iterable[DecisionLaneSpec]) -> ResolvedDecisionPlan:
        lanes = tuple(lane_specs)
        if any(not isinstance(lane, DecisionLaneSpec) for lane in lanes):
            raise TypeError("lane_specs must contain DecisionLaneSpec values")
        lane_ids = [lane.lane_id for lane in lanes]
        if len(set(lane_ids)) != len(lane_ids):
            raise PlannerError("duplicate lane_id in decision plan")

        resolved_lanes = tuple(self._compile_lane(lane) for lane in lanes)
        resolved_lanes = tuple(sorted(resolved_lanes, key=lambda lane: lane.lane_id))

        routes: dict[tuple[str, str], str] = {}
        for lane in resolved_lanes:
            if lane.authority != "authoritative":
                continue
            route = (lane.asset, lane.decision_timeframe)
            previous = routes.get(route)
            if previous is not None:
                raise PlannerError(
                    "multiple authoritative lanes for route "
                    f"{route}: {previous}, {lane.lane_id}"
                )
            routes[route] = lane.lane_id

        return ResolvedDecisionPlan(
            lanes=resolved_lanes,
            authoritative_routes=routes,
        )

    def _compile_lane(self, lane: DecisionLaneSpec) -> ResolvedLanePlan:
        ordered_bindings = tuple(sorted(lane.bindings, key=lambda item: item.slot_name))
        resolved_specs: dict[str, ModelSpec] = {}
        binding_fingerprints: dict[str, str] = {}
        binding_ids: dict[str, str] = {}

        for binding in ordered_bindings:
            try:
                spec = self._catalog.resolve(
                    binding.plugin_name,
                    binding.plugin_version,
                )
            except CatalogError as exc:
                raise PlannerError(str(exc)) from exc
            self._validate_capabilities(lane, binding, spec)
            resolved_specs[binding.slot_name] = spec
            runtime_binding = {
                "lane_id": lane.lane_id,
                "asset": lane.asset,
                "venue": lane.venue,
                "instrument_id": lane.instrument_id,
                "slot_name": binding.slot_name,
                "trigger_timeframe": lane.trigger_timeframe,
                "decision_timeframe": lane.decision_timeframe,
                "trigger_mode": lane.trigger_mode,
                "plugin_name": binding.plugin_name,
                "plugin_version": binding.plugin_version,
                "dependencies": dict(sorted(binding.dependencies.items())),
            }
            fingerprint = binding_config_fingerprint(
                binding.parameters,
                runtime_binding,
            )
            binding_fingerprints[binding.slot_name] = fingerprint
            binding_ids[binding.slot_name] = make_binding_id(
                lane_id=lane.lane_id,
                slot_name=binding.slot_name,
                plugin_name=binding.plugin_name,
                plugin_version=binding.plugin_version,
                binding_fingerprint=fingerprint,
            )

        dependencies = self._resolve_dependencies(
            ordered_bindings,
            resolved_specs,
            binding_ids,
        )
        self._validate_stateful_replay_closure(
            ordered_bindings,
            resolved_specs,
        )
        execution_order = self._topological_order(ordered_bindings)
        lane_revision = effective_lane_revision(
            lane.lane_id,
            {
                "asset": lane.asset,
                "venue": lane.venue,
                "instrument_id": lane.instrument_id,
                "decision_timeframe": lane.decision_timeframe,
                "trigger_timeframe": lane.trigger_timeframe,
                "trigger_mode": lane.trigger_mode,
                "authority": lane.authority,
                "risk_profile_key": lane.risk_profile_key,
                "bindings": [
                    {
                        "slot_name": binding.slot_name,
                        "binding_id": binding_ids[binding.slot_name],
                        "binding_config_fingerprint": binding_fingerprints[
                            binding.slot_name
                        ],
                        "dependencies": dict(sorted(binding.dependencies.items())),
                    }
                    for binding in ordered_bindings
                ],
            },
            {
                "name": lane.policy_name,
                "version": lane.policy_version,
                "parameters": lane.policy_parameters,
            },
        )

        resolved_bindings = {
            binding.slot_name: ResolvedModelBinding(
                lane_id=lane.lane_id,
                slot_name=binding.slot_name,
                plugin_name=binding.plugin_name,
                plugin_version=binding.plugin_version,
                model_spec=resolved_specs[binding.slot_name],
                binding_config_fingerprint=binding_fingerprints[binding.slot_name],
                binding_id=binding_ids[binding.slot_name],
                effective_lane_revision=lane_revision,
                parameters=binding.parameters,
                trigger_timeframe=lane.trigger_timeframe,
                decision_timeframe=lane.decision_timeframe,
                trigger_mode=lane.trigger_mode,
                dependencies=dependencies[binding.slot_name],
                effective_feature_requirements=resolved_specs[
                    binding.slot_name
                ].intrinsic_feature_requirements,
                effective_data_requirements=resolved_specs[
                    binding.slot_name
                ].intrinsic_data_requirements,
                risk_profile_key=lane.risk_profile_key,
                publication_authority=lane.authority,
            )
            for binding in ordered_bindings
        }

        return ResolvedLanePlan(
            lane_id=lane.lane_id,
            asset=lane.asset,
            venue=lane.venue,
            instrument_id=lane.instrument_id,
            decision_timeframe=lane.decision_timeframe,
            trigger_timeframe=lane.trigger_timeframe,
            trigger_mode=lane.trigger_mode,
            authority=lane.authority,
            risk_profile_key=lane.risk_profile_key,
            policy_name=lane.policy_name,
            policy_version=lane.policy_version,
            policy_parameters=lane.policy_parameters,
            effective_lane_revision=lane_revision,
            bindings=resolved_bindings,
            execution_order=tuple(binding_ids[slot] for slot in execution_order),
        )

    @staticmethod
    def _validate_capabilities(
        lane: DecisionLaneSpec,
        binding: ModelBindingSpec,
        spec: ModelSpec,
    ) -> None:
        if (
            spec.supported_timeframes
            and lane.decision_timeframe not in spec.supported_timeframes
        ):
            raise PlannerError(
                f"{binding.slot_name} does not support decision timeframe "
                f"{lane.decision_timeframe}"
            )
        if (
            spec.supported_trigger_timeframes
            and lane.trigger_timeframe not in spec.supported_trigger_timeframes
        ):
            raise PlannerError(
                f"{binding.slot_name} does not support trigger timeframe "
                f"{lane.trigger_timeframe}"
            )
        if (
            spec.supported_trigger_modes
            and lane.trigger_mode not in spec.supported_trigger_modes
        ):
            raise PlannerError(
                f"{binding.slot_name} does not support trigger mode {lane.trigger_mode}"
            )
        if spec.stateful and (
            not spec.state_reconstruction.durable_pit_required
            or any(
                not requirement.replay_support_required
                for requirement in spec.intrinsic_data_requirements
            )
        ):
            raise PlannerError(
                f"stateful binding {binding.slot_name} is not replay-safe"
            )

    @staticmethod
    def _resolve_dependencies(
        bindings: Sequence[ModelBindingSpec],
        specs: Mapping[str, ModelSpec],
        binding_ids: Mapping[str, str],
    ) -> dict[str, dict[str, str]]:
        dependencies: dict[str, dict[str, str]] = {}
        binding_slots = set(specs)
        for binding in bindings:
            declared = {
                requirement.slot_name: requirement.artifact_type
                for requirement in specs[binding.slot_name].dependency_requirements
            }
            configured = dict(binding.dependencies)
            missing = sorted(set(declared) - set(configured))
            extra = sorted(set(configured) - set(declared))
            if missing:
                raise PlannerError(
                    f"binding {binding.slot_name} missing dependency slots: "
                    f"{', '.join(missing)}"
                )
            if extra:
                raise PlannerError(
                    f"binding {binding.slot_name} has undeclared dependency slots: "
                    f"{', '.join(extra)}"
                )

            resolved: dict[str, str] = {}
            for dependency_slot in sorted(declared):
                provider_slot = configured[dependency_slot]
                if provider_slot == binding.slot_name:
                    raise PlannerError(
                        f"binding {binding.slot_name} cannot depend on itself"
                    )
                if provider_slot not in binding_slots:
                    raise PlannerError(
                        f"binding {binding.slot_name} references missing provider "
                        f"{provider_slot}"
                    )
                provider_spec = specs[provider_slot]
                expected_artifact = declared[dependency_slot]
                if provider_spec.produces_artifact_type != expected_artifact:
                    raise PlannerError(
                        f"dependency {binding.slot_name}.{dependency_slot} requires "
                        f"{expected_artifact}, provider {provider_slot} produces "
                        f"{provider_spec.produces_artifact_type}"
                    )
                resolved[dependency_slot] = binding_ids[provider_slot]
            dependencies[binding.slot_name] = resolved
        return dependencies

    @staticmethod
    def _validate_stateful_replay_closure(
        bindings: Sequence[ModelBindingSpec],
        specs: Mapping[str, ModelSpec],
    ) -> None:
        """Require replay-safe external inputs across stateful ancestors."""

        bindings_by_slot = {binding.slot_name: binding for binding in bindings}
        for root_slot in sorted(bindings_by_slot):
            root_spec = specs[root_slot]
            if not root_spec.stateful:
                continue
            if not root_spec.state_reconstruction.durable_pit_required:
                raise PlannerError(
                    f"stateful binding {root_slot} is not replay-safe: "
                    "durable PIT reconstruction is required"
                )

            pending = [root_slot]
            visited: set[str] = set()
            while pending:
                slot_name = pending.pop()
                if slot_name in visited:
                    continue
                visited.add(slot_name)
                spec = specs[slot_name]
                for requirement in spec.intrinsic_data_requirements:
                    if requirement.replay_support_required:
                        continue
                    if slot_name == root_slot:
                        raise PlannerError(
                            f"stateful binding {root_slot} has non-replay-safe "
                            f"data concept {requirement.concept}"
                        )
                    raise PlannerError(
                        f"stateful binding {root_slot} depends on non-replay-safe "
                        f"upstream binding {slot_name} data concept "
                        f"{requirement.concept}"
                    )
                pending.extend(
                    sorted(bindings_by_slot[slot_name].dependencies.values())
                )

    @staticmethod
    def _topological_order(bindings: Sequence[ModelBindingSpec]) -> tuple[str, ...]:
        slots = {binding.slot_name for binding in bindings}
        indegree = {slot: 0 for slot in slots}
        consumers: dict[str, set[str]] = {slot: set() for slot in slots}
        for binding in bindings:
            for provider in binding.dependencies.values():
                if provider in slots and binding.slot_name not in consumers[provider]:
                    consumers[provider].add(binding.slot_name)
                    indegree[binding.slot_name] += 1

        ready = [slot for slot, degree in indegree.items() if degree == 0]
        ready.sort()
        heapify_ready = ready
        ordered: list[str] = []
        while heapify_ready:
            slot = heappop(heapify_ready)
            ordered.append(slot)
            for consumer in sorted(consumers[slot]):
                indegree[consumer] -= 1
                if indegree[consumer] == 0:
                    heappush(heapify_ready, consumer)

        if len(ordered) != len(slots):
            cycle_slots = sorted(
                slot for slot, degree in indegree.items() if degree > 0
            )
            raise PlannerError(
                "dependency cycle detected involving: " + ", ".join(cycle_slots)
            )
        return tuple(ordered)


def compile_decision_plan(
    catalog: PluginCatalog,
    lane_specs: Iterable[DecisionLaneSpec],
) -> ResolvedDecisionPlan:
    """Compile a catalog and explicit lanes without invoking any model."""

    return StaticCompositionPlanner(catalog).compile(lane_specs)


__all__ = [
    "DecisionLaneSpec",
    "ModelBindingSpec",
    "PlannerError",
    "ResolvedDecisionPlan",
    "ResolvedLanePlan",
    "StaticCompositionPlanner",
    "compile_decision_plan",
]
