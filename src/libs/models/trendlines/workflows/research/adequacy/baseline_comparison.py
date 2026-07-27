"""Paired deterministic naive-baseline comparisons for adequacy research."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from numbers import Real
from typing import Any

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
from .contracts import (
    TrendlineAdequacyStudyConfig,
)
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


BASELINE_SELECTION_SEMANTICS_VERSION = (
    "trendlines.adequacy-baseline-selection.v1"
)
BASELINE_COMPARISON_SUMMARY_SEMANTICS_VERSION = (
    "trendlines.adequacy-baseline-comparison-summary.v1"
)
BASELINE_COMPARISON_BUNDLE_SEMANTICS_VERSION = (
    "trendlines.adequacy-baseline-comparison-bundle.v1"
)
BASELINE_SELECTION_REASONS = (
    "available",
    "insufficient_same_role_pivots",
)
CONFIRMED_PIVOT_FINALITY = "confirmed_append_only"
DETERMINISTIC_BASELINE_KINDS = (
    TrendlineAdequacyBaselineKind.RECENT_EXTREMA,
    TrendlineAdequacyBaselineKind.HORIZONTAL_SUPPORT_RESISTANCE,
)
COMPARISON_DELTA_FIELDS = (
    "touch_rate",
    "rejection_rate",
    "confirmed_break_rate",
    "false_break_rate",
    "mean_penetration_atr",
    "mean_favourable_excursion_atr",
    "mean_adverse_excursion_atr",
)


class TrendlineBaselineComparisonError(ValueError):
    """Raised when paired baseline evidence is invalid or ambiguous."""


def _identity(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrendlineBaselineComparisonError(f"{name} must be non-empty")
    return value


def _sha256(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise TrendlineBaselineComparisonError(
            f"{name} must be a lowercase SHA-256 identity"
        )
    return value


def _strict_int(value: Any, *, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise TrendlineBaselineComparisonError(
            f"{name} must be a non-boolean integer >= {minimum}"
        )
    return value


def _finite(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TrendlineBaselineComparisonError(f"{name} must be finite numeric")
    result = float(value)
    if not isfinite(result):
        raise TrendlineBaselineComparisonError(f"{name} must be finite numeric")
    return result


def _timestamp(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrendlineBaselineComparisonError(f"{name} must be non-empty text")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise TrendlineBaselineComparisonError(f"{name} must be ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TrendlineBaselineComparisonError(f"{name} must be timezone-aware")
    return value


def _optional_delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return float(left - right)


def _selection_payload(selection: "TrendlineBaselineSelection") -> dict[str, Any]:
    return {
        "baseline_id": selection.baseline_id,
        "baseline_name": selection.baseline_name,
        "baseline_kind": selection.baseline_kind.value,
        "model_event_id": selection.model_event_id,
        "timeframe": selection.timeframe,
        "role": selection.role,
        "selection_position": selection.selection_position,
        "selection_event_at": selection.selection_event_at,
        "selection_available_at": selection.selection_available_at,
        "selection_atr": selection.selection_atr,
        "available": selection.available,
        "reason": selection.reason,
        "selected_pivot_positions": list(selection.selected_pivot_positions),
        "selected_pivot_prices": list(selection.selected_pivot_prices),
        "selected_pivot_finality": selection.selected_pivot_finality,
        "replay_point_id": selection.replay_point_id,
        "content_id": selection.content_id,
        "source_id": selection.source_id,
        "checkpoint_id": selection.checkpoint_id,
        "frozen_slope": selection.frozen_slope,
        "frozen_intercept": selection.frozen_intercept,
        "semantics_version": BASELINE_SELECTION_SEMANTICS_VERSION,
    }


@dataclass(frozen=True)
class TrendlineBaselineSelection:
    """One deterministic baseline attempt paired to one model event."""

    baseline_id: str
    baseline_name: str
    baseline_kind: TrendlineAdequacyBaselineKind
    model_event_id: str
    timeframe: str
    role: str
    selection_position: int
    selection_event_at: str
    selection_available_at: str
    selection_atr: float
    available: bool
    reason: str
    selected_pivot_positions: tuple[int, ...]
    selected_pivot_prices: tuple[float, ...]
    selected_pivot_finality: str | None
    replay_point_id: str
    content_id: str
    source_id: str
    checkpoint_id: str
    frozen_slope: float | None
    frozen_intercept: float | None
    baseline_selection_id: str = ""

    def __post_init__(self) -> None:
        _sha256(self.baseline_id, name="baseline selection baseline_id")
        _identity(self.baseline_name, name="baseline selection baseline_name")
        if self.baseline_kind not in DETERMINISTIC_BASELINE_KINDS:
            raise TrendlineBaselineComparisonError(
                "baseline selection kind is not an approved deterministic baseline"
            )
        _sha256(self.model_event_id, name="baseline selection model_event_id")
        _identity(self.timeframe, name="baseline selection timeframe")
        if self.role not in INTERACTION_ROLES:
            raise TrendlineBaselineComparisonError("baseline selection role is invalid")
        _strict_int(self.selection_position, name="baseline selection position")
        _timestamp(self.selection_event_at, name="baseline selection event_at")
        _timestamp(self.selection_available_at, name="baseline selection available_at")
        _finite(self.selection_atr, name="baseline selection ATR")
        if self.selection_atr <= 0:
            raise TrendlineBaselineComparisonError("baseline selection ATR must be positive")
        if not isinstance(self.available, bool):
            raise TrendlineBaselineComparisonError("baseline selection available must be bool")
        if self.reason not in BASELINE_SELECTION_REASONS:
            raise TrendlineBaselineComparisonError("baseline selection reason is invalid")
        positions = tuple(
            _strict_int(value, name="selected pivot position")
            for value in self.selected_pivot_positions
        )
        prices = tuple(
            _finite(value, name="selected pivot price")
            for value in self.selected_pivot_prices
        )
        if len(positions) != len(prices):
            raise TrendlineBaselineComparisonError(
                "selected pivot positions/prices must have equal length"
            )
        if tuple(sorted(set(positions))) != positions:
            raise TrendlineBaselineComparisonError(
                "selected pivot positions must be ordered and unique"
            )
        if any(value >= self.selection_position for value in positions):
            raise TrendlineBaselineComparisonError(
                "selected pivots must precede selection position"
            )
        if self.available:
            expected_count = (
                2
                if self.baseline_kind is TrendlineAdequacyBaselineKind.RECENT_EXTREMA
                else 1
            )
            if self.reason != "available" or len(positions) != expected_count:
                raise TrendlineBaselineComparisonError(
                    "available baseline selection has invalid pivot count/reason"
                )
            if self.selected_pivot_finality != CONFIRMED_PIVOT_FINALITY:
                raise TrendlineBaselineComparisonError(
                    "available baseline selection must use confirmed pivots"
                )
            slope = _finite(self.frozen_slope, name="baseline frozen slope")
            intercept = _finite(self.frozen_intercept, name="baseline frozen intercept")
            object.__setattr__(self, "frozen_slope", slope)
            object.__setattr__(self, "frozen_intercept", intercept)
        else:
            if self.reason != "insufficient_same_role_pivots":
                raise TrendlineBaselineComparisonError(
                    "baseline abstention reason is invalid"
                )
            if positions or self.selected_pivot_finality is not None:
                raise TrendlineBaselineComparisonError(
                    "baseline abstention cannot retain selected pivots"
                )
            if self.frozen_slope is not None or self.frozen_intercept is not None:
                raise TrendlineBaselineComparisonError(
                    "baseline abstention cannot retain geometry"
                )
        for name, value in (
            ("replay_point_id", self.replay_point_id),
            ("content_id", self.content_id),
            ("source_id", self.source_id),
            ("checkpoint_id", self.checkpoint_id),
        ):
            _sha256(value, name=f"baseline selection {name}")
        expected = canonical_hash(
            _selection_payload(self),
            semantics_version=BASELINE_SELECTION_SEMANTICS_VERSION,
        )
        if self.baseline_selection_id and self.baseline_selection_id != expected:
            raise TrendlineBaselineComparisonError(
                "baseline_selection_id does not match selection content"
            )
        object.__setattr__(self, "selected_pivot_positions", positions)
        object.__setattr__(self, "selected_pivot_prices", prices)
        object.__setattr__(self, "baseline_selection_id", expected)

    def to_dict(self) -> dict[str, Any]:
        return {"baseline_selection_id": self.baseline_selection_id, **_selection_payload(self)}


def _comparison_summary_payload(
    summary: "TrendlineBaselineComparisonSummary",
) -> dict[str, Any]:
    return {
        "baseline_id": summary.baseline_id,
        "baseline_name": summary.baseline_name,
        "baseline_kind": summary.baseline_kind.value,
        "timeframe": summary.timeframe,
        "role": summary.role,
        "horizon_bars": summary.horizon_bars,
        "model_summary_id": summary.model_summary_id,
        "baseline_summary_id": summary.baseline_summary_id,
        "model_event_count": summary.model_event_count,
        "baseline_available_count": summary.baseline_available_count,
        "baseline_abstention_count": summary.baseline_abstention_count,
        "matched_eligible_event_count": summary.matched_eligible_event_count,
        "right_censored_pair_count": summary.right_censored_pair_count,
        "baseline_coverage_rate": summary.baseline_coverage_rate,
        "model_summary": summary.model_summary.to_dict(),
        "baseline_summary": summary.baseline_summary.to_dict(),
        "touch_rate_delta": summary.touch_rate_delta,
        "rejection_rate_delta": summary.rejection_rate_delta,
        "confirmed_break_rate_delta": summary.confirmed_break_rate_delta,
        "false_break_rate_delta": summary.false_break_rate_delta,
        "mean_penetration_atr_delta": summary.mean_penetration_atr_delta,
        "mean_favourable_excursion_atr_delta": summary.mean_favourable_excursion_atr_delta,
        "mean_adverse_excursion_atr_delta": summary.mean_adverse_excursion_atr_delta,
        "semantics_version": BASELINE_COMPARISON_SUMMARY_SEMANTICS_VERSION,
    }


@dataclass(frozen=True)
class TrendlineBaselineComparisonSummary:
    """Auditable model-minus-baseline statistics for one coordinate."""

    baseline_id: str
    baseline_name: str
    baseline_kind: TrendlineAdequacyBaselineKind
    timeframe: str
    role: str
    horizon_bars: int
    model_summary_id: str
    baseline_summary_id: str
    model_event_count: int
    baseline_available_count: int
    baseline_abstention_count: int
    matched_eligible_event_count: int
    right_censored_pair_count: int
    baseline_coverage_rate: float | None
    model_summary: TrendlineInteractionSummary
    baseline_summary: TrendlineInteractionSummary
    touch_rate_delta: float | None
    rejection_rate_delta: float | None
    confirmed_break_rate_delta: float | None
    false_break_rate_delta: float | None
    mean_penetration_atr_delta: float | None
    mean_favourable_excursion_atr_delta: float | None
    mean_adverse_excursion_atr_delta: float | None
    comparison_summary_id: str = ""

    def __post_init__(self) -> None:
        _sha256(self.baseline_id, name="comparison baseline_id")
        _identity(self.baseline_name, name="comparison baseline_name")
        if self.baseline_kind not in DETERMINISTIC_BASELINE_KINDS:
            raise TrendlineBaselineComparisonError("comparison baseline kind is invalid")
        _identity(self.timeframe, name="comparison timeframe")
        if self.role not in INTERACTION_ROLES:
            raise TrendlineBaselineComparisonError("comparison role is invalid")
        horizon = _strict_int(self.horizon_bars, name="comparison horizon", minimum=1)
        _sha256(self.model_summary_id, name="comparison model_summary_id")
        _sha256(self.baseline_summary_id, name="comparison baseline_summary_id")
        counts = {}
        for name, value in (
            ("model_event_count", self.model_event_count),
            ("baseline_available_count", self.baseline_available_count),
            ("baseline_abstention_count", self.baseline_abstention_count),
            ("matched_eligible_event_count", self.matched_eligible_event_count),
            ("right_censored_pair_count", self.right_censored_pair_count),
        ):
            counts[name] = _strict_int(value, name=f"comparison {name}")
        if counts["baseline_available_count"] + counts["baseline_abstention_count"] != counts["model_event_count"]:
            raise TrendlineBaselineComparisonError(
                "baseline available plus abstention counts must equal model events"
            )
        if not isinstance(self.model_summary, TrendlineInteractionSummary):
            raise TrendlineBaselineComparisonError("model summary must be typed")
        if not isinstance(self.baseline_summary, TrendlineInteractionSummary):
            raise TrendlineBaselineComparisonError("baseline summary must be typed")
        for value, name in (
            (self.model_summary, "model summary"),
            (self.baseline_summary, "baseline summary"),
        ):
            if (
                value.timeframe != self.timeframe
                or value.role != self.role
                or value.horizon_bars != horizon
            ):
                raise TrendlineBaselineComparisonError(
                    f"{name} coordinate differs from comparison"
                )
        if self.model_summary_id != self.model_summary.summary_id:
            raise TrendlineBaselineComparisonError("model summary ID differs")
        if self.baseline_summary_id != self.baseline_summary.summary_id:
            raise TrendlineBaselineComparisonError("baseline summary ID differs")
        if self.model_summary.event_count != counts["baseline_available_count"]:
            raise TrendlineBaselineComparisonError(
                "model summary event count differs from baseline availability"
            )
        if self.baseline_summary.event_count != counts["baseline_available_count"]:
            raise TrendlineBaselineComparisonError(
                "baseline summary event count differs from baseline availability"
            )
        if self.model_summary.eligible_event_count != counts["matched_eligible_event_count"]:
            raise TrendlineBaselineComparisonError(
                "matched eligible count differs from model summary"
            )
        if self.model_summary.right_censored_count != counts["right_censored_pair_count"]:
            raise TrendlineBaselineComparisonError(
                "right-censored pair count differs from model summary"
            )
        if self.baseline_summary.right_censored_count != counts["right_censored_pair_count"]:
            raise TrendlineBaselineComparisonError(
                "right-censored pair count differs from baseline summary"
            )
        expected_coverage = (
            counts["baseline_available_count"] / counts["model_event_count"]
            if counts["model_event_count"]
            else None
        )
        if self.baseline_coverage_rate != expected_coverage:
            raise TrendlineBaselineComparisonError(
                "baseline coverage rate is not derived from counts"
            )
        for field in COMPARISON_DELTA_FIELDS:
            value = getattr(self, f"{field}_delta")
            if value is not None:
                _finite(value, name=f"comparison {field}_delta")
        object.__setattr__(self, "horizon_bars", horizon)
        for name, value in counts.items():
            object.__setattr__(self, name, value)
        expected = canonical_hash(
            _comparison_summary_payload(self),
            semantics_version=BASELINE_COMPARISON_SUMMARY_SEMANTICS_VERSION,
        )
        if self.comparison_summary_id and self.comparison_summary_id != expected:
            raise TrendlineBaselineComparisonError(
                "comparison_summary_id does not match summary content"
            )
        object.__setattr__(self, "comparison_summary_id", expected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparison_summary_id": self.comparison_summary_id,
            **_comparison_summary_payload(self),
        }


def _summary_bindings_payload(
    values: tuple[tuple[str, TrendlineInteractionSummary], ...],
) -> list[dict[str, Any]]:
    return [
        {"baseline_id": baseline_id, "summary": summary.to_dict()}
        for baseline_id, summary in values
    ]


def _bundle_payload(
    bundle: "TrendlineDeterministicBaselineComparisonBundle",
) -> dict[str, Any]:
    return {
        "dataset_id": bundle.dataset_id,
        "replay_id": bundle.replay_id,
        "cohort_id": bundle.cohort_id,
        "study_config_id": bundle.study_config_id,
        "structural_stability_bundle_id": bundle.structural_stability_bundle_id,
        "interaction_utility_bundle_id": bundle.interaction_utility_bundle_id,
        "interaction_spec": bundle.interaction_spec.to_dict(),
        "interaction_spec_id": bundle.interaction_spec_id,
        "baseline_specs": [spec.to_dict() for spec in bundle.baseline_specs],
        "model_event_ids": list(bundle.model_event_ids),
        "baseline_selections": [row.to_dict() for row in bundle.baseline_selections],
        "baseline_outcomes": [row.to_dict() for row in bundle.baseline_outcomes],
        "model_summaries": _summary_bindings_payload(bundle.model_summaries),
        "baseline_summaries": _summary_bindings_payload(bundle.baseline_summaries),
        "comparison_summaries": [row.to_dict() for row in bundle.comparison_summaries],
        "semantics_version": BASELINE_COMPARISON_BUNDLE_SEMANTICS_VERSION,
    }


@dataclass(frozen=True)
class TrendlineDeterministicBaselineComparisonBundle:
    """Content-addressed paired deterministic baseline evidence."""

    dataset_id: str
    replay_id: str
    cohort_id: str
    study_config_id: str
    structural_stability_bundle_id: str
    interaction_utility_bundle_id: str
    interaction_spec: TrendlineInteractionUtilitySpec
    baseline_specs: tuple[TrendlineAdequacyBaselineSpec, ...]
    model_event_ids: tuple[str, ...]
    baseline_selections: tuple[TrendlineBaselineSelection, ...]
    baseline_outcomes: tuple[TrendlineInteractionOutcome, ...]
    model_summaries: tuple[tuple[str, TrendlineInteractionSummary], ...]
    baseline_summaries: tuple[tuple[str, TrendlineInteractionSummary], ...]
    comparison_summaries: tuple[TrendlineBaselineComparisonSummary, ...]
    baseline_comparison_bundle_id: str = ""

    def __post_init__(self) -> None:
        for name, value in (
            ("dataset_id", self.dataset_id),
            ("replay_id", self.replay_id),
            ("cohort_id", self.cohort_id),
            ("study_config_id", self.study_config_id),
            ("structural_stability_bundle_id", self.structural_stability_bundle_id),
            ("interaction_utility_bundle_id", self.interaction_utility_bundle_id),
        ):
            _sha256(value, name=f"comparison bundle {name}")
        if not isinstance(self.interaction_spec, TrendlineInteractionUtilitySpec):
            raise TrendlineBaselineComparisonError("comparison interaction spec is invalid")
        specs = tuple(self.baseline_specs)
        if not all(isinstance(value, TrendlineAdequacyBaselineSpec) for value in specs):
            raise TrendlineBaselineComparisonError("comparison baseline specs are untyped")
        if not isinstance(self.model_event_ids, tuple):
            raise TrendlineBaselineComparisonError("model event IDs must be immutable")
        for value in self.model_event_ids:
            _sha256(value, name="model event ID")
        for values, row_type, name in (
            (self.baseline_selections, TrendlineBaselineSelection, "selections"),
            (self.baseline_outcomes, TrendlineInteractionOutcome, "outcomes"),
            (self.comparison_summaries, TrendlineBaselineComparisonSummary, "summaries"),
        ):
            if not isinstance(values, tuple) or not all(isinstance(value, row_type) for value in values):
                raise TrendlineBaselineComparisonError(f"comparison {name} are untyped")
        for bindings, name in (
            (self.model_summaries, "model summaries"),
            (self.baseline_summaries, "baseline summaries"),
        ):
            if not isinstance(bindings, tuple):
                raise TrendlineBaselineComparisonError(f"comparison {name} must be immutable")
            for baseline_id, summary in bindings:
                _sha256(baseline_id, name=f"{name} baseline ID")
                if not isinstance(summary, TrendlineInteractionSummary):
                    raise TrendlineBaselineComparisonError(f"comparison {name} are untyped")
        expected = canonical_hash(
            _bundle_payload(self),
            semantics_version=BASELINE_COMPARISON_BUNDLE_SEMANTICS_VERSION,
        )
        if self.baseline_comparison_bundle_id and self.baseline_comparison_bundle_id != expected:
            raise TrendlineBaselineComparisonError(
                "baseline comparison bundle ID does not match content"
            )
        object.__setattr__(self, "baseline_specs", specs)
        object.__setattr__(self, "baseline_comparison_bundle_id", expected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_comparison_bundle_id": self.baseline_comparison_bundle_id,
            **_bundle_payload(self),
        }

    @property
    def interaction_spec_id(self) -> str:
        return self.interaction_spec.interaction_spec_id


def _approved_specs(
    study_config: TrendlineAdequacyStudyConfig,
) -> tuple[TrendlineAdequacyBaselineSpec, ...]:
    specs = tuple(study_config.baseline_specs)
    if tuple(spec.kind for spec in specs) != DETERMINISTIC_BASELINE_KINDS:
        raise TrendlineBaselineComparisonError(
            "study configuration must contain exactly the two frozen deterministic baselines"
        )
    for spec in specs:
        if spec.repetitions != 1 or spec.seed is not None:
            raise TrendlineBaselineComparisonError(
                "D4A baselines must be deterministic single-attempt specs"
            )
    return specs


def _validate_pivot_row(
    row: ReplayPivotRow,
    event: TrendlineInteractionEvent,
    point: Any,
) -> None:
    if row.timeframe != event.timeframe or row.position != event.selection_position:
        raise TrendlineBaselineComparisonError("pivot row coordinate differs from model event")
    if row.extractor_finality != CONFIRMED_PIVOT_FINALITY:
        raise TrendlineBaselineComparisonError("pivot row is not confirmed append-only")
    if row.pivot_role not in {"high", "low"}:
        raise TrendlineBaselineComparisonError("pivot role is invalid")
    if not 0 <= row.bar_position < event.selection_position:
        raise TrendlineBaselineComparisonError("pivot position is not causally prior")
    for name, actual, expected in (
        ("replay_point_id", row.replay_point_id, event.replay_point_id),
        ("content_id", row.content_id, event.content_id),
        ("source_id", row.source_id, event.source_id),
        ("checkpoint_id", row.checkpoint_id, event.checkpoint_id),
        ("boundary_snapshot_id", row.boundary_snapshot_id, point.boundary_identity.snapshot_id),
        ("boundary_revision_id", row.boundary_revision_id, point.boundary_identity.revision_id),
    ):
        if actual != expected:
            raise TrendlineBaselineComparisonError(
                f"pivot {name} differs from model event"
            )
    _finite(row.price, name="pivot price")
    _timestamp(row.event_at, name="pivot event_at")
    if row.source_id != point.prefix_source_ref.source_id:
        raise TrendlineBaselineComparisonError("pivot source differs from replay point")


def _selection_from_pivots(
    spec: TrendlineAdequacyBaselineSpec,
    event: TrendlineInteractionEvent,
    point: Any,
    pivots: Sequence[ReplayPivotRow],
) -> TrendlineBaselineSelection:
    expected_role = "low" if event.role == "support" else "high"
    role_pivots = tuple(
        sorted(
            (row for row in pivots if row.pivot_role == expected_role),
            key=lambda row: row.bar_position,
        )
    )
    required = 2 if spec.kind is TrendlineAdequacyBaselineKind.RECENT_EXTREMA else 1
    selected = role_pivots[-required:] if len(role_pivots) >= required else ()
    available = bool(selected)
    slope: float | None = None
    intercept: float | None = None
    positions: tuple[int, ...] = ()
    prices: tuple[float, ...] = ()
    finality: str | None = None
    reason = "available" if available else "insufficient_same_role_pivots"
    if available:
        positions = tuple(row.bar_position for row in selected)
        prices = tuple(float(row.price) for row in selected)
        finality = selected[0].extractor_finality
        if spec.kind is TrendlineAdequacyBaselineKind.RECENT_EXTREMA:
            x1, x2 = positions
            y1, y2 = prices
            if x1 >= x2:
                raise TrendlineBaselineComparisonError("recent extrema pivot positions are unordered")
            slope = (y2 - y1) / (x2 - x1)
            intercept = y2 - slope * x2
        else:
            slope = 0.0
            intercept = prices[0]
    return TrendlineBaselineSelection(
        baseline_id=spec.baseline_id,
        baseline_name=spec.name,
        baseline_kind=spec.kind,
        model_event_id=event.event_id,
        timeframe=event.timeframe,
        role=event.role,
        selection_position=event.selection_position,
        selection_event_at=event.selection_event_at,
        selection_available_at=event.selection_available_at,
        selection_atr=event.selection_atr,
        available=available,
        reason=reason,
        selected_pivot_positions=positions,
        selected_pivot_prices=prices,
        selected_pivot_finality=finality,
        replay_point_id=event.replay_point_id,
        content_id=event.content_id,
        source_id=event.source_id,
        checkpoint_id=event.checkpoint_id,
        frozen_slope=slope,
        frozen_intercept=intercept,
    )


def build_baseline_selections(
    prepared: PreparedTrendlineResearchRun,
    replay: PreparedTrendlineResearchReplay,
    study_config: TrendlineAdequacyStudyConfig,
    structural_stability_bundle: TrendlineStructuralStabilityBundle,
    interaction_bundle: TrendlineInteractionUtilityBundle,
) -> tuple[TrendlineBaselineSelection, ...]:
    """Build one causal pivot selection attempt per model event and baseline."""

    if replay.prepared is not prepared:
        raise TrendlineBaselineComparisonError("prepared run does not belong to replay")
    if structural_stability_bundle.study_config_id != study_config.study_config_id:
        raise TrendlineBaselineComparisonError("D2 study config differs from supplied study config")
    specs = _approved_specs(study_config)
    validate_interaction_utility_bundle(
        interaction_bundle,
        structural_stability_bundle=structural_stability_bundle,
        replay=replay,
    )
    if interaction_bundle.interaction_spec_id != interaction_bundle.interaction_spec.interaction_spec_id:
        raise TrendlineBaselineComparisonError("interaction spec identity differs")
    result: list[TrendlineBaselineSelection] = []
    pivot_cache: dict[tuple[str, int], tuple[ReplayPivotRow, ...]] = {}
    for spec in specs:
        for event in interaction_bundle.events:
            point = replay.output_at(event.timeframe, event.selection_position)
            validate_replay_point_integrity(point)
            if point.replay_point_id != event.replay_point_id or point.content_id != event.content_id:
                raise TrendlineBaselineComparisonError("model event does not bind replay point")
            key = (event.timeframe, event.selection_position)
            pivots = pivot_cache.get(key)
            if pivots is None:
                pivots = inspect_replay_pivots(
                    prepared,
                    replay,
                    timeframe=event.timeframe,
                    position=event.selection_position,
                )
                for pivot in pivots:
                    _validate_pivot_row(pivot, event, point)
                pivot_cache[key] = pivots
            result.append(_selection_from_pivots(spec, event, point, pivots))
    return tuple(result)


def build_baseline_outcomes(
    selections: Iterable[TrendlineBaselineSelection],
    replay: PreparedTrendlineResearchReplay,
    interaction_spec: TrendlineInteractionUtilitySpec,
) -> tuple[TrendlineInteractionOutcome, ...]:
    """Measure exact D3 outcomes for each available frozen baseline geometry."""

    result: list[TrendlineInteractionOutcome] = []
    for selection in selections:
        if not selection.available:
            continue
        frame = replay.prepared.dataset.frames[selection.timeframe]
        result.extend(
            measure_frozen_geometry_outcomes(
                interaction_event_id=selection.baseline_selection_id,
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


def _summary_for_bindings(
    bindings: Mapping[str, tuple[str, str]],
    outcomes: Sequence[TrendlineInteractionOutcome],
    timeframes: Sequence[str],
    interaction_spec: TrendlineInteractionUtilitySpec,
) -> tuple[TrendlineInteractionSummary, ...]:
    return build_interaction_summaries(bindings, outcomes, timeframes, interaction_spec)


def _summary_map(
    bindings: Sequence[tuple[str, TrendlineInteractionSummary]],
) -> dict[tuple[str, str, str, int], TrendlineInteractionSummary]:
    result: dict[tuple[str, str, str, int], TrendlineInteractionSummary] = {}
    for baseline_id, summary in bindings:
        key = (baseline_id, summary.timeframe, summary.role, summary.horizon_bars)
        if key in result:
            raise TrendlineBaselineComparisonError("duplicate summary coordinate")
        result[key] = summary
    return result


def _build_comparison_summaries(
    interaction_bundle: TrendlineInteractionUtilityBundle,
    specs: Sequence[TrendlineAdequacyBaselineSpec],
    selections: Sequence[TrendlineBaselineSelection],
    model_summaries: Sequence[tuple[str, TrendlineInteractionSummary]],
    baseline_summaries: Sequence[tuple[str, TrendlineInteractionSummary]],
) -> tuple[TrendlineBaselineComparisonSummary, ...]:
    model_events = {
        event.event_id: event for event in interaction_bundle.events
    }
    model_summary_map = _summary_map(model_summaries)
    baseline_summary_map = _summary_map(baseline_summaries)
    result: list[TrendlineBaselineComparisonSummary] = []
    for spec in specs:
        spec_selections = tuple(
            value for value in selections if value.baseline_id == spec.baseline_id
        )
        for timeframe in tuple(dict.fromkeys(event.timeframe for event in interaction_bundle.events)):
            for role in INTERACTION_ROLES:
                model_event_count = sum(
                    event.timeframe == timeframe and event.role == role
                    for event in model_events.values()
                )
                available_count = sum(
                    value.available
                    and value.timeframe == timeframe
                    and value.role == role
                    for value in spec_selections
                )
                abstention_count = model_event_count - available_count
                for horizon in interaction_bundle.interaction_spec.evaluation_horizons_bars:
                    key = (spec.baseline_id, timeframe, role, horizon)
                    model_summary = model_summary_map[(key)]
                    baseline_summary = baseline_summary_map[(key)]
                    result.append(
                        TrendlineBaselineComparisonSummary(
                            baseline_id=spec.baseline_id,
                            baseline_name=spec.name,
                            baseline_kind=spec.kind,
                            timeframe=timeframe,
                            role=role,
                            horizon_bars=horizon,
                            model_summary_id=model_summary.summary_id,
                            baseline_summary_id=baseline_summary.summary_id,
                            model_event_count=model_event_count,
                            baseline_available_count=available_count,
                            baseline_abstention_count=abstention_count,
                            matched_eligible_event_count=model_summary.eligible_event_count,
                            right_censored_pair_count=model_summary.right_censored_count,
                            baseline_coverage_rate=(
                                available_count / model_event_count
                                if model_event_count
                                else None
                            ),
                            model_summary=model_summary,
                            baseline_summary=baseline_summary,
                            touch_rate_delta=_optional_delta(
                                model_summary.touch_rate,
                                baseline_summary.touch_rate,
                            ),
                            rejection_rate_delta=_optional_delta(
                                model_summary.rejection_rate,
                                baseline_summary.rejection_rate,
                            ),
                            confirmed_break_rate_delta=_optional_delta(
                                model_summary.confirmed_break_rate,
                                baseline_summary.confirmed_break_rate,
                            ),
                            false_break_rate_delta=_optional_delta(
                                model_summary.false_break_rate,
                                baseline_summary.false_break_rate,
                            ),
                            mean_penetration_atr_delta=_optional_delta(
                                model_summary.mean_penetration_atr,
                                baseline_summary.mean_penetration_atr,
                            ),
                            mean_favourable_excursion_atr_delta=_optional_delta(
                                model_summary.mean_favourable_excursion_atr,
                                baseline_summary.mean_favourable_excursion_atr,
                            ),
                            mean_adverse_excursion_atr_delta=_optional_delta(
                                model_summary.mean_adverse_excursion_atr,
                                baseline_summary.mean_adverse_excursion_atr,
                            ),
                        )
                    )
    return tuple(result)


def _build_summary_bindings(
    specs: Sequence[TrendlineAdequacyBaselineSpec],
    selections: Sequence[TrendlineBaselineSelection],
    interaction_bundle: TrendlineInteractionUtilityBundle,
    outcomes: Sequence[TrendlineInteractionOutcome],
    interaction_spec: TrendlineInteractionUtilitySpec,
) -> tuple[
    tuple[tuple[str, TrendlineInteractionSummary], ...],
    tuple[tuple[str, TrendlineInteractionSummary], ...],
]:
    timeframes = tuple(dict.fromkeys(event.timeframe for event in interaction_bundle.events))
    model_result: list[tuple[str, TrendlineInteractionSummary]] = []
    baseline_result: list[tuple[str, TrendlineInteractionSummary]] = []
    for spec in specs:
        available = tuple(
            value
            for value in selections
            if value.baseline_id == spec.baseline_id and value.available
        )
        model_bindings = {
            value.model_event_id: (value.timeframe, value.role)
            for value in available
        }
        baseline_bindings = {
            value.baseline_selection_id: (value.timeframe, value.role)
            for value in available
        }
        model_outcomes = tuple(
            value
            for value in interaction_bundle.outcomes
            if value.interaction_event_id in model_bindings
        )
        baseline_outcomes = tuple(
            value
            for value in outcomes
            if value.interaction_event_id in baseline_bindings
        )
        model_result.extend(
            (spec.baseline_id, summary)
            for summary in _summary_for_bindings(
                model_bindings,
                model_outcomes,
                timeframes,
                interaction_spec,
            )
        )
        baseline_result.extend(
            (spec.baseline_id, summary)
            for summary in _summary_for_bindings(
                baseline_bindings,
                baseline_outcomes,
                timeframes,
                interaction_spec,
            )
        )
    return tuple(model_result), tuple(baseline_result)


def build_baseline_comparison_bundle(
    prepared: PreparedTrendlineResearchRun,
    replay: PreparedTrendlineResearchReplay,
    study_config: TrendlineAdequacyStudyConfig,
    structural_stability_bundle: TrendlineStructuralStabilityBundle,
    interaction_bundle: TrendlineInteractionUtilityBundle,
) -> TrendlineDeterministicBaselineComparisonBundle:
    """Build paired deterministic baselines at the committed D3 events."""

    if replay.prepared is not prepared:
        raise TrendlineBaselineComparisonError("prepared run does not belong to replay")
    if structural_stability_bundle.study_config_id != study_config.study_config_id:
        raise TrendlineBaselineComparisonError("D2 study config differs from supplied study config")
    specs = _approved_specs(study_config)
    selections = build_baseline_selections(
        prepared,
        replay,
        study_config,
        structural_stability_bundle,
        interaction_bundle,
    )
    outcomes = build_baseline_outcomes(
        selections,
        replay,
        interaction_bundle.interaction_spec,
    )
    model_summaries, baseline_summaries = _build_summary_bindings(
        specs,
        selections,
        interaction_bundle,
        outcomes,
        interaction_bundle.interaction_spec,
    )
    bundle = TrendlineDeterministicBaselineComparisonBundle(
        dataset_id=replay.dataset_id,
        replay_id=replay.replay_id,
        cohort_id=structural_stability_bundle.cohort_id,
        study_config_id=structural_stability_bundle.study_config_id,
        structural_stability_bundle_id=structural_stability_bundle.structural_stability_bundle_id,
        interaction_utility_bundle_id=interaction_bundle.interaction_utility_bundle_id,
        interaction_spec=interaction_bundle.interaction_spec,
        baseline_specs=specs,
        model_event_ids=tuple(event.event_id for event in interaction_bundle.events),
        baseline_selections=selections,
        baseline_outcomes=outcomes,
        model_summaries=model_summaries,
        baseline_summaries=baseline_summaries,
        comparison_summaries=_build_comparison_summaries(
            interaction_bundle,
            specs,
            selections,
            model_summaries,
            baseline_summaries,
        ),
    )
    validate_baseline_comparison_bundle(
        bundle,
        prepared=prepared,
        replay=replay,
        structural_stability_bundle=structural_stability_bundle,
        interaction_bundle=interaction_bundle,
        study_config=study_config,
    )
    return bundle


def _validate_structural_states_against_replay(
    structural_stability_bundle: TrendlineStructuralStabilityBundle,
    replay: PreparedTrendlineResearchReplay,
) -> None:
    for state in structural_stability_bundle.state_rows:
        point = replay.output_at(state.timeframe, state.position)
        validate_replay_point_integrity(point)
        boundary_identity = point.boundary_identity
        expected = (
            (state.timeframe, point.timeframe),
            (state.position, point.position),
            (state.event_at, point.event_at.isoformat()),
            (state.available_at, point.available_at.isoformat()),
            (state.replay_point_id, point.replay_point_id),
            (state.content_id, point.content_id),
            (state.source_id, point.prefix_source_ref.source_id),
            (state.checkpoint_id, boundary_identity.checkpoint.checkpoint_id),
            (state.boundary_snapshot_id, boundary_identity.snapshot_id),
            (state.boundary_revision_id, boundary_identity.revision_id),
        )
        if any(left != right for left, right in expected):
            raise TrendlineBaselineComparisonError(
                "structural state does not bind its replay point"
            )


def validate_baseline_comparison_bundle(
    bundle: TrendlineDeterministicBaselineComparisonBundle,
    *,
    prepared: PreparedTrendlineResearchRun,
    replay: PreparedTrendlineResearchReplay,
    structural_stability_bundle: TrendlineStructuralStabilityBundle,
    interaction_bundle: TrendlineInteractionUtilityBundle,
    study_config: TrendlineAdequacyStudyConfig,
) -> None:
    """Recompute paired pivot selections, outcomes, summaries, and identity."""

    if not isinstance(bundle, TrendlineDeterministicBaselineComparisonBundle):
        raise TrendlineBaselineComparisonError("comparison bundle must be typed")
    if replay.prepared is not prepared:
        raise TrendlineBaselineComparisonError("prepared run does not belong to replay")
    if structural_stability_bundle.study_config_id != study_config.study_config_id:
        raise TrendlineBaselineComparisonError("D2 study config differs from supplied study config")
    validate_structural_stability_bundle(structural_stability_bundle)
    _validate_structural_states_against_replay(structural_stability_bundle, replay)
    validate_interaction_utility_bundle(
        interaction_bundle,
        structural_stability_bundle=structural_stability_bundle,
        replay=replay,
    )
    expected_ids = {
        "dataset_id": replay.dataset_id,
        "replay_id": replay.replay_id,
        "cohort_id": structural_stability_bundle.cohort_id,
        "study_config_id": structural_stability_bundle.study_config_id,
        "structural_stability_bundle_id": structural_stability_bundle.structural_stability_bundle_id,
        "interaction_utility_bundle_id": interaction_bundle.interaction_utility_bundle_id,
    }
    for name, expected in expected_ids.items():
        if getattr(bundle, name) != expected:
            raise TrendlineBaselineComparisonError(f"comparison {name} differs from source")
    if bundle.interaction_spec.to_dict() != interaction_bundle.interaction_spec.to_dict():
        raise TrendlineBaselineComparisonError("comparison interaction spec differs")
    if bundle.interaction_spec_id != bundle.interaction_spec.interaction_spec_id:
        raise TrendlineBaselineComparisonError("comparison interaction spec identity differs")
    if bundle.interaction_spec_id != interaction_bundle.interaction_spec_id:
        raise TrendlineBaselineComparisonError("comparison interaction spec differs from D3")
    specs = _approved_specs(study_config)
    if tuple(spec.to_dict() for spec in bundle.baseline_specs) != tuple(
        spec.to_dict() for spec in specs
    ):
        raise TrendlineBaselineComparisonError("comparison baseline specs differ")
    expected_event_ids = tuple(event.event_id for event in interaction_bundle.events)
    if bundle.model_event_ids != expected_event_ids:
        raise TrendlineBaselineComparisonError("comparison model event IDs differ")
    expected_selections = build_baseline_selections(
        prepared,
        replay,
        study_config,
        structural_stability_bundle,
        interaction_bundle,
    )
    if tuple(value.to_dict() for value in bundle.baseline_selections) != tuple(
        value.to_dict() for value in expected_selections
    ):
        raise TrendlineBaselineComparisonError("baseline selections differ from causal pivots")
    expected_outcomes = build_baseline_outcomes(
        expected_selections,
        replay,
        interaction_bundle.interaction_spec,
    )
    expected_coordinates = {
        (value.interaction_event_id, value.horizon_bars)
        for value in expected_outcomes
    }
    actual_coordinates = [
        (value.interaction_event_id, value.horizon_bars)
        for value in bundle.baseline_outcomes
    ]
    if len(set(actual_coordinates)) != len(actual_coordinates) or set(actual_coordinates) != expected_coordinates:
        raise TrendlineBaselineComparisonError(
            "baseline outcomes do not cover exact available selection/horizon coordinates"
        )
    if tuple(value.to_dict() for value in bundle.baseline_outcomes) != tuple(
        value.to_dict() for value in expected_outcomes
    ):
        raise TrendlineBaselineComparisonError("baseline outcomes differ from replay OHLC")
    expected_model_summaries, expected_baseline_summaries = _build_summary_bindings(
        specs,
        expected_selections,
        interaction_bundle,
        expected_outcomes,
        interaction_bundle.interaction_spec,
    )
    if tuple(
        (baseline_id, summary.to_dict())
        for baseline_id, summary in bundle.model_summaries
    ) != tuple(
        (baseline_id, summary.to_dict())
        for baseline_id, summary in expected_model_summaries
    ):
        raise TrendlineBaselineComparisonError("matched model summaries differ")
    if tuple(
        (baseline_id, summary.to_dict())
        for baseline_id, summary in bundle.baseline_summaries
    ) != tuple(
        (baseline_id, summary.to_dict())
        for baseline_id, summary in expected_baseline_summaries
    ):
        raise TrendlineBaselineComparisonError("baseline summaries differ")
    expected_comparisons = _build_comparison_summaries(
        interaction_bundle,
        specs,
        expected_selections,
        expected_model_summaries,
        expected_baseline_summaries,
    )
    if tuple(value.to_dict() for value in bundle.comparison_summaries) != tuple(
        value.to_dict() for value in expected_comparisons
    ):
        raise TrendlineBaselineComparisonError("comparison summaries differ")
    expected_bundle_id = canonical_hash(
        _bundle_payload(bundle),
        semantics_version=BASELINE_COMPARISON_BUNDLE_SEMANTICS_VERSION,
    )
    if bundle.baseline_comparison_bundle_id != expected_bundle_id:
        raise TrendlineBaselineComparisonError("comparison bundle identity differs")


__all__ = [
    "BASELINE_COMPARISON_BUNDLE_SEMANTICS_VERSION",
    "BASELINE_COMPARISON_SUMMARY_SEMANTICS_VERSION",
    "BASELINE_SELECTION_REASONS",
    "BASELINE_SELECTION_SEMANTICS_VERSION",
    "CONFIRMED_PIVOT_FINALITY",
    "DETERMINISTIC_BASELINE_KINDS",
    "TrendlineBaselineComparisonError",
    "TrendlineBaselineComparisonSummary",
    "TrendlineBaselineSelection",
    "TrendlineDeterministicBaselineComparisonBundle",
    "build_baseline_comparison_bundle",
    "build_baseline_outcomes",
    "build_baseline_selections",
    "validate_baseline_comparison_bundle",
]
