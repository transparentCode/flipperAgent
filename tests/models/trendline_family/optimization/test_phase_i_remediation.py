from __future__ import annotations

from dataclasses import replace
import json

import pytest

from libs.models.trendline_family.contracts import ContractValidationError
from libs.models.trendline_family.optimization.artifacts import (
    ArtifactEnvelope,
    RunManifest,
    VerifiedRunBundle,
    atomic_write_json,
    build_completion_artifact_index,
    verify_artifact_bundle,
)
from libs.models.trendline_family.optimization.candidate_optimizer import CandidateGeometryEvaluator, CandidateOutcomePolicy
from libs.models.trendline_family.optimization.contracts import (
    MetricRecord,
    ObjectiveGate,
    ObjectiveSpec,
    OptimizationStage,
    PromotionDecision,
    PromotionRecommendation,
    WindowResult,
)
from libs.models.trendline_family.optimization.evaluator import (
    HoldoutOpenRegistry,
    build_holdout_open_audit,
    build_promotion_recommendation,
    evaluate_holdout_once,
    freeze_validation_finalist,
    run_validation_trial,
    run_stage_grid,
    select_validation_finalist,
    verify_parameter_effect_audits,
)
from libs.models.trendline_family.optimization.folds import build_walk_forward_fold_plan
from libs.models.trendline_family.optimization.metrics import aggregate_window_metrics, binary_classification_metrics
from libs.models.trendline_family.optimization.runner import run_phase_i_evaluation
from libs.models.trendline_family.optimization.tracker_optimizer import TrackerEvaluator, build_frozen_candidate_stream

from .support import dataset, fixture_evaluation_spec, resolved_config, window_result


def _retarget_counterfactual(counterfactual, *, overrides, reverted_parameter):
    trial = replace(
        counterfactual.trial,
        parameter_overrides=overrides,
        reverted_parameter=reverted_parameter,
        trial_config_hash=None,
        trial_id=None,
    )
    windows = tuple(replace(window, trial_id=trial.trial_id, result_id=None) for window in counterfactual.window_results)
    return replace(counterfactual, trial=trial, window_results=windows, result_id=None)


def _rebuild_freeze_bundle(result, *, fold_plan, finalist_freeze):
    audits = tuple(
        replace(audit, finalist_freeze_id=finalist_freeze.freeze_id, audit_id=None)
        for audit in result.holdout_open_audits
    )
    manifest = replace(
        result.manifest,
        finalist_freeze_id=finalist_freeze.freeze_id,
        holdout_open_audit_ids=tuple(audit.audit_id for audit in audits),
        completion_index_id=None,
        run_id=None,
    )
    index = build_completion_artifact_index(
        manifest=manifest,
        baseline=result.baseline_validation,
        trials=result.trials,
        recommendation=result.recommendation,
        baseline_holdout=result.baseline_holdout,
        finalist_holdout=result.finalist_holdout,
        finalist_freeze=finalist_freeze,
        holdout_open_audits=audits,
    )
    manifest = replace(manifest, completion_index_id=index.index_id, run_id=manifest.run_id)
    return dict(
        manifest=manifest,
        fold_plan=fold_plan,
        baseline_validation=result.baseline_validation,
        trials=result.trials,
        recommendation=result.recommendation,
        baseline_holdout=result.baseline_holdout,
        finalist_holdout=result.finalist_holdout,
        finalist_freeze=finalist_freeze,
        holdout_open_audits=audits,
        completion_index=index,
    )


def test_per_parameter_counterfactual_audits_use_real_baselines_and_isolate_inert_and_leaking_values() -> None:
    source = dataset(rows=72)
    config = resolved_config()
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=3, holdout_bars=8, warmup_bars=4)

    def evaluator(trial, _config, window, kind):
        overrides = trial.parameter_overrides
        return window_result(
            trial,
            window,
            kind,
            metric_value=0.7 if overrides.get("candidate.lookback_bars") == 180 else 0.5,
            stage_fingerprint=f"lookback:{overrides.get('candidate.lookback_bars')}",
            forbidden_fingerprint=f"fixed-stream:min-bars:{overrides.get('candidate.min_bars')}",
        )

    baseline, trials = run_stage_grid(
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        dataset=source,
        fold_plan=plan,
        baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"),
        search_space={"candidate.lookback_bars": (180,), "candidate.min_bars": (50,)},
        evaluator=evaluator,
        maximum_trial_count=1,
        evaluation_spec=fixture_evaluation_spec("counterfactual-audit"),
    )
    trial = trials[0]
    audits = {audit.parameter_name: audit for audit in trial.parameter_effect_audits}
    assert audits["candidate.lookback_bars"].baseline_value == config.candidate.lookback_bars
    assert audits["candidate.lookback_bars"].effect_detected
    assert not audits["candidate.lookback_bars"].leakage_detected
    assert not audits["candidate.min_bars"].effect_detected
    assert audits["candidate.min_bars"].leakage_detected
    assert all(audit.counterfactual_result_id in {item.result_id for item in trial.counterfactual_results} for audit in audits.values())
    assert select_validation_finalist(baseline=baseline, trials=trials) is None


