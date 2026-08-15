"""Deterministic semantic data policy and request planning for ``decision_app``.

This module owns semantic routing policy and source-adapter boundaries only.  It
does not know how a cache, durable database, or live acquisition service is
implemented; tests and later runtime integrations provide small async fetchers.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Literal

from apps.decision_app.domain.contracts import ResolvedModelBinding
from apps.decision_app.domain.identity import sha256_fingerprint
from apps.decision_app.planning.planner import ResolvedLanePlan
from libs.contracts.decision import (
    DataMode,
    DataRequest,
    DataRequirement,
    DataSnapshot,
    FrozenMapping,
    require_utc,
    validate_data_snapshot,
)

DataSourceKind = Literal["cache", "pit", "live"]
DataScopeMode = Literal["lane_asset", "global"]
DataAttemptOutcome = Literal["MISS", "REJECTED", "ERROR", "ACCEPTED"]

DataFetcher = Callable[[DataRequest], Awaitable[DataSnapshot | None]]


class DataError(ValueError):
    """Base error for semantic data policy, planning, and resolution failures."""


class DataPolicyError(DataError):
    """Raised when an app-owned policy or source catalog is invalid."""


class DataPlanError(DataError):
    """Raised when a deterministic data plan cannot be compiled or trusted."""


class DataRequestError(DataError):
    """Raised when a runtime request violates its static data envelope."""


class DataSourceContractError(DataError):
    """Raised when a source violates the D5 fetch/result contract."""


def _require_non_empty(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _normalize_names(values: Iterable[str], *, field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field_name} must be a sequence of strings")
    normalized = tuple(
        _require_non_empty(value, field_name=field_name) for value in values
    )
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must not contain duplicates")
    return tuple(sorted(normalized))


def _normalize_order(values: Iterable[str], *, field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field_name} must be a sequence of source names")
    normalized = tuple(
        _require_non_empty(value, field_name=field_name) for value in values
    )
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must not contain duplicate sources")
    return normalized


def _freeze_names(values: Iterable[str], *, field_name: str) -> tuple[str, ...]:
    return _normalize_names(values, field_name=field_name)


def _freeze_string_map(
    values: Mapping[str, str], *, field_name: str
) -> FrozenMapping[str, str]:
    if not isinstance(values, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    normalized: dict[str, str] = {}
    for key, value in values.items():
        normalized[_require_non_empty(key, field_name=f"{field_name} key")] = (
            _require_non_empty(value, field_name=f"{field_name}[{key}]")
        )
    return FrozenMapping(dict(sorted(normalized.items())))


def _freeze_mapping(values: Mapping[str, Any], *, field_name: str) -> FrozenMapping:
    if not isinstance(values, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    if any(not isinstance(key, str) for key in values):
        raise TypeError(f"{field_name} keys must be strings")
    return FrozenMapping(dict(sorted(values.items())))


def _require_mode(value: object) -> DataMode:
    if value not in {"LIVE", "REPLAY"}:
        raise ValueError("mode must be LIVE or REPLAY")
    return value  # type: ignore[return-value]


def _require_utc_pair(market_as_of: datetime, cutoff: datetime) -> None:
    require_utc(market_as_of, field_name="market_as_of")
    require_utc(cutoff, field_name="resolver_knowledge_cutoff")
    if cutoff < market_as_of:
        raise ValueError("resolver_knowledge_cutoff must be at or after market_as_of")


@dataclass(frozen=True, slots=True, kw_only=True)
class DataSourceDefinition:
    """One explicit physical source adapter definition."""

    name: str
    version: str
    kind: DataSourceKind
    capability: Literal["LIVE_AND_REPLAY", "LIVE_ONLY"]
    fetcher: DataFetcher

    def __post_init__(self) -> None:
        _require_non_empty(self.name, field_name="source name")
        _require_non_empty(self.version, field_name="source version")
        if self.kind not in {"cache", "pit", "live"}:
            raise ValueError("source kind must be cache, pit, or live")
        if self.capability not in {"LIVE_AND_REPLAY", "LIVE_ONLY"}:
            raise ValueError("source capability must be LIVE_AND_REPLAY or LIVE_ONLY")
        if not callable(self.fetcher):
            raise TypeError("source fetcher must be callable")


class DataSourceCatalog:
    """Explicit immutable source catalog with deterministic iteration."""

    __slots__ = ("_sources",)

    def __init__(self, sources: Iterable[DataSourceDefinition]) -> None:
        entries = tuple(sources)
        if any(not isinstance(source, DataSourceDefinition) for source in entries):
            raise TypeError(
                "source catalog entries must be DataSourceDefinition values"
            )
        by_name: dict[str, DataSourceDefinition] = {}
        for source in entries:
            if source.name in by_name:
                raise DataPolicyError(f"duplicate source registration: {source.name}")
            by_name[source.name] = source
        object.__setattr__(
            self,
            "_sources",
            FrozenMapping(dict(sorted(by_name.items()))),
        )

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("DataSourceCatalog is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("DataSourceCatalog is immutable")

    def __iter__(self):
        return iter(self._sources.values())

    def __len__(self) -> int:
        return len(self._sources)

    def resolve(self, name: str) -> DataSourceDefinition:
        try:
            return self._sources[name]
        except KeyError as exc:
            raise DataPolicyError(f"unknown data source: {name}") from exc

    def get(self, name: str) -> DataSourceDefinition | None:
        return self._sources.get(name)

    @property
    def sources(self) -> Mapping[str, DataSourceDefinition]:
        return self._sources


@dataclass(frozen=True, slots=True, kw_only=True)
class ConceptDataPolicy:
    """App-owned semantic routing policy for one data concept."""

    concept: str
    scope_mode: DataScopeMode
    live_source_order: tuple[str, ...] = ()
    replay_source_order: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_non_empty(self.concept, field_name="data concept")
        if self.scope_mode not in {"lane_asset", "global"}:
            raise ValueError("scope_mode must be lane_asset or global")
        object.__setattr__(
            self,
            "live_source_order",
            _normalize_order(self.live_source_order, field_name="live_source_order"),
        )
        object.__setattr__(
            self,
            "replay_source_order",
            _normalize_order(
                self.replay_source_order,
                field_name="replay_source_order",
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DataPolicy:
    """Immutable app-owned policy with no wildcard or inheritance semantics."""

    name: str
    version: str
    concepts: Mapping[str, ConceptDataPolicy] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.name, field_name="data policy name")
        _require_non_empty(self.version, field_name="data policy version")
        if not isinstance(self.concepts, Mapping):
            raise TypeError("concepts must be a mapping")
        normalized: dict[str, ConceptDataPolicy] = {}
        for concept, policy in self.concepts.items():
            _require_non_empty(concept, field_name="data policy concept key")
            if not isinstance(policy, ConceptDataPolicy):
                raise TypeError("concept policies must be ConceptDataPolicy values")
            if concept != policy.concept:
                raise ValueError("concept policy key must match concept")
            normalized[concept] = policy
        object.__setattr__(
            self,
            "concepts",
            FrozenMapping(dict(sorted(normalized.items()))),
        )

    def get(self, concept: str) -> ConceptDataPolicy | None:
        return self.concepts.get(concept)

    def resolve(self, concept: str) -> ConceptDataPolicy:
        policy = self.get(concept)
        if policy is None:
            raise DataPolicyError(f"no data policy for concept: {concept}")
        return policy


def _source_metadata(
    source_names: Iterable[str], catalog: DataSourceCatalog
) -> tuple[
    FrozenMapping[str, str], FrozenMapping[str, DataSourceKind], FrozenMapping[str, str]
]:
    names = tuple(dict.fromkeys(source_names))
    versions: dict[str, str] = {}
    kinds: dict[str, DataSourceKind] = {}
    capabilities: dict[str, str] = {}
    for name in names:
        source = catalog.resolve(name)
        versions[name] = source.version
        kinds[name] = source.kind
        capabilities[name] = source.capability
    return (
        FrozenMapping(dict(sorted(versions.items()))),
        FrozenMapping(dict(sorted(kinds.items()))),
        FrozenMapping(dict(sorted(capabilities.items()))),
    )


_SOURCE_KIND_ORDER: dict[DataSourceKind, int] = {"cache": 0, "pit": 1, "live": 2}


def _validate_route(
    *,
    concept: str,
    mode: DataMode,
    source_names: Sequence[str],
    catalog: DataSourceCatalog,
) -> None:
    definitions = [catalog.resolve(name) for name in source_names]
    if mode == "LIVE":
        ranks = [_SOURCE_KIND_ORDER[source.kind] for source in definitions]
        if ranks != sorted(ranks):
            raise DataPolicyError(
                f"LIVE route for {concept} must follow cache -> pit -> live order"
            )
        if sum(source.kind == "live" for source in definitions) > 1:
            raise DataPolicyError(
                f"LIVE route for {concept} may contain one live source"
            )
    else:
        if any(
            source.kind != "pit" or source.capability != "LIVE_AND_REPLAY"
            for source in definitions
        ):
            raise DataPolicyError(
                f"REPLAY route for {concept} must contain replay-safe PIT sources"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedConceptDataRoute:
    """Policy route with source identity resolved from the explicit catalog."""

    concept: str
    scope_mode: DataScopeMode
    live_source_order: tuple[str, ...] = ()
    replay_source_order: tuple[str, ...] = ()
    source_versions: Mapping[str, str] = field(default_factory=dict)
    source_kinds: Mapping[str, DataSourceKind] = field(default_factory=dict)
    source_capabilities: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.concept, field_name="route concept")
        if self.scope_mode not in {"lane_asset", "global"}:
            raise ValueError("route scope_mode is invalid")
        live = _normalize_order(self.live_source_order, field_name="live_source_order")
        replay = _normalize_order(
            self.replay_source_order,
            field_name="replay_source_order",
        )
        object.__setattr__(self, "live_source_order", live)
        object.__setattr__(self, "replay_source_order", replay)
        versions = _freeze_string_map(
            self.source_versions, field_name="source_versions"
        )
        kinds = _freeze_mapping(self.source_kinds, field_name="source_kinds")
        capabilities = _freeze_mapping(
            self.source_capabilities,
            field_name="source_capabilities",
        )
        used = set(live) | set(replay)
        if set(versions) != used or set(kinds) != used or set(capabilities) != used:
            raise ValueError("route source metadata must cover exactly used sources")
        if any(kind not in {"cache", "pit", "live"} for kind in kinds.values()):
            raise ValueError("route source kinds are invalid")
        if any(
            capability not in {"LIVE_AND_REPLAY", "LIVE_ONLY"}
            for capability in capabilities.values()
        ):
            raise ValueError("route source capabilities are invalid")
        object.__setattr__(self, "source_versions", versions)
        object.__setattr__(self, "source_kinds", kinds)
        object.__setattr__(self, "source_capabilities", capabilities)
        live_ranks = [_SOURCE_KIND_ORDER[kinds[name]] for name in live]
        if live_ranks != sorted(live_ranks):
            raise ValueError("LIVE route must follow cache -> pit -> live order")
        if sum(kinds[name] == "live" for name in live) > 1:
            raise ValueError("LIVE route may contain one live source")
        if any(
            kinds[name] != "pit" or capabilities[name] != "LIVE_AND_REPLAY"
            for name in replay
        ):
            raise ValueError("REPLAY route must contain replay-safe PIT sources")


@dataclass(frozen=True, slots=True, kw_only=True)
class BindingDataPlan:
    """Exact intrinsic data envelope for one resolved binding."""

    binding_id: str
    requirements: tuple[DataRequirement, ...]
    required_concepts: tuple[str, ...]
    optional_concepts: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_non_empty(self.binding_id, field_name="data binding ID")
        requirements = tuple(self.requirements)
        if any(not isinstance(item, DataRequirement) for item in requirements):
            raise TypeError("data requirements must contain DataRequirement values")
        concepts = [item.concept for item in requirements]
        if len(set(concepts)) != len(concepts):
            raise ValueError("data binding requirement concepts must be unique")
        requirements = tuple(sorted(requirements, key=lambda item: item.concept))
        required = tuple(sorted(item.concept for item in requirements if item.required))
        optional = tuple(
            sorted(item.concept for item in requirements if not item.required)
        )
        if tuple(self.required_concepts) != required:
            raise ValueError("required_concepts must match requirements")
        if tuple(self.optional_concepts) != optional:
            raise ValueError("optional_concepts must match requirements")
        object.__setattr__(self, "requirements", requirements)
        object.__setattr__(self, "required_concepts", required)
        object.__setattr__(self, "optional_concepts", optional)


def _requirement_payload(requirement: DataRequirement) -> Mapping[str, Any]:
    return {
        "concept": requirement.concept,
        "required": requirement.required,
        "replay_support_required": requirement.replay_support_required,
        "max_age_at_market_as_of": requirement.max_age_at_market_as_of,
        "max_available_lag": requirement.max_available_lag,
        "alignment": requirement.alignment,
    }


def _route_payload(route: ResolvedConceptDataRoute) -> Mapping[str, Any]:
    return {
        "concept": route.concept,
        "scope_mode": route.scope_mode,
        "live_source_order": route.live_source_order,
        "replay_source_order": route.replay_source_order,
        "source_versions": route.source_versions,
        "source_kinds": route.source_kinds,
        "source_capabilities": route.source_capabilities,
    }


def _data_plan_payload_values(
    *,
    lane_id: str,
    base_lane_revision: str,
    data_policy_name: str,
    data_policy_version: str,
    requested_concepts: Sequence[str],
    routes: Mapping[str, ResolvedConceptDataRoute],
    unrouted_concepts: Sequence[str],
    bindings: Mapping[str, BindingDataPlan],
) -> Mapping[str, Any]:
    return {
        "lane_id": lane_id,
        "base_lane_revision": base_lane_revision,
        "policy": {
            "name": data_policy_name,
            "version": data_policy_version,
        },
        "requested_concepts": tuple(requested_concepts),
        "unrouted_concepts": tuple(unrouted_concepts),
        "routes": [_route_payload(routes[concept]) for concept in sorted(routes)],
        "bindings": [
            {
                "binding_id": binding_id,
                "requirements": [
                    _requirement_payload(requirement)
                    for requirement in binding.requirements
                ],
                "required_concepts": binding.required_concepts,
                "optional_concepts": binding.optional_concepts,
            }
            for binding_id, binding in sorted(bindings.items())
        ],
    }


def _data_plan_payload(plan: DataPlan) -> Mapping[str, Any]:
    return _data_plan_payload_values(
        lane_id=plan.lane_id,
        base_lane_revision=plan.base_lane_revision,
        data_policy_name=plan.data_policy_name,
        data_policy_version=plan.data_policy_version,
        requested_concepts=plan.requested_concepts,
        routes=plan.routes,
        unrouted_concepts=plan.unrouted_concepts,
        bindings=plan.bindings,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class DataPlan:
    """Immutable static data envelope and resolved physical routes for one lane."""

    lane_id: str
    base_lane_revision: str
    data_policy_name: str
    data_policy_version: str
    requested_concepts: tuple[str, ...]
    routes: Mapping[str, ResolvedConceptDataRoute]
    unrouted_concepts: tuple[str, ...]
    bindings: Mapping[str, BindingDataPlan]
    data_plan_fingerprint: str

    def __post_init__(self) -> None:
        for field_name in (
            "lane_id",
            "base_lane_revision",
            "data_policy_name",
            "data_policy_version",
            "data_plan_fingerprint",
        ):
            _require_non_empty(getattr(self, field_name), field_name=field_name)
        requested = _normalize_names(
            self.requested_concepts,
            field_name="requested_concepts",
        )
        unrouted = _normalize_names(
            self.unrouted_concepts,
            field_name="unrouted_concepts",
        )
        if not set(unrouted) <= set(requested):
            raise ValueError("unrouted concepts must be requested")
        routes: dict[str, ResolvedConceptDataRoute] = {}
        if not isinstance(self.routes, Mapping):
            raise TypeError("routes must be a mapping")
        for concept, route in self.routes.items():
            _require_non_empty(concept, field_name="data route concept key")
            if not isinstance(route, ResolvedConceptDataRoute):
                raise TypeError("routes must contain ResolvedConceptDataRoute values")
            if concept != route.concept:
                raise ValueError("route map key must match route concept")
            routes[concept] = route
        if not set(routes) <= set(requested):
            raise ValueError("routes must contain only requested concepts")
        if set(routes) & set(unrouted):
            raise ValueError("a concept cannot be both routed and unrouted")
        if set(routes) | set(unrouted) != set(requested):
            raise ValueError("requested concepts must be routed or unrouted")
        if not isinstance(self.bindings, Mapping):
            raise TypeError("bindings must be a mapping")
        bindings: dict[str, BindingDataPlan] = {}
        for binding_id, binding in self.bindings.items():
            _require_non_empty(binding_id, field_name="data binding map key")
            if not isinstance(binding, BindingDataPlan):
                raise TypeError("bindings must contain BindingDataPlan values")
            if binding_id != binding.binding_id:
                raise ValueError("data binding map key must match binding_id")
            bindings[binding_id] = binding
        if not bindings:
            raise ValueError("data plan must contain at least one binding")
        expected_requested = {
            requirement.concept
            for binding in bindings.values()
            for requirement in binding.requirements
        }
        if expected_requested != set(requested):
            raise ValueError("requested concepts must match binding demand")
        object.__setattr__(self, "requested_concepts", requested)
        object.__setattr__(self, "unrouted_concepts", unrouted)
        object.__setattr__(self, "routes", FrozenMapping(dict(sorted(routes.items()))))
        object.__setattr__(
            self,
            "bindings",
            FrozenMapping(dict(sorted(bindings.items()))),
        )
        expected_fingerprint = _compute_data_plan_fingerprint(self)
        if self.data_plan_fingerprint != expected_fingerprint:
            raise ValueError(
                "data_plan_fingerprint does not match normalized data plan"
            )


def _compute_data_plan_fingerprint(plan: DataPlan) -> str:
    return sha256_fingerprint(_data_plan_payload(plan))


def _resolve_route(
    policy: ConceptDataPolicy,
    catalog: DataSourceCatalog,
) -> ResolvedConceptDataRoute:
    for mode, source_names in (
        ("LIVE", policy.live_source_order),
        ("REPLAY", policy.replay_source_order),
    ):
        for source_name in source_names:
            catalog.resolve(source_name)
        _validate_route(
            concept=policy.concept,
            mode=mode,  # type: ignore[arg-type]
            source_names=source_names,
            catalog=catalog,
        )
    versions, kinds, capabilities = _source_metadata(
        (*policy.live_source_order, *policy.replay_source_order),
        catalog,
    )
    return ResolvedConceptDataRoute(
        concept=policy.concept,
        scope_mode=policy.scope_mode,
        live_source_order=policy.live_source_order,
        replay_source_order=policy.replay_source_order,
        source_versions=versions,
        source_kinds=kinds,
        source_capabilities=capabilities,
    )


def compile_data_plan(
    lane: ResolvedLanePlan,
    policy: DataPolicy,
    source_catalog: DataSourceCatalog,
) -> DataPlan:
    """Compile semantic binding demand into deterministic source routes."""

    if not isinstance(lane, ResolvedLanePlan):
        raise TypeError("lane must be a ResolvedLanePlan")
    if not isinstance(policy, DataPolicy):
        raise TypeError("policy must be a DataPolicy")
    if not isinstance(source_catalog, DataSourceCatalog):
        raise TypeError("source_catalog must be a DataSourceCatalog")

    bindings: dict[str, BindingDataPlan] = {}
    requested = sorted(
        {
            requirement.concept
            for binding in lane.bindings.values()
            for requirement in binding.effective_data_requirements
        }
    )
    for binding in lane.bindings.values():
        requirements = tuple(binding.effective_data_requirements)
        bindings[binding.binding_id] = BindingDataPlan(
            binding_id=binding.binding_id,
            requirements=requirements,
            required_concepts=tuple(
                sorted(item.concept for item in requirements if item.required)
            ),
            optional_concepts=tuple(
                sorted(item.concept for item in requirements if not item.required)
            ),
        )

    routes: dict[str, ResolvedConceptDataRoute] = {}
    unrouted: list[str] = []
    for concept in requested:
        concept_policy = policy.get(concept)
        if concept_policy is None:
            unrouted.append(concept)
        else:
            routes[concept] = _resolve_route(concept_policy, source_catalog)

    requested_concepts = tuple(requested)
    unrouted_concepts = tuple(unrouted)
    fingerprint = sha256_fingerprint(
        _data_plan_payload_values(
            lane_id=lane.lane_id,
            base_lane_revision=lane.effective_lane_revision,
            data_policy_name=policy.name,
            data_policy_version=policy.version,
            requested_concepts=requested_concepts,
            routes=routes,
            unrouted_concepts=unrouted_concepts,
            bindings=bindings,
        )
    )
    return DataPlan(
        lane_id=lane.lane_id,
        base_lane_revision=lane.effective_lane_revision,
        data_policy_name=policy.name,
        data_policy_version=policy.version,
        requested_concepts=requested_concepts,
        routes=routes,
        unrouted_concepts=unrouted_concepts,
        bindings=bindings,
        data_plan_fingerprint=fingerprint,
    )


def validate_data_plan_against_lane(
    data_plan: DataPlan,
    lane: ResolvedLanePlan,
) -> None:
    """Validate plan identity and exact per-binding semantic data demand."""

    if not isinstance(data_plan, DataPlan):
        raise TypeError("data_plan must be a DataPlan")
    if not isinstance(lane, ResolvedLanePlan):
        raise TypeError("lane must be a ResolvedLanePlan")
    if data_plan.lane_id != lane.lane_id:
        raise DataPlanError("data plan lane_id must match resolved lane")
    if data_plan.base_lane_revision != lane.effective_lane_revision:
        raise DataPlanError("data plan base lane revision must match resolved lane")
    expected_ids = {binding.binding_id for binding in lane.bindings.values()}
    if set(data_plan.bindings) != expected_ids:
        raise DataPlanError("data plan binding IDs must match resolved lane")
    for binding in lane.bindings.values():
        plan_binding = data_plan.bindings[binding.binding_id]
        expected = tuple(
            sorted(binding.effective_data_requirements, key=lambda item: item.concept)
        )
        if plan_binding.requirements != expected:
            raise DataPlanError(f"data binding {binding.binding_id} demand mismatch")


def _physical_request_payload(
    request: DataRequest,
    *,
    lane_id: str,
) -> Mapping[str, Any]:
    _require_non_empty(lane_id, field_name="lane_id")
    return {
        "lane_id": lane_id,
        "concept": request.concept,
        "asset": request.asset,
        "scope": request.scope,
        "market_as_of": request.market_as_of,
        "mode": request.mode,
        "resolver_knowledge_cutoff": request.resolver_knowledge_cutoff,
        "replay_support_required": request.replay_support_required,
        "freshness_bound": request.freshness_bound,
        "max_available_lag": request.max_available_lag,
        "alignment": request.alignment,
    }


def make_data_request_key(request: DataRequest, *, lane_id: str) -> str:
    """Build the canonical physical identity, intentionally excluding requiredness."""

    if not isinstance(request, DataRequest):
        raise TypeError("request must be a DataRequest")
    return f"data:{sha256_fingerprint(_physical_request_payload(request, lane_id=lane_id))}"


def _canonical_physical_request(request: DataRequest) -> DataRequest:
    """Remove binding-local requiredness before shared physical acquisition."""

    return replace(request, required=False)


def materialize_data_request(
    *,
    resolved_lane: ResolvedLanePlan,
    resolved_binding: ResolvedModelBinding,
    data_plan: DataPlan,
    dynamic_requirement: DataRequirement,
    mode: DataMode,
    market_as_of: datetime,
    resolver_knowledge_cutoff: datetime,
) -> DataRequest:
    """Materialize one exact plugin semantic demand using app-owned routing."""

    if not isinstance(resolved_lane, ResolvedLanePlan):
        raise TypeError("resolved_lane must be a ResolvedLanePlan")
    if not isinstance(resolved_binding, ResolvedModelBinding):
        raise TypeError("resolved_binding must be a ResolvedModelBinding")
    lane_binding = next(
        (
            binding
            for binding in resolved_lane.bindings.values()
            if binding.binding_id == resolved_binding.binding_id
        ),
        None,
    )
    if lane_binding is None:
        raise DataRequestError("resolved binding is not in resolved lane")
    if resolved_binding != lane_binding:
        raise DataRequestError("resolved binding does not match resolved lane")
    validate_data_plan_against_lane(data_plan, resolved_lane)
    _require_mode(mode)
    _require_utc_pair(market_as_of, resolver_knowledge_cutoff)
    try:
        binding_plan = data_plan.bindings[resolved_binding.binding_id]
    except KeyError as exc:
        raise DataRequestError("resolved binding is not in data plan") from exc
    declared = next(
        (
            requirement
            for requirement in binding_plan.requirements
            if requirement.concept == dynamic_requirement.concept
        ),
        None,
    )
    if declared is None:
        raise DataRequestError(
            f"concept {dynamic_requirement.concept} is not declared by binding"
        )
    if declared != dynamic_requirement:
        raise DataRequestError(
            f"dynamic requirement for {dynamic_requirement.concept} does not match envelope"
        )
    route = data_plan.routes.get(dynamic_requirement.concept)
    if route is None:
        raise DataRequestError(
            f"concept {dynamic_requirement.concept} has no resolved data route"
        )
    asset = resolved_lane.asset if route.scope_mode == "lane_asset" else None
    scope = None if route.scope_mode == "lane_asset" else "global"
    provisional = DataRequest(
        request_key="pending",
        concept=dynamic_requirement.concept,
        market_as_of=market_as_of,
        required=dynamic_requirement.required,
        mode=mode,
        resolver_knowledge_cutoff=resolver_knowledge_cutoff,
        replay_support_required=dynamic_requirement.replay_support_required,
        asset=asset,
        scope=scope,
        freshness_bound=dynamic_requirement.max_age_at_market_as_of,
        max_available_lag=dynamic_requirement.max_available_lag,
        alignment=dynamic_requirement.alignment,
    )
    return DataRequest(
        request_key=make_data_request_key(provisional, lane_id=resolved_lane.lane_id),
        concept=provisional.concept,
        market_as_of=provisional.market_as_of,
        required=provisional.required,
        mode=provisional.mode,
        resolver_knowledge_cutoff=provisional.resolver_knowledge_cutoff,
        replay_support_required=provisional.replay_support_required,
        asset=provisional.asset,
        scope=provisional.scope,
        freshness_bound=provisional.freshness_bound,
        max_available_lag=provisional.max_available_lag,
        alignment=provisional.alignment,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class BindingDataRequest:
    """One runtime-materialized request associated with a resolved binding."""

    binding_id: str
    request: DataRequest

    def __post_init__(self) -> None:
        _require_non_empty(self.binding_id, field_name="binding_id")
        if not isinstance(self.request, DataRequest):
            raise TypeError("request must be a DataRequest")


@dataclass(frozen=True, slots=True, kw_only=True)
class DataSourceAttempt:
    """Stable per-source outcome evidence for one resolver request."""

    source: str
    source_kind: DataSourceKind
    outcome: DataAttemptOutcome
    reason: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.source, field_name="attempt source")
        if self.source_kind not in {"cache", "pit", "live"}:
            raise ValueError("attempt source_kind is invalid")
        if self.outcome not in {"MISS", "REJECTED", "ERROR", "ACCEPTED"}:
            raise ValueError("attempt outcome is invalid")
        if self.reason is not None:
            _require_non_empty(self.reason, field_name="attempt reason")


def _freeze_request_map(
    values: Mapping[str, DataRequest], *, field_name: str
) -> FrozenMapping[str, DataRequest]:
    if not isinstance(values, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    normalized: dict[str, DataRequest] = {}
    for key, request in values.items():
        _require_non_empty(key, field_name=f"{field_name} key")
        if not isinstance(request, DataRequest):
            raise TypeError(f"{field_name} must contain DataRequest values")
        if key != request.request_key:
            raise ValueError(f"{field_name} key must match request_key")
        normalized[key] = request
    return FrozenMapping(dict(sorted(normalized.items())))


@dataclass(frozen=True, slots=True, kw_only=True)
class BindingDataResolution:
    """Binding-isolated data availability and visible snapshots."""

    binding_id: str
    requested_request_keys: tuple[str, ...]
    required_request_keys: tuple[str, ...]
    optional_request_keys: tuple[str, ...]
    available: bool
    snapshots: Mapping[str, DataSnapshot] = field(default_factory=dict)
    missing_required_requests: tuple[str, ...] = ()
    missing_optional_requests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_non_empty(self.binding_id, field_name="binding_id")
        requested = _normalize_names(
            self.requested_request_keys,
            field_name="requested_request_keys",
        )
        required_requests = _normalize_names(
            self.required_request_keys,
            field_name="required_request_keys",
        )
        optional_requests = _normalize_names(
            self.optional_request_keys,
            field_name="optional_request_keys",
        )
        required = _normalize_names(
            self.missing_required_requests,
            field_name="missing_required_requests",
        )
        optional = _normalize_names(
            self.missing_optional_requests,
            field_name="missing_optional_requests",
        )
        if not isinstance(self.available, bool):
            raise TypeError("available must be a bool")
        if set(required_requests) & set(optional_requests):
            raise ValueError("required and optional request keys must be disjoint")
        if set(required_requests) | set(optional_requests) != set(requested):
            raise ValueError(
                "required and optional request keys must classify every request"
            )
        if set(required) & set(optional):
            raise ValueError("missing required and optional requests must be disjoint")
        if not set(required) <= set(required_requests):
            raise ValueError("missing required requests must be required requests")
        if not set(optional) <= set(optional_requests):
            raise ValueError("missing optional requests must be optional requests")
        if not isinstance(self.snapshots, Mapping):
            raise TypeError("snapshots must be a mapping")
        snapshots: dict[str, DataSnapshot] = {}
        for key, snapshot in self.snapshots.items():
            _require_non_empty(key, field_name="binding snapshot key")
            if not isinstance(snapshot, DataSnapshot):
                raise TypeError("snapshots must contain DataSnapshot values")
            if key != snapshot.request_key:
                raise ValueError("binding snapshot key must match request_key")
            snapshots[key] = snapshot
        snapshot_keys = set(snapshots)
        if snapshot_keys & (set(required) | set(optional)):
            raise ValueError("a request cannot be present and missing")
        if snapshot_keys | set(required) | set(optional) != set(requested):
            raise ValueError("binding resolution must classify every request")
        if self.available != (not required):
            raise ValueError(
                "binding availability must match missing required requests"
            )
        object.__setattr__(self, "requested_request_keys", requested)
        object.__setattr__(self, "required_request_keys", required_requests)
        object.__setattr__(self, "optional_request_keys", optional_requests)
        object.__setattr__(self, "missing_required_requests", required)
        object.__setattr__(self, "missing_optional_requests", optional)
        object.__setattr__(
            self, "snapshots", FrozenMapping(dict(sorted(snapshots.items())))
        )


def _freeze_snapshot_map(
    values: Mapping[str, DataSnapshot], *, field_name: str
) -> FrozenMapping[str, DataSnapshot]:
    if not isinstance(values, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    normalized: dict[str, DataSnapshot] = {}
    for key, snapshot in values.items():
        _require_non_empty(key, field_name=f"{field_name} key")
        if not isinstance(snapshot, DataSnapshot):
            raise TypeError(f"{field_name} must contain DataSnapshot values")
        if key != snapshot.request_key:
            raise ValueError(f"{field_name} key must match request_key")
        normalized[key] = snapshot
    return FrozenMapping(dict(sorted(normalized.items())))


def _freeze_attempt_map(
    values: Mapping[str, Sequence[DataSourceAttempt]], *, field_name: str
) -> FrozenMapping[str, tuple[DataSourceAttempt, ...]]:
    if not isinstance(values, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    normalized: dict[str, tuple[DataSourceAttempt, ...]] = {}
    for key, attempts in values.items():
        _require_non_empty(key, field_name=f"{field_name} key")
        attempt_tuple = tuple(attempts)
        if any(not isinstance(attempt, DataSourceAttempt) for attempt in attempt_tuple):
            raise TypeError(f"{field_name} must contain DataSourceAttempt values")
        normalized[key] = attempt_tuple
    return FrozenMapping(dict(sorted(normalized.items())))


@dataclass(frozen=True, slots=True, kw_only=True)
class DataResolution:
    """Immutable shared resolution with binding-isolated availability evidence."""

    lane_id: str
    base_lane_revision: str
    data_plan_fingerprint: str
    mode: DataMode
    market_as_of: datetime
    resolver_knowledge_cutoff: datetime
    requests: Mapping[str, DataRequest]
    shared_snapshots: Mapping[str, DataSnapshot]
    unavailable_requests: Mapping[str, str]
    attempts: Mapping[str, Sequence[DataSourceAttempt]]
    bindings: Mapping[str, BindingDataResolution]

    def __post_init__(self) -> None:
        for field_name in (
            "lane_id",
            "base_lane_revision",
            "data_plan_fingerprint",
        ):
            _require_non_empty(getattr(self, field_name), field_name=field_name)
        _require_mode(self.mode)
        _require_utc_pair(self.market_as_of, self.resolver_knowledge_cutoff)
        requests = _freeze_request_map(self.requests, field_name="requests")
        snapshots = _freeze_snapshot_map(
            self.shared_snapshots,
            field_name="shared_snapshots",
        )
        if not isinstance(self.unavailable_requests, Mapping):
            raise TypeError("unavailable_requests must be a mapping")
        unavailable: dict[str, str] = {}
        for key, reason in self.unavailable_requests.items():
            _require_non_empty(key, field_name="unavailable request key")
            _require_non_empty(reason, field_name="unavailable request reason")
            unavailable[key] = reason
        if set(snapshots) & set(unavailable):
            raise ValueError("a request cannot be shared and unavailable")
        if set(snapshots) | set(unavailable) != set(requests):
            raise ValueError("every request must be shared or unavailable")
        for key, request in requests.items():
            if request.mode != self.mode:
                raise ValueError("request mode must match data resolution mode")
            if request.market_as_of != self.market_as_of:
                raise ValueError("request market_as_of must match data resolution")
            if request.resolver_knowledge_cutoff != self.resolver_knowledge_cutoff:
                raise ValueError("request knowledge cutoff must match data resolution")
            if make_data_request_key(request, lane_id=self.lane_id) != key:
                raise ValueError("request key is not canonical")
            if key in snapshots:
                validate_data_snapshot(request, snapshots[key])
        attempts = _freeze_attempt_map(self.attempts, field_name="attempts")
        if set(attempts) != set(requests):
            raise ValueError("attempt evidence must cover every request")
        for key, attempt_sequence in attempts.items():
            accepted = [
                attempt for attempt in attempt_sequence if attempt.outcome == "ACCEPTED"
            ]
            if key in snapshots:
                if len(accepted) != 1:
                    raise ValueError(
                        "shared snapshot requires exactly one accepted attempt"
                    )
                if attempt_sequence[-1] is not accepted[0]:
                    raise ValueError("accepted attempt must be the final attempt")
                if accepted[0].source != snapshots[key].source:
                    raise ValueError(
                        "accepted attempt source must match shared snapshot source"
                    )
            else:
                if accepted:
                    raise ValueError(
                        "unavailable request cannot contain an accepted attempt"
                    )
                if not attempt_sequence and self.unavailable_requests[key] != (
                    "no_allowed_source"
                ):
                    raise ValueError(
                        "empty attempts require no_allowed_source unavailability"
                    )
        if not isinstance(self.bindings, Mapping):
            raise TypeError("bindings must be a mapping")
        bindings: dict[str, BindingDataResolution] = {}
        for binding_id, binding in self.bindings.items():
            _require_non_empty(binding_id, field_name="binding resolution key")
            if not isinstance(binding, BindingDataResolution):
                raise TypeError("bindings must contain BindingDataResolution values")
            if binding_id != binding.binding_id:
                raise ValueError("binding resolution key must match binding_id")
            if not set(binding.requested_request_keys) <= set(requests):
                raise ValueError("binding requests must belong to resolution requests")
            for key, snapshot in binding.snapshots.items():
                if key not in snapshots or snapshot != snapshots[key]:
                    raise ValueError("binding snapshot must match shared snapshot")
            for key in (
                *binding.missing_required_requests,
                *binding.missing_optional_requests,
            ):
                if key not in unavailable:
                    raise ValueError(
                        "missing binding request needs unavailable evidence"
                    )
            bindings[binding_id] = binding
        object.__setattr__(self, "requests", requests)
        object.__setattr__(self, "shared_snapshots", snapshots)
        object.__setattr__(
            self,
            "unavailable_requests",
            FrozenMapping(dict(sorted(unavailable.items()))),
        )
        object.__setattr__(self, "attempts", attempts)
        object.__setattr__(
            self,
            "bindings",
            FrozenMapping(dict(sorted(bindings.items()))),
        )


def _validate_binding_request(
    request: DataRequest,
    lane: ResolvedLanePlan,
    binding: ResolvedModelBinding,
    binding_plan: BindingDataPlan,
    route: ResolvedConceptDataRoute | None,
    *,
    mode: DataMode,
    market_as_of: datetime,
    resolver_knowledge_cutoff: datetime,
) -> None:
    if request.mode != mode:
        raise DataRequestError("request mode must match resolver mode")
    if request.market_as_of != market_as_of:
        raise DataRequestError("request market_as_of must match resolver cutoff")
    if request.resolver_knowledge_cutoff != resolver_knowledge_cutoff:
        raise DataRequestError("request knowledge cutoff must match resolver cutoff")
    if route is None:
        raise DataRequestError(f"concept {request.concept} has no resolved route")
    declared = next(
        (item for item in binding_plan.requirements if item.concept == request.concept),
        None,
    )
    if declared is None:
        raise DataRequestError(f"binding {binding.slot_name} did not declare concept")
    if request.required != declared.required:
        raise DataRequestError("request requiredness does not match data envelope")
    if request.replay_support_required != declared.replay_support_required:
        raise DataRequestError(
            "request replay requirement does not match data envelope"
        )
    if request.freshness_bound != declared.max_age_at_market_as_of:
        raise DataRequestError("request freshness does not match data envelope")
    if request.max_available_lag != declared.max_available_lag:
        raise DataRequestError("request availability lag does not match data envelope")
    if request.alignment != declared.alignment:
        raise DataRequestError("request alignment does not match data envelope")
    if route.scope_mode == "lane_asset":
        if request.asset != lane.asset:
            raise DataRequestError("lane_asset request asset must match resolved lane")
        if request.scope is not None:
            raise DataRequestError("lane_asset request must not carry global scope")
    else:
        if request.asset is not None or request.scope != "global":
            raise DataRequestError("global request must carry global scope only")


class DataResolver:
    """Bounded deterministic resolver over an explicit source catalog."""

    def __init__(self, source_catalog: DataSourceCatalog) -> None:
        if not isinstance(source_catalog, DataSourceCatalog):
            raise TypeError("source_catalog must be a DataSourceCatalog")
        self._source_catalog = source_catalog

    async def resolve(
        self,
        data_plan: DataPlan,
        resolved_lane: ResolvedLanePlan,
        binding_requests: Sequence[BindingDataRequest],
        *,
        mode: DataMode,
        market_as_of: datetime,
        resolver_knowledge_cutoff: datetime,
    ) -> DataResolution:
        """Resolve one bounded request batch without retries or background state."""

        if not isinstance(data_plan, DataPlan):
            raise TypeError("data_plan must be a DataPlan")
        if not isinstance(resolved_lane, ResolvedLanePlan):
            raise TypeError("resolved_lane must be a ResolvedLanePlan")
        validate_data_plan_against_lane(data_plan, resolved_lane)
        _require_mode(mode)
        _require_utc_pair(market_as_of, resolver_knowledge_cutoff)
        self._validate_source_catalog_against_plan(data_plan)
        if isinstance(binding_requests, (str, bytes)):
            raise TypeError("binding_requests must be a sequence")

        bindings_by_id = {
            binding.binding_id: binding for binding in resolved_lane.bindings.values()
        }
        requests_by_binding: dict[str, list[DataRequest]] = {
            binding_id: [] for binding_id in bindings_by_id
        }
        grouped: dict[str, list[tuple[str, DataRequest]]] = {}
        seen_pairs: set[tuple[str, str]] = set()
        for item in binding_requests:
            if not isinstance(item, BindingDataRequest):
                raise TypeError(
                    "binding_requests must contain BindingDataRequest values"
                )
            binding = bindings_by_id.get(item.binding_id)
            if binding is None:
                raise DataRequestError(f"unknown binding request: {item.binding_id}")
            binding_plan = data_plan.bindings[item.binding_id]
            route = data_plan.routes.get(item.request.concept)
            _validate_binding_request(
                item.request,
                resolved_lane,
                binding,
                binding_plan,
                route,
                mode=mode,
                market_as_of=market_as_of,
                resolver_knowledge_cutoff=resolver_knowledge_cutoff,
            )
            if (
                make_data_request_key(item.request, lane_id=data_plan.lane_id)
                != item.request.request_key
            ):
                raise DataRequestError("request_key is not canonical")
            pair = (item.binding_id, item.request.request_key)
            if pair in seen_pairs:
                raise DataRequestError("duplicate binding/request pair")
            seen_pairs.add(pair)
            requests_by_binding[item.binding_id].append(item.request)
            grouped.setdefault(item.request.request_key, []).append(
                (item.binding_id, item.request)
            )

        unique_requests: dict[str, DataRequest] = {}
        for request_key, entries in grouped.items():
            first = entries[0][1]
            for _, request in entries[1:]:
                if not _same_physical_request(first, request):
                    raise DataRequestError(
                        f"conflicting physical semantics for request key {request_key}"
                    )
            unique_requests[request_key] = _canonical_physical_request(first)

        shared: dict[str, DataSnapshot] = {}
        unavailable: dict[str, str] = {}
        attempts: dict[str, tuple[DataSourceAttempt, ...]] = {}
        for request_key in sorted(unique_requests):
            request = unique_requests[request_key]
            snapshot, request_attempts, reason = await self._resolve_one(
                request,
                data_plan.routes[request.concept],
            )
            attempts[request_key] = request_attempts
            if snapshot is None:
                unavailable[request_key] = reason or "unavailable"
            else:
                shared[request_key] = snapshot

        binding_resolutions: dict[str, BindingDataResolution] = {}
        for binding_id in sorted(bindings_by_id):
            requested = tuple(
                sorted(
                    request.request_key for request in requests_by_binding[binding_id]
                )
            )
            missing_required = tuple(
                sorted(
                    request.request_key
                    for request in requests_by_binding[binding_id]
                    if request.request_key in unavailable and request.required
                )
            )
            missing_optional = tuple(
                sorted(
                    request.request_key
                    for request in requests_by_binding[binding_id]
                    if request.request_key in unavailable and not request.required
                )
            )
            binding_resolutions[binding_id] = BindingDataResolution(
                binding_id=binding_id,
                requested_request_keys=requested,
                required_request_keys=tuple(
                    sorted(
                        request.request_key
                        for request in requests_by_binding[binding_id]
                        if request.required
                    )
                ),
                optional_request_keys=tuple(
                    sorted(
                        request.request_key
                        for request in requests_by_binding[binding_id]
                        if not request.required
                    )
                ),
                available=not missing_required,
                snapshots={
                    request_key: shared[request_key]
                    for request_key in requested
                    if request_key in shared
                },
                missing_required_requests=missing_required,
                missing_optional_requests=missing_optional,
            )

        return DataResolution(
            lane_id=resolved_lane.lane_id,
            base_lane_revision=resolved_lane.effective_lane_revision,
            data_plan_fingerprint=data_plan.data_plan_fingerprint,
            mode=mode,
            market_as_of=market_as_of,
            resolver_knowledge_cutoff=resolver_knowledge_cutoff,
            requests=unique_requests,
            shared_snapshots=shared,
            unavailable_requests=unavailable,
            attempts=attempts,
            bindings=binding_resolutions,
        )

    def _validate_source_catalog_against_plan(self, data_plan: DataPlan) -> None:
        for route in data_plan.routes.values():
            for source_name in set(route.source_versions):
                source = self._source_catalog.resolve(source_name)
                if (
                    source.version != route.source_versions[source_name]
                    or source.kind != route.source_kinds[source_name]
                    or source.capability != route.source_capabilities[source_name]
                ):
                    raise DataPlanError(
                        f"source catalog definition drift for {source_name}"
                    )

    async def _resolve_one(
        self,
        request: DataRequest,
        route: ResolvedConceptDataRoute,
    ) -> tuple[DataSnapshot | None, tuple[DataSourceAttempt, ...], str | None]:
        source_names = (
            route.replay_source_order
            if request.mode == "REPLAY"
            else route.live_source_order
        )
        if not source_names:
            return None, (), "no_allowed_source"
        attempts: list[DataSourceAttempt] = []
        for source_name in source_names:
            source = self._source_catalog.resolve(source_name)
            if request.mode == "REPLAY" and (
                source.kind != "pit" or source.capability != "LIVE_AND_REPLAY"
            ):
                raise DataPlanError("REPLAY attempted a non-replay-safe source")
            try:
                result = source.fetcher(request)
                if not inspect.isawaitable(result):
                    raise DataSourceContractError(
                        f"source {source.name} fetcher did not return an awaitable"
                    )
                candidate = await result
            except asyncio.CancelledError:
                raise
            except DataSourceContractError:
                raise
            except Exception:  # noqa: BLE001 - ordinary source failures fall through
                attempts.append(
                    DataSourceAttempt(
                        source=source.name,
                        source_kind=source.kind,
                        outcome="ERROR",
                        reason="source_error",
                    )
                )
                continue
            if candidate is None:
                attempts.append(
                    DataSourceAttempt(
                        source=source.name,
                        source_kind=source.kind,
                        outcome="MISS",
                        reason="miss",
                    )
                )
                continue
            self._validate_candidate_contract(source, request, candidate)
            try:
                validate_data_snapshot(request, candidate)
            except ValueError:
                attempts.append(
                    DataSourceAttempt(
                        source=source.name,
                        source_kind=source.kind,
                        outcome="REJECTED",
                        reason="ineligible_candidate",
                    )
                )
                continue
            attempts.append(
                DataSourceAttempt(
                    source=source.name,
                    source_kind=source.kind,
                    outcome="ACCEPTED",
                    reason="accepted",
                )
            )
            return candidate, tuple(attempts), None
        return None, tuple(attempts), "all_sources_unavailable"

    @staticmethod
    def _validate_candidate_contract(
        source: DataSourceDefinition,
        request: DataRequest,
        candidate: object,
    ) -> None:
        if not isinstance(candidate, DataSnapshot):
            raise DataSourceContractError(
                f"source {source.name} returned a non-DataSnapshot value"
            )
        if candidate.source != source.name:
            raise DataSourceContractError(
                "snapshot source does not match source definition"
            )
        if candidate.resolved_capability != source.capability:
            raise DataSourceContractError(
                "snapshot capability does not match source definition"
            )
        if candidate.concept != request.concept:
            raise DataSourceContractError("snapshot concept does not match request")
        if candidate.request_key != request.request_key:
            raise DataSourceContractError("snapshot request_key does not match request")


def _same_physical_request(left: DataRequest, right: DataRequest) -> bool:
    return _physical_request_payload(left, lane_id="same") == _physical_request_payload(
        right,
        lane_id="same",
    )


__all__ = [
    "BindingDataPlan",
    "BindingDataRequest",
    "BindingDataResolution",
    "ConceptDataPolicy",
    "DataError",
    "DataPlan",
    "DataPlanError",
    "DataPolicy",
    "DataPolicyError",
    "DataRequestError",
    "DataResolution",
    "DataResolver",
    "DataScopeMode",
    "DataSourceAttempt",
    "DataSourceCatalog",
    "DataSourceContractError",
    "DataSourceDefinition",
    "DataSourceKind",
    "ResolvedConceptDataRoute",
    "compile_data_plan",
    "make_data_request_key",
    "materialize_data_request",
    "validate_data_plan_against_lane",
]
