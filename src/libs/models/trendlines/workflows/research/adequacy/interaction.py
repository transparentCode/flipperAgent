"""Causal interaction utility measurements for frozen boundary-ray births."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from numbers import Real
from statistics import fmean, median
from typing import Any

import pandas as pd

from libs.models.trendlines.contracts.identity import canonical_hash
from libs.models.trendlines.workflows.research.contracts import (
    PreparedTrendlineResearchRun,
)
from libs.models.trendlines.workflows.research.replay import (
    PreparedTrendlineResearchReplay,
    TrendlineReplayPoint,
    TrendlineReplayContractError,
    TrendlineReplayIntegrityError,
    validate_replay_point_integrity,
)

from .contracts import (
    TrendlineAdequacyCohort,
    TrendlineAdequacyStudyConfig,
    TrendlineObservationUnit,
    build_adequacy_cohort,
)
from .stability import (
    TrendlineStructuralEpisode,
    TrendlineStructuralStabilityBundle,
    TrendlineStructuralStabilityError,
    TrendlineStructuralState,
    validate_structural_stability_bundle,
)


INTERACTION_UTILITY_SPEC_SEMANTICS_VERSION = (
    "trendlines.adequacy-interaction-utility-spec.v1"
)
INTERACTION_EVENT_SEMANTICS_VERSION = "trendlines.adequacy-interaction-event.v1"
INTERACTION_OUTCOME_SEMANTICS_VERSION = "trendlines.adequacy-interaction-outcome.v1"
INTERACTION_SUMMARY_SEMANTICS_VERSION = "trendlines.adequacy-interaction-summary.v1"
INTERACTION_UTILITY_BUNDLE_SEMANTICS_VERSION = (
    "trendlines.adequacy-interaction-utility-bundle.v1"
)
INTERACTION_BREAK_STATUSES = ("none", "confirmed", "false", "unresolved")
INTERACTION_ROLES = ("support", "resistance")


class TrendlineInteractionUtilityError(ValueError):
    """Raised when causal interaction evidence is invalid or ambiguous."""


def _strict_int(value: Any, *, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise TrendlineInteractionUtilityError(
            f"{name} must be a non-boolean integer >= {minimum}"
        )
    return value


def _finite(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TrendlineInteractionUtilityError(f"{name} must be finite numeric")
    result = float(value)
    if not isfinite(result):
        raise TrendlineInteractionUtilityError(f"{name} must be finite numeric")
    return result


def _nonnegative(value: Any, *, name: str) -> float:
    result = _finite(value, name=name)
    if result < 0:
        raise TrendlineInteractionUtilityError(f"{name} must be >= 0")
    return result


def _identity(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrendlineInteractionUtilityError(f"{name} must be non-empty")
    return value


def _sha256(value: Any, *, name: str) -> str:
    result = _identity(value, name=name)
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        raise TrendlineInteractionUtilityError(
            f"{name} must be a lowercase SHA-256 identity"
        )
    return result


def _timestamp_text(value: Any, *, name: str) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise TrendlineInteractionUtilityError(f"{name} must be timezone-aware")
    return timestamp.tz_convert("UTC").isoformat()


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _require_rate(
    value: float | None,
    numerator: int,
    denominator: int,
    *,
    name: str,
) -> None:
    expected = _rate(numerator, denominator)
    if value != expected:
        raise TrendlineInteractionUtilityError(
            f"{name} does not match its count-derived rate"
        )
    if value is not None:
        _finite(value, name=name)


def _anchor_payload(anchor_key: Sequence[Any]) -> list[Any]:
    return list(anchor_key)


def _spec_payload(spec: "TrendlineInteractionUtilitySpec") -> dict[str, Any]:
    return {
        "evaluation_horizons_bars": list(spec.evaluation_horizons_bars),
        "break_confirmation_bars": spec.break_confirmation_bars,
        "semantics_version": spec.semantics_version,
    }


@dataclass(frozen=True)
class TrendlineInteractionUtilitySpec:
    """Frozen future-OUTCOME protocol for one interaction study."""

    evaluation_horizons_bars: tuple[int, ...]
    break_confirmation_bars: int
    semantics_version: str = INTERACTION_UTILITY_SPEC_SEMANTICS_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.evaluation_horizons_bars, tuple):
            raise TrendlineInteractionUtilityError(
                "evaluation_horizons_bars must be an ordered tuple"
            )
        horizons = tuple(
            _strict_int(value, name="evaluation horizon", minimum=1)
            for value in self.evaluation_horizons_bars
        )
        if not horizons:
            raise TrendlineInteractionUtilityError(
                "evaluation_horizons_bars must be non-empty"
            )
        if len(set(horizons)) != len(horizons) or tuple(sorted(horizons)) != horizons:
            raise TrendlineInteractionUtilityError(
                "evaluation_horizons_bars must be ordered and unique"
            )
        confirmation = _strict_int(
            self.break_confirmation_bars,
            name="break_confirmation_bars",
            minimum=1,
        )
        if self.semantics_version != INTERACTION_UTILITY_SPEC_SEMANTICS_VERSION:
            raise TrendlineInteractionUtilityError(
                "unsupported interaction-utility spec semantics_version"
            )
        object.__setattr__(self, "evaluation_horizons_bars", horizons)
        object.__setattr__(self, "break_confirmation_bars", confirmation)

    def to_dict(self) -> dict[str, Any]:
        return _spec_payload(self)

    @property
    def interaction_spec_id(self) -> str:
        return canonical_hash(
            self.to_dict(),
            semantics_version=INTERACTION_UTILITY_SPEC_SEMANTICS_VERSION,
        )


def _event_payload(event: "TrendlineInteractionEvent") -> dict[str, Any]:
    return {
        "cohort_id": event.cohort_id,
        "study_config_id": event.study_config_id,
        "structural_stability_bundle_id": event.structural_stability_bundle_id,
        "interaction_spec_id": event.interaction_spec_id,
        "timeframe": event.timeframe,
        "episode_id": event.episode_id,
        "birth_state_id": event.birth_state_id,
        "anchor_key": _anchor_payload(event.anchor_key),
        "role": event.role,
        "selection_position": event.selection_position,
        "selection_event_at": event.selection_event_at,
        "selection_available_at": event.selection_available_at,
        "selection_atr": event.selection_atr,
        "frozen_slope": event.frozen_slope,
        "frozen_intercept": event.frozen_intercept,
        "replay_point_id": event.replay_point_id,
        "content_id": event.content_id,
        "source_id": event.source_id,
        "checkpoint_id": event.checkpoint_id,
        "semantics_version": INTERACTION_EVENT_SEMANTICS_VERSION,
    }


@dataclass(frozen=True)
class TrendlineInteractionEvent:
    """One non-left-censored boundary-ray birth with frozen geometry."""

    cohort_id: str
    study_config_id: str
    structural_stability_bundle_id: str
    interaction_spec_id: str
    timeframe: str
    episode_id: str
    birth_state_id: str
    anchor_key: tuple[Any, ...]
    role: str
    selection_position: int
    selection_event_at: str
    selection_available_at: str
    selection_atr: float
    frozen_slope: float
    frozen_intercept: float
    replay_point_id: str
    content_id: str
    source_id: str
    checkpoint_id: str
    event_id: str = ""

    def __post_init__(self) -> None:
        for name, value in (
            ("cohort_id", self.cohort_id),
            ("study_config_id", self.study_config_id),
            ("structural_stability_bundle_id", self.structural_stability_bundle_id),
            ("interaction_spec_id", self.interaction_spec_id),
            ("episode_id", self.episode_id),
            ("birth_state_id", self.birth_state_id),
            ("replay_point_id", self.replay_point_id),
            ("content_id", self.content_id),
            ("source_id", self.source_id),
            ("checkpoint_id", self.checkpoint_id),
        ):
            _sha256(value, name=f"event {name}")
        _identity(self.timeframe, name="event timeframe")
        if not isinstance(self.anchor_key, tuple) or not self.anchor_key:
            raise TrendlineInteractionUtilityError("event anchor_key is required")
        if self.role not in INTERACTION_ROLES:
            raise TrendlineInteractionUtilityError("event role must be support or resistance")
        _strict_int(self.selection_position, name="event selection_position")
        event_at = _timestamp_text(
            self.selection_event_at,
            name="event selection_event_at",
        )
        available_at = _timestamp_text(
            self.selection_available_at,
            name="event selection_available_at",
        )
        if available_at < event_at:
            raise TrendlineInteractionUtilityError(
                "event selection availability precedes event time"
            )
        atr = _finite(self.selection_atr, name="event selection_atr")
        if atr <= 0:
            raise TrendlineInteractionUtilityError("event selection_atr must be positive")
        slope = _finite(self.frozen_slope, name="event frozen_slope")
        intercept = _finite(self.frozen_intercept, name="event frozen_intercept")
        expected = canonical_hash(
            {
                **_event_payload(self),
                "selection_event_at": event_at,
                "selection_available_at": available_at,
                "selection_atr": atr,
                "frozen_slope": slope,
                "frozen_intercept": intercept,
            },
            semantics_version=INTERACTION_EVENT_SEMANTICS_VERSION,
        )
        if self.event_id and self.event_id != expected:
            raise TrendlineInteractionUtilityError(
                "event_id does not match event content"
            )
        object.__setattr__(self, "selection_event_at", event_at)
        object.__setattr__(self, "selection_available_at", available_at)
        object.__setattr__(self, "selection_atr", atr)
        object.__setattr__(self, "frozen_slope", slope)
        object.__setattr__(self, "frozen_intercept", intercept)
        object.__setattr__(self, "event_id", expected)

    def to_dict(self) -> dict[str, Any]:
        return {**_event_payload(self), "event_id": self.event_id}


def _outcome_payload(outcome: "TrendlineInteractionOutcome") -> dict[str, Any]:
    return {
        "interaction_event_id": outcome.interaction_event_id,
        "horizon_bars": outcome.horizon_bars,
        "horizon_end_position": outcome.horizon_end_position,
        "right_censored": outcome.right_censored,
        "first_touch_position": outcome.first_touch_position,
        "first_touch_latency_bars": outcome.first_touch_latency_bars,
        "first_touch_projected_level": outcome.first_touch_projected_level,
        "first_touch_penetration_atr": outcome.first_touch_penetration_atr,
        "defended_touch": outcome.defended_touch,
        "wick_rejection": outcome.wick_rejection,
        "first_adverse_close_position": outcome.first_adverse_close_position,
        "break_status": outcome.break_status,
        "favourable_excursion_atr": outcome.favourable_excursion_atr,
        "adverse_excursion_atr": outcome.adverse_excursion_atr,
        "semantics_version": INTERACTION_OUTCOME_SEMANTICS_VERSION,
    }


@dataclass(frozen=True)
class TrendlineInteractionOutcome:
    """One exact-horizon future OHLC outcome for one interaction event."""

    interaction_event_id: str
    horizon_bars: int
    horizon_end_position: int
    right_censored: bool
    first_touch_position: int | None
    first_touch_latency_bars: int | None
    first_touch_projected_level: float | None
    first_touch_penetration_atr: float | None
    defended_touch: bool | None
    wick_rejection: bool | None
    first_adverse_close_position: int | None
    break_status: str
    favourable_excursion_atr: float | None
    adverse_excursion_atr: float | None
    outcome_id: str = ""

    def __post_init__(self) -> None:
        _sha256(self.interaction_event_id, name="outcome interaction_event_id")
        _strict_int(self.horizon_bars, name="outcome horizon_bars", minimum=1)
        _strict_int(
            self.horizon_end_position,
            name="outcome horizon_end_position",
            minimum=1,
        )
        if not isinstance(self.right_censored, bool):
            raise TrendlineInteractionUtilityError("outcome right_censored must be bool")
        if self.break_status not in INTERACTION_BREAK_STATUSES:
            raise TrendlineInteractionUtilityError("outcome break_status is invalid")
        if self.first_touch_position is None:
            if any(
                value is not None
                for value in (
                    self.first_touch_latency_bars,
                    self.first_touch_projected_level,
                    self.first_touch_penetration_atr,
                    self.defended_touch,
                    self.wick_rejection,
                    self.favourable_excursion_atr,
                    self.adverse_excursion_atr,
                )
            ):
                raise TrendlineInteractionUtilityError(
                    "touch fields require first_touch_position"
                )
        else:
            _strict_int(
                self.first_touch_position,
                name="outcome first_touch_position",
                minimum=1,
            )
            if self.first_touch_latency_bars is None:
                raise TrendlineInteractionUtilityError("touch latency is required")
            _strict_int(
                self.first_touch_latency_bars,
                name="outcome first_touch_latency_bars",
                minimum=1,
            )
            for name, value in (
                ("first_touch_projected_level", self.first_touch_projected_level),
                ("first_touch_penetration_atr", self.first_touch_penetration_atr),
                ("favourable_excursion_atr", self.favourable_excursion_atr),
                ("adverse_excursion_atr", self.adverse_excursion_atr),
            ):
                if value is None:
                    raise TrendlineInteractionUtilityError(f"{name} is required after touch")
                _nonnegative(value, name=name)
            if not isinstance(self.defended_touch, bool) or not isinstance(
                self.wick_rejection, bool
            ):
                raise TrendlineInteractionUtilityError(
                    "touch classifications must be bool after touch"
                )
            if self.wick_rejection and not self.defended_touch:
                raise TrendlineInteractionUtilityError(
                    "wick_rejection must be a defended touch"
                )
        if self.first_adverse_close_position is None:
            if self.break_status != "none":
                raise TrendlineInteractionUtilityError(
                    "break status requires first adverse close"
                )
        else:
            _strict_int(
                self.first_adverse_close_position,
                name="outcome first_adverse_close_position",
                minimum=1,
            )
            if self.break_status == "none":
                raise TrendlineInteractionUtilityError(
                    "first adverse close requires break status"
                )
        if self.right_censored and (
            self.first_touch_position is not None
            or self.first_adverse_close_position is not None
            or self.break_status != "none"
        ):
            raise TrendlineInteractionUtilityError(
                "right-censored outcome cannot contain unavailable horizon results"
            )
        expected = canonical_hash(
            _outcome_payload(self),
            semantics_version=INTERACTION_OUTCOME_SEMANTICS_VERSION,
        )
        if self.outcome_id and self.outcome_id != expected:
            raise TrendlineInteractionUtilityError(
                "outcome_id does not match outcome content"
            )
        object.__setattr__(self, "outcome_id", expected)

    def to_dict(self) -> dict[str, Any]:
        return {**_outcome_payload(self), "outcome_id": self.outcome_id}


def _summary_payload(summary: "TrendlineInteractionSummary") -> dict[str, Any]:
    return {
        "timeframe": summary.timeframe,
        "role": summary.role,
        "horizon_bars": summary.horizon_bars,
        "event_count": summary.event_count,
        "eligible_event_count": summary.eligible_event_count,
        "right_censored_count": summary.right_censored_count,
        "touch_count": summary.touch_count,
        "defended_touch_count": summary.defended_touch_count,
        "wick_rejection_count": summary.wick_rejection_count,
        "candidate_break_count": summary.candidate_break_count,
        "confirmed_break_count": summary.confirmed_break_count,
        "false_break_count": summary.false_break_count,
        "unresolved_break_count": summary.unresolved_break_count,
        "touch_rate": summary.touch_rate,
        "rejection_rate": summary.rejection_rate,
        "confirmed_break_rate": summary.confirmed_break_rate,
        "false_break_rate": summary.false_break_rate,
        "mean_first_touch_latency_bars": summary.mean_first_touch_latency_bars,
        "median_first_touch_latency_bars": summary.median_first_touch_latency_bars,
        "mean_penetration_atr": summary.mean_penetration_atr,
        "median_penetration_atr": summary.median_penetration_atr,
        "mean_favourable_excursion_atr": summary.mean_favourable_excursion_atr,
        "median_favourable_excursion_atr": summary.median_favourable_excursion_atr,
        "mean_adverse_excursion_atr": summary.mean_adverse_excursion_atr,
        "median_adverse_excursion_atr": summary.median_adverse_excursion_atr,
        "semantics_version": INTERACTION_SUMMARY_SEMANTICS_VERSION,
    }


@dataclass(frozen=True)
class TrendlineInteractionSummary:
    """Per-role, per-horizon interaction counts, rates, and touch statistics."""

    timeframe: str
    role: str
    horizon_bars: int
    event_count: int
    eligible_event_count: int
    right_censored_count: int
    touch_count: int
    defended_touch_count: int
    wick_rejection_count: int
    candidate_break_count: int
    confirmed_break_count: int
    false_break_count: int
    unresolved_break_count: int
    touch_rate: float | None
    rejection_rate: float | None
    confirmed_break_rate: float | None
    false_break_rate: float | None
    mean_first_touch_latency_bars: float | None
    median_first_touch_latency_bars: float | None
    mean_penetration_atr: float | None
    median_penetration_atr: float | None
    mean_favourable_excursion_atr: float | None
    median_favourable_excursion_atr: float | None
    mean_adverse_excursion_atr: float | None
    median_adverse_excursion_atr: float | None
    summary_id: str = ""

    def __post_init__(self) -> None:
        _identity(self.timeframe, name="summary timeframe")
        if self.role not in INTERACTION_ROLES:
            raise TrendlineInteractionUtilityError("summary role is invalid")
        _strict_int(self.horizon_bars, name="summary horizon_bars", minimum=1)
        counts = (
            ("event_count", self.event_count),
            ("eligible_event_count", self.eligible_event_count),
            ("right_censored_count", self.right_censored_count),
            ("touch_count", self.touch_count),
            ("defended_touch_count", self.defended_touch_count),
            ("wick_rejection_count", self.wick_rejection_count),
            ("candidate_break_count", self.candidate_break_count),
            ("confirmed_break_count", self.confirmed_break_count),
            ("false_break_count", self.false_break_count),
            ("unresolved_break_count", self.unresolved_break_count),
        )
        for name, value in counts:
            _strict_int(value, name=f"summary {name}")
        if self.eligible_event_count + self.right_censored_count != self.event_count:
            raise TrendlineInteractionUtilityError(
                "summary eligible and right-censored counts are inconsistent"
            )
        if self.touch_count > self.eligible_event_count:
            raise TrendlineInteractionUtilityError("summary touch count exceeds eligible events")
        if self.defended_touch_count > self.touch_count:
            raise TrendlineInteractionUtilityError("summary defended count exceeds touches")
        if self.wick_rejection_count > self.defended_touch_count:
            raise TrendlineInteractionUtilityError("summary wick count exceeds defended touches")
        if self.candidate_break_count > self.eligible_event_count:
            raise TrendlineInteractionUtilityError("summary candidate breaks exceed eligible events")
        if (
            self.confirmed_break_count
            + self.false_break_count
            + self.unresolved_break_count
            != self.candidate_break_count
        ):
            raise TrendlineInteractionUtilityError(
                "summary break classifications are inconsistent"
            )
        _require_rate(self.touch_rate, self.touch_count, self.eligible_event_count, name="summary touch_rate")
        _require_rate(self.rejection_rate, self.defended_touch_count, self.touch_count, name="summary rejection_rate")
        _require_rate(self.confirmed_break_rate, self.confirmed_break_count, self.candidate_break_count, name="summary confirmed_break_rate")
        _require_rate(self.false_break_rate, self.false_break_count, self.candidate_break_count, name="summary false_break_rate")
        for name, value in (
            ("mean_first_touch_latency_bars", self.mean_first_touch_latency_bars),
            ("median_first_touch_latency_bars", self.median_first_touch_latency_bars),
            ("mean_penetration_atr", self.mean_penetration_atr),
            ("median_penetration_atr", self.median_penetration_atr),
            ("mean_favourable_excursion_atr", self.mean_favourable_excursion_atr),
            ("median_favourable_excursion_atr", self.median_favourable_excursion_atr),
            ("mean_adverse_excursion_atr", self.mean_adverse_excursion_atr),
            ("median_adverse_excursion_atr", self.median_adverse_excursion_atr),
        ):
            if value is not None:
                _finite(value, name=f"summary {name}")
        if self.touch_count == 0 and any(
            value is not None
            for value in (
                self.mean_first_touch_latency_bars,
                self.median_first_touch_latency_bars,
                self.mean_penetration_atr,
                self.median_penetration_atr,
                self.mean_favourable_excursion_atr,
                self.median_favourable_excursion_atr,
                self.mean_adverse_excursion_atr,
                self.median_adverse_excursion_atr,
            )
        ):
            raise TrendlineInteractionUtilityError(
                "summary touch statistics require touched events"
            )
        if self.touch_count and any(
            value is None
            for value in (
                self.mean_first_touch_latency_bars,
                self.median_first_touch_latency_bars,
                self.mean_penetration_atr,
                self.median_penetration_atr,
                self.mean_favourable_excursion_atr,
                self.median_favourable_excursion_atr,
                self.mean_adverse_excursion_atr,
                self.median_adverse_excursion_atr,
            )
        ):
            raise TrendlineInteractionUtilityError(
                "summary touch statistics are incomplete"
            )
        expected = canonical_hash(
            _summary_payload(self),
            semantics_version=INTERACTION_SUMMARY_SEMANTICS_VERSION,
        )
        if self.summary_id and self.summary_id != expected:
            raise TrendlineInteractionUtilityError(
                "summary_id does not match summary content"
            )
        object.__setattr__(self, "summary_id", expected)

    def to_dict(self) -> dict[str, Any]:
        return {**_summary_payload(self), "summary_id": self.summary_id}


def _bundle_payload(bundle: "TrendlineInteractionUtilityBundle") -> dict[str, Any]:
    return {
        "dataset_id": bundle.dataset_id,
        "replay_id": bundle.replay_id,
        "cohort_id": bundle.cohort_id,
        "study_config_id": bundle.study_config_id,
        "structural_stability_bundle_id": bundle.structural_stability_bundle_id,
        "interaction_spec": bundle.interaction_spec.to_dict(),
        "interaction_spec_id": bundle.interaction_spec_id,
        "events": [event.to_dict() for event in bundle.events],
        "outcomes": [outcome.to_dict() for outcome in bundle.outcomes],
        "summaries": [summary.to_dict() for summary in bundle.summaries],
        "semantics_version": INTERACTION_UTILITY_BUNDLE_SEMANTICS_VERSION,
    }


@dataclass(frozen=True)
class TrendlineInteractionUtilityBundle:
    """Content-addressed interaction outcomes for one causal D2 cohort."""

    dataset_id: str
    replay_id: str
    cohort_id: str
    study_config_id: str
    structural_stability_bundle_id: str
    interaction_spec: TrendlineInteractionUtilitySpec
    events: tuple[TrendlineInteractionEvent, ...]
    outcomes: tuple[TrendlineInteractionOutcome, ...]
    summaries: tuple[TrendlineInteractionSummary, ...]
    interaction_utility_bundle_id: str = ""
    semantics_version: str = INTERACTION_UTILITY_BUNDLE_SEMANTICS_VERSION

    @property
    def interaction_spec_id(self) -> str:
        return self.interaction_spec.interaction_spec_id

    def __post_init__(self) -> None:
        for name, value in (
            ("dataset_id", self.dataset_id),
            ("replay_id", self.replay_id),
            ("cohort_id", self.cohort_id),
            ("study_config_id", self.study_config_id),
            ("structural_stability_bundle_id", self.structural_stability_bundle_id),
        ):
            _sha256(value, name=f"bundle {name}")
        if not isinstance(self.interaction_spec, TrendlineInteractionUtilitySpec):
            raise TrendlineInteractionUtilityError("bundle interaction_spec is invalid")
        for rows, row_type in (
            (self.events, TrendlineInteractionEvent),
            (self.outcomes, TrendlineInteractionOutcome),
            (self.summaries, TrendlineInteractionSummary),
        ):
            if not isinstance(rows, tuple):
                raise TrendlineInteractionUtilityError(
                    "bundle row collections must be immutable tuples"
                )
            if not all(isinstance(row, row_type) for row in rows):
                raise TrendlineInteractionUtilityError("bundle contains untyped rows")
        if self.semantics_version != INTERACTION_UTILITY_BUNDLE_SEMANTICS_VERSION:
            raise TrendlineInteractionUtilityError(
                "unsupported interaction bundle semantics_version"
            )
        expected = canonical_hash(
            _bundle_payload(self),
            semantics_version=INTERACTION_UTILITY_BUNDLE_SEMANTICS_VERSION,
        )
        if self.interaction_utility_bundle_id and self.interaction_utility_bundle_id != expected:
            raise TrendlineInteractionUtilityError(
                "interaction_utility_bundle_id does not match bundle content"
            )
        object.__setattr__(self, "interaction_utility_bundle_id", expected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "interaction_utility_bundle_id": self.interaction_utility_bundle_id,
            **_bundle_payload(self),
        }


def _ray_state_key(state: TrendlineStructuralState) -> tuple[str, tuple[Any, ...], int]:
    return state.timeframe, state.anchor_key, state.position


def _event_from_episode(
    episode: TrendlineStructuralEpisode,
    state: TrendlineStructuralState,
    point: TrendlineReplayPoint,
    *,
    cohort_id: str,
    study_config_id: str,
    structural_stability_bundle: TrendlineStructuralStabilityBundle,
    interaction_spec: TrendlineInteractionUtilitySpec,
) -> TrendlineInteractionEvent:
    if episode.observation_unit is not TrendlineObservationUnit.BOUNDARY_RAY:
        raise TrendlineInteractionUtilityError("interaction events require boundary rays")
    if episode.left_censored:
        raise TrendlineInteractionUtilityError("left-censored episode cannot become event")
    if state.position != episode.first_position or state.anchor_key != episode.anchor_key:
        raise TrendlineInteractionUtilityError("episode birth state binding is inconsistent")
    if state.observation_unit is not TrendlineObservationUnit.BOUNDARY_RAY:
        raise TrendlineInteractionUtilityError("birth state must be a boundary-ray state")
    if state.role not in INTERACTION_ROLES:
        raise TrendlineInteractionUtilityError("boundary-ray birth role is invalid")
    if point.timeframe != state.timeframe or point.position != state.position:
        raise TrendlineInteractionUtilityError("birth state does not bind replay point")
    validate_replay_point_integrity(point)
    boundary_identity = point.boundary_identity
    if (
        state.replay_point_id != point.replay_point_id
        or state.content_id != point.content_id
        or state.source_id != point.prefix_source_ref.source_id
        or state.checkpoint_id != boundary_identity.checkpoint.checkpoint_id
        or state.boundary_snapshot_id != boundary_identity.snapshot_id
        or state.boundary_revision_id != boundary_identity.revision_id
    ):
        raise TrendlineInteractionUtilityError("birth state does not bind replay identities")
    context = point.boundary_snapshot.boundary.boundary_context
    if not isinstance(context, Mapping) or "latest_atr" not in context:
        raise TrendlineInteractionUtilityError("selection point lacks latest_atr provenance")
    if len(state.shape) != 4:
        raise TrendlineInteractionUtilityError("boundary-ray state shape must have four values")
    atr = _finite(context["latest_atr"], name="selection latest_atr")
    if atr <= 0:
        raise TrendlineInteractionUtilityError("selection latest_atr must be positive")
    return TrendlineInteractionEvent(
        cohort_id=cohort_id,
        study_config_id=study_config_id,
        structural_stability_bundle_id=structural_stability_bundle.structural_stability_bundle_id,
        interaction_spec_id=interaction_spec.interaction_spec_id,
        timeframe=state.timeframe,
        episode_id=episode.episode_id,
        birth_state_id=state.state_id,
        anchor_key=state.anchor_key,
        role=state.role,
        selection_position=state.position,
        selection_event_at=point.event_at.isoformat(),
        selection_available_at=point.available_at.isoformat(),
        selection_atr=atr,
        frozen_slope=state.shape[2],
        frozen_intercept=state.shape[3],
        replay_point_id=point.replay_point_id,
        content_id=point.content_id,
        source_id=point.prefix_source_ref.source_id,
        checkpoint_id=boundary_identity.checkpoint.checkpoint_id,
    )


def _derive_interaction_events(
    replay: PreparedTrendlineResearchReplay,
    structural_stability_bundle: TrendlineStructuralStabilityBundle,
    interaction_spec: TrendlineInteractionUtilitySpec,
    *,
    cohort_id: str,
    study_config_id: str,
) -> tuple[TrendlineInteractionEvent, ...]:
    """Derive the exact boundary-ray birth event set from frozen evidence."""

    states = {
        _ray_state_key(state): state
        for state in structural_stability_bundle.state_rows
        if state.observation_unit is TrendlineObservationUnit.BOUNDARY_RAY
    }
    timeframe_order = {
        value: index for index, value in enumerate(replay.prepared.spec.timeframes)
    }
    episodes = sorted(
        (
            episode
            for episode in structural_stability_bundle.episode_rows
            if episode.observation_unit is TrendlineObservationUnit.BOUNDARY_RAY
            and not episode.left_censored
        ),
        key=lambda episode: (
            timeframe_order.get(episode.timeframe, len(timeframe_order)),
            episode.first_position,
            episode.role_switch_count,
            str(episode.anchor_key),
            episode.episode_ordinal,
        ),
    )
    events: list[TrendlineInteractionEvent] = []
    for episode in episodes:
        key = (episode.timeframe, episode.anchor_key, episode.first_position)
        state = states.get(key)
        if state is None:
            raise TrendlineInteractionUtilityError("episode birth state is missing")
        point = replay.output_at(episode.timeframe, episode.first_position)
        events.append(
            _event_from_episode(
                episode,
                state,
                point,
                cohort_id=cohort_id,
                study_config_id=study_config_id,
                structural_stability_bundle=structural_stability_bundle,
                interaction_spec=interaction_spec,
            )
        )
    if len({event.event_id for event in events}) != len(events):
        raise TrendlineInteractionUtilityError("duplicate derived interaction events")
    return tuple(events)


def build_interaction_events(
    prepared: PreparedTrendlineResearchRun,
    replay: PreparedTrendlineResearchReplay,
    cohort: TrendlineAdequacyCohort,
    study_config: TrendlineAdequacyStudyConfig,
    structural_stability_bundle: TrendlineStructuralStabilityBundle,
    interaction_spec: TrendlineInteractionUtilitySpec,
) -> tuple[TrendlineInteractionEvent, ...]:
    """Select non-left-censored boundary-ray episode births."""

    if replay.prepared is not prepared:
        raise TrendlineInteractionUtilityError("prepared run does not belong to replay")
    expected_cohort = build_adequacy_cohort(prepared, replay, study_config)
    if cohort.cohort_id != expected_cohort.cohort_id:
        raise TrendlineInteractionUtilityError("cohort does not match replay")
    if structural_stability_bundle.cohort_id != cohort.cohort_id:
        raise TrendlineInteractionUtilityError("D2 bundle cohort does not match")
    if structural_stability_bundle.study_config_id != study_config.study_config_id:
        raise TrendlineInteractionUtilityError("D2 bundle study config does not match")
    validate_structural_stability_bundle(structural_stability_bundle)
    return _derive_interaction_events(
        replay,
        structural_stability_bundle,
        interaction_spec,
        cohort_id=cohort.cohort_id,
        study_config_id=study_config.study_config_id,
    )


def _row_value(row: Any, column: str, position: int) -> float:
    try:
        value = row[column]
    except (KeyError, TypeError) as exc:
        raise TrendlineInteractionUtilityError(
            f"future frame lacks {column} column"
        ) from exc
    return _finite(value, name=f"future {column} at {position}")


def _project(event: TrendlineInteractionEvent, position: int) -> float:
    return event.frozen_slope * position + event.frozen_intercept


def _is_adverse(role: str, close: float, level: float) -> bool:
    return close < level if role == "support" else close > level


def _is_defended(role: str, close: float, level: float) -> bool:
    return close >= level if role == "support" else close <= level


def _is_wick_rejection(role: str, low: float, high: float, close: float, level: float) -> bool:
    if role == "support":
        return low < level and close >= level
    return high > level and close <= level


def _penetration(role: str, low: float, high: float, level: float, atr: float) -> float:
    raw = max(level - low, 0.0) if role == "support" else max(high - level, 0.0)
    return raw / atr


def _excursion(role: str, low: float, high: float, level: float, atr: float) -> tuple[float, float]:
    if role == "support":
        favourable = max(high - level, 0.0) / atr
        adverse = max(level - low, 0.0) / atr
    else:
        favourable = max(level - low, 0.0) / atr
        adverse = max(high - level, 0.0) / atr
    return favourable, adverse


def _break_status(
    event: TrendlineInteractionEvent,
    frame: pd.DataFrame,
    candidate: int | None,
    horizon_end: int,
    confirmation_bars: int,
) -> str:
    if candidate is None:
        return "none"
    consecutive = 1
    if consecutive >= confirmation_bars:
        return "confirmed"
    for position in range(candidate + 1, horizon_end + 1):
        row = frame.iloc[position]
        close = _row_value(row, "close", position)
        if _is_adverse(event.role, close, _project(event, position)):
            consecutive += 1
            if consecutive >= confirmation_bars:
                return "confirmed"
        else:
            return "false"
    return "unresolved"


def measure_interaction_outcomes(
    event: TrendlineInteractionEvent,
    frame: pd.DataFrame,
    interaction_spec: TrendlineInteractionUtilitySpec,
    *,
    final_position: int | None = None,
) -> tuple[TrendlineInteractionOutcome, ...]:
    """Measure future OHLC outcomes without executing model code."""

    if not isinstance(event, TrendlineInteractionEvent):
        raise TrendlineInteractionUtilityError("event must be typed")
    if not isinstance(interaction_spec, TrendlineInteractionUtilitySpec):
        raise TrendlineInteractionUtilityError("interaction_spec must be typed")
    if event.interaction_spec_id != interaction_spec.interaction_spec_id:
        raise TrendlineInteractionUtilityError("event spec does not match interaction spec")
    if not isinstance(frame, pd.DataFrame):
        raise TrendlineInteractionUtilityError("frame must be a DataFrame")
    if "bar_available_at" not in frame.columns:
        raise TrendlineInteractionUtilityError("frame lacks bar_available_at")
    last_position = len(frame) - 1 if final_position is None else final_position
    _strict_int(last_position, name="final_position", minimum=event.selection_position)
    if last_position >= len(frame):
        raise TrendlineInteractionUtilityError("final_position exceeds frame")
    selection_available = pd.Timestamp(event.selection_available_at)
    results: list[TrendlineInteractionOutcome] = []
    for horizon in interaction_spec.evaluation_horizons_bars:
        horizon_end = event.selection_position + horizon
        if horizon_end > last_position:
            results.append(
                TrendlineInteractionOutcome(
                    interaction_event_id=event.event_id,
                    horizon_bars=horizon,
                    horizon_end_position=horizon_end,
                    right_censored=True,
                    first_touch_position=None,
                    first_touch_latency_bars=None,
                    first_touch_projected_level=None,
                    first_touch_penetration_atr=None,
                    defended_touch=None,
                    wick_rejection=None,
                    first_adverse_close_position=None,
                    break_status="none",
                    favourable_excursion_atr=None,
                    adverse_excursion_atr=None,
                )
            )
            continue
        first_touch: int | None = None
        first_touch_level: float | None = None
        first_touch_penetration: float | None = None
        defended: bool | None = None
        wick: bool | None = None
        first_adverse: int | None = None
        for position in range(event.selection_position + 1, horizon_end + 1):
            available = pd.Timestamp(frame["bar_available_at"].iloc[position])
            if available.tzinfo is None or available.utcoffset() is None:
                raise TrendlineInteractionUtilityError(
                    f"future availability at {position} is not timezone-aware"
                )
            if available <= selection_available:
                raise TrendlineInteractionUtilityError(
                    "future bar availability is not after selection availability"
                )
            row = frame.iloc[position]
            low = _row_value(row, "low", position)
            high = _row_value(row, "high", position)
            close = _row_value(row, "close", position)
            level = _project(event, position)
            if first_touch is None and low <= level <= high:
                first_touch = position
                first_touch_level = level
                first_touch_penetration = _penetration(
                    event.role,
                    low,
                    high,
                    level,
                    event.selection_atr,
                )
                defended = _is_defended(event.role, close, level)
                wick = _is_wick_rejection(event.role, low, high, close, level)
            if first_adverse is None and _is_adverse(event.role, close, level):
                first_adverse = position
        break_status = _break_status(
            event,
            frame,
            first_adverse,
            horizon_end,
            interaction_spec.break_confirmation_bars,
        )
        favourable: float | None = None
        adverse: float | None = None
        if first_touch is not None:
            favourable_values: list[float] = []
            adverse_values: list[float] = []
            for position in range(first_touch, horizon_end + 1):
                row = frame.iloc[position]
                low = _row_value(row, "low", position)
                high = _row_value(row, "high", position)
                levels = _project(event, position)
                current_favourable, current_adverse = _excursion(
                    event.role,
                    low,
                    high,
                    levels,
                    event.selection_atr,
                )
                favourable_values.append(current_favourable)
                adverse_values.append(current_adverse)
            favourable = max(favourable_values)
            adverse = max(adverse_values)
        results.append(
            TrendlineInteractionOutcome(
                interaction_event_id=event.event_id,
                horizon_bars=horizon,
                horizon_end_position=horizon_end,
                right_censored=False,
                first_touch_position=first_touch,
                first_touch_latency_bars=(
                    first_touch - event.selection_position
                    if first_touch is not None
                    else None
                ),
                first_touch_projected_level=first_touch_level,
                first_touch_penetration_atr=first_touch_penetration,
                defended_touch=defended,
                wick_rejection=wick,
                first_adverse_close_position=first_adverse,
                break_status=break_status,
                favourable_excursion_atr=favourable,
                adverse_excursion_atr=adverse,
            )
        )
    return tuple(results)


def _stats(values: Sequence[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    return float(fmean(values)), float(median(values))


def _build_summary(
    timeframe: str,
    role: str,
    horizon: int,
    outcomes: Sequence[TrendlineInteractionOutcome],
) -> TrendlineInteractionSummary:
    values = tuple(outcomes)
    if not all(value.horizon_bars == horizon for value in values):
        raise TrendlineInteractionUtilityError("summary outcomes have mixed horizons")
    eligible = tuple(value for value in values if not value.right_censored)
    touched = tuple(value for value in eligible if value.first_touch_position is not None)
    candidates = tuple(
        value for value in eligible if value.first_adverse_close_position is not None
    )
    latencies = [float(value.first_touch_latency_bars) for value in touched]
    penetrations = [float(value.first_touch_penetration_atr) for value in touched]
    favourable = [float(value.favourable_excursion_atr) for value in touched]
    adverse = [float(value.adverse_excursion_atr) for value in touched]
    latency_mean, latency_median = _stats(latencies)
    penetration_mean, penetration_median = _stats(penetrations)
    favourable_mean, favourable_median = _stats(favourable)
    adverse_mean, adverse_median = _stats(adverse)
    confirmed = sum(value.break_status == "confirmed" for value in candidates)
    false = sum(value.break_status == "false" for value in candidates)
    unresolved = sum(value.break_status == "unresolved" for value in candidates)
    return TrendlineInteractionSummary(
        timeframe=timeframe,
        role=role,
        horizon_bars=horizon,
        event_count=len(values),
        eligible_event_count=len(eligible),
        right_censored_count=sum(value.right_censored for value in values),
        touch_count=len(touched),
        defended_touch_count=sum(value.defended_touch is True for value in touched),
        wick_rejection_count=sum(value.wick_rejection is True for value in touched),
        candidate_break_count=len(candidates),
        confirmed_break_count=confirmed,
        false_break_count=false,
        unresolved_break_count=unresolved,
        touch_rate=_rate(len(touched), len(eligible)),
        rejection_rate=_rate(
            sum(value.defended_touch is True for value in touched),
            len(touched),
        ),
        confirmed_break_rate=_rate(confirmed, len(candidates)),
        false_break_rate=_rate(false, len(candidates)),
        mean_first_touch_latency_bars=latency_mean,
        median_first_touch_latency_bars=latency_median,
        mean_penetration_atr=penetration_mean,
        median_penetration_atr=penetration_median,
        mean_favourable_excursion_atr=favourable_mean,
        median_favourable_excursion_atr=favourable_median,
        mean_adverse_excursion_atr=adverse_mean,
        median_adverse_excursion_atr=adverse_median,
    )


def _expected_summaries(
    events: Sequence[TrendlineInteractionEvent],
    outcomes: Sequence[TrendlineInteractionOutcome],
    timeframes: Sequence[str],
    spec: TrendlineInteractionUtilitySpec,
) -> tuple[TrendlineInteractionSummary, ...]:
    by_event = {event.event_id: event for event in events}
    result: list[TrendlineInteractionSummary] = []
    for timeframe in timeframes:
        for role in INTERACTION_ROLES:
            role_events = [event for event in events if event.timeframe == timeframe and event.role == role]
            for horizon in spec.evaluation_horizons_bars:
                role_outcomes = [
                    outcome
                    for outcome in outcomes
                    if outcome.horizon_bars == horizon
                    and by_event[outcome.interaction_event_id].timeframe == timeframe
                    and by_event[outcome.interaction_event_id].role == role
                ]
                if len(role_outcomes) != len(role_events):
                    raise TrendlineInteractionUtilityError(
                        "outcome coverage does not match event coverage"
                    )
                result.append(_build_summary(timeframe, role, horizon, role_outcomes))
    return tuple(result)


def _validate_outcome_coordinates(
    event: TrendlineInteractionEvent,
    outcome: TrendlineInteractionOutcome,
) -> None:
    expected_end = event.selection_position + outcome.horizon_bars
    if outcome.horizon_end_position != expected_end:
        raise TrendlineInteractionUtilityError(
            "outcome horizon_end_position is inconsistent with event selection"
        )
    if outcome.first_touch_position is not None:
        if not (
            event.selection_position
            < outcome.first_touch_position
            <= outcome.horizon_end_position
        ):
            raise TrendlineInteractionUtilityError(
                "outcome first_touch_position is outside event horizon"
            )
        if outcome.first_touch_latency_bars != (
            outcome.first_touch_position - event.selection_position
        ):
            raise TrendlineInteractionUtilityError(
                "outcome first_touch_latency_bars is inconsistent"
            )
    if outcome.first_adverse_close_position is not None and not (
        event.selection_position
        < outcome.first_adverse_close_position
        <= outcome.horizon_end_position
    ):
        raise TrendlineInteractionUtilityError(
            "outcome first_adverse_close_position is outside event horizon"
        )


def validate_interaction_utility_bundle(
    bundle: TrendlineInteractionUtilityBundle,
    *,
    structural_stability_bundle: TrendlineStructuralStabilityBundle,
    replay: PreparedTrendlineResearchReplay,
) -> None:
    """Validate D3 content against its complete replay and D2 evidence."""

    if not isinstance(bundle, TrendlineInteractionUtilityBundle):
        raise TrendlineInteractionUtilityError("bundle must be typed")
    if not isinstance(structural_stability_bundle, TrendlineStructuralStabilityBundle):
        raise TrendlineInteractionUtilityError("D2 structural stability bundle must be typed")
    if not isinstance(replay, PreparedTrendlineResearchReplay):
        raise TrendlineInteractionUtilityError("replay must be typed")
    try:
        validate_structural_stability_bundle(structural_stability_bundle)
    except TrendlineStructuralStabilityError as exc:
        raise TrendlineInteractionUtilityError(
            "D2 structural stability bundle is invalid"
        ) from exc
    if bundle.cohort_id != structural_stability_bundle.cohort_id:
        raise TrendlineInteractionUtilityError("D3 cohort does not match D2 cohort")
    if bundle.study_config_id != structural_stability_bundle.study_config_id:
        raise TrendlineInteractionUtilityError("D3 study config does not match D2 study config")
    if bundle.structural_stability_bundle_id != structural_stability_bundle.structural_stability_bundle_id:
        raise TrendlineInteractionUtilityError("D2 bundle identity differs")
    if bundle.dataset_id != replay.dataset_id:
        raise TrendlineInteractionUtilityError("D3 dataset does not match replay dataset")
    if bundle.replay_id != replay.replay_id:
        raise TrendlineInteractionUtilityError("D3 replay does not match replay identity")

    try:
        expected_events = _derive_interaction_events(
            replay,
            structural_stability_bundle,
            bundle.interaction_spec,
            cohort_id=structural_stability_bundle.cohort_id,
            study_config_id=structural_stability_bundle.study_config_id,
        )
    except (TrendlineReplayContractError, TrendlineReplayIntegrityError) as exc:
        raise TrendlineInteractionUtilityError(
            "D3 event replay evidence is invalid"
        ) from exc
    expected_events_by_id = {event.event_id: event for event in expected_events}
    actual_events_by_id = {event.event_id: event for event in bundle.events}
    if len(actual_events_by_id) != len(bundle.events):
        raise TrendlineInteractionUtilityError("duplicate interaction event IDs")
    if set(actual_events_by_id) != set(expected_events_by_id):
        raise TrendlineInteractionUtilityError(
            "D3 events do not match non-left-censored boundary-ray births"
        )
    for event_id, expected in expected_events_by_id.items():
        actual = actual_events_by_id[event_id]
        if actual.to_dict() != expected.to_dict():
            raise TrendlineInteractionUtilityError(
                "D3 event content does not match D2/replay evidence"
            )

    event_ids = set(expected_events_by_id)
    expected_coordinates = {
        (event_id, horizon)
        for event_id in event_ids
        for horizon in bundle.interaction_spec.evaluation_horizons_bars
    }
    actual_coordinates = [
        (outcome.interaction_event_id, outcome.horizon_bars)
        for outcome in bundle.outcomes
    ]
    if len(set(actual_coordinates)) != len(actual_coordinates):
        raise TrendlineInteractionUtilityError(
            "duplicate interaction event/horizon outcomes"
        )
    if set(actual_coordinates) != expected_coordinates:
        raise TrendlineInteractionUtilityError(
            "interaction outcomes do not cover exact event/horizon product"
        )
    outcomes_by_coordinate = {}
    for outcome in bundle.outcomes:
        expected_event = expected_events_by_id.get(outcome.interaction_event_id)
        if expected_event is None:
            raise TrendlineInteractionUtilityError(
                "interaction outcome references unknown event"
            )
        expected_identity = canonical_hash(
            _outcome_payload(outcome),
            semantics_version=INTERACTION_OUTCOME_SEMANTICS_VERSION,
        )
        if outcome.outcome_id != expected_identity:
            raise TrendlineInteractionUtilityError(
                "interaction outcome identity differs"
            )
        _validate_outcome_coordinates(expected_event, outcome)
        outcomes_by_coordinate[
            (outcome.interaction_event_id, outcome.horizon_bars)
        ] = outcome

    expected_outcomes: list[TrendlineInteractionOutcome] = []
    for event in expected_events:
        frame = replay.prepared.dataset.frames[event.timeframe]
        expected_outcomes.extend(
            measure_interaction_outcomes(
                event,
                frame,
                bundle.interaction_spec,
            )
        )
    expected_outcomes_tuple = tuple(expected_outcomes)
    actual_outcomes_tuple = tuple(
        outcomes_by_coordinate[(event.event_id, horizon)]
        for event in expected_events
        for horizon in bundle.interaction_spec.evaluation_horizons_bars
    )
    if tuple(value.to_dict() for value in actual_outcomes_tuple) != tuple(
        value.to_dict() for value in expected_outcomes_tuple
    ):
        raise TrendlineInteractionUtilityError(
            "interaction outcomes do not match replay OHLC evidence"
        )

    expected_summaries = _expected_summaries(
        expected_events,
        expected_outcomes_tuple,
        tuple(replay.prepared.spec.timeframes),
        bundle.interaction_spec,
    )
    if tuple(value.to_dict() for value in bundle.summaries) != tuple(
        value.to_dict() for value in expected_summaries
    ):
        raise TrendlineInteractionUtilityError(
            "interaction summaries do not match outcome content"
        )
    if len({summary.summary_id for summary in bundle.summaries}) != len(bundle.summaries):
        raise TrendlineInteractionUtilityError("duplicate interaction summary IDs")
    if bundle.interaction_utility_bundle_id != canonical_hash(
        _bundle_payload(bundle),
        semantics_version=INTERACTION_UTILITY_BUNDLE_SEMANTICS_VERSION,
    ):
        raise TrendlineInteractionUtilityError("interaction bundle identity differs")


def build_interaction_utility_bundle(
    prepared: PreparedTrendlineResearchRun,
    replay: PreparedTrendlineResearchReplay,
    cohort: TrendlineAdequacyCohort,
    study_config: TrendlineAdequacyStudyConfig,
    structural_stability_bundle: TrendlineStructuralStabilityBundle,
    interaction_spec: TrendlineInteractionUtilitySpec,
) -> TrendlineInteractionUtilityBundle:
    """Build D3 outcomes from a validated replay and committed D2 bundle."""

    events = build_interaction_events(
        prepared,
        replay,
        cohort,
        study_config,
        structural_stability_bundle,
        interaction_spec,
    )
    timeframe_order = {value: index for index, value in enumerate(prepared.spec.timeframes)}
    events = tuple(
        sorted(
            events,
            key=lambda event: (
                timeframe_order[event.timeframe],
                event.selection_position,
                event.role,
                str(event.anchor_key),
                event.episode_id,
            ),
        )
    )
    outcomes: list[TrendlineInteractionOutcome] = []
    for event in events:
        outcomes.extend(
            measure_interaction_outcomes(
                event,
                prepared.dataset.frames[event.timeframe],
                interaction_spec,
            )
        )
    outcomes_tuple = tuple(outcomes)
    summaries = _expected_summaries(
        events,
        outcomes_tuple,
        prepared.spec.timeframes,
        interaction_spec,
    )
    bundle = TrendlineInteractionUtilityBundle(
        dataset_id=prepared.dataset.dataset_id,
        replay_id=replay.replay_id,
        cohort_id=cohort.cohort_id,
        study_config_id=study_config.study_config_id,
        structural_stability_bundle_id=structural_stability_bundle.structural_stability_bundle_id,
        interaction_spec=interaction_spec,
        events=events,
        outcomes=outcomes_tuple,
        summaries=summaries,
    )
    validate_interaction_utility_bundle(
        bundle,
        structural_stability_bundle=structural_stability_bundle,
        replay=replay,
    )
    return bundle


__all__ = [
    "INTERACTION_BREAK_STATUSES",
    "INTERACTION_EVENT_SEMANTICS_VERSION",
    "INTERACTION_OUTCOME_SEMANTICS_VERSION",
    "INTERACTION_ROLES",
    "INTERACTION_SUMMARY_SEMANTICS_VERSION",
    "INTERACTION_UTILITY_BUNDLE_SEMANTICS_VERSION",
    "INTERACTION_UTILITY_SPEC_SEMANTICS_VERSION",
    "TrendlineInteractionEvent",
    "TrendlineInteractionOutcome",
    "TrendlineInteractionSummary",
    "TrendlineInteractionUtilityBundle",
    "TrendlineInteractionUtilityError",
    "TrendlineInteractionUtilitySpec",
    "build_interaction_events",
    "build_interaction_utility_bundle",
    "measure_interaction_outcomes",
    "validate_interaction_utility_bundle",
]