def test_direction_aware_worst_metrics_and_macro_f1_are_truthful() -> None:
    objective = ObjectiveSpec("loss-v1", "loss", maximize=False, worst_window_ceiling=1.0)
    windows = (
        WindowResult("trial", "fold-1", "validation", (MetricRecord("loss", 0.2, sample_count=1, valid_row_count=1),), 1),
        WindowResult("trial", "fold-2", "validation", (MetricRecord("loss", 1.5, sample_count=1, valid_row_count=1),), 1),
    )
    metrics = aggregate_window_metrics(windows, objective=objective)
    assert metrics["loss__worst"].value == 1.5
    classification = {metric.name: metric for metric in binary_classification_metrics(labels=[True, True, False, False], predictions=[True, False, False, False])}
    assert classification["positive_f1"].value == pytest.approx(2.0 / 3.0)
    assert classification["negative_f1"].value == pytest.approx(0.8)
    assert classification["macro_f1"].value == pytest.approx(11.0 / 15.0)


def test_objective_gates_reject_partial_coverage_and_minimized_worst_window() -> None:
    source = dataset(rows=72)
    config = resolved_config()
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=3, holdout_bars=8, warmup_bars=4)

    def partial(trial, _config, window, kind):
        value = 0.8 if window.fold_index == 0 else None
        return WindowResult(
            trial_id=trial.trial_id,
            fold_id=window.fold_id,
            window_kind=kind,
            metrics=(
                MetricRecord("candidate_coverage_ratio", value=value, sample_count=8, valid_row_count=8)
                if value is not None
                else MetricRecord("candidate_coverage_ratio", value=None, sample_count=8, undefined_reason="fixture_undefined")
            ,),
            evaluated_bar_count=8,
            diagnostics={
                "stage_output_fingerprint": str(sorted(trial.parameter_overrides.items())),
                "forbidden_output_fingerprint": "fixed",
            },
        )

    baseline, trials = run_stage_grid(
        stage=OptimizationStage.CANDIDATE_GEOMETRY, dataset=source, fold_plan=plan, baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio", minimum_fold_coverage=1.0, maximum_failure_rate=0.0),
        search_space={"candidate.lookback_bars": (180,)}, evaluator=partial, maximum_trial_count=1,
        evaluation_spec=fixture_evaluation_spec("partial-coverage"),
    )
    assert trials[0].objective_gate is not None
    assert not trials[0].objective_gate.passed
    assert "minimum_fold_coverage_not_met" in trials[0].objective_gate.rejection_reasons
    assert "maximum_failure_rate_exceeded" in trials[0].objective_gate.rejection_reasons
    assert select_validation_finalist(baseline=baseline, trials=trials) is None

    maximize = ObjectiveSpec("quality-v1", "quality", maximize=True)
    maximize_metrics = aggregate_window_metrics(
        (
            WindowResult("t", "a", "validation", (MetricRecord("quality", 0.4, sample_count=1, valid_row_count=1),), 1),
            WindowResult("t", "b", "validation", (MetricRecord("quality", 0.9, sample_count=1, valid_row_count=1),), 1),
        ),
        objective=maximize,
    )
    assert maximize_metrics["quality__worst"].value == 0.4


def test_candidate_evaluation_semantics_change_trial_identity() -> None:
    source = dataset(rows=56)
    config = resolved_config()
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=2, holdout_bars=8, warmup_bars=4)
    first = CandidateGeometryEvaluator(dataset=source, outcome_policy=CandidateOutcomePolicy(horizon_bars=1))
    second = CandidateGeometryEvaluator(dataset=source, outcome_policy=CandidateOutcomePolicy(horizon_bars=4))
    from libs.models.trendline_family.optimization.evaluator import build_trial_config

    left = build_trial_config(
        stage=OptimizationStage.CANDIDATE_GEOMETRY, dataset=source, fold_plan=plan, baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"), parameter_overrides={}, evaluation_spec=first.evaluation_spec(),
    )
    right = build_trial_config(
        stage=OptimizationStage.CANDIDATE_GEOMETRY, dataset=source, fold_plan=plan, baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"), parameter_overrides={}, evaluation_spec=second.evaluation_spec(),
    )
    assert left.trial_id != right.trial_id


