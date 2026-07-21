"""Deterministic Phase-I evaluation, counterfactual audits, and holdout gates."""

from __future__ import annotations

from dataclasses import replace
from itertools import product
from time import perf_counter
from typing import Any, Callable, Mapping, Protocol, Sequence

from ..configuration.contracts import ResolvedTrendlineFamilyConfig, TrendlineFamilyConfig
from ..contracts import ContractValidationError
from .contracts import (
    FailureCode,
    FinalistFreeze,
    HoldoutOpenAudit,
    ObjectiveGate,
    ObjectiveSpec,
    OptimizationStage,
    ParameterEffectAudit,
    PromotionDecision,
    PromotionRecommendation,
    StageEvaluationSpec,
    TrialConfig,
    TrialResult,
    TrialStatus,
    WindowResult,
    canonical_json,
    semantic_id,
)
from .folds import FoldPlan, HoldoutPlan, ImmutableHistoricalFrame, WalkForwardFold
from .metrics import aggregate_window_metrics, metric_delta


WindowEvaluator = Callable[[TrialConfig, ResolvedTrendlineFamilyConfig, WalkForwardFold | HoldoutPlan, str], WindowResult]


_OWNED_PARAMETERS: dict[OptimizationStage, frozenset[str]] = {
    OptimizationStage.CANDIDATE_GEOMETRY: frozenset(
        {
            "candidate.pivot_provider",
            "candidate.fitter",
            "candidate.lookback_bars",
            "candidate.min_bars",
            "candidate.fractal_left_bars",
            "candidate.fractal_right_bars",
            "candidate.min_pivots_per_side",
            "candidate.min_candidate_quality",
        }
    ),
    OptimizationStage.TRACKER: frozenset(
        {
            "candidate.birth_quality_threshold",
            "matching.normalization_atr_window",
            "matching.max_distance_atr",
            "matching.max_slope_delta_atr_per_hour",
            "matching.minimum_match_score",
            "matching.level_weight",
            "matching.slope_weight",
            "matching.anchor_weight",
            "matching.role_weight",
            "lifecycle.active_grace_bars",
            "lifecycle.dormant_after_bars",
            "lifecycle.expire_after_bars",
            "lifecycle.confidence_decay_per_unmatched_bar",
            "lifecycle.reactivation_min_score",
            "lifecycle.max_active_families_per_role",
            "rails.max_group_slope_delta_atr_per_hour",
            "rails.max_adjacent_gap_atr",
            "rails.max_corridor_width_atr",
            "rails.minimum_spacing_atr",
            "rails.representative_policy",
        }
    ),
    OptimizationStage.INTERACTION: frozenset(
        {
            "interaction.atr_window",
            "interaction.tolerance_atr",
            "interaction.approaching_distance_atr",
            "interaction.minimum_zone_ticks",
            "interaction.close_confirmation_bars",
            "events.pressure_min_bars",
            "events.rejection_recovery_bars",
            "events.retest_window_bars",
            "events.retest_confirmation_bars",
        }
    ),
    OptimizationStage.FEATURE_ABLATION: frozenset(),
}


class StageEvaluator(Protocol):
    def __call__(
        self,
        trial: TrialConfig,
        config: ResolvedTrendlineFamilyConfig,
        window: WalkForwardFold | HoldoutPlan,
        window_kind: str,
    ) -> WindowResult: ...


class HoldoutOpenRegistry:
    """Per-run one-time holdout opener. Identical audited replays are idempotent."""

    def __init__(self) -> None:
        self._opened: dict[tuple[str, str], str] = {}

    def register(self, audit: HoldoutOpenAudit) -> None:
        key = (audit.finalist_freeze_id, audit.target)
        prior = self._opened.get(key)
        if prior is None:
            self._opened[key] = audit.audit_id
            return
        if prior != audit.audit_id:
            raise ContractValidationError("conflicting holdout open request is already registered")


def owned_parameters(stage: OptimizationStage | str) -> frozenset[str]:
    return _OWNED_PARAMETERS[OptimizationStage(stage)]


def validate_stage_overrides(stage: OptimizationStage | str, overrides: Mapping[str, Any]) -> None:
    stage_value = OptimizationStage(stage)
    if not isinstance(overrides, Mapping) or any(not isinstance(key, str) or not key for key in overrides):
        raise ContractValidationError("stage overrides must be a mapping with non-empty string keys")
    unknown = set(overrides).difference(_OWNED_PARAMETERS[stage_value])
    if unknown:
        raise ContractValidationError(
            f"{stage_value.value} overrides cross-stage or unknown parameters: {sorted(unknown)}"
        )
    if stage_value is OptimizationStage.FEATURE_ABLATION and overrides:
        raise ContractValidationError("feature ablation has typed feature groups, not runtime parameter overrides")


def apply_stage_overrides(
    config: ResolvedTrendlineFamilyConfig,
    *,
    stage: OptimizationStage | str,
    overrides: Mapping[str, Any],
) -> ResolvedTrendlineFamilyConfig:
    """Return a new validated config. Runtime config and YAML remain untouched."""

    if not isinstance(config, ResolvedTrendlineFamilyConfig):
        raise ContractValidationError("base config must be ResolvedTrendlineFamilyConfig")
    stage_value = OptimizationStage(stage)
    validate_stage_overrides(stage_value, overrides)
    sections: dict[str, Any] = {
        name: getattr(config, name)
        for name in (
            "model", "candidate", "matching", "lifecycle", "interaction", "events", "rails", "mtf", "ranking", "repository", "runtime"
        )
    }
    provenance = dict(config.field_provenance)
    for dotted_key, value in sorted(overrides.items()):
        section_name, field_name = dotted_key.split(".", 1)
        sections[section_name] = replace(sections[section_name], **{field_name: value})
        provenance[dotted_key] = f"offline_phase_i:{stage_value.value}"
    return ResolvedTrendlineFamilyConfig.create(
        asset=config.asset,
        timeframe=config.timeframe,
        config_version=config.config_version,
        config=TrendlineFamilyConfig(**sections),
        field_provenance=provenance,
        profile_id=config.profile_id,
        profile_version=config.profile_version,
    )


