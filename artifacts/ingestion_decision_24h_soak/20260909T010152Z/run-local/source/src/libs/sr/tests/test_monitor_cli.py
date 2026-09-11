"""Tests for SR monitor_optimization CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.sr.scripts.monitor_optimization import (
    parse_args,
    cmd_show,
    cmd_list,
    cmd_compare,
    _load_result_summary,
    _fmt_param,
)


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------

def _make_result_json(path: Path, global_score: float = 0.85, assets: list | None = None) -> Path:
    """Write a minimal TwoStageResult-shaped JSON file."""
    assets = assets or ["BTCUSDT"]
    data = {
        "global_params": {"lifecycle.age_lambda": 0.003, "ensemble.structural_vs_micro_ratio": 0.55},
        "global_score": global_score,
        "per_asset_params": {a: {"1h": {"some_param": 0.1}} for a in assets},
        "per_asset_results": [
            {
                "asset": a,
                "timeframe": "1h",
                "best_params": {"some_param": 0.1},
                "train_score": 0.80,
                "val_score": 0.75,
                "accepted": True,
                "fallback_to_global": False,
                "n_folds": 3,
                "fold_scores": [0.7, 0.8, 0.75],
                "gate_failures": 0,
                "constraint_failures": 1,
            }
            for a in assets
        ],
        "metadata": {
            "total_time_seconds": 120.5,
            "stage1_n_trials": 50,
            "stage2_assets_optimized": len(assets),
            "stage2_assets_accepted": len(assets),
        },
        "timestamp": "2026-04-29T12:00:00",
    }
    path.write_text(json.dumps(data, indent=2))
    return path


# -----------------------------------------------------------------------
# parse_args
# -----------------------------------------------------------------------

class TestParseArgs:
    def test_show(self):
        args = parse_args(["show", "some/path.json"])
        assert args.command == "show"
        assert args.path == "some/path.json"

    def test_list(self):
        args = parse_args(["list", "--sort", "score"])
        assert args.command == "list"
        assert args.sort == "score"

    def test_watch(self):
        args = parse_args(["watch", "--interval", "3"])
        assert args.command == "watch"
        assert args.interval == 3

    def test_compare(self):
        args = parse_args(["compare", "a.json", "b.json"])
        assert args.command == "compare"
        assert args.path1 == "a.json"
        assert args.path2 == "b.json"

    def test_no_command(self):
        args = parse_args([])
        assert args.command is None


# -----------------------------------------------------------------------
# cmd_show
# -----------------------------------------------------------------------

class TestCmdShow:
    def test_missing_file(self):
        code = cmd_show("/nonexistent/path.json")
        assert code == 1

    def test_valid_file(self, tmp_path: Path, capsys):
        result_path = _make_result_json(tmp_path / "test.json", global_score=0.92)
        code = cmd_show(str(result_path))
        assert code == 0
        output = capsys.readouterr().out
        assert "0.9200" in output
        assert "BTCUSDT" in output
        assert "accepted" in output


# -----------------------------------------------------------------------
# cmd_list
# -----------------------------------------------------------------------

class TestCmdList:
    def test_empty_dir(self, tmp_path: Path, monkeypatch, capsys):
        import app.sr.scripts.monitor_optimization as mod
        monkeypatch.setattr(mod, "_RESULTS_DIR", tmp_path)
        code = cmd_list()
        assert code == 0
        assert "No result files" in capsys.readouterr().out

    def test_with_results(self, tmp_path: Path, monkeypatch, capsys):
        import app.sr.scripts.monitor_optimization as mod
        monkeypatch.setattr(mod, "_RESULTS_DIR", tmp_path)
        _make_result_json(tmp_path / "run1.json", global_score=0.85)
        _make_result_json(tmp_path / "run2.json", global_score=0.90)
        code = cmd_list(sort_by="score")
        assert code == 0
        output = capsys.readouterr().out
        assert "run1.json" in output
        assert "run2.json" in output
        assert "2 result(s)" in output


# -----------------------------------------------------------------------
# cmd_compare
# -----------------------------------------------------------------------

class TestCmdCompare:
    def test_missing_file(self):
        code = cmd_compare("/nonexistent/a.json", "/nonexistent/b.json")
        assert code == 1

    def test_valid_comparison(self, tmp_path: Path, capsys):
        p1 = _make_result_json(tmp_path / "run1.json", global_score=0.80)
        p2 = _make_result_json(tmp_path / "run2.json", global_score=0.90)
        code = cmd_compare(str(p1), str(p2))
        assert code == 0
        output = capsys.readouterr().out
        assert "COMPARISON" in output
        assert "+0.1000" in output  # delta
        assert "run1.json" in output
        assert "run2.json" in output

    def test_param_diff_marker(self, tmp_path: Path, capsys):
        """Changed params should get * marker."""
        p1 = _make_result_json(tmp_path / "a.json", global_score=0.80)
        # Modify one param in second file
        d = json.loads(p1.read_text())
        d["global_params"]["lifecycle.age_lambda"] = 0.005
        d["global_score"] = 0.82
        p2 = tmp_path / "b.json"
        p2.write_text(json.dumps(d))

        code = cmd_compare(str(p1), str(p2))
        assert code == 0
        output = capsys.readouterr().out
        assert "*" in output


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

class TestHelpers:
    def test_fmt_param_float(self):
        assert _fmt_param(0.123456789) == "0.123457"

    def test_fmt_param_none(self):
        assert _fmt_param(None) == "-"

    def test_fmt_param_str(self):
        assert _fmt_param("tpe") == "tpe"

    def test_load_result_summary(self, tmp_path: Path):
        p = _make_result_json(tmp_path / "test.json", global_score=0.88, assets=["BTCUSDT", "ETHUSDT"])
        s = _load_result_summary(p)
        assert s is not None
        assert s["global_score"] == 0.88
        assert "BTCUSDT" in s["assets"]
        assert s["n_asset_results"] == 2

    def test_load_result_summary_invalid(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        assert _load_result_summary(bad) is None
