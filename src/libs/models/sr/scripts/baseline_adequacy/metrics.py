"""Null medians, real-to-null comparisons, and frozen V1.9 gates."""

from __future__ import annotations

from statistics import median

from libs.models.sr.domain.contracts import ContractValidationError, ZoneSide

from .contracts import (
    AdequacyAggregateMetrics,
    AdequacyGateResult,
    AdequacyResult,
    BaselineAdequacyConfig,
    BaselineAdequacyDecision,
    BaselineAdequacyDisposition,
    ControlBuildResult,
    FoldAdequacyMetrics,
    FoldSideNull,
    RealOutcomeComparison,
    RealOutcomeRecord,
)


def _median(values: list[float]) -> float | None:
    return None if not values else float(median(values))


def _fold_name_set(config: BaselineAdequacyConfig) -> tuple[str, ...]:
    return tuple(fold.name for fold in config.folds)


def _gate(
    name: str,
    category: str,
    value: float | int | None,
    threshold: float | int | None,
    *,
    passed: bool,
    operator: str = ">=",
    reason: str,
    fold: str | None = None,
) -> AdequacyGateResult:
    return AdequacyGateResult(name=name, category=category, passed=passed, value=value, threshold=threshold, operator=operator, reason=reason, fold=fold)


def _comparison_median(comparisons: tuple[RealOutcomeComparison, ...], side: ZoneSide) -> float | None:
    values = [item.excess_quality for item in comparisons if item.side is side]
    return _median(values)