def enumerate_grid(search_space: Mapping[str, Sequence[Any]], *, maximum_trial_count: int) -> tuple[Mapping[str, Any], ...]:
    if isinstance(maximum_trial_count, bool) or not isinstance(maximum_trial_count, int) or maximum_trial_count < 1:
        raise ContractValidationError("maximum_trial_count must be a positive integer")
    if not isinstance(search_space, Mapping) or any(not isinstance(key, str) or not key for key in search_space):
        raise ContractValidationError("search_space must be a mapping with non-empty parameter names")
    keys = tuple(sorted(search_space))
    values: list[tuple[Any, ...]] = []
    for key in keys:
        domain = search_space[key]
        if isinstance(domain, (str, bytes)) or not isinstance(domain, Sequence) or not domain:
            raise ContractValidationError(f"search domain {key} must be a non-empty sequence")
        canonical: dict[str, Any] = {}
        for value in domain:
            canonical.setdefault(canonical_json(value), value)
        values.append(tuple(canonical[item] for item in sorted(canonical)))
    combinations: list[Mapping[str, Any]] = []
    for combination in product(*values):
        candidate = {key: value for key, value in zip(keys, combination, strict=True)}
        combinations.append(candidate)
        if len(combinations) > maximum_trial_count:
            raise ContractValidationError("search space exceeds maximum_trial_count")
    return tuple(combinations or ({},))


def resolve_evaluation_spec(
    *,
    evaluator: StageEvaluator,
    stage: OptimizationStage,
    explicit_spec: StageEvaluationSpec | None = None,
) -> StageEvaluationSpec:
    """Resolve evaluator semantics. Anonymous callables never receive a trial ID."""

    factory = getattr(evaluator, "evaluation_spec", None)
    if callable(factory):
        spec = factory()
        if not isinstance(spec, StageEvaluationSpec):
            raise ContractValidationError("evaluator evaluation_spec() must return StageEvaluationSpec")
        if spec.stage is not stage:
            raise ContractValidationError("evaluator evaluation spec stage mismatch")
        if explicit_spec is not None and explicit_spec != spec:
            raise ContractValidationError("explicit evaluator spec does not match evaluator semantics")
        return spec
    if explicit_spec is None:
        raise ContractValidationError("evaluator requires evaluation_spec() or explicit StageEvaluationSpec")
    if not isinstance(explicit_spec, StageEvaluationSpec) or explicit_spec.stage is not stage:
        raise ContractValidationError("explicit evaluator spec must match optimization stage")
    return explicit_spec


def verify_trial_evaluator_spec(
    *, trial: TrialConfig, evaluator: StageEvaluator, explicit_spec: StageEvaluationSpec | None = None
) -> StageEvaluationSpec:
    spec = resolve_evaluation_spec(evaluator=evaluator, stage=trial.stage, explicit_spec=explicit_spec)
    if spec.spec_id != trial.evaluation_spec.spec_id:
        raise ContractValidationError("supplied evaluator semantics do not match trial evaluation_spec")
    return spec


def build_trial_config(
    *,
    stage: OptimizationStage | str,
    dataset: ImmutableHistoricalFrame,
    fold_plan: FoldPlan,
    baseline_config: ResolvedTrendlineFamilyConfig,
    objective: ObjectiveSpec,
    parameter_overrides: Mapping[str, Any],
    seed: int = 0,
    evaluation_context: Mapping[str, Any] | None = None,
    evaluation_spec: StageEvaluationSpec | None = None,
    trial_kind: str = "primary",
    counterfactual_of_trial_id: str | None = None,
    reverted_parameter: str | None = None,
) -> TrialConfig:
    stage_value = OptimizationStage(stage)
    if dataset.asset != baseline_config.asset or dataset.timeframe != baseline_config.timeframe:
        raise ContractValidationError("dataset identity must equal base config identity")
    if dataset.dataset_hash != fold_plan.data_hash:
        raise ContractValidationError("dataset hash must equal fold plan hash")
    validate_stage_overrides(stage_value, parameter_overrides)
    return TrialConfig(
        stage=stage_value,
        asset=dataset.asset,
        timeframe=dataset.timeframe,
        parameter_overrides=parameter_overrides,
        baseline_config_hash=baseline_config.resolved_config_hash,
        dataset_hash=dataset.dataset_hash,
        fold_plan_id=fold_plan.fold_plan_id,
        objective=objective,
        model_version=baseline_config.model_version,
        config_version=baseline_config.config_version,
        seed=seed,
        evaluation_context={} if evaluation_context is None else evaluation_context,
        evaluation_spec=evaluation_spec,
        trial_kind=trial_kind,
        counterfactual_of_trial_id=counterfactual_of_trial_id,
        reverted_parameter=reverted_parameter,
    )


