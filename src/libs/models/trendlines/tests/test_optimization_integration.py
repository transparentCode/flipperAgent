"""Integration tests for trendlines optimization — facade + YAML writeback."""

from __future__ import annotations

import yaml
import numpy as np
import pandas as pd
import pytest

from app.trendlines.optimization.optimizer import OPTUNA_AVAILABLE

pytestmark = pytest.mark.skipif(not OPTUNA_AVAILABLE, reason="optuna not installed")

from app.trendlines.api import optimize_trendlines
from app.trendlines.optimization.models import (
    TrendlinesOptimizationConfig,
    TrendlinesOptimizationResult,
)
from app.trendlines.optimization.walk_forward import WalkForwardSplit, WalkForwardValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 4000, base: float = 100.0) -> pd.DataFrame:
    rng = np.random.RandomState(42)
    closes = base + np.cumsum(rng.randn(n) * 0.5)
    return pd.DataFrame({
        "open": closes - rng.rand(n) * 0.3,
        "high": closes + rng.rand(n) * 1.0,
        "low": closes - rng.rand(n) * 1.0,
        "close": closes,
        "volume": rng.rand(n) * 1000,
    })


# Reuse mock from test_optimizer
from app.trendlines.tests.test_optimizer import _mock_pipeline_factory


# ---------------------------------------------------------------------------
# Walk-forward validator
# ---------------------------------------------------------------------------

class TestWalkForwardValidator:
    def test_n_folds(self):
        wf = WalkForwardValidator(train_bars=2160, test_bars=720, step_bars=720)
        n = wf.n_folds(4000)
        assert n >= 1

    def test_get_splits_structure(self):
        wf = WalkForwardValidator(train_bars=2160, test_bars=720, step_bars=720)
        splits = wf.get_splits(4000)
        assert len(splits) >= 1
        for s in splits:
            assert isinstance(s, WalkForwardSplit)
            assert s.train_end <= s.test_start
            assert s.train_size == 2160
            assert s.test_size == 720

    def test_iterate_splits(self):
        wf = WalkForwardValidator(train_bars=1000, test_bars=500, step_bars=500, min_train_bars=500)
        df = _make_ohlcv(3000)
        count = 0
        for split, train_df, test_df in wf.iterate_splits(df):
            assert len(train_df) == split.train_size
            assert len(test_df) == split.test_size
            count += 1
        assert count >= 1

    def test_insufficient_data(self):
        wf = WalkForwardValidator(train_bars=2160, test_bars=720, min_train_bars=2160)
        splits = wf.get_splits(100)
        assert len(splits) == 0


# ---------------------------------------------------------------------------
# Facade: optimize_trendlines()
# ---------------------------------------------------------------------------

class TestOptimizeTrendlinesFacade:
    def test_facade_returns_result(self):
        df = _make_ohlcv(4000)
        result = optimize_trendlines(
            df,
            asset="TEST",
            timeframe="1h",
            n_trials=2,
            pipeline_factory=_mock_pipeline_factory,
        )
        assert isinstance(result, TrendlinesOptimizationResult)
        assert result.n_trials_total == 2
        assert result.asset == "TEST"

    def test_facade_with_custom_config(self):
        df = _make_ohlcv(4000)
        config = TrendlinesOptimizationConfig(
            n_trials=2,
            interaction_tolerance_atr=(0.15, 0.35),
        )
        result = optimize_trendlines(
            df, asset="T", timeframe="1h",
            config=config, n_trials=2,
            pipeline_factory=_mock_pipeline_factory,
        )
        assert result.n_trials_total == 2


# ---------------------------------------------------------------------------
# YAML writeback
# ---------------------------------------------------------------------------

class TestYAMLWriteback:
    def test_writeback_creates_structure(self, tmp_path):
        yaml_path = str(tmp_path / "trendlines.yaml")
        with open(yaml_path, "w") as f:
            yaml.dump({"defaults": {"interaction_tolerance_atr": 0.25}}, f)

        df = _make_ohlcv(4000)
        result = optimize_trendlines(
            df, asset="BTCUSDT", timeframe="1h",
            n_trials=2, pipeline_factory=_mock_pipeline_factory,
        )
        result.apply_to_config(yaml_path)

        with open(yaml_path) as f:
            written = yaml.safe_load(f)

        assert "BTCUSDT" in written["assets"]
        assert "1h" in written["assets"]["BTCUSDT"]["timeframes"]
        tf = written["assets"]["BTCUSDT"]["timeframes"]["1h"]
        # Should have at least interaction_tolerance_atr from best_params
        assert "interaction_tolerance_atr" in tf

    def test_writeback_preserves_other_assets(self, tmp_path):
        yaml_path = str(tmp_path / "trendlines.yaml")
        cfg = {
            "defaults": {},
            "assets": {
                "ETHUSDT": {
                    "timeframes": {"1h": {"interaction_tolerance_atr": 0.22}}
                }
            },
        }
        with open(yaml_path, "w") as f:
            yaml.dump(cfg, f)

        df = _make_ohlcv(4000)
        result = optimize_trendlines(
            df, asset="BTCUSDT", timeframe="1h",
            n_trials=2, pipeline_factory=_mock_pipeline_factory,
        )
        result.apply_to_config(yaml_path)

        with open(yaml_path) as f:
            written = yaml.safe_load(f)

        # ETHUSDT should still be there
        assert written["assets"]["ETHUSDT"]["timeframes"]["1h"]["interaction_tolerance_atr"] == 0.22
        assert "BTCUSDT" in written["assets"]
