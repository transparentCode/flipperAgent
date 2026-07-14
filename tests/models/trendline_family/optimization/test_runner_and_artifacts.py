from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from libs.models.trendline_family.contracts import ContractValidationError
from libs.models.trendline_family.optimization.artifacts import atomic_write_json
from libs.models.trendline_family.optimization.contracts import ObjectiveSpec, OptimizationStage, PromotionDecision
from libs.models.trendline_family.optimization.evaluator import (
    build_holdout_open_audit,
    build_promotion_recommendation,
    enumerate_grid,
    evaluate_holdout_once,
    freeze_validation_finalist,
    HoldoutOpenRegistry,
    run_stage_grid,
    select_validation_finalist,
)
from libs.models.trendline_family.optimization.folds import build_walk_forward_fold_plan
from libs.models.trendline_family.optimization.runner import run_phase_i_evaluation

from .support import dataset, fixture_evaluation_spec, resolved_config, window_result


def test_grid_is_stage_owned_and_holdout_is_not_used_for_selection() -> None:
    source = dataset(rows=72)
    config = resolved_config()
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=3, holdout_bars=8, warmup_bars=5)
    calls: list[str] = []

    def evaluator(trial, _config, window, kind):
        calls.append(kind)
        value = 0.5 + (0.1 if trial.parameter_overrides else 0.0)
        return window_result(
            trial,
            window,
            kind,
            metric_value=value,
            stage_fingerprint=f"stage:{sorted(trial.parameter_overrides.items())}",
            forbidden_fingerprint="candidate-stream-fixed",
        )

    objective = ObjectiveSpec("candidate-v1", "candidate_coverage_ratio", minimum_sample_count=1)
    baseline, trials = run_stage_grid(
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        dataset=source,
        fold_plan=plan,
        baseline_config=config,
        objective=objective,
        search_space={"candidate.lookback_bars": (180, 200)},
        evaluator=evaluator,
        maximum_trial_count=4,
        evaluation_spec=fixture_evaluation_spec("grid"),
    )
    finalist = select_validation_finalist(baseline=baseline, trials=trials)

    assert finalist is not None
    # One full trial plus one isolated counterfactual run per tuned parameter.
    assert calls == ["validation"] * (len(plan.folds) * 5)
    assert finalist.trial.parameter_overrides
    assert all(audit.effect_detected and not audit.leakage_detected for audit in finalist.parameter_effect_audits)

    freeze = freeze_validation_finalist(baseline=baseline, finalist=finalist, fold_plan=plan)
    holdout_registry = HoldoutOpenRegistry()
    baseline_holdout = evaluate_holdout_once(
        validation_finalist=baseline,
        baseline_config=config,
        fold_plan=plan,
        evaluator=evaluator,
        finalist_freeze=freeze,
        holdout_open_audit=build_holdout_open_audit(finalist_freeze=freeze, fold_plan=plan, result=baseline, target="baseline"),
        holdout_open_registry=holdout_registry,
        evaluation_spec=fixture_evaluation_spec("grid"),
    )
    finalist_holdout = evaluate_holdout_once(
        validation_finalist=finalist,
        baseline_config=config,
        fold_plan=plan,
        evaluator=evaluator,
        finalist_freeze=freeze,
        holdout_open_audit=build_holdout_open_audit(finalist_freeze=freeze, fold_plan=plan, result=finalist, target="finalist"),
        holdout_open_registry=holdout_registry,
        evaluation_spec=fixture_evaluation_spec("grid"),
        baseline_holdout=baseline_holdout,
    )
    recommendation = build_promotion_recommendation(
        baseline_validation=baseline,
        finalist_validation=finalist,
        baseline_holdout=baseline_holdout,
        finalist_holdout=finalist_holdout,
    )
    assert calls[-2:] == ["holdout", "holdout"]
    assert recommendation.decision is PromotionDecision.PROMOTE

    with pytest.raises(ContractValidationError, match="cross-stage"):
        run_stage_grid(
            stage=OptimizationStage.CANDIDATE_GEOMETRY,
            dataset=source,
            fold_plan=plan,
            baseline_config=config,
            objective=objective,
            search_space={"matching.max_distance_atr": (0.5,)},
            evaluator=evaluator,
            maximum_trial_count=1,
            evaluation_spec=fixture_evaluation_spec("cross-stage"),
        )


def test_no_effect_is_rejected_and_atomic_serialization_preserves_prior_file(tmp_path: Path) -> None:
    source = dataset(rows=56)
    config = resolved_config()
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=2, holdout_bars=8, warmup_bars=4)

    def no_effect(trial, _config, window, kind):
        return window_result(trial, window, kind, metric_value=0.5, stage_fingerprint="same-stage", forbidden_fingerprint="fixed")

    baseline, trials = run_stage_grid(
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        dataset=source,
        fold_plan=plan,
        baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"),
        search_space={"candidate.lookback_bars": (180,)},
        evaluator=no_effect,
        maximum_trial_count=1,
        evaluation_spec=fixture_evaluation_spec("no-effect"),
    )
    recommendation = build_promotion_recommendation(
        baseline_validation=baseline,
        finalist_validation=None,
        baseline_holdout=None,
        finalist_holdout=None,
    )
    assert trials[0].parameter_effect_audits[0].decision is PromotionDecision.REJECT
    assert recommendation.decision is PromotionDecision.REJECT

    target = tmp_path / "artifact.json"
    atomic_write_json(target, {"value": 1})
    with pytest.raises(ContractValidationError):
        atomic_write_json(target, {"unsupported": object()})
    assert target.read_text(encoding="ascii").strip().endswith('"value":1}')