def run_validation_trial(
    *,
    trial: TrialConfig,
    config: ResolvedTrendlineFamilyConfig,
    fold_plan: FoldPlan,
    evaluator: StageEvaluator,
    evaluation_spec: StageEvaluationSpec | None = None,
) -> TrialResult:
    verify_trial_evaluator_spec(trial=trial, evaluator=evaluator, explicit_spec=evaluation_spec)
    started = perf_counter()
    windows: list[WindowResult] = []
    try:
        for fold in fold_plan.folds:
            result = evaluator(trial, config, fold, "validation")
            if result.trial_id != trial.trial_id or result.fold_id != fold.fold_id or result.window_kind != "validation":
                raise ContractValidationError("evaluator returned an incompatible validation window")
            windows.append(result)
    except ContractValidationError as exc:
        return _with_objective_gate(TrialResult(
            trial=trial, status=TrialStatus.INVALID, window_results=tuple(windows), failure_code=FailureCode.DATA_INVALID,
            failure_reason=_bounded_error(exc), runtime_diagnostics={"evaluated_fold_count": len(windows), "runtime_seconds": perf_counter() - started},
        ), required_fold_count=len(fold_plan.folds))
    except Exception as exc:  # pragma: no cover - persisted containment boundary
        return _with_objective_gate(TrialResult(
            trial=trial, status=TrialStatus.FAILED, window_results=tuple(windows), failure_code=FailureCode.INTERNAL_ERROR,
            failure_reason=_bounded_error(exc), runtime_diagnostics={"evaluated_fold_count": len(windows), "runtime_seconds": perf_counter() - started},
        ), required_fold_count=len(fold_plan.folds))
    result = TrialResult(
        trial=trial, status=TrialStatus.COMPLETED, window_results=tuple(windows),
        aggregate_metrics=aggregate_window_metrics(windows, objective=trial.objective),
        runtime_diagnostics={"evaluated_fold_count": len(windows), "runtime_seconds": perf_counter() - started},
    )
    return _with_objective_gate(result, required_fold_count=len(fold_plan.folds))


def build_objective_gate(
    result: TrialResult,
    *,
    required_fold_count: int,
    baseline: TrialResult | None = None,
) -> ObjectiveGate:
    """Apply every objective gate with explicit maximize/minimize semantics."""

    objective = result.trial.objective
    primary_by_window = [window.metric(objective.primary_metric) for window in result.window_results]
    defined = [metric for metric in primary_by_window if metric is not None and metric.value is not None]
    primary = result.metric(objective.primary_metric)
    worst = result.metric(f"{objective.primary_metric}__worst")
    sample_count = 0 if primary is None else primary.sample_count
    latency = result.runtime_diagnostics.get("latency_ms")
    if latency is not None and (isinstance(latency, bool) or not isinstance(latency, (int, float))):
        latency = None
    churn_metric = result.metric("family_churn_rate") or result.metric("churn_rate")
    churn = None if churn_metric is None else churn_metric.value
    comparable: bool | None = None
    if baseline is not None:
        comparable = _population_signature(result) == _population_signature(baseline)
    reasons: list[str] = []
    if result.status is not TrialStatus.COMPLETED:
        reasons.append("trial_not_completed")
    coverage = 0.0 if required_fold_count == 0 else len(defined) / required_fold_count
    failed_count = max(0, required_fold_count - len(defined))
    if coverage < objective.minimum_fold_coverage:
        reasons.append("minimum_fold_coverage_not_met")
    if failed_count / required_fold_count > objective.maximum_failure_rate:
        reasons.append("maximum_failure_rate_exceeded")
    if primary is None or primary.value is None:
        reasons.append("primary_metric_undefined")
    elif sample_count < objective.minimum_sample_count:
        reasons.append("minimum_sample_count_not_met")
    if objective.worst_window_floor is not None and (worst is None or worst.value is None or worst.value < objective.worst_window_floor):
        reasons.append("worst_window_floor_not_met")
    if objective.worst_window_ceiling is not None and (worst is None or worst.value is None or worst.value > objective.worst_window_ceiling):
        reasons.append("worst_window_ceiling_exceeded")
    if objective.maximum_latency_ms is not None and (latency is None or float(latency) > objective.maximum_latency_ms):
        reasons.append("maximum_latency_ms_exceeded")
    if objective.maximum_churn_rate is not None and (churn is None or churn > objective.maximum_churn_rate):
        reasons.append("maximum_churn_rate_exceeded")
    if objective.require_comparable_population and baseline is not None and not comparable:
        reasons.append("population_not_comparable")
    if any(window.diagnostics.get("causality_ok") is False for window in result.window_results):
        reasons.append("causality_violation")
    return ObjectiveGate(
        objective=objective,
        required_fold_count=required_fold_count,
        defined_primary_fold_count=len(defined),
        failed_or_invalid_window_count=failed_count,
        evaluated_row_count=sum(window.evaluated_bar_count for window in result.window_results),
        primary_value=None if primary is None else primary.value,
        worst_window_value=None if worst is None else worst.value,
        latency_ms=None if latency is None else float(latency),
        churn_rate=churn,
        comparable_population=comparable,
        passed=not reasons,
        rejection_reasons=tuple(sorted(set(reasons))),
    )


def _with_objective_gate(result: TrialResult, *, required_fold_count: int, baseline: TrialResult | None = None) -> TrialResult:
    return TrialResult(
        trial=result.trial, status=result.status, window_results=result.window_results,
        aggregate_metrics=result.aggregate_metrics, parameter_effect_audits=result.parameter_effect_audits,
        failure_code=result.failure_code, failure_reason=result.failure_reason,
        runtime_diagnostics=result.runtime_diagnostics,
        objective_gate=build_objective_gate(result, required_fold_count=required_fold_count, baseline=baseline),
        counterfactual_results=result.counterfactual_results,
    )


def _population_signature(result: TrialResult) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (window.fold_id, str(window.diagnostics.get("evaluated_index_hash", f"{window.fold_id}:{window.evaluated_bar_count}")))
            for window in result.window_results
        )
    )


def _config_value(config: ResolvedTrendlineFamilyConfig, dotted_name: str) -> Any:
    section, field = dotted_name.split(".", 1)
    return getattr(getattr(config, section), field)


