"""Static shared-feature planning for the offline decision_app foundation."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

from apps.decision_app.domain.contracts import ResolvedModelBinding
from apps.decision_app.domain.identity import sha256_fingerprint
from apps.decision_app.domain.market_state import MarketSeriesKey, TimeframeGrid
from apps.decision_app.planning.planner import ResolvedDecisionPlan, ResolvedLanePlan
from libs.contracts.decision import FrozenMapping

FeatureHistorySource = Literal["decision", "trigger", "fixed"]
FeatureCalculator = Callable[[Any], Any]


class FeatureError(ValueError):
    """Base error for invalid shared-feature definitions or plans."""


class FeatureCatalogError(FeatureError):
    """Raised when an explicit feature catalog is invalid or incomplete."""


class FeaturePlanError(FeatureError):
    """Raised when feature demand cannot be compiled safely."""


def _require_non_empty(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _require_positive_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
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


def _series_sort_key(key: MarketSeriesKey) -> tuple[str, str, str, str]:
    return (key.asset, key.venue, key.instrument_id, key.timeframe)


def _freeze_history_map(
    values: Mapping[MarketSeriesKey, int], *, field_name: str
) -> FrozenMapping[MarketSeriesKey, int]:
    if not isinstance(values, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    normalized: dict[MarketSeriesKey, int] = {}
    for key, count in values.items():
        if not isinstance(key, MarketSeriesKey):
            raise TypeError(f"{field_name} keys must be MarketSeriesKey values")
        normalized[key] = _require_positive_int(
            count,
            field_name=f"{field_name}[{key.timeframe}]",
        )
    return FrozenMapping(
        dict(sorted(normalized.items(), key=lambda item: _series_sort_key(item[0])))
    )


def _validate_partition(
    requested: set[str],
    effective: set[str],
    disabled: set[str],
    undefined: set[str],
    *,
    field_name: str,
) -> None:
    categories = (effective, disabled, undefined)
    for index, first in enumerate(categories):
        for second in categories[index + 1 :]:
            if overlap := first & second:
                raise ValueError(
                    f"{field_name} classification overlaps: {sorted(overlap)}"
                )
    if effective | disabled | undefined != requested:
        raise ValueError(
            f"{field_name} classification must cover exactly the requested features"
        )
    if (
        not effective <= requested
        or not disabled <= requested
        or not undefined <= requested
    ):
        raise ValueError(f"{field_name} classification contains an unrequested feature")


@dataclass(frozen=True, slots=True, kw_only=True)
class FeatureHistoryRequirement:
    """One exact positive closed-bar lookback owned by a feature definition."""

    source: FeatureHistorySource
    bars: int
    timeframe: str | None = None

    def __post_init__(self) -> None:
        if self.source not in {"decision", "trigger", "fixed"}:
            raise ValueError("feature history source is not supported")
        _require_positive_int(self.bars, field_name="feature history bars")
        if self.source in {"decision", "trigger"}:
            if self.timeframe is not None:
                raise ValueError(
                    f"{self.source} feature history must not specify timeframe"
                )
        elif self.timeframe is None:
            raise ValueError("fixed feature history requires timeframe")
        else:
            _require_non_empty(self.timeframe, field_name="feature history timeframe")


FeatureHistoryRequirementResolver = Callable[
    [ResolvedLanePlan], Sequence[FeatureHistoryRequirement]
]
FeatureConfigFingerprintResolver = Callable[[ResolvedLanePlan], str]


@dataclass(frozen=True, slots=True, kw_only=True)
class SharedFeatureDefinition:
    """Explicit app-owned implementation metadata for one shared feature."""

    name: str
    version: str
    calculator: FeatureCalculator
    history_requirements: tuple[FeatureHistoryRequirement, ...] = ()
    history_requirement_resolver: FeatureHistoryRequirementResolver | None = None
    config_fingerprint_resolver: FeatureConfigFingerprintResolver | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.name, field_name="feature name")
        _require_non_empty(self.version, field_name="feature version")
        if not callable(self.calculator):
            raise TypeError("feature calculator must be callable")
        if self.history_requirement_resolver is not None and not callable(
            self.history_requirement_resolver
        ):
            raise TypeError("history_requirement_resolver must be callable")
        if self.config_fingerprint_resolver is not None and not callable(
            self.config_fingerprint_resolver
        ):
            raise TypeError("config_fingerprint_resolver must be callable")
        requirements = tuple(self.history_requirements)
        if any(
            not isinstance(item, FeatureHistoryRequirement) for item in requirements
        ):
            raise TypeError(
                "history_requirements must contain FeatureHistoryRequirement values"
            )
        if self.history_requirement_resolver is not None and requirements:
            raise ValueError(
                "dynamic history requirements cannot be combined with static "
                "history_requirements"
            )
        object.__setattr__(
            self,
            "history_requirements",
            tuple(
                sorted(
                    requirements,
                    key=lambda item: (item.source, item.timeframe or "", item.bars),
                )
            ),
        )


class FeatureCatalog:
    """Immutable explicit catalog with one definition per semantic name."""

    __slots__ = ("_by_name", "_definitions")

    def __init__(self, definitions: Iterable[SharedFeatureDefinition]) -> None:
        entries = tuple(definitions)
        if any(
            not isinstance(definition, SharedFeatureDefinition)
            for definition in entries
        ):
            raise TypeError(
                "feature catalog entries must be SharedFeatureDefinition values"
            )
        by_name: dict[str, SharedFeatureDefinition] = {}
        for definition in entries:
            if definition.name in by_name:
                raise FeatureCatalogError(
                    f"duplicate feature definition: {definition.name}"
                )
            by_name[definition.name] = definition
        ordered = tuple(sorted(entries, key=lambda definition: definition.name))
        object.__setattr__(self, "_definitions", ordered)
        object.__setattr__(self, "_by_name", MappingProxyType(by_name))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("FeatureCatalog is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("FeatureCatalog is immutable")

    def __iter__(self) -> Iterator[SharedFeatureDefinition]:
        return iter(self._definitions)

    def __len__(self) -> int:
        return len(self._definitions)

    @property
    def definitions(self) -> tuple[SharedFeatureDefinition, ...]:
        return self._definitions

    def resolve(self, name: str) -> SharedFeatureDefinition:
        _require_non_empty(name, field_name="feature name")
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise FeatureCatalogError(f"unknown feature definition: {name}") from exc

    def get(self, name: str) -> SharedFeatureDefinition | None:
        return self._by_name.get(name)


@dataclass(frozen=True, slots=True, kw_only=True)
class FeaturePolicy:
    """Explicit operator allowlist for shared feature computation."""

    name: str
    version: str
    allowed_features: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_non_empty(self.name, field_name="feature policy name")
        _require_non_empty(self.version, field_name="feature policy version")
        object.__setattr__(
            self,
            "allowed_features",
            _normalize_names(self.allowed_features, field_name="allowed_features"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class BindingFeaturePlan:
    """Binding-specific feature availability and visibility evidence."""

    binding_id: str
    required_features: tuple[str, ...] = ()
    optional_features: tuple[str, ...] = ()
    enabled_features: tuple[str, ...] = ()
    disabled_required_features: tuple[str, ...] = ()
    disabled_optional_features: tuple[str, ...] = ()
    undefined_required_features: tuple[str, ...] = ()
    undefined_optional_features: tuple[str, ...] = ()
    statically_available: bool = True

    def __post_init__(self) -> None:
        _require_non_empty(self.binding_id, field_name="binding_id")
        for field_name in (
            "required_features",
            "optional_features",
            "enabled_features",
            "disabled_required_features",
            "disabled_optional_features",
            "undefined_required_features",
            "undefined_optional_features",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalize_names(getattr(self, field_name), field_name=field_name),
            )
        if set(self.required_features) & set(self.optional_features):
            raise ValueError("a feature cannot be both required and optional")
        required = set(self.required_features)
        optional = set(self.optional_features)
        enabled = set(self.enabled_features)
        disabled_required = set(self.disabled_required_features)
        disabled_optional = set(self.disabled_optional_features)
        undefined_required = set(self.undefined_required_features)
        undefined_optional = set(self.undefined_optional_features)
        if not enabled <= required | optional:
            raise ValueError("enabled binding features must be requested")
        _validate_partition(
            required,
            enabled & required,
            disabled_required,
            undefined_required,
            field_name="required binding features",
        )
        _validate_partition(
            optional,
            enabled & optional,
            disabled_optional,
            undefined_optional,
            field_name="optional binding features",
        )
        if not isinstance(self.statically_available, bool):
            raise TypeError("statically_available must be a bool")
        expected_available = not (disabled_required | undefined_required)
        if self.statically_available != expected_available:
            raise ValueError("binding static availability is inconsistent")


@dataclass(frozen=True, slots=True, kw_only=True)
class FeaturePlan:
    """Immutable deterministic demand and availability plan for one lane."""

    lane_id: str
    base_lane_revision: str
    feature_policy_name: str
    feature_policy_version: str
    requested_shared_features: tuple[str, ...]
    operator_allowed_features: tuple[str, ...]
    effective_shared_features: tuple[str, ...]
    disabled_features: tuple[str, ...]
    undefined_features: tuple[str, ...]
    feature_versions: Mapping[str, str]
    history_requirements: Mapping[str, Mapping[MarketSeriesKey, int]]
    bindings: Mapping[str, BindingFeaturePlan]
    feature_plan_fingerprint: str
    feature_config_fingerprints: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "lane_id",
            "base_lane_revision",
            "feature_policy_name",
            "feature_policy_version",
            "feature_plan_fingerprint",
        ):
            _require_non_empty(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "requested_shared_features",
            "operator_allowed_features",
            "effective_shared_features",
            "disabled_features",
            "undefined_features",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalize_names(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "feature_versions",
            _freeze_string_map(self.feature_versions, field_name="feature_versions"),
        )
        object.__setattr__(
            self,
            "feature_config_fingerprints",
            _freeze_string_map(
                self.feature_config_fingerprints,
                field_name="feature_config_fingerprints",
            ),
        )
        if not isinstance(self.history_requirements, Mapping):
            raise TypeError("history_requirements must be a mapping")
        history: dict[str, FrozenMapping[MarketSeriesKey, int]] = {}
        for name, requirements in self.history_requirements.items():
            _require_non_empty(name, field_name="history feature name")
            history[name] = _freeze_history_map(
                requirements,
                field_name=f"history_requirements[{name}]",
            )
        object.__setattr__(
            self,
            "history_requirements",
            FrozenMapping(dict(sorted(history.items()))),
        )
        if not isinstance(self.bindings, Mapping):
            raise TypeError("bindings must be a mapping")
        bindings: dict[str, BindingFeaturePlan] = {}
        for binding_id, binding in self.bindings.items():
            _require_non_empty(binding_id, field_name="feature binding ID")
            if not isinstance(binding, BindingFeaturePlan):
                raise TypeError("bindings must contain BindingFeaturePlan values")
            if binding_id != binding.binding_id:
                raise ValueError("feature binding map key must match binding_id")
            bindings[binding_id] = binding
        object.__setattr__(
            self, "bindings", FrozenMapping(dict(sorted(bindings.items())))
        )
        if not bindings:
            raise ValueError("feature plan must contain at least one binding")
        effective = set(self.effective_shared_features)
        requested = set(self.requested_shared_features)
        disabled = set(self.disabled_features)
        undefined = set(self.undefined_features)
        _validate_partition(
            requested,
            effective,
            disabled,
            undefined,
            field_name="feature plan features",
        )
        if undefined & set(self.operator_allowed_features):
            raise ValueError("undefined features must not be operator allowed")
        if set(self.feature_versions) != effective:
            raise ValueError("feature_versions must cover exactly effective features")
        if set(self.history_requirements) != effective:
            raise ValueError(
                "history_requirements must cover exactly effective features"
            )
        if not set(self.feature_config_fingerprints) <= effective:
            raise ValueError(
                "feature_config_fingerprints must contain only effective features"
            )
        if not set(self.effective_shared_features) <= set(
            self.requested_shared_features
        ):
            raise ValueError("effective features must be requested")
        if not set(self.effective_shared_features) <= set(
            self.operator_allowed_features
        ):
            raise ValueError("effective features must be operator allowed")
        requested_from_bindings: set[str] = set()
        effective_from_bindings: set[str] = set()
        for binding in bindings.values():
            required = set(binding.required_features)
            optional = set(binding.optional_features)
            requested_from_bindings.update(required | optional)
            enabled = set(binding.enabled_features)
            effective_from_bindings.update(enabled)
            expected_enabled = (required | optional) & effective
            expected_disabled_required = required & disabled
            expected_disabled_optional = optional & disabled
            expected_undefined_required = required & undefined
            expected_undefined_optional = optional & undefined
            if enabled != expected_enabled:
                raise ValueError("binding enabled features do not match plan")
            if set(binding.disabled_required_features) != expected_disabled_required:
                raise ValueError("binding disabled required features do not match plan")
            if set(binding.disabled_optional_features) != expected_disabled_optional:
                raise ValueError("binding disabled optional features do not match plan")
            if set(binding.undefined_required_features) != expected_undefined_required:
                raise ValueError(
                    "binding undefined required features do not match plan"
                )
            if set(binding.undefined_optional_features) != expected_undefined_optional:
                raise ValueError(
                    "binding undefined optional features do not match plan"
                )
        if requested_from_bindings != set(self.requested_shared_features):
            raise ValueError("requested_shared_features must match binding demand")
        if effective_from_bindings != effective:
            raise ValueError("effective_shared_features must match binding enablement")
        expected_fingerprint = _compute_feature_plan_fingerprint(self)
        if self.feature_plan_fingerprint != expected_fingerprint:
            raise ValueError(
                "feature_plan_fingerprint does not match normalized feature plan"
            )


def resolve_feature_history_requirements(
    definition: SharedFeatureDefinition,
    lane: ResolvedLanePlan,
    timeframe_grid: TimeframeGrid,
) -> FrozenMapping[MarketSeriesKey, int]:
    """Resolve one definition's exact canonical series lookbacks for a lane."""

    if not isinstance(definition, SharedFeatureDefinition):
        raise TypeError("definition must be a SharedFeatureDefinition")
    if not isinstance(lane, ResolvedLanePlan):
        raise TypeError("lane must be a ResolvedLanePlan")
    if not isinstance(timeframe_grid, TimeframeGrid):
        raise TypeError("timeframe_grid must be a TimeframeGrid")

    if definition.history_requirement_resolver is None:
        requirements = definition.history_requirements
    else:
        resolved_requirements = definition.history_requirement_resolver(lane)
        if isinstance(resolved_requirements, (str, bytes)) or not isinstance(
            resolved_requirements, Sequence
        ):
            raise TypeError(
                "history_requirement_resolver must return a sequence of "
                "FeatureHistoryRequirement values"
            )
        requirements = tuple(resolved_requirements)
        if any(
            not isinstance(item, FeatureHistoryRequirement) for item in requirements
        ):
            raise TypeError(
                "history_requirement_resolver must return only "
                "FeatureHistoryRequirement values"
            )

    resolved: dict[MarketSeriesKey, int] = {}
    for requirement in requirements:
        if requirement.source == "decision":
            timeframe = lane.decision_timeframe
        elif requirement.source == "trigger":
            timeframe = lane.trigger_timeframe
        else:
            assert requirement.timeframe is not None
            timeframe = requirement.timeframe
        timeframe_grid.duration(timeframe)
        key = MarketSeriesKey(
            asset=lane.asset,
            venue=lane.venue,
            instrument_id=lane.instrument_id,
            timeframe=timeframe,
        )
        resolved[key] = max(resolved.get(key, 0), requirement.bars)
    return _freeze_history_map(resolved, field_name="resolved feature history")


