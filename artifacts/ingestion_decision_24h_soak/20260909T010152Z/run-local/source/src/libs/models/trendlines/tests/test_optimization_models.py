"""Tests for trendlines optimization data models."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from libs.models.trendlines.optimization.models import (
    TrendlinesBenchmarkResults,
    TrendlinesOptimizationConfig,
    TrendlinesOptimizationResult,
    TrendlinesOptimizationWeights,
    TrendlinesTrialResult,
)


# ---------------------------------------------------------------------------
# TrendlinesBenchmarkResults
# ---------------------------------------------------------------------------

class TestBenchmarkResults:
    def test_defaults(self):
        br = TrendlinesBenchmarkResults()
        assert br.mean_longevity == 0.0
        assert br.mean_pen_rate == 1.0
        assert br.passed_penetration_gate is False
        assert br.passed_pivot_constraint is False

    def test_to_dict_roundtrip(self):
        br = TrendlinesBenchmarkResults(
            mean_longevity=0.85,
            n_lines=4,
            touch_accuracy=0.6,
            total_touches=10,
            total_hits=6,
            mean_pen_rate=0.2,
            passed_penetration_gate=True,
            mean_pivots=30.0,
            pivot_score=1.0,
            passed_pivot_constraint=True,
            fitness=0.408,
            n_bars=720,
        )
        d = br.to_dict()
        br2 = TrendlinesBenchmarkResults.from_dict(d)
        assert br2.mean_longevity == br.mean_longevity
        assert br2.passed_penetration_gate is True
        assert br2.n_lines == 4

    def test_from_dict_ignores_extra_keys(self):
        d = {"mean_longevity": 0.5, "unknown_field": 999}
        br = TrendlinesBenchmarkResults.from_dict(d)
        assert br.mean_longevity == 0.5


# ---------------------------------------------------------------------------
# TrendlinesOptimizationWeights
# ---------------------------------------------------------------------------

class TestWeights:
    def test_defaults_valid(self):
        w = TrendlinesOptimizationWeights()
        w.validate()  # should not raise

    def test_invalid_sum_raises(self):
        w = TrendlinesOptimizationWeights(longevity=0.5, touch_accuracy=0.5, fold_stability=0.5)
        with pytest.raises(ValueError, match="should sum"):
            w.validate()


# ---------------------------------------------------------------------------
# TrendlinesOptimizationConfig
# ---------------------------------------------------------------------------

class TestConfig:
    def test_defaults(self):
        cfg = TrendlinesOptimizationConfig()
        assert cfg.n_trials == 50
        assert cfg.interaction_tolerance_atr == (0.10, 0.50)
        assert cfg.train_bars == 2160
        assert cfg.soft_gate is True

    def test_to_dict(self):
        cfg = TrendlinesOptimizationConfig()
        d = cfg.to_dict()
        assert "interaction_tolerance_atr" in d
        assert "n_trials" in d
        assert d["sampler"] == "tpe"

    def test_search_bounds_order(self):
        cfg = TrendlinesOptimizationConfig()
        assert cfg.interaction_tolerance_atr[0] < cfg.interaction_tolerance_atr[1]
        assert cfg.asymmetry_threshold[0] < cfg.asymmetry_threshold[1]
        assert cfg.squeeze_threshold[0] < cfg.squeeze_threshold[1]


# ---------------------------------------------------------------------------
# TrendlinesTrialResult
# ---------------------------------------------------------------------------

class TestTrialResult:
    def test_to_dict(self):
        tr = TrendlinesTrialResult(
            trial_id=0,
            params={"interaction_tolerance_atr": 0.25},
            objective_value=0.5,
            benchmark_results=TrendlinesBenchmarkResults(),
            passed_gate=True,
            passed_constraint=True,
        )
        d = tr.to_dict()
        assert d["trial_id"] == 0
        assert d["passed_gate"] is True
        assert "benchmark_results" in d
        assert "timestamp" in d


# ---------------------------------------------------------------------------
# TrendlinesOptimizationResult — save/load roundtrip
# ---------------------------------------------------------------------------

class TestOptimizationResult:
    def _make_result(self) -> TrendlinesOptimizationResult:
        bench = TrendlinesBenchmarkResults(mean_longevity=0.9, passed_penetration_gate=True)
        trial = TrendlinesTrialResult(
            trial_id=0,
            params={"interaction_tolerance_atr": 0.25, "squeeze_threshold": 3.0},
            objective_value=0.6,
            benchmark_results=bench,
            passed_gate=True,
            passed_constraint=True,
        )
        return TrendlinesOptimizationResult(
            asset="BTCUSDT",
            timeframe="1h",
            best_params={"interaction_tolerance_atr": 0.25, "squeeze_threshold": 3.0},
            best_objective=0.6,
            best_benchmarks=bench,
            n_trials_passed_gate=1,
            n_trials_total=1,
            total_time_seconds=1.5,
            config=TrendlinesOptimizationConfig(),
            all_trials=[trial],
        )

    def test_save_load_roundtrip(self, tmp_path):
        result = self._make_result()
        path = str(tmp_path / "result.json")
        result.save(path)

        loaded = TrendlinesOptimizationResult.load(path)
        assert loaded.asset == "BTCUSDT"
        assert loaded.timeframe == "1h"
        assert loaded.best_objective == 0.6
        assert loaded.best_benchmarks.mean_longevity == 0.9
        assert len(loaded.all_trials) == 1
        assert loaded.all_trials[0].passed_gate is True

    def test_save_produces_valid_json(self, tmp_path):
        result = self._make_result()
        path = str(tmp_path / "result.json")
        result.save(path)
        with open(path) as f:
            data = json.load(f)
        assert data["asset"] == "BTCUSDT"
        assert isinstance(data["all_trials"], list)

    def test_apply_to_config(self, tmp_path):
        # Create a minimal YAML
        yaml_path = str(tmp_path / "trendlines.yaml")
        cfg = {
            "defaults": {"interaction_tolerance_atr": 0.25},
            "assets": {
                "BTCUSDT": {
                    "timeframes": {
                        "1h": {"interaction_tolerance_atr": 0.25}
                    }
                }
            },
        }
        with open(yaml_path, "w") as f:
            yaml.dump(cfg, f)

        result = self._make_result()
        result.best_params = {
            "interaction_tolerance_atr": 0.18,
            "squeeze_threshold": 2.5,
            "left_window": 5,  # categorical — should NOT be written
        }
        result.apply_to_config(yaml_path)

        with open(yaml_path) as f:
            written = yaml.safe_load(f)

        tf_block = written["assets"]["BTCUSDT"]["timeframes"]["1h"]
        assert tf_block["interaction_tolerance_atr"] == 0.18
        assert tf_block["squeeze_threshold"] == 2.5
        assert "left_window" not in tf_block

    def test_apply_to_config_creates_asset_block(self, tmp_path):
        yaml_path = str(tmp_path / "trendlines.yaml")
        with open(yaml_path, "w") as f:
            yaml.dump({"defaults": {}}, f)

        result = self._make_result()
        result.asset = "NEWCOIN"
        result.timeframe = "4h"
        result.best_params = {"interaction_tolerance_atr": 0.3}
        result.apply_to_config(yaml_path)

        with open(yaml_path) as f:
            written = yaml.safe_load(f)
        assert written["assets"]["NEWCOIN"]["timeframes"]["4h"]["interaction_tolerance_atr"] == 0.3
