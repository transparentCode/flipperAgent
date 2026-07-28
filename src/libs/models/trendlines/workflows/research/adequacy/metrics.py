"""Descriptive eligibility measurement for the L2-D1 adequacy foundation."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable

from .contracts import (
    TrendlineAdequacyCohort,
    TrendlineAdequacyContractError,
    TrendlineAdequacyMetricDefinition,
    TrendlineAdequacyMetricDirection,
    TrendlineAdequacyMetricPhase,
    TrendlineAdequacyObservation,
    TrendlineAdequacyObservationState,
    TrendlineAdequacyStudyConfig,
    KNOWN_ADEQUACY_METRIC_NAMES,
    build_adequacy_cohort,
    validate_adequacy_point_causality,
)


ADEQUACY_METRIC_VALUE_SEMANTICS_VERSION = "trendlines.adequacy-metric-value.v1"
ADEQUACY_TIMEFRAME_SUMMARY_SEMANTICS_VERSION = (
    "trendlines.adequacy-timeframe-summary.v1"
)
ADEQUACY_MEASUREMENT_SUMMARY_SEMANTICS_VERSION = (
    "trendlines.adequacy-measurement-summary.v1"
)


def _require_count(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TrendlineAdequacyContractError(
            f"{name} must be a non-negative non-boolean integer"
        )
    return value


def _require_identity(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrendlineAdequacyContractError(f"{name} must be non-empty")
    return value


def default_adequacy_metric_catalog() -> tuple[TrendlineAdequacyMetricDefinition, ...]:
    """Return frozen metric metadata; no metric here selects an outcome."""

    return (
        TrendlineAdequacyMetricDefinition(
            "eligible_point_coverage",
            TrendlineAdequacyMetricPhase.FOUNDATION,
            "fraction",
            TrendlineAdequacyMetricDirection.HIGHER_IS_BETTER,
            False,
            "Eligible recorded points divided by scoped recorded points.",
        ),
        TrendlineAdequacyMetricDefinition(
            "invalid_point_rate",
            TrendlineAdequacyMetricPhase.FOUNDATION,
            "fraction",
            TrendlineAdequacyMetricDirection.LOWER_IS_BETTER,
            False,
            "Invalid model observations divided by scoped recorded points.",
        ),
        TrendlineAdequacyMetricDefinition(
            "line_observation_count",
            TrendlineAdequacyMetricPhase.STRUCTURAL_STABILITY,
            "count",
            TrendlineAdequacyMetricDirection.DESCRIPTIVE,
            False,
            "Count of fitted-line observations at eligible points.",
        ),
        TrendlineAdequacyMetricDefinition(
            "ray_observation_count",
            TrendlineAdequacyMetricPhase.STRUCTURAL_STABILITY,
            "count",
            TrendlineAdequacyMetricDirection.DESCRIPTIVE,
            False,
            "Count of boundary-ray observations at eligible points.",
        ),
        TrendlineAdequacyMetricDefinition(
            "line_birth_rate",
            TrendlineAdequacyMetricPhase.STRUCTURAL_STABILITY,
            "fraction",
            TrendlineAdequacyMetricDirection.DESCRIPTIVE,
            True,
            "Rate at which fitted lines first appear across later prefixes.",
        ),
        TrendlineAdequacyMetricDefinition(
            "revision_churn_rate",
            TrendlineAdequacyMetricPhase.STRUCTURAL_STABILITY,
            "fraction",
            TrendlineAdequacyMetricDirection.LOWER_IS_BETTER,
            True,
            "Rate of geometry identity changes across later prefixes.",
        ),
        TrendlineAdequacyMetricDefinition(
            "anchor_persistence_rate",
            TrendlineAdequacyMetricPhase.STRUCTURAL_STABILITY,
            "fraction",
            TrendlineAdequacyMetricDirection.HIGHER_IS_BETTER,
            True,
            "Rate at which line or ray anchors persist across later prefixes.",
        ),
        TrendlineAdequacyMetricDefinition(
            "touch_rate",
            TrendlineAdequacyMetricPhase.INTERACTION_UTILITY,
            "fraction",
            TrendlineAdequacyMetricDirection.DESCRIPTIVE,
            True,
            "Causal future touch frequency after line selection.",
        ),
        TrendlineAdequacyMetricDefinition(
            "rejection_rate",
            TrendlineAdequacyMetricPhase.INTERACTION_UTILITY,
            "fraction",
            TrendlineAdequacyMetricDirection.DESCRIPTIVE,
            True,
            "Causal rejection or bounce frequency after touch.",
        ),
        TrendlineAdequacyMetricDefinition(
            "penetration_depth",
            TrendlineAdequacyMetricPhase.INTERACTION_UTILITY,
            "price_distance",
            TrendlineAdequacyMetricDirection.LOWER_IS_BETTER,
            True,
            "Distance-normalized penetration after line interaction.",
        ),
        TrendlineAdequacyMetricDefinition(
            "confirmed_break_rate",
            TrendlineAdequacyMetricPhase.INTERACTION_UTILITY,
            "fraction",
            TrendlineAdequacyMetricDirection.DESCRIPTIVE,
            True,
            "Confirmed causal break frequency after interaction.",
        ),
        TrendlineAdequacyMetricDefinition(
            "false_break_rate",
            TrendlineAdequacyMetricPhase.INTERACTION_UTILITY,
            "fraction",
            TrendlineAdequacyMetricDirection.LOWER_IS_BETTER,
            True,
            "False-break frequency after a candidate break.",
        ),
        TrendlineAdequacyMetricDefinition(
            "favourable_excursion",
            TrendlineAdequacyMetricPhase.INTERACTION_UTILITY,
            "price_distance",
            TrendlineAdequacyMetricDirection.HIGHER_IS_BETTER,
            True,
            "Distance-normalized favourable movement after selection.",
        ),
        TrendlineAdequacyMetricDefinition(
            "adverse_excursion",
            TrendlineAdequacyMetricPhase.INTERACTION_UTILITY,
            "price_distance",
            TrendlineAdequacyMetricDirection.LOWER_IS_BETTER,
            True,
            "Distance-normalized adverse movement after selection.",
        ),
        TrendlineAdequacyMetricDefinition(
            "null_lift",
            TrendlineAdequacyMetricPhase.BASELINE_COMPARISON,
            "difference",
            TrendlineAdequacyMetricDirection.HIGHER_IS_BETTER,
            True,
            "Difference from a frozen naive or null geometry baseline.",
        ),
        TrendlineAdequacyMetricDefinition(
            "cohort_stability",
            TrendlineAdequacyMetricPhase.ROBUSTNESS,
            "fraction",
            TrendlineAdequacyMetricDirection.HIGHER_IS_BETTER,
            True,
            "Stability of a conclusion across frozen cohorts.",
        ),
    )


@dataclass(frozen=True)
class TrendlineAdequacyMetricValue:
    """A descriptive value emitted by the foundation summary."""

    name: str
    value: float | None
    observation_count: int
    semantics_version: str = ADEQUACY_METRIC_VALUE_SEMANTICS_VERSION

    def __post_init__(self) -> None:
        name = _require_identity(self.name, name="metric name")
        if name not in KNOWN_ADEQUACY_METRIC_NAMES:
            raise TrendlineAdequacyContractError(f"unknown adequacy metric: {name}")
        count = _require_count(self.observation_count, name="observation_count")
        value = self.value
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TrendlineAdequacyContractError(
                    "metric value must be finite numeric or None"
                )
            value = float(value)
            if not isfinite(value):
                raise TrendlineAdequacyContractError(
                    "metric value must be finite numeric or None"
                )
        if self.semantics_version != ADEQUACY_METRIC_VALUE_SEMANTICS_VERSION:
            raise TrendlineAdequacyContractError(
                "metric value semantics_version is unsupported"
            )
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "observation_count", count)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "observation_count": self.observation_count,
            "semantics_version": self.semantics_version,
        }


@dataclass(frozen=True)
class TrendlineAdequacyTimeframeSummary:
    timeframe: str
    scoped_point_count: int
    eligible_point_count: int
    invalid_point_count: int
    excluded_point_count: int
    line_observation_count: int
    ray_observation_count: int
    semantics_version: str = ADEQUACY_TIMEFRAME_SUMMARY_SEMANTICS_VERSION

    def __post_init__(self) -> None:
        _require_identity(self.timeframe, name="summary timeframe")
        counts = {
            "scoped_point_count": self.scoped_point_count,
            "eligible_point_count": self.eligible_point_count,
            "invalid_point_count": self.invalid_point_count,
            "excluded_point_count": self.excluded_point_count,
            "line_observation_count": self.line_observation_count,
            "ray_observation_count": self.ray_observation_count,
        }
        normalized = {
            name: _require_count(value, name=name)
            for name, value in counts.items()
        }
        if normalized["eligible_point_count"] > normalized["scoped_point_count"]:
            raise TrendlineAdequacyContractError(
                "eligible point count exceeds scoped point count"
            )
        if normalized["invalid_point_count"] > normalized["scoped_point_count"]:
            raise TrendlineAdequacyContractError(
                "invalid point count exceeds scoped point count"
            )
        if normalized["excluded_point_count"] > normalized["scoped_point_count"]:
            raise TrendlineAdequacyContractError(
                "excluded point count exceeds scoped point count"
            )
        if (
            normalized["eligible_point_count"]
            + normalized["excluded_point_count"]
            != normalized["scoped_point_count"]
        ):
            raise TrendlineAdequacyContractError(
                "eligible plus excluded points must equal scoped points"
            )
        if self.semantics_version != ADEQUACY_TIMEFRAME_SUMMARY_SEMANTICS_VERSION:
            raise TrendlineAdequacyContractError(
                "timeframe summary semantics_version is unsupported"
            )
        for name, value in normalized.items():
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "scoped_point_count": self.scoped_point_count,
            "eligible_point_count": self.eligible_point_count,
            "invalid_point_count": self.invalid_point_count,
            "excluded_point_count": self.excluded_point_count,
            "line_observation_count": self.line_observation_count,
            "ray_observation_count": self.ray_observation_count,
            "semantics_version": self.semantics_version,
        }


@dataclass(frozen=True)
class TrendlineAdequacyMeasurementSummary:
    """Descriptive scope accounting, not a model-quality decision."""

    cohort_id: str
    scoped_point_count: int
    eligible_point_count: int
    invalid_point_count: int
    excluded_point_count: int
    timeframe_summaries: tuple[TrendlineAdequacyTimeframeSummary, ...]
    metric_values: tuple[TrendlineAdequacyMetricValue, ...]
    semantics_version: str = ADEQUACY_MEASUREMENT_SUMMARY_SEMANTICS_VERSION

    def __post_init__(self) -> None:
        cohort_id = _require_identity(self.cohort_id, name="summary cohort_id")
        counts = {
            "scoped_point_count": self.scoped_point_count,
            "eligible_point_count": self.eligible_point_count,
            "invalid_point_count": self.invalid_point_count,
            "excluded_point_count": self.excluded_point_count,
        }
        normalized = {
            name: _require_count(value, name=name)
            for name, value in counts.items()
        }
        timeframe_summaries = tuple(self.timeframe_summaries)
        metric_values = tuple(self.metric_values)
        if not timeframe_summaries or not all(
            isinstance(value, TrendlineAdequacyTimeframeSummary)
            for value in timeframe_summaries
        ):
            raise TrendlineAdequacyContractError(
                "measurement summary needs typed timeframe summaries"
            )
        if len({value.timeframe for value in timeframe_summaries}) != len(
            timeframe_summaries
        ):
            raise TrendlineAdequacyContractError(
                "measurement timeframe summaries must be unique"
            )
        if not all(
            isinstance(value, TrendlineAdequacyMetricValue)
            for value in metric_values
        ) or len({value.name for value in metric_values}) != len(metric_values):
            raise TrendlineAdequacyContractError(
                "measurement metric values must be typed and unique"
            )
        aggregate = {
            name: sum(getattr(value, name) for value in timeframe_summaries)
            for name in (
                "scoped_point_count",
                "eligible_point_count",
                "invalid_point_count",
                "excluded_point_count",
            )
        }
        if aggregate != normalized:
            raise TrendlineAdequacyContractError(
                "measurement counts do not match timeframe summaries"
            )
        if normalized["eligible_point_count"] > normalized["scoped_point_count"]:
            raise TrendlineAdequacyContractError(
                "eligible point count exceeds scoped point count"
            )
        if normalized["invalid_point_count"] > normalized["scoped_point_count"]:
            raise TrendlineAdequacyContractError(
                "invalid point count exceeds scoped point count"
            )
        if normalized["eligible_point_count"] + normalized["excluded_point_count"] != normalized["scoped_point_count"]:
            raise TrendlineAdequacyContractError(
                "eligible plus excluded points must equal scoped points"
            )
        if self.semantics_version != ADEQUACY_MEASUREMENT_SUMMARY_SEMANTICS_VERSION:
            raise TrendlineAdequacyContractError(
                "measurement summary semantics_version is unsupported"
            )
        object.__setattr__(self, "cohort_id", cohort_id)
        object.__setattr__(self, "scoped_point_count", normalized["scoped_point_count"])
        object.__setattr__(self, "eligible_point_count", normalized["eligible_point_count"])
        object.__setattr__(self, "invalid_point_count", normalized["invalid_point_count"])
        object.__setattr__(self, "excluded_point_count", normalized["excluded_point_count"])
        object.__setattr__(self, "timeframe_summaries", timeframe_summaries)
        object.__setattr__(self, "metric_values", metric_values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cohort_id": self.cohort_id,
            "scoped_point_count": self.scoped_point_count,
            "eligible_point_count": self.eligible_point_count,
            "invalid_point_count": self.invalid_point_count,
            "excluded_point_count": self.excluded_point_count,
            "timeframe_summaries": [
                value.to_dict() for value in self.timeframe_summaries
            ],
            "metric_values": [value.to_dict() for value in self.metric_values],
            "decision": None,
            "semantics_version": self.semantics_version,
        }


def _validate_cohort_binding(
    cohort: TrendlineAdequacyCohort,
    prepared: Any,
    replay: Any,
    study_config: TrendlineAdequacyStudyConfig,
) -> None:
    expected = build_adequacy_cohort(prepared, replay, study_config)
    if cohort.cohort_id != expected.cohort_id:
        raise TrendlineAdequacyContractError(
            "adequacy cohort does not match prepared/replay/study identities"
        )


def collect_adequacy_observations(
    cohort: TrendlineAdequacyCohort,
    prepared: Any,
    replay: Any,
    study_config: TrendlineAdequacyStudyConfig,
) -> tuple[TrendlineAdequacyObservation, ...]:
    """Collect compact eligibility observations from recorded replay points."""

    _validate_cohort_binding(cohort, prepared, replay, study_config)
    observations: list[TrendlineAdequacyObservation] = []
    for timeframe in cohort.timeframes:
        study_window = study_config.window_for(timeframe)
        replay_window = replay.replay_spec.windows[timeframe]
        for point in replay.timeframes[timeframe].points:
            validate_adequacy_point_causality(point)
            prior_executed_prefix_count = max(
                0,
                point.position - replay_window.warmup_start_position,
            )
            if not (
                study_window.start_position
                <= point.position
                <= study_window.end_position
            ):
                state = TrendlineAdequacyObservationState.OUTSIDE_WINDOW
                reason = "position_outside_adequacy_window"
            elif (
                prior_executed_prefix_count
                < study_window.minimum_prior_executed_prefixes
            ):
                state = TrendlineAdequacyObservationState.INSUFFICIENT_HISTORY
                reason = "minimum_prior_executed_prefixes_not_met"
            elif not point.output.fit_result.is_valid:
                state = TrendlineAdequacyObservationState.INVALID_OUTPUT
                reason = "invalid_model_output"
            else:
                state = TrendlineAdequacyObservationState.ELIGIBLE
                reason = "eligible_recorded_causal_point"
            fit = point.output.fit_result
            boundary = point.boundary_snapshot.boundary
            observations.append(
                TrendlineAdequacyObservation(
                    cohort_id=cohort.cohort_id,
                    timeframe=timeframe,
                    position=point.position,
                    event_at=point.event_at,
                    available_at=point.available_at,
                    replay_point_id=point.replay_point_id,
                    content_id=point.content_id,
                    source_id=point.prefix_source_ref.source_id,
                    checkpoint_id=point.boundary_identity.checkpoint.checkpoint_id,
                    fit_valid=fit.is_valid,
                    state=state,
                    reason=reason,
                    prior_executed_prefix_count=prior_executed_prefix_count,
                    support_line_count=len(fit.support_lines),
                    resistance_line_count=len(fit.resistance_lines),
                    support_ray_count=len(boundary.active_support_rays),
                    resistance_ray_count=len(boundary.active_resistance_rays),
                )
            )
    return tuple(observations)


def summarize_adequacy_eligibility(
    observations: Iterable[TrendlineAdequacyObservation],
) -> TrendlineAdequacyMeasurementSummary:
    """Return descriptive counts and foundation rates without selecting a decision."""

    values = tuple(observations)
    if not values:
        raise TrendlineAdequacyContractError("observations must be non-empty")
    cohort_ids = {value.cohort_id for value in values}
    if len(cohort_ids) != 1:
        raise TrendlineAdequacyContractError(
            "observations must belong to exactly one cohort"
        )
    ordered_timeframes = tuple(dict.fromkeys(value.timeframe for value in values))
    scoped_by_timeframe: dict[str, list[TrendlineAdequacyObservation]] = {
        timeframe: [
            value
            for value in values
            if value.timeframe == timeframe
            and value.state is not TrendlineAdequacyObservationState.OUTSIDE_WINDOW
        ]
        for timeframe in ordered_timeframes
    }
    timeframe_summaries: list[TrendlineAdequacyTimeframeSummary] = []
    for timeframe in ordered_timeframes:
        scoped = scoped_by_timeframe[timeframe]
        eligible = [value for value in scoped if value.eligible]
        invalid = [
            value
            for value in scoped
            if not value.fit_valid
        ]
        timeframe_summaries.append(
            TrendlineAdequacyTimeframeSummary(
                timeframe=timeframe,
                scoped_point_count=len(scoped),
                eligible_point_count=len(eligible),
                invalid_point_count=len(invalid),
                excluded_point_count=len(scoped) - len(eligible),
                line_observation_count=sum(
                    value.support_line_count + value.resistance_line_count
                    for value in eligible
                ),
                ray_observation_count=sum(
                    value.support_ray_count + value.resistance_ray_count
                    for value in eligible
                ),
            )
        )
    scoped_count = sum(value.scoped_point_count for value in timeframe_summaries)
    eligible_count = sum(value.eligible_point_count for value in timeframe_summaries)
    invalid_count = sum(value.invalid_point_count for value in timeframe_summaries)
    metric_values = (
        TrendlineAdequacyMetricValue(
            "eligible_point_coverage",
            eligible_count / scoped_count if scoped_count else None,
            scoped_count,
        ),
        TrendlineAdequacyMetricValue(
            "invalid_point_rate",
            invalid_count / scoped_count if scoped_count else None,
            scoped_count,
        ),
        TrendlineAdequacyMetricValue(
            "line_observation_count",
            float(sum(value.line_observation_count for value in timeframe_summaries)),
            eligible_count,
        ),
        TrendlineAdequacyMetricValue(
            "ray_observation_count",
            float(sum(value.ray_observation_count for value in timeframe_summaries)),
            eligible_count,
        ),
    )
    return TrendlineAdequacyMeasurementSummary(
        cohort_id=next(iter(cohort_ids)),
        scoped_point_count=scoped_count,
        eligible_point_count=eligible_count,
        invalid_point_count=invalid_count,
        excluded_point_count=scoped_count - eligible_count,
        timeframe_summaries=tuple(timeframe_summaries),
        metric_values=metric_values,
    )


__all__ = [
    "ADEQUACY_MEASUREMENT_SUMMARY_SEMANTICS_VERSION",
    "ADEQUACY_METRIC_VALUE_SEMANTICS_VERSION",
    "ADEQUACY_TIMEFRAME_SUMMARY_SEMANTICS_VERSION",
    "TrendlineAdequacyMeasurementSummary",
    "TrendlineAdequacyMetricValue",
    "TrendlineAdequacyTimeframeSummary",
    "collect_adequacy_observations",
    "default_adequacy_metric_catalog",
    "summarize_adequacy_eligibility",
]