def resolve_feature_config_fingerprint(
    definition: SharedFeatureDefinition,
    lane: ResolvedLanePlan,
) -> str | None:
    """Resolve one optional lane-specific feature configuration identity."""

    if not isinstance(definition, SharedFeatureDefinition):
        raise TypeError("definition must be a SharedFeatureDefinition")
    if not isinstance(lane, ResolvedLanePlan):
        raise TypeError("lane must be a ResolvedLanePlan")
    if definition.config_fingerprint_resolver is None:
        return None
    return _require_non_empty(
        definition.config_fingerprint_resolver(lane),
        field_name="feature config fingerprint",
    )


def _feature_fingerprint_payload(
    *,
    lane_id: str,
    base_lane_revision: str,
    feature_policy_name: str,
    feature_policy_version: str,
    operator_allowed_features: Sequence[str],
    binding_plans: Mapping[str, BindingFeaturePlan],
    feature_versions: Mapping[str, str],
    effective: Sequence[str],
    disabled: Sequence[str],
    undefined: Sequence[str],
    histories: Mapping[str, Mapping[MarketSeriesKey, int]],
    feature_config_fingerprints: Mapping[str, str],
) -> Mapping[str, Any]:
    effective_features: list[dict[str, Any]] = []
    for name in sorted(effective):
        feature = {
            "name": name,
            "version": feature_versions[name],
            "history": [
                {
                    "asset": key.asset,
                    "venue": key.venue,
                    "instrument_id": key.instrument_id,
                    "timeframe": key.timeframe,
                    "bars": count,
                }
                for key, count in histories[name].items()
            ],
        }
        if name in feature_config_fingerprints:
            feature["config_fingerprint"] = feature_config_fingerprints[name]
        effective_features.append(feature)
    return {
        "lane_id": lane_id,
        "base_lane_revision": base_lane_revision,
        "policy": {
            "name": feature_policy_name,
            "version": feature_policy_version,
            "allowed_features": tuple(sorted(operator_allowed_features)),
        },
        "bindings": [
            {
                "binding_id": binding_id,
                "required_features": plan.required_features,
                "optional_features": plan.optional_features,
                "enabled_features": plan.enabled_features,
                "disabled_required_features": plan.disabled_required_features,
                "disabled_optional_features": plan.disabled_optional_features,
                "undefined_required_features": plan.undefined_required_features,
                "undefined_optional_features": plan.undefined_optional_features,
            }
            for binding_id, plan in sorted(binding_plans.items())
        ],
        "effective_features": effective_features,
        "disabled_features": tuple(sorted(disabled)),
        "undefined_features": tuple(sorted(undefined)),
    }