def test_holdout_requires_frozen_audited_finalist_and_uses_stateful_warmup() -> None:
    source = dataset(rows=64)
    config = resolved_config()
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=2, holdout_bars=8, warmup_bars=4)

    def evaluator(trial, _config, window, kind):
        return window_result(
            trial, window, kind, metric_value=0.7 if trial.parameter_overrides else 0.5,
            stage_fingerprint=str(sorted(trial.parameter_overrides.items())), forbidden_fingerprint="fixed",
        )

    baseline, trials = run_stage_grid(
        stage=OptimizationStage.CANDIDATE_GEOMETRY, dataset=source, fold_plan=plan, baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"), search_space={"candidate.lookback_bars": (180,)},
            evaluator=evaluator, maximum_trial_count=1,
            evaluation_spec=fixture_evaluation_spec("holdout"),
    )
    finalist = select_validation_finalist(baseline=baseline, trials=trials)
    assert finalist is not None
    with pytest.raises(ContractValidationError, match="FinalistFreeze"):
        evaluate_holdout_once(validation_finalist=finalist, baseline_config=config, fold_plan=plan, evaluator=evaluator)
    freeze = freeze_validation_finalist(baseline=baseline, finalist=finalist, fold_plan=plan)
    registry = HoldoutOpenRegistry()
    final_audit = build_holdout_open_audit(finalist_freeze=freeze, fold_plan=plan, result=finalist, target="finalist")
    holdout = evaluate_holdout_once(
        validation_finalist=finalist, baseline_config=config, fold_plan=plan, evaluator=evaluator,
        finalist_freeze=freeze, holdout_open_audit=final_audit, holdout_open_registry=registry,
        evaluation_spec=fixture_evaluation_spec("holdout"),
    )
    assert holdout.window_results[0].fold_id == plan.holdout.holdout_plan_id
    assert evaluate_holdout_once(
        validation_finalist=finalist, baseline_config=config, fold_plan=plan, evaluator=evaluator,
        finalist_freeze=freeze, holdout_open_audit=final_audit, holdout_open_registry=registry,
        evaluation_spec=fixture_evaluation_spec("holdout"),
    ).result_id == holdout.result_id
    with pytest.raises(ContractValidationError, match="non-finalist"):
        baseline_audit = build_holdout_open_audit(finalist_freeze=freeze, fold_plan=plan, result=baseline, target="baseline")
        evaluate_holdout_once(
            validation_finalist=finalist, baseline_config=config, fold_plan=plan, evaluator=evaluator,
            finalist_freeze=freeze, holdout_open_audit=baseline_audit, holdout_open_registry=registry,
            evaluation_spec=fixture_evaluation_spec("holdout"),
        )

    stream = build_frozen_candidate_stream(dataset=source, config=config)
    tracker = TrackerEvaluator(dataset=source, candidate_stream=stream)
    from libs.models.trendline_family.optimization.evaluator import build_trial_config

    tracker_trial = build_trial_config(
        stage=OptimizationStage.TRACKER, dataset=source, fold_plan=plan, baseline_config=config,
        objective=ObjectiveSpec("tracker-v1", "family_continuation_rate"), parameter_overrides={}, evaluation_spec=tracker.evaluation_spec(),
    )
    window = tracker(tracker_trial, config, plan.holdout, "holdout")
    assert window.diagnostics["replay_start_position"] == plan.holdout.warmup.start_position


def test_false_promotion_and_forged_envelope_are_rejected() -> None:
    with pytest.raises(ContractValidationError, match="promote requires"):
        PromotionRecommendation(
            stage=OptimizationStage.CANDIDATE_GEOMETRY,
            baseline_result_id="baseline",
            finalist_result_id=None,
            decision=PromotionDecision.PROMOTE,
            rationale=("forged",),
            validation_evidence={},
            holdout_evidence={},
            parameter_effect_audits=(),
        )
    envelope = ArtifactEnvelope(run_id="run", kind="trial", payload={"value": 1})
    with pytest.raises(ContractValidationError, match="artifact_id"):
        ArtifactEnvelope.from_dict({**envelope.to_dict(), "artifact_id": "forged"})


def test_verified_artifact_bundle_rejects_cross_artifact_run_rewrite(tmp_path) -> None:
    source = dataset(rows=56)
    config = resolved_config()
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=2, holdout_bars=8, warmup_bars=4)

    def evaluator(trial, _config, window, kind):
        return window_result(
            trial, window, kind, metric_value=0.5,
            stage_fingerprint=str(sorted(trial.parameter_overrides.items())), forbidden_fingerprint="fixed",
        )

    result = run_phase_i_evaluation(
        stage=OptimizationStage.CANDIDATE_GEOMETRY, dataset=source, fold_plan=plan, baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"), search_space={"candidate.lookback_bars": (180,)},
        evaluator=evaluator, output_root=tmp_path / "phase_i", maximum_trial_count=1,
        evaluation_spec=fixture_evaluation_spec("artifact-rewrite"),
    )
    manifest_config = result.manifest.resolved_configurations["BTCUSDT:1h"]
    assert manifest_config["resolved_values"] == config.to_dict()
    assert manifest_config["configuration_fingerprint"] == config.configuration_fingerprint
    verify_artifact_bundle(result.artifact_paths)
    target = result.artifact_paths["fold_plan"]
    forged = json.loads(target.read_text(encoding="ascii"))
    forged["run_id"] = "other-run"
    # Recomputing only the envelope ID still leaves cross-artifact provenance false.
    atomic_write_json(target, ArtifactEnvelope(run_id="other-run", kind=forged["kind"], payload=forged["payload"]).to_dict())
    with pytest.raises(ContractValidationError, match="run IDs"):
        verify_artifact_bundle(result.artifact_paths)