def attach_parameter_effect_audits(
    *,
    baseline_config: ResolvedTrendlineFamilyConfig,
    dataset: ImmutableHistoricalFrame,
    fold_plan: FoldPlan,
    evaluator: StageEvaluator,
    full_trial: TrialResult,
    seed: int,
    evaluation_spec: StageEvaluationSpec | None = None,
) -> TrialResult:
    """Run one independent marginal counterfactual per tuned parameter."""

    if full_trial.trial.trial_kind != "primary":
        raise ContractValidationError("only primary trials may receive parameter effect audits")
    if not full_trial.trial.parameter_overrides:
        return full_trial
    counterfactuals: list[TrialResult] = []
    audits: list[ParameterEffectAudit] = []
    for parameter_name, trial_value in sorted(full_trial.trial.parameter_overrides.items()):
        baseline_value = _config_value(baseline_config, parameter_name)
        counter_overrides = dict(full_trial.trial.parameter_overrides)
        counter_overrides[parameter_name] = baseline_value
        counter_trial = build_trial_config(
            stage=full_trial.trial.stage,
            dataset=dataset,
            fold_plan=fold_plan,
            baseline_config=baseline_config,
            objective=full_trial.trial.objective,
            parameter_overrides=counter_overrides,
            seed=seed,
            evaluation_context=full_trial.trial.evaluation_context,
            evaluation_spec=full_trial.trial.evaluation_spec,
            trial_kind="counterfactual",
            counterfactual_of_trial_id=full_trial.trial.trial_id,
            reverted_parameter=parameter_name,
        )
        try:
            counter_config = apply_stage_overrides(
                baseline_config, stage=full_trial.trial.stage, overrides=counter_overrides
            )
            counter_result = run_validation_trial(
                trial=counter_trial,
                config=counter_config,
                fold_plan=fold_plan,
                evaluator=evaluator,
                evaluation_spec=evaluation_spec,
            )
        except ContractValidationError as exc:
            counter_result = _with_objective_gate(TrialResult(
                trial=counter_trial, status=TrialStatus.INVALID, failure_code=FailureCode.DATA_INVALID,
                failure_reason=_bounded_error(exc),
            ), required_fold_count=len(fold_plan.folds))
        counterfactuals.append(counter_result)
        full_stage = _diagnostic_fingerprint(full_trial, "stage_output_fingerprint")
        counter_stage = _diagnostic_fingerprint(counter_result, "stage_output_fingerprint")
        full_forbidden = _diagnostic_fingerprint(full_trial, "forbidden_output_fingerprint")
        counter_forbidden = _diagnostic_fingerprint(counter_result, "forbidden_output_fingerprint")
        effect = (
            full_trial.status is TrialStatus.COMPLETED
            and counter_result.status is TrialStatus.COMPLETED
            and full_stage != counter_stage
        )
        leakage = (
            full_trial.status is not TrialStatus.COMPLETED
            or counter_result.status is not TrialStatus.COMPLETED
            or full_forbidden != counter_forbidden
        )
        audits.append(
            ParameterEffectAudit(
                parameter_name=parameter_name,
                owning_stage=full_trial.trial.stage,
                baseline_value=baseline_value,
                trial_value=trial_value,
                expected_affected_outputs=("stage_output_fingerprint",),
                observed_changed_outputs=("stage_output_fingerprint",) if effect else (),
                forbidden_outputs_checked=("forbidden_output_fingerprint",),
                effect_detected=effect,
                leakage_detected=leakage,
                decision=PromotionDecision.PROMOTE if effect and not leakage else PromotionDecision.REJECT,
                counterfactual_trial_id=counter_trial.trial_id,
                counterfactual_result_id=counter_result.result_id,
            )
        )
    return TrialResult(
        trial=full_trial.trial, status=full_trial.status, window_results=full_trial.window_results,
        aggregate_metrics=full_trial.aggregate_metrics, parameter_effect_audits=tuple(audits),
        failure_code=full_trial.failure_code,
        failure_reason=full_trial.failure_reason,
        runtime_diagnostics=full_trial.runtime_diagnostics, objective_gate=full_trial.objective_gate,
        counterfactual_results=tuple(counterfactuals),
    )


def run_stage_grid(
    *,
    stage: OptimizationStage | str,
    dataset: ImmutableHistoricalFrame,
    fold_plan: FoldPlan,
    baseline_config: ResolvedTrendlineFamilyConfig,
    objective: ObjectiveSpec,
    search_space: Mapping[str, Sequence[Any]],
    evaluator: StageEvaluator,
    maximum_trial_count: int,
    seed: int = 0,
    evaluation_spec: StageEvaluationSpec | None = None,
) -> tuple[TrialResult, tuple[TrialResult, ...]]:
    stage_value = OptimizationStage(stage)
    validate_stage_overrides(stage_value, search_space)
    resolved_evaluation_spec = resolve_evaluation_spec(
        evaluator=evaluator, stage=stage_value, explicit_spec=evaluation_spec
    )
    baseline_trial = build_trial_config(
        stage=stage_value, dataset=dataset, fold_plan=fold_plan, baseline_config=baseline_config, objective=objective,
        parameter_overrides={}, seed=seed, evaluation_spec=resolved_evaluation_spec,
    )
    baseline = run_validation_trial(
        trial=baseline_trial,
        config=baseline_config,
        fold_plan=fold_plan,
        evaluator=evaluator,
        evaluation_spec=resolved_evaluation_spec,
    )
    results: list[TrialResult] = []
    for overrides in enumerate_grid(search_space, maximum_trial_count=maximum_trial_count):
        if not overrides:
            continue
        trial = build_trial_config(
            stage=stage_value, dataset=dataset, fold_plan=fold_plan, baseline_config=baseline_config, objective=objective,
            parameter_overrides=overrides, seed=seed, evaluation_spec=resolved_evaluation_spec,
        )
        try:
            config = apply_stage_overrides(baseline_config, stage=stage_value, overrides=overrides)
        except ContractValidationError as exc:
            invalid = TrialResult(
                trial=trial, status=TrialStatus.INVALID, failure_code=FailureCode.PARAMETER_OWNERSHIP_VIOLATION,
                failure_reason=_bounded_error(exc),
            )
            audited = attach_parameter_effect_audits(
                baseline_config=baseline_config,
                dataset=dataset,
                fold_plan=fold_plan,
                evaluator=evaluator,
                full_trial=_with_objective_gate(
                    invalid,
                    required_fold_count=len(fold_plan.folds),
                    baseline=baseline,
                ),
                seed=seed,
                evaluation_spec=resolved_evaluation_spec,
            )
            results.append(_with_objective_gate(audited, required_fold_count=len(fold_plan.folds), baseline=baseline))
            continue
        full = run_validation_trial(
            trial=trial,
            config=config,
            fold_plan=fold_plan,
            evaluator=evaluator,
            evaluation_spec=resolved_evaluation_spec,
        )
        audited = attach_parameter_effect_audits(
            baseline_config=baseline_config, dataset=dataset, fold_plan=fold_plan, evaluator=evaluator,
            full_trial=full, seed=seed, evaluation_spec=resolved_evaluation_spec,
        )
        results.append(_with_objective_gate(audited, required_fold_count=len(fold_plan.folds), baseline=baseline))
    return baseline, tuple(results)


