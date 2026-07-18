"""Lifecycle utility metrics, null comparisons, and disposition gates."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from libs.models.sr.domain import ContractValidationError

from .config import FROZEN_EVENT_CLASSES, LifecycleUtilityConfig
from .contracts import (
    AggregateMetrics,
    EventClassMetrics,
    FoldMetrics,
    GateResult,
    LifecycleUtilityDecision,
    LifecycleUtilityDisposition,
    ResolutionOutcome,
)


def _median(values: list[float]) -> float | None:
    return None if not values else float(median(values))


@dataclass(frozen=True)
class MetricsEvaluation:
    outcomes: tuple[ResolutionOutcome, ...]
    fold_metrics: tuple[FoldMetrics, ...]
    aggregate: AggregateMetrics
    gates: tuple[GateResult, ...]
    decision: LifecycleUtilityDecision


def _gate(
    name: str,
    value: int | float | None,
    *,
    applicable: bool,
    passed: bool,
    reason: str,
) -> GateResult:
    category, operator, threshold, _ = {
        "readiness.completed_unique_resolutions": ("readiness", ">=", 16, "integer"),
        "readiness.comparable_folds": ("readiness", ">=", 4, "integer"),
        "readiness.minimum_completed_per_comparable_fold": ("readiness", ">=", 2, "integer"),
        "readiness.minimum_null_controls_per_compared_cell": ("readiness", ">=", 4, "integer"),
        "quality.pooled_median_excess_quality_atr": ("quality", ">=", 0.10, "number"),
        "quality.positive_comparable_fold_fraction": ("quality", ">=", 0.60, "number"),
        "quality.worst_comparable_fold_median_excess_atr": ("quality", ">=", -0.10, "number"),
        "stability.false_breakout_median_excess_quality_atr": ("stability", ">=", 0.0, "number"),
        "stability.break_confirmed_median_excess_quality_atr": ("stability", ">=", 0.0, "number"),
    }[name]
    return GateResult(name=name, category=category, passed=passed, applicable=applicable, value=value, threshold=threshold, operator=operator, reason=reason)


def _fold_metric(fold: str, outcomes: tuple[ResolutionOutcome, ...], config: LifecycleUtilityConfig) -> FoldMetrics:
    rows = tuple(item for item in outcomes if item.event_fold == fold)
    completed = tuple(item for item in rows if item.completed)
    compared = tuple(item for item in completed if item.compared)
    counts = tuple(item.null_control_count for item in completed)
    minimum_controls = min(counts) if counts else None
    comparable = bool(completed) and len(completed) >= config.readiness.minimum_completed_per_comparable_fold and len(compared) == len(completed) and minimum_controls is not None and minimum_controls >= config.readiness.minimum_null_controls_per_compared_cell
    return FoldMetrics(
        fold=fold,
        total_resolution_count=len(rows),
        completed_count=len(completed),
        right_censored_count=sum(item.right_censored for item in rows),
        compared_count=len(compared) if comparable else 0,
        minimum_null_control_count=minimum_controls if comparable else None,
        comparable=comparable,
        median_excess_quality_atr=_median([item.excess_quality_atr for item in compared]) if comparable else None,
    )


def evaluate_metrics(
    outcomes: tuple[ResolutionOutcome, ...],
    *,
    config: LifecycleUtilityConfig,
    contract_valid: bool = True,
) -> MetricsEvaluation:
    if type(outcomes) is not tuple or any(type(item) is not ResolutionOutcome for item in outcomes):
        raise ContractValidationError("lifecycle metrics require ResolutionOutcome values")
    if len({item.outcome_id for item in outcomes}) != len(outcomes) or len({item.zone_id for item in outcomes}) != len(outcomes):
        raise ContractValidationError("lifecycle outcomes must be unique by outcome and zone")
    fold_metrics = tuple(_fold_metric(fold.name, outcomes, config) for fold in config.folds)
    comparable_folds = tuple(item for item in fold_metrics if item.comparable)
    comparable_fold_names = {item.fold for item in comparable_folds}
    comparable_outcomes = tuple(item for item in outcomes if item.event_fold in comparable_fold_names and item.compared)
    pooled_values = [item.excess_quality_atr for item in comparable_outcomes]
    positive_fraction = None if not comparable_folds else sum(item.median_excess_quality_atr is not None and item.median_excess_quality_atr > 0 for item in comparable_folds) / len(comparable_folds)
    worst = None if not comparable_folds else min(item.median_excess_quality_atr for item in comparable_folds if item.median_excess_quality_atr is not None)
    event_metrics = tuple(
        EventClassMetrics(event_class=event_class, comparable_outcome_count=sum(item.event_class == event_class for item in comparable_outcomes), median_excess_quality_atr=_median([item.excess_quality_atr for item in comparable_outcomes if item.event_class == event_class]))
        for event_class in FROZEN_EVENT_CLASSES
    )
    aggregate = AggregateMetrics(
        total_resolution_count=len(outcomes),
        completed_count=sum(item.completed for item in outcomes),
        right_censored_count=sum(item.right_censored for item in outcomes),
        compared_count=len(comparable_outcomes),
        comparable_fold_count=len(comparable_folds),
        pooled_median_excess_quality_atr=_median(pooled_values),
        positive_comparable_fold_fraction=positive_fraction,
        worst_comparable_fold_median_excess_atr=worst,
        event_classes=event_metrics,
    )
    completed = aggregate.completed_count
    minimum_completed_per_fold = min((item.completed_count for item in comparable_folds), default=0)
    compared_cells = tuple((item.event_fold, item.effective_side, item.null_control_count) for item in outcomes if item.completed)
    minimum_null_controls = min((count for _, _, count in compared_cells), default=0)
    gates = (
        _gate("readiness.completed_unique_resolutions", completed, applicable=True, passed=completed >= config.readiness.minimum_completed_unique_resolutions, reason="completed unique resolution outcomes meet readiness minimum" if completed >= config.readiness.minimum_completed_unique_resolutions else "completed unique resolution outcomes are below readiness minimum"),
        _gate("readiness.comparable_folds", len(comparable_folds), applicable=True, passed=len(comparable_folds) >= config.readiness.minimum_comparable_folds, reason="enough comparable folds" if len(comparable_folds) >= config.readiness.minimum_comparable_folds else "too few comparable folds"),
        _gate("readiness.minimum_completed_per_comparable_fold", minimum_completed_per_fold, applicable=True, passed=minimum_completed_per_fold >= config.readiness.minimum_completed_per_comparable_fold and bool(comparable_folds), reason="each comparable fold has enough completed outcomes" if minimum_completed_per_fold >= config.readiness.minimum_completed_per_comparable_fold and comparable_folds else "comparable fold completion minimum is not met"),
        _gate("readiness.minimum_null_controls_per_compared_cell", minimum_null_controls, applicable=True, passed=minimum_null_controls >= config.readiness.minimum_null_controls_per_compared_cell and all(item.compared for item in outcomes if item.completed), reason="all completed outcome cells have enough null controls" if minimum_null_controls >= config.readiness.minimum_null_controls_per_compared_cell and all(item.compared for item in outcomes if item.completed) else "a compared fold/effective-side null cell is missing or undersized"),
        _gate("quality.pooled_median_excess_quality_atr", aggregate.pooled_median_excess_quality_atr, applicable=aggregate.pooled_median_excess_quality_atr is not None, passed=aggregate.pooled_median_excess_quality_atr is not None and aggregate.pooled_median_excess_quality_atr >= config.quality.minimum_pooled_median_excess_quality_atr, reason="pooled median excess meets quality threshold" if aggregate.pooled_median_excess_quality_atr is not None and aggregate.pooled_median_excess_quality_atr >= config.quality.minimum_pooled_median_excess_quality_atr else "pooled median excess is below threshold or undefined"),
        _gate("quality.positive_comparable_fold_fraction", aggregate.positive_comparable_fold_fraction, applicable=aggregate.positive_comparable_fold_fraction is not None, passed=aggregate.positive_comparable_fold_fraction is not None and aggregate.positive_comparable_fold_fraction >= config.quality.minimum_positive_comparable_fold_fraction, reason="positive comparable-fold fraction meets threshold" if aggregate.positive_comparable_fold_fraction is not None and aggregate.positive_comparable_fold_fraction >= config.quality.minimum_positive_comparable_fold_fraction else "positive comparable-fold fraction is below threshold or undefined"),
        _gate("quality.worst_comparable_fold_median_excess_atr", aggregate.worst_comparable_fold_median_excess_atr, applicable=aggregate.worst_comparable_fold_median_excess_atr is not None, passed=aggregate.worst_comparable_fold_median_excess_atr is not None and aggregate.worst_comparable_fold_median_excess_atr >= config.quality.minimum_worst_comparable_fold_median_excess_atr, reason="worst comparable-fold median meets threshold" if aggregate.worst_comparable_fold_median_excess_atr is not None and aggregate.worst_comparable_fold_median_excess_atr >= config.quality.minimum_worst_comparable_fold_median_excess_atr else "worst comparable-fold median is below threshold or undefined"),
        _event_class_gate(event_metrics[0], config),
        _event_class_gate(event_metrics[1], config),
    )
    readiness_pass = all(item.passed for item in gates[:4])
    quality_pass = all(item.passed for item in gates[4:])
    if not contract_valid:
        disposition = LifecycleUtilityDisposition.INVALID_EVIDENCE
        reason = "contract or upstream parity validation failed"
    elif not readiness_pass:
        disposition = LifecycleUtilityDisposition.INSUFFICIENT_EVIDENCE
        reason = "lifecycle resolution readiness gates are not satisfied"
    elif quality_pass:
        disposition = LifecycleUtilityDisposition.LIFECYCLE_CONTEXT_SUPPORTED
        reason = "all lifecycle resolution quality and stability gates pass"
    else:
        disposition = LifecycleUtilityDisposition.LIFECYCLE_CONTEXT_NOT_SUPPORTED
        reason = "at least one lifecycle resolution quality or stability gate fails"
    decision = LifecycleUtilityDecision(contract_valid=contract_valid, disposition=disposition, gates=gates, reason=reason)
    return MetricsEvaluation(outcomes=outcomes, fold_metrics=fold_metrics, aggregate=aggregate, gates=gates, decision=decision)


def _event_class_gate(metric: EventClassMetrics, config: LifecycleUtilityConfig) -> GateResult:
    name = f"stability.{metric.event_class.lower()}_median_excess_quality_atr"
    applicable = metric.comparable_outcome_count >= config.quality.minimum_event_class_comparable_outcomes
    passed = not applicable or (metric.median_excess_quality_atr is not None and metric.median_excess_quality_atr >= config.quality.minimum_event_class_median_excess_atr)
    return _gate(name, metric.median_excess_quality_atr, applicable=applicable, passed=passed, reason="event class median is non-negative" if passed and applicable else "event class is below the comparable-outcome minimum" if not applicable else "event class median excess is negative")


__all__ = ["MetricsEvaluation", "evaluate_metrics"]
