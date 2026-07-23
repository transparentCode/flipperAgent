from __future__ import annotations

import json
from pathlib import Path

import pytest

from libs.models.trendline_family import MTFNormalizationContext, compose_trendline_family_mtf
from libs.models.trendline_family.config_resolver import TrendlineFamilyConfigResolver
from libs.models.trendline_family.contracts import ContractValidationError
from libs.models.trendline_family.optimization.contracts import ObjectiveSpec, OptimizationStage
from libs.models.trendline_family.optimization.folds import build_walk_forward_fold_plan
from libs.models.trendline_family.optimization.runner import run_phase_i_evaluation
from libs.models.trendline_family.research_lab import (
    artifact_trial_rows,
    build_smoke_config,
    build_smoke_ohlcv,
    dataset_summary,
    export_research_artifacts,
    immutable_research_frame,
    load_verified_phase_i_artifacts,
    run_canonical_replay,
)
from ..tracker_support import SequenceProvider, abstention


def _phase_i_run(tmp_path: Path):
    dataset = immutable_research_frame(frame=build_smoke_ohlcv(rows=56), asset="BTCUSDT", timeframe="1h")
    config = build_smoke_config()
    plan = build_walk_forward_fold_plan(
        dataset,
        initial_train_bars=18,
        validation_bars=8,
        fold_count=2,
        holdout_bars=8,
        warmup_bars=4,
    )

    def evaluator(trial, _config, window, kind):
        from libs.models.trendline_family.optimization.contracts import MetricRecord, WindowResult

        return WindowResult(
            trial_id=trial.trial_id,
            fold_id=window.fold_id if kind == "validation" else window.holdout_plan_id,
            window_kind=kind,
            metrics=(MetricRecord("candidate_coverage_ratio", 0.7 if trial.parameter_overrides else 0.5, sample_count=8, valid_row_count=8),),
            evaluated_bar_count=8,
            diagnostics={"stage_output_fingerprint": str(sorted(trial.parameter_overrides.items())), "forbidden_output_fingerprint": "fixed"},
        )

    from libs.models.trendline_family.optimization.contracts import StageEvaluationSpec

    return run_phase_i_evaluation(
        stage=OptimizationStage.CANDIDATE_GEOMETRY,
        dataset=dataset,
        fold_plan=plan,
        baseline_config=config,
        objective=ObjectiveSpec("research-fixture-v1", "candidate_coverage_ratio"),
        search_space={"candidate.lookback_bars": (40,)},
        evaluator=evaluator,
        output_root=tmp_path / "phase_i",
        maximum_trial_count=1,
        evaluation_spec=StageEvaluationSpec(
            stage=OptimizationStage.CANDIDATE_GEOMETRY,
            spec_type="research_lab_fixture",
            semantic_inputs={"version": "v1"},
        ),
    )


def test_artifact_browser_verifies_validation_rows_before_display(tmp_path: Path) -> None:
    result = _phase_i_run(tmp_path)
    browser = load_verified_phase_i_artifacts(tmp_path / "phase_i")
    rows = artifact_trial_rows(browser.trials)
    assert browser.manifest.run_id == result.manifest.run_id
    assert rows and all(row.validation_only for row in rows)
    stage = OptimizationStage.CANDIDATE_GEOMETRY.value
    metric = "candidate_coverage_ratio"
    assert browser.manifest.objective_specs[stage].primary_metric == metric
    assert all(row.stage == stage and row.primary_metric_name == metric for row in rows)
    assert all(
        row.validation_only
        and row.per_window_metrics
        and all(window.get("window_kind") == "validation" for window in row.per_window_metrics)
        for row in rows
    )
    assert all(row.primary_metric_value is not None for row in rows)
    assert browser.recommendation.finalist_holdout_result_id is None
    result.artifact_paths["trial:" + result.trials[0].trial.trial_id].unlink()
    with pytest.raises(ContractValidationError, match="incomplete"):
        load_verified_phase_i_artifacts(tmp_path / "phase_i")


def test_export_is_semantic_deterministic_and_does_not_touch_runtime_yaml(tmp_path: Path) -> None:
    config_path = Path("configs/trendline_family.yaml")
    before = config_path.read_bytes()
    dataset = immutable_research_frame(frame=build_smoke_ohlcv(), asset="BTCUSDT", timeframe="1h")
    replay = run_canonical_replay(dataset=dataset, config=build_smoke_config())
    first = export_research_artifacts(
        output_root=tmp_path,
        replay=replay,
        selected_position=dataset.row_count - 1,
        tables={"empty": ()},
    )
    second = export_research_artifacts(
        output_root=tmp_path,
        replay=replay,
        selected_position=dataset.row_count - 1,
        tables={"empty": ()},
    )
    assert first == second
    assert config_path.read_bytes() == before


