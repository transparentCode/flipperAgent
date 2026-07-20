"""Bounded Phase-I orchestration. It is research-only and cannot mutate runtime state."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..configuration.contracts import ResolvedTrendlineFamilyConfig
from ..configuration.provenance import configuration_manifest
from .artifacts import CompletionArtifactIndex, RunManifest, build_completion_artifact_index, write_phase_i_artifacts
from .contracts import FinalistFreeze, HoldoutOpenAudit, ObjectiveSpec, OptimizationStage, PromotionRecommendation, StageEvaluationSpec, TrialResult
from .evaluator import (
    StageEvaluator,
    build_holdout_open_audit,
    build_promotion_recommendation,
    evaluate_holdout_once,
    freeze_validation_finalist,
    HoldoutOpenRegistry,
    resolve_evaluation_spec,
    run_stage_grid,
    select_validation_finalist,
)
from .folds import FoldPlan, ImmutableHistoricalFrame


@dataclass(frozen=True)
class PhaseIEvaluationResult:
    manifest: RunManifest
    baseline_validation: TrialResult
    trials: tuple[TrialResult, ...]
    finalist_validation: TrialResult | None
    baseline_holdout: TrialResult | None
    finalist_holdout: TrialResult | None
    recommendation: PromotionRecommendation
    artifact_paths: Mapping[str, Path]
    finalist_freeze: FinalistFreeze | None = None
    holdout_open_audits: tuple[HoldoutOpenAudit, ...] = ()
    completion_index: CompletionArtifactIndex | None = None


def run_phase_i_evaluation(
    *,
    stage: OptimizationStage | str,
    dataset: ImmutableHistoricalFrame,
    fold_plan: FoldPlan,
    baseline_config: ResolvedTrendlineFamilyConfig,
    objective: ObjectiveSpec,
    search_space: Mapping[str, Sequence[Any]],
    evaluator: StageEvaluator,
    output_root: str | Path,
    maximum_trial_count: int,
    seed: int = 0,
    open_holdout: bool = False,
    codebase_project: str | None = None,
    evaluation_spec: StageEvaluationSpec | None = None,
) -> PhaseIEvaluationResult:
    """Run one stage only. Selection uses validation; holdout opens only after a finalist freeze."""

    stage_value = OptimizationStage(stage)
    resolved_evaluation_spec = resolve_evaluation_spec(
        evaluator=evaluator, stage=stage_value, explicit_spec=evaluation_spec
    )
    baseline_parameter_values = {
        stage_value.value: {
            parameter_name: getattr(getattr(baseline_config, parameter_name.split(".", 1)[0]), parameter_name.split(".", 1)[1])
            for parameter_name in sorted(search_space)
        }
    }
    manifest = RunManifest(
        requested_stages=(stage_value,), assets=(dataset.asset,), timeframes=(dataset.timeframe,),
        dataset_hashes={f"{dataset.asset}:{dataset.timeframe}": dataset.dataset_hash},
        fold_plan_ids={f"{dataset.asset}:{dataset.timeframe}": fold_plan.fold_plan_id},
        baseline_config_hashes={f"{dataset.asset}:{dataset.timeframe}": baseline_config.resolved_config_hash},
        search_spaces={stage_value.value: search_space}, objective_versions={stage_value.value: objective.objective_version},
        objective_specs={stage_value.value: objective}, stage_evaluation_specs={stage_value.value: resolved_evaluation_spec},
        maximum_trial_count=maximum_trial_count, holdout_policy={
            "open_holdout": open_holdout, "requires_finalist_freeze": True, "stateful_warmup": True,
        },
        seeds={stage_value.value: seed}, model_version=baseline_config.model_version, config_version=baseline_config.config_version,
        stage_baseline_parameter_values=baseline_parameter_values,
        resolved_configurations={
            f"{dataset.asset}:{dataset.timeframe}": configuration_manifest(baseline_config)
        },
        codebase_project=codebase_project, started_at=datetime.now(timezone.utc),
    )
    baseline, trials = run_stage_grid(
        stage=stage_value, dataset=dataset, fold_plan=fold_plan, baseline_config=baseline_config, objective=objective,
        search_space=search_space, evaluator=evaluator, maximum_trial_count=maximum_trial_count, seed=seed,
        evaluation_spec=resolved_evaluation_spec,
    )
    finalist = select_validation_finalist(baseline=baseline, trials=trials)
    baseline_holdout = None
    finalist_holdout = None
    finalist_freeze = None
    holdout_open_audits: tuple[HoldoutOpenAudit, ...] = ()
    if open_holdout and finalist is not None:
        finalist_freeze = freeze_validation_finalist(baseline=baseline, finalist=finalist, fold_plan=fold_plan)
        holdout_registry = HoldoutOpenRegistry()
        baseline_audit = build_holdout_open_audit(
            finalist_freeze=finalist_freeze, fold_plan=fold_plan, result=baseline, target="baseline"
        )
        finalist_audit = build_holdout_open_audit(
            finalist_freeze=finalist_freeze, fold_plan=fold_plan, result=finalist, target="finalist"
        )
        baseline_holdout = evaluate_holdout_once(
            validation_finalist=baseline, baseline_config=baseline_config, fold_plan=fold_plan, evaluator=evaluator,
            finalist_freeze=finalist_freeze, holdout_open_audit=baseline_audit,
            holdout_open_registry=holdout_registry,
            evaluation_spec=resolved_evaluation_spec,
        )
        finalist_holdout = evaluate_holdout_once(
            validation_finalist=finalist, baseline_config=baseline_config, fold_plan=fold_plan, evaluator=evaluator,
            finalist_freeze=finalist_freeze, holdout_open_audit=finalist_audit,
            holdout_open_registry=holdout_registry,
            evaluation_spec=resolved_evaluation_spec,
            baseline_holdout=baseline_holdout,
        )
        holdout_open_audits = (baseline_audit, finalist_audit)
    recommendation = build_promotion_recommendation(
        baseline_validation=baseline, finalist_validation=finalist, baseline_holdout=baseline_holdout,
        finalist_holdout=finalist_holdout, validation_trials=trials,
    )
    failed_stage_reasons = {
        stage_value.value: "; ".join(
            f"{trial.trial.trial_id}:{trial.failure_reason}" for trial in trials
            if trial.status.value != "completed" and trial.failure_reason is not None
        )
    }
    complete_manifest = RunManifest(
        requested_stages=manifest.requested_stages, assets=manifest.assets, timeframes=manifest.timeframes,
        dataset_hashes=manifest.dataset_hashes, fold_plan_ids=manifest.fold_plan_ids,
        baseline_config_hashes=manifest.baseline_config_hashes, search_spaces=manifest.search_spaces,
        objective_versions=manifest.objective_versions, objective_specs=manifest.objective_specs,
        stage_evaluation_specs=manifest.stage_evaluation_specs, maximum_trial_count=manifest.maximum_trial_count,
        search_strategy=manifest.search_strategy, holdout_policy=manifest.holdout_policy, seeds=manifest.seeds,
        stage_baseline_parameter_values=manifest.stage_baseline_parameter_values,
        resolved_configurations=manifest.resolved_configurations,
        model_version=manifest.model_version, config_version=manifest.config_version, codebase_project=manifest.codebase_project,
        finalist_freeze_id=None if finalist_freeze is None else finalist_freeze.freeze_id,
        holdout_open_audit_ids=tuple(audit.audit_id for audit in holdout_open_audits),
        started_at=manifest.started_at, completed_at=datetime.now(timezone.utc),
        completion_status="completed" if not failed_stage_reasons[stage_value.value] else "completed_with_trial_failures",
        failed_stage_reasons={key: value for key, value in failed_stage_reasons.items() if value},
    )
    completion_index = build_completion_artifact_index(
        manifest=complete_manifest,
        baseline=baseline,
        trials=trials,
        recommendation=recommendation,
        baseline_holdout=baseline_holdout,
        finalist_holdout=finalist_holdout,
        finalist_freeze=finalist_freeze,
        holdout_open_audits=holdout_open_audits,
    )
    complete_manifest = replace(
        complete_manifest,
        completion_index_id=completion_index.index_id,
        run_id=complete_manifest.run_id,
    )
    artifact_paths = write_phase_i_artifacts(
        output_root=output_root, manifest=complete_manifest, fold_plan=fold_plan, baseline=baseline, trials=trials,
        recommendation=recommendation, baseline_holdout=baseline_holdout, finalist_holdout=finalist_holdout,
        finalist_freeze=finalist_freeze, holdout_open_audits=holdout_open_audits, completion_index=completion_index,
    )
    return PhaseIEvaluationResult(
        manifest=complete_manifest, baseline_validation=baseline, trials=trials, finalist_validation=finalist,
        baseline_holdout=baseline_holdout, finalist_holdout=finalist_holdout, recommendation=recommendation,
        artifact_paths=artifact_paths, finalist_freeze=finalist_freeze, holdout_open_audits=holdout_open_audits,
        completion_index=completion_index,
    )


__all__ = ["PhaseIEvaluationResult", "run_phase_i_evaluation"]
