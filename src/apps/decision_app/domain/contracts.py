"""Application-owned contracts built on the pure plugin semantic types."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from libs.contracts.decision import (
    DataRequirement,
    FeatureRequirement,
    FrozenMapping,
    ModelDecision,
    ModelSpec,
    deep_freeze,
    require_utc,
)

PublicationAuthority = Literal["authoritative", "shadow"]
LaneState = Literal["WARMING", "LIVE", "DEGRADED", "INVALID", "PAUSED", "STOPPED"]
PriceContinuity = Literal["CONTINUOUS", "GAP_DETECTED", "UNRESOLVED"]
CommitDisposition = Literal["published", "no_signal", "shadow"]


def _require_non_empty(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _freeze_mapping(
    value: Mapping[str, Any], *, field_name: str
) -> FrozenMapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} keys must be strings")
    return FrozenMapping({key: deep_freeze(item) for key, item in value.items()})


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedModelBinding:
    """Resolved binding metadata; it performs no plugin loading or graph work."""

    lane_id: str
    slot_name: str
    plugin_name: str
    plugin_version: str
    model_spec: ModelSpec
    binding_config_fingerprint: str
    binding_id: str
    effective_lane_revision: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    trigger_timeframe: str = ""
    decision_timeframe: str = ""
    trigger_mode: str = ""
    dependencies: Mapping[str, str] = field(default_factory=dict)
    effective_feature_requirements: tuple[FeatureRequirement, ...] = ()
    effective_data_requirements: tuple[DataRequirement, ...] = ()
    risk_profile_key: str | None = None
    publication_authority: PublicationAuthority = "authoritative"

    def __post_init__(self) -> None:
        for field_name in (
            "lane_id",
            "slot_name",
            "plugin_name",
            "plugin_version",
            "trigger_timeframe",
            "decision_timeframe",
            "trigger_mode",
        ):
            _require_non_empty(getattr(self, field_name), field_name=field_name)
        if not isinstance(self.model_spec, ModelSpec):
            raise TypeError("model_spec must be a ModelSpec")
        _require_non_empty(
            self.binding_config_fingerprint,
            field_name="binding_config_fingerprint",
        )
        _require_non_empty(self.binding_id, field_name="binding_id")
        _require_non_empty(
            self.effective_lane_revision,
            field_name="effective_lane_revision",
        )
        if self.plugin_name != self.model_spec.name:
            raise ValueError("plugin_name must match model_spec.name")
        if self.plugin_version != self.model_spec.version:
            raise ValueError("plugin_version must match model_spec.version")
        if self.risk_profile_key is not None:
            _require_non_empty(self.risk_profile_key, field_name="risk_profile_key")
        if self.publication_authority not in {"authoritative", "shadow"}:
            raise ValueError("publication_authority must be authoritative or shadow")
        object.__setattr__(
            self,
            "parameters",
            _freeze_mapping(self.parameters, field_name="parameters"),
        )
        object.__setattr__(
            self,
            "dependencies",
            _freeze_mapping(self.dependencies, field_name="dependencies"),
        )
        if any(not isinstance(value, str) for value in self.dependencies.values()):
            raise TypeError("dependencies values must be binding IDs")
        object.__setattr__(
            self,
            "effective_feature_requirements",
            _normalize_feature_requirements(self.effective_feature_requirements),
        )
        requirements = tuple(self.effective_data_requirements)
        if any(not isinstance(item, DataRequirement) for item in requirements):
            raise TypeError(
                "effective_data_requirements must contain DataRequirement values"
            )
        object.__setattr__(self, "effective_data_requirements", requirements)


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionPolicyResult:
    """Post-evaluation lane result, including the only output completion time."""

    lane_id: str
    effective_lane_revision: str
    decision_id: str
    policy_version: str
    market_as_of: datetime
    decision_ready_at: datetime
    decision: ModelDecision | None = None
    binding_config_fingerprints: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    # D8 additive identity/provenance fields.  They remain optional so the
    # previously approved semantic contract remains constructible in isolation;
    # D8 policy results populate and validate the complete set.
    base_lane_revision: str | None = None
    decision_execution_revision: str | None = None
    feature_plan_fingerprint: str | None = None
    data_plan_fingerprint: str | None = None
    policy_name: str | None = None
    policy_parameters: Mapping[str, Any] = field(default_factory=dict)
    risk_profile_key: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.lane_id, field_name="lane_id")
        _require_non_empty(
            self.effective_lane_revision,
            field_name="effective_lane_revision",
        )
        _require_non_empty(self.decision_id, field_name="decision_id")
        _require_non_empty(self.policy_version, field_name="policy_version")
        require_utc(self.market_as_of, field_name="market_as_of")
        require_utc(self.decision_ready_at, field_name="decision_ready_at")
        if self.decision_ready_at < self.market_as_of:
            raise ValueError("decision_ready_at must be at or after market_as_of")
        if self.decision is not None:
            if not isinstance(self.decision, ModelDecision):
                raise TypeError("decision must be a ModelDecision or None")
            if self.decision.market_as_of != self.market_as_of:
                raise ValueError("decision market_as_of must match result market_as_of")
        object.__setattr__(
            self, "metadata", _freeze_mapping(self.metadata, field_name="metadata")
        )
        fingerprints = _freeze_mapping(
            self.binding_config_fingerprints,
            field_name="binding_config_fingerprints",
        )
        if any(not isinstance(value, str) for value in fingerprints.values()):
            raise TypeError("binding_config_fingerprints values must be strings")
        object.__setattr__(self, "binding_config_fingerprints", fingerprints)
        object.__setattr__(
            self,
            "policy_parameters",
            _freeze_mapping(self.policy_parameters, field_name="policy_parameters"),
        )
        d8_identity_fields = (
            self.base_lane_revision,
            self.decision_execution_revision,
            self.feature_plan_fingerprint,
            self.data_plan_fingerprint,
            self.policy_name,
        )
        if self.risk_profile_key is not None and not any(
            value is not None for value in d8_identity_fields
        ):
            raise ValueError("risk_profile_key requires complete D8 identity fields")
        if any(value is not None for value in d8_identity_fields):
            if any(value is None for value in d8_identity_fields):
                raise ValueError(
                    "D8 identity fields must be supplied as one complete set"
                )
            for field_name in (
                "base_lane_revision",
                "decision_execution_revision",
                "feature_plan_fingerprint",
                "data_plan_fingerprint",
                "policy_name",
            ):
                _require_non_empty(
                    getattr(self, field_name),
                    field_name=field_name,
                )
            if self.base_lane_revision != self.effective_lane_revision:
                raise ValueError(
                    "base_lane_revision must match effective_lane_revision"
                )
            from apps.decision_app.domain.identity import (
                compute_decision_execution_revision,
                decision_id,
            )

            expected_revision = compute_decision_execution_revision(
                lane_id=self.lane_id,
                base_lane_revision=self.base_lane_revision,
                feature_plan_fingerprint=self.feature_plan_fingerprint,
                data_plan_fingerprint=self.data_plan_fingerprint,
                policy_name=self.policy_name,
                policy_version=self.policy_version,
                policy_parameters=self.policy_parameters,
            )
            if self.decision_execution_revision != expected_revision:
                raise ValueError(
                    "decision_execution_revision does not match D8 identity inputs"
                )
            expected_decision_id = decision_id(
                lane_id=self.lane_id,
                lane_revision=expected_revision,
                market_as_of=self.market_as_of,
            )
            if self.decision_id != expected_decision_id:
                raise ValueError("decision_id does not match D8 identity inputs")
        if self.risk_profile_key is not None:
            _require_non_empty(self.risk_profile_key, field_name="risk_profile_key")


@dataclass(frozen=True, slots=True, kw_only=True)
class InputReadCursor:
    """Observed input-reader progress, independent of every model lane."""

    stream_key: str
    latest_stream_id: str | None = None
    latest_market_as_of: datetime | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.stream_key, field_name="stream_key")
        if self.latest_stream_id is not None:
            _require_non_empty(self.latest_stream_id, field_name="latest_stream_id")
        if self.latest_market_as_of is not None:
            require_utc(self.latest_market_as_of, field_name="latest_market_as_of")


@dataclass(frozen=True, slots=True, kw_only=True)
class LaneCommitWatermark:
    """Progress committed by one lane after publication/no-signal disposition."""

    lane_id: str
    latest_market_as_of: datetime | None = None
    last_disposition: CommitDisposition | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.lane_id, field_name="lane_id")
        if self.latest_market_as_of is not None:
            require_utc(self.latest_market_as_of, field_name="latest_market_as_of")
        if self.last_disposition not in {"published", "no_signal", "shadow", None}:
            raise ValueError(
                "last_disposition must be published, no_signal, shadow, or None"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceRelayProgress:
    """PriceRelay progress and explicit continuity evidence."""

    relay_plan_id: str
    latest_market_as_of: datetime | None = None
    continuity_status: PriceContinuity = "CONTINUOUS"
    gap_evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty(self.relay_plan_id, field_name="relay_plan_id")
        if self.latest_market_as_of is not None:
            require_utc(self.latest_market_as_of, field_name="latest_market_as_of")
        if self.continuity_status not in {"CONTINUOUS", "GAP_DETECTED", "UNRESOLVED"}:
            raise ValueError("continuity_status is not supported")
        object.__setattr__(
            self,
            "gap_evidence",
            _freeze_mapping(self.gap_evidence, field_name="gap_evidence"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class LaneReadiness:
    """Data-only readiness snapshot for one lane."""

    state: LaneState
    required_cutoff: datetime
    input_read_cursor: InputReadCursor
    observed_cutoffs: Mapping[str, datetime] = field(default_factory=dict)
    lane_commit_watermark: LaneCommitWatermark
    missing_inputs: tuple[str, ...] = ()
    missing_dependencies: tuple[str, ...] = ()
    last_rewarm_reason: str | None = None

    def __post_init__(self) -> None:
        if self.state not in {
            "WARMING",
            "LIVE",
            "DEGRADED",
            "INVALID",
            "PAUSED",
            "STOPPED",
        }:
            raise ValueError("state is not supported")
        require_utc(self.required_cutoff, field_name="required_cutoff")
        if not isinstance(self.input_read_cursor, InputReadCursor):
            raise TypeError("input_read_cursor must be an InputReadCursor")
        if not isinstance(self.lane_commit_watermark, LaneCommitWatermark):
            raise TypeError("lane_commit_watermark must be a LaneCommitWatermark")
        if not isinstance(self.observed_cutoffs, Mapping):
            raise TypeError("observed_cutoffs must be a mapping")
        normalized_cutoffs: dict[str, datetime] = {}
        for timeframe, cutoff in self.observed_cutoffs.items():
            _require_non_empty(timeframe, field_name="observed_cutoffs timeframe")
            normalized_cutoffs[timeframe] = require_utc(
                cutoff,
                field_name="observed_cutoff",
            )
        object.__setattr__(self, "observed_cutoffs", FrozenMapping(normalized_cutoffs))
        object.__setattr__(
            self,
            "missing_inputs",
            _normalize_strings(self.missing_inputs, field_name="missing_inputs"),
        )
        object.__setattr__(
            self,
            "missing_dependencies",
            _normalize_strings(
                self.missing_dependencies, field_name="missing_dependencies"
            ),
        )
        if self.last_rewarm_reason is not None:
            _require_non_empty(self.last_rewarm_reason, field_name="last_rewarm_reason")


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceRelayPlan:
    """Independent downstream-risk price cadence configuration."""

    relay_plan_id: str
    manifest_asset: str
    asset: str
    venue: str
    instrument_id: str
    timeframe: str
    stream_key: str
    downstream_risk_compatibility: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "relay_plan_id",
            "manifest_asset",
            "asset",
            "venue",
            "instrument_id",
            "timeframe",
            "stream_key",
        ):
            _require_non_empty(getattr(self, field_name), field_name=field_name)
        object.__setattr__(
            self,
            "downstream_risk_compatibility",
            _freeze_mapping(
                self.downstream_risk_compatibility,
                field_name="downstream_risk_compatibility",
            ),
        )


def _normalize_strings(values: tuple[str, ...], *, field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field_name} must be a sequence of strings")
    normalized = tuple(
        _require_non_empty(value, field_name=field_name) for value in values
    )
    return normalized


def _normalize_feature_requirements(
    values: tuple[FeatureRequirement, ...],
) -> tuple[FeatureRequirement, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("effective_feature_requirements must be a sequence")
    normalized = tuple(values)
    if any(not isinstance(value, FeatureRequirement) for value in normalized):
        raise TypeError(
            "effective_feature_requirements must contain FeatureRequirement values"
        )
    names = [value.name for value in normalized]
    if len(set(names)) != len(names):
        raise ValueError("effective feature requirement names must be unique")
    return tuple(sorted(normalized, key=lambda value: value.name))


__all__ = [
    "CommitDisposition",
    "DecisionPolicyResult",
    "InputReadCursor",
    "LaneCommitWatermark",
    "LaneReadiness",
    "LaneState",
    "PriceContinuity",
    "PriceRelayPlan",
    "PriceRelayProgress",
    "PublicationAuthority",
    "ResolvedModelBinding",
]