def test_run_manifest_identity_binds_full_objective_and_holdout_policy() -> None:
    base = dict(
        requested_stages=(OptimizationStage.CANDIDATE_GEOMETRY,), assets=("BTCUSDT",), timeframes=("1h",),
        dataset_hashes={"BTCUSDT:1h": "dataset"}, fold_plan_ids={"BTCUSDT:1h": "fold"},
        baseline_config_hashes={"BTCUSDT:1h": "config"}, search_spaces={"candidate_geometry": {}},
        objective_versions={"candidate_geometry": "v1"}, seeds={"candidate_geometry": 0}, model_version="model", config_version="config",
    )
    first_objective = ObjectiveSpec("v1", "coverage")
    second_objective = ObjectiveSpec("v1", "quality")
    first = RunManifest(
        **base, objective_specs={"candidate_geometry": first_objective},
        stage_evaluation_specs={"candidate_geometry": CandidateGeometryEvaluator(dataset=dataset(rows=48)).evaluation_spec()},
        maximum_trial_count=2, holdout_policy={"open_holdout": False},
    )
    changed_objective = RunManifest(
        **base, objective_specs={"candidate_geometry": second_objective},
        stage_evaluation_specs={"candidate_geometry": CandidateGeometryEvaluator(dataset=dataset(rows=48)).evaluation_spec()},
        maximum_trial_count=2, holdout_policy={"open_holdout": False},
    )
    changed_holdout = replace(first, holdout_policy={"open_holdout": True}, run_id=None)
    assert len({first.run_id, changed_objective.run_id, changed_holdout.run_id}) == 3


def test_custom_evaluators_require_explicit_distinct_semantic_specs(tmp_path) -> None:
    source = dataset(rows=56)
    config = resolved_config()
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=2, holdout_bars=8, warmup_bars=4)

    def first(trial, _config, window, kind):
        return window_result(trial, window, kind, metric_value=0.7, stage_fingerprint="first", forbidden_fingerprint="fixed")

    def second(trial, _config, window, kind):
        return window_result(trial, window, kind, metric_value=0.9, stage_fingerprint="second", forbidden_fingerprint="fixed")

    with pytest.raises(ContractValidationError, match="evaluation_spec"):
        run_stage_grid(
            stage=OptimizationStage.CANDIDATE_GEOMETRY, dataset=source, fold_plan=plan, baseline_config=config,
            objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"), search_space={"candidate.lookback_bars": (180,)},
            evaluator=first, maximum_trial_count=1,
        )
    first_spec = fixture_evaluation_spec("custom-first")
    second_spec = fixture_evaluation_spec("custom-second")
    first_baseline, _ = run_stage_grid(
        stage=OptimizationStage.CANDIDATE_GEOMETRY, dataset=source, fold_plan=plan, baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"), search_space={"candidate.lookback_bars": (180,)},
        evaluator=first, maximum_trial_count=1, evaluation_spec=first_spec,
    )
    second_baseline, _ = run_stage_grid(
        stage=OptimizationStage.CANDIDATE_GEOMETRY, dataset=source, fold_plan=plan, baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"), search_space={"candidate.lookback_bars": (180,)},
        evaluator=second, maximum_trial_count=1, evaluation_spec=second_spec,
    )
    assert first_baseline.trial.trial_id != second_baseline.trial.trial_id
    with pytest.raises(ContractValidationError, match="do not match trial"):
        run_validation_trial(
            trial=first_baseline.trial,
            config=config,
            fold_plan=plan,
            evaluator=second,
            evaluation_spec=second_spec,
        )
    first_run = run_phase_i_evaluation(
        stage=OptimizationStage.CANDIDATE_GEOMETRY, dataset=source, fold_plan=plan, baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"), search_space={"candidate.lookback_bars": (180,)},
        evaluator=first, output_root=tmp_path / "first", maximum_trial_count=1, evaluation_spec=first_spec,
    )
    second_run = run_phase_i_evaluation(
        stage=OptimizationStage.CANDIDATE_GEOMETRY, dataset=source, fold_plan=plan, baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"), search_space={"candidate.lookback_bars": (180,)},
        evaluator=second, output_root=tmp_path / "second", maximum_trial_count=1, evaluation_spec=second_spec,
    )
    assert first_run.manifest.run_id != second_run.manifest.run_id


def test_holdout_evaluator_substitution_rejects_before_opening() -> None:
    source = dataset(rows=64)
    config = resolved_config()
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=2, holdout_bars=8, warmup_bars=4)
    calls: list[str] = []

    def first(trial, _config, window, kind):
        calls.append(kind)
        return window_result(
            trial, window, kind, metric_value=0.7 if trial.parameter_overrides else 0.5,
            stage_fingerprint=str(sorted(trial.parameter_overrides.items())), forbidden_fingerprint="fixed",
        )

    def substituted(trial, _config, window, kind):
        calls.append("substituted:" + kind)
        return window_result(trial, window, kind, metric_value=0.95, stage_fingerprint="substituted", forbidden_fingerprint="fixed")

    first_spec = fixture_evaluation_spec("holdout-first")
    second_spec = fixture_evaluation_spec("holdout-substituted")
    baseline, trials = run_stage_grid(
        stage=OptimizationStage.CANDIDATE_GEOMETRY, dataset=source, fold_plan=plan, baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"), search_space={"candidate.lookback_bars": (180,)},
        evaluator=first, maximum_trial_count=1, evaluation_spec=first_spec,
    )
    finalist = select_validation_finalist(baseline=baseline, trials=trials)
    assert finalist is not None
    freeze = freeze_validation_finalist(baseline=baseline, finalist=finalist, fold_plan=plan)
    audit = build_holdout_open_audit(finalist_freeze=freeze, fold_plan=plan, result=finalist, target="finalist")
    with pytest.raises(ContractValidationError, match="do not match trial"):
        evaluate_holdout_once(
            validation_finalist=finalist, baseline_config=config, fold_plan=plan, evaluator=substituted,
            finalist_freeze=freeze, holdout_open_audit=audit, holdout_open_registry=HoldoutOpenRegistry(),
            evaluation_spec=second_spec,
        )
    assert not any(item.startswith("substituted:") for item in calls)


