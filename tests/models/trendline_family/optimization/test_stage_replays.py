from __future__ import annotations

from dataclasses import dataclass

from libs.models.trendline_family.optimization.candidate_optimizer import CandidateGeometryEvaluator
from libs.models.trendline_family.optimization.contracts import ObjectiveSpec, OptimizationStage
from libs.models.trendline_family.optimization.evaluator import build_trial_config
from libs.models.trendline_family.optimization.folds import build_walk_forward_fold_plan
from libs.models.trendline_family.optimization.interaction_optimizer import InteractionEvaluator, build_frozen_family_snapshot_stream
from libs.models.trendline_family.optimization.tracker_optimizer import TrackerEvaluator, build_frozen_candidate_stream
from libs.models.trendline_family.provider import CandidateGenerationResult, CandidateGenerationStatus

from .support import dataset, resolved_config


@dataclass
class AbstainingProvider:
    observed_prefixes: list[int]

    def generate(self, ohlcv, *, observed_at, **_kwargs):
        assert ohlcv.index[-1].to_pydatetime() == observed_at
        self.observed_prefixes.append(len(ohlcv))
        return CandidateGenerationResult(
            status=CandidateGenerationStatus.NO_CONFIRMED_PIVOTS,
            candidates=(),
            reason_codes=("fixture_no_pivots",),
        )


def test_stage_replays_are_causal_and_freeze_their_upstream_inputs() -> None:
    source = dataset(rows=56)
    config = resolved_config()
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=2, holdout_bars=8, warmup_bars=4)

    candidate_provider = AbstainingProvider([])
    candidate_trial = build_trial_config(
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        dataset=source,
        fold_plan=plan,
        baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"),
        parameter_overrides={},
    )
    candidate_window = CandidateGeometryEvaluator(dataset=source, provider=candidate_provider)(
        candidate_trial,
        config,
        plan.folds[0],
        "validation",
    )
    assert max(candidate_provider.observed_prefixes) == plan.folds[0].validation.end_position + 1
    assert any(metric.name == "candidate_coverage_ratio" for metric in candidate_window.metrics)

    stream_provider = AbstainingProvider([])
    candidate_stream = build_frozen_candidate_stream(dataset=source, config=config, provider=stream_provider)
    tracker_trial = build_trial_config(
        stage=OptimizationStage.TRACKER,
        dataset=source,
        fold_plan=plan,
        baseline_config=config,
        objective=ObjectiveSpec("tracker-v1", "family_continuation_rate"),
        parameter_overrides={},
    )
    tracker_window = TrackerEvaluator(dataset=source, candidate_stream=candidate_stream)(
        tracker_trial,
        config,
        plan.folds[0],
        "validation",
    )
    assert tracker_window.diagnostics["forbidden_output_fingerprint"] == candidate_stream.stream_id

    source_snapshots = build_frozen_family_snapshot_stream(
        dataset=source,
        config=config,
        candidate_stream=candidate_stream,
    )
    snapshot_ids_before = tuple(record.snapshot.snapshot_id for record in source_snapshots.records)
    interaction_trial = build_trial_config(
        stage=OptimizationStage.INTERACTION,
        dataset=source,
        fold_plan=plan,
        baseline_config=config,
        objective=ObjectiveSpec("interaction-v1", "break_confirmed_rate"),
        parameter_overrides={},
    )
    interaction_window = InteractionEvaluator(dataset=source, source_snapshots=source_snapshots)(
        interaction_trial,
        config,
        plan.folds[0],
        "validation",
    )
    assert interaction_window.diagnostics["forbidden_output_fingerprint"] == source_snapshots.stream_id
    assert tuple(record.snapshot.snapshot_id for record in source_snapshots.records) == snapshot_ids_before


def test_appended_future_rows_do_not_change_candidate_output_at_prior_window() -> None:
    source = dataset(rows=56)
    extended = dataset(rows=72)
    config = resolved_config()
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=2, holdout_bars=8, warmup_bars=4)
    trial = build_trial_config(
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        dataset=source,
        fold_plan=plan,
        baseline_config=config,
        objective=ObjectiveSpec("candidate-v1", "candidate_coverage_ratio"),
        parameter_overrides={},
    )
    left = CandidateGeometryEvaluator(dataset=source, provider=AbstainingProvider([]))(
        trial,
        config,
        plan.folds[0],
        "validation",
    )
    right = CandidateGeometryEvaluator(dataset=extended, provider=AbstainingProvider([]))(
        trial,
        config,
        plan.folds[0],
        "validation",
    )
    assert left.metrics == right.metrics
    assert left.diagnostics["stage_output_fingerprint"] == right.diagnostics["stage_output_fingerprint"]
