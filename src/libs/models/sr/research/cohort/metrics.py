"""Causal replay, first-touch accounting, cohort aggregation, and gates."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any

from libs.models.sr.domain import ContractValidationError, SREventType, ZoneSide
from libs.models.sr.config.models import ResolvedSRConfig
from libs.models.sr.research.metrics.first_touch_windows import compute_candidate_metrics
from libs.models.sr.research.replay.atr import replay_candidates

from .contracts import (
    APPROVED_ASSETS,
    AssetEvaluation,
    AssetSource,
    CohortAggregate,
    CohortEvaluation,
    CohortFold,
    Disposition,
    EventAccounting,
    GateRecord,
    MacroAggregate,
    MacroMetric,
    SourceBundle,
    source_capsule,
)


@dataclass(frozen=True)
class ReplayProtocol:
    """Duck-typed V1.6 protocol passed to its read-only replay functions."""

    venue: str
    symbol: str
    timeframe: str
    candidate_periods: tuple[int, ...]
    common_start_period: int
    evaluation_reference_period: int
    outcome_start_offset_bars: int
    outcome_horizon_bars: int
    development_folds: tuple[CohortFold, ...]


def replay_protocol(config: object, asset: str) -> ReplayProtocol:
    return ReplayProtocol(
        venue=config.venue,
        symbol=asset,
        timeframe=config.timeframe,
        candidate_periods=(config.atr_period,),
        common_start_period=config.common_start_period,
        evaluation_reference_period=config.atr_period,
        outcome_start_offset_bars=config.outcome_start_offset_bars,
        outcome_horizon_bars=config.outcome_horizon_bars,
        development_folds=config.folds,
    )


def replay_asset(
    config: object,
    source: AssetSource,
    resolved_config: ResolvedSRConfig,
    *,
    implementation_commit: str,
) -> AssetEvaluation:
    if source.asset != resolved_config.asset or source.timeframe != resolved_config.timeframe:
        raise ContractValidationError("source and resolved configuration ownership mismatch")
    if resolved_config.resolved_config_hash != source.resolved_sr_config_hash:
        raise ContractValidationError("source SR config hash does not match resolved input")
    replay_config = replay_protocol(config, source.asset)
    capsule = source_capsule(source, implementation_commit=implementation_commit)
    replays = replay_candidates(capsule, (config.atr_period,), config=replay_config, resolved_config=resolved_config)
    if len(replays) != 1:
        raise ContractValidationError("cohort replay must produce exactly one ATR(14) replay")
    replay = replays[0]
    metrics = compute_candidate_metrics(replay, capsule, config=replay_config)
    return AssetEvaluation(
        asset=source.asset,
        source_id=source.source_id,
        resolved_sr_config_hash=source.resolved_sr_config_hash,
        resolved_input_hash=source.resolved_input_hash,
        replay=replay,
        metrics=metrics,
        folds=config.folds,
    )


def created_side_counts(evaluation: AssetEvaluation) -> tuple[int, int]:
    """Count created support/resistance zones over the complete replay."""
    sides: dict[str, ZoneSide] = {}
    for observation in evaluation.replay.trace.zone_observations:
        sides.setdefault(observation.zone_id, observation.side)
    created: set[str] = set()
    for event in evaluation.replay.trace.events:
        if event.event_type is SREventType.CREATED:
            created.add(event.zone_id)
    return (
        sum(sides.get(zone_id) is ZoneSide.SUPPORT for zone_id in created),
        sum(sides.get(zone_id) is ZoneSide.RESISTANCE for zone_id in created),
    )


def _completed_values(evaluations: tuple[AssetEvaluation, ...], name: str) -> list[float]:
    values: list[float] = []
    for evaluation in evaluations:
        for outcome in evaluation.metrics.pooled.outcomes:
            if outcome.completed:
                value = getattr(outcome, name)
                if value is not None:
                    values.append(value)
    return values


def _micro(evaluations: tuple[AssetEvaluation, ...]) -> CohortAggregate:
    pooled = [evaluation.metrics.pooled for evaluation in evaluations]
    outcomes = tuple(outcome for metric in pooled for outcome in metric.outcomes)
    completed = tuple(outcome for outcome in outcomes if outcome.completed)
    right_censored = sum(outcome.right_censored for outcome in outcomes)
    invalidated = sum(outcome.invalidated for outcome in completed)
    created = sum(metric.created_zone_count for metric in pooled)
    eligible_bars = sum(metric.eligible_model_bar_count for metric in pooled)
    terminal = sum(metric.cohort_terminal_count for metric in pooled)
    favorable = _completed_values(evaluations, "favorable_reference_atr")
    adverse = _completed_values(evaluations, "adverse_reference_atr")
    quality = _completed_values(evaluations, "quality_reference_atr")
    return CohortAggregate(
        view="micro",
        total_first_touch_outcomes=len(outcomes),
        completed_first_touch_outcomes=len(completed),
        right_censored_first_touch_outcomes=right_censored,
        support_completed_count=sum(metric.support_completed_count for metric in pooled),
        resistance_completed_count=sum(metric.resistance_completed_count for metric in pooled),
        invalidated_completed_outcomes=invalidated,
        created_zone_count=created,
        eligible_model_bar_count=eligible_bars,
        cohort_terminal_count=terminal,
        right_censoring_rate=None if not outcomes else right_censored / len(outcomes),
        invalidation_rate=None if not completed else invalidated / len(completed),
        zone_creation_density_per_100_bars=None if not eligible_bars else created * 100.0 / eligible_bars,
        churn_rate=None if not created else terminal / created,
        median_favorable_reference_atr=None if not favorable else median(favorable),
        median_adverse_reference_atr=None if not adverse else median(adverse),
        median_quality_reference_atr=None if not quality else median(quality),
        outcomes=outcomes,
        event_accounting=EventAccounting(
            created=sum(evaluation.event_accounting.created for evaluation in evaluations),
            touched=sum(evaluation.event_accounting.touched for evaluation in evaluations),
            breach_started=sum(evaluation.event_accounting.breach_started for evaluation in evaluations),
            false_breakout=sum(evaluation.event_accounting.false_breakout for evaluation in evaluations),
            break_confirmed=sum(evaluation.event_accounting.break_confirmed for evaluation in evaluations),
            expired=sum(evaluation.event_accounting.expired for evaluation in evaluations),
            observed_event_count=sum(evaluation.event_accounting.observed_event_count for evaluation in evaluations),
        ),
    )


_MACRO_FIELDS = (
    "total_first_touch_outcomes", "completed_first_touch_outcomes", "right_censored_first_touch_outcomes",
    "support_completed_count", "resistance_completed_count", "invalidated_completed_outcomes", "created_zone_count",
    "eligible_model_bar_count", "cohort_terminal_count", "right_censoring_rate", "invalidation_rate",
    "zone_creation_density_per_100_bars", "churn_rate", "median_favorable_reference_atr",
    "median_adverse_reference_atr", "median_quality_reference_atr",
)


def _macro(evaluations: tuple[AssetEvaluation, ...]) -> MacroAggregate:
    metrics: list[tuple[str, MacroMetric]] = []
    pooled = tuple(evaluation.metrics.pooled for evaluation in evaluations)
    for field_name in _MACRO_FIELDS:
        values = [getattr(metric, field_name) for metric in pooled]
        numeric = [float(value) for value in values if value is not None]
        metrics.append((field_name, MacroMetric(
            median=None if not numeric else median(numeric),
            minimum=None if not numeric else min(numeric),
            maximum=None if not numeric else max(numeric),
        )))
    return MacroAggregate(metrics=tuple(sorted(metrics, key=lambda item: item[0])))


def aggregate(evaluations: tuple[AssetEvaluation, ...]) -> tuple[CohortAggregate, MacroAggregate]:
    if type(evaluations) is not tuple or any(type(item) is not AssetEvaluation for item in evaluations):
        raise ContractValidationError("cohort aggregation requires AssetEvaluation values")
    if tuple(item.asset for item in evaluations) != APPROVED_ASSETS:
        raise ContractValidationError("cohort aggregation requires canonical asset order")
    return _micro(evaluations), _macro(evaluations)


def _gate(
    name: str,
    *,
    asset: str | None,
    fold: str | None,
    passed: bool,
    value: Any,
    threshold: Any,
    reason: str,
) -> GateRecord:
    return GateRecord(name=name, asset=asset, fold=fold, passed=passed, value=value, threshold=threshold, reason=reason)


def readiness_gates(config: object, evaluations: tuple[AssetEvaluation, ...]) -> tuple[tuple[GateRecord, ...], Disposition]:
    gates: list[GateRecord] = []
    anomalies: list[GateRecord] = []
    for evaluation in evaluations:
        support, resistance = created_side_counts(evaluation)
        metric = evaluation.metrics.pooled
        anomaly_checks = (
            ("created_zones", metric.created_zone_count),
            ("support_zones", support),
            ("resistance_zones", resistance),
            ("first_touches", metric.total_first_touch_outcomes),
            ("terminal_cohort_events", metric.cohort_terminal_count),
        )
        for name, value in anomaly_checks:
            record = _gate(
                f"structural.{name}", asset=evaluation.asset, fold=None,
                passed=value > 0, value=value, threshold=1,
                reason="non-zero structural cohort" if value > 0 else "zero structural cohort across complete development",
            )
            gates.append(record)
            if not record.passed:
                anomalies.append(record)
        eligible_folds = sum(fold.completed_first_touch_outcomes >= config.readiness_gates.minimum_completed_first_touches_per_fold for fold in evaluation.metrics.folds)
        total_completed = metric.completed_first_touch_outcomes
        for fold in evaluation.metrics.folds:
            gates.append(_gate(
                "sample.completed_first_touches_per_fold", asset=evaluation.asset, fold=fold.name,
                passed=fold.completed_first_touch_outcomes >= config.readiness_gates.minimum_completed_first_touches_per_fold,
                value=fold.completed_first_touch_outcomes, threshold=config.readiness_gates.minimum_completed_first_touches_per_fold,
                reason="fold is sample-eligible" if fold.completed_first_touch_outcomes >= config.readiness_gates.minimum_completed_first_touches_per_fold else "fold has insufficient completed first touches",
            ))
        gates.append(_gate(
            "sample.eligible_development_folds", asset=evaluation.asset, fold=None,
            passed=eligible_folds >= config.readiness_gates.minimum_eligible_development_folds,
            value=eligible_folds, threshold=config.readiness_gates.minimum_eligible_development_folds,
            reason="enough eligible folds" if eligible_folds >= config.readiness_gates.minimum_eligible_development_folds else "too few eligible folds",
        ))
        gates.append(_gate(
            "sample.development_completed_first_touches", asset=evaluation.asset, fold=None,
            passed=total_completed >= config.readiness_gates.minimum_development_completed_first_touches,
            value=total_completed, threshold=config.readiness_gates.minimum_development_completed_first_touches,
            reason="development coverage is sufficient" if total_completed >= config.readiness_gates.minimum_development_completed_first_touches else "development coverage is insufficient",
        ))
    if anomalies:
        return tuple(gates), Disposition.STRUCTURAL_ANOMALY
    aggregate_sample_gates = {
        "sample.eligible_development_folds",
        "sample.development_completed_first_touches",
    }
    failed_samples = [
        gate for gate in gates
        if gate.name in aggregate_sample_gates and not gate.passed
    ]
    if failed_samples:
        return tuple(gates), Disposition.INSUFFICIENT_EVIDENCE
    return tuple(gates), Disposition.READY_FOR_PARAMETER_SENSITIVITY


def evaluate_cohort(
    config: object,
    source_bundle: SourceBundle,
    resolved_configs: dict[str, ResolvedSRConfig],
    resolved_inputs: dict[str, Any] | None = None,
    *,
    implementation_commit: str | None = None,
) -> CohortEvaluation:
    if source_bundle.config_hash != config.config_hash:
        raise ContractValidationError("source bundle config identity mismatch")
    if type(resolved_configs) is not dict or tuple(resolved_configs) != APPROVED_ASSETS or any(type(value) is not ResolvedSRConfig for value in resolved_configs.values()):
        raise ContractValidationError("resolved configurations must use canonical asset order")
    if resolved_inputs is not None:
        if type(resolved_inputs) is not dict or tuple(resolved_inputs) != APPROVED_ASSETS:
            raise ContractValidationError("resolved inputs must use canonical asset order")
        for source in source_bundle.assets:
            resolved_input = resolved_inputs[source.asset]
            if getattr(resolved_input, "resolved_input_hash", None) != source.resolved_input_hash:
                raise ContractValidationError("source and resolved input hashes do not reconcile")
    evaluation_commit = source_bundle.implementation_commit if implementation_commit is None else implementation_commit
    evaluations = tuple(
        replay_asset(config, source, resolved_configs[source.asset], implementation_commit=evaluation_commit)
        for source in source_bundle.assets
    )
    micro, macro = aggregate(evaluations)
    gates, disposition = readiness_gates(config, evaluations)
    return CohortEvaluation(
        implementation_commit=evaluation_commit,
        config_hash=config.config_hash,
        source_bundle_id=source_bundle.bundle_id,
        assets=evaluations,
        micro=micro,
        macro=macro,
        gates=gates,
        disposition=disposition,
    )


__all__ = [
    "ReplayProtocol", "aggregate", "created_side_counts", "evaluate_cohort",
    "readiness_gates", "replay_asset", "replay_protocol",
]
