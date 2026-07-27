"""Seeded stochastic-null comparisons for mature trendline adequacy research."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from math import ceil, floor, isfinite
from numbers import Real
import random
from statistics import fmean, median
from typing import Any

import pandas as pd

from libs.models.trendlines.contracts.identity import canonical_hash
from libs.models.trendlines.workflows.research.contracts import (
    PreparedTrendlineResearchRun,
)
from libs.models.trendlines.workflows.research.diagnostics import (
    ReplayPivotRow,
    inspect_replay_pivots,
)
from libs.models.trendlines.workflows.research.replay import (
    PreparedTrendlineResearchReplay,
    validate_replay_point_integrity,
)

from .baselines import (
    TrendlineAdequacyBaselineKind,
    TrendlineAdequacyBaselineSpec,
)
from .baseline_comparison import (
    COMPARISON_DELTA_FIELDS,
    CONFIRMED_PIVOT_FINALITY,
    TrendlineBaselineComparisonError,
    TrendlineDeterministicBaselineComparisonBundle,
    _validate_pivot_row,
    validate_baseline_comparison_bundle,
)
from .contracts import TrendlineAdequacyStudyConfig
from .interaction import (
    INTERACTION_ROLES,
    TrendlineInteractionEvent,
    TrendlineInteractionOutcome,
    TrendlineInteractionSummary,
    TrendlineInteractionUtilityBundle,
    TrendlineInteractionUtilitySpec,
    build_interaction_summaries,
    measure_frozen_geometry_outcomes,
    validate_interaction_utility_bundle,
)
from .stability import (
    TrendlineStructuralStabilityBundle,
    validate_structural_stability_bundle,
)


STOCHASTIC_DRAW_SEMANTICS_VERSION = (
    "trendlines.adequacy-stochastic-null-draw.v1"
)
STOCHASTIC_SELECTION_SEMANTICS_VERSION = (
    "trendlines.adequacy-stochastic-null-selection.v1"
)
STOCHASTIC_REPETITION_COMPARISON_SEMANTICS_VERSION = (
    "trendlines.adequacy-stochastic-null-repetition-comparison.v1"
)
STOCHASTIC_DISTRIBUTION_SUMMARY_SEMANTICS_VERSION = (
    "trendlines.adequacy-stochastic-null-distribution-summary.v1"
)
STOCHASTIC_NULL_BUNDLE_SEMANTICS_VERSION = (
    "trendlines.adequacy-stochastic-null-comparison-bundle.v1"
)
STOCHASTIC_NULL_KINDS = (
    TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR,
    TrendlineAdequacyBaselineKind.DENSITY_MATCHED_NULL,
)
STOCHASTIC_SELECTION_REASONS = (
    "available",
    "no_valid_same_role_pivot_pair",
    "no_prior_same_role_donor",
)
STOCHASTIC_DISTRIBUTION_METRICS = tuple(COMPARISON_DELTA_FIELDS)
STOCHASTIC_QUANTILE_PROBABILITIES = (0.05, 0.95)


class TrendlineStochasticNullComparisonError(ValueError):
    """Raised when stochastic-null evidence is invalid or non-causal."""


def _identity(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrendlineStochasticNullComparisonError(f"{name} must be non-empty")
    return value


def _sha256(value: Any, *, name: str) -> str:
    result = _identity(value, name=name)
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        raise TrendlineStochasticNullComparisonError(
            f"{name} must be a lowercase SHA-256 identity"
        )
    return result


def _strict_int(value: Any, *, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise TrendlineStochasticNullComparisonError(
            f"{name} must be a non-boolean integer >= {minimum}"
        )
    return value


def _finite(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TrendlineStochasticNullComparisonError(f"{name} must be finite numeric")
    result = float(value)
    if not isfinite(result):
        raise TrendlineStochasticNullComparisonError(f"{name} must be finite numeric")
    return result


def _timestamp(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrendlineStochasticNullComparisonError(f"{name} must be non-empty text")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise TrendlineStochasticNullComparisonError(
            f"{name} must be ISO timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TrendlineStochasticNullComparisonError(
            f"{name} must be timezone-aware"
        )
    return value


def _timestamp_value(value: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise TrendlineStochasticNullComparisonError(
            "timestamp must be timezone-aware"
        )
    return timestamp.tz_convert("UTC")


def _optional_delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return float(left - right)


def _approved_stochastic_specs(
    specs: Sequence[TrendlineAdequacyBaselineSpec],
) -> tuple[TrendlineAdequacyBaselineSpec, ...]:
    result = tuple(specs)
    if tuple(spec.kind for spec in result) != STOCHASTIC_NULL_KINDS:
        raise TrendlineStochasticNullComparisonError(
            "D4B requires exactly random-pair and density-matched baseline kinds"
        )
    expected_names = (
        "random-valid-pivot-pair-v1",
        "causal-density-matched-null-v1",
    )
    expected_preserves = (
        ("timeframe", "position", "role", "pivot_count", "causal_prefix"),
        (
            "timeframe",
            "position",
            "role",
            "ray_count",
            "observation_density",
            "causal_prefix",
        ),
    )
    for index, spec in enumerate(result):
        if spec.name != expected_names[index]:
            raise TrendlineStochasticNullComparisonError(
                "D4B stochastic baseline name is not approved"
            )
        if spec.repetitions < 1:
            raise TrendlineStochasticNullComparisonError(
                "D4B repetitions must be positive"
            )
        if spec.seed is None or isinstance(spec.seed, bool) or not isinstance(spec.seed, int):
            raise TrendlineStochasticNullComparisonError(
                "D4B stochastic baseline seed must be explicit integer"
            )
        if spec.preserves != expected_preserves[index]:
            raise TrendlineStochasticNullComparisonError(
                "D4B stochastic baseline preservation fields differ"
            )
    return result


def _quantiles(value: Sequence[float]) -> tuple[float, float]:
    probabilities = STOCHASTIC_QUANTILE_PROBABILITIES
    if not value:
        raise TrendlineStochasticNullComparisonError(
            "quantiles require at least one defined value"
        )
    ordered = tuple(sorted(float(item) for item in value))
    result: list[float] = []
    for probability in probabilities:
        height = (len(ordered) - 1) * probability
        lower = floor(height)
        upper = ceil(height)
        result.append(
            ordered[lower]
            + (height - lower) * (ordered[upper] - ordered[lower])
        )
    return result[0], result[1]


def derive_stochastic_draw_id(
    baseline_id: str,
    baseline_seed: int,
    repetition_index: int,
    model_event_id: str,
) -> str:
    """Derive one process-independent draw identity."""

    _sha256(baseline_id, name="draw baseline_id")
    _strict_int(baseline_seed, name="draw baseline_seed")
    _strict_int(repetition_index, name="draw repetition_index")
    _sha256(model_event_id, name="draw model_event_id")
    return canonical_hash(
        {
            "baseline_id": baseline_id,
            "baseline_seed": baseline_seed,
            "repetition_index": repetition_index,
            "model_event_id": model_event_id,
            "semantics_version": STOCHASTIC_DRAW_SEMANTICS_VERSION,
        },
        semantics_version=STOCHASTIC_DRAW_SEMANTICS_VERSION,
    )


def _draw_index(draw_id: str, candidate_count: int) -> int:
    _sha256(draw_id, name="draw_id")
    count = _strict_int(candidate_count, name="candidate_count", minimum=1)
    draw_seed = int(draw_id[:16], 16)
    return random.Random(draw_seed).randrange(count)


def _canonical_events(
    events: Sequence[TrendlineInteractionEvent],
) -> tuple[TrendlineInteractionEvent, ...]:
    if not all(isinstance(event, TrendlineInteractionEvent) for event in events):
        raise TrendlineStochasticNullComparisonError("D3 events must be typed")
    return tuple(
        sorted(
            events,
            key=lambda event: (
                event.timeframe,
                event.selection_position,
                event.event_id,
            ),
        )
    )


def _timeframes(events: Sequence[TrendlineInteractionEvent]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(event.timeframe for event in _canonical_events(events)))


def _event_point(
    event: TrendlineInteractionEvent,
    replay: PreparedTrendlineResearchReplay,
) -> Any:
    try:
        point = replay.output_at(event.timeframe, event.selection_position)
        validate_replay_point_integrity(point)
    except Exception as exc:
        raise TrendlineStochasticNullComparisonError(
            "stochastic event replay point failed canonical integrity"
        ) from exc
    boundary_identity = point.boundary_identity
    expected = (
        event.replay_point_id,
        point.replay_point_id,
        event.content_id,
        point.content_id,
        event.source_id,
        point.prefix_source_ref.source_id,
        event.checkpoint_id,
        boundary_identity.checkpoint.checkpoint_id,
    )
    if any(left != right for left, right in zip(expected[::2], expected[1::2])):
        raise TrendlineStochasticNullComparisonError(
            "stochastic event does not bind replay point"
        )
    return point


def _selection_close(
    replay: PreparedTrendlineResearchReplay,
    event: TrendlineInteractionEvent,
) -> float:
    frame = replay.prepared.dataset.frames[event.timeframe]
    if event.selection_position >= len(frame):
        raise TrendlineStochasticNullComparisonError(
            "event selection position exceeds prepared frame"
        )
    return _finite(frame.iloc[event.selection_position]["close"], name="selection close")


def _validated_pivots(
    prepared: PreparedTrendlineResearchRun,
    replay: PreparedTrendlineResearchReplay,
    event: TrendlineInteractionEvent,
    point: Any,
) -> tuple[ReplayPivotRow, ...]:
    try:
        pivots = inspect_replay_pivots(
            prepared,
            replay,
            timeframe=event.timeframe,
            position=event.selection_position,
        )
        for pivot in pivots:
            _validate_pivot_row(pivot, event, point)
            if pivot.extractor_finality != CONFIRMED_PIVOT_FINALITY:
                raise TrendlineStochasticNullComparisonError(
                    "stochastic pivot must be confirmed append-only"
                )
    except TrendlineBaselineComparisonError as exc:
        raise TrendlineStochasticNullComparisonError(
            "stochastic pivot failed causal selection validation"
        ) from exc
    return tuple(pivots)


def _role_pivot_pairs(
    pivots: Sequence[ReplayPivotRow],
    event: TrendlineInteractionEvent,
    selection_close: float,
) -> tuple[tuple[int, int, float, float], ...]:
    expected_role = "low" if event.role == "support" else "high"
    role_pivots = tuple(
        sorted(
            (pivot for pivot in pivots if pivot.pivot_role == expected_role),
            key=lambda pivot: (pivot.bar_position, float(pivot.price)),
        )
    )
    candidates: list[tuple[int, int, float, float]] = []
    for left_index, left in enumerate(role_pivots):
        for right in role_pivots[left_index + 1 :]:
            x1 = left.bar_position
            x2 = right.bar_position
            if not x1 < x2 < event.selection_position:
                continue
            y1 = _finite(left.price, name="random pivot price")
            y2 = _finite(right.price, name="random pivot price")
            slope = (y2 - y1) / (x2 - x1)
            intercept = y2 - slope * x2
            level = slope * event.selection_position + intercept
            if event.role == "support" and level > selection_close:
                continue
            if event.role == "resistance" and level < selection_close:
                continue
            candidates.append((x1, x2, y1, y2))
    return tuple(sorted(candidates, key=lambda value: value))


def _density_donors(
    event: TrendlineInteractionEvent,
    events: Sequence[TrendlineInteractionEvent],
) -> tuple[TrendlineInteractionEvent, ...]:
    current_available = _timestamp_value(event.selection_available_at)
    donors = tuple(
        donor
        for donor in events
        if donor.timeframe == event.timeframe
        and donor.role == event.role
        and donor.event_id != event.event_id
        and donor.selection_position < event.selection_position
        and _timestamp_value(donor.selection_available_at) < current_available
    )
    return tuple(
        sorted(donors, key=lambda donor: (donor.selection_position, donor.event_id))
    )


def transport_density_matched_geometry(
    current_event: TrendlineInteractionEvent,
    donor_event: TrendlineInteractionEvent,
    *,
    current_selection_close: float,
    donor_selection_close: float,
) -> tuple[float, float, float, float, float, float, float]:
    """Transport donor geometry using current selection ATR and close."""

    if current_event.timeframe != donor_event.timeframe:
        raise TrendlineStochasticNullComparisonError(
            "density donor timeframe differs from current event"
        )
    if current_event.role != donor_event.role:
        raise TrendlineStochasticNullComparisonError(
            "density donor role differs from current event"
        )
    if not donor_event.selection_position < current_event.selection_position:
        raise TrendlineStochasticNullComparisonError(
            "density donor is not strictly prior"
        )
    if not _timestamp_value(donor_event.selection_available_at) < _timestamp_value(
        current_event.selection_available_at
    ):
        raise TrendlineStochasticNullComparisonError(
            "density donor availability is not strictly prior"
        )
    current_close = _finite(current_selection_close, name="current selection close")
    current_atr = _finite(current_event.selection_atr, name="current selection ATR")
    donor_atr = _finite(donor_event.selection_atr, name="donor selection ATR")
    if current_atr <= 0 or donor_atr <= 0:
        raise TrendlineStochasticNullComparisonError("density ATR must be positive")
    donor_slope = _finite(donor_event.frozen_slope, name="donor slope")
    donor_intercept = _finite(donor_event.frozen_intercept, name="donor intercept")
    donor_close = _finite(donor_selection_close, name="donor selection close")
    donor_level = (
        donor_slope * donor_event.selection_position + donor_intercept
    )
    normalised_slope = donor_slope / donor_atr
    if current_event.role == "support":
        normalised_distance = (donor_close - donor_level) / donor_atr
        current_level = current_close - normalised_distance * current_atr
    else:
        normalised_distance = (donor_level - donor_close) / donor_atr
        current_level = current_close + normalised_distance * current_atr
    null_slope = normalised_slope * current_atr
    null_intercept = current_level - null_slope * current_event.selection_position
    return (
        null_slope,
        null_intercept,
        normalised_slope,
        normalised_distance,
        donor_level,
        donor_close,
        current_level,
    )


def _transport_density_geometry(
    current_event: TrendlineInteractionEvent,
    donor_event: TrendlineInteractionEvent,
    *,
    current_selection_close: float,
    donor_selection_close: float,
) -> tuple[float, float, float, float, float, float, float]:
    return transport_density_matched_geometry(
        current_event,
        donor_event,
        current_selection_close=current_selection_close,
        donor_selection_close=donor_selection_close,
    )


def _selection_payload(
    selection: "TrendlineStochasticNullSelection",
) -> dict[str, Any]:
    return {
        "baseline_id": selection.baseline_id,
        "baseline_name": selection.baseline_name,
        "baseline_kind": selection.baseline_kind.value,
        "baseline_seed": selection.baseline_seed,
        "repetition_index": selection.repetition_index,
        "model_event_id": selection.model_event_id,
        "timeframe": selection.timeframe,
        "role": selection.role,
        "selection_position": selection.selection_position,
        "selection_event_at": selection.selection_event_at,
        "selection_available_at": selection.selection_available_at,
        "selection_close": selection.selection_close,
        "selection_atr": selection.selection_atr,
        "available": selection.available,
        "reason": selection.reason,
        "draw_id": selection.draw_id,
        "candidate_count": selection.candidate_count,
        "selected_candidate_index": selection.selected_candidate_index,
        "selected_pivot_positions": list(selection.selected_pivot_positions),
        "selected_pivot_prices": list(selection.selected_pivot_prices),
        "selected_pivot_finality": selection.selected_pivot_finality,
        "donor_event_id": selection.donor_event_id,
        "donor_selection_position": selection.donor_selection_position,
        "donor_selection_event_at": selection.donor_selection_event_at,
        "donor_selection_available_at": selection.donor_selection_available_at,
        "donor_selection_atr": selection.donor_selection_atr,
        "donor_selection_close": selection.donor_selection_close,
        "donor_frozen_slope": selection.donor_frozen_slope,
        "donor_frozen_intercept": selection.donor_frozen_intercept,
        "donor_level": selection.donor_level,
        "normalised_donor_slope": selection.normalised_donor_slope,
        "normalised_donor_distance": selection.normalised_donor_distance,
        "donor_replay_point_id": selection.donor_replay_point_id,
        "donor_content_id": selection.donor_content_id,
        "donor_source_id": selection.donor_source_id,
        "donor_checkpoint_id": selection.donor_checkpoint_id,
        "replay_point_id": selection.replay_point_id,
        "content_id": selection.content_id,
        "source_id": selection.source_id,
        "checkpoint_id": selection.checkpoint_id,
        "frozen_slope": selection.frozen_slope,
        "frozen_intercept": selection.frozen_intercept,
        "semantics_version": STOCHASTIC_SELECTION_SEMANTICS_VERSION,
    }


@dataclass(frozen=True)
class TrendlineStochasticNullSelection:
    """One seeded stochastic geometry attempt at one model event."""

    baseline_id: str
    baseline_name: str
    baseline_kind: TrendlineAdequacyBaselineKind
    baseline_seed: int
    repetition_index: int
    model_event_id: str
    timeframe: str
    role: str
    selection_position: int
    selection_event_at: str
    selection_available_at: str
    selection_close: float
    selection_atr: float
    available: bool
    reason: str
    draw_id: str
    candidate_count: int
    selected_candidate_index: int | None
    replay_point_id: str
    content_id: str
    source_id: str
    checkpoint_id: str
    frozen_slope: float | None
    frozen_intercept: float | None
    selected_pivot_positions: tuple[int, ...] = ()
    selected_pivot_prices: tuple[float, ...] = ()
    selected_pivot_finality: str | None = None
    donor_event_id: str | None = None
    donor_selection_position: int | None = None
    donor_selection_event_at: str | None = None
    donor_selection_available_at: str | None = None
    donor_selection_atr: float | None = None
    donor_selection_close: float | None = None
    donor_frozen_slope: float | None = None
    donor_frozen_intercept: float | None = None
    donor_level: float | None = None
    normalised_donor_slope: float | None = None
    normalised_donor_distance: float | None = None
    donor_replay_point_id: str | None = None
    donor_content_id: str | None = None
    donor_source_id: str | None = None
    donor_checkpoint_id: str | None = None
    selection_id: str = ""

    def __post_init__(self) -> None:
        _sha256(self.baseline_id, name="stochastic selection baseline_id")
        _identity(self.baseline_name, name="stochastic selection baseline_name")
        if self.baseline_kind not in STOCHASTIC_NULL_KINDS:
            raise TrendlineStochasticNullComparisonError(
                "stochastic selection kind is not authorised"
            )
        _strict_int(self.baseline_seed, name="stochastic selection seed")
        _strict_int(self.repetition_index, name="stochastic repetition", minimum=0)
        _sha256(self.model_event_id, name="stochastic model_event_id")
        _identity(self.timeframe, name="stochastic timeframe")
        if self.role not in INTERACTION_ROLES:
            raise TrendlineStochasticNullComparisonError(
                "stochastic selection role is invalid"
            )
        _strict_int(self.selection_position, name="stochastic selection position")
        _timestamp(self.selection_event_at, name="stochastic selection event_at")
        _timestamp(
            self.selection_available_at,
            name="stochastic selection available_at",
        )
        _finite(self.selection_close, name="stochastic selection close")
        selection_atr = _finite(self.selection_atr, name="stochastic selection ATR")
        if selection_atr <= 0:
            raise TrendlineStochasticNullComparisonError(
                "stochastic selection ATR must be positive"
            )
        if not isinstance(self.available, bool):
            raise TrendlineStochasticNullComparisonError(
                "stochastic selection available must be bool"
            )
        if self.reason not in STOCHASTIC_SELECTION_REASONS:
            raise TrendlineStochasticNullComparisonError(
                "stochastic selection reason is invalid"
            )
        _sha256(self.draw_id, name="stochastic draw_id")
        candidate_count = _strict_int(
            self.candidate_count,
            name="stochastic candidate_count",
        )
        if self.selected_candidate_index is not None:
            selected_index = _strict_int(
                self.selected_candidate_index,
                name="stochastic selected_candidate_index",
            )
            if selected_index >= candidate_count:
                raise TrendlineStochasticNullComparisonError(
                    "selected candidate index exceeds candidate count"
                )
        elif self.available:
            raise TrendlineStochasticNullComparisonError(
                "available stochastic selection requires candidate index"
            )
        if self.available and candidate_count < 1:
            raise TrendlineStochasticNullComparisonError(
                "available stochastic selection requires candidates"
            )
        if not self.available and self.selected_candidate_index is not None:
            raise TrendlineStochasticNullComparisonError(
                "abstention cannot retain selected candidate"
            )
        if self.available and self.reason != "available":
            raise TrendlineStochasticNullComparisonError(
                "available stochastic selection reason is invalid"
            )
        if not self.available and self.frozen_slope is not None:
            raise TrendlineStochasticNullComparisonError(
                "abstention cannot retain frozen slope"
            )
        if not self.available and self.frozen_intercept is not None:
            raise TrendlineStochasticNullComparisonError(
                "abstention cannot retain frozen intercept"
            )
        positions = tuple(
            _strict_int(value, name="stochastic pivot position")
            for value in self.selected_pivot_positions
        )
        prices = tuple(
            _finite(value, name="stochastic pivot price")
            for value in self.selected_pivot_prices
        )
        if len(positions) != len(prices):
            raise TrendlineStochasticNullComparisonError(
                "stochastic pivot positions/prices length differs"
            )
        if tuple(sorted(set(positions))) != positions:
            raise TrendlineStochasticNullComparisonError(
                "stochastic pivot positions must be ordered and unique"
            )
        if any(position >= self.selection_position for position in positions):
            raise TrendlineStochasticNullComparisonError(
                "stochastic pivot is not causally prior"
            )
        donor_values = (
            self.donor_event_id,
            self.donor_selection_position,
            self.donor_selection_event_at,
            self.donor_selection_available_at,
            self.donor_selection_atr,
            self.donor_selection_close,
            self.donor_frozen_slope,
            self.donor_frozen_intercept,
            self.donor_level,
            self.normalised_donor_slope,
            self.normalised_donor_distance,
            self.donor_replay_point_id,
            self.donor_content_id,
            self.donor_source_id,
            self.donor_checkpoint_id,
        )
        if any(value is None for value in donor_values) and any(
            value is not None for value in donor_values
        ):
            raise TrendlineStochasticNullComparisonError(
                "density donor provenance must be complete"
            )
        if self.baseline_kind is TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR:
            if self.available:
                if len(positions) != 2 or self.selected_pivot_finality != CONFIRMED_PIVOT_FINALITY:
                    raise TrendlineStochasticNullComparisonError(
                        "random available selection requires two confirmed pivots"
                    )
            elif positions or self.selected_pivot_prices or self.selected_pivot_finality:
                raise TrendlineStochasticNullComparisonError(
                    "random abstention cannot retain pivot provenance"
                )
            if any(value is not None for value in donor_values):
                raise TrendlineStochasticNullComparisonError(
                    "random selection cannot retain donor provenance"
                )
            expected_reason = (
                "available" if self.available else "no_valid_same_role_pivot_pair"
            )
        else:
            if positions or prices or self.selected_pivot_finality is not None:
                raise TrendlineStochasticNullComparisonError(
                    "density selection cannot retain pivot provenance"
                )
            expected_reason = "available" if self.available else "no_prior_same_role_donor"
            if self.available:
                if any(value is None for value in donor_values):
                    raise TrendlineStochasticNullComparisonError(
                        "density available selection requires donor provenance"
                    )
                if not self.donor_selection_position < self.selection_position:
                    raise TrendlineStochasticNullComparisonError(
                        "density donor position is not prior"
                    )
                if not _timestamp_value(self.donor_selection_available_at) < _timestamp_value(
                    self.selection_available_at
                ):
                    raise TrendlineStochasticNullComparisonError(
                        "density donor availability is not prior"
                    )
                for name, value in (
                    ("donor_selection_atr", self.donor_selection_atr),
                    ("donor_selection_close", self.donor_selection_close),
                    ("donor_frozen_slope", self.donor_frozen_slope),
                    ("donor_frozen_intercept", self.donor_frozen_intercept),
                    ("donor_level", self.donor_level),
                    ("normalised_donor_slope", self.normalised_donor_slope),
                    ("normalised_donor_distance", self.normalised_donor_distance),
                ):
                    _finite(value, name=name)
                if self.donor_selection_atr <= 0:
                    raise TrendlineStochasticNullComparisonError(
                        "donor selection ATR must be positive"
                    )
            elif any(value is not None for value in donor_values):
                raise TrendlineStochasticNullComparisonError(
                    "density abstention cannot retain donor provenance"
                )
        if self.reason != expected_reason:
            raise TrendlineStochasticNullComparisonError(
                "stochastic selection reason does not match availability"
            )
        if self.available:
            _finite(self.frozen_slope, name="stochastic frozen slope")
            _finite(self.frozen_intercept, name="stochastic frozen intercept")
        for name, value in (
            ("replay_point_id", self.replay_point_id),
            ("content_id", self.content_id),
            ("source_id", self.source_id),
            ("checkpoint_id", self.checkpoint_id),
        ):
            _sha256(value, name=f"stochastic selection {name}")
        expected = canonical_hash(
            _selection_payload(self),
            semantics_version=STOCHASTIC_SELECTION_SEMANTICS_VERSION,
        )
        if self.selection_id and self.selection_id != expected:
            raise TrendlineStochasticNullComparisonError(
                "stochastic selection ID does not match content"
            )
        object.__setattr__(self, "selection_atr", selection_atr)
        object.__setattr__(self, "selected_pivot_positions", positions)
        object.__setattr__(self, "selected_pivot_prices", prices)
        object.__setattr__(self, "selection_id", expected)

    def to_dict(self) -> dict[str, Any]:
        return {"selection_id": self.selection_id, **_selection_payload(self)}


def _repetition_payload(
    row: "TrendlineNullRepetitionComparison",
) -> dict[str, Any]:
    return {
        "baseline_id": row.baseline_id,
        "baseline_name": row.baseline_name,
        "baseline_kind": row.baseline_kind.value,
        "baseline_seed": row.baseline_seed,
        "repetition_index": row.repetition_index,
        "timeframe": row.timeframe,
        "role": row.role,
        "horizon_bars": row.horizon_bars,
        "model_event_count": row.model_event_count,
        "available_null_selection_count": row.available_null_selection_count,
        "abstention_count": row.abstention_count,
        "matched_eligible_pair_count": row.matched_eligible_pair_count,
        "right_censored_pair_count": row.right_censored_pair_count,
        "coverage_rate": row.coverage_rate,
        "model_summary": row.model_summary.to_dict(),
        "null_summary": row.null_summary.to_dict(),
        "touch_rate_delta": row.touch_rate_delta,
        "rejection_rate_delta": row.rejection_rate_delta,
        "confirmed_break_rate_delta": row.confirmed_break_rate_delta,
        "false_break_rate_delta": row.false_break_rate_delta,
        "mean_penetration_atr_delta": row.mean_penetration_atr_delta,
        "mean_favourable_excursion_atr_delta": row.mean_favourable_excursion_atr_delta,
        "mean_adverse_excursion_atr_delta": row.mean_adverse_excursion_atr_delta,
        "semantics_version": STOCHASTIC_REPETITION_COMPARISON_SEMANTICS_VERSION,
    }


@dataclass(frozen=True)
class TrendlineNullRepetitionComparison:
    """One paired model/null summary for one repetition coordinate."""

    baseline_id: str
    baseline_name: str
    baseline_kind: TrendlineAdequacyBaselineKind
    baseline_seed: int
    repetition_index: int
    timeframe: str
    role: str
    horizon_bars: int
    model_event_count: int
    available_null_selection_count: int
    abstention_count: int
    matched_eligible_pair_count: int
    right_censored_pair_count: int
    coverage_rate: float | None
    model_summary: TrendlineInteractionSummary
    null_summary: TrendlineInteractionSummary
    touch_rate_delta: float | None
    rejection_rate_delta: float | None
    confirmed_break_rate_delta: float | None
    false_break_rate_delta: float | None
    mean_penetration_atr_delta: float | None
    mean_favourable_excursion_atr_delta: float | None
    mean_adverse_excursion_atr_delta: float | None
    comparison_id: str = ""

    def __post_init__(self) -> None:
        _sha256(self.baseline_id, name="repetition baseline_id")
        _identity(self.baseline_name, name="repetition baseline_name")
        if self.baseline_kind not in STOCHASTIC_NULL_KINDS:
            raise TrendlineStochasticNullComparisonError(
                "repetition baseline kind is not stochastic"
            )
        _strict_int(self.baseline_seed, name="repetition baseline seed")
        _strict_int(self.repetition_index, name="repetition index", minimum=0)
        _identity(self.timeframe, name="repetition timeframe")
        if self.role not in INTERACTION_ROLES:
            raise TrendlineStochasticNullComparisonError("repetition role is invalid")
        horizon = _strict_int(self.horizon_bars, name="repetition horizon", minimum=1)
        counts = {}
        for name, value in (
            ("model_event_count", self.model_event_count),
            ("available_null_selection_count", self.available_null_selection_count),
            ("abstention_count", self.abstention_count),
            ("matched_eligible_pair_count", self.matched_eligible_pair_count),
            ("right_censored_pair_count", self.right_censored_pair_count),
        ):
            counts[name] = _strict_int(value, name=name)
        if counts["available_null_selection_count"] + counts["abstention_count"] != counts["model_event_count"]:
            raise TrendlineStochasticNullComparisonError(
                "null availability plus abstentions differs from model events"
            )
        if counts["matched_eligible_pair_count"] + counts["right_censored_pair_count"] != counts[
            "available_null_selection_count"
        ]:
            raise TrendlineStochasticNullComparisonError(
                "null eligible plus right-censored differs from available"
            )
        for name, summary in (
            ("model summary", self.model_summary),
            ("null summary", self.null_summary),
        ):
            if not isinstance(summary, TrendlineInteractionSummary):
                raise TrendlineStochasticNullComparisonError(f"{name} must be typed")
            if (
                summary.timeframe != self.timeframe
                or summary.role != self.role
                or summary.horizon_bars != horizon
            ):
                raise TrendlineStochasticNullComparisonError(
                    f"{name} coordinate differs from repetition"
                )
            if summary.event_count != counts["available_null_selection_count"]:
                raise TrendlineStochasticNullComparisonError(
                    f"{name} event count differs from available null selections"
                )
            if summary.eligible_event_count != counts["matched_eligible_pair_count"]:
                raise TrendlineStochasticNullComparisonError(
                    f"{name} eligible count differs from repetition"
                )
            if summary.right_censored_count != counts["right_censored_pair_count"]:
                raise TrendlineStochasticNullComparisonError(
                    f"{name} right-censored count differs from repetition"
                )
        expected_coverage = (
            counts["available_null_selection_count"] / counts["model_event_count"]
            if counts["model_event_count"]
            else None
        )
        if self.coverage_rate != expected_coverage:
            raise TrendlineStochasticNullComparisonError(
                "repetition coverage rate is not derived from counts"
            )
        for field in STOCHASTIC_DISTRIBUTION_METRICS:
            expected = _optional_delta(
                getattr(self.model_summary, field),
                getattr(self.null_summary, field),
            )
            actual = getattr(self, f"{field}_delta")
            if actual != expected:
                raise TrendlineStochasticNullComparisonError(
                    f"repetition {field} delta differs from summaries"
                )
        expected = canonical_hash(
            _repetition_payload(self),
            semantics_version=STOCHASTIC_REPETITION_COMPARISON_SEMANTICS_VERSION,
        )
        if self.comparison_id and self.comparison_id != expected:
            raise TrendlineStochasticNullComparisonError(
                "repetition comparison ID does not match content"
            )
        object.__setattr__(self, "horizon_bars", horizon)
        for name, value in counts.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "comparison_id", expected)

    def to_dict(self) -> dict[str, Any]:
        return {"comparison_id": self.comparison_id, **_repetition_payload(self)}


def _distribution_payload(
    row: "TrendlineNullDistributionSummary",
) -> dict[str, Any]:
    return {
        "baseline_id": row.baseline_id,
        "baseline_name": row.baseline_name,
        "baseline_kind": row.baseline_kind.value,
        "baseline_seed": row.baseline_seed,
        "repetition_count": row.repetition_count,
        "timeframe": row.timeframe,
        "role": row.role,
        "horizon_bars": row.horizon_bars,
        "metric": row.metric,
        "comparison_ids": list(row.comparison_ids),
        "defined_repetition_count": row.defined_repetition_count,
        "undefined_repetition_count": row.undefined_repetition_count,
        "mean_delta": row.mean_delta,
        "median_delta": row.median_delta,
        "minimum_delta": row.minimum_delta,
        "maximum_delta": row.maximum_delta,
        "q05_delta": row.q05_delta,
        "q95_delta": row.q95_delta,
        "negative_delta_count": row.negative_delta_count,
        "zero_delta_count": row.zero_delta_count,
        "positive_delta_count": row.positive_delta_count,
        "semantics_version": STOCHASTIC_DISTRIBUTION_SUMMARY_SEMANTICS_VERSION,
    }


@dataclass(frozen=True)
class TrendlineNullDistributionSummary:
    """Distribution of one model-minus-null statistic across repetitions."""

    baseline_id: str
    baseline_name: str
    baseline_kind: TrendlineAdequacyBaselineKind
    baseline_seed: int
    repetition_count: int
    timeframe: str
    role: str
    horizon_bars: int
    metric: str
    comparison_ids: tuple[str, ...]
    defined_repetition_count: int
    undefined_repetition_count: int
    mean_delta: float | None
    median_delta: float | None
    minimum_delta: float | None
    maximum_delta: float | None
    q05_delta: float | None
    q95_delta: float | None
    negative_delta_count: int
    zero_delta_count: int
    positive_delta_count: int
    distribution_id: str = ""

    def __post_init__(self) -> None:
        _sha256(self.baseline_id, name="distribution baseline_id")
        _identity(self.baseline_name, name="distribution baseline_name")
        if self.baseline_kind not in STOCHASTIC_NULL_KINDS:
            raise TrendlineStochasticNullComparisonError(
                "distribution baseline kind is not stochastic"
            )
        _strict_int(self.baseline_seed, name="distribution seed")
        repetition_count = _strict_int(
            self.repetition_count,
            name="distribution repetition count",
            minimum=1,
        )
        _identity(self.timeframe, name="distribution timeframe")
        if self.role not in INTERACTION_ROLES:
            raise TrendlineStochasticNullComparisonError("distribution role is invalid")
        _strict_int(self.horizon_bars, name="distribution horizon", minimum=1)
        if self.metric not in STOCHASTIC_DISTRIBUTION_METRICS:
            raise TrendlineStochasticNullComparisonError("distribution metric is invalid")
        comparison_ids = tuple(self.comparison_ids)
        if len(comparison_ids) != repetition_count or not all(
            len(value) == 64
            and all(char in "0123456789abcdef" for char in value)
            for value in comparison_ids
        ):
            raise TrendlineStochasticNullComparisonError(
                "distribution comparison IDs do not cover repetitions"
            )
        defined = _strict_int(
            self.defined_repetition_count,
            name="defined repetition count",
        )
        undefined = _strict_int(
            self.undefined_repetition_count,
            name="undefined repetition count",
        )
        if defined + undefined != repetition_count:
            raise TrendlineStochasticNullComparisonError(
                "defined plus undefined repetitions differs from repetition count"
            )
        for name, value in (
            ("negative_delta_count", self.negative_delta_count),
            ("zero_delta_count", self.zero_delta_count),
            ("positive_delta_count", self.positive_delta_count),
        ):
            _strict_int(value, name=name)
        if self.negative_delta_count + self.zero_delta_count + self.positive_delta_count != defined:
            raise TrendlineStochasticNullComparisonError(
                "distribution sign counts differ from defined repetitions"
            )
        stats = (
            self.mean_delta,
            self.median_delta,
            self.minimum_delta,
            self.maximum_delta,
            self.q05_delta,
            self.q95_delta,
        )
        if defined == 0 and any(value is not None for value in stats):
            raise TrendlineStochasticNullComparisonError(
                "undefined distribution cannot retain statistics"
            )
        for name, value in (
            ("mean_delta", self.mean_delta),
            ("median_delta", self.median_delta),
            ("minimum_delta", self.minimum_delta),
            ("maximum_delta", self.maximum_delta),
            ("q05_delta", self.q05_delta),
            ("q95_delta", self.q95_delta),
        ):
            if value is not None:
                _finite(value, name=name)
        expected = canonical_hash(
            _distribution_payload(self),
            semantics_version=STOCHASTIC_DISTRIBUTION_SUMMARY_SEMANTICS_VERSION,
        )
        if self.distribution_id and self.distribution_id != expected:
            raise TrendlineStochasticNullComparisonError(
                "distribution ID does not match content"
            )
        object.__setattr__(self, "repetition_count", repetition_count)
        object.__setattr__(self, "comparison_ids", comparison_ids)
        object.__setattr__(self, "defined_repetition_count", defined)
        object.__setattr__(self, "undefined_repetition_count", undefined)
        object.__setattr__(self, "distribution_id", expected)

    def to_dict(self) -> dict[str, Any]:
        return {"distribution_id": self.distribution_id, **_distribution_payload(self)}


def _bundle_payload(
    bundle: "TrendlineStochasticNullComparisonBundle",
) -> dict[str, Any]:
    return {
        "dataset_id": bundle.dataset_id,
        "replay_id": bundle.replay_id,
        "cohort_id": bundle.cohort_id,
        "study_config_id": bundle.study_config_id,
        "structural_stability_bundle_id": bundle.structural_stability_bundle_id,
        "interaction_utility_bundle_id": bundle.interaction_utility_bundle_id,
        "baseline_comparison_bundle_id": bundle.baseline_comparison_bundle_id,
        "interaction_spec": bundle.interaction_spec.to_dict(),
        "interaction_spec_id": bundle.interaction_spec_id,
        "stochastic_baseline_specs": [
            spec.to_dict() for spec in bundle.stochastic_baseline_specs
        ],
        "quantile_probabilities": list(bundle.quantile_probabilities),
        "model_event_ids": list(bundle.model_event_ids),
        "stochastic_selections": [
            row.to_dict() for row in bundle.stochastic_selections
        ],
        "null_outcomes": [row.to_dict() for row in bundle.null_outcomes],
        "repetition_comparisons": [
            row.to_dict() for row in bundle.repetition_comparisons
        ],
        "distribution_summaries": [
            row.to_dict() for row in bundle.distribution_summaries
        ],
        "semantics_version": STOCHASTIC_NULL_BUNDLE_SEMANTICS_VERSION,
    }


@dataclass(frozen=True)
class TrendlineStochasticNullComparisonBundle:
    """Content-addressed seeded stochastic-null comparison evidence."""

    dataset_id: str
    replay_id: str
    cohort_id: str
    study_config_id: str
    structural_stability_bundle_id: str
    interaction_utility_bundle_id: str
    baseline_comparison_bundle_id: str
    interaction_spec: TrendlineInteractionUtilitySpec
    interaction_spec_id: str
    stochastic_baseline_specs: tuple[TrendlineAdequacyBaselineSpec, ...]
    quantile_probabilities: tuple[float, ...]
    model_event_ids: tuple[str, ...]
    stochastic_selections: tuple[TrendlineStochasticNullSelection, ...]
    null_outcomes: tuple[TrendlineInteractionOutcome, ...]
    repetition_comparisons: tuple[TrendlineNullRepetitionComparison, ...]
    distribution_summaries: tuple[TrendlineNullDistributionSummary, ...]
    stochastic_null_comparison_bundle_id: str = ""

    def __post_init__(self) -> None:
        for name, value in (
            ("dataset_id", self.dataset_id),
            ("replay_id", self.replay_id),
            ("cohort_id", self.cohort_id),
            ("study_config_id", self.study_config_id),
            ("structural_stability_bundle_id", self.structural_stability_bundle_id),
            ("interaction_utility_bundle_id", self.interaction_utility_bundle_id),
            ("baseline_comparison_bundle_id", self.baseline_comparison_bundle_id),
            ("interaction_spec_id", self.interaction_spec_id),
        ):
            _sha256(value, name=f"stochastic bundle {name}")
        if not isinstance(self.interaction_spec, TrendlineInteractionUtilitySpec):
            raise TrendlineStochasticNullComparisonError(
                "stochastic bundle interaction spec is invalid"
            )
        if self.interaction_spec_id != self.interaction_spec.interaction_spec_id:
            raise TrendlineStochasticNullComparisonError(
                "stochastic bundle interaction spec identity differs"
            )
        specs = _approved_stochastic_specs(self.stochastic_baseline_specs)
        probabilities = tuple(float(value) for value in self.quantile_probabilities)
        if probabilities != STOCHASTIC_QUANTILE_PROBABILITIES:
            raise TrendlineStochasticNullComparisonError(
                "stochastic quantile probabilities must be (0.05, 0.95)"
            )
        if not isinstance(self.model_event_ids, tuple) or not all(
            len(value) == 64
            and all(char in "0123456789abcdef" for char in value)
            for value in self.model_event_ids
        ):
            raise TrendlineStochasticNullComparisonError(
                "stochastic model event IDs must be immutable SHA identities"
            )
        for rows, row_type, name in (
            (
                self.stochastic_selections,
                TrendlineStochasticNullSelection,
                "selections",
            ),
            (self.null_outcomes, TrendlineInteractionOutcome, "outcomes"),
            (
                self.repetition_comparisons,
                TrendlineNullRepetitionComparison,
                "repetition comparisons",
            ),
            (
                self.distribution_summaries,
                TrendlineNullDistributionSummary,
                "distribution summaries",
            ),
        ):
            if not isinstance(rows, tuple) or not all(
                isinstance(row, row_type) for row in rows
            ):
                raise TrendlineStochasticNullComparisonError(
                    f"stochastic {name} must be immutable typed rows"
                )
        expected = canonical_hash(
            _bundle_payload(self),
            semantics_version=STOCHASTIC_NULL_BUNDLE_SEMANTICS_VERSION,
        )
        if self.stochastic_null_comparison_bundle_id and self.stochastic_null_comparison_bundle_id != expected:
            raise TrendlineStochasticNullComparisonError(
                "stochastic bundle ID does not match content"
            )
        object.__setattr__(self, "stochastic_baseline_specs", specs)
        object.__setattr__(self, "quantile_probabilities", probabilities)
        object.__setattr__(self, "stochastic_null_comparison_bundle_id", expected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stochastic_null_comparison_bundle_id": self.stochastic_null_comparison_bundle_id,
            **_bundle_payload(self),
        }


def _selection_from_random_pair(
    spec: TrendlineAdequacyBaselineSpec,
    event: TrendlineInteractionEvent,
    point: Any,
    selection_close: float,
    repetition_index: int,
    draw_id: str,
    candidates: Sequence[tuple[int, int, float, float]],
) -> TrendlineStochasticNullSelection:
    if not candidates:
        return TrendlineStochasticNullSelection(
            baseline_id=spec.baseline_id,
            baseline_name=spec.name,
            baseline_kind=spec.kind,
            baseline_seed=spec.seed,
            repetition_index=repetition_index,
            model_event_id=event.event_id,
            timeframe=event.timeframe,
            role=event.role,
            selection_position=event.selection_position,
            selection_event_at=event.selection_event_at,
            selection_available_at=event.selection_available_at,
            selection_close=selection_close,
            selection_atr=event.selection_atr,
            available=False,
            reason="no_valid_same_role_pivot_pair",
            draw_id=draw_id,
            candidate_count=0,
            selected_candidate_index=None,
            replay_point_id=event.replay_point_id,
            content_id=event.content_id,
            source_id=event.source_id,
            checkpoint_id=event.checkpoint_id,
            frozen_slope=None,
            frozen_intercept=None,
        )
    selected_index = _draw_index(draw_id, len(candidates))
    x1, x2, y1, y2 = candidates[selected_index]
    slope = (y2 - y1) / (x2 - x1)
    intercept = y2 - slope * x2
    return TrendlineStochasticNullSelection(
        baseline_id=spec.baseline_id,
        baseline_name=spec.name,
        baseline_kind=spec.kind,
        baseline_seed=spec.seed,
        repetition_index=repetition_index,
        model_event_id=event.event_id,
        timeframe=event.timeframe,
        role=event.role,
        selection_position=event.selection_position,
        selection_event_at=event.selection_event_at,
        selection_available_at=event.selection_available_at,
        selection_close=selection_close,
        selection_atr=event.selection_atr,
        available=True,
        reason="available",
        draw_id=draw_id,
        candidate_count=len(candidates),
        selected_candidate_index=selected_index,
        replay_point_id=event.replay_point_id,
        content_id=event.content_id,
        source_id=event.source_id,
        checkpoint_id=event.checkpoint_id,
        frozen_slope=slope,
        frozen_intercept=intercept,
        selected_pivot_positions=(x1, x2),
        selected_pivot_prices=(y1, y2),
        selected_pivot_finality=CONFIRMED_PIVOT_FINALITY,
    )


def _selection_from_density_donor(
    spec: TrendlineAdequacyBaselineSpec,
    event: TrendlineInteractionEvent,
    point: Any,
    selection_close: float,
    repetition_index: int,
    draw_id: str,
    donors: Sequence[TrendlineInteractionEvent],
    donor_closes: Mapping[str, float],
) -> TrendlineStochasticNullSelection:
    if not donors:
        return TrendlineStochasticNullSelection(
            baseline_id=spec.baseline_id,
            baseline_name=spec.name,
            baseline_kind=spec.kind,
            baseline_seed=spec.seed,
            repetition_index=repetition_index,
            model_event_id=event.event_id,
            timeframe=event.timeframe,
            role=event.role,
            selection_position=event.selection_position,
            selection_event_at=event.selection_event_at,
            selection_available_at=event.selection_available_at,
            selection_close=selection_close,
            selection_atr=event.selection_atr,
            available=False,
            reason="no_prior_same_role_donor",
            draw_id=draw_id,
            candidate_count=0,
            selected_candidate_index=None,
            replay_point_id=event.replay_point_id,
            content_id=event.content_id,
            source_id=event.source_id,
            checkpoint_id=event.checkpoint_id,
            frozen_slope=None,
            frozen_intercept=None,
        )
    selected_index = _draw_index(draw_id, len(donors))
    donor = donors[selected_index]
    (
        slope,
        intercept,
        normalised_slope,
        normalised_distance,
        donor_level,
        donor_close,
        _current_level,
    ) = _transport_density_geometry(
        event,
        donor,
        current_selection_close=selection_close,
        donor_selection_close=donor_closes[donor.event_id],
    )
    return TrendlineStochasticNullSelection(
        baseline_id=spec.baseline_id,
        baseline_name=spec.name,
        baseline_kind=spec.kind,
        baseline_seed=spec.seed,
        repetition_index=repetition_index,
        model_event_id=event.event_id,
        timeframe=event.timeframe,
        role=event.role,
        selection_position=event.selection_position,
        selection_event_at=event.selection_event_at,
        selection_available_at=event.selection_available_at,
        selection_close=selection_close,
        selection_atr=event.selection_atr,
        available=True,
        reason="available",
        draw_id=draw_id,
        candidate_count=len(donors),
        selected_candidate_index=selected_index,
        replay_point_id=event.replay_point_id,
        content_id=event.content_id,
        source_id=event.source_id,
        checkpoint_id=event.checkpoint_id,
        frozen_slope=slope,
        frozen_intercept=intercept,
        donor_event_id=donor.event_id,
        donor_selection_position=donor.selection_position,
        donor_selection_event_at=donor.selection_event_at,
        donor_selection_available_at=donor.selection_available_at,
        donor_selection_atr=donor.selection_atr,
        donor_selection_close=donor_close,
        donor_frozen_slope=donor.frozen_slope,
        donor_frozen_intercept=donor.frozen_intercept,
        donor_level=donor_level,
        normalised_donor_slope=normalised_slope,
        normalised_donor_distance=normalised_distance,
        donor_replay_point_id=donor.replay_point_id,
        donor_content_id=donor.content_id,
        donor_source_id=donor.source_id,
        donor_checkpoint_id=donor.checkpoint_id,
    )


def build_stochastic_null_selections(
    prepared: PreparedTrendlineResearchRun,
    replay: PreparedTrendlineResearchReplay,
    interaction_bundle: TrendlineInteractionUtilityBundle,
    stochastic_baseline_specs: Sequence[TrendlineAdequacyBaselineSpec],
) -> tuple[TrendlineStochasticNullSelection, ...]:
    """Build one deterministic seeded attempt per event/repetition/baseline."""

    if replay.prepared is not prepared:
        raise TrendlineStochasticNullComparisonError(
            "prepared run does not belong to replay"
        )
    specs = _approved_stochastic_specs(stochastic_baseline_specs)
    events = _canonical_events(interaction_bundle.events)
    point_cache = {event.event_id: _event_point(event, replay) for event in events}
    close_cache = {
        event.event_id: _selection_close(replay, event) for event in events
    }
    pivot_cache: dict[str, tuple[tuple[int, int, float, float], ...]] = {}
    donor_cache: dict[str, tuple[TrendlineInteractionEvent, ...]] = {}
    results: list[TrendlineStochasticNullSelection] = []
    for spec in specs:
        for repetition_index in range(spec.repetitions):
            for event in events:
                point = point_cache[event.event_id]
                draw_id = derive_stochastic_draw_id(
                    spec.baseline_id,
                    spec.seed,
                    repetition_index,
                    event.event_id,
                )
                if spec.kind is TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR:
                    candidates = pivot_cache.get(event.event_id)
                    if candidates is None:
                        pivots = _validated_pivots(prepared, replay, event, point)
                        candidates = _role_pivot_pairs(
                            pivots,
                            event,
                            close_cache[event.event_id],
                        )
                        pivot_cache[event.event_id] = candidates
                    result = _selection_from_random_pair(
                        spec,
                        event,
                        point,
                        close_cache[event.event_id],
                        repetition_index,
                        draw_id,
                        candidates,
                    )
                else:
                    donors = donor_cache.get(event.event_id)
                    if donors is None:
                        donors = _density_donors(event, events)
                        donor_cache[event.event_id] = donors
                    result = _selection_from_density_donor(
                        spec,
                        event,
                        point,
                        close_cache[event.event_id],
                        repetition_index,
                        draw_id,
                        donors,
                        close_cache,
                    )
                results.append(result)
    return tuple(results)


def build_stochastic_null_outcomes(
    selections: Sequence[TrendlineStochasticNullSelection],
    replay: PreparedTrendlineResearchReplay,
    interaction_spec: TrendlineInteractionUtilitySpec,
) -> tuple[TrendlineInteractionOutcome, ...]:
    """Measure D3 outcomes for each available frozen null geometry."""

    result: list[TrendlineInteractionOutcome] = []
    for selection in selections:
        if not selection.available:
            continue
        frame = replay.prepared.dataset.frames[selection.timeframe]
        result.extend(
            measure_frozen_geometry_outcomes(
                interaction_event_id=selection.selection_id,
                role=selection.role,
                selection_position=selection.selection_position,
                selection_available_at=selection.selection_available_at,
                selection_atr=selection.selection_atr,
                frozen_slope=selection.frozen_slope,
                frozen_intercept=selection.frozen_intercept,
                frame=frame,
                interaction_spec=interaction_spec,
            )
        )
    return tuple(result)


def _summary_map(
    values: Sequence[TrendlineInteractionSummary],
) -> dict[tuple[str, str, int], TrendlineInteractionSummary]:
    result: dict[tuple[str, str, int], TrendlineInteractionSummary] = {}
    for summary in values:
        key = (summary.timeframe, summary.role, summary.horizon_bars)
        if key in result:
            raise TrendlineStochasticNullComparisonError(
                "duplicate interaction summary coordinate"
            )
        result[key] = summary
    return result


def _build_repetition_comparisons(
    interaction_bundle: TrendlineInteractionUtilityBundle,
    specs: Sequence[TrendlineAdequacyBaselineSpec],
    selections: Sequence[TrendlineStochasticNullSelection],
    outcomes: Sequence[TrendlineInteractionOutcome],
    interaction_spec: TrendlineInteractionUtilitySpec,
) -> tuple[TrendlineNullRepetitionComparison, ...]:
    events = _canonical_events(interaction_bundle.events)
    timeframes = _timeframes(events)
    result: list[TrendlineNullRepetitionComparison] = []
    model_event_counts = {
        (timeframe, role): sum(
            event.timeframe == timeframe and event.role == role for event in events
        )
        for timeframe in timeframes
        for role in INTERACTION_ROLES
    }
    for spec in specs:
        for repetition_index in range(spec.repetitions):
            repetition_selections = tuple(
                selection
                for selection in selections
                if selection.baseline_id == spec.baseline_id
                and selection.repetition_index == repetition_index
            )
            available = tuple(
                selection for selection in repetition_selections if selection.available
            )
            model_bindings = {
                selection.model_event_id: (selection.timeframe, selection.role)
                for selection in available
            }
            null_bindings = {
                selection.selection_id: (selection.timeframe, selection.role)
                for selection in available
            }
            model_outcomes = tuple(
                outcome
                for outcome in interaction_bundle.outcomes
                if outcome.interaction_event_id in model_bindings
            )
            null_outcomes = tuple(
                outcome
                for outcome in outcomes
                if outcome.interaction_event_id in null_bindings
            )
            model_summaries = build_interaction_summaries(
                model_bindings,
                model_outcomes,
                timeframes,
                interaction_spec,
            )
            null_summaries = build_interaction_summaries(
                null_bindings,
                null_outcomes,
                timeframes,
                interaction_spec,
            )
            model_summary_map = _summary_map(model_summaries)
            null_summary_map = _summary_map(null_summaries)
            for timeframe in timeframes:
                for role in INTERACTION_ROLES:
                    model_event_count = model_event_counts[(timeframe, role)]
                    available_count = sum(
                        selection.timeframe == timeframe and selection.role == role
                        for selection in available
                    )
                    for horizon in interaction_spec.evaluation_horizons_bars:
                        model_summary = model_summary_map[(timeframe, role, horizon)]
                        null_summary = null_summary_map[(timeframe, role, horizon)]
                        result.append(
                            TrendlineNullRepetitionComparison(
                                baseline_id=spec.baseline_id,
                                baseline_name=spec.name,
                                baseline_kind=spec.kind,
                                baseline_seed=spec.seed,
                                repetition_index=repetition_index,
                                timeframe=timeframe,
                                role=role,
                                horizon_bars=horizon,
                                model_event_count=model_event_count,
                                available_null_selection_count=available_count,
                                abstention_count=model_event_count - available_count,
                                matched_eligible_pair_count=model_summary.eligible_event_count,
                                right_censored_pair_count=model_summary.right_censored_count,
                                coverage_rate=(
                                    available_count / model_event_count
                                    if model_event_count
                                    else None
                                ),
                                model_summary=model_summary,
                                null_summary=null_summary,
                                touch_rate_delta=_optional_delta(
                                    model_summary.touch_rate,
                                    null_summary.touch_rate,
                                ),
                                rejection_rate_delta=_optional_delta(
                                    model_summary.rejection_rate,
                                    null_summary.rejection_rate,
                                ),
                                confirmed_break_rate_delta=_optional_delta(
                                    model_summary.confirmed_break_rate,
                                    null_summary.confirmed_break_rate,
                                ),
                                false_break_rate_delta=_optional_delta(
                                    model_summary.false_break_rate,
                                    null_summary.false_break_rate,
                                ),
                                mean_penetration_atr_delta=_optional_delta(
                                    model_summary.mean_penetration_atr,
                                    null_summary.mean_penetration_atr,
                                ),
                                mean_favourable_excursion_atr_delta=_optional_delta(
                                    model_summary.mean_favourable_excursion_atr,
                                    null_summary.mean_favourable_excursion_atr,
                                ),
                                mean_adverse_excursion_atr_delta=_optional_delta(
                                    model_summary.mean_adverse_excursion_atr,
                                    null_summary.mean_adverse_excursion_atr,
                                ),
                            )
                        )
    return tuple(result)


def _build_distribution_summaries(
    specs: Sequence[TrendlineAdequacyBaselineSpec],
    comparisons: Sequence[TrendlineNullRepetitionComparison],
    timeframes: Sequence[str],
    interaction_spec: TrendlineInteractionUtilitySpec,
) -> tuple[TrendlineNullDistributionSummary, ...]:
    result: list[TrendlineNullDistributionSummary] = []
    for spec in specs:
        for timeframe in timeframes:
            for role in INTERACTION_ROLES:
                for horizon in interaction_spec.evaluation_horizons_bars:
                    rows = tuple(
                        row
                        for row in comparisons
                        if row.baseline_id == spec.baseline_id
                        and row.timeframe == timeframe
                        and row.role == role
                        and row.horizon_bars == horizon
                    )
                    if tuple(row.repetition_index for row in rows) != tuple(
                        range(spec.repetitions)
                    ):
                        raise TrendlineStochasticNullComparisonError(
                            "distribution repetitions are incomplete or unordered"
                        )
                    for metric in STOCHASTIC_DISTRIBUTION_METRICS:
                        values = tuple(
                            getattr(row, f"{metric}_delta")
                            for row in rows
                            if getattr(row, f"{metric}_delta") is not None
                        )
                        defined = len(values)
                        undefined = spec.repetitions - defined
                        if values:
                            q05, q95 = _quantiles(values)
                            mean_delta = float(fmean(values))
                            median_delta = float(median(values))
                            minimum_delta = min(values)
                            maximum_delta = max(values)
                            negative = sum(value < 0 for value in values)
                            zero = sum(value == 0 for value in values)
                            positive = sum(value > 0 for value in values)
                        else:
                            q05 = q95 = None
                            mean_delta = median_delta = None
                            minimum_delta = maximum_delta = None
                            negative = zero = positive = 0
                        result.append(
                            TrendlineNullDistributionSummary(
                                baseline_id=spec.baseline_id,
                                baseline_name=spec.name,
                                baseline_kind=spec.kind,
                                baseline_seed=spec.seed,
                                repetition_count=spec.repetitions,
                                timeframe=timeframe,
                                role=role,
                                horizon_bars=horizon,
                                metric=metric,
                                comparison_ids=tuple(
                                    row.comparison_id for row in rows
                                ),
                                defined_repetition_count=defined,
                                undefined_repetition_count=undefined,
                                mean_delta=mean_delta,
                                median_delta=median_delta,
                                minimum_delta=minimum_delta,
                                maximum_delta=maximum_delta,
                                q05_delta=q05,
                                q95_delta=q95,
                                negative_delta_count=negative,
                                zero_delta_count=zero,
                                positive_delta_count=positive,
                            )
                        )
    return tuple(result)


def build_stochastic_null_comparison_bundle(
    prepared: PreparedTrendlineResearchRun,
    replay: PreparedTrendlineResearchReplay,
    study_config: TrendlineAdequacyStudyConfig,
    structural_stability_bundle: TrendlineStructuralStabilityBundle,
    interaction_bundle: TrendlineInteractionUtilityBundle,
    deterministic_baseline_bundle: TrendlineDeterministicBaselineComparisonBundle,
    stochastic_baseline_specs: Sequence[TrendlineAdequacyBaselineSpec],
    *,
    quantile_probabilities: Sequence[float],
) -> TrendlineStochasticNullComparisonBundle:
    """Build and fully validate one bounded stochastic-null comparison."""

    specs = _approved_stochastic_specs(stochastic_baseline_specs)
    probabilities = tuple(float(value) for value in quantile_probabilities)
    if probabilities != STOCHASTIC_QUANTILE_PROBABILITIES:
        raise TrendlineStochasticNullComparisonError(
            "D4B quantile probabilities must be explicit (0.05, 0.95)"
        )
    selections = build_stochastic_null_selections(
        prepared,
        replay,
        interaction_bundle,
        specs,
    )
    outcomes = build_stochastic_null_outcomes(
        selections,
        replay,
        interaction_bundle.interaction_spec,
    )
    comparisons = _build_repetition_comparisons(
        interaction_bundle,
        specs,
        selections,
        outcomes,
        interaction_bundle.interaction_spec,
    )
    distributions = _build_distribution_summaries(
        specs,
        comparisons,
        _timeframes(interaction_bundle.events),
        interaction_bundle.interaction_spec,
    )
    bundle = TrendlineStochasticNullComparisonBundle(
        dataset_id=replay.dataset_id,
        replay_id=replay.replay_id,
        cohort_id=structural_stability_bundle.cohort_id,
        study_config_id=structural_stability_bundle.study_config_id,
        structural_stability_bundle_id=structural_stability_bundle.structural_stability_bundle_id,
        interaction_utility_bundle_id=interaction_bundle.interaction_utility_bundle_id,
        baseline_comparison_bundle_id=deterministic_baseline_bundle.baseline_comparison_bundle_id,
        interaction_spec=interaction_bundle.interaction_spec,
        interaction_spec_id=interaction_bundle.interaction_spec_id,
        stochastic_baseline_specs=specs,
        quantile_probabilities=probabilities,
        model_event_ids=tuple(
            event.event_id for event in _canonical_events(interaction_bundle.events)
        ),
        stochastic_selections=selections,
        null_outcomes=outcomes,
        repetition_comparisons=comparisons,
        distribution_summaries=distributions,
    )
    validate_stochastic_null_comparison_bundle(
        bundle,
        prepared=prepared,
        replay=replay,
        structural_stability_bundle=structural_stability_bundle,
        interaction_bundle=interaction_bundle,
        deterministic_baseline_bundle=deterministic_baseline_bundle,
        study_config=study_config,
    )
    return bundle


def _expected_distribution_values(
    rows: Sequence[TrendlineNullRepetitionComparison],
    metric: str,
) -> tuple[float, ...]:
    return tuple(
        value
        for value in (getattr(row, f"{metric}_delta") for row in rows)
        if value is not None
    )


def validate_stochastic_null_comparison_bundle(
    bundle: TrendlineStochasticNullComparisonBundle,
    *,
    prepared: PreparedTrendlineResearchRun,
    replay: PreparedTrendlineResearchReplay,
    structural_stability_bundle: TrendlineStructuralStabilityBundle,
    interaction_bundle: TrendlineInteractionUtilityBundle,
    deterministic_baseline_bundle: TrendlineDeterministicBaselineComparisonBundle,
    study_config: TrendlineAdequacyStudyConfig,
) -> None:
    """Recompute all stochastic selections, outcomes, summaries, and identity."""

    if not isinstance(bundle, TrendlineStochasticNullComparisonBundle):
        raise TrendlineStochasticNullComparisonError("stochastic bundle must be typed")
    if replay.prepared is not prepared:
        raise TrendlineStochasticNullComparisonError(
            "prepared run does not belong to replay"
        )
    validate_structural_stability_bundle(structural_stability_bundle)
    validate_interaction_utility_bundle(
        interaction_bundle,
        structural_stability_bundle=structural_stability_bundle,
        replay=replay,
    )
    validate_baseline_comparison_bundle(
        deterministic_baseline_bundle,
        prepared=prepared,
        replay=replay,
        structural_stability_bundle=structural_stability_bundle,
        interaction_bundle=interaction_bundle,
        study_config=study_config,
    )
    expected_ids = {
        "dataset_id": replay.dataset_id,
        "replay_id": replay.replay_id,
        "cohort_id": structural_stability_bundle.cohort_id,
        "study_config_id": structural_stability_bundle.study_config_id,
        "structural_stability_bundle_id": structural_stability_bundle.structural_stability_bundle_id,
        "interaction_utility_bundle_id": interaction_bundle.interaction_utility_bundle_id,
        "baseline_comparison_bundle_id": deterministic_baseline_bundle.baseline_comparison_bundle_id,
        "interaction_spec_id": interaction_bundle.interaction_spec_id,
    }
    for name, expected in expected_ids.items():
        if getattr(bundle, name) != expected:
            raise TrendlineStochasticNullComparisonError(
                f"stochastic bundle {name} differs from source"
            )
    if bundle.interaction_spec.to_dict() != interaction_bundle.interaction_spec.to_dict():
        raise TrendlineStochasticNullComparisonError(
            "stochastic interaction spec differs from D3"
        )
    specs = _approved_stochastic_specs(bundle.stochastic_baseline_specs)
    if tuple(spec.to_dict() for spec in bundle.stochastic_baseline_specs) != tuple(
        spec.to_dict() for spec in specs
    ):
        raise TrendlineStochasticNullComparisonError(
            "stochastic baseline specs differ"
        )
    expected_events = _canonical_events(interaction_bundle.events)
    expected_event_ids = tuple(event.event_id for event in expected_events)
    if bundle.model_event_ids != expected_event_ids:
        raise TrendlineStochasticNullComparisonError(
            "stochastic model event IDs differ"
        )
    expected_selections = build_stochastic_null_selections(
        prepared,
        replay,
        interaction_bundle,
        specs,
    )
    expected_selection_coordinates = {
        (spec.baseline_id, repetition, event.event_id)
        for spec in specs
        for repetition in range(spec.repetitions)
        for event in expected_events
    }
    actual_selection_coordinates = [
        (selection.baseline_id, selection.repetition_index, selection.model_event_id)
        for selection in bundle.stochastic_selections
    ]
    if (
        len(set(actual_selection_coordinates)) != len(actual_selection_coordinates)
        or set(actual_selection_coordinates) != expected_selection_coordinates
    ):
        raise TrendlineStochasticNullComparisonError(
            "stochastic selections do not cover exact baseline/repetition/event product"
        )
    if tuple(row.to_dict() for row in bundle.stochastic_selections) != tuple(
        row.to_dict() for row in expected_selections
    ):
        raise TrendlineStochasticNullComparisonError(
            "stochastic selections differ from causal draw reconstruction"
        )
    expected_outcomes = build_stochastic_null_outcomes(
        expected_selections,
        replay,
        interaction_bundle.interaction_spec,
    )
    expected_outcome_coordinates = {
        (outcome.interaction_event_id, outcome.horizon_bars)
        for outcome in expected_outcomes
    }
    actual_outcome_coordinates = [
        (outcome.interaction_event_id, outcome.horizon_bars)
        for outcome in bundle.null_outcomes
    ]
    if (
        len(set(actual_outcome_coordinates)) != len(actual_outcome_coordinates)
        or set(actual_outcome_coordinates) != expected_outcome_coordinates
    ):
        raise TrendlineStochasticNullComparisonError(
            "stochastic outcomes do not cover exact selection/horizon product"
        )
    if tuple(row.to_dict() for row in bundle.null_outcomes) != tuple(
        row.to_dict() for row in expected_outcomes
    ):
        raise TrendlineStochasticNullComparisonError(
            "stochastic outcomes differ from replay OHLC"
        )
    expected_comparisons = _build_repetition_comparisons(
        interaction_bundle,
        specs,
        expected_selections,
        expected_outcomes,
        interaction_bundle.interaction_spec,
    )
    if tuple(row.to_dict() for row in bundle.repetition_comparisons) != tuple(
        row.to_dict() for row in expected_comparisons
    ):
        raise TrendlineStochasticNullComparisonError(
            "stochastic repetition comparisons differ"
        )
    expected_distributions = _build_distribution_summaries(
        specs,
        expected_comparisons,
        _timeframes(expected_events),
        interaction_bundle.interaction_spec,
    )
    if tuple(row.to_dict() for row in bundle.distribution_summaries) != tuple(
        row.to_dict() for row in expected_distributions
    ):
        raise TrendlineStochasticNullComparisonError(
            "stochastic distribution summaries differ"
        )
    expected_bundle_id = canonical_hash(
        _bundle_payload(bundle),
        semantics_version=STOCHASTIC_NULL_BUNDLE_SEMANTICS_VERSION,
    )
    if bundle.stochastic_null_comparison_bundle_id != expected_bundle_id:
        raise TrendlineStochasticNullComparisonError(
            "stochastic bundle identity differs"
        )


__all__ = [
    "STOCHASTIC_DRAW_SEMANTICS_VERSION",
    "STOCHASTIC_SELECTION_SEMANTICS_VERSION",
    "STOCHASTIC_REPETITION_COMPARISON_SEMANTICS_VERSION",
    "STOCHASTIC_DISTRIBUTION_SUMMARY_SEMANTICS_VERSION",
    "STOCHASTIC_NULL_BUNDLE_SEMANTICS_VERSION",
    "STOCHASTIC_NULL_KINDS",
    "STOCHASTIC_SELECTION_REASONS",
    "STOCHASTIC_DISTRIBUTION_METRICS",
    "STOCHASTIC_QUANTILE_PROBABILITIES",
    "TrendlineStochasticNullComparisonError",
    "TrendlineStochasticNullSelection",
    "TrendlineNullRepetitionComparison",
    "TrendlineNullDistributionSummary",
    "TrendlineStochasticNullComparisonBundle",
    "derive_stochastic_draw_id",
    "transport_density_matched_geometry",
    "build_stochastic_null_selections",
    "build_stochastic_null_outcomes",
    "build_stochastic_null_comparison_bundle",
    "validate_stochastic_null_comparison_bundle",
]
