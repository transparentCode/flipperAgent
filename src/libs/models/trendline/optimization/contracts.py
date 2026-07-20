"""Immutable Phase-I evaluation contracts with deterministic semantic identities."""

from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
import json
import math
from types import MappingProxyType
from typing import Any, Mapping

from ..contracts import ContractValidationError


OPTIMIZATION_SCHEMA_VERSION = "trendline_family_phase_i_v1"
_OPERATIONAL_DIAGNOSTIC_KEYS = frozenset(
    {
        "runtime_seconds",
        "latency_ms",
        "bars_per_second",
        "artifact_size_bytes",
        "created_at",
        "started_at",
        "completed_at",
    }
)


class OptimizationStage(str, Enum):
    CANDIDATE_GEOMETRY = "candidate_geometry"
    TRACKER = "tracker"
    INTERACTION = "interaction"
    REGIME_ABLATION = "regime_ablation"


class TrialStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    INVALID = "invalid"


class PromotionDecision(str, Enum):
    PROMOTE = "promote"
    HOLD = "hold"
    REJECT = "reject"


class OptimizationDirection(str, Enum):
    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


class FailureCode(str, Enum):
    DATA_INVALID = "data_invalid"
    INSUFFICIENT_ROWS = "insufficient_rows"
    NO_VALID_WINDOWS = "no_valid_windows"
    NO_CANDIDATES = "no_candidates"
    NO_FAMILIES = "no_families"
    NO_EVENTS = "no_events"
    NO_POSITIVE_LABELS = "no_positive_labels"
    NO_NEGATIVE_LABELS = "no_negative_labels"
    NONFINITE_METRIC = "nonfinite_metric"
    PARAMETER_OWNERSHIP_VIOLATION = "parameter_ownership_violation"
    PARAMETER_NO_EFFECT = "parameter_no_effect"
    CROSS_STAGE_LEAKAGE = "cross_stage_leakage"
    CAUSALITY_VIOLATION = "causality_violation"
    LATENCY_LIMIT_EXCEEDED = "latency_limit_exceeded"
    ARTIFACT_WRITE_FAILED = "artifact_write_failed"
    INTERNAL_ERROR = "internal_error"


class FeatureGroup(str, Enum):
    BASELINE = "baseline"
    BASE_GEOMETRY = "base_geometry"
    FAMILY_IDENTITY_LIFECYCLE = "family_identity_lifecycle"
    INTERACTION_OBSERVATIONS = "interaction_observations"
    FULL_EVENTS = "full_events"
    MULTI_RAIL = "multi_rail"
    MTF = "mtf"
    ALL_TRENDLINE_FAMILY = "all_trendline_family"