def _compute_feature_plan_fingerprint(plan: FeaturePlan) -> str:
    """Recompute the fingerprint from the plan's normalized semantic fields."""

    return sha256_fingerprint(
        _feature_fingerprint_payload(
            lane_id=plan.lane_id,
            base_lane_revision=plan.base_lane_revision,
            feature_policy_name=plan.feature_policy_name,
            feature_policy_version=plan.feature_policy_version,
            operator_allowed_features=plan.operator_allowed_features,
            binding_plans=plan.bindings,
            feature_versions=plan.feature_versions,
            effective=plan.effective_shared_features,
            disabled=plan.disabled_features,
            undefined=plan.undefined_features,
            histories=plan.history_requirements,
            feature_config_fingerprints=plan.feature_config_fingerprints,
        )
    )


def compile_feature_plan(
    lane: ResolvedLanePlan,
    catalog: FeatureCatalog,
    policy: FeaturePolicy,
    timeframe_grid: TimeframeGrid,
) -> FeaturePlan:
    """Compile binding demand and operator policy into one deterministic plan."""

    if not isinstance(lane, ResolvedLanePlan):
        raise TypeError("lane must be a ResolvedLanePlan")
    if not isinstance(catalog, FeatureCatalog):
        raise TypeError("catalog must be a FeatureCatalog")
    if not isinstance(policy, FeaturePolicy):
        raise TypeError("policy must be a FeaturePolicy")
    if not isinstance(timeframe_grid, TimeframeGrid):
        raise TypeError("timeframe_grid must be a TimeframeGrid")
    for name in policy.allowed_features:
        if catalog.get(name) is None:
            raise FeaturePlanError(f"feature policy allows unknown feature: {name}")

    requested = sorted(
        {
            requirement.name
            for binding in lane.bindings.values()
            for requirement in binding.effective_feature_requirements
        }
    )
    allowed = set(policy.allowed_features)
    catalog_names = {definition.name for definition in catalog}
    undefined = sorted(set(requested) - catalog_names)
    disabled = sorted((set(requested) & catalog_names) - allowed)
    effective = sorted(set(requested) & allowed & catalog_names)

    binding_plans: dict[str, BindingFeaturePlan] = {}
    for binding in lane.bindings.values():
        required = sorted(
            requirement.name
            for requirement in binding.effective_feature_requirements
            if requirement.required
        )
        optional = sorted(
            requirement.name
            for requirement in binding.effective_feature_requirements
            if not requirement.required
        )
        binding_plans[binding.binding_id] = BindingFeaturePlan(
            binding_id=binding.binding_id,
            required_features=tuple(required),
            optional_features=tuple(optional),
            enabled_features=tuple(
                name
                for name in sorted(set(required) | set(optional))
                if name in effective
            ),
            disabled_required_features=tuple(
                name for name in required if name in disabled
            ),
            disabled_optional_features=tuple(
                name for name in optional if name in disabled
            ),
            undefined_required_features=tuple(
                name for name in required if name in undefined
            ),
            undefined_optional_features=tuple(
                name for name in optional if name in undefined
            ),
            statically_available=not (
                any(name in disabled for name in required)
                or any(name in undefined for name in required)
            ),
        )

    histories = {
        name: resolve_feature_history_requirements(
            catalog.resolve(name),
            lane,
            timeframe_grid,
        )
        for name in effective
    }
    feature_versions = {name: catalog.resolve(name).version for name in effective}
    feature_config_fingerprints = {
        name: fingerprint
        for name in effective
        if (
            fingerprint := resolve_feature_config_fingerprint(
                catalog.resolve(name), lane
            )
        )
        is not None
    }
    fingerprint = sha256_fingerprint(
        _feature_fingerprint_payload(
            lane_id=lane.lane_id,
            base_lane_revision=lane.effective_lane_revision,
            feature_policy_name=policy.name,
            feature_policy_version=policy.version,
            operator_allowed_features=policy.allowed_features,
            binding_plans=binding_plans,
            feature_versions=feature_versions,
            effective=effective,
            disabled=disabled,
            undefined=undefined,
            histories=histories,
            feature_config_fingerprints=feature_config_fingerprints,
        )
    )
    return FeaturePlan(
        lane_id=lane.lane_id,
        base_lane_revision=lane.effective_lane_revision,
        feature_policy_name=policy.name,
        feature_policy_version=policy.version,
        requested_shared_features=tuple(requested),
        operator_allowed_features=policy.allowed_features,
        effective_shared_features=tuple(effective),
        disabled_features=tuple(disabled),
        undefined_features=tuple(undefined),
        feature_versions=feature_versions,
        history_requirements=histories,
        bindings=binding_plans,
        feature_plan_fingerprint=fingerprint,
        feature_config_fingerprints=feature_config_fingerprints,
    )


