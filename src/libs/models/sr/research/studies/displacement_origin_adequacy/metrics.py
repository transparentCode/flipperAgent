"""Readiness and utility assessment for frozen SR-V2.0 cases."""

from __future__ import annotations

from statistics import median

from libs.models.sr.domain import ContractValidationError, ZoneSide

from .config import DisplacementOriginAdequacyConfig
from .contracts import (
    CandidateCase,
    Decision,
    DisplacementOriginDisposition,
    DisplacementOriginStudy,
    FoldMetrics,
    GateResult,
    MatchedControl,
    OutcomeStatus,
)


def _median(values: list[float]) -> float | None:
    return None if not values else float(median(values))


def _gate(
    name: str,
    category: str,
    value: float | int | None,
    threshold: float | int,
) -> GateResult:
    return GateResult(
        name=name,
        category=category,
        value=value,
        threshold=threshold,
        operator=">=",
        passed=value is not None and value >= threshold,
    )


def build_study(
    cases: tuple[CandidateCase, ...],
    controls: tuple[MatchedControl, ...],
    *,
    config: DisplacementOriginAdequacyConfig,
    implementation_commit: str,
) -> DisplacementOriginStudy:
    """Compare completed raw-zone revisits with matched causal null controls."""
    if type(cases) is not tuple or any(type(item) is not CandidateCase for item in cases):
        raise ContractValidationError("V2.0 metrics require CandidateCase tuple")
    if type(controls) is not tuple or any(type(item) is not MatchedControl for item in controls):
        raise ContractValidationError("V2.0 metrics require MatchedControl tuple")
    if len({item.case_id for item in cases}) != len(cases):
        raise ContractValidationError("V2.0 metrics require unique cases")
    completed = tuple(item for item in cases if item.status is OutcomeStatus.COMPLETED)
    completed_ids = {item.case_id for item in completed}
    if any(item.real_case_id not in completed_ids for item in controls):
        raise ContractValidationError("matched control references an incomplete real case")

    fold_metrics: list[FoldMetrics] = []
    comparable_excess: list[float] = []
    for fold in config.folds:
        fold_cases = tuple(item for item in completed if item.fold == fold.name)
        fold_controls = tuple(item for item in controls if item.outcome.fold == fold.name)
        support_controls = tuple(item for item in fold_controls if item.outcome.side is ZoneSide.SUPPORT)
        resistance_controls = tuple(item for item in fold_controls if item.outcome.side is ZoneSide.RESISTANCE)
        support_median = _median([item.outcome.quality_reference_atr for item in support_controls])
        resistance_median = _median([item.outcome.quality_reference_atr for item in resistance_controls])
        comparable = (
            len(fold_cases) >= config.gates.minimum_real_outcomes_per_comparable_fold
            and len(support_controls) >= config.gates.minimum_controls_per_side_per_comparable_fold
            and len(resistance_controls) >= config.gates.minimum_controls_per_side_per_comparable_fold
        )
        fold_excess: list[float] = []
        if comparable:
            for case in fold_cases:
                assert case.outcome is not None and case.outcome.quality_reference_atr is not None
                null_median = support_median if case.candidate.side is ZoneSide.SUPPORT else resistance_median
                if null_median is None:
                    raise ContractValidationError("comparable V2.0 case lacks same-side null median")
                matches = tuple(
                    item
                    for item in fold_controls
                    if item.real_case_id == case.case_id
                    and item.outcome.side is case.candidate.side
                    and item.outcome.anchor_at == case.outcome.first_touch_at
                    and item.outcome.reference_atr_14 == case.outcome.reference_atr_14
                    and item.zone_width_atr == case.zone_width_atr
                )
                if len(matches) != 1:
                    raise ContractValidationError("completed case must have exactly one matched same-side control")
                excess = case.outcome.quality_reference_atr - null_median
                fold_excess.append(excess)
                comparable_excess.append(excess)
        fold_metrics.append(
            FoldMetrics(
                fold=fold.name,
                completed_real_count=len(fold_cases),
                support_control_count=len(support_controls),
                resistance_control_count=len(resistance_controls),
                comparable=comparable,
                median_excess_quality_atr=_median(fold_excess),
            )
        )

    comparable = tuple(item for item in fold_metrics if item.comparable)
    pooled = _median(comparable_excess)
    positive_fraction = (
        None
        if not comparable
        else sum(item.median_excess_quality_atr is not None and item.median_excess_quality_atr > 0.0 for item in comparable) / len(comparable)
    )
    worst = (
        None
        if not comparable
        else min(
            item.median_excess_quality_atr
            for item in comparable
            if item.median_excess_quality_atr is not None
        )
    )
    min_real = min((item.completed_real_count for item in comparable), default=None)
    min_controls = min(
        (min(item.support_control_count, item.resistance_control_count) for item in comparable),
        default=None,
    )
    gates = (
        _gate("readiness.completed_real_outcomes", "readiness", len(completed), config.gates.minimum_completed_real_outcomes),
        _gate("readiness.comparable_folds", "readiness", len(comparable), config.gates.minimum_comparable_folds),
        _gate("readiness.real_outcomes_per_comparable_fold", "readiness", min_real, config.gates.minimum_real_outcomes_per_comparable_fold),
        _gate("readiness.controls_per_side_per_comparable_fold", "readiness", min_controls, config.gates.minimum_controls_per_side_per_comparable_fold),
        _gate("utility.pooled_median_excess_quality_atr", "utility", pooled, config.gates.minimum_pooled_median_excess_quality_atr),
        _gate("utility.positive_comparable_fold_fraction", "utility", positive_fraction, config.gates.minimum_positive_comparable_fold_fraction),
        _gate("utility.worst_comparable_fold_excess_atr", "utility", worst, config.gates.minimum_worst_comparable_fold_excess_atr),
    )
    readiness = tuple(item for item in gates if item.category == "readiness")
    utility = tuple(item for item in gates if item.category == "utility")
    if any(not item.passed for item in readiness):
        disposition = DisplacementOriginDisposition.INSUFFICIENT_EVIDENCE
        reason = "readiness gates failed"
    elif all(item.passed for item in utility):
        disposition = DisplacementOriginDisposition.BEATS_NAIVE_NULL
        reason = "all utility gates passed after readiness"
    else:
        disposition = DisplacementOriginDisposition.NOT_BETTER_THAN_NAIVE_NULL
        reason = "one or more utility gates failed after readiness"
    return DisplacementOriginStudy(
        implementation_commit=implementation_commit,
        config_hash=config.config_hash,
        source_bundle_id=config.source.bundle_id,
        source_id=config.source.source_id,
        cases=cases,
        controls=controls,
        fold_metrics=tuple(fold_metrics),
        pooled_median_excess_quality_atr=pooled,
        positive_comparable_fold_fraction=positive_fraction,
        worst_comparable_fold_excess_atr=worst,
        decision=Decision(disposition=disposition, gates=gates, reason=reason),
    )


__all__ = ["build_study"]