def test_replay_and_export_identity_bind_provider_and_selected_evidence(tmp_path: Path) -> None:
    dataset = immutable_research_frame(frame=build_smoke_ohlcv(), asset="BTCUSDT", timeframe="1h")
    config = build_smoke_config()
    native = run_canonical_replay(dataset=dataset, config=config)
    empty = run_canonical_replay(
        dataset=dataset,
        config=config,
        provider=SequenceProvider(tuple(abstention() for _ in range(dataset.row_count))),
        provider_spec={"provider": "test_empty_v1", "fixture": "no_candidates"},
    )
    assert native.context.research_run_id != empty.context.research_run_id

    first = export_research_artifacts(
        output_root=tmp_path,
        replay=native,
        selected_position=20,
        tables={"one": ()},
    )
    second = export_research_artifacts(
        output_root=tmp_path,
        replay=native,
        selected_position=dataset.row_count - 1,
        tables={"one": ()},
    )
    changed_tables = export_research_artifacts(
        output_root=tmp_path,
        replay=native,
        selected_position=dataset.row_count - 1,
        tables={"changed": ({"id": "evidence"},)},
    )
    assert first["export_manifest"].parent != second["export_manifest"].parent
    assert second["export_manifest"].parent != changed_tables["export_manifest"].parent

    forged_summary = {**dataset_summary(dataset), "dataset_hash": "forged", "row_count": 999}
    with pytest.raises(ContractValidationError, match="dataset summary does not match"):
        export_research_artifacts(
            output_root=tmp_path,
            replay=native,
            selected_position=0,
            tables={"empty": ()},
            dataset_summary_payload=forged_summary,
        )


def test_export_binds_distinct_replay_and_mtf_config_identities(tmp_path: Path) -> None:
    dataset = immutable_research_frame(frame=build_smoke_ohlcv(), asset="BTCUSDT", timeframe="1h")
    replay = run_canonical_replay(dataset=dataset, config=build_smoke_config())
    mtf_config = TrendlineFamilyConfigResolver(
        {
            "version": "research-mtf-export-v1",
            "defaults": {
                "mtf": {
                    "enabled": True,
                    "source_timeframes": ["1h", "4h"],
                    "minimum_confluence_timeframes": 2,
                    "max_source_age_bars": 4.0,
                    "stale_include_age_bars": 1.0,
                    "max_level_distance_atr": 1.0,
                    "max_corridor_separation_atr": 1.0,
                    "max_slope_delta_atr_per_hour": 1.0,
                    "intersection_horizon_bars": 24,
                    "normalization_policy": "decision_timeframe_atr",
                }
            },
        }
    ).resolve(asset="BTCUSDT", timeframe="1h")
    selected_position = dataset.row_count - 1
    selected = replay.output_at(selected_position).snapshot
    mtf_snapshot = compose_trendline_family_mtf(
        source_snapshots={"1h": selected},
        decision_timestamp=selected.timestamp,
        normalization_context=MTFNormalizationContext(
            asset="BTCUSDT",
            decision_timeframe="1h",
            atr=2.0,
            decision_price=float(dataset.to_frame().iloc[-1]["close"]),
        ),
        config=mtf_config,
    )
    paths = export_research_artifacts(
        output_root=tmp_path,
        replay=replay,
        selected_position=selected_position,
        tables={"empty": ()},
        mtf_snapshot=mtf_snapshot,
    )
    manifest = json.loads(paths["export_manifest"].read_text(encoding="utf-8"))
    assert manifest["replay_config_version"] == replay.context.config_version
    assert manifest["replay_resolved_config_hash"] == replay.context.resolved_config_hash
    assert manifest["replay_mtf_config_hash"] == replay.context.mtf_config_hash
    assert manifest["mtf_config_version"] == mtf_snapshot.config_version
    assert manifest["mtf_config_hash"] == mtf_snapshot.policy_audit.mtf_config_hash
    assert manifest["mtf_snapshot_id"] == mtf_snapshot.mtf_snapshot_id
    assert paths["mtf_snapshot"].is_file()


def test_runtime_modules_do_not_import_research_lab() -> None:
    source_root = Path("src")
    runtime_python = tuple(source_root.glob("apps/**/*.py")) + tuple(source_root.glob("libs/models/trendline_family/*.py"))
    offenders = [path for path in runtime_python if "research_lab" in path.read_text(encoding="utf-8")]
    assert offenders == []


def test_research_support_has_no_legacy_trendline_imports() -> None:
    support_files = tuple(Path("src/libs/models/trendline_family/research_lab").glob("*.py"))
    forbidden = ("libs.trendlines", "libs.models.trendlines_old", "app.trendlines")
    assert all(not any(value in path.read_text(encoding="utf-8") for value in forbidden) for path in support_files)