def _utc(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ContractValidationError(f"{field_name} must be a timezone-aware UTC datetime")
    return value.astimezone(timezone.utc)


def _text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


def _integer(value: Any, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractValidationError(f"{field_name} must be an integer >= {minimum}")
    return value


def _number(value: Any, *, field_name: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field_name} must be finite numeric")
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ContractValidationError(f"{field_name} must be finite numeric")
    return result


def freeze(value: Any, *, field_name: str = "value") -> Any:
    """Recursively copy semantic data so caller mutation cannot alter a trial."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return _number(value, field_name=field_name)
    if isinstance(value, datetime):
        return _utc(value, field_name=field_name)
    if isinstance(value, Enum):
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ContractValidationError(f"{field_name} mapping keys must be strings")
        return MappingProxyType(
            {key: freeze(item, field_name=f"{field_name}.{key}") for key, item in sorted(value.items())}
        )
    if isinstance(value, (tuple, list)):
        return tuple(freeze(item, field_name=field_name) for item in value)
    raise ContractValidationError(f"{field_name} contains unsupported value type")


def primitive(value: Any) -> Any:
    """Convert a frozen semantic payload to canonical JSON-safe primitives."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return float(value)
    if isinstance(value, datetime):
        return _utc(value, field_name="timestamp").isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {key: primitive(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [primitive(item) for item in value]
    if is_dataclass(value):
        return primitive(value.to_dict() if hasattr(value, "to_dict") else value.__dict__)
    raise ContractValidationError(f"unsupported semantic value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(primitive(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def semantic_payload(value: Any) -> Any:
    """Remove operational observations before deriving a semantic identity."""

    if isinstance(value, Mapping):
        return {
            key: semantic_payload(item)
            for key, item in value.items()
            if key not in _OPERATIONAL_DIAGNOSTIC_KEYS and key != "runtime_diagnostics"
        }
    if isinstance(value, tuple):
        return tuple(semantic_payload(item) for item in value)
    return value


def semantic_id(prefix: str, value: Any) -> str:
    return f"{_text(prefix, field_name='identity prefix')}_{sha256(canonical_json(value).encode()).hexdigest()}"


def _required_mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ContractValidationError(f"{field_name} must be a mapping with string keys")
    return value


@dataclass(frozen=True)
class StageEvaluationSpec:
    """Complete immutable evaluator request bound into every semantic trial."""

    stage: OptimizationStage | str
    spec_type: str
    semantic_inputs: Mapping[str, Any]
    spec_version: str = "v1"
    spec_id: str | None = None

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "stage", OptimizationStage(self.stage))
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("invalid evaluation spec stage") from exc
        for name in ("spec_type", "spec_version"):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        object.__setattr__(self, "semantic_inputs", freeze(self.semantic_inputs, field_name="evaluation semantic_inputs"))
        expected = semantic_id("trendline-family-stage-evaluation-spec", self.identity_payload())
        if self.spec_id is not None and self.spec_id != expected:
            raise ContractValidationError("evaluation spec ID does not match semantic inputs")
        object.__setattr__(self, "spec_id", expected)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "spec_type": self.spec_type,
            "semantic_inputs": self.semantic_inputs,
            "spec_version": self.spec_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**primitive(self.identity_payload()), "spec_id": self.spec_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StageEvaluationSpec":
        payload = _required_mapping(value, field_name="StageEvaluationSpec")
        return cls(
            stage=payload.get("stage"),
            spec_type=payload.get("spec_type"),
            semantic_inputs=payload.get("semantic_inputs", {}),
            spec_version=payload.get("spec_version", "v1"),
            spec_id=payload.get("spec_id"),
        )


@dataclass(frozen=True)
class CandidateEvaluationSpec:
    provider_identity: str
    provider_state_hash: str
    outcome_policy: Mapping[str, Any] | None
    spec_version: str = "candidate_evaluation_v1"

    def to_stage_spec(self) -> StageEvaluationSpec:
        return StageEvaluationSpec(
            stage=OptimizationStage.CANDIDATE_GEOMETRY,
            spec_type="candidate_evaluation",
            semantic_inputs={
                "provider_identity": _text(self.provider_identity, field_name="provider_identity"),
                "provider_state_hash": _text(self.provider_state_hash, field_name="provider_state_hash"),
                "outcome_policy": None if self.outcome_policy is None else freeze(self.outcome_policy, field_name="outcome_policy"),
            },
            spec_version=self.spec_version,
        )


@dataclass(frozen=True)
class TrackerEvaluationSpec:
    frozen_candidate_stream_id: str
    source_candidate_config_hash: str
    spec_version: str = "tracker_evaluation_v1"

    def to_stage_spec(self) -> StageEvaluationSpec:
        return StageEvaluationSpec(
            stage=OptimizationStage.TRACKER,
            spec_type="tracker_evaluation",
            semantic_inputs={
                "frozen_candidate_stream_id": _text(self.frozen_candidate_stream_id, field_name="frozen_candidate_stream_id"),
                "source_candidate_config_hash": _text(self.source_candidate_config_hash, field_name="source_candidate_config_hash"),
            },
            spec_version=self.spec_version,
        )


@dataclass(frozen=True)
class InteractionEvaluationSpec:
    frozen_source_snapshot_stream_id: str
    outcome_policy: Mapping[str, Any] | None
    tick_size: float | None
    spec_version: str = "interaction_evaluation_v1"

    def to_stage_spec(self) -> StageEvaluationSpec:
        tick_size = None if self.tick_size is None else _number(self.tick_size, field_name="tick_size", minimum=0.0)
        return StageEvaluationSpec(
            stage=OptimizationStage.INTERACTION,
            spec_type="interaction_evaluation",
            semantic_inputs={
                "frozen_source_snapshot_stream_id": _text(self.frozen_source_snapshot_stream_id, field_name="frozen_source_snapshot_stream_id"),
                "outcome_policy": None if self.outcome_policy is None else freeze(self.outcome_policy, field_name="interaction outcome_policy"),
                "tick_size": tick_size,
            },
            spec_version=self.spec_version,
        )


@dataclass(frozen=True)
class RegimeAblationEvaluationSpec:
    scorer_identity: str
    scorer_state_hash: str
    threshold: float
    label_column: str
    baseline_feature_hash: str
    shadow_feature_hash: str
    spec_version: str = "regime_ablation_evaluation_v1"

    def to_stage_spec(self) -> StageEvaluationSpec:
        return StageEvaluationSpec(
            stage=OptimizationStage.REGIME_ABLATION,
            spec_type="regime_ablation_evaluation",
            semantic_inputs={
                "scorer_identity": _text(self.scorer_identity, field_name="scorer_identity"),
                "scorer_state_hash": _text(self.scorer_state_hash, field_name="scorer_state_hash"),
                "threshold": _number(self.threshold, field_name="ablation threshold", minimum=0.0),
                "label_column": _text(self.label_column, field_name="label_column"),
                "baseline_feature_hash": _text(self.baseline_feature_hash, field_name="baseline_feature_hash"),
                "shadow_feature_hash": _text(self.shadow_feature_hash, field_name="shadow_feature_hash"),
            },
            spec_version=self.spec_version,
        )


@dataclass(frozen=True)
class MetricRecord:
    name: str
    value: float | None
    numerator: float | None = None
    denominator: float | None = None
    sample_count: int = 0
    valid_row_count: int = 0
    excluded_row_count: int = 0
    undefined_reason: str | None = None
    metric_version: str = "v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, field_name="metric name"))
        if self.value is None:
            if not isinstance(self.undefined_reason, str) or not self.undefined_reason:
                raise ContractValidationError("undefined metric requires undefined_reason")
        else:
            object.__setattr__(self, "value", _number(self.value, field_name="metric value"))
            if self.undefined_reason is not None:
                raise ContractValidationError("defined metric cannot carry undefined_reason")
        for name in ("numerator", "denominator"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _number(value, field_name=f"metric {name}"))
        for name in ("sample_count", "valid_row_count", "excluded_row_count"):
            object.__setattr__(self, name, _integer(getattr(self, name), field_name=f"metric {name}"))
        if self.valid_row_count > self.sample_count:
            raise ContractValidationError("metric valid_row_count cannot exceed sample_count")
        object.__setattr__(self, "metric_version", _text(self.metric_version, field_name="metric version"))

    def to_dict(self) -> dict[str, Any]:
        return primitive(self.__dict__)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MetricRecord":
        return cls(**dict(_required_mapping(value, field_name="MetricRecord")))


@dataclass(frozen=True)
class ObjectiveSpec:
    objective_version: str
    primary_metric: str
    maximize: bool = True
    minimum_sample_count: int = 1
    minimum_fold_coverage: float = 1.0
    maximum_failure_rate: float = 0.0
    worst_window_floor: float | None = None
    worst_window_ceiling: float | None = None
    allowed_degradation: float = 0.0
    maximum_latency_ms: float | None = None
    maximum_churn_rate: float | None = None
    require_comparable_population: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "objective_version", _text(self.objective_version, field_name="objective_version"))
        object.__setattr__(self, "primary_metric", _text(self.primary_metric, field_name="primary_metric"))
        if not isinstance(self.maximize, bool):
            raise ContractValidationError("objective maximize must be boolean")
        object.__setattr__(self, "minimum_sample_count", _integer(self.minimum_sample_count, field_name="minimum_sample_count", minimum=1))
        coverage = _number(self.minimum_fold_coverage, field_name="minimum_fold_coverage", minimum=0.0)
        if coverage > 1.0:
            raise ContractValidationError("minimum_fold_coverage cannot exceed one")
        object.__setattr__(self, "minimum_fold_coverage", coverage)
        failure_rate = _number(self.maximum_failure_rate, field_name="maximum_failure_rate", minimum=0.0)
        if failure_rate > 1.0:
            raise ContractValidationError("maximum_failure_rate cannot exceed one")
        object.__setattr__(self, "maximum_failure_rate", failure_rate)
        if self.worst_window_floor is not None:
            object.__setattr__(self, "worst_window_floor", _number(self.worst_window_floor, field_name="worst_window_floor"))
        if self.worst_window_ceiling is not None:
            object.__setattr__(self, "worst_window_ceiling", _number(self.worst_window_ceiling, field_name="worst_window_ceiling"))
        if self.maximize and self.worst_window_ceiling is not None:
            raise ContractValidationError("maximize objective cannot use worst_window_ceiling")
        if not self.maximize and self.worst_window_floor is not None:
            raise ContractValidationError("minimize objective cannot use worst_window_floor")
        object.__setattr__(self, "allowed_degradation", _number(self.allowed_degradation, field_name="allowed_degradation", minimum=0.0))
        if self.maximum_latency_ms is not None:
            object.__setattr__(self, "maximum_latency_ms", _number(self.maximum_latency_ms, field_name="maximum_latency_ms", minimum=0.0))
        if self.maximum_churn_rate is not None:
            rate = _number(self.maximum_churn_rate, field_name="maximum_churn_rate", minimum=0.0)
            if rate > 1.0:
                raise ContractValidationError("maximum_churn_rate cannot exceed one")
            object.__setattr__(self, "maximum_churn_rate", rate)
        if not isinstance(self.require_comparable_population, bool):
            raise ContractValidationError("require_comparable_population must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return primitive(self.__dict__)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ObjectiveSpec":
        payload = _required_mapping(value, field_name="ObjectiveSpec")
        return cls(**dict(payload))


@dataclass(frozen=True)
class ObjectiveGate:
    """Direction-aware, persisted hard-gate evidence for one result population."""

    objective: ObjectiveSpec
    required_fold_count: int
    defined_primary_fold_count: int
    failed_or_invalid_window_count: int
    evaluated_row_count: int
    primary_value: float | None
    worst_window_value: float | None
    latency_ms: float | None
    churn_rate: float | None
    comparable_population: bool | None
    passed: bool
    rejection_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.objective, ObjectiveSpec):
            raise ContractValidationError("objective gate requires ObjectiveSpec")
        for name in ("required_fold_count", "defined_primary_fold_count", "failed_or_invalid_window_count", "evaluated_row_count"):
            object.__setattr__(self, name, _integer(getattr(self, name), field_name=name))
        if self.defined_primary_fold_count > self.required_fold_count or self.failed_or_invalid_window_count > self.required_fold_count:
            raise ContractValidationError("objective gate fold counts are inconsistent")
        for name in ("primary_value", "worst_window_value", "latency_ms", "churn_rate"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _number(value, field_name=name, minimum=0.0 if name in {"latency_ms", "churn_rate"} else None))
        if self.churn_rate is not None and self.churn_rate > 1.0:
            raise ContractValidationError("objective gate churn_rate cannot exceed one")
        if self.comparable_population is not None and not isinstance(self.comparable_population, bool):
            raise ContractValidationError("objective gate comparable_population must be bool or None")
        if not isinstance(self.passed, bool):
            raise ContractValidationError("objective gate passed must be boolean")
        reasons = tuple(_text(reason, field_name="objective gate rejection reason") for reason in self.rejection_reasons)
        if len(set(reasons)) != len(reasons):
            raise ContractValidationError("objective gate rejection reasons must be unique")
        if self.passed and reasons:
            raise ContractValidationError("passing objective gate cannot carry rejection reasons")
        if not self.passed and not reasons:
            raise ContractValidationError("failing objective gate requires rejection reasons")
        intrinsic_reasons = self._intrinsic_rejection_reasons()
        if self.passed and intrinsic_reasons:
            raise ContractValidationError("passing objective gate contradicts derived gate fields")
        if not self.passed and not intrinsic_reasons.issubset(set(reasons)):
            raise ContractValidationError("objective gate omits derived rejection reasons")
        object.__setattr__(self, "rejection_reasons", tuple(sorted(reasons)))

    def _intrinsic_rejection_reasons(self) -> set[str]:
        coverage = self.fold_coverage_ratio
        failure_rate = self.failure_rate
        reasons: set[str] = set()
        if coverage < self.objective.minimum_fold_coverage:
            reasons.add("minimum_fold_coverage_not_met")
        if failure_rate > self.objective.maximum_failure_rate:
            reasons.add("maximum_failure_rate_exceeded")
        if self.primary_value is None:
            reasons.add("primary_metric_undefined")
        if self.objective.worst_window_floor is not None and (
            self.worst_window_value is None or self.worst_window_value < self.objective.worst_window_floor
        ):
            reasons.add("worst_window_floor_not_met")
        if self.objective.worst_window_ceiling is not None and (
            self.worst_window_value is None or self.worst_window_value > self.objective.worst_window_ceiling
        ):
            reasons.add("worst_window_ceiling_exceeded")
        if self.objective.maximum_latency_ms is not None and (
            self.latency_ms is None or self.latency_ms > self.objective.maximum_latency_ms
        ):
            reasons.add("maximum_latency_ms_exceeded")
        if self.objective.maximum_churn_rate is not None and (
            self.churn_rate is None or self.churn_rate > self.objective.maximum_churn_rate
        ):
            reasons.add("maximum_churn_rate_exceeded")
        if self.objective.require_comparable_population and self.comparable_population is False:
            reasons.add("population_not_comparable")
        return reasons

    @property
    def fold_coverage_ratio(self) -> float:
        return 0.0 if self.required_fold_count == 0 else self.defined_primary_fold_count / self.required_fold_count

    @property
    def failure_rate(self) -> float:
        return 0.0 if self.required_fold_count == 0 else self.failed_or_invalid_window_count / self.required_fold_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective.to_dict(),
            "required_fold_count": self.required_fold_count,
            "defined_primary_fold_count": self.defined_primary_fold_count,
            "failed_or_invalid_window_count": self.failed_or_invalid_window_count,
            "evaluated_row_count": self.evaluated_row_count,
            "primary_value": self.primary_value,
            "worst_window_value": self.worst_window_value,
            "latency_ms": self.latency_ms,
            "churn_rate": self.churn_rate,
            "comparable_population": self.comparable_population,
            "fold_coverage_ratio": self.fold_coverage_ratio,
            "failure_rate": self.failure_rate,
            "passed": self.passed,
            "rejection_reasons": self.rejection_reasons,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ObjectiveGate":
        payload = _required_mapping(value, field_name="ObjectiveGate")
        return cls(
            objective=ObjectiveSpec.from_dict(_required_mapping(payload.get("objective"), field_name="ObjectiveGate.objective")),
            required_fold_count=payload.get("required_fold_count"),
            defined_primary_fold_count=payload.get("defined_primary_fold_count"),
            failed_or_invalid_window_count=payload.get("failed_or_invalid_window_count"),
            evaluated_row_count=payload.get("evaluated_row_count"),
            primary_value=payload.get("primary_value"),
            worst_window_value=payload.get("worst_window_value"),
            latency_ms=payload.get("latency_ms"),
            churn_rate=payload.get("churn_rate"),
            comparable_population=payload.get("comparable_population"),
            passed=payload.get("passed"),
            rejection_reasons=tuple(payload.get("rejection_reasons", ())),
        )


@dataclass(frozen=True)
class TrialConfig:
    stage: OptimizationStage | str
    asset: str
    timeframe: str
    parameter_overrides: Mapping[str, Any]
    baseline_config_hash: str
    dataset_hash: str
    fold_plan_id: str
    objective: ObjectiveSpec
    model_version: str
    config_version: str
    seed: int = 0
    evaluation_context: Mapping[str, Any] = field(default_factory=dict)
    evaluation_spec: StageEvaluationSpec | None = None
    trial_kind: str = "primary"
    counterfactual_of_trial_id: str | None = None
    reverted_parameter: str | None = None
    trial_config_hash: str | None = None
    trial_id: str | None = None

    def __post_init__(self) -> None:
        try:
            stage = OptimizationStage(self.stage)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(f"invalid optimization stage: {self.stage!r}") from exc
        object.__setattr__(self, "stage", stage)
        for name in ("asset", "timeframe", "baseline_config_hash", "dataset_hash", "fold_plan_id", "model_version", "config_version"):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        object.__setattr__(self, "parameter_overrides", freeze(self.parameter_overrides, field_name="parameter_overrides"))
        if not isinstance(self.objective, ObjectiveSpec):
            raise ContractValidationError("trial objective must be ObjectiveSpec")
        object.__setattr__(self, "seed", _integer(self.seed, field_name="seed"))
        object.__setattr__(self, "evaluation_context", freeze(self.evaluation_context, field_name="evaluation_context"))
        spec = self.evaluation_spec or StageEvaluationSpec(
            stage=self.stage,
            spec_type="generic_offline_evaluator",
            semantic_inputs=self.evaluation_context,
        )
        if not isinstance(spec, StageEvaluationSpec) or spec.stage is not self.stage:
            raise ContractValidationError("trial evaluation_spec must match trial stage")
        object.__setattr__(self, "evaluation_spec", spec)
        if self.trial_kind not in {"primary", "counterfactual"}:
            raise ContractValidationError("trial_kind must be primary or counterfactual")
        if self.trial_kind == "primary":
            if self.counterfactual_of_trial_id is not None or self.reverted_parameter is not None:
                raise ContractValidationError("primary trial cannot declare counterfactual fields")
        else:
            object.__setattr__(self, "counterfactual_of_trial_id", _text(self.counterfactual_of_trial_id, field_name="counterfactual_of_trial_id"))
            object.__setattr__(self, "reverted_parameter", _text(self.reverted_parameter, field_name="reverted_parameter"))
        expected_config_hash = semantic_id(
            "trendline-family-trial-config",
            {
                "stage": self.stage,
                "baseline_config_hash": self.baseline_config_hash,
                "parameter_overrides": self.parameter_overrides,
                "evaluation_context": self.evaluation_context,
                "evaluation_spec": spec.to_dict(),
                "trial_kind": self.trial_kind,
                "counterfactual_of_trial_id": self.counterfactual_of_trial_id,
                "reverted_parameter": self.reverted_parameter,
            },
        )
        if self.trial_config_hash is not None and self.trial_config_hash != expected_config_hash:
            raise ContractValidationError("trial_config_hash does not match baseline and overrides")
        object.__setattr__(self, "trial_config_hash", expected_config_hash)
        expected = semantic_id("trendline-family-trial", self.identity_payload())
        if self.trial_id is not None and self.trial_id != expected:
            raise ContractValidationError("trial_id does not match semantic trial request")
        object.__setattr__(self, "trial_id", expected)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": OPTIMIZATION_SCHEMA_VERSION,
            "stage": self.stage,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "parameter_overrides": self.parameter_overrides,
            "baseline_config_hash": self.baseline_config_hash,
            "trial_config_hash": self.trial_config_hash,
            "dataset_hash": self.dataset_hash,
            "fold_plan_id": self.fold_plan_id,
            "objective": self.objective.to_dict(),
            "model_version": self.model_version,
            "config_version": self.config_version,
            "seed": self.seed,
            "evaluation_context": self.evaluation_context,
            "evaluation_spec": self.evaluation_spec.to_dict(),
            "trial_kind": self.trial_kind,
            "counterfactual_of_trial_id": self.counterfactual_of_trial_id,
            "reverted_parameter": self.reverted_parameter,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**primitive(self.identity_payload()), "trial_id": self.trial_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TrialConfig":
        payload = _required_mapping(value, field_name="TrialConfig")
        return cls(
            stage=payload.get("stage"), asset=payload.get("asset"), timeframe=payload.get("timeframe"),
            parameter_overrides=payload.get("parameter_overrides", {}), baseline_config_hash=payload.get("baseline_config_hash"),
            dataset_hash=payload.get("dataset_hash"), fold_plan_id=payload.get("fold_plan_id"),
            objective=ObjectiveSpec.from_dict(_required_mapping(payload.get("objective"), field_name="TrialConfig.objective")),
            model_version=payload.get("model_version"), config_version=payload.get("config_version"), seed=payload.get("seed", 0),
            evaluation_context=payload.get("evaluation_context", {}),
            evaluation_spec=StageEvaluationSpec.from_dict(_required_mapping(payload.get("evaluation_spec"), field_name="TrialConfig.evaluation_spec")),
            trial_kind=payload.get("trial_kind", "primary"), counterfactual_of_trial_id=payload.get("counterfactual_of_trial_id"),
            reverted_parameter=payload.get("reverted_parameter"), trial_config_hash=payload.get("trial_config_hash"), trial_id=payload.get("trial_id"),
        )


@dataclass(frozen=True)
class WindowResult:
    trial_id: str
    fold_id: str
    window_kind: str
    metrics: tuple[MetricRecord, ...]
    evaluated_bar_count: int
    excluded_reasons: Mapping[str, int] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    result_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "trial_id", _text(self.trial_id, field_name="trial_id"))
        object.__setattr__(self, "fold_id", _text(self.fold_id, field_name="fold_id"))
        if self.window_kind not in {"validation", "holdout"}:
            raise ContractValidationError("window_kind must be validation or holdout")
        metrics = tuple(self.metrics)
        if not metrics or any(not isinstance(metric, MetricRecord) for metric in metrics):
            raise ContractValidationError("window result requires MetricRecord values")
        if len({metric.name for metric in metrics}) != len(metrics):
            raise ContractValidationError("window metric names must be unique")
        object.__setattr__(self, "metrics", tuple(sorted(metrics, key=lambda metric: metric.name)))
        object.__setattr__(self, "evaluated_bar_count", _integer(self.evaluated_bar_count, field_name="evaluated_bar_count"))
        reasons = freeze(self.excluded_reasons, field_name="excluded_reasons")
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in reasons.values()):
            raise ContractValidationError("excluded reasons must map to non-negative integers")
        object.__setattr__(self, "excluded_reasons", reasons)
        if set(self.diagnostics).intersection(_OPERATIONAL_DIAGNOSTIC_KEYS):
            raise ContractValidationError("operational diagnostics belong on TrialResult, not WindowResult")
        object.__setattr__(self, "diagnostics", freeze(self.diagnostics, field_name="diagnostics"))
        expected = semantic_id("trendline-family-window-result", self.identity_payload())
        if self.result_id is not None and self.result_id != expected:
            raise ContractValidationError("window result_id does not match semantic payload")
        object.__setattr__(self, "result_id", expected)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "fold_id": self.fold_id,
            "window_kind": self.window_kind,
            "metrics": [metric.to_dict() for metric in self.metrics],
            "evaluated_bar_count": self.evaluated_bar_count,
            "excluded_reasons": self.excluded_reasons,
            "diagnostics": self.diagnostics,
        }

    def metric(self, name: str) -> MetricRecord | None:
        return next((metric for metric in self.metrics if metric.name == name), None)

    def to_dict(self) -> dict[str, Any]:
        return {**primitive(self.identity_payload()), "result_id": self.result_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WindowResult":
        payload = _required_mapping(value, field_name="WindowResult")
        return cls(
            trial_id=payload.get("trial_id"), fold_id=payload.get("fold_id"), window_kind=payload.get("window_kind"),
            metrics=tuple(MetricRecord.from_dict(item) for item in payload.get("metrics", ())),
            evaluated_bar_count=payload.get("evaluated_bar_count"), excluded_reasons=payload.get("excluded_reasons", {}),
            diagnostics=payload.get("diagnostics", {}), result_id=payload.get("result_id"),
        )


@dataclass(frozen=True)
class ParameterEffectAudit:
    parameter_name: str
    owning_stage: OptimizationStage | str
    baseline_value: Any
    trial_value: Any
    expected_affected_outputs: tuple[str, ...]
    observed_changed_outputs: tuple[str, ...]
    forbidden_outputs_checked: tuple[str, ...]
    effect_detected: bool
    leakage_detected: bool
    decision: PromotionDecision | str
    counterfactual_trial_id: str
    counterfactual_result_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameter_name", _text(self.parameter_name, field_name="parameter_name"))
        try:
            object.__setattr__(self, "owning_stage", OptimizationStage(self.owning_stage))
            object.__setattr__(self, "decision", PromotionDecision(self.decision))
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("invalid parameter effect enum") from exc
        for name in ("expected_affected_outputs", "observed_changed_outputs", "forbidden_outputs_checked"):
            values = tuple(_text(item, field_name=name) for item in getattr(self, name))
            if len(set(values)) != len(values):
                raise ContractValidationError(f"{name} must be unique")
            object.__setattr__(self, name, tuple(sorted(values)))
        if not isinstance(self.effect_detected, bool) or not isinstance(self.leakage_detected, bool):
            raise ContractValidationError("parameter effect booleans must be bool")
        object.__setattr__(self, "baseline_value", freeze(self.baseline_value, field_name="baseline_value"))
        object.__setattr__(self, "trial_value", freeze(self.trial_value, field_name="trial_value"))
        object.__setattr__(self, "counterfactual_trial_id", _text(self.counterfactual_trial_id, field_name="counterfactual_trial_id"))
        object.__setattr__(self, "counterfactual_result_id", _text(self.counterfactual_result_id, field_name="counterfactual_result_id"))
        if self.decision is PromotionDecision.HOLD:
            raise ContractValidationError("parameter audit decision must be promote or reject")
        if self.decision is PromotionDecision.PROMOTE and (not self.effect_detected or self.leakage_detected):
            raise ContractValidationError("promoted parameter audit requires a detected isolated effect")
        if self.decision is PromotionDecision.REJECT and self.effect_detected and not self.leakage_detected:
            raise ContractValidationError("rejected parameter audit must record no effect or leakage")

    def to_dict(self) -> dict[str, Any]:
        return primitive(self.__dict__)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ParameterEffectAudit":
        payload = _required_mapping(value, field_name="ParameterEffectAudit")
        return cls(**dict(payload))


@dataclass(frozen=True)
class TrialResult:
    trial: TrialConfig
    status: TrialStatus | str
    window_results: tuple[WindowResult, ...] = ()
    aggregate_metrics: Mapping[str, MetricRecord] = field(default_factory=dict)
    parameter_effect_audits: tuple[ParameterEffectAudit, ...] = ()
    failure_code: FailureCode | str | None = None
    failure_reason: str | None = None
    runtime_diagnostics: Mapping[str, Any] = field(default_factory=dict)
    objective_gate: ObjectiveGate | None = None
    counterfactual_results: tuple["TrialResult", ...] = ()
    result_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.trial, TrialConfig):
            raise ContractValidationError("trial result requires TrialConfig")
        try:
            status = TrialStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("invalid trial status") from exc
        windows = tuple(self.window_results)
        if any(not isinstance(window, WindowResult) for window in windows):
            raise ContractValidationError("window_results must contain WindowResult values")
        if any(window.trial_id != self.trial.trial_id for window in windows):
            raise ContractValidationError("window result trial identity mismatch")
        if len({window.result_id for window in windows}) != len(windows):
            raise ContractValidationError("window results must be unique")
        object.__setattr__(self, "window_results", tuple(sorted(windows, key=lambda item: (item.window_kind, item.fold_id, item.result_id))))
        if not isinstance(self.aggregate_metrics, Mapping) or any(not isinstance(key, str) or not key for key in self.aggregate_metrics):
            raise ContractValidationError("aggregate_metrics must be a mapping with non-empty names")
        metrics = dict(self.aggregate_metrics)
        if any(not isinstance(item, MetricRecord) for item in metrics.values()):
            raise ContractValidationError("aggregate_metrics must map to MetricRecord values")
        object.__setattr__(self, "aggregate_metrics", MappingProxyType(dict(sorted(metrics.items()))))
        audits = tuple(self.parameter_effect_audits)
        if any(not isinstance(audit, ParameterEffectAudit) for audit in audits):
            raise ContractValidationError("parameter_effect_audits must be canonical")
        object.__setattr__(self, "parameter_effect_audits", tuple(sorted(audits, key=lambda item: item.parameter_name)))
        if status in {TrialStatus.FAILED, TrialStatus.INVALID, TrialStatus.REJECTED}:
            if self.failure_code is None or not isinstance(self.failure_reason, str) or not self.failure_reason:
                raise ContractValidationError("failed, invalid, or rejected trial requires failure evidence")
        elif self.failure_code is not None or self.failure_reason is not None:
            raise ContractValidationError("completed trial cannot carry failure evidence")
        if self.failure_code is not None:
            try:
                object.__setattr__(self, "failure_code", FailureCode(self.failure_code))
            except (TypeError, ValueError) as exc:
                raise ContractValidationError("invalid failure code") from exc
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "runtime_diagnostics", freeze(self.runtime_diagnostics, field_name="runtime_diagnostics"))
        if self.objective_gate is not None and not isinstance(self.objective_gate, ObjectiveGate):
            raise ContractValidationError("objective_gate must be ObjectiveGate")
        counterfactuals = tuple(self.counterfactual_results)
        if any(not isinstance(item, TrialResult) for item in counterfactuals):
            raise ContractValidationError("counterfactual_results must contain TrialResult values")
        if any(item.trial.trial_kind != "counterfactual" for item in counterfactuals):
            raise ContractValidationError("counterfactual result must use counterfactual trial kind")
        if len({item.trial.trial_id for item in counterfactuals}) != len(counterfactuals):
            raise ContractValidationError("counterfactual trial IDs must be unique")
        object.__setattr__(self, "counterfactual_results", tuple(sorted(counterfactuals, key=lambda item: item.trial.trial_id)))
        counterfactual_by_id = {item.trial.trial_id: item for item in counterfactuals}
        for audit in audits:
            counterfactual = counterfactual_by_id.get(audit.counterfactual_trial_id)
            if counterfactual is None or counterfactual.result_id != audit.counterfactual_result_id:
                raise ContractValidationError("parameter audit must bind a persisted counterfactual result")
            if counterfactual.trial.counterfactual_of_trial_id != self.trial.trial_id:
                raise ContractValidationError("counterfactual trial must bind its full trial")
            if counterfactual.trial.reverted_parameter != audit.parameter_name:
                raise ContractValidationError("counterfactual reverted parameter does not match audit")
        expected = semantic_id("trendline-family-trial-result", self.identity_payload())
        if self.result_id is not None and self.result_id != expected:
            raise ContractValidationError("trial result_id does not match semantic result")
        object.__setattr__(self, "result_id", expected)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "trial": self.trial.to_dict(),
            "status": self.status,
            "window_results": [window.to_dict() for window in self.window_results],
            "aggregate_metrics": {key: metric.to_dict() for key, metric in self.aggregate_metrics.items()},
            "parameter_effect_audits": [audit.to_dict() for audit in self.parameter_effect_audits],
            "failure_code": self.failure_code,
            "failure_reason": self.failure_reason,
            "objective_gate": None if self.objective_gate is None else self.objective_gate.to_dict(),
            "counterfactual_results": [item.to_dict() for item in self.counterfactual_results],
        }

    def metric(self, name: str) -> MetricRecord | None:
        return self.aggregate_metrics.get(name)

    def to_dict(self) -> dict[str, Any]:
        return {
            **primitive(self.identity_payload()),
            "runtime_diagnostics": primitive(self.runtime_diagnostics),
            "result_id": self.result_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TrialResult":
        payload = _required_mapping(value, field_name="TrialResult")
        return cls(
            trial=TrialConfig.from_dict(_required_mapping(payload.get("trial"), field_name="TrialResult.trial")),
            status=payload.get("status"), window_results=tuple(WindowResult.from_dict(item) for item in payload.get("window_results", ())),
            aggregate_metrics={key: MetricRecord.from_dict(item) for key, item in _required_mapping(payload.get("aggregate_metrics", {}), field_name="TrialResult.aggregate_metrics").items()},
            parameter_effect_audits=tuple(ParameterEffectAudit.from_dict(item) for item in payload.get("parameter_effect_audits", ())),
            failure_code=payload.get("failure_code"), failure_reason=payload.get("failure_reason"),
            runtime_diagnostics=payload.get("runtime_diagnostics", {}),
            objective_gate=None if payload.get("objective_gate") is None else ObjectiveGate.from_dict(_required_mapping(payload.get("objective_gate"), field_name="TrialResult.objective_gate")),
            counterfactual_results=tuple(TrialResult.from_dict(item) for item in payload.get("counterfactual_results", ())),
            result_id=payload.get("result_id"),
        )


@dataclass(frozen=True)
class FinalistFreeze:
    """Validation-only finalist identity required before a holdout can open."""

    stage: OptimizationStage | str
    fold_plan_id: str
    baseline_validation_result_id: str
    finalist_validation_result_id: str
    objective: ObjectiveSpec
    evaluation_spec_id: str
    freeze_id: str | None = None

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "stage", OptimizationStage(self.stage))
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("invalid finalist freeze stage") from exc
        for name in (
            "fold_plan_id",
            "baseline_validation_result_id",
            "finalist_validation_result_id",
            "evaluation_spec_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        if not isinstance(self.objective, ObjectiveSpec):
            raise ContractValidationError("finalist freeze requires ObjectiveSpec")
        expected = semantic_id("trendline-family-finalist-freeze", self.identity_payload())
        if self.freeze_id is not None and self.freeze_id != expected:
            raise ContractValidationError("freeze_id does not match validation finalist")
        object.__setattr__(self, "freeze_id", expected)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "fold_plan_id": self.fold_plan_id,
            "baseline_validation_result_id": self.baseline_validation_result_id,
            "finalist_validation_result_id": self.finalist_validation_result_id,
            "objective": self.objective.to_dict(),
            "evaluation_spec_id": self.evaluation_spec_id,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**primitive(self.identity_payload()), "freeze_id": self.freeze_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FinalistFreeze":
        payload = _required_mapping(value, field_name="FinalistFreeze")
        return cls(
            stage=payload.get("stage"),
            fold_plan_id=payload.get("fold_plan_id"),
            baseline_validation_result_id=payload.get("baseline_validation_result_id"),
            finalist_validation_result_id=payload.get("finalist_validation_result_id"),
            objective=ObjectiveSpec.from_dict(_required_mapping(payload.get("objective"), field_name="FinalistFreeze.objective")),
            evaluation_spec_id=payload.get("evaluation_spec_id"),
            freeze_id=payload.get("freeze_id"),
        )


@dataclass(frozen=True)
class HoldoutOpenAudit:
    """Immutable audit proving a holdout evaluation followed finalist freeze."""

    finalist_freeze_id: str
    holdout_plan_id: str
    target: str
    trial_id: str
    validation_result_id: str
    open_reason: str = "frozen_validation_finalist"
    audit_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("finalist_freeze_id", "holdout_plan_id", "trial_id", "validation_result_id", "open_reason"):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        if self.target not in {"baseline", "finalist"}:
            raise ContractValidationError("holdout target must be baseline or finalist")
        expected = semantic_id("trendline-family-holdout-open-audit", self.identity_payload())
        if self.audit_id is not None and self.audit_id != expected:
            raise ContractValidationError("holdout audit_id does not match semantic request")
        object.__setattr__(self, "audit_id", expected)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "finalist_freeze_id": self.finalist_freeze_id,
            "holdout_plan_id": self.holdout_plan_id,
            "target": self.target,
            "trial_id": self.trial_id,
            "validation_result_id": self.validation_result_id,
            "open_reason": self.open_reason,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**primitive(self.identity_payload()), "audit_id": self.audit_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HoldoutOpenAudit":
        return cls(**dict(_required_mapping(value, field_name="HoldoutOpenAudit")))


@dataclass(frozen=True)
class PromotionRecommendation:
    stage: OptimizationStage | str
    baseline_result_id: str
    finalist_result_id: str | None
    decision: PromotionDecision | str
    rationale: tuple[str, ...]
    validation_evidence: Mapping[str, Any]
    holdout_evidence: Mapping[str, Any]
    parameter_effect_audits: tuple[ParameterEffectAudit, ...]
    config_patch_preview: Mapping[str, Any] = field(default_factory=dict)
    active_consumption_patch_preview: Mapping[str, Any] = field(default_factory=dict)
    required_human_approvals: tuple[str, ...] = ("quant_review", "human_runtime_promotion")
    baseline_holdout_result_id: str | None = None
    finalist_holdout_result_id: str | None = None
    baseline_validation_gate: ObjectiveGate | None = None
    finalist_validation_gate: ObjectiveGate | None = None
    baseline_holdout_gate: ObjectiveGate | None = None
    finalist_holdout_gate: ObjectiveGate | None = None
    promotion_gate_passed: bool = False
    recommendation_id: str | None = None

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "stage", OptimizationStage(self.stage))
            object.__setattr__(self, "decision", PromotionDecision(self.decision))
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("invalid recommendation enum") from exc
        object.__setattr__(self, "baseline_result_id", _text(self.baseline_result_id, field_name="baseline_result_id"))
        if self.finalist_result_id is not None:
            object.__setattr__(self, "finalist_result_id", _text(self.finalist_result_id, field_name="finalist_result_id"))
        for name in ("baseline_holdout_result_id", "finalist_holdout_result_id"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _text(value, field_name=name))
        rationale = tuple(_text(item, field_name="rationale") for item in self.rationale)
        if not rationale:
            raise ContractValidationError("promotion recommendation requires rationale")
        object.__setattr__(self, "rationale", rationale)
        for name in ("validation_evidence", "holdout_evidence", "config_patch_preview", "active_consumption_patch_preview"):
            object.__setattr__(self, name, freeze(getattr(self, name), field_name=name))
        audits = tuple(self.parameter_effect_audits)
        if any(not isinstance(audit, ParameterEffectAudit) for audit in audits):
            raise ContractValidationError("recommendation audits must be canonical")
        object.__setattr__(self, "parameter_effect_audits", tuple(sorted(audits, key=lambda item: item.parameter_name)))
        approvals = tuple(_text(item, field_name="required_human_approvals") for item in self.required_human_approvals)
        object.__setattr__(self, "required_human_approvals", tuple(sorted(set(approvals))))
        for name in (
            "baseline_validation_gate",
            "finalist_validation_gate",
            "baseline_holdout_gate",
            "finalist_holdout_gate",
        ):
            gate = getattr(self, name)
            if gate is not None and not isinstance(gate, ObjectiveGate):
                raise ContractValidationError(f"{name} must be an ObjectiveGate")
        if not isinstance(self.promotion_gate_passed, bool):
            raise ContractValidationError("promotion_gate_passed must be boolean")
        if self.decision is PromotionDecision.PROMOTE:
            gates = (
                self.baseline_validation_gate,
                self.finalist_validation_gate,
                self.baseline_holdout_gate,
                self.finalist_holdout_gate,
            )
            if (
                self.finalist_result_id is None
                or self.baseline_holdout_result_id is None
                or self.finalist_holdout_result_id is None
                or not self.promotion_gate_passed
                or any(gate is None or not gate.passed for gate in gates)
                or any(not audit.effect_detected or audit.leakage_detected for audit in audits)
            ):
                raise ContractValidationError("promote requires complete passing validation and holdout gate evidence")
        expected = semantic_id("trendline-family-promotion-recommendation", self.identity_payload())
        if self.recommendation_id is not None and self.recommendation_id != expected:
            raise ContractValidationError("recommendation_id does not match complete evidence")
        object.__setattr__(self, "recommendation_id", expected)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": OPTIMIZATION_SCHEMA_VERSION,
            "stage": self.stage,
            "baseline_result_id": self.baseline_result_id,
            "finalist_result_id": self.finalist_result_id,
            "decision": self.decision,
            "rationale": self.rationale,
            "validation_evidence": semantic_payload(self.validation_evidence),
            "holdout_evidence": semantic_payload(self.holdout_evidence),
            "parameter_effect_audits": [audit.to_dict() for audit in self.parameter_effect_audits],
            "config_patch_preview": self.config_patch_preview,
            "active_consumption_patch_preview": self.active_consumption_patch_preview,
            "required_human_approvals": self.required_human_approvals,
            "baseline_holdout_result_id": self.baseline_holdout_result_id,
            "finalist_holdout_result_id": self.finalist_holdout_result_id,
            "baseline_validation_gate": None if self.baseline_validation_gate is None else self.baseline_validation_gate.to_dict(),
            "finalist_validation_gate": None if self.finalist_validation_gate is None else self.finalist_validation_gate.to_dict(),
            "baseline_holdout_gate": None if self.baseline_holdout_gate is None else self.baseline_holdout_gate.to_dict(),
            "finalist_holdout_gate": None if self.finalist_holdout_gate is None else self.finalist_holdout_gate.to_dict(),
            "promotion_gate_passed": self.promotion_gate_passed,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**primitive(self.identity_payload()), "recommendation_id": self.recommendation_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PromotionRecommendation":
        payload = _required_mapping(value, field_name="PromotionRecommendation")

        def gate(name: str) -> ObjectiveGate | None:
            raw = payload.get(name)
            return None if raw is None else ObjectiveGate.from_dict(_required_mapping(raw, field_name=name))

        return cls(
            stage=payload.get("stage"),
            baseline_result_id=payload.get("baseline_result_id"),
            finalist_result_id=payload.get("finalist_result_id"),
            decision=payload.get("decision"),
            rationale=tuple(payload.get("rationale", ())),
            validation_evidence=payload.get("validation_evidence", {}),
            holdout_evidence=payload.get("holdout_evidence", {}),
            parameter_effect_audits=tuple(ParameterEffectAudit.from_dict(item) for item in payload.get("parameter_effect_audits", ())),
            config_patch_preview=payload.get("config_patch_preview", {}),
            active_consumption_patch_preview=payload.get("active_consumption_patch_preview", {}),
            required_human_approvals=tuple(payload.get("required_human_approvals", ())),
            baseline_holdout_result_id=payload.get("baseline_holdout_result_id"),
            finalist_holdout_result_id=payload.get("finalist_holdout_result_id"),
            baseline_validation_gate=gate("baseline_validation_gate"),
            finalist_validation_gate=gate("finalist_validation_gate"),
            baseline_holdout_gate=gate("baseline_holdout_gate"),
            finalist_holdout_gate=gate("finalist_holdout_gate"),
            promotion_gate_passed=payload.get("promotion_gate_passed", False),
            recommendation_id=payload.get("recommendation_id"),
        )


__all__ = [
    "FailureCode",
    "FeatureGroup",
    "FinalistFreeze",
    "HoldoutOpenAudit",
    "MetricRecord",
    "OPTIMIZATION_SCHEMA_VERSION",
    "ObjectiveSpec",
    "ObjectiveGate",
    "OptimizationDirection",
    "OptimizationStage",
    "ParameterEffectAudit",
    "PromotionDecision",
    "PromotionRecommendation",
    "TrialConfig",
    "TrialResult",
    "TrialStatus",
    "WindowResult",
    "StageEvaluationSpec",
    "CandidateEvaluationSpec",
    "TrackerEvaluationSpec",
    "InteractionEvaluationSpec",
    "RegimeAblationEvaluationSpec",
    "canonical_json",
    "freeze",
    "primitive",
    "semantic_payload",
    "semantic_id",
]
