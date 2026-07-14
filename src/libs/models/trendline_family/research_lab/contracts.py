"""Immutable display records for canonical trendline-family research only."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from ..contracts import ContractValidationError, deterministic_hash, require_utc


CROSS_ASSET_SAMPLE_DEFINITION = "confirmed_ohlcv_exact_window_v1"
CROSS_ASSET_METRIC_DEFINITIONS = MappingProxyType(
    {
        "candidate_count": "canonical_candidate_row_count_v1",
        "eligible_bar_count": "confirmed_ohlcv_row_count_v1",
        "family_snapshot_count": "canonical_family_snapshot_row_count_v1",
        "unique_family_count": "unique_family_id_count_over_replay_v1",
    }
)


def _text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be non-empty text")
    return value


def _utc(value: datetime, *, field_name: str) -> datetime:
    return require_utc(value, field_name=field_name)


@dataclass(frozen=True)
class ResearchRunContext:
    """Semantic research inputs. Wall-clock timing intentionally excluded."""

    asset: str
    timeframe: str
    dataset_hash: str
    model_version: str
    config_version: str
    resolved_config_hash: str
    mtf_config_hash: str
    parameter_policy_hash: str
    research_parameters: Mapping[str, Any]
    provider_spec: Mapping[str, Any] = field(default_factory=dict)
    research_run_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "asset",
            "timeframe",
            "dataset_hash",
            "model_version",
            "config_version",
            "resolved_config_hash",
            "mtf_config_hash",
            "parameter_policy_hash",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        object.__setattr__(self, "research_parameters", _frozen_mapping(self.research_parameters, field_name="research_parameters"))
        object.__setattr__(self, "provider_spec", _frozen_mapping(self.provider_spec, field_name="provider_spec"))
        if not self.provider_spec:
            raise ContractValidationError("provider_spec must identify provider semantics")
        expected = deterministic_hash(self.identity_payload())
        if self.research_run_id is not None and self.research_run_id != expected:
            raise ContractValidationError("research_run_id does not match semantic inputs")
        object.__setattr__(self, "research_run_id", expected)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "dataset_hash": self.dataset_hash,
            "model_version": self.model_version,
            "config_version": self.config_version,
            "resolved_config_hash": self.resolved_config_hash,
            "mtf_config_hash": self.mtf_config_hash,
            "parameter_policy_hash": self.parameter_policy_hash,
            "research_parameters": self.research_parameters,
            "provider_spec": self.provider_spec,
        }

    def to_dict(self) -> dict[str, Any]:
        return record_to_dict(self)


@dataclass(frozen=True)
class ResearchExportManifest:
    """Content-addressed offline export identity; separate from replay identity."""

    research_run_id: str
    selected_snapshot_id: str
    selected_snapshot_timestamp: datetime
    selected_position: int | None
    dataset_summary_hash: str
    replay_config_version: str
    replay_resolved_config_hash: str
    replay_mtf_config_hash: str
    table_hashes: Mapping[str, str]
    mtf_snapshot_id: str | None
    mtf_config_version: str | None
    mtf_config_hash: str | None
    phase_i_run_id: str | None
    phase_i_artifact_hashes: Mapping[str, str]
    schema_version: str = "research_export_v2"
    export_bundle_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "research_run_id",
            "selected_snapshot_id",
            "dataset_summary_hash",
            "replay_config_version",
            "replay_resolved_config_hash",
            "replay_mtf_config_hash",
            "schema_version",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        object.__setattr__(self, "selected_snapshot_timestamp", _utc(self.selected_snapshot_timestamp, field_name="selected_snapshot_timestamp"))
        if self.selected_position is not None and (isinstance(self.selected_position, bool) or not isinstance(self.selected_position, int) or self.selected_position < 0):
            raise ContractValidationError("selected_position must be non-negative integer or None")
        object.__setattr__(self, "mtf_snapshot_id", _optional_text(self.mtf_snapshot_id, field_name="mtf_snapshot_id"))
        object.__setattr__(self, "mtf_config_version", _optional_text(self.mtf_config_version, field_name="mtf_config_version"))
        object.__setattr__(self, "mtf_config_hash", _optional_text(self.mtf_config_hash, field_name="mtf_config_hash"))
        if (self.mtf_snapshot_id is None) != (self.mtf_config_version is None) or (
            self.mtf_snapshot_id is None
        ) != (self.mtf_config_hash is None):
            raise ContractValidationError("MTF export identity fields must be all present or all absent")
        object.__setattr__(self, "phase_i_run_id", _optional_text(self.phase_i_run_id, field_name="phase_i_run_id"))
        object.__setattr__(self, "table_hashes", _hash_mapping(self.table_hashes, field_name="table_hashes"))
        object.__setattr__(self, "phase_i_artifact_hashes", _hash_mapping(self.phase_i_artifact_hashes, field_name="phase_i_artifact_hashes"))
        expected = deterministic_hash(self.identity_payload())
        if self.export_bundle_id is not None and self.export_bundle_id != expected:
            raise ContractValidationError("export_bundle_id does not match export evidence")
        object.__setattr__(self, "export_bundle_id", expected)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "research_run_id": self.research_run_id,
            "selected_snapshot_id": self.selected_snapshot_id,
            "selected_snapshot_timestamp": self.selected_snapshot_timestamp,
            "selected_position": self.selected_position,
            "dataset_summary_hash": self.dataset_summary_hash,
            "replay_config_version": self.replay_config_version,
            "replay_resolved_config_hash": self.replay_resolved_config_hash,
            "replay_mtf_config_hash": self.replay_mtf_config_hash,
            "table_hashes": self.table_hashes,
            "mtf_snapshot_id": self.mtf_snapshot_id,
            "mtf_config_version": self.mtf_config_version,
            "mtf_config_hash": self.mtf_config_hash,
            "phase_i_run_id": self.phase_i_run_id,
            "phase_i_artifact_hashes": self.phase_i_artifact_hashes,
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return record_to_dict(self)


@dataclass(frozen=True)
class CrossAssetComparabilityPolicy:
    """Content-addressed parameter, sample, coverage, and metric semantics."""

    sample_definition: str = CROSS_ASSET_SAMPLE_DEFINITION
    metric_definitions: Mapping[str, str] = field(
        default_factory=lambda: dict(CROSS_ASSET_METRIC_DEFINITIONS)
    )
    minimum_asset_count: int = 2
    require_same_timeframe: bool = True
    require_same_window: bool = True
    require_same_row_count: bool = True
    require_same_parameter_policy: bool = True
    require_same_provider_spec: bool = True
    policy_id: str | None = None

    def __post_init__(self) -> None:
        sample_definition = _text(self.sample_definition, field_name="sample_definition")
        if sample_definition != CROSS_ASSET_SAMPLE_DEFINITION:
            raise ContractValidationError(
                "unsupported cross-asset sample_definition; expected confirmed OHLCV exact-window semantics"
            )
        object.__setattr__(self, "sample_definition", sample_definition)
        definitions = _hash_mapping(self.metric_definitions, field_name="metric_definitions")
        if dict(definitions) != dict(CROSS_ASSET_METRIC_DEFINITIONS):
            raise ContractValidationError("cross-asset metric_definitions must match canonical structural metrics")
        object.__setattr__(self, "metric_definitions", definitions)
        if (
            isinstance(self.minimum_asset_count, bool)
            or not isinstance(self.minimum_asset_count, int)
            or self.minimum_asset_count < 2
        ):
            raise ContractValidationError("minimum_asset_count must be an integer >= 2")
        for name in (
            "require_same_timeframe",
            "require_same_window",
            "require_same_row_count",
            "require_same_parameter_policy",
            "require_same_provider_spec",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ContractValidationError(f"{name} must be boolean")
        expected = deterministic_hash(self.identity_payload())
        if self.policy_id is not None and self.policy_id != expected:
            raise ContractValidationError("policy_id must content-address the complete comparability policy")
        object.__setattr__(self, "policy_id", expected)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "sample_definition": self.sample_definition,
            "metric_definitions": self.metric_definitions,
            "minimum_asset_count": self.minimum_asset_count,
            "require_same_timeframe": self.require_same_timeframe,
            "require_same_window": self.require_same_window,
            "require_same_row_count": self.require_same_row_count,
            "require_same_parameter_policy": self.require_same_parameter_policy,
            "require_same_provider_spec": self.require_same_provider_spec,
        }

    def to_dict(self) -> dict[str, Any]:
        return record_to_dict(self)


@dataclass(frozen=True)
class CrossAssetComparabilityAudit:
    policy_id: str
    policy_identity: Mapping[str, Any]
    comparable: bool
    reason_codes: tuple[str, ...]
    assets: tuple[str, ...]
    timeframes: tuple[str, ...]
    parameter_policy_hashes: tuple[str, ...]
    provider_spec_hashes: tuple[str, ...]
    sample_starts: tuple[datetime, ...]
    sample_ends: tuple[datetime, ...]
    row_counts: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _text(self.policy_id, field_name="policy_id"))
        policy_identity = _frozen_mapping(self.policy_identity, field_name="policy_identity")
        if deterministic_hash(policy_identity) != self.policy_id:
            raise ContractValidationError("cross-asset audit policy identity does not match policy_id")
        object.__setattr__(self, "policy_identity", policy_identity)
        if not isinstance(self.comparable, bool):
            raise ContractValidationError("comparable must be boolean")
        reason_codes = tuple(self.reason_codes)
        if any(not isinstance(item, str) or not item for item in reason_codes):
            raise ContractValidationError("reason_codes must contain non-empty strings")
        if len(set(reason_codes)) != len(reason_codes):
            raise ContractValidationError("reason_codes must be unique")
        if self.comparable == bool(reason_codes):
            raise ContractValidationError("comparability must match reason-code presence")
        assets = tuple(_text(item, field_name="asset") for item in self.assets)
        lengths = {
            len(assets),
            len(self.timeframes),
            len(self.parameter_policy_hashes),
            len(self.provider_spec_hashes),
            len(self.sample_starts),
            len(self.sample_ends),
            len(self.row_counts),
        }
        if len(lengths) != 1:
            raise ContractValidationError("cross-asset audit evidence lengths must match")
        object.__setattr__(self, "reason_codes", reason_codes)
        object.__setattr__(self, "assets", assets)
        object.__setattr__(self, "timeframes", tuple(_text(item, field_name="timeframe") for item in self.timeframes))
        object.__setattr__(
            self,
            "parameter_policy_hashes",
            tuple(_text(item, field_name="parameter_policy_hash") for item in self.parameter_policy_hashes),
        )
        object.__setattr__(
            self,
            "provider_spec_hashes",
            tuple(_text(item, field_name="provider_spec_hash") for item in self.provider_spec_hashes),
        )
        object.__setattr__(
            self,
            "sample_starts",
            tuple(_utc(item, field_name="sample_start") for item in self.sample_starts),
        )
        object.__setattr__(
            self,
            "sample_ends",
            tuple(_utc(item, field_name="sample_end") for item in self.sample_ends),
        )
        row_counts = tuple(self.row_counts)
        if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in row_counts):
            raise ContractValidationError("row_counts must contain positive integers")
        object.__setattr__(self, "row_counts", row_counts)


@dataclass(frozen=True)
class CrossAssetComparisonRow:
    asset: str
    timeframe: str
    dataset_hash: str
    parameter_policy_hash: str
    provider_spec_hash: str
    sample_start: datetime
    sample_end: datetime
    eligible_bar_count: int
    candidate_count: int
    unique_family_count: int
    family_snapshot_count: int

    def __post_init__(self) -> None:
        for name in (
            "asset",
            "timeframe",
            "dataset_hash",
            "parameter_policy_hash",
            "provider_spec_hash",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        object.__setattr__(self, "sample_start", _utc(self.sample_start, field_name="sample_start"))
        object.__setattr__(self, "sample_end", _utc(self.sample_end, field_name="sample_end"))
        if self.sample_start > self.sample_end:
            raise ContractValidationError("cross-asset sample start cannot exceed end")
        for name in (
            "eligible_bar_count",
            "candidate_count",
            "unique_family_count",
            "family_snapshot_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ContractValidationError(f"{name} must be a non-negative integer")


@dataclass(frozen=True)
class CrossAssetComparison:
    policy: CrossAssetComparabilityPolicy
    audit: CrossAssetComparabilityAudit
    rows: tuple[CrossAssetComparisonRow, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.policy, CrossAssetComparabilityPolicy):
            raise ContractValidationError("cross-asset comparison requires typed policy")
        if not isinstance(self.audit, CrossAssetComparabilityAudit):
            raise ContractValidationError("cross-asset comparison requires typed audit")
        if (
            self.audit.policy_id != self.policy.policy_id
            or dict(self.audit.policy_identity) != record_to_dict(self.policy.identity_payload())
        ):
            raise ContractValidationError("cross-asset audit policy mismatch")
        if not self.audit.comparable:
            raise ContractValidationError("cross-asset comparison cannot contain incomparable samples")
        rows = tuple(self.rows)
        if any(not isinstance(item, CrossAssetComparisonRow) for item in rows):
            raise ContractValidationError("cross-asset comparison rows must be typed")
        if tuple(sorted(rows, key=lambda item: item.asset)) != rows:
            raise ContractValidationError("cross-asset comparison rows require asset ordering")
        if tuple(item.asset for item in rows) != self.audit.assets:
            raise ContractValidationError("cross-asset comparison rows must match audit assets")
        object.__setattr__(self, "rows", rows)


@dataclass(frozen=True)
class SnapshotSummary:
    snapshot_id: str
    previous_snapshot_id: str | None
    timestamp: datetime
    active_family_count: int
    dormant_family_count: int
    transition_count: int
    corridor_count: int
    observation_count: int
    event_count: int
    diagnostics: Mapping[str, Any]


@dataclass(frozen=True)
class CandidateRow:
    timestamp: datetime
    candidate_id: str
    role: str
    provider: str
    method: str
    anchor_count: int
    anchor_kinds: tuple[str, ...]
    slope_per_second: float
    normalized_quality: float
    coverage: float
    residual_scale_atr: float | None
    source_line_index: int | None


@dataclass(frozen=True)
class CandidateStatusRow:
    timestamp: datetime
    status: str
    candidate_count: int
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ProviderAuditRow:
    timestamp: datetime
    status: str
    candidate_count: int
    reason_codes: tuple[str, ...]
    confirmed_bar_count: int | None
    confirmed_pivot_count: int | None
    fitted_path_count: int | None
    fit_status: str | None


@dataclass(frozen=True)
class FamilyRow:
    snapshot_id: str
    timestamp: datetime
    family_id: str
    role: str
    lifecycle: str
    confidence: float
    age_bars: int
    representative_member_id: str
    member_count: int
    structural_importance: float
    current_relevance: float
    touch_count: int
    breach_count: int
    corridor_width_atr: float | None
    corridor_status: str


@dataclass(frozen=True)
class MemberRailRow:
    snapshot_id: str
    timestamp: datetime
    family_id: str
    member_id: str
    candidate_id: str
    role: str
    lifecycle: str
    representative: bool
    confidence: float
    age_bars: int
    projected_price: float
    reference_time: datetime
    reference_price: float
    slope_per_second: float
    anchor_ids: tuple[str, ...]
    anchor_points: tuple[tuple[datetime, float, str], ...]


@dataclass(frozen=True)
class CorridorRow:
    snapshot_id: str
    timestamp: datetime
    corridor_id: str
    family_id: str
    role: str
    lower_price: float
    upper_price: float
    center_price: float
    width_atr: float
    rail_count: int
    ordered_member_ids: tuple[str, ...]


@dataclass(frozen=True)
class InteractionZoneRow:
    snapshot_id: str
    timestamp: datetime
    observation_id: str
    family_id: str
    role: str
    exact_line_price: float
    lower_price: float
    upper_price: float
    width_atr: float
    observation_state: str


@dataclass(frozen=True)
class TransitionRow:
    snapshot_id: str
    timestamp: datetime
    transition_id: str
    family_id: str
    transition_type: str
    previous_version: int | None
    new_version: int
    reason_codes: tuple[str, ...]
    added_member_ids: tuple[str, ...]
    continued_member_ids: tuple[str, ...]
    removed_member_ids: tuple[str, ...]
    representative_changed: bool
    source_group_id: str | None
    source_group_candidate_ids: tuple[str, ...]


@dataclass(frozen=True)
class SourceGroupAuditRow:
    snapshot_id: str
    timestamp: datetime
    source_group_id: str
    role: str
    candidate_ids: tuple[str, ...]
    candidate_content_hashes: tuple[str, ...]


@dataclass(frozen=True)
class StructuralOutcomeRow:
    subject_type: str
    subject_id: str
    lifetime_bars: int | None
    dormant_snapshot_count: int | None
    interaction_snapshot_count: int | None
    status: str
    reason_code: str | None


@dataclass(frozen=True)
class ObservationRow:
    snapshot_id: str
    timestamp: datetime
    observation_id: str
    family_id: str
    role: str
    state: str
    exact_line_price: float
    distance_to_line_atr: float
    distance_to_zone_atr: float
    wick_penetration_atr: float
    body_penetration_atr: float
    close_penetration_atr: float


@dataclass(frozen=True)
class EventRow:
    snapshot_id: str
    timestamp: datetime
    event_id: str
    family_id: str
    state: str
    previous_state: str | None
    started_at: datetime
    updated_at: datetime
    age_bars: int
    last_observation_id: str


@dataclass(frozen=True)
class EventTransitionRow:
    snapshot_id: str
    timestamp: datetime
    transition_id: str
    event_id: str
    family_id: str
    from_state: str
    to_state: str
    trigger_observation_id: str
    reason_code: str


@dataclass(frozen=True)
class MTFSourceRow:
    mtf_snapshot_id: str
    decision_timestamp: datetime
    source_timeframe: str
    freshness_state: str
    source_snapshot_id: str | None
    source_snapshot_timestamp: datetime | None
    source_age_bars: float | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class MTFProjectedFamilyRow:
    mtf_snapshot_id: str
    projected_family_id: str
    source_snapshot_id: str
    source_timeframe: str
    source_family_id: str
    source_family_version: int
    role: str
    lifecycle: str
    representative_member_id: str
    projected_representative_price: float
    projected_representative_slope_per_second: float
    projected_corridor_lower_price: float
    projected_corridor_upper_price: float
    projected_corridor_width_atr: float
    source_confidence: float
    source_structural_importance: float
    source_event_id: str | None
    source_event_state: str | None
    source_age_bars: float
    freshness_state: str
    contributes_to_confluence: bool
    projected_order_changed: bool
    projection_timestamp: datetime


@dataclass(frozen=True)
class MTFProjectedMemberRow:
    mtf_snapshot_id: str
    projected_member_id: str
    projected_family_id: str
    source_snapshot_id: str
    source_timeframe: str
    source_family_id: str
    source_member_id: str
    source_candidate_id: str
    reference_time: datetime
    reference_price: float
    slope_per_second: float
    projected_price: float
    projected_offset_from_representative: float
    source_order_index: int
    projection_timestamp: datetime


@dataclass(frozen=True)
class MTFRelationRow:
    mtf_snapshot_id: str
    relation_id: str
    relation_type: str
    left_projected_family_id: str
    right_projected_family_id: str
    left_source_timeframe: str
    right_source_timeframe: str
    intersection_timestamp: datetime | None
    intersection_price: float | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class MTFClusterRow:
    mtf_snapshot_id: str
    cluster_id: str
    role: str
    projected_family_ids: tuple[str, ...]
    source_timeframes: tuple[str, ...]
    confluence_strength: float | None
    is_confluence: bool
    freshness_summary: str


@dataclass(frozen=True)
class ArtifactTrialRow:
    trial_id: str
    result_id: str
    stage: str
    status: str
    overrides: Mapping[str, Any]
    primary_metric_name: str
    primary_metric_value: float | None
    worst_metric_value: float | None
    validation_only: bool
    rejection_reasons: tuple[str, ...]
    aggregate_metrics: Mapping[str, Any]
    per_window_metrics: tuple[Mapping[str, Any], ...]
    counterfactual_result_ids: tuple[str, ...]
    parameter_audits: tuple[Mapping[str, Any], ...]


def record_to_dict(value: Any) -> Any:
    """Convert immutable display records to deterministic JSON-ready data."""

    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, datetime):
        return _utc(value, field_name="record timestamp").astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            item.name: record_to_dict(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): record_to_dict(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (tuple, list)):
        return [record_to_dict(item) for item in value]
    raise ContractValidationError(f"research record contains unsupported type: {type(value).__name__}")


def _frozen_mapping(value: Mapping[str, Any], *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{field_name} must be a mapping")
    return MappingProxyType(
        {
            str(key): _frozen_value(item, field_name=f"{field_name}.{key}")
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    )


def _hash_mapping(value: Mapping[str, str], *, field_name: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{field_name} must be a mapping")
    values: dict[str, str] = {}
    for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
        key_text = _text(str(key), field_name=f"{field_name} key")
        values[key_text] = _text(item, field_name=f"{field_name}.{key_text}")
    return MappingProxyType(values)


def _optional_text(value: str | None, *, field_name: str) -> str | None:
    return None if value is None else _text(value, field_name=field_name)


def _frozen_value(value: Any, *, field_name: str) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, datetime):
        return _utc(value, field_name=field_name)
    if isinstance(value, Enum):
        return value
    if isinstance(value, Mapping):
        return _frozen_mapping(value, field_name=field_name)
    if isinstance(value, (tuple, list)):
        return tuple(_frozen_value(item, field_name=f"{field_name} item") for item in value)
    raise ContractValidationError(f"{field_name} contains unsupported type: {type(value).__name__}")


__all__ = [
    "ArtifactTrialRow",
    "CandidateRow",
    "CandidateStatusRow",
    "ProviderAuditRow",
    "CorridorRow",
    "CrossAssetComparabilityAudit",
    "CrossAssetComparabilityPolicy",
    "CrossAssetComparison",
    "CrossAssetComparisonRow",
    "EventRow",
    "EventTransitionRow",
    "FamilyRow",
    "InteractionZoneRow",
    "MTFClusterRow",
    "MTFProjectedFamilyRow",
    "MTFProjectedMemberRow",
    "MTFRelationRow",
    "MTFSourceRow",
    "MemberRailRow",
    "ObservationRow",
    "ResearchRunContext",
    "ResearchExportManifest",
    "SnapshotSummary",
    "SourceGroupAuditRow",
    "StructuralOutcomeRow",
    "TransitionRow",
    "record_to_dict",
]
