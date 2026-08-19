"""D9A bounded startup capture and publication-suppressed reconstruction.

This module owns the startup boundary only.  It captures a canonical input
tail, warms from the read-only durable candle source, reconstructs state via
the existing D6 runtime, and returns evidence for the future D9B reader.  It
does not read continuously, publish signals, or own lifecycle workers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from itertools import pairwise
from typing import Any, Literal

from apps.decision_app.data.resolver import (
    DataPlan,
    DataPolicy,
    DataResolver,
    DataSourceCatalog,
    compile_data_plan,
)
from apps.decision_app.domain.contracts import (
    InputReadCursor,
    LaneCommitWatermark,
    PriceRelayPlan,
)
from apps.decision_app.domain.identity import lane_execution_identity
from apps.decision_app.domain.market_state import (
    BarStore,
    MarketSeriesKey,
    TimeframeGrid,
    compile_bar_store_capacities,
    validate_canonical_bar_geometry,
)
from apps.decision_app.domain.state import BindingRuntimeState, LaneExecutionIdentity
from apps.decision_app.domain.view import (
    DecisionViewBuilder,
    LaneMarketView,
    MarketViewNotReadyError,
)
from apps.decision_app.features.engine import FeatureEngine
from apps.decision_app.features.planning import (
    FeatureCatalog,
    FeaturePlan,
    FeaturePolicy,
    compile_feature_bar_store_capacities,
    compile_feature_plan,
    merge_bar_store_capacities,
)
from apps.decision_app.planning.planner import (
    ResolvedDecisionPlan,
    ResolvedLanePlan,
    compile_decision_plan,
)
from apps.decision_app.planning.readiness import (
    LaneMarketRequirements,
    compile_lane_causal_history_requirements,
    compile_lane_market_requirements,
)
from apps.decision_app.runtime.models import ModelRuntime, RewarmError, RewarmStep
from apps.decision_app.runtime.plugins import (
    RuntimePluginCatalog,
    StateInitializationRequirement,
)
from apps.decision_app.runtime.policy import (
    PASSTHROUGH_V1,
    PRIORITY_V1,
    DecisionPolicyCatalog,
)
from apps.decision_app.settings import DecisionConfig
from apps.decision_app.storage.checkpoints import (
    CheckpointSaveResult,
    InMemoryCheckpointRepository,
    LaneStateCheckpoint,
)
from apps.decision_app.storage.market_history import CanonicalMarketHistoryRepository
from apps.decision_app.storage.shadow_progress import (
    InMemoryLaneEffectProgressRepository,
    LaneEffectProgress,
)
from apps.decision_app.transport.ingestion import (
    CanonicalMarketEvent,
    canonical_ingestion_stream_key,
    parse_canonical_ingestion_event,
)
from apps.decision_app.transport.price_relay import (
    compile_price_relay_plans,
    plan_series_key,
)
from libs.common.signal_authority import SignalAuthorityStore, SignalRouteAuthority
from libs.contracts.decision import FrozenMapping, deep_freeze, require_utc


class StartupError(ValueError):
    """Base D9A startup/reconstruction failure."""


class StartupContractError(StartupError):
    """Raised for global configuration or canonical contract corruption."""


class StartupLaneError(StartupError):
    """Raised when one lane cannot reconstruct safely."""


StartupStatus = Literal["STARTUP_READY", "STARTUP_BLOCKED"]
LaneStartupStatus = Literal[
    "STARTUP_READY", "INACTIVE", "WARMING", "INVALID", "BLOCKED"
]


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be non-empty text")
    return value


def _save_result_value(value: object) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def _sorted_keys(values: Sequence[MarketSeriesKey]) -> tuple[MarketSeriesKey, ...]:
    return tuple(
        sorted(
            values,
            key=lambda item: (
                item.asset,
                item.venue,
                item.instrument_id,
                item.timeframe,
            ),
        )
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class SeriesStartupPosition:
    """Original stream tail and durable cutoff captured before reconstruction."""

    series_key: MarketSeriesKey
    stream_key: str
    captured_tail_id: str | None
    captured_tail_market_as_of: datetime | None
    db_latest_market_as_of: datetime | None
    warm_cutoff: datetime | None

    def __post_init__(self) -> None:
        if not isinstance(self.series_key, MarketSeriesKey):
            raise TypeError("series_key must be MarketSeriesKey")
        if self.stream_key != canonical_ingestion_stream_key(self.series_key):
            raise ValueError("stream_key must match series_key")
        if self.captured_tail_id is not None:
            _text(self.captured_tail_id, "captured_tail_id")
        for field_name in (
            "captured_tail_market_as_of",
            "db_latest_market_as_of",
            "warm_cutoff",
        ):
            value = getattr(self, field_name)
            if value is not None:
                require_utc(value, field_name=field_name)
        if (
            self.db_latest_market_as_of is not None
            and self.captured_tail_market_as_of is not None
            and self.db_latest_market_as_of < self.captured_tail_market_as_of
        ):
            raise StartupContractError(
                "canonical DB cutoff is older than captured ingestion stream tail"
            )
        expected_warm = self.db_latest_market_as_of or self.captured_tail_market_as_of
        if self.warm_cutoff != expected_warm:
            raise ValueError("warm_cutoff must be the durable cutoff or stream tail")


@dataclass(frozen=True, slots=True, kw_only=True)
class LaneStartupEvidence:
    """Bounded lane-specific startup status and reconstruction evidence."""

    lane_id: str
    status: LaneStartupStatus
    resume_cutoff: datetime | None = None
    state_inception_at: datetime | None = None
    checkpoint_loaded: bool = False
    checkpoint_save_result: str | None = None
    replay_step_count: int = 0
    reason: str | None = None

    def __post_init__(self) -> None:
        _text(self.lane_id, "lane_id")
        if self.status not in {
            "STARTUP_READY",
            "INACTIVE",
            "WARMING",
            "INVALID",
            "BLOCKED",
        }:
            raise ValueError("unsupported lane startup status")
        for field_name in ("resume_cutoff", "state_inception_at"):
            value = getattr(self, field_name)
            if value is not None:
                require_utc(value, field_name=field_name)
        if (
            isinstance(self.replay_step_count, bool)
            or not isinstance(self.replay_step_count, int)
            or self.replay_step_count < 0
        ):
            raise ValueError("replay_step_count must be a non-negative integer")
        if self.reason is not None:
            _text(self.reason, "lane startup reason")


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionStartupSnapshot:
    """Immutable bounded evidence returned by the D9A startup boundary."""

    status: StartupStatus
    configured_lane_ids: tuple[str, ...]
    active_manifest_assets: tuple[str, ...]
    series_positions: Mapping[MarketSeriesKey, SeriesStartupPosition]
    input_cursors: Mapping[str, InputReadCursor]
    lane_watermarks: Mapping[str, LaneCommitWatermark]
    lane_evidence: Mapping[str, LaneStartupEvidence]
    reconstruction_evidence: Mapping[str, Mapping[str, Any]]
    no_publication: bool = True
    authority_records: Mapping[str, SignalRouteAuthority] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in {"STARTUP_READY", "STARTUP_BLOCKED"}:
            raise ValueError("unsupported startup status")
        lane_ids = tuple(
            sorted(_text(item, "lane_id") for item in self.configured_lane_ids)
        )
        if len(set(lane_ids)) != len(lane_ids):
            raise ValueError("configured lane IDs must be unique")
        if not isinstance(self.no_publication, bool) or not self.no_publication:
            raise ValueError("D9A startup evidence must be publication-free")
        positions: dict[MarketSeriesKey, SeriesStartupPosition] = {}
        for key, position in self.series_positions.items():
            if not isinstance(key, MarketSeriesKey) or not isinstance(
                position, SeriesStartupPosition
            ):
                raise TypeError("series_positions must contain typed positions")
            if key != position.series_key:
                raise ValueError("series position key must match series_key")
            positions[key] = position
        cursors: dict[str, InputReadCursor] = {}
        for stream_key, cursor in self.input_cursors.items():
            if stream_key != cursor.stream_key:
                raise ValueError("cursor map key must match stream_key")
            cursors[stream_key] = cursor
        watermarks: dict[str, LaneCommitWatermark] = {}
        for lane_id, watermark in self.lane_watermarks.items():
            if lane_id != watermark.lane_id:
                raise ValueError("watermark map key must match lane_id")
            if watermark.last_disposition not in {
                None,
                "shadow",
                "published",
                "no_signal",
            }:
                raise ValueError("unsupported startup watermark disposition")
            watermarks[lane_id] = watermark
        evidence: dict[str, LaneStartupEvidence] = {}
        for lane_id, item in self.lane_evidence.items():
            if lane_id != item.lane_id:
                raise ValueError("lane evidence map key must match lane_id")
            evidence[lane_id] = item
        authorities: dict[str, SignalRouteAuthority] = {}
        for route, record in self.authority_records.items():
            if not isinstance(route, str) or not isinstance(
                record, SignalRouteAuthority
            ):
                raise TypeError("authority_records must contain typed records")
            if route != record.route:
                raise ValueError("authority record map key must match route")
            authorities[route] = record
        object.__setattr__(self, "configured_lane_ids", lane_ids)
        object.__setattr__(
            self, "active_manifest_assets", tuple(sorted(self.active_manifest_assets))
        )
        object.__setattr__(self, "series_positions", FrozenMapping(positions))
        object.__setattr__(self, "input_cursors", FrozenMapping(cursors))
        object.__setattr__(self, "lane_watermarks", FrozenMapping(watermarks))
        object.__setattr__(self, "lane_evidence", FrozenMapping(evidence))
        object.__setattr__(
            self,
            "authority_records",
            FrozenMapping(dict(sorted(authorities.items()))),
        )
        object.__setattr__(
            self,
            "reconstruction_evidence",
            FrozenMapping(
                {
                    key: deep_freeze(value)
                    for key, value in sorted(self.reconstruction_evidence.items())
                }
            ),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionStartupResult:
    """Runtime owners plus immutable startup evidence for D9B."""

    snapshot: DecisionStartupSnapshot
    bar_store: BarStore
    runtimes: Mapping[str, ModelRuntime]
    decision_plan: ResolvedDecisionPlan
    feature_plans: Mapping[str, FeaturePlan]
    data_plans: Mapping[str, DataPlan]
    lane_requirements: Mapping[str, LaneMarketRequirements]
    lane_catchup_cutoffs: Mapping[str, tuple[datetime, ...]] = field(
        default_factory=dict
    )
    lane_catchup_stores: Mapping[str, BarStore] = field(default_factory=dict)
    relay_plans: tuple[PriceRelayPlan, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, DecisionStartupSnapshot):
            raise TypeError("snapshot must be DecisionStartupSnapshot")
        if not isinstance(self.bar_store, BarStore):
            raise TypeError("bar_store must be BarStore")
        if not isinstance(self.runtimes, Mapping):
            raise TypeError("runtimes must be a mapping")
        if not isinstance(self.decision_plan, ResolvedDecisionPlan):
            raise TypeError("decision_plan must be ResolvedDecisionPlan")
        if any(not isinstance(plan, PriceRelayPlan) for plan in self.relay_plans):
            raise TypeError("relay_plans must contain PriceRelayPlan values")
        relay_ids = tuple(plan.relay_plan_id for plan in self.relay_plans)
        if len(set(relay_ids)) != len(relay_ids):
            raise ValueError("relay plan IDs must be unique")
        object.__setattr__(
            self,
            "relay_plans",
            tuple(sorted(self.relay_plans, key=lambda item: item.relay_plan_id)),
        )
        lane_ids = {lane.lane_id for lane in self.decision_plan.lanes}
        for name, values, expected_type in (
            ("feature_plans", self.feature_plans, FeaturePlan),
            ("data_plans", self.data_plans, DataPlan),
            ("lane_requirements", self.lane_requirements, LaneMarketRequirements),
        ):
            if not isinstance(values, Mapping):
                raise TypeError(f"{name} must be a mapping")
            if set(values) != lane_ids:
                raise ValueError(f"{name} must cover every resolved lane")
            if any(not isinstance(value, expected_type) for value in values.values()):
                raise TypeError(f"{name} has invalid values")
        if not isinstance(self.lane_catchup_cutoffs, Mapping):
            raise TypeError("lane_catchup_cutoffs must be a mapping")
        raw_catchups = self.lane_catchup_cutoffs
        if not raw_catchups:
            raw_catchups = {lane_id: () for lane_id in lane_ids}
        if set(raw_catchups) != lane_ids:
            raise ValueError("lane_catchup_cutoffs must cover every resolved lane")
        normalized_catchups: dict[str, tuple[datetime, ...]] = {}
        for lane_id, cutoffs in raw_catchups.items():
            if isinstance(cutoffs, (str, bytes)) or not isinstance(cutoffs, Sequence):
                raise TypeError("lane catch-up cutoffs must be sequences")
            values = tuple(cutoffs)
            for cutoff in values:
                require_utc(cutoff, field_name="lane catch-up cutoff")
            if any(current <= previous for previous, current in pairwise(values)):
                raise ValueError("lane catch-up cutoffs must be strictly increasing")
            normalized_catchups[lane_id] = values
        if not isinstance(self.lane_catchup_stores, Mapping):
            raise TypeError("lane_catchup_stores must be a mapping")
        if not set(self.lane_catchup_stores) <= lane_ids:
            raise ValueError("lane_catchup_stores contains an unknown lane")
        if any(
            not isinstance(store, BarStore)
            for store in self.lane_catchup_stores.values()
        ):
            raise TypeError("lane_catchup_stores must contain BarStore values")
        object.__setattr__(
            self,
            "feature_plans",
            FrozenMapping(dict(sorted(self.feature_plans.items()))),
        )
        object.__setattr__(
            self,
            "data_plans",
            FrozenMapping(dict(sorted(self.data_plans.items()))),
        )
        object.__setattr__(
            self,
            "lane_requirements",
            FrozenMapping(dict(sorted(self.lane_requirements.items()))),
        )
        object.__setattr__(
            self,
            "lane_catchup_cutoffs",
            FrozenMapping(dict(sorted(normalized_catchups.items()))),
        )
        object.__setattr__(
            self,
            "lane_catchup_stores",
            FrozenMapping(dict(sorted(self.lane_catchup_stores.items()))),
        )
        for lane_id in lane_ids:
            if (
                self.snapshot.lane_evidence[lane_id].status == "STARTUP_READY"
                and lane_id not in self.runtimes
            ):
                raise ValueError("STARTUP_READY lane must have a runtime")


async def _capture_tail(
    stream_client: Any,
    *,
    stream_key: str,
    series_key: MarketSeriesKey,
    timeframe_grid: TimeframeGrid,
) -> CanonicalMarketEvent | None:
    if stream_client is None:
        return None
    xrevrange = getattr(stream_client, "xrevrange", None)
    if not callable(xrevrange):
        raise StartupContractError("stream client must provide bounded xrevrange")
    records = await xrevrange(stream_key, "+", "-", count=1)
    if not records:
        return None
    stream_id, fields = records[0]
    return parse_canonical_ingestion_event(
        stream_key=stream_key,
        stream_id=stream_id,
        fields=fields,
        expected_series=series_key,
        timeframe_grid=timeframe_grid,
    )


async def capture_series_startup_positions(
    *,
    series_keys: Sequence[MarketSeriesKey],
    timeframe_grid: TimeframeGrid,
    stream_client: Any,
    history_repository: CanonicalMarketHistoryRepository,
) -> Mapping[MarketSeriesKey, SeriesStartupPosition]:
    """Capture each stream tail once, then read the durable DB cutoff."""

    if not isinstance(timeframe_grid, TimeframeGrid):
        raise TypeError("timeframe_grid must be TimeframeGrid")
    if not hasattr(history_repository, "fetch_latest_cutoff"):
        raise TypeError("history_repository must provide fetch_latest_cutoff")
    positions: dict[MarketSeriesKey, SeriesStartupPosition] = {}
    for series_key in _sorted_keys(series_keys):
        stream_key = canonical_ingestion_stream_key(series_key)
        tail = await _capture_tail(
            stream_client,
            stream_key=stream_key,
            series_key=series_key,
            timeframe_grid=timeframe_grid,
        )
        db_latest = await history_repository.fetch_latest_cutoff(series_key)
        tail_cutoff = None if tail is None else tail.bar.market_as_of
        warm_cutoff = db_latest or tail_cutoff
        positions[series_key] = SeriesStartupPosition(
            series_key=series_key,
            stream_key=stream_key,
            captured_tail_id=None if tail is None else tail.stream_id,
            captured_tail_market_as_of=tail_cutoff,
            db_latest_market_as_of=db_latest,
            warm_cutoff=warm_cutoff,
        )
    return FrozenMapping(positions)


def _position_cursor(position: SeriesStartupPosition) -> InputReadCursor:
    return InputReadCursor(
        stream_key=position.stream_key,
        latest_stream_id=position.captured_tail_id,
        latest_market_as_of=position.warm_cutoff,
    )


class DecisionStartupCoordinator:
    """Compile and reconstruct static D9A state without starting live readers."""

    def __init__(
        self,
        *,
        decision_config: DecisionConfig,
        plugin_catalog: Any,
        feature_catalog: FeatureCatalog,
        feature_policy: FeaturePolicy,
        data_policy: DataPolicy,
        source_catalog: DataSourceCatalog,
        runtime_plugin_catalog: RuntimePluginCatalog,
        history_repository: Any,
        policy_catalog: DecisionPolicyCatalog | None = None,
        stream_client: Any = None,
        checkpoint_repository: Any | None = None,
        shadow_progress_repository: Any | None = None,
        manifest_store: Any | None = None,
        data_resolver: DataResolver | None = None,
        authority_store: SignalAuthorityStore | None = None,
    ) -> None:
        if not isinstance(decision_config, DecisionConfig):
            raise TypeError("decision_config must be DecisionConfig")
        if not isinstance(feature_catalog, FeatureCatalog):
            raise TypeError("feature_catalog must be FeatureCatalog")
        if not isinstance(feature_policy, FeaturePolicy):
            raise TypeError("feature_policy must be FeaturePolicy")
        if not isinstance(data_policy, DataPolicy):
            raise TypeError("data_policy must be DataPolicy")
        if not isinstance(source_catalog, DataSourceCatalog):
            raise TypeError("source_catalog must be DataSourceCatalog")
        if not isinstance(runtime_plugin_catalog, RuntimePluginCatalog):
            raise TypeError("runtime_plugin_catalog must be RuntimePluginCatalog")
        if policy_catalog is not None and not isinstance(
            policy_catalog, DecisionPolicyCatalog
        ):
            raise TypeError("policy_catalog must be DecisionPolicyCatalog or None")
        if not hasattr(history_repository, "fetch_bars"):
            raise TypeError("history_repository must provide fetch_bars")
        self._config = decision_config
        self._plugin_catalog = plugin_catalog
        self._feature_catalog = feature_catalog
        self._feature_policy = feature_policy
        self._data_policy = data_policy
        self._source_catalog = source_catalog
        self._runtime_catalog = runtime_plugin_catalog
        self._policy_catalog = policy_catalog or DecisionPolicyCatalog(
            [PASSTHROUGH_V1, PRIORITY_V1]
        )
        self._history = history_repository
        self._streams = stream_client
        self._checkpoints = checkpoint_repository or InMemoryCheckpointRepository()
        self._effect_progress = (
            shadow_progress_repository or InMemoryLaneEffectProgressRepository()
        )
        if not callable(getattr(self._effect_progress, "load", None)) or not callable(
            getattr(self._effect_progress, "save", None)
        ):
            raise TypeError(
                "lane effect progress repository must provide load() and save()"
            )
        self._manifest_store = manifest_store
        self._data_resolver = data_resolver or DataResolver(source_catalog)
        if authority_store is not None and not isinstance(
            authority_store, SignalAuthorityStore
        ):
            raise TypeError("authority_store must be SignalAuthorityStore or None")
        self._authority_store = authority_store

    async def start(self) -> DecisionStartupResult:
        """Perform one bounded startup reconstruction and return its owners."""

        decision_plan = compile_decision_plan(
            self._plugin_catalog,
            self._config.lane_specs(),
        )
        authority_records = await self._validate_authoritative_owners(decision_plan)
        for lane in decision_plan.lanes:
            # D8 policy identity is part of startup compilation even though
            # D9A never evaluates a policy or publishes a result.
            self._policy_catalog.resolve(lane.policy_name, lane.policy_version)
        feature_plans = {
            lane.lane_id: compile_feature_plan(
                lane,
                self._feature_catalog,
                self._feature_policy,
                self._config.timeframe_grid,
            )
            for lane in decision_plan.lanes
        }
        lane_requirements = {
            lane.lane_id: compile_lane_market_requirements(
                lane,
                self._config.timeframe_grid,
            )
            for lane in decision_plan.lanes
        }
        data_plans = {
            lane.lane_id: compile_data_plan(
                lane,
                self._data_policy,
                self._source_catalog,
            )
            for lane in decision_plan.lanes
        }
        relay_plans = compile_price_relay_plans(self._config)
        positions = await capture_series_startup_positions(
            series_keys=self._required_series(
                decision_plan,
                feature_plans,
                relay_plans,
            ),
            timeframe_grid=self._config.timeframe_grid,
            stream_client=self._streams,
            history_repository=self._history,
        )
        active_assets = await self._active_manifest_assets(decision_plan, feature_plans)
        active_relay_plans = tuple(
            plan for plan in relay_plans if plan.asset in active_assets
        )
        capacities = self._compile_capacities(
            decision_plan,
            feature_plans,
            relay_plans,
        )
        # This tail is exclusively for the final bounded shared BarStore.  A
        # stateful lane's replay history is loaded separately after its
        # checkpoint and replay interval are known.
        history_cache = await self._load_history(positions, capacities)
        final_store = BarStore(capacities)
        self._fill_store(final_store, history_cache)
        lane_evidence: dict[str, LaneStartupEvidence] = {}
        lane_watermarks: dict[str, LaneCommitWatermark] = {}
        runtimes: dict[str, ModelRuntime] = {}
        reconstruction_evidence: dict[str, Mapping[str, Any]] = {}
        lane_catchup_cutoffs: dict[str, tuple[datetime, ...]] = {
            lane.lane_id: () for lane in decision_plan.lanes
        }
        lane_catchup_stores: dict[str, BarStore] = {}
        for lane in decision_plan.lanes:
            if lane.asset not in active_assets:
                lane_evidence[lane.lane_id] = LaneStartupEvidence(
                    lane_id=lane.lane_id,
                    status="INACTIVE",
                    reason="manifest_not_live",
                )
                continue
            try:
                runtime, evidence, catchup_store = await self._reconstruct_lane(
                    lane,
                    feature_plans[lane.lane_id],
                    data_plans[lane.lane_id],
                    history_cache,
                    capacities,
                    positions,
                    final_store,
                    authority_records.get(f"{lane.asset}:{lane.decision_timeframe}"),
                )
            except (StartupLaneError, RewarmError, ValueError, TypeError) as exc:
                lane_evidence[lane.lane_id] = LaneStartupEvidence(
                    lane_id=lane.lane_id,
                    status="BLOCKED",
                    reason=str(exc),
                )
                continue
            runtimes[lane.lane_id] = runtime
            if catchup_store is not None:
                lane_catchup_stores[lane.lane_id] = catchup_store
            resume_cutoff = evidence["resume_cutoff"]
            catchup_cutoffs = tuple(evidence.get("catchup_cutoffs", ()))
            lane_catchup_cutoffs[lane.lane_id] = catchup_cutoffs
            watermark_cutoff = evidence.get("effect_progress_cutoff", resume_cutoff)
            watermark_disposition = evidence.get("effect_progress_disposition")
            lane_watermarks[lane.lane_id] = LaneCommitWatermark(
                lane_id=lane.lane_id,
                latest_market_as_of=watermark_cutoff,
                last_disposition=watermark_disposition,
            )
            lane_evidence[lane.lane_id] = LaneStartupEvidence(
                lane_id=lane.lane_id,
                status="STARTUP_READY",
                resume_cutoff=resume_cutoff,
                state_inception_at=evidence.get("state_inception_at"),
                checkpoint_loaded=bool(evidence["checkpoint_loaded"]),
                checkpoint_save_result=evidence.get("checkpoint_save_result"),
                replay_step_count=int(evidence["replay_step_count"]),
            )
            reconstruction_evidence[lane.lane_id] = evidence
        cursors = {
            position.stream_key: _position_cursor(position)
            for position in positions.values()
        }
        all_active_ready = all(
            item.status in {"STARTUP_READY", "INACTIVE"}
            for item in lane_evidence.values()
        )
        snapshot = DecisionStartupSnapshot(
            status="STARTUP_READY" if all_active_ready else "STARTUP_BLOCKED",
            configured_lane_ids=tuple(lane.lane_id for lane in decision_plan.lanes),
            active_manifest_assets=tuple(sorted(active_assets)),
            series_positions=positions,
            input_cursors=cursors,
            lane_watermarks=lane_watermarks,
            lane_evidence=lane_evidence,
            reconstruction_evidence=reconstruction_evidence,
            authority_records=authority_records,
        )
        return DecisionStartupResult(
            snapshot=snapshot,
            bar_store=final_store,
            runtimes=FrozenMapping(runtimes),
            decision_plan=decision_plan,
            feature_plans=feature_plans,
            data_plans=data_plans,
            lane_requirements=lane_requirements,
            lane_catchup_cutoffs=lane_catchup_cutoffs,
            lane_catchup_stores=lane_catchup_stores,
            relay_plans=active_relay_plans,
        )

    def _required_series(
        self,
        plan: ResolvedDecisionPlan,
        feature_plans: Mapping[str, FeaturePlan],
        relay_plans: Sequence[PriceRelayPlan] = (),
    ) -> tuple[MarketSeriesKey, ...]:
        keys: set[MarketSeriesKey] = set()
        for lane in plan.lanes:
            requirements = compile_lane_market_requirements(
                lane, self._config.timeframe_grid
            )
            keys.update(requirements.minimum_bars_by_series)
        for feature_plan in feature_plans.values():
            for history in feature_plan.history_requirements.values():
                keys.update(history)
        keys.update(plan_series_key(relay_plan) for relay_plan in relay_plans)
        return _sorted_keys(tuple(keys))

    def _compile_capacities(
        self,
        plan: ResolvedDecisionPlan,
        feature_plans: Mapping[str, FeaturePlan],
        relay_plans: Sequence[PriceRelayPlan] = (),
    ) -> Mapping[MarketSeriesKey, int]:
        base = compile_bar_store_capacities(plan, self._config.timeframe_grid)
        feature = compile_feature_bar_store_capacities(
            plan,
            feature_plans,
            self._feature_catalog,
            self._config.timeframe_grid,
        )
        merged = merge_bar_store_capacities(base, feature)
        relay_capacities = {
            plan_series_key(relay_plan): 1 for relay_plan in relay_plans
        }
        return merge_bar_store_capacities(merged, relay_capacities)

    async def _load_history(
        self,
        positions: Mapping[MarketSeriesKey, SeriesStartupPosition],
        capacities: Mapping[MarketSeriesKey, int],
    ) -> Mapping[MarketSeriesKey, tuple[Any, ...]]:
        result: dict[MarketSeriesKey, tuple[Any, ...]] = {}
        for key, position in positions.items():
            if position.warm_cutoff is None:
                result[key] = ()
                continue
            # The final shared store is deliberately limited to its compiled
            # steady-state capacity.  Stateful replay uses a separate
            # lane-specific range below, so this tail must never be used as a
            # proxy for a checkpoint catch-up window.
            limit = capacities.get(key, 1)
            result[key] = tuple(
                await self._history.fetch_bars(
                    key,
                    through=position.warm_cutoff,
                    limit=limit,
                )
            )
        return FrozenMapping(result)

    def _lane_history_requirements(
        self,
        lane: ResolvedLanePlan,
        feature_plan: FeaturePlan,
    ) -> Mapping[MarketSeriesKey, int]:
        """Merge D3 and D4 per-cutoff history needs for one lane."""

        return compile_lane_causal_history_requirements(
            lane,
            feature_plan,
            self._config.timeframe_grid,
        )

    def _validate_causal_history_at_cutoff(
        self,
        lane: ResolvedLanePlan,
        feature_plan: FeaturePlan,
        store: BarStore,
        cutoff: datetime,
    ) -> None:
        """Require the merged D3+D4 history window at one selected cutoff."""

        require_utc(cutoff, field_name="startup resume cutoff")
        requirements = self._lane_history_requirements(lane, feature_plan)
        for key, required_count in requirements.items():
            expected_cutoff = self._config.timeframe_grid.expected_closed_cutoff(
                key.timeframe,
                cutoff,
            )
            try:
                bars = store.bars_at(
                    key,
                    expected_cutoff,
                    limit=required_count,
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise StartupLaneError(
                    "no ready causal lane cutoff in retained history"
                ) from exc
            if len(bars) != required_count:
                raise StartupLaneError(
                    "no ready causal lane cutoff in retained history"
                )
            previous = None
            for bar in bars:
                try:
                    validate_canonical_bar_geometry(
                        key,
                        bar,
                        self._config.timeframe_grid,
                    )
                except (TypeError, ValueError) as exc:
                    raise StartupLaneError(
                        "no ready causal lane cutoff in retained history"
                    ) from exc
                if (
                    not bar.closed
                    or bar.market_as_of != bar.bar_close_at
                    or bar.market_as_of > cutoff
                    or bar.bar_close_at > expected_cutoff
                ):
                    raise StartupLaneError(
                        "no ready causal lane cutoff in retained history"
                    )
                if previous is not None and bar.bar_open_at != previous.bar_close_at:
                    raise StartupLaneError(
                        "no ready causal lane cutoff in retained history"
                    )
                previous = bar
            if bars[-1].market_as_of != expected_cutoff:
                raise StartupLaneError(
                    "no ready causal lane cutoff in retained history"
                )

    def _lane_identity(
        self,
        lane: ResolvedLanePlan,
        feature_plan: FeaturePlan,
        data_plan: Any,
    ) -> LaneExecutionIdentity:
        """Build the exact D6 identity without instantiating a runtime."""

        return lane_execution_identity(lane, feature_plan, data_plan)

    async def _validate_authoritative_owners(
        self,
        plan: ResolvedDecisionPlan,
    ) -> Mapping[str, SignalRouteAuthority]:
        if self._authority_store is None:
            return FrozenMapping({})
        routes = tuple(
            sorted(
                {
                    f"{lane.asset}:{lane.decision_timeframe}"
                    for lane in plan.lanes
                    if lane.authority == "authoritative"
                }
            )
        )
        records: dict[str, SignalRouteAuthority] = {}
        for route in routes:
            try:
                record = await self._authority_store.assert_owner(route, "decision")
            except Exception as exc:
                raise StartupContractError(
                    f"authoritative route {route} is not owned by decision: {exc}"
                ) from exc
            records[route] = record
        return FrozenMapping(records)

    async def _effect_progress_for_lane(
        self,
        *,
        lane: ResolvedLanePlan,
        data_plan: DataPlan,
        identity: LaneExecutionIdentity,
        resume_cutoff: datetime,
        ready_views: Sequence[tuple[datetime, LaneMarketView]],
        stateful_binding_ids: Sequence[str],
        authority_record: SignalRouteAuthority | None,
    ) -> tuple[LaneEffectProgress | None, tuple[datetime, ...]]:
        """Resolve authority-neutral effect progress without rewinding input."""

        progress = await self._effect_progress.load(identity)
        if authority_record is not None and progress is None:
            raise StartupLaneError(
                "authoritative handoff effect progress is missing at the authority boundary"
            )
        if progress is None:
            baseline = LaneEffectProgress.create(
                identity=identity,
                market_as_of=resume_cutoff,
                last_disposition=None,
            )
            result = await self._effect_progress.save(baseline)
            if _save_result_value(result) not in {
                "INSERTED",
                "UPDATED",
                "IDENTICAL",
            }:
                raise StartupLaneError(
                    f"effect progress persistence {result} blocks startup"
                )
            progress = baseline
        if not isinstance(progress, LaneEffectProgress):
            raise StartupLaneError("effect progress repository returned invalid record")
        if progress.identity != identity:
            raise StartupLaneError("effect progress identity does not match lane")
        if authority_record is not None:
            progress_cutoff_ms = int(progress.market_as_of.timestamp() * 1000)
            if progress_cutoff_ms < authority_record.boundary_ms:
                raise StartupLaneError(
                    "authoritative handoff effect progress is behind the authority boundary"
                )
        if progress.market_as_of > resume_cutoff:
            raise StartupLaneError("effect progress is ahead of market reconstruction")
        if progress.market_as_of == resume_cutoff:
            return progress, ()
        if stateful_binding_ids:
            raise StartupLaneError("stateful lane has an unresolved effect backlog")
        if data_plan.requested_concepts:
            raise StartupLaneError(
                "external-data lane has an unresolved effect backlog"
            )
        trigger_duration = self._config.timeframe_grid.duration(lane.trigger_timeframe)
        candidates = tuple(
            cutoff
            for cutoff, _view in ready_views
            if progress.market_as_of < cutoff <= resume_cutoff
        )
        expected_first = progress.market_as_of + trigger_duration
        if not candidates or candidates[0] != expected_first:
            raise StartupLaneError(
                "retained history cannot bridge lane effect progress backlog"
            )
        if candidates[-1] != resume_cutoff or any(
            current != previous + trigger_duration
            for previous, current in pairwise(candidates)
        ):
            raise StartupLaneError(
                "lane effect backlog is not contiguous in retained history"
            )
        return progress, candidates

    def _ready_views(
        self,
        lane: ResolvedLanePlan,
        lane_requirements: Any,
        store: BarStore,
        positions: Mapping[MarketSeriesKey, SeriesStartupPosition],
    ) -> list[tuple[datetime, LaneMarketView]]:
        """Build all retained ready cutoffs for one bounded store."""

        trigger_key = lane_requirements.trigger_series
        position = positions.get(trigger_key)
        if position is None or position.warm_cutoff is None:
            return []
        try:
            trigger_bars = store.bars_at(trigger_key, position.warm_cutoff)
        except KeyError:
            return []
        candidates = tuple(dict.fromkeys(bar.market_as_of for bar in trigger_bars))
        input_cursor = _position_cursor(position)
        watermark = LaneCommitWatermark(lane_id=lane.lane_id)
        view_builder = DecisionViewBuilder(store, self._config.timeframe_grid)
        ready: list[tuple[datetime, LaneMarketView]] = []
        for cutoff in candidates:
            try:
                view = view_builder.build(
                    lane,
                    lane_requirements,
                    cutoff,
                    input_read_cursor=input_cursor,
                    lane_commit_watermark=watermark,
                )
            except (MarketViewNotReadyError, ValueError, KeyError):
                continue
            ready.append((cutoff, view))
        return ready

    async def _load_effect_catchup_store(
        self,
        *,
        lane: ResolvedLanePlan,
        feature_plan: FeaturePlan,
        lane_requirements: Mapping[MarketSeriesKey, int],
        catchup_cutoffs: Sequence[datetime],
        resume_cutoff: datetime,
    ) -> BarStore | None:
        """Load one bounded causal store for a stateless effect backlog."""

        if not catchup_cutoffs:
            return None
        if any(binding.model_spec.stateful for binding in lane.bindings.values()):
            raise StartupLaneError("stateful lane has an unresolved effect backlog")
        first_cutoff = catchup_cutoffs[0]
        histories: dict[MarketSeriesKey, tuple[Any, ...]] = {}
        capacities: dict[MarketSeriesKey, int] = {}
        for key, required_count in lane_requirements.items():
            duration = self._config.timeframe_grid.duration(key.timeframe)
            first_visible_cutoff = self._config.timeframe_grid.expected_closed_cutoff(
                key.timeframe,
                first_cutoff,
            )
            # ``start`` is an open-time bound while ``first_visible_cutoff``
            # is a close-time bound.  N contiguous bars ending at that close
            # begin exactly N durations earlier.
            start = first_visible_cutoff - duration * required_count
            bars = tuple(
                await self._history.fetch_bars(
                    key,
                    start=start,
                    through=resume_cutoff,
                )
            )
            if len(bars) < required_count:
                raise StartupLaneError(
                    "retained history cannot bridge lane effect progress backlog"
                )
            histories[key] = bars
            capacities[key] = len(bars)

        store = BarStore(capacities)
        try:
            self._fill_store(store, histories)
            for cutoff in catchup_cutoffs:
                self._validate_causal_history_at_cutoff(
                    lane,
                    feature_plan,
                    store,
                    cutoff,
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise StartupLaneError(
                "retained history cannot bridge lane effect progress backlog"
            ) from exc
        return store

    async def _load_reconstruction_history(
        self,
        *,
        first_replay_cutoff: datetime,
        lane_requirements: Mapping[MarketSeriesKey, int],
        capacities: Mapping[MarketSeriesKey, int],
        positions: Mapping[MarketSeriesKey, SeriesStartupPosition],
    ) -> Mapping[MarketSeriesKey, tuple[Any, ...]]:
        """Load one bounded causal replay range for each required lane series."""

        require_utc(first_replay_cutoff, field_name="first_replay_cutoff")
        result: dict[MarketSeriesKey, tuple[Any, ...]] = {}
        for key in lane_requirements:
            position = positions.get(key)
            if position is None or position.warm_cutoff is None:
                result[key] = ()
                continue
            series_duration = self._config.timeframe_grid.duration(key.timeframe)
            first_visible_cutoff = self._config.timeframe_grid.expected_closed_cutoff(
                key.timeframe,
                first_replay_cutoff,
            )
            capacity = capacities.get(key)
            if capacity is None:
                raise StartupLaneError(
                    f"missing steady-state capacity for reconstruction series {key}"
                )
            start = first_visible_cutoff - series_duration * capacity
            result[key] = tuple(
                await self._history.fetch_bars(
                    key,
                    start=start,
                    through=position.warm_cutoff,
                )
            )
        return FrozenMapping(result)

    @staticmethod
    def _fill_store(
        store: BarStore, history: Mapping[MarketSeriesKey, Sequence[Any]]
    ) -> None:
        for key in store.series_keys:
            for bar in history.get(key, ()):
                store.append(key, bar)

    async def _active_manifest_assets(
        self,
        plan: ResolvedDecisionPlan,
        feature_plans: Mapping[str, FeaturePlan],
    ) -> set[str]:
        configured = {
            asset.decision_asset: asset.manifest_asset
            for asset in self._config.assets.values()
            if asset.enabled
        }
        if self._manifest_store is None:
            return set(configured)
        required_timeframes_by_manifest: dict[str, set[str]] = {}
        relay_plans = compile_price_relay_plans(self._config)
        for series_key in self._required_series(plan, feature_plans, relay_plans):
            for asset in self._config.assets.values():
                if (
                    series_key.asset in {asset.decision_asset, asset.manifest_asset}
                    and series_key.venue == asset.venue
                    and series_key.instrument_id == asset.instrument_id
                ):
                    required_timeframes_by_manifest.setdefault(
                        asset.manifest_asset,
                        set(),
                    ).add(series_key.timeframe)

        active: set[str] = set()
        for decision_asset, manifest_asset in configured.items():
            manifest = await self._manifest_store.read_asset(manifest_asset)
            if manifest is None:
                continue
            if (
                manifest.symbol != manifest_asset
                or manifest.source != "ingestion"
                or not manifest.enabled
                or str(manifest.desired_state).upper() != "LIVE"
            ):
                continue
            required_timeframes = required_timeframes_by_manifest.get(
                manifest_asset,
                set(),
            )
            valid = True
            for timeframe in required_timeframes:
                timeframe_manifest = await self._manifest_store.read_timeframe(
                    manifest_asset,
                    timeframe,
                )
                if timeframe_manifest is None or (
                    timeframe_manifest.symbol != manifest_asset
                    or timeframe_manifest.source != "ingestion"
                    or not timeframe_manifest.enabled
                    or str(timeframe_manifest.desired_state).upper() != "LIVE"
                ):
                    valid = False
                    break
            if valid:
                active.add(decision_asset)
        return active

    def _initialization_for(self, binding: Any) -> StateInitializationRequirement:
        requirement = self._runtime_catalog.initialization_for(binding)
        if requirement is not None:
            return requirement
        if not binding.model_spec.stateful:
            raise StartupLaneError(
                "stateless binding unexpectedly requires initialization"
            )
        raise StartupLaneError(
            f"stateful binding {binding.slot_name} has no bounded initialization requirement"
        )

    async def _reconstruct_lane(
        self,
        lane: ResolvedLanePlan,
        feature_plan: FeaturePlan,
        data_plan: Any,
        history: Mapping[MarketSeriesKey, Sequence[Any]],
        capacities: Mapping[MarketSeriesKey, int],
        positions: Mapping[MarketSeriesKey, SeriesStartupPosition],
        final_store: BarStore,
        authority_record: SignalRouteAuthority | None,
    ) -> tuple[ModelRuntime, Mapping[str, Any], BarStore | None]:
        lane_requirements = compile_lane_market_requirements(
            lane, self._config.timeframe_grid
        )
        trigger_key = lane_requirements.trigger_series
        lane_stateful = tuple(
            sorted(
                binding.binding_id
                for binding in lane.bindings.values()
                if binding.model_spec.stateful
            )
        )
        identity = self._lane_identity(lane, feature_plan, data_plan)
        baseline_store = final_store
        baseline_ready = self._ready_views(
            lane,
            lane_requirements,
            baseline_store,
            positions,
        )
        if not baseline_ready:
            raise StartupLaneError("no ready causal lane cutoff in retained history")
        resume_candidate, _ = baseline_ready[-1]
        self._validate_causal_history_at_cutoff(
            lane,
            feature_plan,
            baseline_store,
            resume_candidate,
        )
        checkpoint = await self._checkpoints.load(
            identity,
            expected_binding_ids=lane_stateful,
        )
        if checkpoint is not None and checkpoint.market_as_of > resume_candidate:
            raise StartupLaneError("checkpoint cutoff is after startup resume cutoff")

        effect_progress, catchup_cutoffs = await self._effect_progress_for_lane(
            lane=lane,
            data_plan=data_plan,
            identity=identity,
            resume_cutoff=resume_candidate,
            ready_views=baseline_ready,
            stateful_binding_ids=lane_stateful,
            authority_record=authority_record,
        )
        catchup_store = await self._load_effect_catchup_store(
            lane=lane,
            feature_plan=feature_plan,
            lane_requirements=self._lane_history_requirements(lane, feature_plan),
            catchup_cutoffs=catchup_cutoffs,
            resume_cutoff=resume_candidate,
        )

        replay_history: Mapping[MarketSeriesKey, Sequence[Any]] = history
        if lane_stateful and checkpoint is not None:
            if checkpoint.market_as_of < resume_candidate:
                first_replay_cutoff = (
                    checkpoint.market_as_of
                    + self._config.timeframe_grid.duration(lane.trigger_timeframe)
                )
                replay_history = await self._load_reconstruction_history(
                    first_replay_cutoff=first_replay_cutoff,
                    lane_requirements=self._lane_history_requirements(
                        lane, feature_plan
                    ),
                    capacities=capacities,
                    positions=positions,
                )
        elif lane_stateful and checkpoint is None:
            requirement_steps = max(
                self._initialization_for(binding).trigger_steps
                for binding in lane.bindings.values()
                if binding.model_spec.stateful
            )
            trigger_duration = self._config.timeframe_grid.duration(
                lane.trigger_timeframe
            )
            first_replay_cutoff = resume_candidate - trigger_duration * (
                requirement_steps - 1
            )
            replay_history = await self._load_reconstruction_history(
                first_replay_cutoff=first_replay_cutoff,
                lane_requirements=self._lane_history_requirements(lane, feature_plan),
                capacities=capacities,
                positions=positions,
            )

        temp_capacities = {
            key: max(1, len(values)) for key, values in replay_history.items()
        }
        # The final store is authoritative for stateless lanes and for a
        # checkpoint already at the current cutoff.  Stateful catch-up gets a
        # lane-local store sized only to the fetched reconstruction inventory.
        temp_store = BarStore(temp_capacities)
        self._fill_store(temp_store, replay_history)
        temp_runtime = ModelRuntime(
            lane,
            feature_plan,
            data_plan,
            FeatureEngine(
                self._feature_catalog, temp_store, self._config.timeframe_grid
            ),
            self._data_resolver,
            self._runtime_catalog,
            self._config.timeframe_grid,
        )
        ready = self._ready_views(
            lane,
            lane_requirements,
            temp_store,
            positions,
        )
        if not ready:
            raise StartupLaneError("no ready causal lane cutoff in retained history")
        resume_cutoff, _resume_view = ready[-1]
        if resume_cutoff != resume_candidate:
            raise StartupLaneError(
                "reconstruction history does not reach startup resume cutoff"
            )
        self._validate_causal_history_at_cutoff(
            lane,
            feature_plan,
            temp_store,
            resume_cutoff,
        )
        checkpoint_loaded = checkpoint is not None
        state_inception_at: datetime | None = None
        replay_steps: list[RewarmStep] = []
        if lane_stateful:
            if checkpoint is not None:
                records = {
                    binding_id: BindingRuntimeState(
                        binding_id=binding_id,
                        health="LIVE",
                        committed_market_as_of=checkpoint.market_as_of,
                        committed_state=checkpoint.state_by_binding[binding_id],
                        last_failure_reason=None,
                    )
                    for binding_id in lane_stateful
                }
                temp_runtime.state_store.install_rewarm(identity, records)
                state_inception_at = checkpoint.state_inception_at
                if checkpoint.market_as_of < resume_cutoff:
                    expected = (
                        checkpoint.market_as_of
                        + self._config.timeframe_grid.duration(lane.trigger_timeframe)
                    )
                    after = [
                        (cutoff, view)
                        for cutoff, view in ready
                        if cutoff > checkpoint.market_as_of
                    ]
                    if not after or after[0][0] != expected:
                        raise StartupLaneError(
                            "retained history cannot bridge checkpoint next trigger transition"
                        )
                    replay_steps = [
                        RewarmStep(
                            lane_market_view=view,
                            resolver_knowledge_cutoff=cutoff,
                        )
                        for cutoff, view in after
                    ]
            else:
                requirement_steps = max(
                    self._initialization_for(binding).trigger_steps
                    for binding in lane.bindings.values()
                    if binding.model_spec.stateful
                )
                if len(ready) < requirement_steps:
                    raise StartupLaneError(
                        "retained history is shorter than state initialization horizon"
                    )
                selected = ready[-requirement_steps:]
                trigger_duration = self._config.timeframe_grid.duration(
                    lane.trigger_timeframe
                )
                if any(
                    current[0] != previous[0] + trigger_duration
                    for previous, current in pairwise(selected)
                ):
                    raise StartupLaneError(
                        "state initialization history has a trigger gap"
                    )
                state_inception_at = selected[0][0]
                replay_steps = [
                    RewarmStep(
                        lane_market_view=view,
                        resolver_knowledge_cutoff=cutoff,
                    )
                    for cutoff, view in selected
                ]
            if replay_steps:
                await temp_runtime.rewarm(replay_steps)
            elif checkpoint is None:
                raise StartupLaneError("stateful startup produced no replay steps")
            states = {
                binding_id: temp_runtime.state_store.get(binding_id).committed_state
                for binding_id in lane_stateful
            }
            checkpoint_to_save = LaneStateCheckpoint.create(
                identity=identity,
                market_as_of=resume_cutoff,
                state_inception_at=state_inception_at or resume_cutoff,
                state_by_binding=states,
            )
            save_result = await self._checkpoints.save(checkpoint_to_save)
            if not isinstance(save_result, CheckpointSaveResult):
                raise StartupLaneError(
                    "checkpoint persistence returned unsupported result"
                )
            if save_result not in {
                CheckpointSaveResult.INSERTED,
                CheckpointSaveResult.UPDATED,
                CheckpointSaveResult.IDENTICAL,
            }:
                raise StartupLaneError(
                    f"checkpoint persistence {save_result.value} blocks startup"
                )
        else:
            save_result = None
        final_runtime = ModelRuntime(
            lane,
            feature_plan,
            data_plan,
            FeatureEngine(
                self._feature_catalog, final_store, self._config.timeframe_grid
            ),
            self._data_resolver,
            self._runtime_catalog,
            self._config.timeframe_grid,
            state_store=temp_runtime.state_store,
        )
        evidence = {
            "resume_cutoff": resume_cutoff,
            "checkpoint_loaded": checkpoint_loaded,
            "checkpoint_save_result": None
            if save_result is None
            else save_result.value,
            "state_inception_at": state_inception_at,
            "replay_step_count": len(replay_steps),
            "captured_tail_id": positions[trigger_key].captured_tail_id,
            "no_publication": True,
            "effect_progress_cutoff": (
                None if effect_progress is None else effect_progress.market_as_of
            ),
            "effect_progress_disposition": (
                None if effect_progress is None else effect_progress.last_disposition
            ),
            # Keep the bounded C4B evidence keys while the physical table and
            # compatibility tests transition to the authority-neutral names.
            "shadow_progress_cutoff": (
                None if effect_progress is None else effect_progress.market_as_of
            ),
            "shadow_progress_disposition": (
                None if effect_progress is None else effect_progress.last_disposition
            ),
            "catchup_cutoffs": catchup_cutoffs,
            "catchup_step_count": len(catchup_cutoffs),
        }
        return final_runtime, evidence, catchup_store


__all__ = [
    "DecisionStartupCoordinator",
    "DecisionStartupResult",
    "DecisionStartupSnapshot",
    "LaneStartupEvidence",
    "SeriesStartupPosition",
    "StartupContractError",
    "StartupError",
    "StartupLaneError",
    "capture_series_startup_positions",
]