def validate_feature_plan_against_lane(
    feature_plan: FeaturePlan,
    lane: ResolvedLanePlan,
    feature_catalog: FeatureCatalog | None = None,
    timeframe_grid: TimeframeGrid | None = None,
) -> None:
    """Validate plan identity, demand, and optional catalog-owned semantics."""

    if not isinstance(feature_plan, FeaturePlan):
        raise TypeError("feature_plan must be a FeaturePlan")
    if not isinstance(lane, ResolvedLanePlan):
        raise TypeError("lane must be a ResolvedLanePlan")
    if (feature_catalog is None) != (timeframe_grid is None):
        raise TypeError("feature_catalog and timeframe_grid must be supplied together")
    if feature_plan.lane_id != lane.lane_id:
        raise FeaturePlanError("feature plan lane_id must match resolved lane")
    if feature_plan.base_lane_revision != lane.effective_lane_revision:
        raise FeaturePlanError(
            "feature plan base lane revision must match resolved lane"
        )

    resolved_bindings = {
        binding.binding_id: binding for binding in lane.bindings.values()
    }
    if set(feature_plan.bindings) != set(resolved_bindings):
        raise FeaturePlanError(
            "feature plan binding IDs must match resolved lane binding IDs"
        )
    for binding_id, resolved_binding in resolved_bindings.items():
        if not isinstance(resolved_binding, ResolvedModelBinding):
            raise TypeError(
                "resolved lane bindings must be ResolvedModelBinding values"
            )
        binding_plan = feature_plan.bindings[binding_id]
        required = tuple(
            sorted(
                requirement.name
                for requirement in resolved_binding.effective_feature_requirements
                if requirement.required
            )
        )
        optional = tuple(
            sorted(
                requirement.name
                for requirement in resolved_binding.effective_feature_requirements
                if not requirement.required
            )
        )
        if binding_plan.required_features != required:
            raise FeaturePlanError(
                f"feature plan required demand mismatch for binding {binding_id}"
            )
        if binding_plan.optional_features != optional:
            raise FeaturePlanError(
                f"feature plan optional demand mismatch for binding {binding_id}"
            )

    if feature_catalog is None or timeframe_grid is None:
        return

    expected_config_fingerprints: dict[str, str] = {}
    for name in feature_plan.effective_shared_features:
        definition = feature_catalog.resolve(name)
        if feature_plan.feature_versions[name] != definition.version:
            raise FeaturePlanError(
                f"feature plan version mismatch for {name}: "
                f"{feature_plan.feature_versions[name]} != {definition.version}"
            )
        expected_history = resolve_feature_history_requirements(
            definition, lane, timeframe_grid
        )
        if dict(feature_plan.history_requirements[name]) != dict(expected_history):
            raise FeaturePlanError(f"feature plan history mismatch for {name}")
        config_fingerprint = resolve_feature_config_fingerprint(definition, lane)
        if config_fingerprint is not None:
            expected_config_fingerprints[name] = config_fingerprint

    if dict(feature_plan.feature_config_fingerprints) != expected_config_fingerprints:
        raise FeaturePlanError("feature plan configuration fingerprint mismatch")
    expected_fingerprint = _compute_feature_plan_fingerprint(feature_plan)
    if feature_plan.feature_plan_fingerprint != expected_fingerprint:
        raise FeaturePlanError("feature_plan_fingerprint does not match plan")


