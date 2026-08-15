"""Synchronous causal shared-feature computation for decision_app D4."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from itertools import pairwise
from typing import Any

from apps.decision_app.domain.market_state import (
    BarStore,
    TimeframeGrid,
    validate_canonical_bar_geometry,
)
from apps.decision_app.domain.view import LaneMarketView
from apps.decision_app.features.planning import (
    FeatureCatalog,
    FeaturePlan,
    SharedFeatureDefinition,
    resolve_feature_history_requirements,
    validate_feature_plan_against_lane,
)
from apps.decision_app.planning.planner import ResolvedLanePlan
from libs.contracts.decision import (
    CausalBarView,
    FeatureSnapshot,
    FrozenMapping,
    deep_freeze,
    require_utc,
)


class FeatureComputationError(ValueError):
    """Raised when a defined feature cannot produce a valid semantic value."""

    def __init__(self, feature_name: str, feature_version: str, message: str) -> None:
        self.feature_name = feature_name
        self.feature_version = feature_version
        super().__init__(f"{feature_name}@{feature_version}: {message}")


def _require_non_empty(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _normalize_history_views(
    value: Mapping[str, Sequence[CausalBarView]],
    *,
    market_as_of: datetime,
) -> FrozenMapping[str, tuple[CausalBarView, ...]]:
    if not isinstance(value, Mapping):
        raise TypeError("histories must be a mapping")
    normalized: dict[str, tuple[CausalBarView, ...]] = {}
    for timeframe, bars in value.items():
        _require_non_empty(timeframe, field_name="history timeframe")
        if isinstance(bars, (str, bytes)) or not isinstance(bars, Sequence):
            raise TypeError("history values must be bar sequences")
        sequence = tuple(bars)
        if any(not isinstance(bar, CausalBarView) for bar in sequence):
            raise TypeError("histories must contain CausalBarView values")
        if any(not bar.closed for bar in sequence):
            raise ValueError("feature histories must contain closed canonical bars")
        if any(bar.timeframe != timeframe for bar in sequence):
            raise ValueError("history bar timeframe must match its mapping key")
        if any(bar.market_as_of > market_as_of for bar in sequence):
            raise ValueError("feature history cannot contain future bars")
        for previous, current in pairwise(sequence):
            if current.bar_open_at <= previous.bar_open_at:
                raise ValueError("feature history must be chronologically ordered")
            if current.bar_open_at < previous.bar_close_at:
                raise ValueError("feature history bars must not overlap")
            if current.bar_open_at != previous.bar_close_at:
                raise ValueError("feature history must be contiguous")
        normalized[timeframe] = sequence
    return FrozenMapping(dict(sorted(normalized.items())))


def _normalize_cutoffs(
    value: Mapping[str, datetime],
    histories: Mapping[str, Sequence[CausalBarView]],
    *,
    market_as_of: datetime,
) -> FrozenMapping[str, datetime]:
    if not isinstance(value, Mapping):
        raise TypeError("observed_cutoffs must be a mapping")
    normalized: dict[str, datetime] = {}
    for timeframe, cutoff in value.items():
        _require_non_empty(timeframe, field_name="observed cutoff timeframe")
        require_utc(cutoff, field_name="observed cutoff")
        if cutoff > market_as_of:
            raise ValueError("observed cutoff cannot be after market_as_of")
        bars = histories.get(timeframe)
        if not bars:
            raise ValueError("observed cutoff requires a non-empty history")
        if cutoff != bars[-1].market_as_of:
            raise ValueError("observed cutoff must equal the final history cutoff")
        normalized[timeframe] = cutoff
    if set(normalized) != set(histories):
        raise ValueError("observed_cutoffs must cover exactly supplied histories")
    return FrozenMapping(dict(sorted(normalized.items())))


@dataclass(frozen=True, slots=True, kw_only=True)
class SharedFeatureContext:
    """Exact immutable causal inputs supplied to one feature calculator."""

    lane_id: str
    asset: str
    venue: str
    instrument_id: str
    market_as_of: datetime
    decision_timeframe: str
    trigger_timeframe: str
    decision_bar: CausalBarView
    decision_bar_closed: bool
    histories: Mapping[str, Sequence[CausalBarView]] = field(default_factory=dict)
    observed_cutoffs: Mapping[str, datetime] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "lane_id",
            "asset",
            "venue",
            "instrument_id",
            "decision_timeframe",
            "trigger_timeframe",
        ):
            _require_non_empty(getattr(self, field_name), field_name=field_name)
        require_utc(self.market_as_of, field_name="market_as_of")
        if not isinstance(self.decision_bar, CausalBarView):
            raise TypeError("decision_bar must be a CausalBarView")
        if self.decision_bar.timeframe != self.decision_timeframe:
            raise ValueError("decision_bar timeframe must match context")
        if self.decision_bar.market_as_of != self.market_as_of:
            raise ValueError("decision_bar market_as_of must match context")
        if not isinstance(self.decision_bar_closed, bool):
            raise TypeError("decision_bar_closed must be a bool")
        if self.decision_bar.closed != self.decision_bar_closed:
            raise ValueError("decision_bar_closed must match decision_bar.closed")
        histories = _normalize_history_views(
            self.histories,
            market_as_of=self.market_as_of,
        )
        object.__setattr__(self, "histories", histories)
        object.__setattr__(
            self,
            "observed_cutoffs",
            _normalize_cutoffs(
                self.observed_cutoffs,
                histories,
                market_as_of=self.market_as_of,
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class BindingFeatureResolution:
    """Binding-local feature visibility and availability evidence."""

    binding_id: str
    available: bool
    features: Mapping[str, FeatureSnapshot] = field(default_factory=dict)
    missing_required_features: tuple[str, ...] = ()
    missing_optional_features: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_non_empty(self.binding_id, field_name="binding_id")
        if not isinstance(self.available, bool):
            raise TypeError("available must be a bool")
        normalized: dict[str, FeatureSnapshot] = {}
        if not isinstance(self.features, Mapping):
            raise TypeError("features must be a mapping")
        for name, snapshot in self.features.items():
            _require_non_empty(name, field_name="feature name")
            if not isinstance(snapshot, FeatureSnapshot):
                raise TypeError("features must contain FeatureSnapshot values")
            if name != snapshot.name:
                raise ValueError("feature mapping key must match snapshot name")
            normalized[name] = snapshot
        object.__setattr__(
            self,
            "features",
            FrozenMapping(dict(sorted(normalized.items()))),
        )
        for field_name in ("missing_required_features", "missing_optional_features"):
            values = tuple(getattr(self, field_name))
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise TypeError(f"{field_name} must contain non-empty strings")
            if len(set(values)) != len(values):
                raise ValueError(f"{field_name} must not contain duplicates")
            object.__setattr__(self, field_name, tuple(sorted(values)))
        missing_required = set(self.missing_required_features)
        missing_optional = set(self.missing_optional_features)
        present = set(self.features)
        if missing_required & missing_optional:
            raise ValueError("a feature cannot be both required and optional missing")
        if present & (missing_required | missing_optional):
            raise ValueError("present features cannot also be missing")
        expected_available = not missing_required
        if self.available != expected_available:
            raise ValueError(
                "binding availability is inconsistent with missing features"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class FeatureResolution:
    """One lane/as-of shared computation and binding-facing resolution."""

    lane_id: str
    base_lane_revision: str
    feature_plan_fingerprint: str
    market_as_of: datetime
    shared_features: Mapping[str, FeatureSnapshot] = field(default_factory=dict)
    unavailable_features: Mapping[str, str] = field(default_factory=dict)
    bindings: Mapping[str, BindingFeatureResolution] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "lane_id",
            "base_lane_revision",
            "feature_plan_fingerprint",
        ):
            _require_non_empty(getattr(self, field_name), field_name=field_name)
        require_utc(self.market_as_of, field_name="market_as_of")
        shared: dict[str, FeatureSnapshot] = {}
        if not isinstance(self.shared_features, Mapping):
            raise TypeError("shared_features must be a mapping")
        for name, snapshot in self.shared_features.items():
            _require_non_empty(name, field_name="shared feature name")
            if not isinstance(snapshot, FeatureSnapshot):
                raise TypeError("shared_features must contain FeatureSnapshot values")
            if name != snapshot.name:
                raise ValueError("shared feature key must match snapshot name")
            if snapshot.market_as_of != self.market_as_of:
                raise ValueError("feature snapshot market_as_of must match resolution")
            shared[name] = snapshot
        object.__setattr__(
            self,
            "shared_features",
            FrozenMapping(dict(sorted(shared.items()))),
        )
        if not isinstance(self.unavailable_features, Mapping):
            raise TypeError("unavailable_features must be a mapping")
        unavailable: dict[str, str] = {}
        for name, reason in self.unavailable_features.items():
            _require_non_empty(name, field_name="unavailable feature name")
            unavailable[name] = _require_non_empty(
                reason,
                field_name=f"unavailable_features[{name}]",
            )
        object.__setattr__(
            self,
            "unavailable_features",
            FrozenMapping(dict(sorted(unavailable.items()))),
        )
        if set(shared) & set(unavailable):
            raise ValueError("a feature cannot be both shared and unavailable")
        if not isinstance(self.bindings, Mapping):
            raise TypeError("bindings must be a mapping")
        bindings: dict[str, BindingFeatureResolution] = {}
        for binding_id, binding in self.bindings.items():
            if not isinstance(binding, BindingFeatureResolution):
                raise TypeError("bindings must contain BindingFeatureResolution values")
            if binding_id != binding.binding_id:
                raise ValueError("binding resolution key must match binding_id")
            if any(name not in self.shared_features for name in binding.features):
                raise ValueError("binding feature visibility must use shared snapshots")
            for name, snapshot in binding.features.items():
                if snapshot != self.shared_features[name]:
                    raise ValueError(
                        "binding feature visibility must reuse the shared snapshot"
                    )
            missing = set(binding.missing_required_features) | set(
                binding.missing_optional_features
            )
            if not missing <= set(self.unavailable_features):
                raise ValueError(
                    "binding missing features must be represented as unavailable"
                )
            bindings[binding_id] = binding
        object.__setattr__(
            self, "bindings", FrozenMapping(dict(sorted(bindings.items())))
        )


class FeatureEngine:
    """Compute effective shared features once from a causal lane view."""

    def __init__(
        self,
        feature_catalog: FeatureCatalog,
        bar_store: BarStore,
        timeframe_grid: TimeframeGrid,
    ) -> None:
        if not isinstance(feature_catalog, FeatureCatalog):
            raise TypeError("feature_catalog must be a FeatureCatalog")
        if not isinstance(bar_store, BarStore):
            raise TypeError("bar_store must be a BarStore")
        if not isinstance(timeframe_grid, TimeframeGrid):
            raise TypeError("timeframe_grid must be a TimeframeGrid")
        self._feature_catalog = feature_catalog
        self._bar_store = bar_store
        self._timeframe_grid = timeframe_grid

    def compute(
        self,
        feature_plan: FeaturePlan,
        resolved_lane: ResolvedLanePlan,
        lane_market_view: LaneMarketView,
    ) -> FeatureResolution:
        """Compute one deterministic lane/as-of feature resolution."""

        if not isinstance(feature_plan, FeaturePlan):
            raise TypeError("feature_plan must be a FeaturePlan")
        if not isinstance(resolved_lane, ResolvedLanePlan):
            raise TypeError("resolved_lane must be a ResolvedLanePlan")
        if not isinstance(lane_market_view, LaneMarketView):
            raise TypeError("lane_market_view must be a LaneMarketView")
        self._validate_inputs(feature_plan, resolved_lane, lane_market_view)

        unavailable: dict[str, str] = {
            name: "disabled_by_policy" for name in feature_plan.disabled_features
        }
        unavailable.update(
            {
                name: "undefined_feature_definition"
                for name in feature_plan.undefined_features
            }
        )
        shared: dict[str, FeatureSnapshot] = {}
        for name in feature_plan.effective_shared_features:
            definition = self._feature_catalog.resolve(name)
            context_or_reason = self._build_feature_context(
                definition,
                feature_plan,
                lane_market_view,
            )
            if isinstance(context_or_reason, str):
                unavailable[name] = context_or_reason
                continue
            try:
                value = definition.calculator(context_or_reason)
                value = deep_freeze(value)
                snapshot = FeatureSnapshot(
                    name=definition.name,
                    version=definition.version,
                    market_as_of=lane_market_view.market_as_of,
                    value=value,
                    provenance=self._provenance(
                        definition,
                        feature_plan,
                        context_or_reason,
                    ),
                )
            except Exception as exc:
                raise FeatureComputationError(
                    definition.name,
                    definition.version,
                    f"calculator failed or returned an invalid value: {exc}",
                ) from exc
            shared[name] = snapshot

        binding_resolutions: dict[str, BindingFeatureResolution] = {}
        for binding_id, binding_plan in feature_plan.bindings.items():
            visible = {
                name: shared[name]
                for name in binding_plan.enabled_features
                if name in shared
            }
            missing_required = tuple(
                name for name in binding_plan.required_features if name not in visible
            )
            missing_optional = tuple(
                name for name in binding_plan.optional_features if name not in visible
            )
            binding_resolutions[binding_id] = BindingFeatureResolution(
                binding_id=binding_id,
                available=not missing_required,
                features=visible,
                missing_required_features=missing_required,
                missing_optional_features=missing_optional,
            )

        return FeatureResolution(
            lane_id=feature_plan.lane_id,
            base_lane_revision=feature_plan.base_lane_revision,
            feature_plan_fingerprint=feature_plan.feature_plan_fingerprint,
            market_as_of=lane_market_view.market_as_of,
            shared_features=shared,
            unavailable_features=unavailable,
            bindings=binding_resolutions,
        )

    def _validate_inputs(
        self,
        feature_plan: FeaturePlan,
        resolved_lane: ResolvedLanePlan,
        lane_market_view: LaneMarketView,
    ) -> None:
        if feature_plan.lane_id != resolved_lane.lane_id:
            raise ValueError("feature_plan lane_id must match resolved lane")
        if feature_plan.base_lane_revision != resolved_lane.effective_lane_revision:
            raise ValueError("feature_plan base revision must match resolved lane")
        for field_name in (
            "lane_id",
            "asset",
            "venue",
            "instrument_id",
            "decision_timeframe",
            "trigger_timeframe",
            "trigger_mode",
        ):
            if getattr(lane_market_view, field_name) != getattr(
                resolved_lane, field_name
            ):
                raise ValueError(
                    f"lane market view {field_name} must match resolved lane"
                )
        validate_feature_plan_against_lane(feature_plan, resolved_lane)
        for name in feature_plan.effective_shared_features:
            definition = self._feature_catalog.resolve(name)
            if feature_plan.feature_versions[name] != definition.version:
                raise ValueError(
                    f"feature plan version does not match catalog for {name}"
                )
            expected_history = resolve_feature_history_requirements(
                definition,
                resolved_lane,
                self._timeframe_grid,
            )
            if dict(feature_plan.history_requirements[name]) != dict(expected_history):
                raise ValueError(
                    f"feature plan history does not match catalog for {name}"
                )
        require_utc(lane_market_view.market_as_of, field_name="market_as_of")

    def _build_feature_context(
        self,
        definition: SharedFeatureDefinition,
        feature_plan: FeaturePlan,
        lane_market_view: LaneMarketView,
    ) -> SharedFeatureContext | str:
        histories: dict[str, tuple[CausalBarView, ...]] = {}
        observed_cutoffs: dict[str, datetime] = {}
        for key, count in feature_plan.history_requirements[definition.name].items():
            expected_cutoff = self._timeframe_grid.expected_closed_cutoff(
                key.timeframe,
                lane_market_view.market_as_of,
            )
            try:
                bars = self._bar_store.bars_at(key, expected_cutoff, limit=count)
            except KeyError:
                return f"series_not_registered:{key.timeframe}"
            for bar in bars:
                validate_canonical_bar_geometry(key, bar, self._timeframe_grid)
            if len(bars) < count:
                return f"insufficient_history:{key.timeframe}"
            if bars[-1].market_as_of != expected_cutoff:
                return f"missing_cutoff:{key.timeframe}"
            if any(
                current.bar_open_at != previous.bar_close_at
                for previous, current in pairwise(bars)
            ):
                return f"history_gap:{key.timeframe}"
            histories[key.timeframe] = bars
            observed_cutoffs[key.timeframe] = bars[-1].market_as_of

        return SharedFeatureContext(
            lane_id=lane_market_view.lane_id,
            asset=lane_market_view.asset,
            venue=lane_market_view.venue,
            instrument_id=lane_market_view.instrument_id,
            market_as_of=lane_market_view.market_as_of,
            decision_timeframe=lane_market_view.decision_timeframe,
            trigger_timeframe=lane_market_view.trigger_timeframe,
            decision_bar=lane_market_view.decision_bar,
            decision_bar_closed=lane_market_view.decision_bar_closed,
            histories=histories,
            observed_cutoffs=observed_cutoffs,
        )

    @staticmethod
    def _provenance(
        definition: SharedFeatureDefinition,
        feature_plan: FeaturePlan,
        context: SharedFeatureContext,
    ) -> Mapping[str, Any]:
        return {
            "feature_name": definition.name,
            "feature_version": definition.version,
            "feature_plan_fingerprint": feature_plan.feature_plan_fingerprint,
            "history_cutoffs": {
                timeframe: cutoff
                for timeframe, cutoff in context.observed_cutoffs.items()
            },
            "history_counts": {
                timeframe: len(bars) for timeframe, bars in context.histories.items()
            },
            "projected_decision_bar": not context.decision_bar_closed,
        }


__all__ = [
    "BindingFeatureResolution",
    "FeatureComputationError",
    "FeatureEngine",
    "FeatureResolution",
    "SharedFeatureContext",
]
