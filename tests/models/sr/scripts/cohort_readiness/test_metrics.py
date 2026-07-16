from __future__ import annotations

from dataclasses import replace
from libs.models.sr.scripts.atr_calibration.candidates import replay_candidate
from libs.models.sr.scripts.atr_calibration.config import load_calibration_config
from libs.models.sr.scripts.atr_calibration.contracts import CapsuleStage
from libs.models.sr.scripts.atr_calibration.metrics import compute_candidate_metrics
from libs.models.sr.scripts.atr_calibration.source import load_capsule
from libs.models.sr.scripts.baseline_trial.config import load_resolved_sr_config
from libs.models.sr.scripts.cohort_readiness.metrics import replay_asset
from libs.models.sr.scripts.cohort_readiness.metrics import aggregate, readiness_gates


def test_taousdt_atr14_metrics_match_v16_exactly(cohort_config, resolved_configs, tao_source, repo_root):
    v16 = load_calibration_config(repo_root / "configs/sr_trials/taousdt_1d_atr_calibration.yaml")
    v16_capsule = load_capsule(
        repo_root / cohort_config.tao_source_path,
        expected_stage=CapsuleStage.DEVELOPMENT,
        expected_source=v16,
        expected_implementation_commit=cohort_config.tao_source_implementation_commit,
    )
    v16_sr = load_resolved_sr_config(repo_root / cohort_config.sr_config_path, asset="TAOUSDT", timeframe="1d")
    old_replay = replay_candidate(v16_capsule, 14, config=v16, resolved_config=v16_sr)
    old_metrics = compute_candidate_metrics(old_replay, v16_capsule, config=v16)
    sr_configs, _, _ = resolved_configs
    new_evaluation = replay_asset(cohort_config, tao_source, sr_configs["TAOUSDT"], implementation_commit="a" * 40)
    assert new_evaluation.metrics.to_payload() == old_metrics.to_payload()
    assert new_evaluation.replay.trace.trace_id == old_replay.trace.trace_id


def _four_asset_evaluations(cohort_config, resolved_configs, tao_source):
    sr_configs, _, _ = resolved_configs
    base = replay_asset(cohort_config, tao_source, sr_configs["TAOUSDT"], implementation_commit="a" * 40)
    return tuple(replace(base, asset=asset) for asset in cohort_config.assets)


def _with_completed_outcomes(window, count):
    outcomes = tuple(outcome for outcome in window.outcomes if outcome.completed)[:count]
    invalidated = sum(outcome.invalidated for outcome in outcomes)
    support = sum(outcome.side.value == "support" for outcome in outcomes)
    return replace(
        window,
        total_first_touch_outcomes=count,
        completed_first_touch_outcomes=count,
        right_censored_first_touch_outcomes=0,
        right_censoring_rate=0.0,
        support_completed_count=support,
        resistance_completed_count=count - support,
        invalidated_completed_outcomes=invalidated,
        invalidation_rate=None if not outcomes else invalidated / len(outcomes),
        outcomes=outcomes,
    )


def test_micro_and_macro_aggregation_use_outcome_level_rows(cohort_config, resolved_configs, tao_source):
    evaluations = _four_asset_evaluations(cohort_config, resolved_configs, tao_source)
    micro, macro = aggregate(evaluations)
    expected_completed = sum(item.metrics.pooled.completed_first_touch_outcomes for item in evaluations)
    expected_total = sum(item.metrics.pooled.total_first_touch_outcomes for item in evaluations)
    assert micro.completed_first_touch_outcomes == expected_completed
    assert micro.total_first_touch_outcomes == expected_total
    quality = macro.to_payload()["median_quality_reference_atr"]
    assert quality["minimum"] <= quality["median"] <= quality["maximum"]


def test_readiness_disposition_order_records_structural_anomaly_first(cohort_config, resolved_configs, tao_source):
    evaluations = _four_asset_evaluations(cohort_config, resolved_configs, tao_source)
    zero = evaluations[1].metrics.pooled
    zero = replace(
        zero,
        total_first_touch_outcomes=0,
        completed_first_touch_outcomes=0,
        right_censored_first_touch_outcomes=0,
        support_completed_count=0,
        resistance_completed_count=0,
        invalidated_completed_outcomes=0,
        created_zone_count=0,
        cohort_terminal_count=0,
        outcomes=(),
    )
    broken = replace(evaluations[1], metrics=replace(evaluations[1].metrics, pooled=zero))
    gates, disposition = readiness_gates(cohort_config, (evaluations[0], broken, evaluations[2], evaluations[3]))
    assert disposition.value == "STRUCTURAL_ANOMALY"
    assert sum(not gate.passed for gate in gates if gate.asset == evaluations[1].asset and gate.name.startswith("structural.")) >= 3