def _normalize_feature_plans(
    feature_plans: Mapping[str, FeaturePlan] | Iterable[FeaturePlan],
) -> tuple[FeaturePlan, ...]:
    if isinstance(feature_plans, Mapping):
        entries = tuple(feature_plans.items())
        for lane_id, plan in entries:
            if not isinstance(plan, FeaturePlan):
                raise TypeError("feature_plans must contain FeaturePlan values")
            if lane_id != plan.lane_id:
                raise ValueError("feature plan mapping key must match lane_id")
        plans = tuple(plan for _, plan in entries)
    else:
        plans = tuple(feature_plans)
    if any(not isinstance(plan, FeaturePlan) for plan in plans):
        raise TypeError("feature_plans must contain FeaturePlan values")
    by_lane = {plan.lane_id: plan for plan in plans}
    if len(by_lane) != len(plans):
        raise ValueError("feature_plans must contain unique lane IDs")
    return tuple(sorted(plans, key=lambda plan: plan.lane_id))


def compile_feature_bar_store_capacities(
    resolved_decision_plan: ResolvedDecisionPlan,
    feature_plans: Mapping[str, FeaturePlan] | Iterable[FeaturePlan],
    feature_catalog: FeatureCatalog,
    timeframe_grid: TimeframeGrid,
) -> FrozenMapping[MarketSeriesKey, int]:
    """Compile only effective feature lookbacks as shared max capacities."""

    if not isinstance(resolved_decision_plan, ResolvedDecisionPlan):
        raise TypeError("resolved_decision_plan must be a ResolvedDecisionPlan")
    if not isinstance(feature_catalog, FeatureCatalog):
        raise TypeError("feature_catalog must be a FeatureCatalog")
    if not isinstance(timeframe_grid, TimeframeGrid):
        raise TypeError("timeframe_grid must be a TimeframeGrid")
    lane_by_id = {lane.lane_id: lane for lane in resolved_decision_plan.lanes}
    plans = _normalize_feature_plans(feature_plans)
    plan_lane_ids = {plan.lane_id for plan in plans}
    expected_lane_ids = set(lane_by_id)
    if plan_lane_ids != expected_lane_ids:
        missing = sorted(expected_lane_ids - plan_lane_ids)
        extra = sorted(plan_lane_ids - expected_lane_ids)
        raise FeaturePlanError(
            "feature plans must contain exactly one current plan per resolved lane; "
            f"missing={missing}, extra={extra}"
        )
    capacities: dict[MarketSeriesKey, int] = {}
    for plan in plans:
        try:
            lane = lane_by_id[plan.lane_id]
        except KeyError as exc:
            raise FeaturePlanError(
                f"feature plan references unknown lane: {plan.lane_id}"
            ) from exc
        validate_feature_plan_against_lane(
            plan,
            lane,
            feature_catalog,
            timeframe_grid,
        )
        for name in plan.effective_shared_features:
            definition = feature_catalog.resolve(name)
            if plan.feature_versions[name] != definition.version:
                raise FeaturePlanError(
                    f"feature plan version mismatch for {name}: "
                    f"{plan.feature_versions[name]} != {definition.version}"
                )
            expected = resolve_feature_history_requirements(
                definition,
                lane,
                timeframe_grid,
            )
            if dict(expected) != dict(plan.history_requirements[name]):
                raise FeaturePlanError(f"feature plan history mismatch for {name}")
            for key, count in expected.items():
                capacities[key] = max(capacities.get(key, 0), count)
    return _freeze_history_map(capacities, field_name="feature capacities")