def test_completion_index_requires_all_attempted_artifacts_and_order_is_irrelevant(tmp_path) -> None:
    source = dataset(rows=56)
    config = resolved_config()
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=2, holdout_bars=8, warmup_bars=4)

    def evaluator(trial, _config, window, kind):
        return window_result(
            trial, window, kind, metric_value=0.5,
            stage_fingerprint=str(sorted(trial.parameter_overrides.items())), forbidden_fingerprint="fixed",
        )

    result = run_phase_i_evaluation(
        stage=OptimizationStage.CANDIDATE_GEOMETRY, dataset=source, fold_plan=plan, baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"), search_space={"candidate.lookback_bars": (180,)},
        evaluator=evaluator, output_root=tmp_path / "phase_i", maximum_trial_count=1,
        evaluation_spec=fixture_evaluation_spec("completion-index"),
    )
    reversed_paths = dict(reversed(tuple(result.artifact_paths.items())))
    verify_artifact_bundle(reversed_paths)
    missing_primary = dict(result.artifact_paths)
    del missing_primary["trial:" + result.trials[0].trial.trial_id]
    with pytest.raises(ContractValidationError, match="path set"):
        verify_artifact_bundle(missing_primary)
    missing_counter = dict(result.artifact_paths)
    counter_key = next(key for key in missing_counter if key.startswith("counterfactual:"))
    del missing_counter[counter_key]
    with pytest.raises(ContractValidationError, match="path set"):
        verify_artifact_bundle(missing_counter)
    extra = dict(result.artifact_paths)
    extra["trial:unrelated"] = result.artifact_paths["trial:" + result.trials[0].trial.trial_id]
    with pytest.raises(ContractValidationError, match="path set"):
        verify_artifact_bundle(extra)
    invalid = run_phase_i_evaluation(
        stage=OptimizationStage.CANDIDATE_GEOMETRY, dataset=source, fold_plan=plan, baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"), search_space={"candidate.lookback_bars": (0,)},
        evaluator=evaluator, output_root=tmp_path / "invalid", maximum_trial_count=1,
        evaluation_spec=fixture_evaluation_spec("completion-index-invalid"),
    )
    invalid_missing = dict(invalid.artifact_paths)
    del invalid_missing["trial:" + invalid.trials[0].trial.trial_id]
    with pytest.raises(ContractValidationError, match="path set"):
        verify_artifact_bundle(invalid_missing)


def test_objective_gate_rejects_internally_impossible_passing_claim() -> None:
    with pytest.raises(ContractValidationError, match="contradicts"):
        ObjectiveGate(
            objective=ObjectiveSpec("loss-v1", "loss", maximize=False, worst_window_ceiling=1.0),
            required_fold_count=3,
            defined_primary_fold_count=0,
            failed_or_invalid_window_count=3,
            evaluated_row_count=0,
            primary_value=None,
            worst_window_value=99.0,
            latency_ms=None,
            churn_rate=None,
            comparable_population=False,
            passed=True,
        )


def test_verified_bundle_rejects_worse_holdout_promote_even_with_recomputed_index(tmp_path) -> None:
    source = dataset(rows=64)
    config = resolved_config()
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=2, holdout_bars=8, warmup_bars=4)

    def evaluator(trial, _config, window, kind):
        if kind == "holdout":
            value = 0.4 if trial.parameter_overrides else 0.5
        else:
            value = 0.7 if trial.parameter_overrides else 0.5
        return window_result(
            trial, window, kind, metric_value=value,
            stage_fingerprint=str(sorted(trial.parameter_overrides.items())), forbidden_fingerprint="fixed",
        )

    result = run_phase_i_evaluation(
        stage=OptimizationStage.CANDIDATE_GEOMETRY, dataset=source, fold_plan=plan, baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"), search_space={"candidate.lookback_bars": (180,)},
        evaluator=evaluator, output_root=tmp_path / "phase_i", maximum_trial_count=1, open_holdout=True,
        evaluation_spec=fixture_evaluation_spec("worse-holdout"),
    )
    assert result.recommendation.decision is PromotionDecision.REJECT
    forged_recommendation = replace(
        result.recommendation,
        decision=PromotionDecision.PROMOTE,
        rationale=("forged_worse_holdout",),
        promotion_gate_passed=True,
        recommendation_id=None,
    )
    pre_index_manifest = replace(result.manifest, completion_index_id=None, run_id=result.manifest.run_id)
    index = build_completion_artifact_index(
        manifest=pre_index_manifest,
        baseline=result.baseline_validation,
        trials=result.trials,
        recommendation=forged_recommendation,
        baseline_holdout=result.baseline_holdout,
        finalist_holdout=result.finalist_holdout,
        finalist_freeze=result.finalist_freeze,
        holdout_open_audits=result.holdout_open_audits,
    )
    forged_manifest = replace(pre_index_manifest, completion_index_id=index.index_id, run_id=pre_index_manifest.run_id)
    with pytest.raises(ContractValidationError, match="promotion recommendation"):
        VerifiedRunBundle(
            manifest=forged_manifest,
            fold_plan=plan,
            baseline_validation=result.baseline_validation,
            trials=result.trials,
            recommendation=forged_recommendation,
            baseline_holdout=result.baseline_holdout,
            finalist_holdout=result.finalist_holdout,
            finalist_freeze=result.finalist_freeze,
            holdout_open_audits=result.holdout_open_audits,
            completion_index=index,
        )


