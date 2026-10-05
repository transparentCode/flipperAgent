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

from apps.decision_app.domain.contracts import (
    InputReadCursor,
    LaneCommitWatermark,
)
from apps.decision_app.domain.identity import (
    compute_decision_execution_revision,
    decision_id,
    lane_execution_identity,
)
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
from apps.decision_app.runtime.deadlines import run_with_timeout
from apps.decision_app.runtime.models import ModelRuntime, RewarmStep
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
from apps.decision_app.storage.effect_skips import (
    InMemoryLaneEffectSkipsRepository,
    LaneEffectSkip,
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
from apps.decision_app.transport.publication import (
    signal_stream_entry_id,
    signal_stream_key,
)
from libs.contracts.decision import FrozenMapping, deep_freeze, require_utc
from libs.contracts.serialization import valkey_decode
from libs.contracts.signal import TradeSignal


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
    pending_trigger_cutoff: datetime | None = None
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
        for field_name in (
            "resume_cutoff",
            "pending_trigger_cutoff",
            "state_inception_at",
        ):
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
    series_failures: Mapping[MarketSeriesKey, str] = field(default_factory=dict)
    no_publication: bool = True

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
                "skipped",
            }:
                raise ValueError("unsupported startup watermark disposition")
            watermarks[lane_id] = watermark
        evidence: dict[str, LaneStartupEvidence] = {}
        for lane_id, item in self.lane_evidence.items():
            if lane_id != item.lane_id:
                raise ValueError("lane evidence map key must match lane_id")
            evidence[lane_id] = item
        object.__setattr__(self, "configured_lane_ids", lane_ids)
        object.__setattr__(
            self, "active_manifest_assets", tuple(sorted(self.active_manifest_assets))
        )
        object.__setattr__(self, "series_positions", FrozenMapping(positions))
        object.__setattr__(self, "input_cursors", FrozenMapping(cursors))
        object.__setattr__(self, "lane_watermarks", FrozenMapping(watermarks))
        object.__setattr__(self, "lane_evidence", FrozenMapping(evidence))
        normalized_failures: dict[MarketSeriesKey, str] = {}
        for key, reason in self.series_failures.items():
            if not isinstance(key, MarketSeriesKey):
                raise TypeError("series_failures keys must be MarketSeriesKey values")
            normalized_failures[key] = _text(reason, "series failure reason")
        object.__setattr__(
            self,
            "series_failures",
            FrozenMapping(
                dict(
                    sorted(
                        normalized_failures.items(),
                        key=lambda item: (
                            item[0].asset,
                            item[0].venue,
                            item[0].instrument_id,
                            item[0].timeframe,
                        ),
                    )
                )
            ),
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
    lane_requirements: Mapping[str, LaneMarketRequirements]
    lane_history_requirements: Mapping[str, Mapping[MarketSeriesKey, int]]

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, DecisionStartupSnapshot):
            raise TypeError("snapshot must be DecisionStartupSnapshot")
        if not isinstance(self.bar_store, BarStore):
            raise TypeError("bar_store must be BarStore")
        if not isinstance(self.runtimes, Mapping):
            raise TypeError("runtimes must be a mapping")
        if not isinstance(self.decision_plan, ResolvedDecisionPlan):
            raise TypeError("decision_plan must be ResolvedDecisionPlan")
        lane_ids = {lane.lane_id for lane in self.decision_plan.lanes}
        for name, values, expected_type in (
            ("feature_plans", self.feature_plans, FeaturePlan),
            ("lane_requirements", self.lane_requirements, LaneMarketRequirements),
        ):
            if not isinstance(values, Mapping):
                raise TypeError(f"{name} must be a mapping")
            if set(values) != lane_ids:
                raise ValueError(f"{name} must cover every resolved lane")
            if any(not isinstance(value, expected_type) for value in values.values()):
                raise TypeError(f"{name} has invalid values")
        if not isinstance(self.lane_history_requirements, Mapping):
            raise TypeError("lane_history_requirements must be a mapping")
        if set(self.lane_history_requirements) != lane_ids:
            raise ValueError("lane_history_requirements must cover every lane")
        normalized_history: dict[str, FrozenMapping[MarketSeriesKey, int]] = {}
        for lane_id, requirements in self.lane_history_requirements.items():
            if not isinstance(requirements, Mapping) or not requirements:
                raise TypeError("lane history requirements must be non-empty mappings")
            normalized: dict[MarketSeriesKey, int] = {}
            for key, count in requirements.items():
                if not isinstance(key, MarketSeriesKey):
                    raise TypeError("lane history requirement keys must be series keys")
                if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
                    raise ValueError("lane history counts must be positive integers")
                normalized[key] = count
            normalized_history[lane_id] = FrozenMapping(
                dict(sorted(normalized.items(), key=lambda item: item[0].timeframe))
            )
        object.__setattr__(
            self,
            "feature_plans",
            FrozenMapping(dict(sorted(self.feature_plans.items()))),
        )
        object.__setattr__(
            self,
            "lane_requirements",
            FrozenMapping(dict(sorted(self.lane_requirements.items()))),
        )
        object.__setattr__(
            self,
            "lane_history_requirements",
            FrozenMapping(dict(sorted(normalized_history.items()))),
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
    io_timeout_seconds: float | None = None,
) -> CanonicalMarketEvent | None:
    if stream_client is None:
        return None
    xrevrange = getattr(stream_client, "xrevrange", None)
    if not callable(xrevrange):
        raise StartupContractError("stream client must provide bounded xrevrange")
    records = await run_with_timeout(
        xrevrange(stream_key, "+", "-", count=1),
        io_timeout_seconds,
        operation="startup series tail read",
    )
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
    io_timeout_seconds: float | None = None,
    series_failures: dict[MarketSeriesKey, str] | None = None,
) -> Mapping[MarketSeriesKey, SeriesStartupPosition]:
    """Capture each stream tail once, then read the durable DB cutoff."""

    if not isinstance(timeframe_grid, TimeframeGrid):
        raise TypeError("timeframe_grid must be TimeframeGrid")
    if not hasattr(history_repository, "fetch_latest_cutoff"):
        raise TypeError("history_repository must provide fetch_latest_cutoff")
    positions: dict[MarketSeriesKey, SeriesStartupPosition] = {}
    for series_key in _sorted_keys(series_keys):
        stream_key = canonical_ingestion_stream_key(series_key)
        try:
            tail = await _capture_tail(
                stream_client,
                stream_key=stream_key,
                series_key=series_key,
                timeframe_grid=timeframe_grid,
                io_timeout_seconds=io_timeout_seconds,
            )
            db_latest = await history_repository.fetch_latest_cutoff(series_key)
        except Exception as exc:
            if series_failures is None:
                raise
            series_failures[series_key] = f"series capture failed: {exc}"
            continue
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
        runtime_plugin_catalog: RuntimePluginCatalog,
        history_repository: Any,
        policy_catalog: DecisionPolicyCatalog | None = None,
        stream_client: Any = None,
        checkpoint_repository: Any | None = None,
        effect_progress_repository: Any | None = None,
        effect_skips_repository: Any | None = None,
        manifest_store: Any | None = None,
        io_timeout_seconds: float | None = None,
    ) -> None:
        if not isinstance(decision_config, DecisionConfig):
            raise TypeError("decision_config must be DecisionConfig")
        if not isinstance(feature_catalog, FeatureCatalog):
            raise TypeError("feature_catalog must be FeatureCatalog")
        if not isinstance(feature_policy, FeaturePolicy):
            raise TypeError("feature_policy must be FeaturePolicy")
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
        self._runtime_catalog = runtime_plugin_catalog
        self._policy_catalog = policy_catalog or DecisionPolicyCatalog(
            [PASSTHROUGH_V1, PRIORITY_V1]
        )
        self._history = history_repository
        self._streams = stream_client
        self._checkpoints = checkpoint_repository or InMemoryCheckpointRepository()
        self._effect_progress = (
            effect_progress_repository or InMemoryLaneEffectProgressRepository()
        )
        if not callable(getattr(self._effect_progress, "load", None)) or not callable(
            getattr(self._effect_progress, "save", None)
        ):
            raise TypeError(
                "lane effect progress repository must provide load() and save()"
            )
        self._manifest_store = manifest_store
        self._effect_skips = (
            effect_skips_repository or InMemoryLaneEffectSkipsRepository()
        )
        if not callable(getattr(self._effect_skips, "upsert", None)):
            raise TypeError("lane effect skips repository must provide upsert()")
        self._io_timeout_seconds = io_timeout_seconds

    async def start(self) -> DecisionStartupResult:
        """Perform one bounded startup reconstruction and return its owners."""

        decision_plan = compile_decision_plan(
            self._plugin_catalog,
            self._config.lane_specs(),
        )
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
        lane_history_requirements = {
            lane.lane_id: compile_lane_causal_history_requirements(
                lane,
                feature_plans[lane.lane_id],
                self._config.timeframe_grid,
            )
            for lane in decision_plan.lanes
        }
        series_failures: dict[MarketSeriesKey, str] = {}
        positions = await capture_series_startup_positions(
            series_keys=self._required_series(decision_plan, feature_plans),
            timeframe_grid=self._config.timeframe_grid,
            stream_client=self._streams,
            history_repository=self._history,
            io_timeout_seconds=self._io_timeout_seconds,
            series_failures=series_failures,
        )
        manifest_failures: dict[str, str] = {}
        active_assets = await self._active_manifest_assets(
            decision_plan,
            feature_plans,
            failures=manifest_failures,
        )
        capacities = self._compile_capacities(
            decision_plan,
            feature_plans,
        )
        # This tail is exclusively for the final bounded shared BarStore.  A
        # stateful lane's replay history is loaded separately after its
        # checkpoint and replay interval are known.
        history_failures: dict[MarketSeriesKey, str] = {}
        history_cache = await self._load_history(
            positions,
            capacities,
            failures=history_failures,
        )
        series_failures.update(history_failures)
        positions = {
            key: position
            for key, position in positions.items()
            if key not in history_failures
        }
        final_store = BarStore(capacities)
        self._fill_store(final_store, history_cache)
        lane_evidence: dict[str, LaneStartupEvidence] = {}
        lane_watermarks: dict[str, LaneCommitWatermark] = {}
        runtimes: dict[str, ModelRuntime] = {}
        reconstruction_evidence: dict[str, Mapping[str, Any]] = {}
        for lane in decision_plan.lanes:
            if lane.asset in manifest_failures:
                lane_evidence[lane.lane_id] = LaneStartupEvidence(
                    lane_id=lane.lane_id,
                    status="BLOCKED",
                    reason=manifest_failures[lane.asset],
                )
                continue
            if lane.asset not in active_assets:
                lane_evidence[lane.lane_id] = LaneStartupEvidence(
                    lane_id=lane.lane_id,
                    status="INACTIVE",
                    reason="manifest_not_live",
                )
                continue
            failed_series = sorted(
                (
                    key
                    for key in self._lane_required_series(
                        lane,
                        feature_plans[lane.lane_id],
                    )
                    if key in series_failures
                ),
                key=lambda item: (
                    item.asset,
                    item.venue,
                    item.instrument_id,
                    item.timeframe,
                ),
            )
            if failed_series:
                lane_evidence[lane.lane_id] = LaneStartupEvidence(
                    lane_id=lane.lane_id,
                    status="BLOCKED",
                    reason=series_failures[failed_series[0]],
                )
                continue
            try:
                runtime, evidence = await self._reconstruct_lane(
                    lane,
                    feature_plans[lane.lane_id],
                    lane_history_requirements[lane.lane_id],
                    history_cache,
                    capacities,
                    positions,
                    final_store,
                )
            except Exception as exc:  # noqa: BLE001 - isolate one lane reconstruction
                lane_evidence[lane.lane_id] = LaneStartupEvidence(
                    lane_id=lane.lane_id,
                    status="BLOCKED",
                    reason=str(exc),
                )
                continue
            runtimes[lane.lane_id] = runtime
            resume_cutoff = evidence["resume_cutoff"]
            watermark_cutoff = evidence.get("effect_progress_cutoff")
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
                pending_trigger_cutoff=evidence.get("pending_trigger_cutoff"),
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
            series_failures=series_failures,
        )
        return DecisionStartupResult(
            snapshot=snapshot,
            bar_store=final_store,
            runtimes=FrozenMapping(runtimes),
            decision_plan=decision_plan,
            feature_plans=feature_plans,
            lane_requirements=lane_requirements,
            lane_history_requirements=lane_history_requirements,
        )

    def _required_series(
        self,
        plan: ResolvedDecisionPlan,
        feature_plans: Mapping[str, FeaturePlan],
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
        return _sorted_keys(tuple(keys))

    def _lane_required_series(
        self,
        lane: ResolvedLanePlan,
        feature_plan: FeaturePlan,
    ) -> set[MarketSeriesKey]:
        keys = set(
            compile_lane_market_requirements(
                lane,
                self._config.timeframe_grid,
            ).minimum_bars_by_series
        )
        for history in feature_plan.history_requirements.values():
            keys.update(history)
        return keys

    def _compile_capacities(
        self,
        plan: ResolvedDecisionPlan,
        feature_plans: Mapping[str, FeaturePlan],
    ) -> Mapping[MarketSeriesKey, int]:
        base = compile_bar_store_capacities(plan, self._config.timeframe_grid)
        feature = compile_feature_bar_store_capacities(
            plan,
            feature_plans,
            self._feature_catalog,
            self._config.timeframe_grid,
        )
        merged = merge_bar_store_capacities(base, feature)
        return merged

    async def _load_history(
        self,
        positions: Mapping[MarketSeriesKey, SeriesStartupPosition],
        capacities: Mapping[MarketSeriesKey, int],
        *,
        failures: dict[MarketSeriesKey, str] | None = None,
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
            try:
                result[key] = tuple(
                    await self._history.fetch_bars(
                        key,
                        through=position.warm_cutoff,
                        limit=limit,
                    )
                )
            except Exception as exc:
                if failures is None:
                    raise
                failures[key] = f"series history read failed: {exc}"
        return FrozenMapping(result)

    def _validate_causal_history_at_cutoff(
        self,
        requirements: Mapping[MarketSeriesKey, int],
        store: BarStore,
        cutoff: datetime,
    ) -> None:
        """Require the merged D3+D4 history window at one selected cutoff."""

        require_utc(cutoff, field_name="startup resume cutoff")
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
    ) -> LaneExecutionIdentity:
        """Build the exact D6 identity without instantiating a runtime."""

        return lane_execution_identity(lane, feature_plan)

    async def _save_effect_progress(
        self,
        *,
        identity: LaneExecutionIdentity,
        market_as_of: datetime,
        last_disposition: Literal["shadow", "published", "no_signal"] | None,
    ) -> LaneEffectProgress:
        progress = LaneEffectProgress.create(
            identity=identity,
            market_as_of=market_as_of,
            last_disposition=last_disposition,
        )
        result = await self._effect_progress.save(progress)
        if _save_result_value(result) not in {"INSERTED", "UPDATED", "IDENTICAL"}:
            raise StartupLaneError(
                f"effect progress persistence {result} blocks startup"
            )
        return progress

    async def _upsert_skip(
        self,
        *,
        identity: LaneExecutionIdentity,
        skipped_from: datetime,
        skipped_through: datetime,
        reason: Literal["restart", "restart_rewarm", "stale", "foreign_entry"],
        trigger_duration: Any,
    ) -> None:
        if skipped_through < skipped_from:
            return
        elapsed = skipped_through - skipped_from
        quotient, remainder = divmod(elapsed, trigger_duration)
        if remainder:
            raise StartupLaneError("skip range is not aligned to the lane trigger")
        await self._effect_skips.upsert(
            LaneEffectSkip(
                identity=identity,
                skipped_from=skipped_from,
                skipped_through=skipped_through,
                cutoff_count=quotient + 1,
                reason=reason,
            )
        )

    async def _probe_effect_entry(
        self,
        *,
        lane: ResolvedLanePlan,
        identity: LaneExecutionIdentity,
        cutoff: datetime,
    ) -> Literal["published", "shadow", "foreign_entry"] | None:
        """Probe the one exact stream ID whose publication may have outlived progress."""

        if self._streams is None:
            return None
        from apps.decision_app.transport.shadow import (
            ShadowDecisionObservation,
            shadow_stream_entry_id,
            shadow_stream_key,
        )

        xrange = getattr(self._streams, "xrange", None)
        if not callable(xrange):
            raise StartupContractError("stream client must provide exact xrange")
        execution_revision = compute_decision_execution_revision(
            lane_id=lane.lane_id,
            base_lane_revision=lane.effective_lane_revision,
            feature_plan_fingerprint=identity.feature_plan_fingerprint,
            policy_name=lane.policy_name,
            policy_version=lane.policy_version,
            policy_parameters=lane.policy_parameters,
        )
        expected_id = decision_id(
            lane_id=lane.lane_id,
            lane_revision=execution_revision,
            market_as_of=cutoff,
        )
        if lane.authority == "authoritative":
            stream_key = signal_stream_key(lane.asset, lane.decision_timeframe)
            stream_id = signal_stream_entry_id(cutoff)
        else:
            stream_key = shadow_stream_key(lane.lane_id)
            stream_id = shadow_stream_entry_id(cutoff)
        records = await run_with_timeout(
            xrange(stream_key, stream_id, stream_id, count=1),
            self._io_timeout_seconds,
            operation="startup exact effect probe",
        )
        if not records:
            return None
        if len(records) != 1:
            raise StartupLaneError("exact effect probe returned multiple entries")
        observed_id, fields = records[0]
        if isinstance(observed_id, bytes):
            observed_id = observed_id.decode("utf-8")
        if observed_id != stream_id or not isinstance(fields, Mapping):
            raise StartupLaneError("exact effect probe returned a malformed entry")
        try:
            if lane.authority == "authoritative":
                signal = valkey_decode(dict(fields), TradeSignal)
                observed_decision_id = signal.metadata.get("decision_id")
                disposition: Literal["published", "shadow"] = "published"
            else:
                observation = valkey_decode(dict(fields), ShadowDecisionObservation)
                observed_decision_id = observation.decision_id
                disposition = "shadow"
        except Exception as exc:
            raise StartupLaneError("exact effect probe entry is malformed") from exc
        if observed_decision_id != expected_id:
            return "foreign_entry"
        return disposition

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
        *,
        failures: dict[str, str] | None = None,
    ) -> set[str]:
        configured = {
            asset.decision_asset: asset
            for asset in self._config.assets.values()
            if asset.enabled
        }
        if self._manifest_store is None:
            return set(configured)
        required_timeframes_by_runtime_asset: dict[str, set[str]] = {}
        for series_key in self._required_series(plan, feature_plans):
            for asset in self._config.assets.values():
                if (
                    series_key.asset in {asset.decision_asset, asset.manifest_asset}
                    and series_key.venue == asset.venue
                    and series_key.instrument_id == asset.instrument_id
                ):
                    required_timeframes_by_runtime_asset.setdefault(
                        asset.decision_asset,
                        set(),
                    ).add(series_key.timeframe)

        active: set[str] = set()
        for decision_asset, asset in configured.items():
            # ``asset.manifest_asset`` remains the canonical Ingestion config
            # key. The manifest store and lifecycle stream use the validated
            # live-provider identity in ``decision_asset``.
            try:
                manifest = await run_with_timeout(
                    self._manifest_store.read_asset(decision_asset),
                    self._io_timeout_seconds,
                    operation="startup asset manifest read",
                )
            except Exception as exc:
                if failures is None:
                    raise
                failures[decision_asset] = f"manifest read failed: {exc}"
                continue
            if manifest is None:
                continue
            if (
                manifest.symbol != decision_asset
                or manifest.source != "ingestion"
                or not manifest.enabled
                or str(manifest.desired_state).upper() != "LIVE"
            ):
                continue
            required_timeframes = required_timeframes_by_runtime_asset.get(
                decision_asset,
                set(),
            )
            valid = True
            for timeframe in sorted(required_timeframes):
                try:
                    timeframe_manifest = await run_with_timeout(
                        self._manifest_store.read_timeframe(
                            decision_asset,
                            timeframe,
                        ),
                        self._io_timeout_seconds,
                        operation="startup timeframe manifest read",
                    )
                except Exception as exc:
                    if failures is None:
                        raise
                    failures[decision_asset] = f"manifest read failed: {exc}"
                    valid = False
                    break
                if timeframe_manifest is None or (
                    timeframe_manifest.symbol != decision_asset
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
        history_requirements: Mapping[MarketSeriesKey, int],
        history: Mapping[MarketSeriesKey, Sequence[Any]],
        capacities: Mapping[MarketSeriesKey, int],
        positions: Mapping[MarketSeriesKey, SeriesStartupPosition],
        final_store: BarStore,
    ) -> tuple[ModelRuntime, Mapping[str, Any]]:
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
        identity = self._lane_identity(lane, feature_plan)
        trigger_position = positions.get(lane_requirements.trigger_series)
        if trigger_position is None or trigger_position.warm_cutoff is None:
            raise StartupLaneError("no warm trigger cutoff in retained history")
        try:
            trigger_bars = final_store.bars_at(
                lane_requirements.trigger_series,
                trigger_position.warm_cutoff,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StartupLaneError(
                "no latest trigger cutoff in retained history"
            ) from exc
        expected_resume = self._config.timeframe_grid.expected_closed_cutoff(
            lane.trigger_timeframe,
            trigger_position.warm_cutoff,
        )
        if not trigger_bars or trigger_bars[-1].market_as_of != expected_resume:
            raise StartupLaneError("latest trigger cutoff is not retained")
        resume_candidate = expected_resume
        self._validate_causal_history_at_cutoff(
            history_requirements,
            final_store,
            resume_candidate,
        )
        view_builder = DecisionViewBuilder(final_store, self._config.timeframe_grid)
        try:
            view_builder.build(
                lane,
                lane_requirements,
                resume_candidate,
                input_read_cursor=_position_cursor(trigger_position),
                lane_commit_watermark=LaneCommitWatermark(lane_id=lane.lane_id),
            )
        except (MarketViewNotReadyError, ValueError, KeyError) as exc:
            raise StartupLaneError(
                "latest trigger cutoff is not causally ready"
            ) from exc
        checkpoint = await self._checkpoints.load(
            identity,
            expected_binding_ids=lane_stateful,
        )
        if checkpoint is not None and checkpoint.market_as_of > resume_candidate:
            raise StartupLaneError("checkpoint cutoff is after startup resume cutoff")
        if (
            checkpoint is not None
            and self._config.timeframe_grid.expected_closed_cutoff(
                lane.trigger_timeframe, checkpoint.market_as_of
            )
            != checkpoint.market_as_of
        ):
            raise StartupLaneError("checkpoint cutoff is not trigger-aligned")
        effect_progress = await self._effect_progress.load(identity)
        if effect_progress is not None:
            if not isinstance(effect_progress, LaneEffectProgress):
                raise StartupLaneError(
                    "effect progress repository returned invalid record"
                )
            if effect_progress.identity != identity:
                raise StartupLaneError("effect progress identity does not match lane")
            if effect_progress.market_as_of > resume_candidate:
                raise StartupLaneError(
                    "effect progress is ahead of market reconstruction"
                )
            if (
                self._config.timeframe_grid.expected_closed_cutoff(
                    lane.trigger_timeframe, effect_progress.market_as_of
                )
                != effect_progress.market_as_of
            ):
                raise StartupLaneError("effect progress cutoff is not trigger-aligned")

        trigger_duration = self._config.timeframe_grid.duration(lane.trigger_timeframe)
        previous_effect_cutoff = (
            None if effect_progress is None else effect_progress.market_as_of
        )
        initial_effect_cutoff = previous_effect_cutoff
        first_unaccounted = (
            resume_candidate
            if previous_effect_cutoff is None
            else previous_effect_cutoff + trigger_duration
        )
        if (
            previous_effect_cutoff is not None
            and previous_effect_cutoff < resume_candidate
            and first_unaccounted > resume_candidate
        ):
            raise StartupLaneError("effect progress is ahead of market reconstruction")
        probe_result: Literal["published", "shadow", "foreign_entry"] | None = None
        if previous_effect_cutoff != resume_candidate:
            probe_result = await self._probe_effect_entry(
                lane=lane,
                identity=identity,
                cutoff=first_unaccounted,
            )
            if probe_result == "foreign_entry":
                await self._upsert_skip(
                    identity=identity,
                    skipped_from=first_unaccounted,
                    skipped_through=first_unaccounted,
                    reason="foreign_entry",
                    trigger_duration=trigger_duration,
                )
                effect_progress = await self._save_effect_progress(
                    identity=identity,
                    market_as_of=first_unaccounted,
                    last_disposition=None,
                )
            elif probe_result in {"published", "shadow"}:
                effect_progress = await self._save_effect_progress(
                    identity=identity,
                    market_as_of=first_unaccounted,
                    last_disposition=probe_result,
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
                    lane_requirements=history_requirements,
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
                lane_requirements=history_requirements,
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
            FeatureEngine(
                self._feature_catalog, temp_store, self._config.timeframe_grid
            ),
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
            history_requirements,
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
                        RewarmStep(lane_market_view=view) for cutoff, view in after
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
                    RewarmStep(lane_market_view=view) for cutoff, view in selected
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

        pending_trigger_cutoff: datetime | None = None
        current_effect_cutoff = (
            None if effect_progress is None else effect_progress.market_as_of
        )
        if lane_stateful:
            # Stateful history is reconstructed through R with publication
            # suppressed.  Progress follows the durable checkpoint only after
            # the full rewarm and checkpoint save have succeeded.
            if initial_effect_cutoff is None or initial_effect_cutoff < resume_cutoff:
                skip_start = (
                    initial_effect_cutoff + trigger_duration
                    if initial_effect_cutoff is not None
                    else (
                        replay_steps[0].lane_market_view.market_as_of
                        if replay_steps
                        else resume_cutoff
                    )
                )
                if probe_result is not None:
                    skip_start = max(skip_start, first_unaccounted + trigger_duration)
                skip_through = (
                    resume_cutoff - trigger_duration
                    if probe_result is not None and first_unaccounted == resume_cutoff
                    else resume_cutoff
                )
                await self._upsert_skip(
                    identity=identity,
                    skipped_from=skip_start,
                    skipped_through=skip_through,
                    reason="restart_rewarm",
                    trigger_duration=trigger_duration,
                )
                if (
                    current_effect_cutoff is None
                    or current_effect_cutoff < resume_cutoff
                ):
                    effect_progress = await self._save_effect_progress(
                        identity=identity,
                        market_as_of=resume_cutoff,
                        last_disposition=None,
                    )
        else:
            if current_effect_cutoff is None or current_effect_cutoff < resume_cutoff:
                if probe_result in {"published", "shadow", "foreign_entry"}:
                    skip_start = first_unaccounted + trigger_duration
                else:
                    skip_start = first_unaccounted
                skip_through = resume_cutoff - trigger_duration
                if skip_start <= skip_through:
                    await self._upsert_skip(
                        identity=identity,
                        skipped_from=skip_start,
                        skipped_through=skip_through,
                        reason="restart",
                        trigger_duration=trigger_duration,
                    )
                    effect_progress = await self._save_effect_progress(
                        identity=identity,
                        market_as_of=skip_through,
                        last_disposition=None,
                    )
                if (
                    effect_progress is None
                    or effect_progress.market_as_of < resume_cutoff
                ):
                    pending_trigger_cutoff = resume_cutoff
        final_runtime = ModelRuntime(
            lane,
            feature_plan,
            FeatureEngine(
                self._feature_catalog, final_store, self._config.timeframe_grid
            ),
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
            "pending_trigger_cutoff": pending_trigger_cutoff,
        }
        return final_runtime, evidence


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