def test_no_finalist_recommendation_is_permutation_invariant_and_tamper_safe() -> None:
    source = dataset(rows=72)
    config = resolved_config()
    plan = build_walk_forward_fold_plan(
        source,
        initial_train_bars=18,
        validation_bars=8,
        fold_count=3,
        holdout_bars=8,
        warmup_bars=5,
    )

    def no_effect(trial, _config, window, kind):
        return window_result(
            trial,
            window,
            kind,
            metric_value=0.5,
            stage_fingerprint="same-stage",
            forbidden_fingerprint="fixed",
        )

    baseline, trials = run_stage_grid(
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        dataset=source,
        fold_plan=plan,
        baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio", minimum_sample_count=1),
        search_space={
            "candidate.lookback_bars": (180, 200),
            "candidate.min_candidate_quality": (0.30, 0.40),
        },
        evaluator=no_effect,
        maximum_trial_count=4,
        evaluation_spec=fixture_evaluation_spec("recommendation-ordering"),
    )
    assert len(trials) == 4
    assert select_validation_finalist(baseline=baseline, trials=trials) is None
    audit_names = tuple(
        audit.parameter_name
        for trial in trials
        for audit in trial.parameter_effect_audits
    )
    assert audit_names.count("candidate.lookback_bars") == 4
    assert audit_names.count("candidate.min_candidate_quality") == 4

    def recommendation_for(ordered_trials):
        return build_promotion_recommendation(
            baseline_validation=baseline,
            finalist_validation=None,
            baseline_holdout=None,
            finalist_holdout=None,
            validation_trials=ordered_trials,
        )

    grid_order = recommendation_for(trials)
    reversed_order = recommendation_for(tuple(reversed(trials)))
    trial_id_order = recommendation_for(tuple(sorted(trials, key=lambda trial: trial.trial.trial_id)))
    assert grid_order.to_dict() == reversed_order.to_dict() == trial_id_order.to_dict()
    assert grid_order.recommendation_id == reversed_order.recommendation_id == trial_id_order.recommendation_id
    assert grid_order.decision is PromotionDecision.REJECT
    assert grid_order.rationale == ("no_validation_trial_passed_stage_owned_gates",)
    assert grid_order.parameter_effect_audits == reversed_order.parameter_effect_audits

    first_trial = trials[0]
    with pytest.raises(ContractValidationError, match="trial_config_hash"):
        replace(
            first_trial.trial,
            parameter_overrides={
                "candidate.lookback_bars": 240,
                "candidate.min_candidate_quality": 0.30,
            },
        )
    with pytest.raises(ContractValidationError, match="parameter audit must bind"):
        replace(
            first_trial,
            parameter_effect_audits=(
                replace(first_trial.parameter_effect_audits[0], counterfactual_trial_id="tampered"),
                *first_trial.parameter_effect_audits[1:],
            ),
        )


def test_complete_offline_run_persists_invalid_trial_without_config_mutation(tmp_path: Path) -> None:
    source = dataset(rows=56)
    config = resolved_config()
    config_before = config.to_dict()
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=2, holdout_bars=8, warmup_bars=4)

    def evaluator(trial, _config, window, kind):
        return window_result(trial, window, kind, metric_value=0.5, stage_fingerprint="stable", forbidden_fingerprint=source.dataset_hash)

    result = run_phase_i_evaluation(
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        dataset=source,
        fold_plan=plan,
        baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"),
        search_space={"candidate.lookback_bars": (0,)},
        evaluator=evaluator,
        output_root=tmp_path / "phase_i",
        maximum_trial_count=1,
        evaluation_spec=fixture_evaluation_spec("invalid-trial"),
    )

    assert config.to_dict() == config_before
    assert result.trials[0].status.value == "invalid"
    assert result.artifact_paths["trial:" + result.trials[0].trial.trial_id].exists()
    assert (tmp_path / "phase_i" / "final_report.md").exists()


def test_trial_order_is_deterministic_and_failed_trial_cannot_mutate_next_trial() -> None:
    source = dataset(rows=64)
    config = resolved_config()
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=2, holdout_bars=8, warmup_bars=4)
    seen: list[int] = []

    def evaluator(trial, _config, window, kind):
        lookback = int(trial.parameter_overrides.get("candidate.lookback_bars", 180))
        seen.append(lookback)
        if lookback == 190:
            raise RuntimeError("fixture failure")
        return window_result(trial, window, kind, metric_value=0.5, stage_fingerprint=f"{lookback}", forbidden_fingerprint="fixed")

    baseline, trials = run_stage_grid(
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        dataset=source,
        fold_plan=plan,
        baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"),
        search_space={"candidate.lookback_bars": (200, 190)},
        evaluator=evaluator,
        maximum_trial_count=2,
        evaluation_spec=fixture_evaluation_spec("failure-isolation"),
    )
    assert enumerate_grid({"candidate.lookback_bars": (200, 190)}, maximum_trial_count=2) == (
        {"candidate.lookback_bars": 190},
        {"candidate.lookback_bars": 200},
    )
    assert baseline.status.value == "completed"
    assert [trial.status.value for trial in trials] == ["failed", "completed"]
    # The last two evaluations are the controlled trial with its parameter
    # reverted to the true resolved baseline value.
    assert seen[-2:] == [240, 240]
