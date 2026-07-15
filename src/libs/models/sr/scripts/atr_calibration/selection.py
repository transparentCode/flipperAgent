"""Development-only challenger selection and one-shot holdout gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from statistics import median
from typing import Any, Mapping

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import deterministic_hash

from .config import CalibrationConfig
from .metrics import CandidateMetrics, WindowMetrics, median_absolute_deviation


class DevelopmentDisposition(str, Enum):
    SELECTED_CHALLENGER = "SELECTED_CHALLENGER"
    RETAIN_GLOBAL_14 = "RETAIN_GLOBAL_14"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class Recommendation(str, Enum):
    PROMOTE_EXACT_OVERRIDE = "PROMOTE_EXACT_OVERRIDE"
    RETAIN_GLOBAL_14 = "RETAIN_GLOBAL_14"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    HOLDOUT_REJECTED = "HOLDOUT_REJECTED"


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    value: Any
    threshold: Any
    reason: str

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name:
            raise ContractValidationError("gate name must be non-empty")
        if type(self.passed) is not bool:
            raise ContractValidationError("gate passed must be boolean")
        if type(self.reason) is not str or not self.reason:
            raise ContractValidationError("gate reason must be non-empty")

    def to_payload(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "value": self.value, "threshold": self.threshold, "reason": self.reason}


@dataclass(frozen=True)
class CandidateDecision:
    period: int
    is_baseline: bool
    eligible: bool
    fully_evaluable: bool
    gates: tuple[GateResult, ...]
    eligible_fold_count: int
    fold_win_count: int
    fold_win_fraction: float | None
    median_eligible_fold_delta: float | None
    pooled_quality_delta: float | None
    median_absolute_deviation: float | None

    def __post_init__(self) -> None:
        if isinstance(self.period, bool) or type(self.period) is not int or self.period < 1:
            raise ContractValidationError("decision period must be positive integer")
        if type(self.is_baseline) is not bool or type(self.eligible) is not bool or type(self.fully_evaluable) is not bool:
            raise ContractValidationError("decision flags must be booleans")
        if type(self.gates) is not tuple or any(type(gate) is not GateResult for gate in self.gates):
            raise ContractValidationError("decision gates must contain GateResult values")
        for name in ("eligible_fold_count", "fold_win_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or type(value) is not int or value < 0:
                raise ContractValidationError(f"{name} must be a non-negative integer")
        if self.fold_win_count > self.eligible_fold_count:
            raise ContractValidationError("fold wins exceed eligible folds")

    def to_payload(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "is_baseline": self.is_baseline,
            "eligible": self.eligible,
            "fully_evaluable": self.fully_evaluable,
            "gates": [gate.to_payload() for gate in self.gates],
            "eligible_fold_count": self.eligible_fold_count,
            "fold_win_count": self.fold_win_count,
            "fold_win_fraction": self.fold_win_fraction,
            "median_eligible_fold_delta": self.median_eligible_fold_delta,
            "pooled_quality_delta": self.pooled_quality_delta,
            "median_absolute_deviation": self.median_absolute_deviation,
        }


@dataclass(frozen=True)
class SelectionArtifact:
    """Immutable development selection; it intentionally contains no holdout data."""

    implementation_commit: str
    config_hash: str
    development_source_id: str
    baseline_period: int
    candidate_periods: tuple[int, ...]
    candidate_metrics: tuple[CandidateMetrics, ...]
    decisions: tuple[CandidateDecision, ...]
    selected_period: int | None
    disposition: DevelopmentDisposition
    selection_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.implementation_commit) is not str or re.fullmatch(r"[0-9a-f]{40,64}", self.implementation_commit) is None:
            raise ContractValidationError("selection implementation_commit must be non-empty")
        if type(self.config_hash) is not str or re.fullmatch(r"[0-9a-f]{64}", self.config_hash) is None:
            raise ContractValidationError("selection config_hash must be non-empty")
        if type(self.development_source_id) is not str or re.fullmatch(r"[0-9a-f]{64}", self.development_source_id) is None:
            raise ContractValidationError("selection development_source_id must be non-empty")
        if isinstance(self.baseline_period, bool) or type(self.baseline_period) is not int or self.baseline_period != 14:
            raise ContractValidationError("selection baseline period must be 14")
        if type(self.candidate_periods) is not tuple or tuple(sorted(self.candidate_periods)) != self.candidate_periods or len(set(self.candidate_periods)) != len(self.candidate_periods):
            raise ContractValidationError("selection candidate periods must be sorted and unique")
        if type(self.candidate_metrics) is not tuple or type(self.decisions) is not tuple:
            raise ContractValidationError("selection tables must be tuples")
        if any(type(metric) is not CandidateMetrics for metric in self.candidate_metrics) or any(type(decision) is not CandidateDecision for decision in self.decisions):
            raise ContractValidationError("selection tables contain invalid contract values")
        if tuple(metric.period for metric in self.candidate_metrics) != self.candidate_periods:
            raise ContractValidationError("candidate metrics are not in canonical order")
        if tuple(decision.period for decision in self.decisions) != self.candidate_periods:
            raise ContractValidationError("candidate decisions are not in canonical order")
        if self.selected_period is not None and self.selected_period not in self.candidate_periods or self.selected_period == self.baseline_period:
            if self.selected_period is not None:
                raise ContractValidationError("selected period must be one non-baseline candidate")
        if type(self.disposition) is not DevelopmentDisposition:
            raise ContractValidationError("invalid development disposition")
        if self.disposition is DevelopmentDisposition.SELECTED_CHALLENGER and self.selected_period is None:
            raise ContractValidationError("selected disposition requires a selected period")
        if self.disposition is not DevelopmentDisposition.SELECTED_CHALLENGER and self.selected_period is not None:
            raise ContractValidationError("non-selected disposition cannot carry a challenger")
        object.__setattr__(self, "selection_id", deterministic_hash(self.identity_payload()))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "implementation_commit": self.implementation_commit,
            "config_hash": self.config_hash,
            "development_source_id": self.development_source_id,
            "baseline_period": self.baseline_period,
            "candidate_periods": list(self.candidate_periods),
            "candidate_metrics": [metric.to_payload() for metric in self.candidate_metrics],
            "decisions": [decision.to_payload() for decision in self.decisions],
            "selected_period": self.selected_period,
            "disposition": self.disposition.value,
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self.identity_payload(), "selection_id": self.selection_id}


def _gate(name: str, passed: bool, value: Any, threshold: Any, reason: str) -> GateResult:
    return GateResult(name=name, passed=passed, value=value, threshold=threshold, reason=reason)


def _delta(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or baseline is None:
        return None
    return candidate - baseline


def _ratio(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or baseline is None or baseline <= 0:
        return None
    return candidate / baseline


def _decision_for_challenger(candidate: CandidateMetrics, baseline: CandidateMetrics, config: CalibrationConfig) -> CandidateDecision:
    gates: list[GateResult] = []
    minimum_fold = config.selection_gates.minimum_completed_first_touches_per_fold
    eligible_deltas: list[float] = []
    for candidate_fold, baseline_fold in zip(candidate.folds, baseline.folds):
        if candidate_fold.completed_first_touch_outcomes >= minimum_fold and baseline_fold.completed_first_touch_outcomes >= minimum_fold and candidate_fold.median_quality_reference_atr is not None and baseline_fold.median_quality_reference_atr is not None:
            eligible_deltas.append(candidate_fold.median_quality_reference_atr - baseline_fold.median_quality_reference_atr)
    eligible_folds = len(eligible_deltas)
    fold_wins = sum(delta > 0 for delta in eligible_deltas)
    fold_win_fraction = None if not eligible_deltas else fold_wins / eligible_folds
    pooled_delta = _delta(candidate.pooled.median_quality_reference_atr, baseline.pooled.median_quality_reference_atr)
    mad = median_absolute_deviation(eligible_deltas)
    gates.append(_gate("minimum_eligible_development_folds", eligible_folds >= config.selection_gates.minimum_eligible_development_folds, eligible_folds, config.selection_gates.minimum_eligible_development_folds, "eligible fold count" if eligible_folds >= config.selection_gates.minimum_eligible_development_folds else "insufficient comparable folds"))
    pooled_coverage = candidate.pooled.completed_first_touch_outcomes >= config.selection_gates.minimum_development_completed_first_touches and baseline.pooled.completed_first_touch_outcomes >= config.selection_gates.minimum_development_completed_first_touches
    gates.append(_gate("minimum_development_completed_first_touches", pooled_coverage, {"candidate": candidate.pooled.completed_first_touch_outcomes, "baseline": baseline.pooled.completed_first_touch_outcomes}, config.selection_gates.minimum_development_completed_first_touches, "pooled coverage" if pooled_coverage else "pooled first-touch coverage is insufficient"))
    fold_gate = fold_win_fraction is not None and fold_win_fraction >= config.selection_gates.minimum_development_fold_win_fraction
    gates.append(_gate("minimum_development_fold_win_fraction", fold_gate, fold_win_fraction, config.selection_gates.minimum_development_fold_win_fraction, "strict fold wins" if fold_gate else "fold win fraction is insufficient or undefined"))
    pooled_gate = pooled_delta is not None and pooled_delta >= config.selection_gates.minimum_development_pooled_delta_reference_atr
    gates.append(_gate("minimum_development_pooled_delta_reference_atr", pooled_gate, pooled_delta, config.selection_gates.minimum_development_pooled_delta_reference_atr, "pooled quality delta" if pooled_gate else "pooled quality delta is insufficient or undefined"))
    invalidation_delta = _delta(candidate.pooled.invalidation_rate, baseline.pooled.invalidation_rate)
    invalidation_gate = invalidation_delta is not None and invalidation_delta <= config.selection_gates.maximum_invalidation_rate_delta
    gates.append(_gate("maximum_invalidation_rate_delta", invalidation_gate, invalidation_delta, config.selection_gates.maximum_invalidation_rate_delta, "invalidation guardrail" if invalidation_gate else "invalidation rate is undefined or exceeds guardrail"))
    density_ratio = _ratio(candidate.pooled.zone_creation_density_per_100_bars, baseline.pooled.zone_creation_density_per_100_bars)
    density_gate = density_ratio is not None and config.selection_gates.minimum_zone_creation_density_ratio <= density_ratio <= config.selection_gates.maximum_zone_creation_density_ratio
    gates.append(_gate("zone_creation_density_ratio", density_gate, density_ratio, [config.selection_gates.minimum_zone_creation_density_ratio, config.selection_gates.maximum_zone_creation_density_ratio], "zone density guardrail" if density_gate else "zone density ratio is undefined or outside guardrail"))
    churn_delta = _delta(candidate.pooled.churn_rate, baseline.pooled.churn_rate)
    churn_gate = churn_delta is not None and churn_delta <= config.selection_gates.maximum_churn_rate_delta
    gates.append(_gate("maximum_churn_rate_delta", churn_gate, churn_delta, config.selection_gates.maximum_churn_rate_delta, "churn guardrail" if churn_gate else "churn rate is undefined or exceeds guardrail"))
    censor_delta = _delta(candidate.pooled.right_censoring_rate, baseline.pooled.right_censoring_rate)
    censor_gate = censor_delta is not None and censor_delta <= config.selection_gates.maximum_right_censoring_rate_delta
    gates.append(_gate("maximum_right_censoring_rate_delta", censor_gate, censor_delta, config.selection_gates.maximum_right_censoring_rate_delta, "right-censoring guardrail" if censor_gate else "right-censoring rate is undefined or exceeds guardrail"))
    fully_evaluable = all(gate.value is not None for gate in gates) and eligible_folds >= config.selection_gates.minimum_eligible_development_folds and candidate.pooled.completed_first_touch_outcomes >= config.selection_gates.minimum_development_completed_first_touches and baseline.pooled.completed_first_touch_outcomes >= config.selection_gates.minimum_development_completed_first_touches
    eligible = fully_evaluable and all(gate.passed for gate in gates)
    return CandidateDecision(
        period=candidate.period,
        is_baseline=False,
        eligible=eligible,
        fully_evaluable=fully_evaluable,
        gates=tuple(gates),
        eligible_fold_count=eligible_folds,
        fold_win_count=fold_wins,
        fold_win_fraction=fold_win_fraction,
        median_eligible_fold_delta=None if not eligible_deltas else median(eligible_deltas),
        pooled_quality_delta=pooled_delta,
        median_absolute_deviation=mad,
    )


def select_development(metrics: tuple[CandidateMetrics, ...], *, config: CalibrationConfig, development_source_id: str, implementation_commit: str) -> SelectionArtifact:
    """Select at most one challenger from development metrics only."""
    if type(metrics) is not tuple or tuple(metric.period for metric in metrics) != config.candidate_periods:
        raise ContractValidationError("development metrics must contain exactly the canonical candidate set")
    baseline = next(metric for metric in metrics if metric.period == config.baseline_period)
    baseline_decision = CandidateDecision(
        period=config.baseline_period,
        is_baseline=True,
        eligible=True,
        fully_evaluable=baseline.pooled.completed_first_touch_outcomes >= config.selection_gates.minimum_development_completed_first_touches,
        gates=(),
        eligible_fold_count=len(baseline.folds),
        fold_win_count=0,
        fold_win_fraction=None,
        median_eligible_fold_delta=None,
        pooled_quality_delta=None,
        median_absolute_deviation=None,
    )
    decisions = [baseline_decision]
    for metric in metrics:
        if metric.period != config.baseline_period:
            decisions.append(_decision_for_challenger(metric, baseline, config))
    decisions = sorted(decisions, key=lambda decision: decision.period)
    challengers = [decision for decision in decisions if not decision.is_baseline and decision.eligible]
    fully_evaluable_challengers = [decision for decision in decisions if not decision.is_baseline and decision.fully_evaluable]
    baseline_coverage = baseline.pooled.completed_first_touch_outcomes >= config.selection_gates.minimum_development_completed_first_touches
    selected: CandidateDecision | None = None
    if challengers:
        selected = sorted(challengers, key=lambda decision: (-decision.median_eligible_fold_delta, -decision.pooled_quality_delta, decision.median_absolute_deviation, abs(decision.period - config.baseline_period), decision.period))[0]
    if selected is not None:
        selected_period = selected.period
        disposition = DevelopmentDisposition.SELECTED_CHALLENGER
    elif not baseline_coverage or not fully_evaluable_challengers:
        selected_period = None
        disposition = DevelopmentDisposition.INSUFFICIENT_EVIDENCE
    else:
        selected_period = None
        disposition = DevelopmentDisposition.RETAIN_GLOBAL_14
    return SelectionArtifact(
        implementation_commit=implementation_commit,
        config_hash=config.config_hash,
        development_source_id=development_source_id,
        baseline_period=config.baseline_period,
        candidate_periods=config.candidate_periods,
        candidate_metrics=metrics,
        decisions=tuple(decisions),
        selected_period=selected_period,
        disposition=disposition,
    )


@dataclass(frozen=True)
class HoldoutEvaluation:
    selected_period: int | None
    recommendation: Recommendation
    baseline_metrics: WindowMetrics | None
    challenger_metrics: WindowMetrics | None
    gates: tuple[GateResult, ...]
    holdout_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.recommendation) is not Recommendation:
            raise ContractValidationError("invalid holdout recommendation")
        if type(self.gates) is not tuple or any(type(gate) is not GateResult for gate in self.gates):
            raise ContractValidationError("holdout gates must contain GateResult values")
        if self.selected_period is None and self.challenger_metrics is not None:
            raise ContractValidationError("no-selection holdout cannot contain challenger metrics")
        object.__setattr__(self, "holdout_id", deterministic_hash(self.to_payload()))

    def to_payload(self) -> dict[str, Any]:
        return {
            "selected_period": self.selected_period,
            "recommendation": self.recommendation.value,
            "baseline_metrics": None if self.baseline_metrics is None else self.baseline_metrics.to_payload(),
            "challenger_metrics": None if self.challenger_metrics is None else self.challenger_metrics.to_payload(),
            "gates": [gate.to_payload() for gate in self.gates],
        }


def evaluate_holdout_metrics(selection: SelectionArtifact, holdout_metrics: Mapping[int, WindowMetrics], *, config: CalibrationConfig) -> HoldoutEvaluation:
    """Apply fixed holdout gates; never rerank or inspect other periods."""
    if type(selection) is not SelectionArtifact:
        raise ContractValidationError("selection must be exactly SelectionArtifact")
    if selection.disposition is not DevelopmentDisposition.SELECTED_CHALLENGER:
        recommendation = Recommendation.INSUFFICIENT_EVIDENCE if selection.disposition is DevelopmentDisposition.INSUFFICIENT_EVIDENCE else Recommendation.RETAIN_GLOBAL_14
        return HoldoutEvaluation(selected_period=None, recommendation=recommendation, baseline_metrics=None, challenger_metrics=None, gates=())
    selected = selection.selected_period
    if set(holdout_metrics) != {config.baseline_period, selected}:
        raise ContractValidationError("holdout metrics must contain exactly baseline and selected challenger")
    baseline = holdout_metrics[config.baseline_period]
    challenger = holdout_metrics[selected]
    gates: list[GateResult] = []
    minimum = config.selection_gates.minimum_holdout_completed_first_touches
    coverage = baseline.completed_first_touch_outcomes >= minimum and challenger.completed_first_touch_outcomes >= minimum
    gates.append(_gate("minimum_holdout_completed_first_touches", coverage, {"baseline": baseline.completed_first_touch_outcomes, "challenger": challenger.completed_first_touch_outcomes}, minimum, "holdout coverage" if coverage else "holdout first-touch coverage is insufficient"))
    quality_delta = _delta(challenger.median_quality_reference_atr, baseline.median_quality_reference_atr)
    quality_gate = quality_delta is not None and quality_delta >= config.selection_gates.minimum_holdout_delta_reference_atr
    gates.append(_gate("minimum_holdout_delta_reference_atr", quality_gate, quality_delta, config.selection_gates.minimum_holdout_delta_reference_atr, "holdout quality delta" if quality_gate else "holdout quality delta is insufficient or undefined"))
    invalidation_delta = _delta(challenger.invalidation_rate, baseline.invalidation_rate)
    invalidation_gate = invalidation_delta is not None and invalidation_delta <= config.selection_gates.maximum_invalidation_rate_delta
    gates.append(_gate("maximum_holdout_invalidation_rate_delta", invalidation_gate, invalidation_delta, config.selection_gates.maximum_invalidation_rate_delta, "holdout invalidation guardrail" if invalidation_gate else "holdout invalidation guardrail failed or undefined"))
    density_ratio = _ratio(challenger.zone_creation_density_per_100_bars, baseline.zone_creation_density_per_100_bars)
    density_gate = density_ratio is not None and config.selection_gates.minimum_zone_creation_density_ratio <= density_ratio <= config.selection_gates.maximum_zone_creation_density_ratio
    gates.append(_gate("holdout_zone_creation_density_ratio", density_gate, density_ratio, [config.selection_gates.minimum_zone_creation_density_ratio, config.selection_gates.maximum_zone_creation_density_ratio], "holdout density guardrail" if density_gate else "holdout density guardrail failed or undefined"))
    churn_delta = _delta(challenger.churn_rate, baseline.churn_rate)
    churn_gate = churn_delta is not None and churn_delta <= config.selection_gates.maximum_churn_rate_delta
    gates.append(_gate("maximum_holdout_churn_rate_delta", churn_gate, churn_delta, config.selection_gates.maximum_churn_rate_delta, "holdout churn guardrail" if churn_gate else "holdout churn guardrail failed or undefined"))
    censor_delta = _delta(challenger.right_censoring_rate, baseline.right_censoring_rate)
    censor_gate = censor_delta is not None and censor_delta <= config.selection_gates.maximum_right_censoring_rate_delta
    gates.append(_gate("maximum_holdout_right_censoring_rate_delta", censor_gate, censor_delta, config.selection_gates.maximum_right_censoring_rate_delta, "holdout censoring guardrail" if censor_gate else "holdout censoring guardrail failed or undefined"))
    if not coverage:
        recommendation = Recommendation.INSUFFICIENT_EVIDENCE
    elif all(gate.passed for gate in gates):
        recommendation = Recommendation.PROMOTE_EXACT_OVERRIDE
    else:
        recommendation = Recommendation.HOLDOUT_REJECTED
    return HoldoutEvaluation(selected_period=selected, recommendation=recommendation, baseline_metrics=baseline, challenger_metrics=challenger, gates=tuple(gates))


__all__ = [
    "CandidateDecision",
    "DevelopmentDisposition",
    "GateResult",
    "HoldoutEvaluation",
    "Recommendation",
    "SelectionArtifact",
    "evaluate_holdout_metrics",
    "select_development",
]