def select_validation_finalist(*, baseline: TrialResult, trials: Sequence[TrialResult]) -> TrialResult | None:
    objective = baseline.trial.objective
    eligible = [
        trial for trial in trials
        if _eligible_validation_trial(trial, objective=objective)
        and _improves_over_baseline(baseline=baseline, candidate=trial, objective=objective)
    ]
    if not eligible:
        return None
    direction = -1.0 if objective.maximize else 1.0
    return sorted(
        eligible,
        key=lambda result: (
            direction * _metric_value(result, objective.primary_metric, maximize=objective.maximize),
            direction * _metric_value(result, f"{objective.primary_metric}__worst", maximize=objective.maximize),
            result.trial.trial_id,
        ),
    )[0]


def freeze_validation_finalist(*, baseline: TrialResult, finalist: TrialResult, fold_plan: FoldPlan) -> FinalistFreeze:
    if baseline.status is not TrialStatus.COMPLETED or finalist.status is not TrialStatus.COMPLETED:
        raise ContractValidationError("only completed validation results can be frozen")
    if finalist.objective_gate is None or not finalist.objective_gate.passed:
        raise ContractValidationError("finalist must pass validation gate before holdout freeze")
    if baseline.trial.fold_plan_id != fold_plan.fold_plan_id or finalist.trial.fold_plan_id != fold_plan.fold_plan_id:
        raise ContractValidationError("finalist freeze fold plan mismatch")
    return FinalistFreeze(
        stage=finalist.trial.stage,
        fold_plan_id=fold_plan.fold_plan_id,
        baseline_validation_result_id=baseline.result_id,
        finalist_validation_result_id=finalist.result_id,
        objective=finalist.trial.objective,
        evaluation_spec_id=finalist.trial.evaluation_spec.spec_id,
    )


def build_holdout_open_audit(
    *, finalist_freeze: FinalistFreeze, fold_plan: FoldPlan, result: TrialResult, target: str
) -> HoldoutOpenAudit:
    expected_result = (
        finalist_freeze.baseline_validation_result_id if target == "baseline" else finalist_freeze.finalist_validation_result_id
    )
    if result.result_id != expected_result or result.trial.stage is not finalist_freeze.stage:
        raise ContractValidationError("holdout audit result does not match frozen validation evidence")
    if result.trial.evaluation_spec.spec_id != finalist_freeze.evaluation_spec_id:
        raise ContractValidationError("holdout audit evaluator semantics do not match finalist freeze")
    return HoldoutOpenAudit(
        finalist_freeze_id=finalist_freeze.freeze_id,
        holdout_plan_id=fold_plan.holdout.holdout_plan_id,
        target=target,
        trial_id=result.trial.trial_id,
        validation_result_id=result.result_id,
    )


def evaluate_holdout_once(
    *,
    validation_finalist: TrialResult,
    baseline_config: ResolvedTrendlineFamilyConfig,
    fold_plan: FoldPlan,
    evaluator: StageEvaluator,
    finalist_freeze: FinalistFreeze | None = None,
    holdout_open_audit: HoldoutOpenAudit | None = None,
    holdout_open_registry: HoldoutOpenRegistry | None = None,
    evaluation_spec: StageEvaluationSpec | None = None,
    baseline_holdout: TrialResult | None = None,
) -> TrialResult:
    """Evaluate only a validation-frozen request, with its stateful warmup available."""

    if finalist_freeze is None or holdout_open_audit is None or holdout_open_registry is None:
        raise ContractValidationError("holdout requires FinalistFreeze, HoldoutOpenAudit, and HoldoutOpenRegistry")
    if validation_finalist.status is not TrialStatus.COMPLETED:
        raise ContractValidationError("only completed validation finalist may open holdout")
    supplied_spec = verify_trial_evaluator_spec(
        trial=validation_finalist.trial, evaluator=evaluator, explicit_spec=evaluation_spec
    )
    if supplied_spec.spec_id != finalist_freeze.evaluation_spec_id:
        raise ContractValidationError("supplied evaluator semantics do not match finalist freeze")
    if holdout_open_audit.finalist_freeze_id != finalist_freeze.freeze_id:
        raise ContractValidationError("holdout audit does not bind finalist freeze")
    if holdout_open_audit.holdout_plan_id != fold_plan.holdout.holdout_plan_id:
        raise ContractValidationError("holdout audit does not bind holdout plan")
    expected_validation_result_id = (
        finalist_freeze.baseline_validation_result_id
        if holdout_open_audit.target == "baseline"
        else finalist_freeze.finalist_validation_result_id
    )
    if validation_finalist.result_id != expected_validation_result_id:
        raise ContractValidationError("arbitrary non-finalist cannot open holdout")
    if holdout_open_audit.trial_id != validation_finalist.trial.trial_id or holdout_open_audit.validation_result_id != validation_finalist.result_id:
        raise ContractValidationError("holdout audit does not bind requested validation result")
    holdout_open_registry.register(holdout_open_audit)
    config = apply_stage_overrides(
        baseline_config, stage=validation_finalist.trial.stage, overrides=validation_finalist.trial.parameter_overrides
    )
    window = evaluator(validation_finalist.trial, config, fold_plan.holdout, "holdout")
    if window.trial_id != validation_finalist.trial.trial_id or window.fold_id != fold_plan.holdout.holdout_plan_id or window.window_kind != "holdout":
        raise ContractValidationError("evaluator returned an incompatible holdout window")
    result = TrialResult(
        trial=validation_finalist.trial, status=TrialStatus.COMPLETED, window_results=(window,),
        aggregate_metrics=aggregate_window_metrics((window,), objective=validation_finalist.trial.objective),
        parameter_effect_audits=validation_finalist.parameter_effect_audits,
        counterfactual_results=validation_finalist.counterfactual_results,
        runtime_diagnostics={"holdout_opened": True, "holdout_reason": holdout_open_audit.open_reason},
    )
    return _with_objective_gate(result, required_fold_count=1, baseline=baseline_holdout)