def test_verified_bundle_rejects_retyped_validation_window_after_identity_recompute(tmp_path) -> None:
    source = dataset(rows=56)
    config = resolved_config()
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=2, holdout_bars=8, warmup_bars=4)

    def evaluator(trial, _config, window, kind):
        return window_result(
            trial, window, kind, metric_value=0.5,
            stage_fingerprint=str(sorted(trial.parameter_overrides.items())), forbidden_fingerprint="fixed",
        )

    result = run_phase_i_evaluation(
        stage=OptimizationStage.CANDIDATE_GEOMETRY, dataset=source, fold_plan=plan, baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"), search_space={"candidate.lookback_bars": (180,)},
        evaluator=evaluator, output_root=tmp_path / "phase_i", maximum_trial_count=1,
        evaluation_spec=fixture_evaluation_spec("retyped-window"),
    )
    original = result.trials[0]
    retyped_window = replace(original.window_results[0], window_kind="holdout", result_id=None)
    retyped_trial = replace(original, window_results=(retyped_window, *original.window_results[1:]), result_id=None)
    pre_index_manifest = replace(result.manifest, completion_index_id=None, run_id=result.manifest.run_id)
    index = build_completion_artifact_index(
        manifest=pre_index_manifest,
        baseline=result.baseline_validation,
        trials=(retyped_trial,),
        recommendation=result.recommendation,
    )
    forged_manifest = replace(pre_index_manifest, completion_index_id=index.index_id, run_id=pre_index_manifest.run_id)
    with pytest.raises(ContractValidationError, match="window kind"):
        VerifiedRunBundle(
            manifest=forged_manifest,
            fold_plan=plan,
            baseline_validation=result.baseline_validation,
            trials=(retyped_trial,),
            recommendation=result.recommendation,
            completion_index=index,
        )