def merge_bar_store_capacities(
    base_capacities: Mapping[MarketSeriesKey, int],
    feature_capacities: Mapping[MarketSeriesKey, int],
) -> FrozenMapping[MarketSeriesKey, int]:
    """Merge D3 and D4 capacities by maximum, never by summation."""

    base = _freeze_history_map(base_capacities, field_name="base capacities")
    feature = _freeze_history_map(feature_capacities, field_name="feature capacities")
    merged: dict[MarketSeriesKey, int] = dict(base)
    for key, count in feature.items():
        merged[key] = max(merged.get(key, 0), count)
    return _freeze_history_map(merged, field_name="merged capacities")


__all__ = [
    "BindingFeaturePlan",
    "FeatureCatalog",
    "FeatureCatalogError",
    "FeatureConfigFingerprintResolver",
    "FeatureError",
    "FeatureHistoryRequirement",
    "FeatureHistoryRequirementResolver",
    "FeaturePlan",
    "FeaturePlanError",
    "FeaturePolicy",
    "SharedFeatureDefinition",
    "compile_feature_bar_store_capacities",
    "compile_feature_plan",
    "merge_bar_store_capacities",
    "resolve_feature_config_fingerprint",
    "resolve_feature_history_requirements",
    "validate_feature_plan_against_lane",
]