def verify_persisted_trial_result(
    *,
    result: TrialResult,
    fold_plan: FoldPlan,
    window_kind: str,
    baseline: TrialResult | None = None,
    baseline_parameter_values: Mapping[str, Any] | None = None,
) -> None:
    """Rebuild persisted aggregate/gate evidence from immutable windows."""

    if window_kind not in {"validation", "holdout"}:
        raise ContractValidationError("persisted result window_kind must be validation or holdout")
    if result.trial.trial_kind == "counterfactual" and result.counterfactual_results:
        raise ContractValidationError("counterfactual results must be terminal artifacts")
    windows = result.window_results
    fold_ids = tuple(window.fold_id for window in windows)
    if len(set(fold_ids)) != len(fold_ids):
        raise ContractValidationError("persisted result has duplicate fold IDs")
    if any(window.window_kind != window_kind for window in windows):
        raise ContractValidationError("persisted result has incompatible window kind")
    if window_kind == "validation":
        expected_ids = tuple(fold.fold_id for fold in fold_plan.folds)
        if result.status is TrialStatus.COMPLETED and set(fold_ids) != set(expected_ids):
            raise ContractValidationError("completed validation result must contain every planned fold")
        if result.status is not TrialStatus.COMPLETED and not set(fold_ids).issubset(expected_ids):
            raise ContractValidationError("failed validation result contains an unrelated fold")
        required_fold_count = len(expected_ids)
    else:
        expected_ids = (fold_plan.holdout.holdout_plan_id,)
        if result.status is TrialStatus.COMPLETED and fold_ids != expected_ids:
            raise ContractValidationError("completed holdout result must contain exactly planned holdout window")
        if result.status is not TrialStatus.COMPLETED and not set(fold_ids).issubset(expected_ids):
            raise ContractValidationError("failed holdout result contains an unrelated window")
        required_fold_count = 1
    expected_aggregate = aggregate_window_metrics(windows, objective=result.trial.objective)
    if dict(result.aggregate_metrics) != expected_aggregate:
        raise ContractValidationError("persisted aggregate metrics do not match window results")
    canonical = replace(result, objective_gate=None, result_id=None)
    expected_gate = build_objective_gate(canonical, required_fold_count=required_fold_count, baseline=baseline)
    if result.objective_gate != expected_gate:
        raise ContractValidationError("persisted objective gate does not match derived evidence")
    if result.trial.trial_kind == "primary" and window_kind == "validation":
        if baseline_parameter_values is None:
            if result.trial.parameter_overrides:
                raise ContractValidationError("primary parameter audit verification requires persisted baseline values")
        else:
            verify_parameter_effect_audits(
                result=result,
                baseline_parameter_values=baseline_parameter_values,
            )
    elif result.trial.trial_kind == "counterfactual" and result.parameter_effect_audits:
        raise ContractValidationError("counterfactual results cannot carry parameter effect audits")
    if window_kind == "validation":
        for counterfactual in result.counterfactual_results:
            verify_persisted_trial_result(
                result=counterfactual,
                fold_plan=fold_plan,
                window_kind="validation",
                baseline=None,
                baseline_parameter_values=baseline_parameter_values,
            )