def evaluate_adequacy(
    real_outcomes: tuple[RealOutcomeRecord, ...],
    controls: ControlBuildResult,
    *,
    config: BaselineAdequacyConfig,
) -> AdequacyResult:
    """Evaluate completed real outcomes against same-fold, same-side nulls."""
    if type(real_outcomes) is not tuple or any(type(item) is not RealOutcomeRecord for item in real_outcomes):
        raise ContractValidationError("real outcomes must be a tuple of RealOutcomeRecord")
    if type(controls) is not ControlBuildResult:
        raise ContractValidationError("controls must be exactly ControlBuildResult")
    if len({item.record_id for item in real_outcomes}) != len(real_outcomes):
        raise ContractValidationError("real outcome records must be unique")
    fold_names = _fold_name_set(config)
    if any(item.fold not in fold_names for item in real_outcomes):
        raise ContractValidationError("real outcome references an unknown fold")

    nulls: list[FoldSideNull] = []
    fold_metrics: list[FoldAdequacyMetrics] = []
    all_comparisons: list[RealOutcomeComparison] = []
    comparable_metrics: list[FoldAdequacyMetrics] = []
    for fold in config.folds:
        fold_controls = tuple(item for item in controls.outcomes if item.fold == fold.name)
        support_controls = tuple(item for item in fold_controls if item.side is ZoneSide.SUPPORT)
        resistance_controls = tuple(item for item in fold_controls if item.side is ZoneSide.RESISTANCE)
        if len(support_controls) != len(resistance_controls):
            raise ContractValidationError("fold-side control counts must be equal")
        support_null = FoldSideNull(fold.name, ZoneSide.SUPPORT, len(support_controls), _median([item.quality_reference_atr for item in support_controls]), tuple(item.control_id for item in support_controls))
        resistance_null = FoldSideNull(fold.name, ZoneSide.RESISTANCE, len(resistance_controls), _median([item.quality_reference_atr for item in resistance_controls]), tuple(item.control_id for item in resistance_controls))
        nulls.extend((support_null, resistance_null))

        completed_real = tuple(item for item in real_outcomes if item.fold == fold.name and item.outcome.completed)
        support_real = tuple(item for item in completed_real if item.outcome.side is ZoneSide.SUPPORT)
        resistance_real = tuple(item for item in completed_real if item.outcome.side is ZoneSide.RESISTANCE)
        required_medians = (
            not support_real or support_null.median_quality is not None,
            not resistance_real or resistance_null.median_quality is not None,
        )
        comparable = len(completed_real) >= 4 and len(support_controls) >= 4 and len(resistance_controls) >= 4 and all(required_medians)
        comparisons: list[RealOutcomeComparison] = []
        if comparable:
            for record in completed_real:
                null_median = support_null.median_quality if record.outcome.side is ZoneSide.SUPPORT else resistance_null.median_quality
                if null_median is None or record.outcome.quality_reference_atr is None:
                    raise ContractValidationError("comparable real outcome lacks same-side null or quality")
                comparisons.append(RealOutcomeComparison(record.record_id, fold.name, record.outcome.side, record.outcome.quality_reference_atr, null_median, record.outcome.quality_reference_atr - null_median))
        comparison_tuple = tuple(comparisons)
        metric = FoldAdequacyMetrics(
            fold=fold.name,
            completed_real_count=len(completed_real),
            support_completed_count=len(support_real),
            resistance_completed_count=len(resistance_real),
            support_control_count=len(support_controls),
            resistance_control_count=len(resistance_controls),
            support_null_median=support_null.median_quality,
            resistance_null_median=resistance_null.median_quality,
            comparable=comparable,
            fold_median_excess=_median([item.excess_quality for item in comparison_tuple]),
            support_median_excess=_comparison_median(comparison_tuple, ZoneSide.SUPPORT),
            resistance_median_excess=_comparison_median(comparison_tuple, ZoneSide.RESISTANCE),
            comparisons=comparison_tuple,
        )
        fold_metrics.append(metric)
        if comparable:
            comparable_metrics.append(metric)
            all_comparisons.extend(comparison_tuple)

    total_completed = sum(item.outcome.completed for item in real_outcomes)
    total_censored = sum(item.outcome.right_censored for item in real_outcomes)
    comparable_comparisons = tuple(all_comparisons)
    pooled_real_values = [item.outcome.quality_reference_atr for item in real_outcomes if item.outcome.completed and item.outcome.quality_reference_atr is not None]
    pooled_support_controls = [item.quality_reference_atr for item in controls.outcomes if item.side is ZoneSide.SUPPORT]
    pooled_resistance_controls = [item.quality_reference_atr for item in controls.outcomes if item.side is ZoneSide.RESISTANCE]
    aggregate = AdequacyAggregateMetrics(
        total_real_outcomes=len(real_outcomes),
        total_completed_real_outcomes=total_completed,
        total_right_censored_real_outcomes=total_censored,
        completed_real_count=len(comparable_comparisons),
        comparable_fold_count=len(comparable_metrics),
        pooled_median_excess_quality=_median([item.excess_quality for item in comparable_comparisons]),
        positive_comparable_fold_fraction=None if not comparable_metrics else sum(item.fold_median_excess is not None and item.fold_median_excess > 0 for item in comparable_metrics) / len(comparable_metrics),
        worst_comparable_fold_excess=None if not comparable_metrics else min(item.fold_median_excess for item in comparable_metrics if item.fold_median_excess is not None),
        pooled_real_baseline_median_quality=_median(pooled_real_values),
        pooled_control_support_median_quality=_median(pooled_support_controls),
        pooled_control_resistance_median_quality=_median(pooled_resistance_controls),
    )

    thresholds = config.gates
    gates: list[AdequacyGateResult] = []
    gates.append(_gate("sample.completed_real_outcomes", "sample", aggregate.completed_real_count, thresholds.minimum_completed_real_outcomes, passed=aggregate.completed_real_count >= thresholds.minimum_completed_real_outcomes, reason="mapped completed real outcomes meet sample minimum" if aggregate.completed_real_count >= thresholds.minimum_completed_real_outcomes else "mapped completed real outcomes are below sample minimum"))
    gates.append(_gate("comparability.comparable_folds", "comparability", aggregate.comparable_fold_count, thresholds.minimum_comparable_folds, passed=aggregate.comparable_fold_count >= thresholds.minimum_comparable_folds, reason="enough comparable folds" if aggregate.comparable_fold_count >= thresholds.minimum_comparable_folds else "too few comparable folds"))
    min_real = None if not comparable_metrics else min(item.completed_real_count for item in comparable_metrics)
    gates.append(_gate("comparability.minimum_real_outcomes_per_comparable_fold", "comparability", min_real, thresholds.minimum_real_outcomes_per_comparable_fold, passed=min_real is not None and min_real >= thresholds.minimum_real_outcomes_per_comparable_fold, reason="every comparable fold has enough real outcomes" if min_real is not None and min_real >= thresholds.minimum_real_outcomes_per_comparable_fold else "comparable fold real-outcome denominator is unavailable or too small"))
    min_controls = None if not comparable_metrics else min(min(item.support_control_count, item.resistance_control_count) for item in comparable_metrics)
    gates.append(_gate("comparability.minimum_controls_per_side_per_comparable_fold", "comparability", min_controls, thresholds.minimum_controls_per_side_per_comparable_fold, passed=min_controls is not None and min_controls >= thresholds.minimum_controls_per_side_per_comparable_fold, reason="every comparable fold has enough controls per side" if min_controls is not None and min_controls >= thresholds.minimum_controls_per_side_per_comparable_fold else "comparable fold control denominator is unavailable or too small"))
    gates.append(_gate("quality.pooled_median_excess_quality_atr", "quality", aggregate.pooled_median_excess_quality, thresholds.minimum_pooled_median_excess_quality_atr, passed=aggregate.pooled_median_excess_quality is not None and aggregate.pooled_median_excess_quality >= thresholds.minimum_pooled_median_excess_quality_atr, reason="pooled excess meets adequacy threshold" if aggregate.pooled_median_excess_quality is not None and aggregate.pooled_median_excess_quality >= thresholds.minimum_pooled_median_excess_quality_atr else "pooled excess is below or undefined"))
    gates.append(_gate("quality.positive_comparable_fold_fraction", "quality", aggregate.positive_comparable_fold_fraction, thresholds.minimum_positive_comparable_fold_fraction, passed=aggregate.positive_comparable_fold_fraction is not None and aggregate.positive_comparable_fold_fraction >= thresholds.minimum_positive_comparable_fold_fraction, reason="positive-fold fraction meets adequacy threshold" if aggregate.positive_comparable_fold_fraction is not None and aggregate.positive_comparable_fold_fraction >= thresholds.minimum_positive_comparable_fold_fraction else "positive-fold fraction is below or undefined"))
    gates.append(_gate("quality.worst_comparable_fold_excess_atr", "quality", aggregate.worst_comparable_fold_excess, thresholds.minimum_worst_comparable_fold_excess_atr, passed=aggregate.worst_comparable_fold_excess is not None and aggregate.worst_comparable_fold_excess >= thresholds.minimum_worst_comparable_fold_excess_atr, reason="worst fold meets adequacy threshold" if aggregate.worst_comparable_fold_excess is not None and aggregate.worst_comparable_fold_excess >= thresholds.minimum_worst_comparable_fold_excess_atr else "worst fold is below or undefined"))
    for metric in fold_metrics:
        gates.append(_gate(f"diagnostic.fold.{metric.fold}.comparable", "diagnostic", 1 if metric.comparable else 0, 1, passed=metric.comparable, operator="==", reason="fold comparability diagnostic" if metric.comparable else "fold failed comparability diagnostic", fold=metric.fold))

    authoritative = tuple(item for item in gates if item.category in {"sample", "comparability"})
    quality = tuple(item for item in gates if item.category == "quality")
    if any(not item.passed for item in authoritative) or not authoritative:
        disposition = BaselineAdequacyDisposition.INSUFFICIENT_EVIDENCE
        reason = "sample or comparability gates failed"
    elif all(item.passed for item in quality):
        disposition = BaselineAdequacyDisposition.BASELINE_BEATS_NAIVE_NULL
        reason = "all three adequacy gates passed"
    else:
        disposition = BaselineAdequacyDisposition.BASELINE_NOT_BETTER_THAN_NAIVE_NULL
        reason = "one or more adequacy gates failed"
    decision = BaselineAdequacyDecision(disposition=disposition, gates=tuple(gates), reason=reason)
    return AdequacyResult(fold_side_nulls=tuple(nulls), comparisons=comparable_comparisons, fold_metrics=tuple(fold_metrics), aggregate=aggregate, decision=decision)


__all__ = ["evaluate_adequacy"]
