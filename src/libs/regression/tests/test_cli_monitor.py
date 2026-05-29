"""Tests for regression optimization CLI: monitor_optimization.py."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from app.regression.optimization.models import (
    RegressionBenchmarkResults,
    RegressionOptimizationConfig,
    RegressionOptimizationResult,
)
from app.regression.scripts.monitor_optimization import (
    cmd_compare,
    cmd_list,
    cmd_show,
    parse_args,
)


def _make_result_json(
    asset="BTCUSDT",
    timeframe="1h",
    best_objective_values=None,
    n_trials=50,
    gate_passed=40,
) -> dict:
    """Create a minimal V2 result JSON dict."""
    if best_objective_values is None:
        best_objective_values = [0.6, 0.85, 0.3]
    return {
        "asset": asset,
        "timeframe": timeframe,
        "best_params": {"window_size": 120, "band_multiplier": 2.5},
        "best_objective_values": best_objective_values,
        "best_benchmarks": RegressionBenchmarkResults(
            weighted_direction_score=0.6,
            band_coverage_pct=0.85,
            band_width_stability=0.4,
            durbin_watson=1.8,
            passed_residual_gate=True,
            confidence_return_spearman=0.1,
            passed_confidence_constraint=True,
            confidence_sharpe=0.3,
            sharpe_improvement=0.15,
        ).to_dict(),
        "pareto_candidates": [],
        "n_trials_passed_gate": gate_passed,
        "n_trials_total": n_trials,
        "total_time_seconds": 600.0,
        "config": RegressionOptimizationConfig().to_dict(),
        "timestamp": datetime(2026, 4, 14, 12, 0, 0).isoformat(),
        "all_trials": [],
    }


def _write_result(tmpdir: Path, filename: str, **overrides) -> Path:
    """Write a result JSON file and return its path."""
    data = _make_result_json(**overrides)
    path = tmpdir / filename
    path.write_text(json.dumps(data, indent=2))
    return path


# ---------------------------------------------------------------------------
# parse_args
# ---------------------------------------------------------------------------

class TestParseArgs:
    def test_show(self):
        args = parse_args(["show", "result.json"])
        assert args.command == "show"
        assert args.path == "result.json"

    def test_list_default_sort(self):
        args = parse_args(["list"])
        assert args.command == "list"
        assert args.sort == "time"

    def test_list_sort_score(self):
        args = parse_args(["list", "--sort", "score"])
        assert args.sort == "score"

    def test_watch(self):
        args = parse_args(["watch", "--interval", "3"])
        assert args.command == "watch"
        assert args.interval == 3

    def test_watch_default(self):
        args = parse_args(["watch"])
        assert args.command == "watch"
        assert args.interval == 5

    def test_compare(self):
        args = parse_args(["compare", "a.json", "b.json"])
        assert args.command == "compare"
        assert args.path1 == "a.json"
        assert args.path2 == "b.json"


# ---------------------------------------------------------------------------
# cmd_show
# ---------------------------------------------------------------------------

class TestCmdShow:
    def test_show_valid_file(self, tmp_path, capsys):
        path = _write_result(tmp_path, "r1.json")
        rc = cmd_show(str(path))
        assert rc == 0
        out = capsys.readouterr().out
        assert "BTCUSDT" in out
        assert "1h" in out
        assert "0.6" in out  # first objective value
        assert "Direction Accuracy" in out

    def test_show_missing_file(self, capsys):
        rc = cmd_show("/nonexistent/path.json")
        assert rc == 1
        err = capsys.readouterr().err
        assert "not found" in err.lower() or "ERROR" in err


# ---------------------------------------------------------------------------
# cmd_list (with mocked results dir)
# ---------------------------------------------------------------------------

class TestCmdList:
    def test_list_with_files(self, tmp_path, capsys, monkeypatch):
        # Write two result files
        _write_result(tmp_path, "btc_1h.json", asset="BTCUSDT", best_objective_values=[0.6, 0.85, 0.3])
        _write_result(tmp_path, "eth_4h.json", asset="ETHUSDT", timeframe="4h", best_objective_values=[0.7, 0.9, 0.4])

        # Monkeypatch _RESULTS_DIR
        import app.regression.scripts.monitor_optimization as mod
        monkeypatch.setattr(mod, "_RESULTS_DIR", tmp_path)

        rc = cmd_list("time")
        assert rc == 0
        out = capsys.readouterr().out
        assert "BTCUSDT" in out
        assert "ETHUSDT" in out
        assert "2 result(s)" in out

    def test_list_empty_dir(self, tmp_path, capsys, monkeypatch):
        import app.regression.scripts.monitor_optimization as mod
        monkeypatch.setattr(mod, "_RESULTS_DIR", tmp_path)

        rc = cmd_list("time")
        assert rc == 0
        out = capsys.readouterr().out
        assert "No result files" in out

    def test_list_sort_by_score(self, tmp_path, capsys, monkeypatch):
        _write_result(tmp_path, "low.json", best_objective_values=[0.2, 0.3, 0.1])
        _write_result(tmp_path, "high.json", best_objective_values=[0.8, 0.9, 0.7])

        import app.regression.scripts.monitor_optimization as mod
        monkeypatch.setattr(mod, "_RESULTS_DIR", tmp_path)

        rc = cmd_list("score")
        assert rc == 0
        out = capsys.readouterr().out
        # High score should appear first
        high_pos = out.index("0.8")
        low_pos = out.index("0.2")
        assert high_pos < low_pos


# ---------------------------------------------------------------------------
# cmd_compare
# ---------------------------------------------------------------------------

class TestCmdCompare:
    def test_compare_two_files(self, tmp_path, capsys):
        p1 = _write_result(tmp_path, "run_a.json", best_objective_values=[0.5, 0.7, 0.3], n_trials=100)
        p2 = _write_result(tmp_path, "run_b.json", best_objective_values=[0.7, 0.85, 0.4], n_trials=200)

        rc = cmd_compare(str(p1), str(p2))
        assert rc == 0
        out = capsys.readouterr().out
        assert "COMPARISON" in out
        assert "Run A" in out
        assert "Run B" in out
        assert "window_size" in out

    def test_compare_missing_file(self, tmp_path, capsys):
        p1 = _write_result(tmp_path, "run_a.json")
        rc = cmd_compare(str(p1), "/nonexistent.json")
        assert rc == 1

    def test_compare_shows_delta(self, tmp_path, capsys):
        p1 = _write_result(tmp_path, "a.json", best_objective_values=[0.4, 0.5, 0.2], n_trials=50)
        p2 = _write_result(tmp_path, "b.json", best_objective_values=[0.7, 0.8, 0.5], n_trials=100)

        cmd_compare(str(p1), str(p2))
        out = capsys.readouterr().out
        # Should show the delta (+0.2500 or similar)
        assert "+" in out


# ---------------------------------------------------------------------------
# help flag
# ---------------------------------------------------------------------------

class TestMonitorHelp:
    def test_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc_info:
            parse_args(["--help"])
        assert exc_info.value.code == 0
