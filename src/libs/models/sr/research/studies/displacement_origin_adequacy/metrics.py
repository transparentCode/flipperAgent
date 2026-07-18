"""Paired real-band minus same-side naïve-band V2.0 metrics."""

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
    NaiveControl,
    OutcomeStatus,
    PairedOutcome,
)


def _median(values: list[float]) -> float | None:
    return None if not values else float(median(values))


def _gate(name: str, category: str, value: float | int | None, threshold: float | int) -> GateResult:
    return GateResult(name=name, category=category, value=value, threshold=threshold, operator=">=", passed=value is not None and value >= threshold)


def build_study(cases: tuple[CandidateCase, ...], controls: tuple[NaiveControl, ...], *, config: DisplacementOriginAdequacyConfig, implementation_commit: str) -> DisplacementOriginStudy:
    if type(cases) is not tuple or any(type(item) is not CandidateCase for item in cases):
        raise ContractValidationError("V2.0 metrics require CandidateCase tuple")
    if type(controls) is not tuple or any(type(item) is not NaiveControl for item in controls):
        raise ContractValidationError("V2.0 metrics require NaiveControl tuple")
    by_case = {item.case_id: item for item in cases}
    if len(by_case) != len(cases):
        raise ContractValidationError("V2.0 metrics require unique cases")
    expected_control_count = sum(case.fold is not None for case in cases) * config.controls_per_real_candidate
    if len(controls) != expected_control_count:
        raise ContractValidationError("V2.0 controls do not reconcile to in-fold candidates")
    pairs: list[PairedOutcome] = []
    for control in controls:
        real = by_case.get(control.real_case_id)
        if real is None or real.fold != control.fold:
            raise ContractValidationError("naive control references unknown or mismatched real case")
        if (
            real.confirmation_bar_id != control.confirmation_bar_id
            or real.confirmation_index != control.confirmation_index
            or real.candidate.state_key != control.candidate.state_key
            or real.candidate.available_at != control.candidate.available_at
            or real.candidate.atr_at_creation != control.candidate.atr_at_creation
            or real.zone_width_atr != control.zone_width_atr
            or real.candidate.geometry.half_width != control.candidate.geometry.half_width
            or real.candidate.candidate_id == control.candidate.candidate_id
        ):
            raise ContractValidationError("naive control matching contract is violated")
        if real.status is not OutcomeStatus.COMPLETED or control.status is not OutcomeStatus.COMPLETED or real.candidate.side is not control.candidate.side:
            continue
        assert real.outcome is not None and control.outcome is not None
        if real.outcome.quality_reference_atr is None or control.outcome.quality_reference_atr is None:
            raise ContractValidationError("completed pair has incomplete quality")
        pairs.append(PairedOutcome(real_case_id=real.case_id, control_id=control.control_id, candidate_id=real.candidate.candidate_id, fold=real.fold, side=real.candidate.side, paired_excess_quality_atr=real.outcome.quality_reference_atr - control.outcome.quality_reference_atr))
    if len({(pair.real_case_id, pair.side) for pair in pairs}) != len(pairs):
        raise ContractValidationError("primary pairs must be unique by real case and side")

    fold_metrics: list[FoldMetrics] = []
    comparable_pairs: list[float] = []
    for fold in config.folds:
        fold_cases = tuple(item for item in cases if item.fold == fold.name and item.status is OutcomeStatus.COMPLETED)
        fold_controls = tuple(item for item in controls if item.fold == fold.name and item.status is OutcomeStatus.COMPLETED)
        support_controls = tuple(item for item in fold_controls if item.candidate.side is ZoneSide.SUPPORT)
        resistance_controls = tuple(item for item in fold_controls if item.candidate.side is ZoneSide.RESISTANCE)
        fold_pairs = tuple(item for item in pairs if item.fold == fold.name)
        comparable = len(fold_pairs) >= config.gates.minimum_pairs_per_comparable_fold and len(support_controls) >= config.gates.minimum_completed_naive_controls_per_side_per_comparable_fold and len(resistance_controls) >= config.gates.minimum_completed_naive_controls_per_side_per_comparable_fold
        values = [item.paired_excess_quality_atr for item in fold_pairs] if comparable else []
        comparable_pairs.extend(values)
        fold_metrics.append(FoldMetrics(fold=fold.name, completed_real_count=len(fold_cases), support_control_count=len(support_controls), resistance_control_count=len(resistance_controls), completed_pair_count=len(fold_pairs), comparable=comparable, median_paired_excess_quality_atr=_median(values)))

    comparable_folds = tuple(item for item in fold_metrics if item.comparable)
    pooled = _median(comparable_pairs)
    positive_fraction = None if not comparable_folds else sum(item.median_paired_excess_quality_atr is not None and item.median_paired_excess_quality_atr > 0.0 for item in comparable_folds) / len(comparable_folds)
    worst = None if not comparable_folds else min(item.median_paired_excess_quality_atr for item in comparable_folds if item.median_paired_excess_quality_atr is not None)
    min_pairs = min((item.completed_pair_count for item in comparable_folds), default=None)
    min_controls = min((min(item.support_control_count, item.resistance_control_count) for item in comparable_folds), default=None)
    gates = (
        _gate("readiness.completed_pairs", "readiness", len(pairs), config.gates.minimum_completed_pairs),
        _gate("readiness.comparable_folds", "readiness", len(comparable_folds), config.gates.minimum_comparable_folds),
        _gate("readiness.pairs_per_comparable_fold", "readiness", min_pairs, config.gates.minimum_pairs_per_comparable_fold),
        _gate("readiness.naive_controls_per_side_per_comparable_fold", "readiness", min_controls, config.gates.minimum_completed_naive_controls_per_side_per_comparable_fold),
        _gate("utility.pooled_median_paired_excess_quality_atr", "utility", pooled, config.gates.minimum_pooled_median_excess_quality_atr),
        _gate("utility.positive_comparable_fold_fraction", "utility", positive_fraction, config.gates.minimum_positive_comparable_fold_fraction),
        _gate("utility.worst_comparable_fold_paired_excess_atr", "utility", worst, config.gates.minimum_worst_comparable_fold_excess_atr),
    )
    readiness = tuple(item for item in gates if item.category == "readiness")
    utility = tuple(item for item in gates if item.category == "utility")
    if any(not item.passed for item in readiness):
        disposition, reason = DisplacementOriginDisposition.INSUFFICIENT_EVIDENCE, "readiness gates failed"
    elif all(item.passed for item in utility):
        disposition, reason = DisplacementOriginDisposition.BEATS_NAIVE_NULL, "all utility gates passed after readiness"
    else:
        disposition, reason = DisplacementOriginDisposition.NOT_BETTER_THAN_NAIVE_NULL, "one or more utility gates failed after readiness"
    return DisplacementOriginStudy(implementation_commit=implementation_commit, config_hash=config.config_hash, source_bundle_id=config.source.bundle_id, source_capsule_bundle_id=config.source.source_bundle_id, source_id=config.source.source_id, cases=cases, controls=controls, pairs=tuple(pairs), fold_metrics=tuple(fold_metrics), pooled_median_paired_excess_quality_atr=pooled, positive_comparable_fold_fraction=positive_fraction, worst_comparable_fold_paired_excess_atr=worst, decision=Decision(disposition=disposition, gates=gates, reason=reason))


__all__ = ["build_study"]
