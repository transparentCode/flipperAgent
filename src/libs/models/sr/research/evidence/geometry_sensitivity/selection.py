"""Frozen V1.8 eligibility, quality, guardrail, stability, and selection rules."""

from __future__ import annotations

from statistics import median
from typing import Any

from libs.models.sr.domain.contracts import ContractValidationError

from .candidate_grid import baseline_candidate, build_candidate_grid, orthogonal_neighbors
from .config import GeometrySensitivityConfig
from .contracts import (
    APPROVED_ASSETS,
    CandidateDecision,
    CandidateEvaluation,
    GeometryDisposition,
    StudyGate,
)


def _gate(name: str, passed: bool, value: Any, threshold: Any, reason: str, *, asset: str | None = None, fold: str | None = None) -> StudyGate:
    return StudyGate(name=name, passed=passed, value=value, threshold=threshold, reason=reason, asset=asset, fold=fold)


def _delta(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or baseline is None:
        return None
    return candidate - baseline


def _ratio(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or baseline is None or baseline <= 0:
        return None
    return candidate / baseline


def _defined(value: float | None) -> bool:
    return value is not None


def _asset_fold_values(candidate: CandidateEvaluation, baseline: CandidateEvaluation) -> tuple[tuple[str, str, float | None], ...]:
    return candidate.asset_fold_deltas if candidate.asset_fold_deltas else ()


def _preliminary_decision(
    candidate: CandidateEvaluation,
    baseline: CandidateEvaluation,
    config: GeometrySensitivityConfig,
) -> tuple[CandidateDecision, tuple[StudyGate, ...]]:
    threshold = config.selection
    gates: list[StudyGate] = []
    gates.extend(candidate.eligibility_gates)
    comparable_by_asset: list[tuple[str, int]] = []
    comparable_values: list[float] = []
    for asset in APPROVED_ASSETS:
        values = tuple(
            value for item_asset, _fold, value in _asset_fold_values(candidate, baseline)
            if item_asset == asset and value is not None
        )
        comparable_by_asset.append((asset, len(values)))
        comparable_values.extend(values)
        gates.append(_gate(
            "comparability.folds_per_asset",
            len(values) >= threshold.minimum_comparable_folds_per_asset,
            len(values), threshold.minimum_comparable_folds_per_asset,
            "asset has enough comparable folds" if len(values) >= threshold.minimum_comparable_folds_per_asset else "asset has too few comparable folds",
            asset=asset,
        ))
    gates.append(_gate(
        "comparability.asset_fold_units",
        len(comparable_values) >= threshold.minimum_comparable_asset_fold_units,
        len(comparable_values), threshold.minimum_comparable_asset_fold_units,
        "cohort has enough comparable asset-fold units" if len(comparable_values) >= threshold.minimum_comparable_asset_fold_units else "cohort has too few comparable asset-fold units",
    ))
    pooled_deltas = tuple(value for _asset, value in candidate.asset_pooled_deltas)
    median_asset_delta = None if any(value is None for value in pooled_deltas) else median(tuple(value for value in pooled_deltas if value is not None))
    micro_delta = _delta(candidate.micro.median_quality_reference_atr, baseline.micro.median_quality_reference_atr)
    positive_count = sum(value is not None and value > 0 for value in pooled_deltas)
    worst_delta = None if any(value is None for value in pooled_deltas) else min(value for value in pooled_deltas if value is not None)
    fold_win_fraction = None if not comparable_values else sum(value > 0 for value in comparable_values) / len(comparable_values)
    quality_gates = (
        _gate("quality.median_asset_delta", median_asset_delta is not None and median_asset_delta >= threshold.minimum_median_asset_delta, median_asset_delta, threshold.minimum_median_asset_delta, "median asset delta meets threshold" if median_asset_delta is not None and median_asset_delta >= threshold.minimum_median_asset_delta else "median asset delta is undefined or below threshold"),
        _gate("quality.micro_delta", micro_delta is not None and micro_delta >= threshold.minimum_micro_delta, micro_delta, threshold.minimum_micro_delta, "micro delta meets threshold" if micro_delta is not None and micro_delta >= threshold.minimum_micro_delta else "micro delta is undefined or below threshold"),
        _gate("quality.positive_asset_count", positive_count >= threshold.minimum_positive_asset_count, positive_count, threshold.minimum_positive_asset_count, "enough assets improve" if positive_count >= threshold.minimum_positive_asset_count else "too few assets improve"),
        _gate("quality.worst_asset_delta", worst_delta is not None and worst_delta >= threshold.minimum_worst_asset_delta, worst_delta, threshold.minimum_worst_asset_delta, "worst asset is within threshold" if worst_delta is not None and worst_delta >= threshold.minimum_worst_asset_delta else "worst asset delta is undefined or below threshold"),
        _gate("quality.asset_fold_win_fraction", fold_win_fraction is not None and fold_win_fraction >= threshold.minimum_asset_fold_win_fraction, fold_win_fraction, threshold.minimum_asset_fold_win_fraction, "fold win fraction meets threshold" if fold_win_fraction is not None and fold_win_fraction >= threshold.minimum_asset_fold_win_fraction else "fold win fraction is undefined or below threshold"),
    )
    gates.extend(quality_gates)
    invalidation_delta = _delta(candidate.micro.invalidation_rate, baseline.micro.invalidation_rate)
    density_ratio = _ratio(candidate.micro.zone_creation_density_per_100_bars, baseline.micro.zone_creation_density_per_100_bars)
    churn_delta = _delta(candidate.micro.churn_rate, baseline.micro.churn_rate)
    censor_delta = _delta(candidate.micro.right_censoring_rate, baseline.micro.right_censoring_rate)
    guardrail_gates = (
        _gate("guardrail.invalidation_rate_delta", invalidation_delta is not None and invalidation_delta <= threshold.maximum_invalidation_rate_delta, invalidation_delta, threshold.maximum_invalidation_rate_delta, "invalidation delta is within guardrail" if invalidation_delta is not None and invalidation_delta <= threshold.maximum_invalidation_rate_delta else "invalidation delta is undefined or exceeds guardrail"),
        _gate("guardrail.zone_creation_density_ratio", density_ratio is not None and threshold.minimum_zone_creation_density_ratio <= density_ratio <= threshold.maximum_zone_creation_density_ratio, density_ratio, [threshold.minimum_zone_creation_density_ratio, threshold.maximum_zone_creation_density_ratio], "density ratio is within guardrail" if density_ratio is not None and threshold.minimum_zone_creation_density_ratio <= density_ratio <= threshold.maximum_zone_creation_density_ratio else "density ratio is undefined or outside guardrail"),
        _gate("guardrail.churn_rate_delta", churn_delta is not None and churn_delta <= threshold.maximum_churn_rate_delta, churn_delta, threshold.maximum_churn_rate_delta, "churn delta is within guardrail" if churn_delta is not None and churn_delta <= threshold.maximum_churn_rate_delta else "churn delta is undefined or exceeds guardrail"),
        _gate("guardrail.right_censoring_rate_delta", censor_delta is not None and censor_delta <= threshold.maximum_right_censoring_rate_delta, censor_delta, threshold.maximum_right_censoring_rate_delta, "right-censoring delta is within guardrail" if censor_delta is not None and censor_delta <= threshold.maximum_right_censoring_rate_delta else "right-censoring delta is undefined or exceeds guardrail"),
    )
    gates.extend(guardrail_gates)
    fully_evaluable = candidate.fully_evaluable and all(gate.passed for gate in gates if gate.name.startswith("comparability."))
    decision = CandidateDecision(
        candidate_id=candidate.candidate.candidate_id,
        is_baseline=False,
        fully_evaluable=fully_evaluable,
        passes_quality=all(gate.passed for gate in quality_gates),
        passes_guardrails=all(gate.passed for gate in guardrail_gates),
        passes_stability=False,
        gates=tuple(gates),
        median_asset_delta=median_asset_delta,
        micro_delta=micro_delta,
        positive_asset_count=positive_count,
        worst_asset_delta=worst_delta,
        comparable_asset_fold_count=len(comparable_values),
        asset_fold_win_fraction=fold_win_fraction,
        comparable_folds_by_asset=tuple(comparable_by_asset),
        neighbor_support_ids=(),
    )
    return decision, tuple(guardrail_gates)


def _baseline_decision(evaluation: CandidateEvaluation) -> CandidateDecision:
    return CandidateDecision(
        candidate_id=evaluation.candidate.candidate_id,
        is_baseline=True,
        fully_evaluable=evaluation.fully_evaluable,
        passes_quality=True,
        passes_guardrails=True,
        passes_stability=True,
        gates=(_gate("baseline.reference", evaluation.fully_evaluable, evaluation.fully_evaluable, True, "validated V1.7 baseline reference" if evaluation.fully_evaluable else "baseline aggregate eligibility failed"),),
        median_asset_delta=0.0,
        micro_delta=0.0,
        positive_asset_count=0,
        worst_asset_delta=0.0,
        comparable_asset_fold_count=0,
        asset_fold_win_fraction=None,
        comparable_folds_by_asset=tuple((asset, 0) for asset in APPROVED_ASSETS),
        neighbor_support_ids=(),
    )


def select_candidates(
    evaluations: tuple[CandidateEvaluation, ...],
    *,
    config: GeometrySensitivityConfig,
) -> tuple[tuple[CandidateDecision, ...], str | None, GeometryDisposition]:
    """Apply all frozen gates and return canonical decisions plus one winner."""
    if type(evaluations) is not tuple or not evaluations:
        raise ContractValidationError("candidate evaluations must be a non-empty tuple")
    baseline_candidate()
    if tuple(item.candidate.candidate_id for item in evaluations) != tuple(item.candidate_id for item in build_candidate_grid()):
        raise ContractValidationError("candidate evaluations are not the canonical nine-candidate matrix")
    baseline_eval = next(item for item in evaluations if item.candidate.baseline)
    if not baseline_eval.fully_evaluable:
        raise ContractValidationError("validated baseline is not fully evaluable")
    preliminary: dict[str, CandidateDecision] = {}
    guardrails: dict[str, tuple[StudyGate, ...]] = {}
    for evaluation in evaluations:
        if evaluation.candidate.baseline:
            preliminary[evaluation.candidate.candidate_id] = _baseline_decision(evaluation)
        else:
            decision, records = _preliminary_decision(evaluation, baseline_eval, config)
            preliminary[evaluation.candidate.candidate_id] = decision
            guardrails[evaluation.candidate.candidate_id] = records
    final: list[CandidateDecision] = []
    for evaluation in evaluations:
        candidate = evaluation.candidate
        current = preliminary[candidate.candidate_id]
        if candidate.baseline:
            final.append(current)
            continue
        support: list[str] = []
        for neighbor in orthogonal_neighbors(candidate):
            decision = preliminary[neighbor.candidate_id]
            if decision.fully_evaluable and not decision.is_baseline and decision.median_asset_delta is not None and decision.median_asset_delta > 0 and decision.micro_delta is not None and decision.micro_delta > 0 and decision.passes_guardrails:
                support.append(neighbor.candidate_id)
        support_tuple = tuple(sorted(support))
        stability = _gate("stability.orthogonal_neighbor", bool(support_tuple), list(support_tuple), "at least one fully evaluable improving orthogonal challenger", "orthogonal neighbor supports local stability" if support_tuple else "no fully evaluable improving orthogonal neighbor")
        gates = tuple(item for item in current.gates if not item.name.startswith("stability.")) + (stability,)
        final.append(CandidateDecision(
            candidate_id=current.candidate_id,
            is_baseline=False,
            fully_evaluable=current.fully_evaluable,
            passes_quality=current.passes_quality,
            passes_guardrails=current.passes_guardrails,
            passes_stability=bool(support_tuple),
            gates=gates,
            median_asset_delta=current.median_asset_delta,
            micro_delta=current.micro_delta,
            positive_asset_count=current.positive_asset_count,
            worst_asset_delta=current.worst_asset_delta,
            comparable_asset_fold_count=current.comparable_asset_fold_count,
            asset_fold_win_fraction=current.asset_fold_win_fraction,
            comparable_folds_by_asset=current.comparable_folds_by_asset,
            neighbor_support_ids=support_tuple,
        ))
    decisions = tuple(final)
    challengers = tuple(item for item in decisions if not item.is_baseline)
    fully = tuple(item for item in challengers if item.fully_evaluable)
    passing = tuple(item for item in fully if item.passes_all_gates)
    if passing:
        by_id = {item.candidate.candidate_id: item.candidate for item in evaluations}
        winner = sorted(
            passing,
            key=lambda item: (
                -(item.median_asset_delta if item.median_asset_delta is not None else float("-inf")),
                -(item.micro_delta if item.micro_delta is not None else float("-inf")),
                -(item.asset_fold_win_fraction if item.asset_fold_win_fraction is not None else float("-inf")),
                by_id[item.candidate_id].manhattan_distance,
                by_id[item.candidate_id].pivot_span_bars,
                by_id[item.candidate_id].zone_half_width_atr,
                item.candidate_id,
            ),
        )[0]
        return decisions, winner.candidate_id, GeometryDisposition.SELECT_GLOBAL_CHALLENGER
    if not fully:
        return decisions, None, GeometryDisposition.INSUFFICIENT_EVIDENCE
    return decisions, None, GeometryDisposition.RETAIN_BASELINE_GEOMETRY


select_geometry = select_candidates


__all__ = ["select_candidates", "select_geometry"]