def verify_parameter_effect_audits(
    *,
    result: TrialResult,
    baseline_parameter_values: Mapping[str, Any],
) -> None:
    """Rebuild every primary-trial counterfactual audit from persisted evidence."""

    if result.trial.trial_kind != "primary":
        raise ContractValidationError("parameter effect audit verification only accepts primary trials")
    overrides = dict(result.trial.parameter_overrides)
    audits = tuple(result.parameter_effect_audits)
    counterfactuals = tuple(result.counterfactual_results)
    if not overrides:
        if audits or counterfactuals:
            raise ContractValidationError("untuned primary trial cannot carry parameter effect evidence")
        return
    if not isinstance(baseline_parameter_values, Mapping):
        raise ContractValidationError("persisted baseline parameter values must be a mapping")
    expected_parameters = set(overrides)
    audit_by_parameter = {audit.parameter_name: audit for audit in audits}
    if len(audit_by_parameter) != len(audits) or set(audit_by_parameter) != expected_parameters:
        raise ContractValidationError("primary trial must contain exactly one audit per override")
    counterfactual_by_parameter = {counterfactual.trial.reverted_parameter: counterfactual for counterfactual in counterfactuals}
    if (
        len(counterfactual_by_parameter) != len(counterfactuals)
        or None in counterfactual_by_parameter
        or set(counterfactual_by_parameter) != expected_parameters
    ):
        raise ContractValidationError("primary trial must contain exactly one counterfactual per override")
    for parameter_name in sorted(expected_parameters):
        if parameter_name not in baseline_parameter_values:
            raise ContractValidationError("persisted baseline parameter values omit audited parameter")
        audit = audit_by_parameter[parameter_name]
        counterfactual = counterfactual_by_parameter[parameter_name]
        baseline_value = baseline_parameter_values[parameter_name]
        if audit.owning_stage is not result.trial.stage:
            raise ContractValidationError("parameter audit owning stage does not match primary trial")
        if canonical_json(audit.baseline_value) != canonical_json(baseline_value):
            raise ContractValidationError("parameter audit baseline value does not match persisted baseline")
        if canonical_json(audit.trial_value) != canonical_json(overrides[parameter_name]):
            raise ContractValidationError("parameter audit trial value does not match primary override")
        expected_overrides = dict(overrides)
        expected_overrides[parameter_name] = baseline_value
        expected_counterfactual = TrialConfig(
            stage=result.trial.stage,
            asset=result.trial.asset,
            timeframe=result.trial.timeframe,
            parameter_overrides=expected_overrides,
            baseline_config_hash=result.trial.baseline_config_hash,
            dataset_hash=result.trial.dataset_hash,
            fold_plan_id=result.trial.fold_plan_id,
            objective=result.trial.objective,
            model_version=result.trial.model_version,
            config_version=result.trial.config_version,
            seed=result.trial.seed,
            evaluation_context=result.trial.evaluation_context,
            evaluation_spec=result.trial.evaluation_spec,
            trial_kind="counterfactual",
            counterfactual_of_trial_id=result.trial.trial_id,
            reverted_parameter=parameter_name,
        )
        if counterfactual.trial.to_dict() != expected_counterfactual.to_dict():
            raise ContractValidationError("counterfactual request does not revert exactly one primary override")
        if audit.counterfactual_trial_id != counterfactual.trial.trial_id or audit.counterfactual_result_id != counterfactual.result_id:
            raise ContractValidationError("parameter audit counterfactual identity mismatch")
        full_stage = _diagnostic_fingerprint(result, "stage_output_fingerprint")
        counter_stage = _diagnostic_fingerprint(counterfactual, "stage_output_fingerprint")
        full_forbidden = _diagnostic_fingerprint(result, "forbidden_output_fingerprint")
        counter_forbidden = _diagnostic_fingerprint(counterfactual, "forbidden_output_fingerprint")
        effect = (
            result.status is TrialStatus.COMPLETED
            and counterfactual.status is TrialStatus.COMPLETED
            and full_stage != counter_stage
        )
        leakage = (
            result.status is not TrialStatus.COMPLETED
            or counterfactual.status is not TrialStatus.COMPLETED
            or full_forbidden != counter_forbidden
        )
        expected_outputs = ("stage_output_fingerprint",) if effect else ()
        expected_decision = PromotionDecision.PROMOTE if effect and not leakage else PromotionDecision.REJECT
        if audit.expected_affected_outputs != ("stage_output_fingerprint",):
            raise ContractValidationError("parameter audit affected-output contract is not canonical")
        if audit.forbidden_outputs_checked != ("forbidden_output_fingerprint",):
            raise ContractValidationError("parameter audit forbidden-output contract is not canonical")
        if audit.effect_detected != effect or audit.leakage_detected != leakage:
            raise ContractValidationError("parameter audit effect or leakage claim does not match evidence")
        if audit.observed_changed_outputs != expected_outputs:
            raise ContractValidationError("parameter audit observed outputs do not match evidence")
        if audit.decision is not expected_decision:
            raise ContractValidationError("parameter audit decision does not match evidence")