def test_persisted_parameter_effect_audits_are_fully_rederived() -> None:
    source = dataset(rows=64)
    config = resolved_config()
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=2, holdout_bars=8, warmup_bars=4)
    baseline_values = {
        "candidate.lookback_bars": config.candidate.lookback_bars,
        "candidate.min_bars": config.candidate.min_bars,
    }

    def inert(trial, _config, window, kind):
        return window_result(
            trial,
            window,
            kind,
            metric_value=0.5,
            stage_fingerprint="constant-stage",
            forbidden_fingerprint="constant-forbidden",
        )

    _, inert_trials = run_stage_grid(
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        dataset=source,
        fold_plan=plan,
        baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"),
        search_space={"candidate.lookback_bars": (180,)},
        evaluator=inert,
        maximum_trial_count=1,
        evaluation_spec=fixture_evaluation_spec("rederive-inert"),
    )
    inert_trial = inert_trials[0]
    inert_audit = inert_trial.parameter_effect_audits[0]
    with pytest.raises(ContractValidationError, match="effect or leakage"):
        verify_parameter_effect_audits(
            result=replace(
                inert_trial,
                parameter_effect_audits=(
                    replace(
                        inert_audit,
                        effect_detected=True,
                        observed_changed_outputs=("stage_output_fingerprint",),
                        decision=PromotionDecision.PROMOTE,
                    ),
                ),
                result_id=None,
            ),
            baseline_parameter_values={"candidate.lookback_bars": config.candidate.lookback_bars},
        )

    def isolated(trial, _config, window, kind):
        return window_result(
            trial,
            window,
            kind,
            metric_value=0.7 if trial.parameter_overrides else 0.5,
            stage_fingerprint=str(sorted(trial.parameter_overrides.items())),
            forbidden_fingerprint="fixed",
        )

    _, trials = run_stage_grid(
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        dataset=source,
        fold_plan=plan,
        baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"),
        search_space={"candidate.lookback_bars": (180,), "candidate.min_bars": (50,)},
        evaluator=isolated,
        maximum_trial_count=1,
        evaluation_spec=fixture_evaluation_spec("rederive-audits"),
    )
    trial = trials[0]
    by_parameter = {audit.parameter_name: audit for audit in trial.parameter_effect_audits}

    forged_effect = replace(
        by_parameter["candidate.lookback_bars"],
        effect_detected=False,
        observed_changed_outputs=(),
        decision=PromotionDecision.REJECT,
    )
    with pytest.raises(ContractValidationError, match="effect or leakage"):
        verify_parameter_effect_audits(
            result=replace(trial, parameter_effect_audits=(forged_effect, by_parameter["candidate.min_bars"]), result_id=None),
            baseline_parameter_values=baseline_values,
        )

    target_counterfactual = next(
        item for item in trial.counterfactual_results if item.trial.reverted_parameter == "candidate.lookback_bars"
    )
    changed_counterfactual = _retarget_counterfactual(
        target_counterfactual,
        overrides={"candidate.lookback_bars": config.candidate.lookback_bars, "candidate.min_bars": 51},
        reverted_parameter="candidate.lookback_bars",
    )
    changed_audit = replace(
        by_parameter["candidate.lookback_bars"],
        counterfactual_trial_id=changed_counterfactual.trial.trial_id,
        counterfactual_result_id=changed_counterfactual.result_id,
    )
    changed_trial = replace(
        trial,
        parameter_effect_audits=(changed_audit, by_parameter["candidate.min_bars"]),
        counterfactual_results=(
            changed_counterfactual,
            *(item for item in trial.counterfactual_results if item is not target_counterfactual),
        ),
        result_id=None,
    )
    with pytest.raises(ContractValidationError, match="revert exactly one"):
        verify_parameter_effect_audits(result=changed_trial, baseline_parameter_values=baseline_values)

    wrong_baseline_counterfactual = _retarget_counterfactual(
        target_counterfactual,
        overrides={"candidate.lookback_bars": 999, "candidate.min_bars": 50},
        reverted_parameter="candidate.lookback_bars",
    )
    wrong_baseline_audit = replace(
        by_parameter["candidate.lookback_bars"],
        baseline_value=999,
        counterfactual_trial_id=wrong_baseline_counterfactual.trial.trial_id,
        counterfactual_result_id=wrong_baseline_counterfactual.result_id,
    )
    wrong_baseline_trial = replace(
        trial,
        parameter_effect_audits=(wrong_baseline_audit, by_parameter["candidate.min_bars"]),
        counterfactual_results=(
            wrong_baseline_counterfactual,
            *(item for item in trial.counterfactual_results if item is not target_counterfactual),
        ),
        result_id=None,
    )
    with pytest.raises(ContractValidationError, match="baseline value"):
        verify_parameter_effect_audits(result=wrong_baseline_trial, baseline_parameter_values=baseline_values)
    with pytest.raises(ContractValidationError, match="exactly one audit"):
        verify_parameter_effect_audits(
            result=replace(trial, parameter_effect_audits=(), result_id=None),
            baseline_parameter_values=baseline_values,
        )

    inert_counterfactual = inert_trial.counterfactual_results[0]
    extra_counterfactual = _retarget_counterfactual(
        inert_counterfactual,
        overrides={"candidate.lookback_bars": 180, "candidate.min_bars": config.candidate.min_bars},
        reverted_parameter="candidate.min_bars",
    )
    extra_audit = replace(
        inert_audit,
        parameter_name="candidate.min_bars",
        baseline_value=config.candidate.min_bars,
        trial_value=config.candidate.min_bars,
        counterfactual_trial_id=extra_counterfactual.trial.trial_id,
        counterfactual_result_id=extra_counterfactual.result_id,
    )
    with pytest.raises(ContractValidationError, match="exactly one audit"):
        verify_parameter_effect_audits(
            result=replace(
                inert_trial,
                parameter_effect_audits=(inert_audit, extra_audit),
                counterfactual_results=(inert_counterfactual, extra_counterfactual),
                result_id=None,
            ),
            baseline_parameter_values=baseline_values,
        )
    with pytest.raises(ContractValidationError, match="exactly one audit"):
        verify_parameter_effect_audits(
            result=replace(
                trial,
                parameter_effect_audits=(by_parameter["candidate.lookback_bars"],) * 2,
                result_id=None,
            ),
            baseline_parameter_values=baseline_values,
        )

    def leaking(trial, _config, window, kind):
        fingerprint = str(sorted(trial.parameter_overrides.items()))
        return window_result(
            trial,
            window,
            kind,
            metric_value=0.7 if trial.parameter_overrides else 0.5,
            stage_fingerprint=fingerprint,
            forbidden_fingerprint=fingerprint,
        )

    _, leaking_trials = run_stage_grid(
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        dataset=source,
        fold_plan=plan,
        baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"),
        search_space={"candidate.lookback_bars": (180,)},
        evaluator=leaking,
        maximum_trial_count=1,
        evaluation_spec=fixture_evaluation_spec("rederive-leakage"),
    )
    leaking_trial = leaking_trials[0]
    leaking_audit = leaking_trial.parameter_effect_audits[0]
    forged_leakage = replace(leaking_audit, leakage_detected=False, decision=PromotionDecision.PROMOTE)
    with pytest.raises(ContractValidationError, match="effect or leakage"):
        verify_parameter_effect_audits(
            result=replace(leaking_trial, parameter_effect_audits=(forged_leakage,), result_id=None),
            baseline_parameter_values={"candidate.lookback_bars": config.candidate.lookback_bars},
        )


