"""Paired real-wick minus same-side naïve-band V2.1 metrics."""

from __future__ import annotations

from statistics import median

from libs.models.sr.domain import ContractValidationError, ZoneSide

from .config import PivotRejectionAdequacyConfig
from .contracts import (
    CandidateCase,
    Decision,
    FoldMetrics,
    GateResult,
    NaiveControl,
    OutcomeStatus,
    PairedOutcome,
    PivotRejectionDisposition,
    PivotRejectionStudy,
)


def _median(values: list[float]) -> float | None:
    return None if not values else float(median(values))


def _gate(
    name: str, category: str, value: float | int | None, threshold: float | int
) -> GateResult:
    return GateResult(
        name, category, value, threshold, ">=", value is not None and value >= threshold
    )


def build_study(
    cases: tuple[CandidateCase, ...],
    controls: tuple[NaiveControl, ...],
    *,
    config: PivotRejectionAdequacyConfig,
    implementation_commit: str,
) -> PivotRejectionStudy:
    if (
        type(cases) is not tuple
        or any(type(item) is not CandidateCase for item in cases)
        or type(controls) is not tuple
        or any(type(item) is not NaiveControl for item in controls)
    ):
        raise ContractValidationError("V2.1 metrics require typed cases and controls")
    if len({case.case_id for case in cases}) != len(cases):
        raise ContractValidationError("V2.1 metrics require unique cases")
    in_fold = tuple(case for case in cases if case.fold is not None)
    by_case = {case.case_id: case for case in in_fold}
    expected = tuple(
        (case.case_id, side) for case in in_fold for side in config.control_side_order
    )
    observed = tuple(
        (control.real_case_id, control.candidate.side) for control in controls
    )
    if observed != expected:
        raise ContractValidationError(
            "V2.1 controls must contain exact ordered SUPPORT/RESISTANCE topology per in-fold case"
        )
    pairs: list[PairedOutcome] = []
    for control in controls:
        real = by_case.get(control.real_case_id)
        if real is None or real.fold != control.fold:
            raise ContractValidationError(
                "naive control references unknown or mismatched causal case"
            )
        if (
            real.confirmation_bar_id != control.confirmation_bar_id
            or real.confirmation_index != control.confirmation_index
            or real.candidate.state_key != control.candidate.state_key
            or real.candidate.available_at != control.candidate.available_at
            or real.candidate.atr_at_creation != control.candidate.atr_at_creation
            or real.zone_width_atr != control.zone_width_atr
            or real.prior_close != control.prior_close
            or control.candidate.geometry.center != real.prior_close
            or real.candidate.geometry.half_width
            != control.candidate.geometry.half_width
            or real.candidate.candidate_id == control.candidate.candidate_id
        ):
            raise ContractValidationError("naive control matching contract is violated")
        if (
            real.status is not OutcomeStatus.COMPLETED
            or control.status is not OutcomeStatus.COMPLETED
            or real.candidate.side is not control.candidate.side
        ):
            continue
        assert real.outcome is not None and control.outcome is not None
        if (
            real.outcome.quality_reference_atr is None
            or control.outcome.quality_reference_atr is None
        ):
            raise ContractValidationError("completed pair has incomplete quality")
        pairs.append(
            PairedOutcome(
                real_case_id=real.case_id,
                control_id=control.control_id,
                candidate_id=real.candidate.candidate_id,
                fold=real.fold,
                side=real.candidate.side,
                paired_excess_quality_atr=real.outcome.quality_reference_atr
                - control.outcome.quality_reference_atr,
            )
        )
    if len({(item.real_case_id, item.side) for item in pairs}) != len(pairs):
        raise ContractValidationError(
            "primary pairs must be unique by real case and side"
        )
    fold_metrics: list[FoldMetrics] = []
    comparable_values: list[float] = []
    for fold in config.folds:
        fold_cases = tuple(
            item
            for item in cases
            if item.fold == fold.name and item.status is OutcomeStatus.COMPLETED
        )
        fold_controls = tuple(
            item
            for item in controls
            if item.fold == fold.name and item.status is OutcomeStatus.COMPLETED
        )
        support = tuple(
            item for item in fold_controls if item.candidate.side is ZoneSide.SUPPORT
        )
        resistance = tuple(
            item for item in fold_controls if item.candidate.side is ZoneSide.RESISTANCE
        )
        fold_pairs = tuple(item for item in pairs if item.fold == fold.name)
        comparable = (
            len(fold_pairs) >= config.gates.minimum_pairs_per_comparable_fold
            and len(support)
            >= config.gates.minimum_completed_naive_controls_per_side_per_comparable_fold
            and len(resistance)
            >= config.gates.minimum_completed_naive_controls_per_side_per_comparable_fold
        )
        values = (
            [item.paired_excess_quality_atr for item in fold_pairs]
            if comparable
            else []
        )
        comparable_values.extend(values)
        fold_metrics.append(
            FoldMetrics(
                fold.name,
                len(fold_cases),
                len(support),
                len(resistance),
                len(fold_pairs),
                comparable,
                _median(values),
            )
        )
    comparable = tuple(item for item in fold_metrics if item.comparable)
    pooled = _median(comparable_values)
    positive = (
        None
        if not comparable
        else sum(
            item.median_paired_excess_quality_atr is not None
            and item.median_paired_excess_quality_atr > 0.0
            for item in comparable
        )
        / len(comparable)
    )
    worst = (
        None
        if not comparable
        else min(
            item.median_paired_excess_quality_atr
            for item in comparable
            if item.median_paired_excess_quality_atr is not None
        )
    )
    minimum_pairs = min(
        (item.completed_pair_count for item in comparable), default=None
    )
    minimum_controls = min(
        (
            min(item.support_control_count, item.resistance_control_count)
            for item in comparable
        ),
        default=None,
    )
    gates = (
        _gate(
            "readiness.completed_pairs",
            "readiness",
            len(pairs),
            config.gates.minimum_completed_pairs,
        ),
        _gate(
            "readiness.comparable_folds",
            "readiness",
            len(comparable),
            config.gates.minimum_comparable_folds,
        ),
        _gate(
            "readiness.pairs_per_comparable_fold",
            "readiness",
            minimum_pairs,
            config.gates.minimum_pairs_per_comparable_fold,
        ),
        _gate(
            "readiness.naive_controls_per_side_per_comparable_fold",
            "readiness",
            minimum_controls,
            config.gates.minimum_completed_naive_controls_per_side_per_comparable_fold,
        ),
        _gate(
            "utility.pooled_median_paired_excess_quality_atr",
            "utility",
            pooled,
            config.gates.minimum_pooled_median_excess_quality_atr,
        ),
        _gate(
            "utility.positive_comparable_fold_fraction",
            "utility",
            positive,
            config.gates.minimum_positive_comparable_fold_fraction,
        ),
        _gate(
            "utility.worst_comparable_fold_paired_excess_atr",
            "utility",
            worst,
            config.gates.minimum_worst_comparable_fold_excess_atr,
        ),
    )
    readiness, utility = (
        tuple(item for item in gates if item.category == "readiness"),
        tuple(item for item in gates if item.category == "utility"),
    )
    if any(not item.passed for item in readiness):
        disposition, reason = (
            PivotRejectionDisposition.INSUFFICIENT_EVIDENCE,
            "readiness gates failed",
        )
    elif all(item.passed for item in utility):
        disposition, reason = (
            PivotRejectionDisposition.BEATS_NAIVE_NULL,
            "all utility gates passed after readiness",
        )
    else:
        disposition, reason = (
            PivotRejectionDisposition.NOT_BETTER_THAN_NAIVE_NULL,
            "one or more utility gates failed after readiness",
        )
    return PivotRejectionStudy(
        implementation_commit,
        config.config_hash,
        config.source.bundle_id,
        config.source.source_bundle_id,
        config.source.source_id,
        cases,
        controls,
        tuple(pairs),
        tuple(fold_metrics),
        pooled,
        positive,
        worst,
        Decision(disposition, gates, reason),
    )


__all__ = ["build_study"]
