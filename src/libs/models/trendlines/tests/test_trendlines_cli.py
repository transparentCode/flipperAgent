import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from app.trendlines import cli as trendlines_cli
from app.trendlines.data import TrendlineDataRequest, build_dataset_manifest
from app.trendlines.workflows.pipeline import workflow as pipeline_workflow
from app.trendlines.workflows.pipeline import data_fetch
from app.trendlines.workflows.pipeline import config_apply


def _demo_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [1.0, 2.0, 3.0, 4.0],
            "high": [1.5, 2.5, 3.5, 4.5],
            "low": [0.5, 1.5, 2.5, 3.5],
            "close": [1.2, 2.2, 3.2, 4.2],
        }
    )


def test_root_cli_dispatches_pipeline_command(monkeypatch):
    called = {}

    class DummyModule:
        @staticmethod
        def main():
            called["argv"] = list(__import__("sys").argv)
            return 7

    monkeypatch.setattr(trendlines_cli, "_load_command_module", lambda command: DummyModule)

    result = trendlines_cli.main(["pipeline-opt", "--asset", "BTCUSDT", "--quiet"])

    assert result == 7
    assert called["argv"][0] == "pipeline-opt"
    assert "--asset" in called["argv"]


def test_root_cli_dispatches_drift_monitor_command(monkeypatch):
    called = {}

    class DummyModule:
        @staticmethod
        def main():
            called["argv"] = list(__import__("sys").argv)
            return 11

    monkeypatch.setattr(trendlines_cli, "_load_command_module", lambda command: DummyModule)

    result = trendlines_cli.main(["drift-monitor", "--asset", "BTCUSDT", "--quiet"])

    assert result == 11
    assert called["argv"][0] == "drift-monitor"
    assert "--asset" in called["argv"]


def test_run_pipeline_cli_writes_result_payload(monkeypatch, tmp_path: Path):
    frame = _demo_frame()

    def fake_fetch_pipeline_workflow_data(request, connector=None, quiet=False):
        del connector, quiet
        frames = {"1h": frame}
        manifest = build_dataset_manifest(request, frames)
        return frames, manifest

    def fake_resolve_temporal_plan(n_bars, timeframe, step_bars=None):
        del n_bars, timeframe, step_bars
        spec = SimpleNamespace(train_bars=10, test_bars=4, step_bars=4)
        return spec, None

    def fake_optimize_timeframe_fn(df, asset, timeframe, extractor_name, train_bars, test_bars, step_bars, quiet):
        del df, quiet
        return {
            "asset": asset,
            "timeframe": timeframe,
            "extractor": extractor_name,
            "best_fitness": 0.08,
            "best_fitness_std": 0.01,
            "n_windows": 3,
            "study_status": "completed_valid",
            "promotion_result": {"status": "promotion_recommended", "should_promote": True},
            "window_scores": [0.07, 0.08, 0.09],
            "train_bars": train_bars,
            "test_bars": test_bars,
            "step_bars": step_bars,
        }

    monkeypatch.setattr(data_fetch, "fetch_pipeline_workflow_data", fake_fetch_pipeline_workflow_data)

    output_path = tmp_path / "trendlines_cli_output.json"
    args = SimpleNamespace(
        asset="BTCUSDT",
        timeframes="1h",
        lookback=30,
        start_date=None,
        end_date=None,
        train_bars=None,
        test_bars=None,
        step_bars=None,
        extractor="fractal",
        output=str(output_path),
        quiet=True,
    )

    monkeypatch.setattr(pipeline_workflow, "optimize_timeframe", fake_optimize_timeframe_fn)
    monkeypatch.setattr(pipeline_workflow, "resolve_pipeline_temporal_plan", fake_resolve_temporal_plan)
    
    result = pipeline_workflow._run_pipeline_cli(args)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 0
    assert payload["asset"] == "BTCUSDT"
    assert payload["dataset_manifest"]["request"]["asset"] == "BTCUSDT"
    assert payload["results"]["1h"]["best_fitness"] == 0.08
    assert payload["results"]["1h"]["step_bars"] == 4
    assert payload["yaml_snippet"]["BTCUSDT"]["timeframes"]["1h"]["extractor"] == "fractal"


def test_apply_pipeline_optimization_to_config_rejects_unapproved_results(tmp_path: Path):
    yaml_path = tmp_path / "trendlines_pipeline.yaml"
    yaml_path.write_text("trendlines_pipeline:\n  universe:\n    BTCUSDT:\n      timeframes:\n        1h: {}\n")

    try:
        config_apply.apply_pipeline_optimization_to_config(
            "BTCUSDT",
            {
                "1h": {
                    "engine": "trendlines",
                    "best_params": {"lookback_bars": 48},
                    "promotion_result": {"should_promote": False},
                }
            },
            str(yaml_path),
        )
    except ValueError as exc:
        assert "not approved for config apply" in str(exc)
    else:
        raise AssertionError("Expected apply_pipeline_optimization_to_config to reject unapproved results")


def test_apply_pipeline_optimization_to_config_merges_promoted_results(tmp_path: Path):
    yaml_path = tmp_path / "trendlines_pipeline.yaml"
    yaml_path.write_text(
        "trendlines_pipeline:\n"
        "  universe:\n"
        "    BTCUSDT:\n"
        "      timeframes:\n"
        "        1h:\n"
        "          lookback_bars: 24\n"
    )

    config_apply.apply_pipeline_optimization_to_config(
        "BTCUSDT",
        {
            "1h": {
                "engine": "trendlines",
                "best_params": {
                    "lookback_bars": 48,
                    "extractor": {"name": "rdp_zigzag", "params": {"epsilon_atr": 0.2}},
                    "fitter": {"name": "least_squares", "params": {"pivot_window": 2}},
                },
                "promotion_result": {"should_promote": True},
            }
        },
        str(yaml_path),
    )

    import yaml

    loaded = yaml.safe_load(yaml_path.read_text())
    timeframe_block = loaded["trendlines_pipeline"]["universe"]["BTCUSDT"]["timeframes"]["1h"]

    assert timeframe_block["lookback_bars"] == 48
    assert timeframe_block["extractor"]["name"] == "rdp_zigzag"
    assert timeframe_block["fitter"]["name"] == "least_squares"