def test_manifest_expected_grid_rejects_missing_extra_and_invalid_primary_trials(tmp_path) -> None:
    source = dataset(rows=64)
    config = resolved_config()
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=2, holdout_bars=8, warmup_bars=4)

    def evaluator(trial, _config, window, kind):
        return window_result(
            trial,
            window,
            kind,
            metric_value=0.7 if trial.parameter_overrides else 0.5,
            stage_fingerprint=str(sorted(trial.parameter_overrides.items())),
            forbidden_fingerprint="fixed",
        )

    result = run_phase_i_evaluation(
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        dataset=source,
        fold_plan=plan,
        baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"),
        search_space={"candidate.lookback_bars": (180, 200)},
        evaluator=evaluator,
        output_root=tmp_path / "complete-grid",
        maximum_trial_count=2,
        evaluation_spec=fixture_evaluation_spec("complete-grid"),
    )
    assert tuple(sorted(trial.trial.trial_id for trial in result.trials)) == result.manifest.expected_primary_trial_ids
    partial_trials = result.trials[:1]
    partial_finalist = select_validation_finalist(baseline=result.baseline_validation, trials=partial_trials)
    partial_recommendation = build_promotion_recommendation(
        baseline_validation=result.baseline_validation,
        finalist_validation=partial_finalist,
        baseline_holdout=None,
        finalist_holdout=None,
        validation_trials=partial_trials,
    )
    manifest = replace(result.manifest, completion_index_id=None, run_id=result.manifest.run_id)
    index = build_completion_artifact_index(
        manifest=manifest,
        baseline=result.baseline_validation,
        trials=partial_trials,
        recommendation=partial_recommendation,
    )
    manifest = replace(manifest, completion_index_id=index.index_id, run_id=manifest.run_id)
    with pytest.raises(ContractValidationError, match="expected request set"):
        VerifiedRunBundle(
            manifest=manifest,
            fold_plan=plan,
            baseline_validation=result.baseline_validation,
            trials=partial_trials,
            recommendation=partial_recommendation,
            completion_index=index,
        )

    _, extra_trials = run_stage_grid(
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        dataset=source,
        fold_plan=plan,
        baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"),
        search_space={"candidate.lookback_bars": (190,)},
        evaluator=evaluator,
        maximum_trial_count=1,
        evaluation_spec=fixture_evaluation_spec("complete-grid"),
    )
    all_trials = (*result.trials, *extra_trials)
    all_finalist = select_validation_finalist(baseline=result.baseline_validation, trials=all_trials)
    all_recommendation = build_promotion_recommendation(
        baseline_validation=result.baseline_validation,
        finalist_validation=all_finalist,
        baseline_holdout=None,
        finalist_holdout=None,
        validation_trials=all_trials,
    )
    extra_index = build_completion_artifact_index(
        manifest=manifest,
        baseline=result.baseline_validation,
        trials=all_trials,
        recommendation=all_recommendation,
    )
    extra_manifest = replace(manifest, completion_index_id=extra_index.index_id, run_id=manifest.run_id)
    with pytest.raises(ContractValidationError, match="expected request set"):
        VerifiedRunBundle(
            manifest=extra_manifest,
            fold_plan=plan,
            baseline_validation=result.baseline_validation,
            trials=all_trials,
            recommendation=all_recommendation,
            completion_index=extra_index,
        )

    invalid = run_phase_i_evaluation(
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        dataset=source,
        fold_plan=plan,
        baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"),
        search_space={"candidate.lookback_bars": (0,)},
        evaluator=evaluator,
        output_root=tmp_path / "invalid-grid",
        maximum_trial_count=1,
        evaluation_spec=fixture_evaluation_spec("invalid-grid"),
    )
    assert invalid.trials[0].status.value == "invalid"
    assert invalid.trials[0].counterfactual_results
    assert invalid.completion_index is not None
    assert invalid.completion_index.primary_trial_results == ((invalid.trials[0].trial.trial_id, invalid.trials[0].result_id),)


def test_finalist_freeze_cannot_substitute_evaluator_or_objective(tmp_path) -> None:
    source = dataset(rows=64)
    config = resolved_config()
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=2, holdout_bars=8, warmup_bars=4)

    def evaluator(trial, _config, window, kind):
        return window_result(
            trial,
            window,
            kind,
            metric_value=0.7 if trial.parameter_overrides else 0.5,
            stage_fingerprint=str(sorted(trial.parameter_overrides.items())),
            forbidden_fingerprint="fixed",
        )

    result = run_phase_i_evaluation(
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        dataset=source,
        fold_plan=plan,
        baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"),
        search_space={"candidate.lookback_bars": (180,)},
        evaluator=evaluator,
        output_root=tmp_path / "freeze",
        maximum_trial_count=1,
        open_holdout=True,
        evaluation_spec=fixture_evaluation_spec("freeze-continuity"),
    )
    assert result.finalist_freeze is not None
    forged_spec = replace(result.finalist_freeze, evaluation_spec_id="forged-evaluator-spec", freeze_id=None)
    with pytest.raises(ContractValidationError, match="evaluator does not match deterministic winner"):
        VerifiedRunBundle(**_rebuild_freeze_bundle(result, fold_plan=plan, finalist_freeze=forged_spec))
    forged_objective = replace(
        result.finalist_freeze,
        objective=ObjectiveSpec("forged-v1", "candidate_count"),
        freeze_id=None,
    )
    with pytest.raises(ContractValidationError, match="objective does not match deterministic winner"):
        VerifiedRunBundle(**_rebuild_freeze_bundle(result, fold_plan=plan, finalist_freeze=forged_objective))
