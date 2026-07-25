import pandas as pd

from app.trendlines.contracts import TrendlineFitResult
from app.trendlines.workflows.pipeline import temporal_spec
from app.trendlines.workflows.pipeline import evaluation
from app.trendlines.workflows.pipeline import workflow as pipeline_workflow


def _make_pipeline_frame() -> pd.DataFrame:
    values = [
        9.2, 10.1, 9.4, 11.0, 10.3, 12.0, 11.4, 13.0, 12.4, 13.8,
        13.0, 14.2, 13.5, 14.8, 14.1, 15.2, 14.5, 15.6, 14.9, 16.0,
    ]
    return pd.DataFrame(
        {
            "open": values,
            "high": [value + 0.6 for value in values],
            "low": [value - 0.7 for value in values],
            "close": [value + 0.2 for value in values],
        }
    )


def test_build_pipeline_optimization_spec_tracks_trendline_parameter_stages():
    data_request = pipeline_workflow.build_pipeline_data_request("BTCUSDT", ("1h",), lookback_days=90)
    temporal_split, _ = temporal_spec.resolve_pipeline_temporal_plan(
        240,
        "1h",
        train_bars=60,
        test_bars=20,
    )
    artifact_ref = pipeline_workflow.build_pipeline_artifact_ref("BTCUSDT", "1h", temporal_split)

    spec = temporal_spec.build_pipeline_optimization_spec(
        asset="BTCUSDT",
        timeframe="1h",
        extractor_name="fractal",
        dataset=data_request,
        artifact=artifact_ref,
        temporal_split=temporal_split,
    )

    assert spec.search_space["engine"] == "trendlines"
    assert spec.search_space["fitter_grid_size"] > 0
    assert spec.metadata["parameter_stages"] == ["extractor", "fitter", "lookback"]


def test_run_pipeline_with_params_returns_trendline_fit_result():
    result = evaluation.run_pipeline_with_params(
        _make_pipeline_frame(),
        "BTCUSDT",
        "1h",
        {
            "extractor": {"name": "fractal", "params": {"window_left": 1, "window_right": 1}},
            "fitter": {"name": "pathfinding", "params": {"pivot_window": 1}},
        },
    )

    assert isinstance(result, TrendlineFitResult)
    assert result.metadata["pipeline"]["extractor"] == "fractal"
    assert result.metadata["pipeline"]["fitter"] == "pathfinding"


def test_resolve_trendlines_workflow_config_preserves_boundary_and_signal_params():
    config = temporal_spec.resolve_trendlines_workflow_config(
        {
            "extractor": {"name": "fractal", "params": {"window_left": 1, "window_right": 1}},
            "fitter": {"name": "pathfinding", "params": {"pivot_window": 1}},
            "boundary_params": {"atr_window": 5, "interaction_tolerance_atr": 0.2},
            "signal_params": {"weights": {"structural": 1.2}},
        }
    )

    assert config is not None
    assert config.boundary_params == {"atr_window": 5, "interaction_tolerance_atr": 0.2}
    assert config.signal_params == {"weights": {"structural": 1.2}}


def test_optimize_timeframe_attaches_workflow_metadata(monkeypatch):
    frame = _make_pipeline_frame()

    def fake_search_pipeline_parameters(df, asset, timeframe, extractor_name, manifest, quiet=False):
        del df, manifest, quiet
        return {
            "engine": "trendlines",
            "asset": asset,
            "timeframe": timeframe,
            "best_params": {"lookback_bars": 12},
            "best_fitness": 0.08,
            "best_fitness_std": 0.01,
            "n_windows": 3,
            "window_scores": [0.07, 0.08, 0.09],
            "step_results": {"step1_extractor": {"best": {"params": {"extractor": extractor_name}}}},
        }

    monkeypatch.setattr(evaluation, "search_pipeline_parameters", fake_search_pipeline_parameters)
    monkeypatch.setattr(pipeline_workflow, "search_pipeline_parameters", fake_search_pipeline_parameters)

    result = pipeline_workflow.optimize_timeframe(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        extractor_name="fractal",
        train_bars=10,
        test_bars=4,
        step_bars=4,
        quiet=True,
    )

    assert result["study_status"] == "completed_valid"
    assert result["promotion_result"]["should_promote"] is True
    assert result["dataset_request"]["asset"] == "BTCUSDT"
    assert result["experiment_spec"]["workflow_kind"] == "pipeline_optimization"
    assert result["pipeline_artifact_ref"]["artifact_root"] == "app/trendlines/results"
    assert result["split_manifest_ref"]["label"] == "trendlines_pipeline_split_manifest"