def build_promotion_recommendation(
    *,
    baseline_validation: TrialResult,
    finalist_validation: TrialResult | None,
    baseline_holdout: TrialResult | None,
    finalist_holdout: TrialResult | None,
    validation_trials: Sequence[TrialResult] = (),
) -> PromotionRecommendation:
    """Build a review-only decision after reapplying all objective gates."""

    stage = baseline_validation.trial.stage
    objective = baseline_validation.trial.objective
    baseline_validation_gate = build_objective_gate(
        baseline_validation, required_fold_count=max(1, len(baseline_validation.window_results))
    )
    if finalist_validation is None:
        # Artifact replay can supply trial-ID order while fresh runs use grid order.
        # Canonicalize before flattening equal-named audits into recommendation evidence.
        canonical_trials = tuple(
            sorted(
                validation_trials,
                key=lambda trial: (
                    canonical_json(trial.trial.parameter_overrides),
                    trial.trial.trial_id,
                ),
            )
        )
        audits = tuple(audit for trial in canonical_trials for audit in trial.parameter_effect_audits)
        return PromotionRecommendation(
            stage=stage, baseline_result_id=baseline_validation.result_id, finalist_result_id=None,
            decision=PromotionDecision.REJECT,
            rationale=("no_validation_trial_passed_stage_owned_gates",),
            validation_evidence={"baseline": baseline_validation.to_dict()}, holdout_evidence={},
            parameter_effect_audits=audits, baseline_validation_gate=baseline_validation_gate,
        )
    finalist_validation_gate = build_objective_gate(
        finalist_validation, required_fold_count=max(1, len(finalist_validation.window_results)), baseline=baseline_validation
    )
    audits = finalist_validation.parameter_effect_audits
    baseline_holdout_gate = None
    finalist_holdout_gate = None
    if baseline_holdout is not None:
        baseline_holdout_gate = build_objective_gate(baseline_holdout, required_fold_count=1)
    if finalist_holdout is not None:
        finalist_holdout_gate = build_objective_gate(finalist_holdout, required_fold_count=1, baseline=baseline_holdout)
    gate_evidence = (
        baseline_validation_gate,
        finalist_validation_gate,
        baseline_holdout_gate,
        finalist_holdout_gate,
    )
    if any(not audit.effect_detected or audit.leakage_detected for audit in audits):
        decision, rationale = PromotionDecision.REJECT, ("parameter_effect_or_isolation_audit_failed",)
    elif baseline_holdout is None or finalist_holdout is None:
        decision, rationale = PromotionDecision.HOLD, ("validation_finalist_frozen_holdout_not_opened",)
    elif any(gate is None or not gate.passed for gate in gate_evidence):
        decision, rationale = PromotionDecision.REJECT, ("objective_gate_failed",)
    elif not _improves_over_baseline(baseline=baseline_validation, candidate=finalist_validation, objective=objective):
        decision, rationale = PromotionDecision.REJECT, ("validation_did_not_improve_owned_objective",)
    elif not _improves_over_baseline(baseline=baseline_holdout, candidate=finalist_holdout, objective=objective):
        decision, rationale = PromotionDecision.REJECT, ("untouched_holdout_did_not_confirm_owned_objective",)
    else:
        decision, rationale = PromotionDecision.PROMOTE, (
            "validation_and_untouched_holdout_confirm_owned_objective", "human_approval_required_before_any_runtime_change",
        )
    return PromotionRecommendation(
        stage=stage, baseline_result_id=baseline_validation.result_id, finalist_result_id=finalist_validation.result_id,
        decision=decision, rationale=rationale,
        validation_evidence={
            "baseline": baseline_validation.to_dict(), "finalist": finalist_validation.to_dict(),
            "primary_delta": metric_delta(
                f"{objective.primary_metric}_delta", baseline_validation.metric(objective.primary_metric),
                finalist_validation.metric(objective.primary_metric),
            ).to_dict(),
        },
        holdout_evidence={
            "baseline": None if baseline_holdout is None else baseline_holdout.to_dict(),
            "finalist": None if finalist_holdout is None else finalist_holdout.to_dict(),
        },
        parameter_effect_audits=audits,
        config_patch_preview={"parameter_overrides": dict(finalist_validation.trial.parameter_overrides)},
        active_consumption_patch_preview={"status": "review_only_no_runtime_mutation"},
        baseline_holdout_result_id=None if baseline_holdout is None else baseline_holdout.result_id,
        finalist_holdout_result_id=None if finalist_holdout is None else finalist_holdout.result_id,
        baseline_validation_gate=baseline_validation_gate,
        finalist_validation_gate=finalist_validation_gate,
        baseline_holdout_gate=baseline_holdout_gate,
        finalist_holdout_gate=finalist_holdout_gate,
        promotion_gate_passed=decision is PromotionDecision.PROMOTE,
    )


def _eligible_validation_trial(trial: TrialResult, *, objective: ObjectiveSpec) -> bool:
    return (
        trial.status is TrialStatus.COMPLETED
        and trial.objective_gate is not None
        and trial.objective_gate.passed
        and bool(trial.parameter_effect_audits)
        and all(audit.effect_detected and not audit.leakage_detected for audit in trial.parameter_effect_audits)
    )


def _improves_over_baseline(*, baseline: TrialResult, candidate: TrialResult, objective: ObjectiveSpec) -> bool:
    if baseline.status is not TrialStatus.COMPLETED or candidate.status is not TrialStatus.COMPLETED:
        return False
    base = baseline.metric(objective.primary_metric)
    trial = candidate.metric(objective.primary_metric)
    if base is None or trial is None or base.value is None or trial.value is None:
        return False
    if trial.sample_count < objective.minimum_sample_count:
        return False
    primary_improves = trial.value > base.value if objective.maximize else trial.value < base.value
    if not primary_improves:
        return False
    # ``allowed_degradation`` is a tolerated worst-window stability loss, not
    # an undisclosed extra primary-improvement margin.
    baseline_worst = baseline.metric(f"{objective.primary_metric}__worst")
    candidate_worst = candidate.metric(f"{objective.primary_metric}__worst")
    if baseline_worst is None or candidate_worst is None or baseline_worst.value is None or candidate_worst.value is None:
        return False
    return (
        candidate_worst.value >= baseline_worst.value - objective.allowed_degradation
        if objective.maximize
        else candidate_worst.value <= baseline_worst.value + objective.allowed_degradation
    )


def _metric_value(result: TrialResult, name: str, *, maximize: bool) -> float:
    metric = result.metric(name)
    if metric is None or metric.value is None:
        return float("-inf") if maximize else float("inf")
    return metric.value


def _diagnostic_fingerprint(result: TrialResult, key: str) -> str:
    return semantic_id(f"trendline-family-{key}", [window.diagnostics.get(key) for window in result.window_results])


def _bounded_error(exc: Exception) -> str:
    return f"{exc.__class__.__name__}:{str(exc).replace(chr(10), ' ')[:240]}"


__all__ = [
    "StageEvaluator", "apply_stage_overrides", "attach_parameter_effect_audits", "build_holdout_open_audit",
    "build_objective_gate", "build_promotion_recommendation", "build_trial_config", "enumerate_grid",
    "evaluate_holdout_once", "freeze_validation_finalist", "HoldoutOpenRegistry", "owned_parameters", "resolve_evaluation_spec",
    "run_stage_grid", "run_validation_trial", "select_validation_finalist", "validate_stage_overrides",
    "verify_parameter_effect_audits", "verify_persisted_trial_result", "verify_trial_evaluator_spec",
]
