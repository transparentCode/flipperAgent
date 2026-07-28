"""Content-addressed final disposition for mature trendline research."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from numbers import Real
from typing import Any, Mapping, Sequence

from libs.models.trendlines.contracts.identity import canonical_hash

from .contracts import TrendlineAdequacyOutcome


FINAL_DISPOSITION_PROTOCOL_SEMANTICS_VERSION = (
    "trendlines.adequacy-final-disposition-protocol.v1"
)
FINAL_COHORT_EVIDENCE_SEMANTICS_VERSION = (
    "trendlines.adequacy-final-cohort-evidence.v1"
)
FINAL_DISPOSITION_BUNDLE_SEMANTICS_VERSION = (
    "trendlines.adequacy-final-disposition-bundle.v1"
)

FINAL_MEMBER_NAMES = (
    "reference-btcusdt-1h-20250101-v1",
    "temporal-btcusdt-1h-20250401-v1",
    "cross-asset-ethusdt-1h-20250401-v1",
    "cross-asset-solusdt-1h-20250401-v1",
    "cross-timeframe-btcusdt-4h-20250401-v1",
)
FINAL_ROLES = ("support", "resistance")
FINAL_HORIZONS_BARS = (1, 3, 6, 12)
FINAL_PRIMARY_METRICS = ("touch_rate",)
FINAL_SECONDARY_METRICS = (
    "rejection_rate",
    "confirmed_break_rate",
    "false_break_rate",
    "mean_penetration_atr",
    "mean_favourable_excursion_atr",
    "mean_adverse_excursion_atr",
)
FINAL_STRUCTURAL_METRICS = (
    "mean_active_anchor_count",
    "birth_rate",
    "total_birth_count",
    "anchor_persistence_rate",
    "revision_churn_rate",
    "episode_count",
    "survival_rate_h1",
    "survival_rate_h3",
    "survival_rate_h6",
    "survival_rate_h12",
)
FINAL_NULL_CELL_CLASSIFICATIONS = (
    "ROBUST_POSITIVE",
    "WEAK_OR_MIXED",
    "ROBUST_NEGATIVE",
)
FINAL_STRUCTURAL_CLASSIFICATIONS = (
    "OBSERVED_NONTRIVIAL_STRUCTURE",
    "NO_MEANINGFUL_STRUCTURE",
    "MIXED_STRUCTURE",
)
FINAL_SENSITIVITY_CLASSIFICATIONS = ("PARAMETER_ROBUST", "PARAMETER_FRAGILE")
FINAL_AXIS_NAMES = (
    "evidence_completeness",
    "structural_non_triviality",
    "null_relative_interaction_utility",
    "geometry_sensitivity",
)
FINAL_UTILITY_CLASSIFICATIONS = (
    "CROSS_MEMBER_SUPPORT",
    "RANDOM_STRONG_DENSITY_FAILED",
    "SUPPORT_FAILED",
    "MIXED_SUPPORT",
)
FINAL_OUTCOME_HIERARCHY = (
    TrendlineAdequacyOutcome.INSUFFICIENT_COVERAGE.value,
    TrendlineAdequacyOutcome.ADEQUATE_FOR_FURTHER_RESEARCH.value,
    TrendlineAdequacyOutcome.UTILITY_NOT_BETTER_THAN_NAIVE_NULL.value,
    TrendlineAdequacyOutcome.STRUCTURALLY_STABLE_BUT_NO_UTILITY.value,
    TrendlineAdequacyOutcome.EXCESSIVE_GEOMETRY_CHURN.value,
    TrendlineAdequacyOutcome.INCONCLUSIVE_INSUFFICIENT_EVIDENCE.value,
)
FINAL_RECOMMENDED_ACTIONS = (
    "RETAIN_AS_CONTEXT_ONLY",
    "RESTRICT_TO_SUPPORTED_SCOPE",
    "REDESIGN_GEOMETRY_SELECTION",
    "STOP_STANDALONE_SIGNAL_DEVELOPMENT",
    "CONTINUE_UNCHANGED_RESEARCH",
)
FINAL_DECISION_RULE_CODES = (
    "RULE_1_COVERAGE_FAILURE",
    "RULE_2_ADEQUATE_FOR_FURTHER_RESEARCH",
    "RULE_3_UTILITY_NOT_BETTER_THAN_NAIVE_NULL",
    "RULE_4_STRUCTURALLY_STABLE_BUT_NO_UTILITY",
    "RULE_5_EXCESSIVE_GEOMETRY_CHURN",
    "RULE_6_RESIDUAL_AMBIGUITY",
)
FINAL_DECISIVE_NULL = {
    "name": "causal-density-matched-null-v1",
    "id": "554f85bb1eea413ac1afabd6acbe4db469f845cdf2d297c64205d4bb71cc8401",
    "role": "decisive_stronger_utility_comparator",
    "legacy_outcome_note": (
        "UTILITY_NOT_BETTER_THAN_NAIVE_NULL is legacy outcome vocabulary; "
        "the decisive failed comparator is the causal density-matched null."
    ),
}


class TrendlineFinalRecommendedAction(str, Enum):
    """Permitted non-production actions after research disposition."""

    RETAIN_AS_CONTEXT_ONLY = "RETAIN_AS_CONTEXT_ONLY"
    RESTRICT_TO_SUPPORTED_SCOPE = "RESTRICT_TO_SUPPORTED_SCOPE"
    REDESIGN_GEOMETRY_SELECTION = "REDESIGN_GEOMETRY_SELECTION"
    STOP_STANDALONE_SIGNAL_DEVELOPMENT = "STOP_STANDALONE_SIGNAL_DEVELOPMENT"
    CONTINUE_UNCHANGED_RESEARCH = "CONTINUE_UNCHANGED_RESEARCH"


class TrendlineFinalDispositionError(ValueError):
    """Raised when final evidence or disposition violates its frozen contract."""


def _text(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrendlineFinalDispositionError(f"{name} must be non-empty text")
    return value


def _sha(value: Any, *, name: str) -> str:
    value = _text(value, name=name)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise TrendlineFinalDispositionError(f"{name} must be lowercase SHA-256")
    return value


def _integer(value: Any, *, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise TrendlineFinalDispositionError(
            f"{name} must be a non-boolean integer >= {minimum}"
        )
    return value


def _number(value: Any, *, name: str, allow_none: bool = False) -> float | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TrendlineFinalDispositionError(f"{name} must be finite numeric")
    result = float(value)
    if not isfinite(result):
        raise TrendlineFinalDispositionError(f"{name} must be finite numeric")
    return result


def _freeze(value: Any) -> Any:
    """Freeze small JSON-shaped evidence values for frozen contracts."""

    if isinstance(value, Mapping):
        return (
            "__map__",
            tuple((str(key), _freeze(item)) for key, item in sorted(value.items())),
        )
    if isinstance(value, (list, tuple)):
        return ("__seq__", tuple(_freeze(item) for item in value))
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TrendlineFinalDispositionError("evidence must be JSON-shaped")


def _thaw(value: Any) -> Any:
    if isinstance(value, tuple) and len(value) == 2 and value[0] == "__map__":
        return {key: _thaw(item) for key, item in value[1]}
    if isinstance(value, tuple) and len(value) == 2 and value[0] == "__seq__":
        return [_thaw(item) for item in value[1]]
    return value


def _rows(value: Any, *, name: str) -> tuple[dict[str, Any], ...]:
    raw = _thaw(value)
    if not isinstance(raw, (list, tuple)):
        raise TrendlineFinalDispositionError(f"{name} must be ordered rows")
    result = tuple(dict(row) for row in raw)
    if any(not isinstance(row, dict) for row in result):
        raise TrendlineFinalDispositionError(f"{name} must contain mappings")
    return result


def _mapping(value: Any, *, name: str) -> dict[str, Any]:
    raw = _thaw(value)
    if not isinstance(raw, Mapping):
        raise TrendlineFinalDispositionError(f"{name} must be a mapping")
    return dict(raw)


def _sign(value: Any) -> int:
    numeric = _number(value, name="sign value", allow_none=True)
    if numeric is None or numeric == 0:
        return 0
    return 1 if numeric > 0 else -1


def _coordinate_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    protocol: "TrendlineFinalDispositionProtocol",
    name: str,
) -> tuple[dict[str, Any], ...]:
    expected = {(role, horizon) for role in protocol.roles for horizon in protocol.horizons_bars}
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for raw in rows:
        row = dict(raw)
        role = _text(row.get("role"), name=f"{name} role")
        horizon = _integer(row.get("horizon_bars"), name=f"{name} horizon", minimum=1)
        coordinate = (role, horizon)
        if coordinate not in expected or coordinate in seen:
            raise TrendlineFinalDispositionError(f"{name} has invalid or duplicate coordinate")
        seen.add(coordinate)
        result.append(row)
    if seen != expected:
        raise TrendlineFinalDispositionError(f"{name} is missing role/horizon evidence")
    return tuple(sorted(result, key=lambda row: (row["role"], row["horizon_bars"])))


@dataclass(frozen=True)
class TrendlineFinalDispositionProtocol:
    """Frozen scope, thresholds, metric catalog, and outcome hierarchy."""

    d5a_source_matrix_bundle_id: str
    d5b_replication_protocol_id: str
    d5b_replication_bundle_id: str
    d5c_sensitivity_protocol_id: str
    d5c_sensitivity_bundle_id: str
    member_names: tuple[str, ...]
    roles: tuple[str, ...]
    horizons_bars: tuple[int, ...]
    primary_metric_catalog: tuple[str, ...]
    secondary_metric_catalog: tuple[str, ...]
    structural_metric_catalog: tuple[str, ...]
    null_cell_classifications: tuple[str, ...]
    member_support_min_cells: int
    cross_member_support_min_members: int
    sensitivity_coarse_jaccard_min: float
    sensitivity_touch_cell_min_count: int
    sensitivity_touch_delta_tolerance: float
    sensitivity_density_direction_change_max: int
    cross_member_parameter_robust_min_members: int
    outcome_hierarchy: tuple[str, ...]
    recommended_actions: tuple[str, ...]
    semantics_version: str = FINAL_DISPOSITION_PROTOCOL_SEMANTICS_VERSION
    protocol_id: str = ""

    def __post_init__(self) -> None:
        for name in (
            "d5a_source_matrix_bundle_id",
            "d5b_replication_protocol_id",
            "d5b_replication_bundle_id",
            "d5c_sensitivity_protocol_id",
            "d5c_sensitivity_bundle_id",
        ):
            _sha(getattr(self, name), name=name)
        if tuple(self.member_names) != FINAL_MEMBER_NAMES:
            raise TrendlineFinalDispositionError("final member order differs")
        if tuple(self.roles) != FINAL_ROLES:
            raise TrendlineFinalDispositionError("final role scope differs")
        if tuple(self.horizons_bars) != FINAL_HORIZONS_BARS:
            raise TrendlineFinalDispositionError("final horizon scope differs")
        if tuple(self.primary_metric_catalog) != FINAL_PRIMARY_METRICS:
            raise TrendlineFinalDispositionError("primary metric catalog differs")
        if tuple(self.secondary_metric_catalog) != FINAL_SECONDARY_METRICS:
            raise TrendlineFinalDispositionError("secondary metric catalog differs")
        if tuple(self.structural_metric_catalog) != FINAL_STRUCTURAL_METRICS:
            raise TrendlineFinalDispositionError("structural metric catalog differs")
        if tuple(self.null_cell_classifications) != FINAL_NULL_CELL_CLASSIFICATIONS:
            raise TrendlineFinalDispositionError("null classification vocabulary differs")
        if self.member_support_min_cells != 6:
            raise TrendlineFinalDispositionError("member support threshold differs")
        if self.cross_member_support_min_members != 4:
            raise TrendlineFinalDispositionError("cross-member support threshold differs")
        if self.cross_member_parameter_robust_min_members != 4:
            raise TrendlineFinalDispositionError("parameter robustness threshold differs")
        if self.sensitivity_coarse_jaccard_min != 0.25:
            raise TrendlineFinalDispositionError("coarse event threshold differs")
        if self.sensitivity_touch_cell_min_count != 6:
            raise TrendlineFinalDispositionError("touch sensitivity threshold differs")
        if self.sensitivity_touch_delta_tolerance != 0.05:
            raise TrendlineFinalDispositionError("touch sensitivity tolerance differs")
        if self.sensitivity_density_direction_change_max != 2:
            raise TrendlineFinalDispositionError("density sensitivity threshold differs")
        if tuple(self.outcome_hierarchy) != FINAL_OUTCOME_HIERARCHY:
            raise TrendlineFinalDispositionError("outcome hierarchy differs")
        if tuple(self.recommended_actions) != FINAL_RECOMMENDED_ACTIONS:
            raise TrendlineFinalDispositionError("recommended-action vocabulary differs")
        if self.semantics_version != FINAL_DISPOSITION_PROTOCOL_SEMANTICS_VERSION:
            raise TrendlineFinalDispositionError("unsupported final protocol semantics")
        object.__setattr__(self, "member_names", tuple(self.member_names))
        object.__setattr__(self, "roles", tuple(self.roles))
        object.__setattr__(self, "horizons_bars", tuple(self.horizons_bars))
        object.__setattr__(self, "primary_metric_catalog", tuple(self.primary_metric_catalog))
        object.__setattr__(self, "secondary_metric_catalog", tuple(self.secondary_metric_catalog))
        object.__setattr__(self, "structural_metric_catalog", tuple(self.structural_metric_catalog))
        object.__setattr__(self, "null_cell_classifications", tuple(self.null_cell_classifications))
        expected = canonical_hash(self.to_dict(include_id=False), semantics_version=self.semantics_version)
        if self.protocol_id and self.protocol_id != expected:
            raise TrendlineFinalDispositionError("final protocol ID differs from content")
        object.__setattr__(self, "protocol_id", expected)

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "d5a_source_matrix_bundle_id": self.d5a_source_matrix_bundle_id,
            "d5b_replication_protocol_id": self.d5b_replication_protocol_id,
            "d5b_replication_bundle_id": self.d5b_replication_bundle_id,
            "d5c_sensitivity_protocol_id": self.d5c_sensitivity_protocol_id,
            "d5c_sensitivity_bundle_id": self.d5c_sensitivity_bundle_id,
            "member_names": list(self.member_names),
            "roles": list(self.roles),
            "horizons_bars": list(self.horizons_bars),
            "primary_metric_catalog": list(self.primary_metric_catalog),
            "secondary_metric_catalog": list(self.secondary_metric_catalog),
            "structural_metric_catalog": list(self.structural_metric_catalog),
            "null_cell_classifications": list(self.null_cell_classifications),
            "member_support_min_cells": self.member_support_min_cells,
            "cross_member_support_min_members": self.cross_member_support_min_members,
            "sensitivity_coarse_jaccard_min": self.sensitivity_coarse_jaccard_min,
            "sensitivity_touch_cell_min_count": self.sensitivity_touch_cell_min_count,
            "sensitivity_touch_delta_tolerance": self.sensitivity_touch_delta_tolerance,
            "sensitivity_density_direction_change_max": self.sensitivity_density_direction_change_max,
            "cross_member_parameter_robust_min_members": self.cross_member_parameter_robust_min_members,
            "outcome_hierarchy": list(self.outcome_hierarchy),
            "recommended_actions": list(self.recommended_actions),
            "semantics_version": self.semantics_version,
        }
        if include_id:
            payload["final_disposition_protocol_id"] = self.protocol_id
        return payload


def build_final_disposition_protocol(
    *,
    d5a_source_matrix_bundle_id: str,
    d5b_replication_protocol_id: str,
    d5b_replication_bundle_id: str,
    d5c_sensitivity_protocol_id: str,
    d5c_sensitivity_bundle_id: str,
) -> TrendlineFinalDispositionProtocol:
    """Build the one frozen D5D protocol from committed prior identities."""

    return TrendlineFinalDispositionProtocol(
        d5a_source_matrix_bundle_id=d5a_source_matrix_bundle_id,
        d5b_replication_protocol_id=d5b_replication_protocol_id,
        d5b_replication_bundle_id=d5b_replication_bundle_id,
        d5c_sensitivity_protocol_id=d5c_sensitivity_protocol_id,
        d5c_sensitivity_bundle_id=d5c_sensitivity_bundle_id,
        member_names=FINAL_MEMBER_NAMES,
        roles=FINAL_ROLES,
        horizons_bars=FINAL_HORIZONS_BARS,
        primary_metric_catalog=FINAL_PRIMARY_METRICS,
        secondary_metric_catalog=FINAL_SECONDARY_METRICS,
        structural_metric_catalog=FINAL_STRUCTURAL_METRICS,
        null_cell_classifications=FINAL_NULL_CELL_CLASSIFICATIONS,
        member_support_min_cells=6,
        cross_member_support_min_members=4,
        sensitivity_coarse_jaccard_min=0.25,
        sensitivity_touch_cell_min_count=6,
        sensitivity_touch_delta_tolerance=0.05,
        sensitivity_density_direction_change_max=2,
        cross_member_parameter_robust_min_members=4,
        outcome_hierarchy=FINAL_OUTCOME_HIERARCHY,
        recommended_actions=FINAL_RECOMMENDED_ACTIONS,
    )


def classify_null_cell(
    mean_delta: Any,
    q05_delta: Any,
    q95_delta: Any,
) -> str:
    """Classify one stochastic-null cell without significance claims."""

    mean = _number(mean_delta, name="null mean delta", allow_none=True)
    q05 = _number(q05_delta, name="null q05 delta", allow_none=True)
    q95 = _number(q95_delta, name="null q95 delta", allow_none=True)
    if mean is not None and q05 is not None and mean > 0 and q05 > 0:
        return "ROBUST_POSITIVE"
    if mean is not None and q95 is not None and mean < 0 and q95 < 0:
        return "ROBUST_NEGATIVE"
    return "WEAK_OR_MIXED"


def classify_null_cells(
    rows: Sequence[Mapping[str, Any]],
    *,
    protocol: TrendlineFinalDispositionProtocol,
) -> tuple[dict[str, Any], ...]:
    """Recompute exact role/horizon null classifications."""

    normalized = _coordinate_rows(rows, protocol=protocol, name="null cells")
    result = []
    for row in normalized:
        classification = classify_null_cell(
            row.get("mean_delta"), row.get("q05_delta"), row.get("q95_delta")
        )
        item = {
            "baseline_id": _sha(row.get("baseline_id"), name="null baseline ID"),
            "baseline_name": _text(row.get("baseline_name"), name="null baseline name"),
            "role": row["role"],
            "horizon_bars": row["horizon_bars"],
            "mean_delta": row.get("mean_delta"),
            "q05_delta": row.get("q05_delta"),
            "q95_delta": row.get("q95_delta"),
            "classification": classification,
        }
        result.append(item)
    return tuple(result)


def member_support(
    cells: Sequence[Mapping[str, Any]],
    *,
    protocol: TrendlineFinalDispositionProtocol,
) -> bool:
    rows = _coordinate_rows(cells, protocol=protocol, name="null cells")
    return sum(row.get("classification") == "ROBUST_POSITIVE" for row in rows) >= protocol.member_support_min_cells


def _touch_rows(capsule: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    rows = [
        row
        for row in capsule.get("delta_rows", ())
        if row.get("stage") == "d3" and row.get("metric_name") == "touch_rate"
    ]
    if len(rows) != 8:
        raise TrendlineFinalDispositionError("sensitivity capsule must contain eight D3 touch deltas")
    return tuple(rows)


def _density_rows(bundle: Mapping[str, Any], *, variant: bool) -> tuple[dict[str, Any], ...]:
    source = bundle.get("d4b_summaries" if variant else "distribution_summaries", ())
    rows = [
        row
        for row in source
        if row.get("metric") == "touch_rate"
        and row.get("baseline_kind") == "density_matched_null"
    ]
    return tuple(rows)


def _sensitivity_variant(
    capsule: Mapping[str, Any],
    *,
    canonical_d3: Mapping[str, Any],
    canonical_d4b: Mapping[str, Any],
    protocol: TrendlineFinalDispositionProtocol,
    variant_name: str,
) -> dict[str, Any]:
    touch_rows = _touch_rows(capsule)
    expected_touch = {(role, horizon) for role in protocol.roles for horizon in protocol.horizons_bars}
    seen: set[tuple[str, int]] = set()
    touch_sign_retained = 0
    for row in touch_rows:
        coordinate = (row["role"], row["horizon_bars"])
        if coordinate in seen or coordinate not in expected_touch:
            raise TrendlineFinalDispositionError("sensitivity touch coordinates are invalid")
        seen.add(coordinate)
        if row.get("baseline_value") is None or row.get("variant_value") is None:
            continue
        if _sign(row["baseline_value"]) == _sign(row["variant_value"]):
            touch_sign_retained += 1
        elif abs(float(row["delta"])) <= protocol.sensitivity_touch_delta_tolerance:
            touch_sign_retained += 1
    if seen != expected_touch:
        raise TrendlineFinalDispositionError("sensitivity touch coordinates are incomplete")

    canonical_density = {
        (row["role"], row["horizon_bars"]): row
        for row in _density_rows(canonical_d4b, variant=False)
    }
    variant_density = {
        (row["role"], row["horizon_bars"]): row
        for row in _density_rows(capsule, variant=True)
    }
    if set(canonical_density) != expected_touch or set(variant_density) != expected_touch:
        raise TrendlineFinalDispositionError("density touch coordinates are incomplete")
    direction_changes = 0
    for coordinate in sorted(expected_touch):
        if _sign(canonical_density[coordinate].get("mean_delta")) != _sign(
            variant_density[coordinate].get("mean_delta")
        ):
            direction_changes += 1
    overlap = dict(capsule.get("event_overlap", {}))
    coarse_jaccard = _number(
        overlap.get("coarse_event_jaccard"),
        name="coarse event Jaccard",
        allow_none=True,
    )
    robust = (
        coarse_jaccard is not None
        and coarse_jaccard >= protocol.sensitivity_coarse_jaccard_min
        and touch_sign_retained >= protocol.sensitivity_touch_cell_min_count
        and direction_changes <= protocol.sensitivity_density_direction_change_max
    )
    return {
        "variant": variant_name,
        "variant_id": _sha(capsule.get("variant_id"), name="variant ID"),
        "capsule_id": _sha(
            capsule.get("geometry_sensitivity_capsule_id"), name="sensitivity capsule ID"
        ),
        "coarse_event_jaccard": coarse_jaccard,
        "exact_event_jaccard": overlap.get("exact_event_jaccard"),
        "touch_sign_retained_count": touch_sign_retained,
        "touch_cell_count": len(expected_touch),
        "density_direction_change_count": direction_changes,
        "classification": "PARAMETER_ROBUST" if robust else "PARAMETER_FRAGILE",
    }


def _structural_evidence(d2: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    summaries = [
        row for row in d2.get("summaries", ()) if row.get("observation_unit") == "boundary_ray"
    ]
    if not summaries:
        raise TrendlineFinalDispositionError("D2 has no boundary-ray summary")
    summary = summaries[0]
    survival = list(summary.get("survival", ()))
    beyond_one = [
        row
        for row in survival
        if row.get("horizon_bars", 0) > 1
        and row.get("eligible_target_count", 0) > 0
        and row.get("survived_count", 0) > 0
    ]
    births = int(summary.get("observed_birth_episode_count", 0))
    episodes = int(summary.get("episode_count", 0))
    if births > 0 and episodes > 0 and beyond_one:
        classification = "OBSERVED_NONTRIVIAL_STRUCTURE"
    elif births == 0 and episodes == 0 and not beyond_one:
        classification = "NO_MEANINGFUL_STRUCTURE"
    else:
        classification = "MIXED_STRUCTURE"
    evidence = {
        "observation_unit": "boundary_ray",
        "timeframe": summary.get("timeframe"),
        "mean_active_anchor_count": summary.get("mean_active_anchor_count"),
        "birth_rate": summary.get("birth_rate"),
        "anchor_persistence_rate": summary.get("anchor_persistence_rate"),
        "revision_churn_rate": summary.get("revision_churn_rate"),
        "episode_count": episodes,
        "observed_birth_episode_count": births,
        "survival": [
            {
                "horizon_bars": row.get("horizon_bars"),
                "eligible_target_count": row.get("eligible_target_count"),
                "survived_count": row.get("survived_count"),
                "survival_rate": row.get("survival_rate"),
            }
            for row in sorted(survival, key=lambda value: value.get("horizon_bars", 0))
        ],
    }
    return classification, evidence


def _secondary_adverse_reversal(
    d4b: Mapping[str, Any],
    *,
    protocol: TrendlineFinalDispositionProtocol,
) -> tuple[bool, tuple[dict[str, Any], ...]]:
    higher_is_better = {"rejection_rate", "confirmed_break_rate", "mean_favourable_excursion_atr"}
    lower_is_better = {"false_break_rate", "mean_penetration_atr", "mean_adverse_excursion_atr"}
    rows = [
        row
        for row in d4b.get("distribution_summaries", ())
        if row.get("baseline_kind") == "density_matched_null"
        and row.get("metric") in FINAL_SECONDARY_METRICS
    ]
    adverse: list[dict[str, Any]] = []
    for row in rows:
        mean = row.get("mean_delta")
        q05 = row.get("q05_delta")
        q95 = row.get("q95_delta")
        if row.get("metric") in higher_is_better:
            robust_adverse = mean is not None and q95 is not None and mean < 0 and q95 < 0
        elif row.get("metric") in lower_is_better:
            robust_adverse = mean is not None and q05 is not None and mean > 0 and q05 > 0
        else:
            robust_adverse = False
        if robust_adverse:
            adverse.append(
                {
                    "role": row.get("role"),
                    "horizon_bars": row.get("horizon_bars"),
                    "metric": row.get("metric"),
                    "mean_delta": mean,
                    "q05_delta": q05,
                    "q95_delta": q95,
                }
            )
    return bool(adverse), tuple(adverse)


@dataclass(frozen=True)
class TrendlineFinalCohortEvidence:
    """Compact evidence row for one canonical cohort."""

    member_name: str
    relation: str
    asset: str
    timeframe: str
    d5a_member_spec_id: str
    d5a_member_evidence_id: str
    canonical_d2_bundle_id: str
    canonical_d3_bundle_id: str
    canonical_d4a_bundle_id: str
    canonical_d4b_bundle_id: str
    baseline_member_result_id: str
    canonical_event_count: int
    structural_classification: str
    structural_evidence: Any
    random_null_cells: Any
    density_null_cells: Any
    random_robust_positive_count: int
    density_robust_positive_count: int
    random_member_support: bool
    density_member_support: bool
    deterministic_baseline_directional_inventory: Any
    dense_capsule_id: str
    sparse_capsule_id: str
    dense_event_overlap: Any
    sparse_event_overlap: Any
    dense_sensitivity: Any
    sparse_sensitivity: Any
    parameter_robust: bool
    secondary_adverse_reversal: bool
    secondary_adverse_reversal_cells: Any
    semantics_version: str = FINAL_COHORT_EVIDENCE_SEMANTICS_VERSION
    cohort_evidence_id: str = ""

    def __post_init__(self) -> None:
        for name in (
            "member_name",
            "relation",
            "asset",
            "timeframe",
        ):
            _text(getattr(self, name), name=name)
        for name in (
            "d5a_member_spec_id",
            "d5a_member_evidence_id",
            "canonical_d2_bundle_id",
            "canonical_d3_bundle_id",
            "canonical_d4a_bundle_id",
            "canonical_d4b_bundle_id",
            "baseline_member_result_id",
            "dense_capsule_id",
            "sparse_capsule_id",
        ):
            _sha(getattr(self, name), name=name)
        _integer(self.canonical_event_count, name="canonical event count")
        if self.structural_classification not in FINAL_STRUCTURAL_CLASSIFICATIONS:
            raise TrendlineFinalDispositionError("structural classification is invalid")
        for name in (
            "random_robust_positive_count",
            "density_robust_positive_count",
        ):
            _integer(getattr(self, name), name=name)
        for name in (
            "random_member_support",
            "density_member_support",
            "parameter_robust",
            "secondary_adverse_reversal",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TrendlineFinalDispositionError(f"{name} must be bool")
        random_cells = _coordinate_rows(
            _rows(self.random_null_cells, name="random null cells"),
            protocol=_protocol_for_row_validation(),
            name="random null cells",
        )
        density_cells = _coordinate_rows(
            _rows(self.density_null_cells, name="density null cells"),
            protocol=_protocol_for_row_validation(),
            name="density null cells",
        )
        if sum(row.get("classification") == "ROBUST_POSITIVE" for row in random_cells) != self.random_robust_positive_count:
            raise TrendlineFinalDispositionError("random robust-positive count differs")
        if sum(row.get("classification") == "ROBUST_POSITIVE" for row in density_cells) != self.density_robust_positive_count:
            raise TrendlineFinalDispositionError("density robust-positive count differs")
        for cells, name in ((random_cells, "random"), (density_cells, "density")):
            if any(
                row.get("classification") not in FINAL_NULL_CELL_CLASSIFICATIONS
                for row in cells
            ):
                raise TrendlineFinalDispositionError(
                    f"{name} null classification is invalid"
                )
        for name, value in (
            ("structural_evidence", self.structural_evidence),
            ("random_null_cells", self.random_null_cells),
            ("density_null_cells", self.density_null_cells),
            ("deterministic_baseline_directional_inventory", self.deterministic_baseline_directional_inventory),
            ("dense_event_overlap", self.dense_event_overlap),
            ("sparse_event_overlap", self.sparse_event_overlap),
            ("dense_sensitivity", self.dense_sensitivity),
            ("sparse_sensitivity", self.sparse_sensitivity),
            ("secondary_adverse_reversal_cells", self.secondary_adverse_reversal_cells),
        ):
            object.__setattr__(self, name, _freeze(_thaw(value)))
        if self.semantics_version != FINAL_COHORT_EVIDENCE_SEMANTICS_VERSION:
            raise TrendlineFinalDispositionError("unsupported cohort evidence semantics")
        expected = canonical_hash(self.to_dict(include_id=False), semantics_version=self.semantics_version)
        if self.cohort_evidence_id and self.cohort_evidence_id != expected:
            raise TrendlineFinalDispositionError("cohort evidence ID differs from content")
        object.__setattr__(self, "cohort_evidence_id", expected)

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "member_name": self.member_name,
            "relation": self.relation,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "d5a_member_spec_id": self.d5a_member_spec_id,
            "d5a_member_evidence_id": self.d5a_member_evidence_id,
            "canonical_d2_bundle_id": self.canonical_d2_bundle_id,
            "canonical_d3_bundle_id": self.canonical_d3_bundle_id,
            "canonical_d4a_bundle_id": self.canonical_d4a_bundle_id,
            "canonical_d4b_bundle_id": self.canonical_d4b_bundle_id,
            "baseline_member_result_id": self.baseline_member_result_id,
            "canonical_event_count": self.canonical_event_count,
            "structural_classification": self.structural_classification,
            "structural_evidence": _thaw(self.structural_evidence),
            "random_null_cells": _thaw(self.random_null_cells),
            "density_null_cells": _thaw(self.density_null_cells),
            "random_robust_positive_count": self.random_robust_positive_count,
            "density_robust_positive_count": self.density_robust_positive_count,
            "random_member_support": self.random_member_support,
            "density_member_support": self.density_member_support,
            "deterministic_baseline_directional_inventory": _thaw(self.deterministic_baseline_directional_inventory),
            "dense_capsule_id": self.dense_capsule_id,
            "sparse_capsule_id": self.sparse_capsule_id,
            "dense_event_overlap": _thaw(self.dense_event_overlap),
            "sparse_event_overlap": _thaw(self.sparse_event_overlap),
            "dense_sensitivity": _thaw(self.dense_sensitivity),
            "sparse_sensitivity": _thaw(self.sparse_sensitivity),
            "parameter_robust": self.parameter_robust,
            "secondary_adverse_reversal": self.secondary_adverse_reversal,
            "secondary_adverse_reversal_cells": _thaw(self.secondary_adverse_reversal_cells),
            "semantics_version": self.semantics_version,
        }
        if include_id:
            payload["cohort_evidence_id"] = self.cohort_evidence_id
        return payload


def _protocol_for_row_validation() -> TrendlineFinalDispositionProtocol:
    """Use frozen coordinate vocabulary for already-built cohort rows."""

    return TrendlineFinalDispositionProtocol(
        d5a_source_matrix_bundle_id="a" * 64,
        d5b_replication_protocol_id="b" * 64,
        d5b_replication_bundle_id="c" * 64,
        d5c_sensitivity_protocol_id="d" * 64,
        d5c_sensitivity_bundle_id="e" * 64,
        member_names=FINAL_MEMBER_NAMES,
        roles=FINAL_ROLES,
        horizons_bars=FINAL_HORIZONS_BARS,
        primary_metric_catalog=FINAL_PRIMARY_METRICS,
        secondary_metric_catalog=FINAL_SECONDARY_METRICS,
        structural_metric_catalog=FINAL_STRUCTURAL_METRICS,
        null_cell_classifications=FINAL_NULL_CELL_CLASSIFICATIONS,
        member_support_min_cells=6,
        cross_member_support_min_members=4,
        sensitivity_coarse_jaccard_min=0.25,
        sensitivity_touch_cell_min_count=6,
        sensitivity_touch_delta_tolerance=0.05,
        sensitivity_density_direction_change_max=2,
        cross_member_parameter_robust_min_members=4,
        outcome_hierarchy=FINAL_OUTCOME_HIERARCHY,
        recommended_actions=FINAL_RECOMMENDED_ACTIONS,
    )


def build_final_cohort_evidence(
    *,
    canonical: Mapping[str, Any],
    dense_capsule: Mapping[str, Any],
    sparse_capsule: Mapping[str, Any],
    protocol: TrendlineFinalDispositionProtocol,
) -> TrendlineFinalCohortEvidence:
    """Recompute one compact cohort row from canonical and sensitivity evidence."""

    member_name = _text(canonical.get("member_name"), name="member name")
    if member_name not in protocol.member_names:
        raise TrendlineFinalDispositionError("cohort is outside frozen member scope")
    for capsule, name in ((dense_capsule, "dense"), (sparse_capsule, "sparse")):
        if capsule.get("member_name") != member_name:
            raise TrendlineFinalDispositionError(f"{name} capsule member differs")
    structural_classification, structural = _structural_evidence(canonical["d2"])
    d3 = canonical["d3"]
    d4b = canonical["d4b"]
    d4a = canonical["d4a"]
    distribution_rows = d4b.get("distribution_summaries", ())
    random_rows = classify_null_cells(
        [
            row
            for row in distribution_rows
            if row.get("baseline_kind") == "random_valid_pivot_pair"
            and row.get("metric") == "touch_rate"
        ],
        protocol=protocol,
    )
    density_rows = classify_null_cells(
        [
            row
            for row in distribution_rows
            if row.get("baseline_kind") == "density_matched_null"
            and row.get("metric") == "touch_rate"
        ],
        protocol=protocol,
    )
    random_support = member_support(random_rows, protocol=protocol)
    density_support = member_support(density_rows, protocol=protocol)
    canonical_touch = {
        (row["role"], row["horizon_bars"]): row.get("touch_rate")
        for row in d3.get("summaries", ())
    }
    dense_sensitivity = _sensitivity_variant(
        dense_capsule,
        canonical_d3=d3,
        canonical_d4b=d4b,
        protocol=protocol,
        variant_name="dense-geometry-v1",
    )
    sparse_sensitivity = _sensitivity_variant(
        sparse_capsule,
        canonical_d3=d3,
        canonical_d4b=d4b,
        protocol=protocol,
        variant_name="sparse-geometry-v1",
    )
    # Ensure canonical touch coordinates are present before accepting sensitivity rows.
    expected_coordinates = {(role, horizon) for role in protocol.roles for horizon in protocol.horizons_bars}
    if set(canonical_touch) != expected_coordinates:
        raise TrendlineFinalDispositionError("canonical D3 touch coordinates are incomplete")
    deterministic = []
    for row in d4a.get("comparison_summaries", ()):
        deterministic.append(
            {
                "baseline_id": row.get("baseline_id"),
                "baseline_name": row.get("baseline_name"),
                "role": row.get("role"),
                "horizon_bars": row.get("horizon_bars"),
                "baseline_coverage_rate": row.get("baseline_coverage_rate"),
                "touch_rate_delta": row.get("touch_rate_delta"),
                "rejection_rate_delta": row.get("rejection_rate_delta"),
            }
        )
    if len(deterministic) != 16:
        raise TrendlineFinalDispositionError("deterministic baseline directional inventory is incomplete")
    secondary_flag, secondary_cells = _secondary_adverse_reversal(d4b, protocol=protocol)
    parameter_robust = any(
        row["classification"] == "PARAMETER_ROBUST"
        for row in (dense_sensitivity, sparse_sensitivity)
    )
    return TrendlineFinalCohortEvidence(
        member_name=member_name,
        relation=_text(canonical.get("relation"), name="relation"),
        asset=_text(canonical.get("asset"), name="asset"),
        timeframe=_text(canonical.get("timeframe"), name="timeframe"),
        d5a_member_spec_id=_sha(canonical.get("d5a_member_spec_id"), name="D5A member spec ID"),
        d5a_member_evidence_id=_sha(canonical.get("d5a_member_evidence_id"), name="D5A member evidence ID"),
        canonical_d2_bundle_id=_sha(canonical.get("canonical_d2_bundle_id"), name="canonical D2 ID"),
        canonical_d3_bundle_id=_sha(canonical.get("canonical_d3_bundle_id"), name="canonical D3 ID"),
        canonical_d4a_bundle_id=_sha(canonical.get("canonical_d4a_bundle_id"), name="canonical D4A ID"),
        canonical_d4b_bundle_id=_sha(canonical.get("canonical_d4b_bundle_id"), name="canonical D4B ID"),
        baseline_member_result_id=_sha(canonical.get("baseline_member_result_id"), name="baseline result ID"),
        canonical_event_count=len(d3.get("events", ())),
        structural_classification=structural_classification,
        structural_evidence=structural,
        random_null_cells=random_rows,
        density_null_cells=density_rows,
        random_robust_positive_count=sum(row["classification"] == "ROBUST_POSITIVE" for row in random_rows),
        density_robust_positive_count=sum(row["classification"] == "ROBUST_POSITIVE" for row in density_rows),
        random_member_support=random_support,
        density_member_support=density_support,
        deterministic_baseline_directional_inventory=deterministic,
        dense_capsule_id=_sha(dense_capsule.get("geometry_sensitivity_capsule_id"), name="dense capsule ID"),
        sparse_capsule_id=_sha(sparse_capsule.get("geometry_sensitivity_capsule_id"), name="sparse capsule ID"),
        dense_event_overlap=dense_capsule.get("event_overlap", {}),
        sparse_event_overlap=sparse_capsule.get("event_overlap", {}),
        dense_sensitivity=dense_sensitivity,
        sparse_sensitivity=sparse_sensitivity,
        parameter_robust=parameter_robust,
        secondary_adverse_reversal=secondary_flag,
        secondary_adverse_reversal_cells=secondary_cells,
    )


def _axis_tuple(values: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple((name, values[name]) for name in FINAL_AXIS_NAMES)


def _action_for_outcome(outcome: TrendlineAdequacyOutcome) -> TrendlineFinalRecommendedAction:
    return {
        TrendlineAdequacyOutcome.ADEQUATE_FOR_FURTHER_RESEARCH: TrendlineFinalRecommendedAction.CONTINUE_UNCHANGED_RESEARCH,
        TrendlineAdequacyOutcome.UTILITY_NOT_BETTER_THAN_NAIVE_NULL: TrendlineFinalRecommendedAction.REDESIGN_GEOMETRY_SELECTION,
        TrendlineAdequacyOutcome.STRUCTURALLY_STABLE_BUT_NO_UTILITY: TrendlineFinalRecommendedAction.RETAIN_AS_CONTEXT_ONLY,
        TrendlineAdequacyOutcome.INSUFFICIENT_COVERAGE: TrendlineFinalRecommendedAction.RESTRICT_TO_SUPPORTED_SCOPE,
        TrendlineAdequacyOutcome.EXCESSIVE_GEOMETRY_CHURN: TrendlineFinalRecommendedAction.REDESIGN_GEOMETRY_SELECTION,
        TrendlineAdequacyOutcome.INCONCLUSIVE_INSUFFICIENT_EVIDENCE: TrendlineFinalRecommendedAction.RESTRICT_TO_SUPPORTED_SCOPE,
    }[outcome]


@dataclass(frozen=True)
class TrendlineFinalDispositionBundle:
    """Final content-addressed outcome and action; no production status."""

    final_disposition_protocol: TrendlineFinalDispositionProtocol
    cohort_evidence_ids: tuple[str, ...]
    axis_classifications: tuple[tuple[str, str], ...]
    selected_outcome: TrendlineAdequacyOutcome
    recommended_action: TrendlineFinalRecommendedAction
    rationale_codes: tuple[str, ...]
    residual_limitations: tuple[str, ...]
    evidence_completeness: bool
    semantics_version: str = FINAL_DISPOSITION_BUNDLE_SEMANTICS_VERSION
    final_disposition_bundle_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.final_disposition_protocol, TrendlineFinalDispositionProtocol):
            raise TrendlineFinalDispositionError("final protocol must be typed")
        ids = tuple(self.cohort_evidence_ids)
        if len(set(ids)) != len(ids) or any(not _sha(value, name="cohort evidence ID") for value in ids):
            raise TrendlineFinalDispositionError("cohort evidence IDs must be unique SHA-256 values")
        axes = tuple(self.axis_classifications)
        if tuple(name for name, _ in axes) != FINAL_AXIS_NAMES:
            raise TrendlineFinalDispositionError("final axis order differs")
        if any(not _text(name, name="axis name") or not _text(value, name="axis value") for name, value in axes):
            raise TrendlineFinalDispositionError("final axis classification is invalid")
        outcome = self.selected_outcome
        if not isinstance(outcome, TrendlineAdequacyOutcome):
            try:
                outcome = TrendlineAdequacyOutcome(outcome)
            except ValueError as exc:
                raise TrendlineFinalDispositionError("invalid final outcome") from exc
            object.__setattr__(self, "selected_outcome", outcome)
        action = self.recommended_action
        if not isinstance(action, TrendlineFinalRecommendedAction):
            try:
                action = TrendlineFinalRecommendedAction(action)
            except ValueError as exc:
                raise TrendlineFinalDispositionError("invalid recommended action") from exc
            object.__setattr__(self, "recommended_action", action)
        if action is not _action_for_outcome(outcome):
            raise TrendlineFinalDispositionError("recommended action does not follow outcome")
        rationale = tuple(_text(value, name="rationale code") for value in self.rationale_codes)
        limitations = tuple(_text(value, name="residual limitation") for value in self.residual_limitations)
        if len(set(rationale)) != len(rationale):
            raise TrendlineFinalDispositionError("rationale codes must be unique")
        if any(value not in FINAL_DECISION_RULE_CODES for value in rationale if value.startswith("RULE_")):
            raise TrendlineFinalDispositionError("rationale code is invalid")
        if not isinstance(self.evidence_completeness, bool):
            raise TrendlineFinalDispositionError("evidence_completeness must be bool")
        if self.evidence_completeness and len(ids) != len(FINAL_MEMBER_NAMES):
            raise TrendlineFinalDispositionError(
                "complete final bundle requires five cohort IDs"
            )
        axis_values = dict(axes)
        if axis_values.get("evidence_completeness") not in {"COMPLETE", "INCOMPLETE"}:
            raise TrendlineFinalDispositionError("evidence completeness axis is invalid")
        if axis_values.get("structural_non_triviality") not in FINAL_STRUCTURAL_CLASSIFICATIONS:
            raise TrendlineFinalDispositionError("structural axis is invalid")
        if axis_values.get("null_relative_interaction_utility") not in FINAL_UTILITY_CLASSIFICATIONS:
            raise TrendlineFinalDispositionError("utility axis is invalid")
        if axis_values.get("geometry_sensitivity") not in FINAL_SENSITIVITY_CLASSIFICATIONS:
            raise TrendlineFinalDispositionError("sensitivity axis is invalid")
        if self.semantics_version != FINAL_DISPOSITION_BUNDLE_SEMANTICS_VERSION:
            raise TrendlineFinalDispositionError("unsupported final bundle semantics")
        object.__setattr__(self, "cohort_evidence_ids", ids)
        object.__setattr__(self, "axis_classifications", axes)
        object.__setattr__(self, "rationale_codes", rationale)
        object.__setattr__(self, "residual_limitations", limitations)
        expected = canonical_hash(self.to_dict(include_id=False), semantics_version=self.semantics_version)
        if self.final_disposition_bundle_id and self.final_disposition_bundle_id != expected:
            raise TrendlineFinalDispositionError("final bundle ID differs from content")
        object.__setattr__(self, "final_disposition_bundle_id", expected)

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = {
            "final_disposition_protocol": self.final_disposition_protocol.to_dict(),
            "final_disposition_protocol_id": self.final_disposition_protocol.protocol_id,
            "cohort_evidence_ids": list(self.cohort_evidence_ids),
            "axis_classifications": [list(value) for value in self.axis_classifications],
            "evidence_completeness": self.evidence_completeness,
            "selected_outcome": self.selected_outcome.value,
            "recommended_action": self.recommended_action.value,
            "rationale_codes": list(self.rationale_codes),
            "residual_limitations": list(self.residual_limitations),
            "semantics_version": self.semantics_version,
        }
        if include_id:
            payload["final_disposition_bundle_id"] = self.final_disposition_bundle_id
        return payload


def _aggregate_classification(cohorts: Sequence[TrendlineFinalCohortEvidence]) -> str:
    values = [row.structural_classification for row in cohorts]
    if all(value == "OBSERVED_NONTRIVIAL_STRUCTURE" for value in values):
        return "OBSERVED_NONTRIVIAL_STRUCTURE"
    if all(value == "NO_MEANINGFUL_STRUCTURE" for value in values):
        return "NO_MEANINGFUL_STRUCTURE"
    return "MIXED_STRUCTURE"


def _synthesize(
    protocol: TrendlineFinalDispositionProtocol,
    cohorts: Sequence[TrendlineFinalCohortEvidence],
    *,
    evidence_complete: bool,
) -> dict[str, Any]:
    ordered = tuple(cohorts)
    complete_scope = len(ordered) == len(protocol.member_names) and tuple(
        row.member_name for row in ordered
    ) == protocol.member_names
    complete = bool(evidence_complete and complete_scope)
    structural = _aggregate_classification(ordered) if ordered else "MIXED_STRUCTURE"
    random_support = complete and sum(row.random_member_support for row in ordered) >= protocol.cross_member_support_min_members
    density_support = complete and sum(row.density_member_support for row in ordered) >= protocol.cross_member_support_min_members
    parameter_robust = complete and sum(row.parameter_robust for row in ordered) >= protocol.cross_member_parameter_robust_min_members
    adverse_reversal = complete and sum(row.secondary_adverse_reversal for row in ordered) >= 4
    structure_nontrivial = structural == "OBSERVED_NONTRIVIAL_STRUCTURE" and complete
    excessive_churn = bool(ordered) and sum(
        row.structural_classification == "NO_MEANINGFUL_STRUCTURE" for row in ordered
    ) >= 4
    random_material = any(row.random_robust_positive_count > 0 for row in ordered)
    if random_support and density_support:
        utility_axis = "CROSS_MEMBER_SUPPORT"
    elif random_material and not density_support:
        utility_axis = "RANDOM_STRONG_DENSITY_FAILED"
    elif not random_support and not density_support:
        utility_axis = "SUPPORT_FAILED"
    else:
        utility_axis = "MIXED_SUPPORT"
    axes = {
        "evidence_completeness": "COMPLETE" if complete else "INCOMPLETE",
        "structural_non_triviality": structural,
        "null_relative_interaction_utility": utility_axis,
        "geometry_sensitivity": "PARAMETER_ROBUST" if parameter_robust else "PARAMETER_FRAGILE",
    }
    if not complete:
        outcome = TrendlineAdequacyOutcome.INSUFFICIENT_COVERAGE
        rule = "RULE_1_COVERAGE_FAILURE"
    elif structure_nontrivial and random_support and density_support and parameter_robust and not adverse_reversal:
        outcome = TrendlineAdequacyOutcome.ADEQUATE_FOR_FURTHER_RESEARCH
        rule = "RULE_2_ADEQUATE_FOR_FURTHER_RESEARCH"
    elif structure_nontrivial and (random_support or random_material) and not density_support and not parameter_robust:
        outcome = TrendlineAdequacyOutcome.UTILITY_NOT_BETTER_THAN_NAIVE_NULL
        rule = "RULE_3_UTILITY_NOT_BETTER_THAN_NAIVE_NULL"
    elif structure_nontrivial and not random_support and not density_support and not parameter_robust:
        outcome = TrendlineAdequacyOutcome.STRUCTURALLY_STABLE_BUT_NO_UTILITY
        rule = "RULE_4_STRUCTURALLY_STABLE_BUT_NO_UTILITY"
    elif excessive_churn:
        outcome = TrendlineAdequacyOutcome.EXCESSIVE_GEOMETRY_CHURN
        rule = "RULE_5_EXCESSIVE_GEOMETRY_CHURN"
    else:
        outcome = TrendlineAdequacyOutcome.INCONCLUSIVE_INSUFFICIENT_EVIDENCE
        rule = "RULE_6_RESIDUAL_AMBIGUITY"
    rationale = (
        "EVIDENCE_COMPLETE" if complete else "EVIDENCE_INCOMPLETE",
        structural,
        "RANDOM_PAIR_CROSS_MEMBER_SUPPORT" if random_support else "RANDOM_PAIR_SUPPORT_FAILED",
        "DENSITY_MATCHED_CROSS_MEMBER_SUPPORT" if density_support else "DENSITY_MATCHED_SUPPORT_FAILED",
        "PARAMETER_ROBUST" if parameter_robust else "PARAMETER_FRAGILE",
        rule,
    )
    limitations = (
        "Five bounded cohorts do not establish broad market universality.",
        "D3 and null comparisons preserve mature-model event timing.",
        "Sensitivity variants have different event populations and are descriptive.",
        "No P&L, promotion, production activation, or provider execution was evaluated.",
    )
    return {
        "complete": complete,
        "axes": _axis_tuple(axes),
        "outcome": outcome,
        "action": _action_for_outcome(outcome),
        "rationale": rationale,
        "limitations": limitations,
        "first_rule": rule,
        "random_support": random_support,
        "density_support": density_support,
        "parameter_robust": parameter_robust,
        "adverse_reversal": adverse_reversal,
        "excessive_churn": excessive_churn,
        "structure_nontrivial": structure_nontrivial,
        "random_material": random_material,
    }


def build_final_disposition_bundle(
    protocol: TrendlineFinalDispositionProtocol,
    cohorts: Sequence[TrendlineFinalCohortEvidence],
    *,
    evidence_complete: bool = True,
) -> TrendlineFinalDispositionBundle:
    """Apply frozen hierarchy and build final bundle."""

    ordered = tuple(cohorts)
    if len(set(row.member_name for row in ordered)) != len(ordered):
        raise TrendlineFinalDispositionError("duplicate cohort evidence")
    if evidence_complete and tuple(row.member_name for row in ordered) != protocol.member_names:
        raise TrendlineFinalDispositionError("complete synthesis requires exact cohort order")
    decision = _synthesize(protocol, ordered, evidence_complete=evidence_complete)
    return TrendlineFinalDispositionBundle(
        final_disposition_protocol=protocol,
        cohort_evidence_ids=tuple(row.cohort_evidence_id for row in ordered),
        axis_classifications=decision["axes"],
        selected_outcome=decision["outcome"],
        recommended_action=decision["action"],
        rationale_codes=decision["rationale"],
        residual_limitations=decision["limitations"],
        evidence_completeness=decision["complete"],
    )


def validate_final_disposition_bundle(
    bundle: TrendlineFinalDispositionBundle,
    *,
    protocol: TrendlineFinalDispositionProtocol,
    cohorts: Sequence[TrendlineFinalCohortEvidence],
    evidence_complete: bool = True,
    expected_cohort_bindings: Mapping[str, Mapping[str, str]] | None = None,
) -> None:
    """Reject manual outcome/action overrides or altered cohort evidence."""

    if not isinstance(bundle, TrendlineFinalDispositionBundle):
        raise TrendlineFinalDispositionError("final bundle must be typed")
    if bundle.final_disposition_protocol.to_dict() != protocol.to_dict():
        raise TrendlineFinalDispositionError("final protocol differs")
    if expected_cohort_bindings is not None:
        if set(expected_cohort_bindings) != {row.member_name for row in cohorts}:
            raise TrendlineFinalDispositionError("expected cohort bindings differ")
        binding_fields = (
            "d5a_member_spec_id",
            "d5a_member_evidence_id",
            "canonical_d2_bundle_id",
            "canonical_d3_bundle_id",
            "canonical_d4a_bundle_id",
            "canonical_d4b_bundle_id",
            "baseline_member_result_id",
            "dense_capsule_id",
            "sparse_capsule_id",
        )
        for row in cohorts:
            expected_binding = expected_cohort_bindings[row.member_name]
            for field in binding_fields:
                expected_value = _sha(expected_binding.get(field), name=f"expected {field}")
                if getattr(row, field) != expected_value:
                    raise TrendlineFinalDispositionError(
                        f"cohort {row.member_name} {field} differs"
                    )
    expected = build_final_disposition_bundle(
        protocol, cohorts, evidence_complete=evidence_complete
    )
    if expected.to_dict() != bundle.to_dict():
        raise TrendlineFinalDispositionError("final disposition does not match evidence")


def build_decision_matrix(
    protocol: TrendlineFinalDispositionProtocol,
    cohorts: Sequence[TrendlineFinalCohortEvidence],
    bundle: TrendlineFinalDispositionBundle,
    *,
    evidence_complete: bool = True,
) -> dict[str, Any]:
    """Return reviewable rule inputs/results; no hidden score."""

    decision = _synthesize(protocol, tuple(cohorts), evidence_complete=evidence_complete)
    rows = tuple(cohorts)
    rule_1_passed = not decision["complete"]
    rule_2_passed = (
        decision["structure_nontrivial"]
        and decision["random_support"]
        and decision["density_support"]
        and decision["parameter_robust"]
        and not decision["adverse_reversal"]
    )
    rule_3_passed = (
        decision["structure_nontrivial"]
        and (decision["random_support"] or decision["random_material"])
        and not decision["density_support"]
        and not decision["parameter_robust"]
    )
    rule_4_passed = (
        decision["structure_nontrivial"]
        and not decision["random_support"]
        and not decision["density_support"]
        and not decision["parameter_robust"]
    )
    rule_5_passed = decision["excessive_churn"]
    rule_6_passed = not any(
        (rule_1_passed, rule_2_passed, rule_3_passed, rule_4_passed, rule_5_passed)
    )
    rules = [
        {
            "rule_code": "RULE_1_COVERAGE_FAILURE",
            "condition": "evidence completeness is INCOMPLETE",
            "evidence": {
                "complete": decision["complete"],
                "incomplete": not decision["complete"],
                "cohort_count": len(rows),
            },
            "passed": rule_1_passed,
            "selected": decision["first_rule"] == "RULE_1_COVERAGE_FAILURE",
        },
        {
            "rule_code": "RULE_2_ADEQUATE_FOR_FURTHER_RESEARCH",
            "condition": "non-trivial structure, both null supports, parameter robustness, no systematic adverse reversal",
            "evidence": {
                "structure_nontrivial": decision["structure_nontrivial"],
                "random_support": decision["random_support"],
                "density_support": decision["density_support"],
                "parameter_robust": decision["parameter_robust"],
                "no_adverse_reversal": not decision["adverse_reversal"],
            },
            "passed": rule_2_passed,
            "selected": decision["first_rule"] == "RULE_2_ADEQUATE_FOR_FURTHER_RESEARCH",
        },
        {
            "rule_code": "RULE_3_UTILITY_NOT_BETTER_THAN_NAIVE_NULL",
            "condition": "non-trivial structure, random support/material evidence, density support failure, parameter fragility",
            "evidence": {
                "structure_nontrivial": decision["structure_nontrivial"],
                "random_support": decision["random_support"],
                "random_material": decision["random_material"],
                "density_support": decision["density_support"],
                "parameter_robust": decision["parameter_robust"],
            },
            "passed": rule_3_passed,
            "selected": decision["first_rule"] == "RULE_3_UTILITY_NOT_BETTER_THAN_NAIVE_NULL",
        },
        {
            "rule_code": "RULE_4_STRUCTURALLY_STABLE_BUT_NO_UTILITY",
            "condition": "non-trivial structure, neither null support, parameter fragility",
            "evidence": {
                "structure_nontrivial": decision["structure_nontrivial"],
                "random_support": decision["random_support"],
                "density_support": decision["density_support"],
                "parameter_robust": decision["parameter_robust"],
            },
            "passed": rule_4_passed,
            "selected": decision["first_rule"] == "RULE_4_STRUCTURALLY_STABLE_BUT_NO_UTILITY",
        },
        {
            "rule_code": "RULE_5_EXCESSIVE_GEOMETRY_CHURN",
            "condition": "D2 lacks persistent multi-bar episodes across most cohorts",
            "evidence": {
                "excessive_churn": decision["excessive_churn"],
                "structural_classifications": [row.structural_classification for row in rows],
            },
            "passed": rule_5_passed,
            "selected": decision["first_rule"] == "RULE_5_EXCESSIVE_GEOMETRY_CHURN",
        },
        {
            "rule_code": "RULE_6_RESIDUAL_AMBIGUITY",
            "condition": "no earlier frozen rule passed",
            "evidence": {"earlier_rules_passed": not rule_6_passed},
            "passed": rule_6_passed,
            "selected": decision["first_rule"] == "RULE_6_RESIDUAL_AMBIGUITY",
        },
    ]
    if tuple(row["rule_code"] for row in rules if row["passed"])[:1] != (decision["first_rule"],):
        raise TrendlineFinalDispositionError("decision hierarchy and rule matrix differ")
    return {
        "schema_version": "trendlines.l2d5d-decision-matrix.v1",
        "protocol_id": protocol.protocol_id,
        "thresholds": protocol.to_dict(),
        "cohort_evidence_ids": list(bundle.cohort_evidence_ids),
        "rules": rules,
        "first_selected_rule": decision["first_rule"],
        "final_outcome": bundle.selected_outcome.value,
        "recommended_action": bundle.recommended_action.value,
        "decisive_null": dict(FINAL_DECISIVE_NULL),
    }


__all__ = [
    "FINAL_AXIS_NAMES",
    "FINAL_COHORT_EVIDENCE_SEMANTICS_VERSION",
    "FINAL_DISPOSITION_BUNDLE_SEMANTICS_VERSION",
    "FINAL_DISPOSITION_PROTOCOL_SEMANTICS_VERSION",
    "FINAL_DECISION_RULE_CODES",
    "FINAL_DECISIVE_NULL",
    "FINAL_HORIZONS_BARS",
    "FINAL_MEMBER_NAMES",
    "FINAL_NULL_CELL_CLASSIFICATIONS",
    "FINAL_PRIMARY_METRICS",
    "FINAL_RECOMMENDED_ACTIONS",
    "FINAL_ROLES",
    "FINAL_SECONDARY_METRICS",
    "FINAL_STRUCTURAL_CLASSIFICATIONS",
    "FINAL_STRUCTURAL_METRICS",
    "FINAL_UTILITY_CLASSIFICATIONS",
    "TrendlineFinalCohortEvidence",
    "TrendlineFinalDispositionBundle",
    "TrendlineFinalDispositionError",
    "TrendlineFinalDispositionProtocol",
    "TrendlineFinalRecommendedAction",
    "build_decision_matrix",
    "build_final_cohort_evidence",
    "build_final_disposition_bundle",
    "build_final_disposition_protocol",
    "classify_null_cell",
    "classify_null_cells",
    "member_support",
    "validate_final_disposition_bundle",
]
