from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.orchestrator import RegimeV2Orchestrator
from libs.models.trendline_family.optimization.contracts import ObjectiveSpec, OptimizationStage
from libs.models.trendline_family.optimization.folds import build_walk_forward_fold_plan
from libs.models.trendline_family.optimization.runner import run_phase_i_evaluation

from .support import dataset, fixture_evaluation_spec, resolved_config, window_result


def test_phase_i_offline_run_does_not_change_active_regime_v2_output(tmp_path) -> None:
    source = dataset(rows=56)
    active_input = source.to_frame().drop(columns=["complete", "event_label"])
    orchestrator = RegimeV2Orchestrator.create("BTCUSDT", "1h")
    before = orchestrator.analyze_series(active_input)
    config = resolved_config()
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=2, holdout_bars=8, warmup_bars=4)

    def evaluator(trial, _config, window, kind):
        return window_result(trial, window, kind, metric_value=0.5, stage_fingerprint="offline", forbidden_fingerprint=source.dataset_hash)

    run_phase_i_evaluation(
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        dataset=source,
        fold_plan=plan,
        baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"),
        search_space={"candidate.lookback_bars": (180,)},
        evaluator=evaluator,
        output_root=tmp_path / "phase_i",
        maximum_trial_count=1,
        evaluation_spec=fixture_evaluation_spec("shadow-invariance"),
    )
    after = orchestrator.analyze_series(active_input)

    pd.testing.assert_frame_equal(before, after)
