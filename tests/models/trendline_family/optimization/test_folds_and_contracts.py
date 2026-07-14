from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from libs.models.trendline_family.contracts import ContractValidationError
from libs.models.trendline_family.optimization.contracts import MetricRecord, ObjectiveSpec, OptimizationStage, TrialConfig, TrialResult, TrialStatus
from libs.models.trendline_family.optimization.folds import build_walk_forward_fold_plan, hash_historical_frame

from .support import dataset, market_frame, resolved_config, window_result


def test_dataset_hash_and_fold_plan_are_deterministic_and_holdout_is_untouched() -> None:
    source = dataset(rows=72)
    plan = build_walk_forward_fold_plan(
        source,
        initial_train_bars=18,
        validation_bars=8,
        fold_count=3,
        holdout_bars=8,
        warmup_bars=6,
        purge_bars=2,
        embargo_bars=1,
        label_horizon_bars=2,
    )

    assert plan.fold_plan_id == build_walk_forward_fold_plan(
        source,
        initial_train_bars=18,
        validation_bars=8,
        fold_count=3,
        holdout_bars=8,
        warmup_bars=6,
        purge_bars=2,
        embargo_bars=1,
        label_horizon_bars=2,
    ).fold_plan_id
    assert plan.holdout.window.start_position > plan.folds[-1].validation.end_position + plan.folds[-1].embargo_bars
    assert plan.holdout.selected_after_fold_plan_id == plan.fold_plan_id
    assert all(fold.validation.start_position - fold.train.end_position - 1 >= 2 for fold in plan.folds)


def test_dataset_validation_rejects_duplicate_incomplete_and_changed_bars() -> None:
    frame = market_frame(rows=20)
    duplicate = pd.concat([frame, frame.iloc[[0]]]).sort_index()
    with pytest.raises(ContractValidationError, match="strictly ordered"):
        hash_historical_frame(duplicate, asset="BTCUSDT", timeframe="1h")

    incomplete = frame.copy()
    incomplete.loc[incomplete.index[-1], "complete"] = False
    with pytest.raises(ContractValidationError, match="incomplete"):
        hash_historical_frame(incomplete, asset="BTCUSDT", timeframe="1h")

    changed = frame.copy()
    changed.loc[changed.index[-1], "close"] += 0.1
    assert hash_historical_frame(frame, asset="BTCUSDT", timeframe="1h") != hash_historical_frame(changed, asset="BTCUSDT", timeframe="1h")


def test_trial_and_result_ids_bind_complete_semantics() -> None:
    source = dataset(rows=48)
    config = resolved_config()
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=6, fold_count=2, holdout_bars=6, warmup_bars=4)
    trial = TrialConfig(
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        asset=source.asset,
        timeframe=source.timeframe,
        parameter_overrides={"candidate.lookback_bars": 80},
        baseline_config_hash=config.resolved_config_hash,
        dataset_hash=source.dataset_hash,
        fold_plan_id=plan.fold_plan_id,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"),
        model_version=config.model_version,
        config_version=config.config_version,
    )
    window = window_result(trial, plan.folds[0], "validation", metric_value=0.5, stage_fingerprint="a", forbidden_fingerprint="same")
    result = TrialResult(trial=trial, status=TrialStatus.COMPLETED, window_results=(window,), aggregate_metrics={"candidate_coverage_ratio": window.metrics[0]})

    changed_metric = replace(
        window,
        metrics=(MetricRecord("candidate_coverage_ratio", value=0.6, sample_count=10, valid_row_count=10),),
        result_id=None,
    )
    changed_result = TrialResult(trial=trial, status=TrialStatus.COMPLETED, window_results=(changed_metric,), aggregate_metrics={"candidate_coverage_ratio": changed_metric.metrics[0]})
    assert result.result_id != changed_result.result_id
    assert result.result_id == TrialResult(
        trial=trial,
        status=TrialStatus.COMPLETED,
        window_results=(window,),
        aggregate_metrics={"candidate_coverage_ratio": window.metrics[0]},
        runtime_diagnostics={"runtime_seconds": 99.0},
    ).result_id
    with pytest.raises(ContractValidationError, match="trial_id"):
        replace(trial, trial_id="forged")
