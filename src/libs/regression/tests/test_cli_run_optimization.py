"""Tests for regression optimization CLI: run_optimization.py."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from app.regression.optimization.models import (
    RegressionBenchmarkResults,
    RegressionOptimizationConfig,
    RegressionOptimizationResult,
)
from app.regression.scripts.run_optimization import (
    StatusFileWriter,
    auto_output_path,
    build_config,
    build_resolver,
    make_status_callback,
    parse_args,
    print_results,
)


# ---------------------------------------------------------------------------
# parse_args
# ---------------------------------------------------------------------------

class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])
        assert args.asset == "BTCUSDT"
        assert args.timeframe == "1h"
        assert args.n_trials is None
        assert args.timeout is None
        assert args.lookback == 90
        assert args.config is None
        assert args.output is None
        assert args.start_date is None
        assert args.end_date is None
        assert args.quiet is False
        assert args.no_trial_history is False
        assert args.log_interval == 10

    def test_custom_flags(self):
        args = parse_args([
            "-a", "ETHUSDT",
            "-t", "4h",
            "--n-trials", "200",
            "--timeout", "7200",
            "--lookback", "180",
            "--log-interval", "5",
            "--quiet",
            "--no-trial-history",
        ])
        assert args.asset == "ETHUSDT"
        assert args.timeframe == "4h"
        assert args.n_trials == 200
        assert args.timeout == 7200
        assert args.lookback == 180
        assert args.log_interval == 5
        assert args.quiet is True
        assert args.no_trial_history is True

    def test_date_range_flags(self):
        args = parse_args([
            "--start-date", "2022-01-01",
            "--end-date", "2026-03-01",
        ])
        assert args.start_date == "2022-01-01"
        assert args.end_date == "2026-03-01"

    def test_start_date_without_end(self):
        args = parse_args(["--start-date", "2023-06-01"])
        assert args.start_date == "2023-06-01"
        assert args.end_date is None

    def test_config_path(self):
        args = parse_args(["--config", "config/regression.yaml"])
        assert args.config == "config/regression.yaml"

    def test_output_path(self):
        args = parse_args(["--output", "/tmp/out.json"])
        assert args.output == "/tmp/out.json"

    def test_invalid_arg_exits(self):
        with pytest.raises(SystemExit):
            parse_args(["--nonexistent-flag"])


# ---------------------------------------------------------------------------
# build_config
# ---------------------------------------------------------------------------

class TestBuildConfig:
    def test_from_defaults(self):
        args = parse_args([])
        config = build_config(args)
        assert isinstance(config, RegressionOptimizationConfig)
        assert config.n_trials == 200  # V2 default from constants
        assert config.timeout_seconds == 3600
        assert config.n_jobs == 1

    def test_from_custom(self):
        args = parse_args(["--n-trials", "50", "--timeout", "1800"])
        config = build_config(args)
        assert config.n_trials == 50
        assert config.timeout_seconds == 1800


# ---------------------------------------------------------------------------
# build_resolver
# ---------------------------------------------------------------------------

class TestBuildResolver:
    def test_default_yaml_loads(self):
        """When --config not provided, resolver uses default regression.yaml."""
        resolver = build_resolver(None)
        assert resolver is not None

    def test_explicit_yaml_loads(self):
        resolver = build_resolver("app/regression/config/regression.yaml")
        assert resolver is not None

    def test_missing_yaml_raises(self):
        with pytest.raises(Exception):
            build_resolver("/nonexistent/path.yaml")


# ---------------------------------------------------------------------------
# auto_output_path
# ---------------------------------------------------------------------------

class TestAutoOutputPath:
    def test_format(self):
        path = auto_output_path("BTCUSDT", "1h")
        assert "BTCUSDT_1h_" in path
        assert path.endswith(".json")
        # Must be under results dir
        assert "optimization/results" in path

    def test_different_assets(self):
        p1 = auto_output_path("BTCUSDT", "1h")
        p2 = auto_output_path("ETHUSDT", "4h")
        assert "BTCUSDT_1h" in p1
        assert "ETHUSDT_4h" in p2


# ---------------------------------------------------------------------------
# print_results
# ---------------------------------------------------------------------------

def _make_mock_result(**overrides):
    defaults = dict(
        asset="BTCUSDT",
        timeframe="1h",
        best_params={"window_size": 120, "band_multiplier": 2.5},
        best_objective_values=(0.62, 0.85, 0.35),
        best_benchmarks=RegressionBenchmarkResults(
            weighted_direction_score=0.62,
            band_coverage_pct=0.853,
            band_width_stability=0.45,
            durbin_watson=1.8,
            passed_residual_gate=True,
            confidence_return_spearman=0.12,
            passed_confidence_constraint=True,
            confidence_sharpe=0.35,
            sharpe_improvement=0.18,
        ),
        pareto_candidates=[],
        n_trials_passed_gate=80,
        n_trials_total=100,
        total_time_seconds=1200.0,
        config=RegressionOptimizationConfig(),
        all_trials=[],
        timestamp=datetime(2026, 4, 14, 12, 0, 0),
    )
    defaults.update(overrides)
    return RegressionOptimizationResult(**defaults)


class TestPrintResults:
    def test_quiet_suppresses(self, capsys):
        result = _make_mock_result()
        print_results(result, quiet=True)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_output_contains_key_fields(self, capsys):
        result = _make_mock_result()
        print_results(result, quiet=False)
        out = capsys.readouterr().out
        assert "BTCUSDT" in out
        assert "1h" in out
        assert "0.62" in out  # first objective value
        assert "80/100" in out
        assert "window_size" in out
        assert "band_multiplier" in out
        assert "Direction Accuracy" in out
        assert "Durbin-Watson" in out
        assert "PASS" in out

    def test_zero_trials(self, capsys):
        result = _make_mock_result(n_trials_total=0, n_trials_passed_gate=0)
        print_results(result, quiet=False)
        out = capsys.readouterr().out
        assert "0/0" in out


# ---------------------------------------------------------------------------
# help flag
# ---------------------------------------------------------------------------

class TestHelpExits:
    def test_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc_info:
            parse_args(["--help"])
        assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# StatusFileWriter + make_status_callback
# ---------------------------------------------------------------------------

class TestStatusFileWriter:
    def test_creates_status_file(self, tmp_path):
        writer = StatusFileWriter(tmp_path, "BTCUSDT", "1h", 100)
        assert writer.status_path.exists()
        with open(writer.status_path) as f:
            data = json.load(f)
        assert data["asset"] == "BTCUSDT"
        assert data["status"] == "starting"
        assert data["pid"] == os.getpid()

    def test_update_writes_running(self, tmp_path):
        writer = StatusFileWriter(tmp_path, "ETH", "4h", 50)
        writer.update(
            trial_current=10,
            best_objective_values=[0.6, 0.8, 0.3],
            best_params={"window_size": 120},
            n_passed_gate=3,
            n_pruned=2,
        )
        with open(writer.status_path) as f:
            data = json.load(f)
        assert data["status"] == "running"
        assert data["trial_current"] == 10
        assert data["best_objective_values"] == [0.6, 0.8, 0.3]
        assert data["n_trials_pruned"] == 2

    def test_complete_writes_completed(self, tmp_path):
        writer = StatusFileWriter(tmp_path, "BTC", "1h", 100)
        result = _make_mock_result()
        writer.complete(result)
        with open(writer.status_path) as f:
            data = json.load(f)
        assert data["status"] == "completed"
        assert data["best_objective_values"] == [0.62, 0.85, 0.35]

    def test_fail_writes_failed(self, tmp_path):
        writer = StatusFileWriter(tmp_path, "BTC", "1h", 100)
        writer.fail("something broke")
        with open(writer.status_path) as f:
            data = json.load(f)
        assert data["status"] == "failed"
        assert data["error"] == "something broke"

    def test_removes_stale_file(self, tmp_path):
        # Create a stale file
        stale = tmp_path / ".optimization_status.json"
        stale.write_text('{"status":"old"}')
        writer = StatusFileWriter(tmp_path, "X", "1h", 10)
        with open(writer.status_path) as f:
            data = json.load(f)
        assert data["status"] == "starting"  # stale overwritten


class TestMakeStatusCallback:
    def test_callback_updates_writer(self, tmp_path):
        writer = StatusFileWriter(tmp_path, "BTC", "1h", 100)

        cb = make_status_callback(writer, 100)
        assert cb is not None

        # V2 multi-objective: study.best_trials returns Pareto front
        best_trial_mock = MagicMock()
        best_trial_mock.values = [0.55, 0.80, 0.30]
        best_trial_mock.params = {"window_size": 120}

        study = MagicMock()
        study.best_trials = [best_trial_mock]
        trial = MagicMock()
        trial.number = 9  # trial 10
        trial.state.name = "COMPLETE"
        trial.user_attrs = {"passed_gate": True}
        study.trials = [trial]

        cb(study, trial)

        with open(writer.status_path) as f:
            data = json.load(f)
        assert data["status"] == "running"
        assert data["trial_current"] == 10
        assert data["best_objective_values"] == [0.55, 0.80, 0.30]

    def test_returns_none_when_no_writer(self):
        assert make_status_callback(None, 100) is None