def test_readiness_returns_insufficient_evidence_when_only_sample_gate_fails(cohort_config, resolved_configs, tao_source):
    evaluations = list(_four_asset_evaluations(cohort_config, resolved_configs, tao_source))
    failed_folds = tuple(replace(fold, total_first_touch_outcomes=0, completed_first_touch_outcomes=0, right_censored_first_touch_outcomes=0, support_completed_count=0, resistance_completed_count=0, invalidated_completed_outcomes=0, outcomes=()) for fold in evaluations[0].metrics.folds)
    evaluations[0] = replace(evaluations[0], metrics=replace(evaluations[0].metrics, folds=failed_folds))
    gates, disposition = readiness_gates(cohort_config, tuple(evaluations))
    assert disposition.value == "INSUFFICIENT_EVIDENCE"
    assert any(not gate.passed and gate.name == "sample.eligible_development_folds" for gate in gates)


def test_four_eligible_folds_and_at_least_24_outcomes_are_ready(cohort_config, resolved_configs, tao_source):
    evaluations = list(_four_asset_evaluations(cohort_config, resolved_configs, tao_source))
    folds = tuple(
        _with_completed_outcomes(fold, 3) if fold.name == "2025_q1" else fold
        for fold in evaluations[0].metrics.folds
    )
    evaluations[0] = replace(evaluations[0], metrics=replace(evaluations[0].metrics, folds=folds))
    gates, disposition = readiness_gates(cohort_config, tuple(evaluations))
    assert disposition.value == "READY_FOR_PARAMETER_SENSITIVITY"
    eligible = next(
        gate for gate in gates
        if gate.asset == "TAOUSDT" and gate.name == "sample.eligible_development_folds"
    )
    assert eligible.value == 4
    assert any(
        not gate.passed and gate.name == "sample.completed_first_touches_per_fold"
        for gate in gates if gate.asset == "TAOUSDT"
    )


def test_three_eligible_folds_are_insufficient_even_when_total_outcomes_pass(cohort_config, resolved_configs, tao_source):
    evaluations = list(_four_asset_evaluations(cohort_config, resolved_configs, tao_source))
    failed = {"2025_q1", "2025_q2"}
    folds = tuple(
        _with_completed_outcomes(fold, 3) if fold.name in failed else fold
        for fold in evaluations[0].metrics.folds
    )
    evaluations[0] = replace(evaluations[0], metrics=replace(evaluations[0].metrics, folds=folds))
    gates, disposition = readiness_gates(cohort_config, tuple(evaluations))
    assert disposition.value == "INSUFFICIENT_EVIDENCE"
    eligible = next(
        gate for gate in gates
        if gate.asset == "TAOUSDT" and gate.name == "sample.eligible_development_folds"
    )
    total = next(
        gate for gate in gates
        if gate.asset == "TAOUSDT" and gate.name == "sample.development_completed_first_touches"
    )
    assert eligible.value == 3
    assert total.passed


def test_four_eligible_folds_but_fewer_than_24_outcomes_are_insufficient(cohort_config, resolved_configs, tao_source):
    evaluations = list(_four_asset_evaluations(cohort_config, resolved_configs, tao_source))
    folds = tuple(
        _with_completed_outcomes(fold, 3) if fold.name == "2025_q1" else fold
        for fold in evaluations[0].metrics.folds
    )
    pooled = _with_completed_outcomes(evaluations[0].metrics.pooled, 20)
    evaluations[0] = replace(
        evaluations[0],
        metrics=replace(evaluations[0].metrics, folds=folds, pooled=pooled),
    )
    gates, disposition = readiness_gates(cohort_config, tuple(evaluations))
    assert disposition.value == "INSUFFICIENT_EVIDENCE"
    eligible = next(
        gate for gate in gates
        if gate.asset == "TAOUSDT" and gate.name == "sample.eligible_development_folds"
    )
    total = next(
        gate for gate in gates
        if gate.asset == "TAOUSDT" and gate.name == "sample.development_completed_first_touches"
    )
    assert eligible.value == 4
    assert not total.passed
