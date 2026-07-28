"""Immutable contracts for causal trendline adequacy measurement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from typing import Any

import pandas as pd

from libs.models.trendlines.contracts.identity import canonical_hash
from ..contracts import PreparedTrendlineResearchRun
from ..replay import (
    PreparedTrendlineResearchReplay,
    TrendlineReplayPoint,
    validate_replay_point_integrity,
)
from .baselines import TrendlineAdequacyBaselineSpec


ADEQUACY_STUDY_CONFIG_SEMANTICS_VERSION = "trendlines.adequacy-study-config.v1"
ADEQUACY_COHORT_SEMANTICS_VERSION = "trendlines.adequacy-cohort.v1"
ADEQUACY_OBSERVATION_SEMANTICS_VERSION = "trendlines.adequacy-observation.v1"


class TrendlineAdequacyContractError(ValueError):
    """Raised when an adequacy scope or observation violates its contract."""


class TrendlineAdequacyAvailabilityError(TrendlineAdequacyContractError):
    """Raised when a replay point is not knowledge-time causal."""


class TrendlineAdequacyAvailabilityPolicy(str, Enum):
    """Availability policy permitted by L2-D1."""

    CAUSAL_PREFIX_ONLY = "causal_prefix_only"


class TrendlineInvalidPointTreatment(str, Enum):
    """Treatment for invalid model observations."""

    RETAIN_AND_REPORT_EXCLUDE_FROM_GEOMETRY_METRICS = (
        "retain_and_report_exclude_from_geometry_metrics"
    )


class TrendlineObservationUnit(str, Enum):
    """Stable unit names for later line/ray measurements."""

    FITTED_LINE = "fitted_line"
    BOUNDARY_RAY = "boundary_ray"


class TrendlineAdequacyOutcome(str, Enum):
    """Permitted future decision vocabulary; never selected by L2-D1."""

    ADEQUATE_FOR_FURTHER_RESEARCH = "adequate_for_further_research"
    STRUCTURALLY_STABLE_BUT_NO_UTILITY = "structurally_stable_but_no_utility"
    UTILITY_NOT_BETTER_THAN_NAIVE_NULL = "utility_not_better_than_naive_null"
    INSUFFICIENT_COVERAGE = "insufficient_coverage"
    EXCESSIVE_GEOMETRY_CHURN = "excessive_geometry_churn"
    INCONCLUSIVE_INSUFFICIENT_EVIDENCE = "inconclusive_insufficient_evidence"


class TrendlineAdequacyMetricPhase(str, Enum):
    FOUNDATION = "foundation"
    STRUCTURAL_STABILITY = "structural_stability"
    INTERACTION_UTILITY = "interaction_utility"
    BASELINE_COMPARISON = "baseline_comparison"
    ROBUSTNESS = "robustness"


class TrendlineAdequacyMetricDirection(str, Enum):
    DESCRIPTIVE = "descriptive"
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class TrendlineAdequacyOperator(str, Enum):
    GREATER_THAN_OR_EQUAL = "ge"
    LESS_THAN_OR_EQUAL = "le"
    EQUAL = "eq"


KNOWN_ADEQUACY_METRIC_NAMES = (
    "eligible_point_coverage",
    "invalid_point_rate",
    "line_observation_count",
    "ray_observation_count",
    "line_birth_rate",
    "revision_churn_rate",
    "anchor_persistence_rate",
    "touch_rate",
    "rejection_rate",
    "penetration_depth",
    "confirmed_break_rate",
    "false_break_rate",
    "favourable_excursion",
    "adverse_excursion",
    "null_lift",
    "cohort_stability",
)


def _as_utc(value: Any, *, name: str) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise TrendlineAdequacyAvailabilityError(
            f"{name} must be timezone-aware"
        )
    return timestamp.tz_convert("UTC").to_pydatetime()


def _strict_int(value: Any, *, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TrendlineAdequacyContractError(
            f"{name} must be a non-boolean integer"
        )
    if value < minimum:
        raise TrendlineAdequacyContractError(
            f"{name} must be >= {minimum}"
        )
    return value


@dataclass(frozen=True)
class TrendlineAdequacyMetricDefinition:
    """Frozen metadata for one metric; it does not calculate the metric."""

    name: str
    phase: TrendlineAdequacyMetricPhase
    unit: str
    direction: TrendlineAdequacyMetricDirection
    requires_future_rows: bool
    description: str

    def __post_init__(self) -> None:
        name = str(self.name).strip()
        unit = str(self.unit).strip()
        description = str(self.description).strip()
        if not name or not unit or not description:
            raise TrendlineAdequacyContractError(
                "metric name, unit and description are required"
            )
        if name not in KNOWN_ADEQUACY_METRIC_NAMES:
            raise TrendlineAdequacyContractError(f"unknown adequacy metric: {name}")
        if not isinstance(self.phase, TrendlineAdequacyMetricPhase):
            raise TrendlineAdequacyContractError("metric phase must be typed")
        if not isinstance(self.direction, TrendlineAdequacyMetricDirection):
            raise TrendlineAdequacyContractError("metric direction must be typed")
        if not isinstance(self.requires_future_rows, bool):
            raise TrendlineAdequacyContractError(
                "requires_future_rows must be a bool"
            )
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "unit", unit)
        object.__setattr__(self, "description", description)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "phase": self.phase.value,
            "unit": self.unit,
            "direction": self.direction.value,
            "requires_future_rows": self.requires_future_rows,
            "description": self.description,
        }


@dataclass(frozen=True)
class TrendlineAdequacyWindow:
    """Recorded-position scope and minimum history requirements for one timeframe."""

    timeframe: str
    start_position: int
    end_position: int
    minimum_warmup_bars: int
    minimum_prior_executed_prefixes: int

    def __post_init__(self) -> None:
        timeframe = str(self.timeframe).strip()
        if not timeframe:
            raise TrendlineAdequacyContractError("adequacy timeframe is required")
        start = _strict_int(self.start_position, name="start_position")
        end = _strict_int(self.end_position, name="end_position")
        warmup = _strict_int(
            self.minimum_warmup_bars,
            name="minimum_warmup_bars",
        )
        history = _strict_int(
            self.minimum_prior_executed_prefixes,
            name="minimum_prior_executed_prefixes",
        )
        if start > end:
            raise TrendlineAdequacyContractError(
                "adequacy start_position must be <= end_position"
            )
        object.__setattr__(self, "timeframe", timeframe)
        object.__setattr__(self, "start_position", start)
        object.__setattr__(self, "end_position", end)
        object.__setattr__(self, "minimum_warmup_bars", warmup)
        object.__setattr__(
            self,
            "minimum_prior_executed_prefixes",
            history,
        )

    def to_dict(self) -> dict[str, int | str]:
        return {
            "timeframe": self.timeframe,
            "start_position": self.start_position,
            "end_position": self.end_position,
            "minimum_warmup_bars": self.minimum_warmup_bars,
            "minimum_prior_executed_prefixes": self.minimum_prior_executed_prefixes,
        }


@dataclass(frozen=True)
class TrendlineAdequacyDecisionRule:
    """Explicit frozen comparison rule; no rule is evaluated in L2-D1."""

    metric_name: str
    operator: TrendlineAdequacyOperator
    threshold: float
    minimum_observation_count: int

    def __post_init__(self) -> None:
        metric_name = str(self.metric_name).strip()
        if metric_name not in KNOWN_ADEQUACY_METRIC_NAMES:
            raise TrendlineAdequacyContractError(
                f"unknown adequacy metric: {metric_name}"
            )
        if not isinstance(self.operator, TrendlineAdequacyOperator):
            raise TrendlineAdequacyContractError("decision operator must be typed")
        if isinstance(self.threshold, bool) or not isinstance(
            self.threshold, (int, float)
        ) or not isfinite(float(self.threshold)):
            raise TrendlineAdequacyContractError(
                "decision threshold must be finite numeric"
            )
        minimum = _strict_int(
            self.minimum_observation_count,
            name="minimum_observation_count",
            minimum=1,
        )
        object.__setattr__(self, "metric_name", metric_name)
        object.__setattr__(self, "threshold", float(self.threshold))
        object.__setattr__(self, "minimum_observation_count", minimum)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "operator": self.operator.value,
            "threshold": self.threshold,
            "minimum_observation_count": self.minimum_observation_count,
        }


@dataclass(frozen=True)
class TrendlineAdequacyStudyConfig:
    """Content-addressed frozen study protocol for later adequacy phases."""

    study_name: str
    windows: tuple[TrendlineAdequacyWindow, ...]
    metric_names: tuple[str, ...]
    decision_rules: tuple[TrendlineAdequacyDecisionRule, ...]
    baseline_specs: tuple[TrendlineAdequacyBaselineSpec, ...]
    line_observation_unit: TrendlineObservationUnit
    ray_observation_unit: TrendlineObservationUnit
    invalid_point_treatment: TrendlineInvalidPointTreatment
    availability_policy: TrendlineAdequacyAvailabilityPolicy
    semantics_version: str = ADEQUACY_STUDY_CONFIG_SEMANTICS_VERSION

    def __post_init__(self) -> None:
        name = str(self.study_name).strip()
        if not name:
            raise TrendlineAdequacyContractError("study_name is required")
        if not isinstance(self.windows, tuple):
            raise TrendlineAdequacyContractError(
                "study windows must be supplied as an ordered tuple"
            )
        raw_windows = self.windows
        if not raw_windows or not all(
            isinstance(value, TrendlineAdequacyWindow) for value in raw_windows
        ):
            raise TrendlineAdequacyContractError(
                "study windows must contain typed adequacy windows"
            )
        if len({value.timeframe for value in raw_windows}) != len(raw_windows):
            raise TrendlineAdequacyContractError("study windows must be unique")
        metric_names = tuple(str(value).strip() for value in self.metric_names)
        if not metric_names or any(not value for value in metric_names):
            raise TrendlineAdequacyContractError("metric_names must be non-empty")
        if len(set(metric_names)) != len(metric_names):
            raise TrendlineAdequacyContractError("metric_names must be unique and ordered")
        unknown = set(metric_names) - set(KNOWN_ADEQUACY_METRIC_NAMES)
        if unknown:
            raise TrendlineAdequacyContractError(
                f"unknown adequacy metrics: {sorted(unknown)}"
            )
        rules = tuple(self.decision_rules)
        if not all(
            isinstance(value, TrendlineAdequacyDecisionRule) for value in rules
        ):
            raise TrendlineAdequacyContractError(
                "decision_rules must contain only typed rules"
            )
        rule_metric_names = tuple(value.metric_name for value in rules)
        if len(set(rule_metric_names)) != len(rule_metric_names):
            raise TrendlineAdequacyContractError(
                "decision_rules must be ordered and unique"
            )
        if any(value not in metric_names for value in rule_metric_names):
            raise TrendlineAdequacyContractError(
                "decision rule metric must be selected in metric_names"
            )
        baselines = tuple(self.baseline_specs)
        if not baselines or not all(
            isinstance(value, TrendlineAdequacyBaselineSpec) for value in baselines
        ):
            raise TrendlineAdequacyContractError(
                "baseline_specs must contain at least one typed baseline"
            )
        if len({value.name for value in baselines}) != len(baselines):
            raise TrendlineAdequacyContractError(
                "baseline names must be unique and ordered"
            )
        if self.line_observation_unit is not TrendlineObservationUnit.FITTED_LINE:
            raise TrendlineAdequacyContractError(
                "line observation unit must be fitted_line"
            )
        if self.ray_observation_unit is not TrendlineObservationUnit.BOUNDARY_RAY:
            raise TrendlineAdequacyContractError(
                "ray observation unit must be boundary_ray"
            )
        if not isinstance(self.invalid_point_treatment, TrendlineInvalidPointTreatment):
            raise TrendlineAdequacyContractError("invalid point treatment must be typed")
        if not isinstance(self.availability_policy, TrendlineAdequacyAvailabilityPolicy):
            raise TrendlineAdequacyContractError("availability policy must be typed")
        if self.availability_policy is not TrendlineAdequacyAvailabilityPolicy.CAUSAL_PREFIX_ONLY:
            raise TrendlineAdequacyContractError("only causal_prefix_only is supported")
        semantics_version = str(self.semantics_version).strip()
        if not semantics_version:
            raise TrendlineAdequacyContractError("semantics_version is required")
        object.__setattr__(self, "study_name", name)
        object.__setattr__(self, "windows", raw_windows)
        object.__setattr__(self, "metric_names", metric_names)
        object.__setattr__(self, "decision_rules", rules)
        object.__setattr__(self, "baseline_specs", baselines)
        object.__setattr__(self, "semantics_version", semantics_version)

    def window_for(self, timeframe: str) -> TrendlineAdequacyWindow:
        for window in self.windows:
            if window.timeframe == timeframe:
                return window
        raise TrendlineAdequacyContractError(
            f"adequacy window missing timeframe {timeframe}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "study_name": self.study_name,
            "windows": [window.to_dict() for window in self.windows],
            "metric_names": list(self.metric_names),
            "decision_rules": [rule.to_dict() for rule in self.decision_rules],
            "baseline_specs": [spec.to_dict() for spec in self.baseline_specs],
            "line_observation_unit": self.line_observation_unit.value,
            "ray_observation_unit": self.ray_observation_unit.value,
            "invalid_point_treatment": self.invalid_point_treatment.value,
            "availability_policy": self.availability_policy.value,
            "semantics_version": self.semantics_version,
        }

    @property
    def study_config_id(self) -> str:
        return canonical_hash(
            self.to_dict(),
            semantics_version=ADEQUACY_STUDY_CONFIG_SEMANTICS_VERSION,
        )

    def validate_for(
        self,
        prepared: PreparedTrendlineResearchRun,
        replay: PreparedTrendlineResearchReplay,
    ) -> None:
        if replay.prepared is not prepared:
            raise TrendlineAdequacyContractError(
                "replay does not belong to prepared research run"
            )
        expected = tuple(prepared.spec.timeframes)
        if tuple(window.timeframe for window in self.windows) != expected:
            raise TrendlineAdequacyContractError(
                "adequacy windows must cover prepared timeframes in exact order"
            )
        for window in self.windows:
            replay_window = replay.replay_spec.windows[window.timeframe]
            if window.start_position < replay_window.record_start_position:
                raise TrendlineAdequacyContractError(
                    f"adequacy window starts before recorded scope for {window.timeframe}"
                )
            if window.end_position > replay_window.end_position:
                raise TrendlineAdequacyContractError(
                    f"adequacy window exceeds replay end for {window.timeframe}"
                )
            first_recorded = window.start_position
            remainder = (
                first_recorded - replay_window.record_start_position
            ) % replay_window.record_every
            if remainder:
                first_recorded += replay_window.record_every - remainder
            if first_recorded > window.end_position:
                raise TrendlineAdequacyContractError(
                    f"adequacy window contains no recorded positions for {window.timeframe}"
                )
            warmup_bars = (
                replay_window.record_start_position
                - replay_window.warmup_start_position
            )
            if window.minimum_warmup_bars > warmup_bars:
                raise TrendlineAdequacyContractError(
                    f"adequacy minimum warm-up exceeds replay warm-up for {window.timeframe}"
                )


@dataclass(frozen=True)
class TrendlineAdequacyCohort:
    """Identity of one frozen prepared/replayed evaluation cohort."""

    cohort_id: str
    study_config_id: str
    asset: str
    timeframes: tuple[str, ...]
    preparation_id: str
    dataset_id: str
    research_configuration_id: str
    replay_id: str
    replay_windows: tuple[tuple[str, int, int, int, int], ...]
    include_signals: bool
    source_ids: tuple[tuple[str, str], ...]
    availability_ids: tuple[tuple[str, str], ...]
    timestamp_semantics: str
    availability_sources: tuple[tuple[str, str], ...]
    semantics_version: str = ADEQUACY_COHORT_SEMANTICS_VERSION

    def __post_init__(self) -> None:
        required_ids = (
            self.cohort_id,
            self.study_config_id,
            self.asset,
            self.preparation_id,
            self.dataset_id,
            self.research_configuration_id,
            self.replay_id,
            self.timestamp_semantics,
        )
        if any(
            not isinstance(value, str) or not value.strip()
            for value in required_ids
        ):
            raise TrendlineAdequacyContractError(
                "cohort identities and scope fields are required"
            )
        timeframes = tuple(self.timeframes)
        if (
            not timeframes
            or any(not isinstance(value, str) or not value.strip() for value in timeframes)
            or len(set(timeframes)) != len(timeframes)
        ):
            raise TrendlineAdequacyContractError(
                "cohort timeframes must be non-empty and unique"
            )
        windows = tuple(self.replay_windows)
        if len(windows) != len(timeframes):
            raise TrendlineAdequacyContractError(
                "cohort replay windows must cover each timeframe exactly"
            )
        window_timeframes: list[str] = []
        for window in windows:
            if not isinstance(window, tuple) or len(window) != 5:
                raise TrendlineAdequacyContractError(
                    "cohort replay windows must be five-item tuples"
                )
            timeframe, warmup, record_start, end, record_every = window
            if not isinstance(timeframe, str) or not timeframe.strip():
                raise TrendlineAdequacyContractError(
                    "cohort replay window timeframe is required"
                )
            window_timeframes.append(timeframe)
            for name, value in (
                ("warmup_start_position", warmup),
                ("record_start_position", record_start),
                ("end_position", end),
            ):
                _strict_int(value, name=f"cohort {name}")
            _strict_int(record_every, name="cohort record_every", minimum=1)
            if warmup > record_start or record_start > end:
                raise TrendlineAdequacyContractError(
                    "cohort replay window positions must be ordered"
                )
        if tuple(window_timeframes) != timeframes:
            raise TrendlineAdequacyContractError(
                "cohort replay windows must preserve timeframe order"
            )
        if not isinstance(self.include_signals, bool):
            raise TrendlineAdequacyContractError(
                "cohort include_signals must be a bool"
            )
        for name, values in (
            ("source_ids", self.source_ids),
            ("availability_ids", self.availability_ids),
            ("availability_sources", self.availability_sources),
        ):
            pairs = tuple(values)
            if any(not isinstance(pair, tuple) or len(pair) != 2 for pair in pairs):
                raise TrendlineAdequacyContractError(
                    f"cohort {name} must contain key/value tuples"
                )
            keys = tuple(key for key, _ in pairs)
            if keys != timeframes or any(
                not isinstance(value, str) or not value.strip()
                for _, value in pairs
            ):
                raise TrendlineAdequacyContractError(
                    f"cohort {name} must match timeframe order with non-empty values"
                )
        if self.semantics_version != ADEQUACY_COHORT_SEMANTICS_VERSION:
            raise TrendlineAdequacyContractError(
                "cohort semantics_version is unsupported"
            )
        identity_payload = {
            "study_config_id": self.study_config_id,
            "asset": self.asset,
            "timeframes": list(timeframes),
            "preparation_id": self.preparation_id,
            "dataset_id": self.dataset_id,
            "research_configuration_id": self.research_configuration_id,
            "replay_id": self.replay_id,
            "replay_windows": list(windows),
            "include_signals": self.include_signals,
            "source_ids": dict(self.source_ids),
            "availability_ids": dict(self.availability_ids),
            "timestamp_semantics": self.timestamp_semantics,
            "availability_sources": dict(self.availability_sources),
            "semantics_version": ADEQUACY_COHORT_SEMANTICS_VERSION,
        }
        expected_cohort_id = canonical_hash(
            identity_payload,
            semantics_version=ADEQUACY_COHORT_SEMANTICS_VERSION,
        )
        if self.cohort_id != expected_cohort_id:
            raise TrendlineAdequacyContractError(
                "cohort_id does not match immutable cohort contents"
            )
        object.__setattr__(self, "timeframes", timeframes)
        object.__setattr__(self, "replay_windows", windows)
        object.__setattr__(self, "source_ids", tuple(self.source_ids))
        object.__setattr__(self, "availability_ids", tuple(self.availability_ids))
        object.__setattr__(
            self,
            "availability_sources",
            tuple(self.availability_sources),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cohort_id": self.cohort_id,
            "study_config_id": self.study_config_id,
            "asset": self.asset,
            "timeframes": list(self.timeframes),
            "preparation_id": self.preparation_id,
            "dataset_id": self.dataset_id,
            "research_configuration_id": self.research_configuration_id,
            "replay_id": self.replay_id,
            "replay_windows": [
                {
                    "timeframe": timeframe,
                    "warmup_start_position": warmup,
                    "record_start_position": record_start,
                    "end_position": end,
                    "record_every": record_every,
                }
                for timeframe, warmup, record_start, end, record_every in self.replay_windows
            ],
            "include_signals": self.include_signals,
            "source_ids": dict(self.source_ids),
            "availability_ids": dict(self.availability_ids),
            "timestamp_semantics": self.timestamp_semantics,
            "availability_sources": dict(self.availability_sources),
            "semantics_version": self.semantics_version,
        }


class TrendlineAdequacyObservationState(str, Enum):
    ELIGIBLE = "eligible"
    OUTSIDE_WINDOW = "outside_window"
    INSUFFICIENT_HISTORY = "insufficient_history"
    INVALID_OUTPUT = "invalid_output"


@dataclass(frozen=True)
class TrendlineAdequacyObservation:
    """Compact descriptive observation for one recorded causal point."""

    cohort_id: str
    timeframe: str
    position: int
    event_at: datetime
    available_at: datetime
    replay_point_id: str
    content_id: str
    source_id: str
    checkpoint_id: str
    fit_valid: bool
    state: TrendlineAdequacyObservationState
    reason: str
    prior_executed_prefix_count: int
    support_line_count: int
    resistance_line_count: int
    support_ray_count: int
    resistance_ray_count: int

    def __post_init__(self) -> None:
        if not all(
            str(value).strip()
            for value in (
                self.cohort_id,
                self.timeframe,
                self.replay_point_id,
                self.content_id,
                self.source_id,
                self.checkpoint_id,
                self.reason,
            )
        ):
            raise TrendlineAdequacyContractError(
                "observation identity, timeframe and reason fields are required"
            )
        _strict_int(self.position, name="observation position")
        _strict_int(
            self.prior_executed_prefix_count,
            name="observation prior_executed_prefix_count",
        )
        for name, value in (
            ("support_line_count", self.support_line_count),
            ("resistance_line_count", self.resistance_line_count),
            ("support_ray_count", self.support_ray_count),
            ("resistance_ray_count", self.resistance_ray_count),
        ):
            _strict_int(value, name=name)
        if not isinstance(self.fit_valid, bool):
            raise TrendlineAdequacyContractError("fit_valid must be a bool")
        if not isinstance(self.state, TrendlineAdequacyObservationState):
            raise TrendlineAdequacyContractError("observation state must be typed")
        if self.state is TrendlineAdequacyObservationState.ELIGIBLE and not self.fit_valid:
            raise TrendlineAdequacyContractError(
                "invalid fit cannot be marked eligible"
            )
        if self.state is TrendlineAdequacyObservationState.INVALID_OUTPUT and self.fit_valid:
            raise TrendlineAdequacyContractError(
                "valid fit cannot be marked invalid_output"
            )
        _as_utc(self.event_at, name="observation event_at")
        _as_utc(self.available_at, name="observation available_at")
        if self.available_at < self.event_at:
            raise TrendlineAdequacyAvailabilityError(
                "observation available_at precedes event_at"
            )

    @property
    def eligible(self) -> bool:
        return self.state is TrendlineAdequacyObservationState.ELIGIBLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "cohort_id": self.cohort_id,
            "timeframe": self.timeframe,
            "position": self.position,
            "event_at": _as_utc(self.event_at, name="event_at").isoformat(),
            "available_at": _as_utc(
                self.available_at,
                name="available_at",
            ).isoformat(),
            "replay_point_id": self.replay_point_id,
            "content_id": self.content_id,
            "source_id": self.source_id,
            "checkpoint_id": self.checkpoint_id,
            "fit_valid": self.fit_valid,
            "state": self.state.value,
            "reason": self.reason,
            "prior_executed_prefix_count": self.prior_executed_prefix_count,
            "support_line_count": self.support_line_count,
            "resistance_line_count": self.resistance_line_count,
            "support_ray_count": self.support_ray_count,
            "resistance_ray_count": self.resistance_ray_count,
            "semantics_version": ADEQUACY_OBSERVATION_SEMANTICS_VERSION,
        }


def validate_adequacy_point_causality(point: TrendlineReplayPoint) -> None:
    """Validate point-in-time facts before any adequacy observation is emitted."""

    try:
        validate_replay_point_integrity(point)
    except (TypeError, ValueError) as exc:
        raise TrendlineAdequacyContractError(
            "replay point integrity validation failed"
        ) from exc
    if not isinstance(point, TrendlineReplayPoint):
        raise TrendlineAdequacyContractError("point must be a TrendlineReplayPoint")
    event_at = _as_utc(point.event_at, name="point event_at")
    available_at = _as_utc(point.available_at, name="point available_at")
    if available_at < event_at:
        raise TrendlineAdequacyAvailabilityError(
            "point available_at precedes event_at"
        )
    boundary = point.boundary_snapshot
    if _as_utc(boundary.timestamp, name="boundary timestamp") != event_at:
        raise TrendlineAdequacyAvailabilityError(
            "boundary timestamp differs from point event_at"
        )
    identity = point.boundary_identity
    if identity is None or not identity.snapshot_id or not identity.revision_id:
        raise TrendlineAdequacyContractError("point boundary identity is required")
    checkpoint = identity.checkpoint
    if not checkpoint.checkpoint_id or not checkpoint.source.source_id:
        raise TrendlineAdequacyContractError("point checkpoint identity is required")
    if _as_utc(checkpoint.source.as_of, name="checkpoint source as_of") != event_at:
        raise TrendlineAdequacyAvailabilityError(
            "checkpoint source as_of differs from point event_at"
        )
    if _as_utc(boundary.known_at, name="boundary known_at") > available_at:
        raise TrendlineAdequacyAvailabilityError(
            "boundary became known after point availability"
        )
    if point.prefix_source_ref.source_id != checkpoint.source.source_id:
        raise TrendlineAdequacyContractError(
            "point prefix source differs from boundary checkpoint source"
        )
    metadata = dict(point.output.metadata)
    for field_name in ("signal_query_known_at", "signal_available_at"):
        value = metadata.get(field_name)
        if value is not None and _as_utc(value, name=field_name) > available_at:
            raise TrendlineAdequacyAvailabilityError(
                f"{field_name} is later than point availability"
            )


def build_adequacy_cohort(
    prepared: PreparedTrendlineResearchRun,
    replay: PreparedTrendlineResearchReplay,
    study_config: TrendlineAdequacyStudyConfig,
) -> TrendlineAdequacyCohort:
    """Bind frozen study scope to one prepared and replayed cohort."""

    if not isinstance(prepared, PreparedTrendlineResearchRun):
        raise TrendlineAdequacyContractError("prepared must be a prepared research run")
    if not isinstance(replay, PreparedTrendlineResearchReplay):
        raise TrendlineAdequacyContractError("replay must be a prepared research replay")
    if not isinstance(study_config, TrendlineAdequacyStudyConfig):
        raise TrendlineAdequacyContractError("study_config must be typed")
    study_config.validate_for(prepared, replay)
    identity = prepared.dataset.identity
    source_ids = tuple(
        (timeframe, identity.source_refs[timeframe].source_id)
        for timeframe in prepared.spec.timeframes
    )
    availability_ids = tuple(
        (timeframe, identity.availability_ids[timeframe])
        for timeframe in prepared.spec.timeframes
    )
    availability_sources = tuple(
        (timeframe, identity.availability_sources[timeframe].value)
        for timeframe in prepared.spec.timeframes
    )
    payload = {
        "study_config_id": study_config.study_config_id,
        "asset": prepared.spec.asset,
        "timeframes": list(prepared.spec.timeframes),
        "preparation_id": prepared.preparation_id,
        "dataset_id": prepared.dataset.dataset_id,
        "research_configuration_id": prepared.configuration.research_configuration_id,
        "replay_id": replay.replay_id,
        "replay_windows": [
            (
                timeframe,
                replay.replay_spec.windows[timeframe].warmup_start_position,
                replay.replay_spec.windows[timeframe].record_start_position,
                replay.replay_spec.windows[timeframe].end_position,
                replay.replay_spec.windows[timeframe].record_every,
            )
            for timeframe in prepared.spec.timeframes
        ],
        "include_signals": replay.replay_spec.include_signals,
        "source_ids": dict(source_ids),
        "availability_ids": dict(availability_ids),
        "timestamp_semantics": identity.timestamp_semantics.value,
        "availability_sources": dict(availability_sources),
        "semantics_version": ADEQUACY_COHORT_SEMANTICS_VERSION,
    }
    cohort_id = canonical_hash(
        payload,
        semantics_version=ADEQUACY_COHORT_SEMANTICS_VERSION,
    )
    return TrendlineAdequacyCohort(
        cohort_id=cohort_id,
        study_config_id=study_config.study_config_id,
        asset=prepared.spec.asset,
        timeframes=prepared.spec.timeframes,
        preparation_id=prepared.preparation_id,
        dataset_id=prepared.dataset.dataset_id,
        research_configuration_id=prepared.configuration.research_configuration_id,
        replay_id=replay.replay_id,
        replay_windows=tuple(
            (
                timeframe,
                replay.replay_spec.windows[timeframe].warmup_start_position,
                replay.replay_spec.windows[timeframe].record_start_position,
                replay.replay_spec.windows[timeframe].end_position,
                replay.replay_spec.windows[timeframe].record_every,
            )
            for timeframe in prepared.spec.timeframes
        ),
        include_signals=replay.replay_spec.include_signals,
        source_ids=source_ids,
        availability_ids=availability_ids,
        timestamp_semantics=identity.timestamp_semantics.value,
        availability_sources=availability_sources,
    )


__all__ = [
    "ADEQUACY_COHORT_SEMANTICS_VERSION",
    "ADEQUACY_OBSERVATION_SEMANTICS_VERSION",
    "ADEQUACY_STUDY_CONFIG_SEMANTICS_VERSION",
    "KNOWN_ADEQUACY_METRIC_NAMES",
    "TrendlineAdequacyAvailabilityError",
    "TrendlineAdequacyAvailabilityPolicy",
    "TrendlineAdequacyCohort",
    "TrendlineAdequacyContractError",
    "TrendlineAdequacyDecisionRule",
    "TrendlineAdequacyMetricDefinition",
    "TrendlineAdequacyMetricDirection",
    "TrendlineAdequacyMetricPhase",
    "TrendlineAdequacyObservation",
    "TrendlineAdequacyObservationState",
    "TrendlineAdequacyOperator",
    "TrendlineAdequacyOutcome",
    "TrendlineAdequacyStudyConfig",
    "TrendlineAdequacyWindow",
    "TrendlineInvalidPointTreatment",
    "TrendlineObservationUnit",
    "build_adequacy_cohort",
    "validate_adequacy_point_causality",
]
