"""Causal structural-stability measurements for mature trendlines research.

This module consumes validated L2-D1 observations and authoritative diagnostic
rows.  It does not execute model code, match approximate geometry, or fetch
data.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Any

import pandas as pd

from libs.models.trendlines.contracts.identity import canonical_hash
from libs.models.trendlines.workflows.research.diagnostics import (
    LineEvidenceRow,
    RayEvidenceRow,
    replay_line_rows,
    replay_ray_rows,
)
from libs.models.trendlines.workflows.research.replay import (
    PreparedTrendlineResearchReplay,
    validate_replay_point_integrity,
    validated_replay_points,
)

from .contracts import (
    TrendlineAdequacyCohort,
    TrendlineAdequacyContractError,
    TrendlineAdequacyObservation,
    TrendlineAdequacyObservationState,
    TrendlineAdequacyStudyConfig,
    TrendlineObservationUnit,
    build_adequacy_cohort,
)
from .metrics import collect_adequacy_observations


STRUCTURAL_STABILITY_SPEC_SEMANTICS_VERSION = (
    "trendlines.adequacy-structural-stability-spec.v1"
)
STRUCTURAL_STATE_SEMANTICS_VERSION = "trendlines.adequacy-structural-state.v1"
STRUCTURAL_TRANSITION_SEMANTICS_VERSION = (
    "trendlines.adequacy-structural-transition.v1"
)
STRUCTURAL_DRIFT_SEMANTICS_VERSION = "trendlines.adequacy-structural-drift.v1"
STRUCTURAL_EPISODE_SEMANTICS_VERSION = (
    "trendlines.adequacy-structural-episode.v1"
)
STRUCTURAL_SURVIVAL_SEMANTICS_VERSION = (
    "trendlines.adequacy-structural-survival.v1"
)
STRUCTURAL_SUMMARY_SEMANTICS_VERSION = (
    "trendlines.adequacy-structural-summary.v1"
)
STRUCTURAL_STABILITY_BUNDLE_SEMANTICS_VERSION = (
    "trendlines.adequacy-structural-stability-bundle.v1"
)


class TrendlineStructuralStabilityError(TrendlineAdequacyContractError):
    """Raised when structural evidence cannot be measured unambiguously."""


def _strict_int(value: Any, *, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise TrendlineStructuralStabilityError(
            f"{name} must be a non-boolean integer >= {minimum}"
        )
    return value


def _finite(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TrendlineStructuralStabilityError(f"{name} must be finite numeric")
    result = float(value)
    if not isfinite(result):
        raise TrendlineStructuralStabilityError(f"{name} must be finite numeric")
    return result


def _identity(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrendlineStructuralStabilityError(f"{name} must be non-empty")
    return value


def _sha256(value: Any, *, name: str) -> str:
    result = _identity(value, name=name)
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        raise TrendlineStructuralStabilityError(
            f"{name} must be a lowercase SHA-256 identity"
        )
    return result


def _timestamp_text(value: Any, *, name: str) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise TrendlineStructuralStabilityError(f"{name} must be timezone-aware")
    return timestamp.tz_convert("UTC").isoformat()


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _require_derived_rate(
    actual: float | None,
    numerator: int,
    denominator: int,
    *,
    name: str,
) -> None:
    expected = _rate(numerator, denominator)
    if expected is None:
        if actual is not None:
            raise TrendlineStructuralStabilityError(
                f"{name} must be None when its denominator is zero"
            )
        return
    if actual is None:
        raise TrendlineStructuralStabilityError(
            f"{name} must equal its derived count rate"
        )
    actual_value = _finite(actual, name=name)
    if actual_value != expected:
        raise TrendlineStructuralStabilityError(
            f"{name} does not match its derived count rate"
        )


def _unit_order(unit: TrendlineObservationUnit) -> int:
    return 0 if unit is TrendlineObservationUnit.FITTED_LINE else 1


def _tuple_scope(
    eligible_positions: Mapping[str, Sequence[int]] | Mapping[Any, Sequence[int]] | None,
    *,
    timeframe: str,
    observation_unit: TrendlineObservationUnit,
) -> tuple[int, ...] | None:
    if eligible_positions is None:
        return None
    direct = eligible_positions.get(timeframe)
    if direct is None:
        direct = eligible_positions.get((observation_unit, timeframe))
    if direct is None:
        direct = eligible_positions.get((observation_unit.value, timeframe))
    if direct is None:
        return None
    values = tuple(_strict_int(value, name="eligible position") for value in direct)
    if len(set(values)) != len(values) or tuple(sorted(values)) != values:
        raise TrendlineStructuralStabilityError(
            f"eligible positions must be ordered and unique for {timeframe}"
        )
    return values


def _row_sort_key(row: Any) -> tuple[Any, ...]:
    return (
        row.timeframe,
        row.position,
        row.role,
        row.anchor_key,
    )


@dataclass(frozen=True)
class TrendlineStructuralStabilitySpec:
    """Explicit survival horizons and identity semantics for one D2 run."""

    survival_horizons_bars: tuple[int, ...]
    semantics_version: str = STRUCTURAL_STABILITY_SPEC_SEMANTICS_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.survival_horizons_bars, tuple):
            raise TrendlineStructuralStabilityError(
                "survival_horizons_bars must be an ordered tuple"
            )
        horizons = tuple(
            _strict_int(value, name="survival horizon", minimum=1)
            for value in self.survival_horizons_bars
        )
        if not horizons:
            raise TrendlineStructuralStabilityError(
                "survival_horizons_bars must be non-empty"
            )
        if len(set(horizons)) != len(horizons) or tuple(sorted(horizons)) != horizons:
            raise TrendlineStructuralStabilityError(
                "survival_horizons_bars must be ordered and unique"
            )
        if self.semantics_version != STRUCTURAL_STABILITY_SPEC_SEMANTICS_VERSION:
            raise TrendlineStructuralStabilityError(
                "unsupported structural-stability spec semantics_version"
            )
        object.__setattr__(self, "survival_horizons_bars", horizons)

    def to_dict(self) -> dict[str, Any]:
        return {
            "survival_horizons_bars": list(self.survival_horizons_bars),
            "semantics_version": self.semantics_version,
        }

    @property
    def stability_spec_id(self) -> str:
        return canonical_hash(
            self.to_dict(),
            semantics_version=STRUCTURAL_STABILITY_SPEC_SEMANTICS_VERSION,
        )


def _state_payload(state: "TrendlineStructuralState") -> dict[str, Any]:
    return {
        "cohort_id": state.cohort_id,
        "stability_spec_id": state.stability_spec_id,
        "observation_unit": state.observation_unit.value,
        "timeframe": state.timeframe,
        "position": state.position,
        "event_at": state.event_at,
        "available_at": state.available_at,
        "anchor_key": list(state.anchor_key),
        "role": state.role,
        "shape": list(state.shape),
        "quality": list(state.quality),
        "replay_point_id": state.replay_point_id,
        "content_id": state.content_id,
        "source_id": state.source_id,
        "checkpoint_id": state.checkpoint_id,
        "boundary_snapshot_id": state.boundary_snapshot_id,
        "boundary_revision_id": state.boundary_revision_id,
        "semantics_version": STRUCTURAL_STATE_SEMANTICS_VERSION,
    }


@dataclass(frozen=True)
class TrendlineStructuralState:
    """One exact diagnostic anchor at one eligible replay position."""

    cohort_id: str
    stability_spec_id: str
    observation_unit: TrendlineObservationUnit
    timeframe: str
    position: int
    event_at: str
    available_at: str
    anchor_key: tuple[Any, ...]
    role: str
    shape: tuple[float, ...]
    quality: tuple[float, ...]
    replay_point_id: str
    content_id: str
    source_id: str
    checkpoint_id: str
    boundary_snapshot_id: str
    boundary_revision_id: str
    state_id: str = ""

    def __post_init__(self) -> None:
        _identity(self.cohort_id, name="state cohort_id")
        _sha256(self.stability_spec_id, name="state stability_spec_id")
        if not isinstance(self.observation_unit, TrendlineObservationUnit):
            raise TrendlineStructuralStabilityError("state observation_unit is invalid")
        _identity(self.timeframe, name="state timeframe")
        _strict_int(self.position, name="state position")
        event_at = _timestamp_text(self.event_at, name="state event_at")
        available_at = _timestamp_text(self.available_at, name="state available_at")
        if available_at < event_at:
            raise TrendlineStructuralStabilityError(
                "state available_at precedes event_at"
            )
        if not isinstance(self.anchor_key, tuple) or not self.anchor_key:
            raise TrendlineStructuralStabilityError("state anchor_key must be non-empty tuple")
        role = _identity(self.role, name="state role")
        shape = tuple(_finite(value, name="state shape") for value in self.shape)
        quality = tuple(_finite(value, name="state quality") for value in self.quality)
        if not shape or not quality:
            raise TrendlineStructuralStabilityError("state shape and quality are required")
        for name, value in (
            ("replay_point_id", self.replay_point_id),
            ("content_id", self.content_id),
            ("source_id", self.source_id),
            ("checkpoint_id", self.checkpoint_id),
            ("boundary_snapshot_id", self.boundary_snapshot_id),
            ("boundary_revision_id", self.boundary_revision_id),
        ):
            _sha256(value, name=f"state {name}")
        object.__setattr__(self, "event_at", event_at)
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "shape", shape)
        object.__setattr__(self, "quality", quality)
        expected = canonical_hash(
            _state_payload(self),
            semantics_version=STRUCTURAL_STATE_SEMANTICS_VERSION,
        )
        if self.state_id and self.state_id != expected:
            raise TrendlineStructuralStabilityError(
                "state_id does not match state content"
            )
        object.__setattr__(self, "state_id", expected)

    def to_dict(self) -> dict[str, Any]:
        return {**_state_payload(self), "state_id": self.state_id}


def _transition_payload(transition: "TrendlineStructuralTransition") -> dict[str, Any]:
    return {
        "observation_unit": transition.observation_unit.value,
        "timeframe": transition.timeframe,
        "left_position": transition.left_position,
        "right_position": transition.right_position,
        "position_gap_bars": transition.position_gap_bars,
        "previous_active_count": transition.previous_active_count,
        "current_active_count": transition.current_active_count,
        "persistent_anchor_count": transition.persistent_anchor_count,
        "birth_count": transition.birth_count,
        "disappearance_count": transition.disappearance_count,
        "shape_revision_count": transition.shape_revision_count,
        "role_switch_count": transition.role_switch_count,
        "anchor_persistence_rate": transition.anchor_persistence_rate,
        "birth_rate": transition.birth_rate,
        "disappearance_rate": transition.disappearance_rate,
        "revision_churn_rate": transition.revision_churn_rate,
        "left_state_ids": list(transition.left_state_ids),
        "right_state_ids": list(transition.right_state_ids),
        "semantics_version": STRUCTURAL_TRANSITION_SEMANTICS_VERSION,
    }


@dataclass(frozen=True)
class TrendlineStructuralTransition:
    """Exact structural change between adjacent eligible observations."""

    observation_unit: TrendlineObservationUnit
    timeframe: str
    left_position: int
    right_position: int
    position_gap_bars: int
    previous_active_count: int
    current_active_count: int
    persistent_anchor_count: int
    birth_count: int
    disappearance_count: int
    shape_revision_count: int
    role_switch_count: int
    anchor_persistence_rate: float | None
    birth_rate: float | None
    disappearance_rate: float | None
    revision_churn_rate: float | None
    left_state_ids: tuple[str, ...] = ()
    right_state_ids: tuple[str, ...] = ()
    transition_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.observation_unit, TrendlineObservationUnit):
            raise TrendlineStructuralStabilityError("transition observation_unit is invalid")
        _identity(self.timeframe, name="transition timeframe")
        _strict_int(self.left_position, name="transition left_position")
        _strict_int(self.right_position, name="transition right_position")
        _strict_int(self.position_gap_bars, name="transition position_gap_bars", minimum=1)
        if self.right_position <= self.left_position:
            raise TrendlineStructuralStabilityError("transition positions must increase")
        if self.position_gap_bars != self.right_position - self.left_position:
            raise TrendlineStructuralStabilityError(
                "transition position_gap_bars does not match positions"
            )
        counts = (
            ("previous_active_count", self.previous_active_count),
            ("current_active_count", self.current_active_count),
            ("persistent_anchor_count", self.persistent_anchor_count),
            ("birth_count", self.birth_count),
            ("disappearance_count", self.disappearance_count),
            ("shape_revision_count", self.shape_revision_count),
            ("role_switch_count", self.role_switch_count),
        )
        for name, value in counts:
            _strict_int(value, name=f"transition {name}")
        if self.persistent_anchor_count > min(
            self.previous_active_count,
            self.current_active_count,
        ):
            raise TrendlineStructuralStabilityError(
                "persistent anchors exceed active anchors"
            )
        if (
            self.persistent_anchor_count + self.birth_count
            != self.current_active_count
        ):
            raise TrendlineStructuralStabilityError(
                "persistent anchors plus births must equal current active anchors"
            )
        if (
            self.persistent_anchor_count + self.disappearance_count
            != self.previous_active_count
        ):
            raise TrendlineStructuralStabilityError(
                "persistent anchors plus disappearances must equal previous active anchors"
            )
        if self.shape_revision_count > self.persistent_anchor_count:
            raise TrendlineStructuralStabilityError(
                "shape revisions exceed persistent anchors"
            )
        if self.role_switch_count > self.persistent_anchor_count:
            raise TrendlineStructuralStabilityError(
                "role switches exceed persistent anchors"
            )
        _require_derived_rate(
            self.anchor_persistence_rate,
            self.persistent_anchor_count,
            self.previous_active_count,
            name="transition anchor_persistence_rate",
        )
        _require_derived_rate(
            self.birth_rate,
            self.birth_count,
            self.current_active_count,
            name="transition birth_rate",
        )
        _require_derived_rate(
            self.disappearance_rate,
            self.disappearance_count,
            self.previous_active_count,
            name="transition disappearance_rate",
        )
        _require_derived_rate(
            self.revision_churn_rate,
            self.shape_revision_count,
            self.persistent_anchor_count,
            name="transition revision_churn_rate",
        )
        left_state_ids = tuple(_sha256(value, name="left state_id") for value in self.left_state_ids)
        right_state_ids = tuple(_sha256(value, name="right state_id") for value in self.right_state_ids)
        if len(left_state_ids) != self.previous_active_count:
            raise TrendlineStructuralStabilityError(
                "left_state_ids count differs from previous active count"
            )
        if len(right_state_ids) != self.current_active_count:
            raise TrendlineStructuralStabilityError(
                "right_state_ids count differs from current active count"
            )
        expected = canonical_hash(
            {
                **_transition_payload(self),
                "left_state_ids": list(left_state_ids),
                "right_state_ids": list(right_state_ids),
            },
            semantics_version=STRUCTURAL_TRANSITION_SEMANTICS_VERSION,
        )
        if self.transition_id and self.transition_id != expected:
            raise TrendlineStructuralStabilityError(
                "transition_id does not match transition content"
            )
        object.__setattr__(self, "left_state_ids", left_state_ids)
        object.__setattr__(self, "right_state_ids", right_state_ids)
        object.__setattr__(self, "transition_id", expected)

    def to_dict(self) -> dict[str, Any]:
        return {**_transition_payload(self), "transition_id": self.transition_id}


def _episode_payload(episode: "TrendlineStructuralEpisode") -> dict[str, Any]:
    return {
        "observation_unit": episode.observation_unit.value,
        "timeframe": episode.timeframe,
        "anchor_key": list(episode.anchor_key),
        "episode_ordinal": episode.episode_ordinal,
        "first_position": episode.first_position,
        "last_position": episode.last_position,
        "observed_position_count": episode.observed_position_count,
        "observed_positions": list(episode.observed_positions),
        "position_span_bars": episode.position_span_bars,
        "initial_role": episode.initial_role,
        "final_role": episode.final_role,
        "role_switch_count": episode.role_switch_count,
        "shape_revision_count": episode.shape_revision_count,
        "left_censored": episode.left_censored,
        "right_censored": episode.right_censored,
        "semantics_version": STRUCTURAL_EPISODE_SEMANTICS_VERSION,
    }


def _drift_payload(drift: "TrendlineStructuralDrift") -> dict[str, Any]:
    return {
        "observation_unit": drift.observation_unit.value,
        "timeframe": drift.timeframe,
        "left_position": drift.left_position,
        "right_position": drift.right_position,
        "anchor_key": list(drift.anchor_key),
        "role_before": drift.role_before,
        "role_after": drift.role_after,
        "slope_delta": drift.slope_delta,
        "intercept_delta": drift.intercept_delta,
        "start_value_delta": drift.start_value_delta,
        "end_value_delta": drift.end_value_delta,
        "start_price_delta": drift.start_price_delta,
        "end_price_delta": drift.end_price_delta,
        "touch_count_delta": drift.touch_count_delta,
        "score_delta": drift.score_delta,
        "quality_delta": drift.quality_delta,
        "r_squared_delta": drift.r_squared_delta,
        "left_state_id": drift.left_state_id,
        "right_state_id": drift.right_state_id,
        "semantics_version": STRUCTURAL_DRIFT_SEMANTICS_VERSION,
    }


@dataclass(frozen=True)
class TrendlineStructuralDrift:
    """Descriptive exact deltas for one persistent anchor transition."""

    observation_unit: TrendlineObservationUnit
    timeframe: str
    left_position: int
    right_position: int
    anchor_key: tuple[Any, ...]
    role_before: str
    role_after: str
    slope_delta: float
    intercept_delta: float
    start_value_delta: float | None
    end_value_delta: float | None
    start_price_delta: float | None
    end_price_delta: float | None
    touch_count_delta: float
    score_delta: float | None
    quality_delta: float | None
    r_squared_delta: float | None
    left_state_id: str
    right_state_id: str
    drift_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.observation_unit, TrendlineObservationUnit):
            raise TrendlineStructuralStabilityError("drift observation_unit is invalid")
        _identity(self.timeframe, name="drift timeframe")
        _strict_int(self.left_position, name="drift left_position")
        _strict_int(self.right_position, name="drift right_position")
        if self.right_position <= self.left_position:
            raise TrendlineStructuralStabilityError("drift positions must increase")
        if not isinstance(self.anchor_key, tuple) or not self.anchor_key:
            raise TrendlineStructuralStabilityError("drift anchor_key is required")
        _identity(self.role_before, name="drift role_before")
        _identity(self.role_after, name="drift role_after")
        for name, value in (
            ("slope_delta", self.slope_delta),
            ("intercept_delta", self.intercept_delta),
            ("touch_count_delta", self.touch_count_delta),
        ):
            _finite(value, name=f"drift {name}")
        for name, value in (
            ("start_value_delta", self.start_value_delta),
            ("end_value_delta", self.end_value_delta),
            ("start_price_delta", self.start_price_delta),
            ("end_price_delta", self.end_price_delta),
            ("score_delta", self.score_delta),
            ("quality_delta", self.quality_delta),
            ("r_squared_delta", self.r_squared_delta),
        ):
            if value is not None:
                _finite(value, name=f"drift {name}")
        _sha256(self.left_state_id, name="drift left_state_id")
        _sha256(self.right_state_id, name="drift right_state_id")
        expected = canonical_hash(
            _drift_payload(self),
            semantics_version=STRUCTURAL_DRIFT_SEMANTICS_VERSION,
        )
        if self.drift_id and self.drift_id != expected:
            raise TrendlineStructuralStabilityError(
                "drift_id does not match drift content"
            )
        object.__setattr__(self, "drift_id", expected)

    def to_dict(self) -> dict[str, Any]:
        return {**_drift_payload(self), "drift_id": self.drift_id}


@dataclass(frozen=True)
class TrendlineStructuralEpisode:
    """One consecutive-presence episode for one roleless anchor."""

    observation_unit: TrendlineObservationUnit
    timeframe: str
    anchor_key: tuple[Any, ...]
    episode_ordinal: int
    first_position: int
    last_position: int
    observed_position_count: int
    position_span_bars: int
    initial_role: str
    final_role: str
    role_switch_count: int
    shape_revision_count: int
    left_censored: bool
    right_censored: bool
    observed_positions: tuple[int, ...]
    episode_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.observation_unit, TrendlineObservationUnit):
            raise TrendlineStructuralStabilityError("episode observation_unit is invalid")
        _identity(self.timeframe, name="episode timeframe")
        if not isinstance(self.anchor_key, tuple) or not self.anchor_key:
            raise TrendlineStructuralStabilityError("episode anchor_key is required")
        _strict_int(self.episode_ordinal, name="episode ordinal")
        first = _strict_int(self.first_position, name="episode first_position")
        last = _strict_int(self.last_position, name="episode last_position")
        if last < first:
            raise TrendlineStructuralStabilityError("episode positions must be ordered")
        count = _strict_int(
            self.observed_position_count,
            name="episode observed_position_count",
            minimum=1,
        )
        if not isinstance(self.observed_positions, tuple) or not self.observed_positions:
            raise TrendlineStructuralStabilityError(
                "episode observed_positions must be an explicit non-empty tuple"
            )
        positions = tuple(
            _strict_int(value, name="episode observed position")
            for value in self.observed_positions
        )
        if tuple(sorted(set(positions))) != positions:
            raise TrendlineStructuralStabilityError(
                "episode observed positions must be ordered and unique"
            )
        if positions[0] != first or positions[-1] != last or len(positions) != count:
            raise TrendlineStructuralStabilityError(
                "episode observed positions do not match episode bounds"
            )
        if self.position_span_bars != last - first:
            raise TrendlineStructuralStabilityError(
                "episode position_span_bars is inconsistent"
            )
        if not isinstance(self.left_censored, bool) or not isinstance(
            self.right_censored, bool
        ):
            raise TrendlineStructuralStabilityError("episode censoring flags must be bool")
        _identity(self.initial_role, name="episode initial_role")
        _identity(self.final_role, name="episode final_role")
        _strict_int(self.role_switch_count, name="episode role_switch_count")
        _strict_int(self.shape_revision_count, name="episode shape_revision_count")
        if self.role_switch_count > max(0, count - 1):
            raise TrendlineStructuralStabilityError("episode role switches exceed observations")
        if self.shape_revision_count > max(0, count - 1):
            raise TrendlineStructuralStabilityError("episode revisions exceed observations")
        expected = canonical_hash(
            _episode_payload(self),
            semantics_version=STRUCTURAL_EPISODE_SEMANTICS_VERSION,
        )
        if self.episode_id and self.episode_id != expected:
            raise TrendlineStructuralStabilityError(
                "episode_id does not match episode content"
            )
        object.__setattr__(self, "observed_positions", positions)
        object.__setattr__(self, "episode_id", expected)

    def to_dict(self) -> dict[str, Any]:
        return {**_episode_payload(self), "episode_id": self.episode_id}


def _survival_payload(survival: "TrendlineStructuralSurvival") -> dict[str, Any]:
    return {
        "observation_unit": survival.observation_unit.value,
        "timeframe": survival.timeframe,
        "horizon_bars": survival.horizon_bars,
        "observed_birth_count": survival.observed_birth_count,
        "eligible_target_count": survival.eligible_target_count,
        "survived_count": survival.survived_count,
        "failed_count": survival.failed_count,
        "right_censored_count": survival.right_censored_count,
        "target_unavailable_count": survival.target_unavailable_count,
        "survival_rate": survival.survival_rate,
        "semantics_version": STRUCTURAL_SURVIVAL_SEMANTICS_VERSION,
    }


@dataclass(frozen=True)
class TrendlineStructuralSurvival:
    """Exact-horizon episode survival accounting."""

    observation_unit: TrendlineObservationUnit
    timeframe: str
    horizon_bars: int
    observed_birth_count: int
    eligible_target_count: int
    survived_count: int
    failed_count: int
    right_censored_count: int
    target_unavailable_count: int
    survival_rate: float | None
    survival_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.observation_unit, TrendlineObservationUnit):
            raise TrendlineStructuralStabilityError("survival observation_unit is invalid")
        _identity(self.timeframe, name="survival timeframe")
        _strict_int(self.horizon_bars, name="survival horizon", minimum=1)
        counts = (
            ("observed_birth_count", self.observed_birth_count),
            ("eligible_target_count", self.eligible_target_count),
            ("survived_count", self.survived_count),
            ("failed_count", self.failed_count),
            ("right_censored_count", self.right_censored_count),
            ("target_unavailable_count", self.target_unavailable_count),
        )
        for name, value in counts:
            _strict_int(value, name=f"survival {name}")
        if self.survived_count + self.failed_count != self.eligible_target_count:
            raise TrendlineStructuralStabilityError(
                "survival target counts are inconsistent"
            )
        if (
            self.eligible_target_count
            + self.right_censored_count
            + self.target_unavailable_count
            != self.observed_birth_count
        ):
            raise TrendlineStructuralStabilityError(
                "survival birth counts are inconsistent"
            )
        expected_rate = _rate(self.survived_count, self.eligible_target_count)
        if self.survival_rate != expected_rate:
            raise TrendlineStructuralStabilityError(
                "survival_rate does not match survived and eligible target counts"
            )
        if expected_rate is not None:
            _finite(self.survival_rate, name="survival rate")
            object.__setattr__(self, "survival_rate", expected_rate)
        expected = canonical_hash(
            _survival_payload(self),
            semantics_version=STRUCTURAL_SURVIVAL_SEMANTICS_VERSION,
        )
        if self.survival_id and self.survival_id != expected:
            raise TrendlineStructuralStabilityError(
                "survival_id does not match survival content"
            )
        object.__setattr__(self, "survival_id", expected)

    def to_dict(self) -> dict[str, Any]:
        return {**_survival_payload(self), "survival_id": self.survival_id}


def _summary_payload(summary: "TrendlineStructuralSummary") -> dict[str, Any]:
    return {
        "observation_unit": summary.observation_unit.value,
        "timeframe": summary.timeframe,
        "eligible_point_count": summary.eligible_point_count,
        "transition_count": summary.transition_count,
        "mean_active_anchor_count": summary.mean_active_anchor_count,
        "minimum_active_anchor_count": summary.minimum_active_anchor_count,
        "maximum_active_anchor_count": summary.maximum_active_anchor_count,
        "total_birth_count": summary.total_birth_count,
        "total_disappearance_count": summary.total_disappearance_count,
        "total_persistent_anchor_count": summary.total_persistent_anchor_count,
        "total_shape_revision_count": summary.total_shape_revision_count,
        "total_role_switch_count": summary.total_role_switch_count,
        "anchor_persistence_rate": summary.anchor_persistence_rate,
        "birth_rate": summary.birth_rate,
        "disappearance_rate": summary.disappearance_rate,
        "revision_churn_rate": summary.revision_churn_rate,
        "episode_count": summary.episode_count,
        "observed_birth_episode_count": summary.observed_birth_episode_count,
        "survival": [row.to_dict() for row in summary.survival],
        "semantics_version": STRUCTURAL_SUMMARY_SEMANTICS_VERSION,
    }


@dataclass(frozen=True)
class TrendlineStructuralSummary:
    """Aggregate structural counts and denominator-aware rates."""

    observation_unit: TrendlineObservationUnit
    timeframe: str
    eligible_point_count: int
    transition_count: int
    mean_active_anchor_count: float | None
    minimum_active_anchor_count: int | None
    maximum_active_anchor_count: int | None
    total_birth_count: int
    total_disappearance_count: int
    total_persistent_anchor_count: int
    total_shape_revision_count: int
    total_role_switch_count: int
    anchor_persistence_rate: float | None
    birth_rate: float | None
    disappearance_rate: float | None
    revision_churn_rate: float | None
    episode_count: int
    observed_birth_episode_count: int
    survival: tuple[TrendlineStructuralSurvival, ...]
    summary_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.observation_unit, TrendlineObservationUnit):
            raise TrendlineStructuralStabilityError("summary observation_unit is invalid")
        _identity(self.timeframe, name="summary timeframe")
        for name, value in (
            ("eligible_point_count", self.eligible_point_count),
            ("transition_count", self.transition_count),
            ("total_birth_count", self.total_birth_count),
            ("total_disappearance_count", self.total_disappearance_count),
            ("total_persistent_anchor_count", self.total_persistent_anchor_count),
            ("total_shape_revision_count", self.total_shape_revision_count),
            ("total_role_switch_count", self.total_role_switch_count),
            ("episode_count", self.episode_count),
            ("observed_birth_episode_count", self.observed_birth_episode_count),
        ):
            _strict_int(value, name=f"summary {name}")
        if self.mean_active_anchor_count is not None:
            _finite(self.mean_active_anchor_count, name="summary mean active count")
        for name, value in (
            ("minimum_active_anchor_count", self.minimum_active_anchor_count),
            ("maximum_active_anchor_count", self.maximum_active_anchor_count),
        ):
            if value is not None:
                _strict_int(value, name=f"summary {name}")
        if (
            self.minimum_active_anchor_count is None
        ) != (self.maximum_active_anchor_count is None):
            raise TrendlineStructuralStabilityError(
                "summary active-count bounds must both be present or absent"
            )
        for name, value in (
            ("anchor_persistence_rate", self.anchor_persistence_rate),
            ("birth_rate", self.birth_rate),
            ("disappearance_rate", self.disappearance_rate),
            ("revision_churn_rate", self.revision_churn_rate),
        ):
            if value is not None:
                _finite(value, name=f"summary {name}")
        survival = tuple(self.survival)
        if not all(isinstance(value, TrendlineStructuralSurvival) for value in survival):
            raise TrendlineStructuralStabilityError("summary survival rows must be typed")
        if len({value.horizon_bars for value in survival}) != len(survival):
            raise TrendlineStructuralStabilityError("summary survival horizons must be unique")
        expected = canonical_hash(
            _summary_payload(self),
            semantics_version=STRUCTURAL_SUMMARY_SEMANTICS_VERSION,
        )
        if self.summary_id and self.summary_id != expected:
            raise TrendlineStructuralStabilityError(
                "summary_id does not match summary content"
            )
        object.__setattr__(self, "survival", survival)
        object.__setattr__(self, "summary_id", expected)

    def to_dict(self) -> dict[str, Any]:
        return {**_summary_payload(self), "summary_id": self.summary_id}


def _bundle_payload(bundle: "TrendlineStructuralStabilityBundle") -> dict[str, Any]:
    return {
        "cohort_id": bundle.cohort_id,
        "study_config_id": bundle.study_config_id,
        "stability_spec_id": bundle.stability_spec_id,
        "eligible_observation_identities": [
            list(identity) for identity in bundle.eligible_observation_identities
        ],
        "eligible_positions": [
            {"timeframe": timeframe, "positions": list(positions)}
            for timeframe, positions in bundle.eligible_positions
        ],
        "state_rows": [row.to_dict() for row in bundle.state_rows],
        "transition_rows": [row.to_dict() for row in bundle.transition_rows],
        "drift_rows": [row.to_dict() for row in bundle.drift_rows],
        "episode_rows": [row.to_dict() for row in bundle.episode_rows],
        "survival_rows": [row.to_dict() for row in bundle.survival_rows],
        "summaries": [row.to_dict() for row in bundle.summaries],
        "semantics_version": STRUCTURAL_STABILITY_BUNDLE_SEMANTICS_VERSION,
    }


@dataclass(frozen=True)
class TrendlineStructuralStabilityBundle:
    """Content-addressed structural measurements for one frozen cohort."""

    structural_stability_bundle_id: str
    cohort_id: str
    study_config_id: str
    stability_spec_id: str
    eligible_observation_identities: tuple[tuple[Any, ...], ...]
    eligible_positions: tuple[tuple[str, tuple[int, ...]], ...]
    state_rows: tuple[TrendlineStructuralState, ...]
    transition_rows: tuple[TrendlineStructuralTransition, ...]
    drift_rows: tuple[TrendlineStructuralDrift, ...]
    episode_rows: tuple[TrendlineStructuralEpisode, ...]
    survival_rows: tuple[TrendlineStructuralSurvival, ...]
    summaries: tuple[TrendlineStructuralSummary, ...]
    semantics_version: str = STRUCTURAL_STABILITY_BUNDLE_SEMANTICS_VERSION

    def __post_init__(self) -> None:
        _sha256(self.cohort_id, name="bundle cohort_id")
        _sha256(self.study_config_id, name="bundle study_config_id")
        _sha256(self.stability_spec_id, name="bundle stability_spec_id")
        identities = tuple(tuple(value) for value in self.eligible_observation_identities)
        positions = tuple(
            (str(timeframe), tuple(_strict_int(value, name="eligible position") for value in values))
            for timeframe, values in self.eligible_positions
        )
        if len({timeframe for timeframe, _ in positions}) != len(positions):
            raise TrendlineStructuralStabilityError("bundle eligible timeframes must be unique")
        for rows, row_type in (
            (self.state_rows, TrendlineStructuralState),
            (self.transition_rows, TrendlineStructuralTransition),
            (self.drift_rows, TrendlineStructuralDrift),
            (self.episode_rows, TrendlineStructuralEpisode),
            (self.survival_rows, TrendlineStructuralSurvival),
            (self.summaries, TrendlineStructuralSummary),
        ):
            if not all(isinstance(row, row_type) for row in rows):
                raise TrendlineStructuralStabilityError("bundle contains untyped structural rows")
        if self.semantics_version != STRUCTURAL_STABILITY_BUNDLE_SEMANTICS_VERSION:
            raise TrendlineStructuralStabilityError("unsupported structural bundle semantics_version")
        expected = canonical_hash(
            {
                **_bundle_payload(self),
                "semantics_version": STRUCTURAL_STABILITY_BUNDLE_SEMANTICS_VERSION,
            },
            semantics_version=STRUCTURAL_STABILITY_BUNDLE_SEMANTICS_VERSION,
        )
        if self.structural_stability_bundle_id and self.structural_stability_bundle_id != expected:
            raise TrendlineStructuralStabilityError(
                "structural_stability_bundle_id does not match bundle content"
            )
        object.__setattr__(self, "eligible_observation_identities", identities)
        object.__setattr__(self, "eligible_positions", positions)
        object.__setattr__(self, "structural_stability_bundle_id", expected)

    @property
    def bundle_id(self) -> str:
        return self.structural_stability_bundle_id

    def computed_bundle_id(self) -> str:
        return canonical_hash(
            _bundle_payload(self),
            semantics_version=STRUCTURAL_STABILITY_BUNDLE_SEMANTICS_VERSION,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "structural_stability_bundle_id": self.structural_stability_bundle_id,
            **_bundle_payload(self),
        }


def _check_observation_binding(
    observation: TrendlineAdequacyObservation,
    row: LineEvidenceRow | RayEvidenceRow,
) -> None:
    if (
        row.timeframe,
        row.position,
        row.replay_point_id,
        row.content_id,
        row.source_id,
        row.checkpoint_id,
    ) != (
        observation.timeframe,
        observation.position,
        observation.replay_point_id,
        observation.content_id,
        observation.source_id,
        observation.checkpoint_id,
    ):
        raise TrendlineStructuralStabilityError(
            "diagnostic row does not bind its adequacy observation"
        )


def _make_line_state(
    observation: TrendlineAdequacyObservation,
    row: LineEvidenceRow,
    spec: TrendlineStructuralStabilitySpec,
) -> TrendlineStructuralState:
    if row.start_position >= row.end_position:
        raise TrendlineStructuralStabilityError("line anchor positions must increase")
    return TrendlineStructuralState(
        cohort_id=observation.cohort_id,
        stability_spec_id=spec.stability_spec_id,
        observation_unit=TrendlineObservationUnit.FITTED_LINE,
        timeframe=row.timeframe,
        position=row.position,
        event_at=observation.event_at.isoformat(),
        available_at=observation.available_at.isoformat(),
        anchor_key=(row.timeframe, row.method, row.start_position, row.end_position),
        role=row.role,
        shape=(row.start_value, row.end_value, row.slope, row.intercept),
        quality=(row.touch_count, row.score),
        replay_point_id=row.replay_point_id,
        content_id=row.content_id,
        source_id=row.source_id,
        checkpoint_id=row.checkpoint_id,
        boundary_snapshot_id=row.boundary_snapshot_id,
        boundary_revision_id=row.boundary_revision_id,
    )


def _make_ray_state(
    observation: TrendlineAdequacyObservation,
    row: RayEvidenceRow,
    spec: TrendlineStructuralStabilitySpec,
) -> TrendlineStructuralState:
    if pd.Timestamp(row.start_time) >= pd.Timestamp(row.end_time):
        raise TrendlineStructuralStabilityError("ray anchor times must increase")
    return TrendlineStructuralState(
        cohort_id=observation.cohort_id,
        stability_spec_id=spec.stability_spec_id,
        observation_unit=TrendlineObservationUnit.BOUNDARY_RAY,
        timeframe=row.timeframe,
        position=row.position,
        event_at=observation.event_at.isoformat(),
        available_at=observation.available_at.isoformat(),
        anchor_key=(row.timeframe, row.start_time, row.end_time),
        role=row.role,
        shape=(row.start_price, row.end_price, row.slope, row.intercept),
        quality=(row.touch_count, row.quality, row.r_squared),
        replay_point_id=row.replay_point_id,
        content_id=row.content_id,
        source_id=row.source_id,
        checkpoint_id=row.checkpoint_id,
        boundary_snapshot_id=row.boundary_snapshot_id,
        boundary_revision_id=row.boundary_revision_id,
    )


def build_structural_states(
    cohort: TrendlineAdequacyCohort,
    observations: Iterable[TrendlineAdequacyObservation],
    line_rows: Iterable[LineEvidenceRow],
    ray_rows: Iterable[RayEvidenceRow],
    stability_spec: TrendlineStructuralStabilitySpec,
) -> tuple[TrendlineStructuralState, ...]:
    """Build exact anchor states from eligible observations and diagnostic rows."""

    if not isinstance(cohort, TrendlineAdequacyCohort):
        raise TrendlineStructuralStabilityError("cohort must be typed")
    if not isinstance(stability_spec, TrendlineStructuralStabilitySpec):
        raise TrendlineStructuralStabilityError("stability_spec must be typed")
    observation_map: dict[tuple[str, int], TrendlineAdequacyObservation] = {}
    for observation in observations:
        if not isinstance(observation, TrendlineAdequacyObservation):
            raise TrendlineStructuralStabilityError("observations must be typed")
        if observation.cohort_id != cohort.cohort_id:
            raise TrendlineStructuralStabilityError("observation cohort differs from cohort")
        coordinate = (observation.timeframe, observation.position)
        if coordinate in observation_map:
            raise TrendlineStructuralStabilityError("duplicate adequacy observation coordinate")
        observation_map[coordinate] = observation

    line_by_coordinate: dict[tuple[str, int], list[LineEvidenceRow]] = defaultdict(list)
    for row in line_rows:
        if not isinstance(row, LineEvidenceRow):
            raise TrendlineStructuralStabilityError("line_rows must contain typed rows")
        coordinate = (row.timeframe, row.position)
        observation = observation_map.get(coordinate)
        if observation is None or observation.state is not TrendlineAdequacyObservationState.ELIGIBLE:
            continue
        _check_observation_binding(observation, row)
        line_by_coordinate[coordinate].append(row)

    ray_by_coordinate: dict[tuple[str, int], list[RayEvidenceRow]] = defaultdict(list)
    for row in ray_rows:
        if not isinstance(row, RayEvidenceRow):
            raise TrendlineStructuralStabilityError("ray_rows must contain typed rows")
        coordinate = (row.timeframe, row.position)
        observation = observation_map.get(coordinate)
        if observation is None or observation.state is not TrendlineAdequacyObservationState.ELIGIBLE:
            continue
        _check_observation_binding(observation, row)
        ray_by_coordinate[coordinate].append(row)

    states: list[TrendlineStructuralState] = []
    for coordinate in sorted(
        (
            key
            for key, observation in observation_map.items()
            if observation.state is TrendlineAdequacyObservationState.ELIGIBLE
        ),
        key=lambda value: (cohort.timeframes.index(value[0]), value[1]),
    ):
        observation = observation_map[coordinate]
        seen: set[tuple[TrendlineObservationUnit, tuple[Any, ...]]] = set()
        for row in sorted(line_by_coordinate.get(coordinate, ()), key=lambda value: (value.role, value.ordinal)):
            state = _make_line_state(observation, row, stability_spec)
            key = (state.observation_unit, state.anchor_key)
            if key in seen:
                raise TrendlineStructuralStabilityError(
                    "duplicate roleless fitted-line anchor at one observation"
                )
            seen.add(key)
            states.append(state)
        for row in sorted(ray_by_coordinate.get(coordinate, ()), key=lambda value: (value.role, value.ordinal)):
            state = _make_ray_state(observation, row, stability_spec)
            key = (state.observation_unit, state.anchor_key)
            if key in seen:
                raise TrendlineStructuralStabilityError(
                    "duplicate roleless boundary-ray anchor at one observation"
                )
            seen.add(key)
            states.append(state)
    return tuple(states)


def _group_states(
    states: Iterable[TrendlineStructuralState],
) -> dict[tuple[TrendlineObservationUnit, str], dict[int, dict[tuple[Any, ...], TrendlineStructuralState]]]:
    grouped: dict[
        tuple[TrendlineObservationUnit, str],
        dict[int, dict[tuple[Any, ...], TrendlineStructuralState]],
    ] = defaultdict(lambda: defaultdict(dict))
    for state in states:
        key = (state.observation_unit, state.timeframe)
        if state.anchor_key in grouped[key][state.position]:
            raise TrendlineStructuralStabilityError(
                "duplicate roleless anchor key at one observation"
            )
        grouped[key][state.position][state.anchor_key] = state
    return grouped


def _ordered_scope_positions(
    grouped: Mapping[tuple[TrendlineObservationUnit, str], Mapping[int, Any]],
    *,
    eligible_positions: Mapping[str, Sequence[int]] | Mapping[Any, Sequence[int]] | None,
    unit: TrendlineObservationUnit,
    timeframe: str,
) -> tuple[int, ...]:
    explicit = _tuple_scope(
        eligible_positions,
        timeframe=timeframe,
        observation_unit=unit,
    )
    if explicit is not None:
        return explicit
    return tuple(sorted(grouped.get((unit, timeframe), {})))


def _scope_timeframes(
    eligible_positions: Mapping[str, Sequence[int]] | Mapping[Any, Sequence[int]] | None,
) -> tuple[str, ...]:
    if eligible_positions is None:
        return ()
    values: list[str] = []
    for key in eligible_positions:
        timeframe = key if isinstance(key, str) else key[1]
        if timeframe not in values:
            values.append(timeframe)
    return tuple(values)


def measure_structural_transitions(
    states: Iterable[TrendlineStructuralState],
    *,
    eligible_positions: Mapping[str, Sequence[int]] | Mapping[Any, Sequence[int]] | None = None,
) -> tuple[TrendlineStructuralTransition, ...]:
    """Measure exact changes between adjacent eligible observation positions."""

    values = tuple(states)
    if not all(isinstance(value, TrendlineStructuralState) for value in values):
        raise TrendlineStructuralStabilityError("states must contain typed rows")
    grouped = _group_states(values)
    keys_set = set(grouped)
    for timeframe in _scope_timeframes(eligible_positions):
        keys_set.update(
            {
                (TrendlineObservationUnit.FITTED_LINE, timeframe),
                (TrendlineObservationUnit.BOUNDARY_RAY, timeframe),
            }
        )
    for key in eligible_positions or {}:
        if not isinstance(key, str):
            unit = key[0]
            if not isinstance(unit, TrendlineObservationUnit):
                unit = TrendlineObservationUnit(str(unit))
            keys_set.add((unit, key[1]))
    keys = sorted(keys_set, key=lambda value: (value[1], _unit_order(value[0])))
    result: list[TrendlineStructuralTransition] = []
    for unit, timeframe in keys:
        positions = _ordered_scope_positions(
            grouped,
            eligible_positions=eligible_positions,
            unit=unit,
            timeframe=timeframe,
        )
        for left_position, right_position in zip(positions, positions[1:]):
            previous = grouped.get((unit, timeframe), {}).get(left_position, {})
            current = grouped.get((unit, timeframe), {}).get(right_position, {})
            previous_keys = set(previous)
            current_keys = set(current)
            persistent = previous_keys & current_keys
            births = current_keys - previous_keys
            disappearances = previous_keys - current_keys
            shape_revisions = sum(
                previous[key].shape != current[key].shape for key in persistent
            )
            role_switches = sum(
                previous[key].role != current[key].role for key in persistent
            )
            transition = TrendlineStructuralTransition(
                observation_unit=unit,
                timeframe=timeframe,
                left_position=left_position,
                right_position=right_position,
                position_gap_bars=right_position - left_position,
                previous_active_count=len(previous),
                current_active_count=len(current),
                persistent_anchor_count=len(persistent),
                birth_count=len(births),
                disappearance_count=len(disappearances),
                shape_revision_count=shape_revisions,
                role_switch_count=role_switches,
                anchor_persistence_rate=_rate(len(persistent), len(previous)),
                birth_rate=_rate(len(births), len(current)),
                disappearance_rate=_rate(len(disappearances), len(previous)),
                revision_churn_rate=_rate(shape_revisions, len(persistent)),
                left_state_ids=tuple(sorted(previous[key].state_id for key in previous)),
                right_state_ids=tuple(sorted(current[key].state_id for key in current)),
            )
            result.append(transition)
    return tuple(result)


def measure_structural_drift(
    states: Iterable[TrendlineStructuralState],
    *,
    eligible_positions: Mapping[str, Sequence[int]] | Mapping[Any, Sequence[int]] | None = None,
) -> tuple[TrendlineStructuralDrift, ...]:
    """Report exact descriptive deltas for every persistent anchor."""

    values = tuple(states)
    if not all(isinstance(value, TrendlineStructuralState) for value in values):
        raise TrendlineStructuralStabilityError("states must contain typed rows")
    grouped = _group_states(values)
    result: list[TrendlineStructuralDrift] = []
    for unit, timeframe in sorted(grouped, key=lambda value: (value[1], _unit_order(value[0]))):
        positions = _ordered_scope_positions(
            grouped,
            eligible_positions=eligible_positions,
            unit=unit,
            timeframe=timeframe,
        )
        for left_position, right_position in zip(positions, positions[1:]):
            previous = grouped.get((unit, timeframe), {}).get(left_position, {})
            current = grouped.get((unit, timeframe), {}).get(right_position, {})
            for anchor_key in sorted(set(previous) & set(current), key=str):
                left = previous[anchor_key]
                right = current[anchor_key]
                if unit is TrendlineObservationUnit.FITTED_LINE:
                    start_value_delta = right.shape[0] - left.shape[0]
                    end_value_delta = right.shape[1] - left.shape[1]
                    start_price_delta = end_price_delta = None
                    score_delta = right.quality[1] - left.quality[1]
                    quality_delta = r_squared_delta = None
                else:
                    start_value_delta = end_value_delta = None
                    start_price_delta = right.shape[0] - left.shape[0]
                    end_price_delta = right.shape[1] - left.shape[1]
                    score_delta = None
                    quality_delta = right.quality[1] - left.quality[1]
                    r_squared_delta = right.quality[2] - left.quality[2]
                result.append(
                    TrendlineStructuralDrift(
                        observation_unit=unit,
                        timeframe=timeframe,
                        left_position=left_position,
                        right_position=right_position,
                        anchor_key=anchor_key,
                        role_before=left.role,
                        role_after=right.role,
                        slope_delta=right.shape[2] - left.shape[2],
                        intercept_delta=right.shape[3] - left.shape[3],
                        start_value_delta=start_value_delta,
                        end_value_delta=end_value_delta,
                        start_price_delta=start_price_delta,
                        end_price_delta=end_price_delta,
                        touch_count_delta=right.quality[0] - left.quality[0],
                        score_delta=score_delta,
                        quality_delta=quality_delta,
                        r_squared_delta=r_squared_delta,
                        left_state_id=left.state_id,
                        right_state_id=right.state_id,
                    )
                )
    return tuple(
        sorted(
            result,
            key=lambda value: (
                value.timeframe,
                _unit_order(value.observation_unit),
                value.left_position,
                str(value.anchor_key),
            ),
        )
    )


def build_structural_episodes(
    states: Iterable[TrendlineStructuralState],
    *,
    eligible_positions: Mapping[str, Sequence[int]] | Mapping[Any, Sequence[int]] | None = None,
) -> tuple[TrendlineStructuralEpisode, ...]:
    """Build consecutive-presence episodes without joining reappearances."""

    values = tuple(states)
    if not all(isinstance(value, TrendlineStructuralState) for value in values):
        raise TrendlineStructuralStabilityError("states must contain typed rows")
    grouped = _group_states(values)
    result: list[TrendlineStructuralEpisode] = []
    for unit, timeframe in sorted(grouped, key=lambda value: (value[1], _unit_order(value[0]))):
        positions = _ordered_scope_positions(
            grouped,
            eligible_positions=eligible_positions,
            unit=unit,
            timeframe=timeframe,
        )
        rank = {position: index for index, position in enumerate(positions)}
        by_anchor: dict[tuple[Any, ...], list[TrendlineStructuralState]] = defaultdict(list)
        for position in positions:
            for state in grouped[(unit, timeframe)].get(position, {}).values():
                by_anchor[state.anchor_key].append(state)
        for anchor_key in sorted(by_anchor, key=str):
            appearances = by_anchor[anchor_key]
            episodes: list[list[TrendlineStructuralState]] = []
            current_episode: list[TrendlineStructuralState] = []
            previous_rank: int | None = None
            for state in appearances:
                current_rank = rank.get(state.position)
                if current_rank is None:
                    raise TrendlineStructuralStabilityError(
                        "state position is absent from eligible scope"
                    )
                if previous_rank is None or current_rank == previous_rank + 1:
                    current_episode.append(state)
                else:
                    episodes.append(current_episode)
                    current_episode = [state]
                previous_rank = current_rank
            if current_episode:
                episodes.append(current_episode)
            for ordinal, episode_states in enumerate(episodes):
                first = episode_states[0]
                last = episode_states[-1]
                role_switches = sum(
                    left.role != right.role
                    for left, right in zip(episode_states, episode_states[1:])
                )
                revisions = sum(
                    left.shape != right.shape
                    for left, right in zip(episode_states, episode_states[1:])
                )
                result.append(
                    TrendlineStructuralEpisode(
                        observation_unit=unit,
                        timeframe=timeframe,
                        anchor_key=anchor_key,
                        episode_ordinal=ordinal,
                        first_position=first.position,
                        last_position=last.position,
                        observed_position_count=len(episode_states),
                        position_span_bars=last.position - first.position,
                        initial_role=first.role,
                        final_role=last.role,
                        role_switch_count=role_switches,
                        shape_revision_count=revisions,
                        left_censored=first.position == positions[0],
                        right_censored=last.position == positions[-1],
                        observed_positions=tuple(state.position for state in episode_states),
                    )
                )
    return tuple(
        sorted(
            result,
            key=lambda value: (
                value.timeframe,
                value.observation_unit.value,
                str(value.anchor_key),
                value.episode_ordinal,
            ),
        )
    )


def measure_structural_survival(
    episodes: Iterable[TrendlineStructuralEpisode],
    eligible_positions: Mapping[str, Sequence[int]] | Mapping[Any, Sequence[int]],
    stability_spec: TrendlineStructuralStabilitySpec,
) -> tuple[TrendlineStructuralSurvival, ...]:
    """Measure exact recorded-target survival for each explicit horizon."""

    if not isinstance(stability_spec, TrendlineStructuralStabilitySpec):
        raise TrendlineStructuralStabilityError("stability_spec must be typed")
    values = tuple(episodes)
    if not all(isinstance(value, TrendlineStructuralEpisode) for value in values):
        raise TrendlineStructuralStabilityError("episodes must contain typed rows")
    grouped: dict[tuple[TrendlineObservationUnit, str], list[TrendlineStructuralEpisode]] = defaultdict(list)
    for episode in values:
        grouped[(episode.observation_unit, episode.timeframe)].append(episode)
    scoped_keys = set(grouped)
    for key in eligible_positions:
        if isinstance(key, str):
            scoped_keys.update(
                (unit, key) for unit in TrendlineObservationUnit
            )
        else:
            unit = key[0]
            if not isinstance(unit, TrendlineObservationUnit):
                unit = TrendlineObservationUnit(str(unit))
            scoped_keys.add((unit, key[1]))
    result: list[TrendlineStructuralSurvival] = []
    for unit, timeframe in sorted(
        scoped_keys, key=lambda value: (value[1], _unit_order(value[0]))
    ):
        positions = _tuple_scope(
            eligible_positions,
            timeframe=timeframe,
            observation_unit=unit,
        )
        if not positions:
            raise TrendlineStructuralStabilityError(
                f"eligible positions are required for survival: {timeframe}"
            )
        position_set = set(positions)
        final_position = positions[-1]
        unit_episodes = grouped.get((unit, timeframe), ())
        births = [episode for episode in unit_episodes if not episode.left_censored]
        for horizon in stability_spec.survival_horizons_bars:
            eligible_target = survived = failed = right_censored = unavailable = 0
            for episode in births:
                target = episode.first_position + horizon
                if target > final_position:
                    right_censored += 1
                elif target not in position_set:
                    unavailable += 1
                else:
                    eligible_target += 1
                    if target in episode.observed_positions:
                        survived += 1
                    else:
                        failed += 1
            result.append(
                TrendlineStructuralSurvival(
                    observation_unit=unit,
                    timeframe=timeframe,
                    horizon_bars=horizon,
                    observed_birth_count=len(births),
                    eligible_target_count=eligible_target,
                    survived_count=survived,
                    failed_count=failed,
                    right_censored_count=right_censored,
                    target_unavailable_count=unavailable,
                    survival_rate=_rate(survived, eligible_target),
                )
            )
    return tuple(result)


def _summary_for(
    unit: TrendlineObservationUnit,
    timeframe: str,
    states: tuple[TrendlineStructuralState, ...],
    transitions: tuple[TrendlineStructuralTransition, ...],
    episodes: tuple[TrendlineStructuralEpisode, ...],
    survival: tuple[TrendlineStructuralSurvival, ...],
    eligible_positions: Mapping[str, Sequence[int]] | Mapping[Any, Sequence[int]],
) -> TrendlineStructuralSummary:
    positions = _tuple_scope(
        eligible_positions,
        timeframe=timeframe,
        observation_unit=unit,
    ) or ()
    grouped = {position: 0 for position in positions}
    for state in states:
        if state.observation_unit is unit and state.timeframe == timeframe:
            grouped[state.position] = grouped.get(state.position, 0) + 1
    active_counts = tuple(grouped[position] for position in positions)
    transitions = tuple(
        value
        for value in transitions
        if value.observation_unit is unit and value.timeframe == timeframe
    )
    episodes = tuple(
        value
        for value in episodes
        if value.observation_unit is unit and value.timeframe == timeframe
    )
    survival = tuple(
        value
        for value in survival
        if value.observation_unit is unit and value.timeframe == timeframe
    )
    previous_denominator = sum(value.previous_active_count for value in transitions)
    current_denominator = sum(value.current_active_count for value in transitions)
    persistent_denominator = sum(value.persistent_anchor_count for value in transitions)
    return TrendlineStructuralSummary(
        observation_unit=unit,
        timeframe=timeframe,
        eligible_point_count=len(positions),
        transition_count=len(transitions),
        mean_active_anchor_count=(sum(active_counts) / len(active_counts) if active_counts else None),
        minimum_active_anchor_count=min(active_counts) if active_counts else None,
        maximum_active_anchor_count=max(active_counts) if active_counts else None,
        total_birth_count=sum(value.birth_count for value in transitions),
        total_disappearance_count=sum(value.disappearance_count for value in transitions),
        total_persistent_anchor_count=persistent_denominator,
        total_shape_revision_count=sum(value.shape_revision_count for value in transitions),
        total_role_switch_count=sum(value.role_switch_count for value in transitions),
        anchor_persistence_rate=_rate(persistent_denominator, previous_denominator),
        birth_rate=_rate(sum(value.birth_count for value in transitions), current_denominator),
        disappearance_rate=_rate(
            sum(value.disappearance_count for value in transitions),
            previous_denominator,
        ),
        revision_churn_rate=_rate(
            sum(value.shape_revision_count for value in transitions),
            persistent_denominator,
        ),
        episode_count=len(episodes),
        observed_birth_episode_count=sum(not value.left_censored for value in episodes),
        survival=tuple(sorted(survival, key=lambda value: value.horizon_bars)),
    )


def _ordered_row_dicts(
    rows: Iterable[Any],
    *,
    key: Any,
) -> tuple[dict[str, Any], ...]:
    return tuple(row.to_dict() for row in sorted(rows, key=key))


def validate_structural_stability_bundle(
    bundle: TrendlineStructuralStabilityBundle,
) -> None:
    """Recompute content identity and row identities at a public boundary."""

    if not isinstance(bundle, TrendlineStructuralStabilityBundle):
        raise TrendlineStructuralStabilityError("bundle must be typed")
    for row in (
        *bundle.state_rows,
        *bundle.transition_rows,
        *bundle.drift_rows,
        *bundle.episode_rows,
        *bundle.survival_rows,
        *bundle.summaries,
    ):
        if isinstance(row, TrendlineStructuralState):
            expected = canonical_hash(
                _state_payload(row),
                semantics_version=STRUCTURAL_STATE_SEMANTICS_VERSION,
            )
            if row.state_id != expected:
                raise TrendlineStructuralStabilityError(
                    "state_id does not match state content"
                )
        elif isinstance(row, TrendlineStructuralTransition):
            expected = canonical_hash(
                _transition_payload(row),
                semantics_version=STRUCTURAL_TRANSITION_SEMANTICS_VERSION,
            )
            if row.transition_id != expected:
                raise TrendlineStructuralStabilityError(
                    "transition_id does not match transition content"
                    )
        elif isinstance(row, TrendlineStructuralDrift):
            expected = canonical_hash(
                _drift_payload(row),
                semantics_version=STRUCTURAL_DRIFT_SEMANTICS_VERSION,
            )
            if row.drift_id != expected:
                raise TrendlineStructuralStabilityError(
                    "drift_id does not match drift content"
                )
        elif isinstance(row, TrendlineStructuralEpisode):
            expected = canonical_hash(
                _episode_payload(row),
                semantics_version=STRUCTURAL_EPISODE_SEMANTICS_VERSION,
            )
            if row.episode_id != expected:
                raise TrendlineStructuralStabilityError(
                    "episode_id does not match episode content"
                )
        elif isinstance(row, TrendlineStructuralSurvival):
            expected = canonical_hash(
                _survival_payload(row),
                semantics_version=STRUCTURAL_SURVIVAL_SEMANTICS_VERSION,
            )
            if row.survival_id != expected:
                raise TrendlineStructuralStabilityError(
                    "survival_id does not match survival content"
                )
        elif isinstance(row, TrendlineStructuralSummary):
            expected = canonical_hash(
                _summary_payload(row),
                semantics_version=STRUCTURAL_SUMMARY_SEMANTICS_VERSION,
            )
            if row.summary_id != expected:
                raise TrendlineStructuralStabilityError(
                    "summary_id does not match summary content"
                )
        else:  # pragma: no cover - guarded by bundle constructor
            raise TrendlineStructuralStabilityError("unknown structural bundle row")

    eligible_positions = dict(bundle.eligible_positions)
    expected_transitions = measure_structural_transitions(
        bundle.state_rows,
        eligible_positions=eligible_positions,
    )
    if _ordered_row_dicts(
        expected_transitions,
        key=lambda row: (
            row.timeframe,
            _unit_order(row.observation_unit),
            row.left_position,
        ),
    ) != _ordered_row_dicts(
        bundle.transition_rows,
        key=lambda row: (
            row.timeframe,
            _unit_order(row.observation_unit),
            row.left_position,
        ),
    ):
        raise TrendlineStructuralStabilityError(
            "transition rows do not match structural state transitions"
        )

    expected_drift = measure_structural_drift(
        bundle.state_rows,
        eligible_positions=eligible_positions,
    )
    if _ordered_row_dicts(
        expected_drift,
        key=lambda row: (
            row.timeframe,
            _unit_order(row.observation_unit),
            row.left_position,
            str(row.anchor_key),
        ),
    ) != _ordered_row_dicts(
        bundle.drift_rows,
        key=lambda row: (
            row.timeframe,
            _unit_order(row.observation_unit),
            row.left_position,
            str(row.anchor_key),
        ),
    ):
        raise TrendlineStructuralStabilityError(
            "drift rows do not match persistent structural states"
        )

    expected_episodes = build_structural_episodes(
        bundle.state_rows,
        eligible_positions=eligible_positions,
    )
    if _ordered_row_dicts(
        expected_episodes,
        key=lambda row: (
            row.timeframe,
            row.observation_unit.value,
            str(row.anchor_key),
            row.episode_ordinal,
        ),
    ) != _ordered_row_dicts(
        bundle.episode_rows,
        key=lambda row: (
            row.timeframe,
            row.observation_unit.value,
            str(row.anchor_key),
            row.episode_ordinal,
        ),
    ):
        raise TrendlineStructuralStabilityError(
            "episode rows do not match structural state presence"
        )

    summaries_by_coordinate: dict[
        tuple[TrendlineObservationUnit, str], TrendlineStructuralSummary
    ] = {}
    for summary in bundle.summaries:
        coordinate = (summary.observation_unit, summary.timeframe)
        if coordinate in summaries_by_coordinate:
            raise TrendlineStructuralStabilityError(
                "duplicate structural summary coordinate"
            )
        summaries_by_coordinate[coordinate] = summary
    for survival in bundle.survival_rows:
        if (survival.observation_unit, survival.timeframe) not in summaries_by_coordinate:
            raise TrendlineStructuralStabilityError(
                "survival row has no matching structural summary"
            )

    expected_summaries = tuple(
        _summary_for(
            unit,
            timeframe,
            bundle.state_rows,
            bundle.transition_rows,
            bundle.episode_rows,
            bundle.survival_rows,
            eligible_positions,
        )
        for timeframe, _ in bundle.eligible_positions
        for unit in (
            TrendlineObservationUnit.FITTED_LINE,
            TrendlineObservationUnit.BOUNDARY_RAY,
        )
    )
    expected_summary_coordinates = {
        (summary.observation_unit, summary.timeframe)
        for summary in expected_summaries
    }
    if set(summaries_by_coordinate) != expected_summary_coordinates:
        raise TrendlineStructuralStabilityError(
            "structural summaries do not cover eligible unit/timeframe coordinates"
        )
    for expected in expected_summaries:
        actual = summaries_by_coordinate[(expected.observation_unit, expected.timeframe)]
        if actual.to_dict() != expected.to_dict():
            raise TrendlineStructuralStabilityError(
                "structural summary does not match derived bundle content"
            )

    if bundle.computed_bundle_id() != bundle.structural_stability_bundle_id:
        raise TrendlineStructuralStabilityError(
            "structural stability bundle identity does not match content"
        )


def build_structural_stability_bundle(
    cohort: TrendlineAdequacyCohort,
    study_config: TrendlineAdequacyStudyConfig,
    observations: Iterable[TrendlineAdequacyObservation],
    replay: PreparedTrendlineResearchReplay,
    stability_spec: TrendlineStructuralStabilitySpec,
) -> TrendlineStructuralStabilityBundle:
    """Build all D2 measurements from one validated replay without execution."""

    if not isinstance(replay, PreparedTrendlineResearchReplay):
        raise TrendlineStructuralStabilityError("replay must be typed")
    if not isinstance(study_config, TrendlineAdequacyStudyConfig):
        raise TrendlineStructuralStabilityError("study_config must be typed")
    study_config.validate_for(replay.prepared, replay)
    expected_cohort = build_adequacy_cohort(replay.prepared, replay, study_config)
    if cohort.cohort_id != expected_cohort.cohort_id:
        raise TrendlineStructuralStabilityError(
            "cohort does not match replay and study configuration"
        )

    points = validated_replay_points(replay)
    for point in points:
        validate_replay_point_integrity(point)
    expected_observations = collect_adequacy_observations(
        cohort,
        replay.prepared,
        replay,
        study_config,
    )
    supplied_observations = tuple(observations)
    if tuple(value.to_dict() for value in supplied_observations) != tuple(
        value.to_dict() for value in expected_observations
    ):
        raise TrendlineStructuralStabilityError(
            "supplied adequacy observations differ from canonical collection"
        )
    line_rows = replay_line_rows(replay)
    ray_rows = replay_ray_rows(replay)
    states = build_structural_states(
        cohort,
        expected_observations,
        line_rows,
        ray_rows,
        stability_spec,
    )
    eligible_positions = tuple(
        (
            timeframe,
            tuple(
                observation.position
                for observation in expected_observations
                if observation.timeframe == timeframe and observation.eligible
            ),
        )
        for timeframe in cohort.timeframes
    )
    transitions = measure_structural_transitions(
        states,
        eligible_positions=dict(eligible_positions),
    )
    drift_rows = measure_structural_drift(
        states,
        eligible_positions=dict(eligible_positions),
    )
    episodes = build_structural_episodes(
        states,
        eligible_positions=dict(eligible_positions),
    )
    survival = measure_structural_survival(
        episodes,
        dict(eligible_positions),
        stability_spec,
    )
    summaries = tuple(
        _summary_for(
            unit,
            timeframe,
            states,
            transitions,
            episodes,
            survival,
            dict(eligible_positions),
        )
        for timeframe in cohort.timeframes
        for unit in (
            TrendlineObservationUnit.FITTED_LINE,
            TrendlineObservationUnit.BOUNDARY_RAY,
        )
    )
    eligible_identities = tuple(
        (
            observation.timeframe,
            observation.position,
            observation.replay_point_id,
            observation.content_id,
            observation.source_id,
            observation.checkpoint_id,
            observation.state.value,
        )
        for observation in expected_observations
        if observation.eligible
    )
    bundle = TrendlineStructuralStabilityBundle(
        structural_stability_bundle_id="",
        cohort_id=cohort.cohort_id,
        study_config_id=study_config.study_config_id,
        stability_spec_id=stability_spec.stability_spec_id,
        eligible_observation_identities=eligible_identities,
        eligible_positions=eligible_positions,
        state_rows=tuple(
            sorted(
                states,
                key=lambda value: (
                    cohort.timeframes.index(value.timeframe),
                    value.position,
                    _unit_order(value.observation_unit),
                    str(value.anchor_key),
                ),
            )
        ),
        transition_rows=tuple(
            sorted(
                transitions,
                key=lambda value: (
                    cohort.timeframes.index(value.timeframe),
                    _unit_order(value.observation_unit),
                    value.left_position,
                ),
            )
        ),
        drift_rows=tuple(
            sorted(
                drift_rows,
                key=lambda value: (
                    cohort.timeframes.index(value.timeframe),
                    _unit_order(value.observation_unit),
                    value.left_position,
                    str(value.anchor_key),
                ),
            )
        ),
        episode_rows=tuple(episodes),
        survival_rows=tuple(
            sorted(
                survival,
                key=lambda value: (
                    cohort.timeframes.index(value.timeframe),
                    _unit_order(value.observation_unit),
                    value.horizon_bars,
                ),
            )
        ),
        summaries=summaries,
    )
    validate_structural_stability_bundle(bundle)
    return bundle


# Descriptive aliases make row-oriented notebook consumers explicit.
TrendlineStructuralStateRow = TrendlineStructuralState
TrendlineStructuralTransitionRow = TrendlineStructuralTransition
TrendlineStructuralEpisodeRow = TrendlineStructuralEpisode
TrendlineStructuralSurvivalRow = TrendlineStructuralSurvival


__all__ = [
    "STRUCTURAL_EPISODE_SEMANTICS_VERSION",
    "STRUCTURAL_DRIFT_SEMANTICS_VERSION",
    "STRUCTURAL_STATE_SEMANTICS_VERSION",
    "STRUCTURAL_STABILITY_BUNDLE_SEMANTICS_VERSION",
    "STRUCTURAL_STABILITY_SPEC_SEMANTICS_VERSION",
    "STRUCTURAL_SUMMARY_SEMANTICS_VERSION",
    "STRUCTURAL_SURVIVAL_SEMANTICS_VERSION",
    "STRUCTURAL_TRANSITION_SEMANTICS_VERSION",
    "TrendlineStructuralEpisode",
    "TrendlineStructuralEpisodeRow",
    "TrendlineStructuralDrift",
    "TrendlineStructuralState",
    "TrendlineStructuralStateRow",
    "TrendlineStructuralStabilityBundle",
    "TrendlineStructuralStabilityError",
    "TrendlineStructuralStabilitySpec",
    "TrendlineStructuralSummary",
    "TrendlineStructuralSurvival",
    "TrendlineStructuralSurvivalRow",
    "TrendlineStructuralTransition",
    "TrendlineStructuralTransitionRow",
    "build_structural_episodes",
    "build_structural_states",
    "build_structural_stability_bundle",
    "measure_structural_survival",
    "measure_structural_drift",
    "measure_structural_transitions",
    "validate_structural_stability_bundle",
]
