"""Tests for optimization scoring, param_auditor, param_writeback, per-model
objectives, and new Pydantic schemas (optimization redesign coverage)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import yaml

from libs.contracts.schemas import (
    OptimizationConfig,
    OptimizationDefaults,
    ParamAuditReport,
    ScheduleEntry,
)
from libs.optim_utils.param_auditor import (
    ParamAuditor,
    _DRAWDOWN_DEGRADATION_THRESHOLD,
    _SHARPE_IMPROVEMENT_THRESHOLD,
)
from libs.optim_utils.param_writeback import (
    read_current_params,
    write_best_params,
)
from libs.optim_utils.scoring import (
    compute_max_drawdown,
    compute_returns,
    compute_sharpe,
    compute_win_rate,
    split_temporal,
)
from libs.optim_utils.scoring_feature_pipeline import _required_warmup_bars


# ---------------------------------------------------------------------------
# scoring.py — split_temporal
# ---------------------------------------------------------------------------

class TestSplitTemporal:
    def test_correct_lengths(self):
        df = pd.DataFrame({"a": range(100)})
        tr, te, va = split_temporal(df, train=0.6, test=0.2, val=0.2)
        assert len(tr) == 60
        assert len(te) == 20
        assert len(va) == 20

    def test_ratios_must_sum_to_one(self):
        df = pd.DataFrame({"a": range(50)})
        with pytest.raises(AssertionError, match="sum to 1.0"):
            split_temporal(df, train=0.5, test=0.2, val=0.2)

    def test_no_overlap(self):
        df = pd.DataFrame({"a": range(100)})
        tr, te, va = split_temporal(df, train=0.6, test=0.2, val=0.2)
        all_indices = set(tr.index) | set(te.index) | set(va.index)
        assert len(all_indices) == len(tr) + len(te) + len(va)


# ---------------------------------------------------------------------------
# scoring.py — compute_returns
# ---------------------------------------------------------------------------

class TestComputeReturns:
    def test_direction_alignment(self):
        close = np.array([100.0, 110.0, 105.0, 115.0])
        directions = np.array([1, 1, -1, 0])
        returns, trade_mask = compute_returns(directions, close, cost_bps=0.0)
        # dir=1 at bar0: earns (110-100)/100 = +0.10
        # dir=1 at bar1: earns (105-110)/110 ~ -0.0455
        # dir=-1 at bar2: earns -(115-105)/105 ~ -0.0952
        assert len(returns) == 3
        assert returns[0] == pytest.approx(0.1, abs=1e-6)
        assert returns[1] < 0
        assert returns[2] < 0

    def test_costs_reduce_returns(self):
        close = np.array([100.0, 110.0, 110.0])
        directions = np.array([1, 1, 0])
        ret_no_cost, _ = compute_returns(directions, close, cost_bps=0.0)
        ret_with_cost, _ = compute_returns(directions, close, cost_bps=10.0)
        assert ret_with_cost[0] < ret_no_cost[0]

    def test_trade_mask_flags_position_changes(self):
        close = np.array([100.0, 101.0, 102.0, 103.0])
        directions = np.array([0, 1, 1, -1])
        _, trade_mask = compute_returns(directions, close, cost_bps=0.0)
        # pos = [0, 1, 1], trades = diff([0, 0, 1, 1]) = [0, 1, 0]
        assert trade_mask[1] is np.True_
        assert trade_mask[2] is np.False_


# ---------------------------------------------------------------------------
# scoring.py — compute_sharpe
# ---------------------------------------------------------------------------

class TestComputeSharpe:
    def test_zero_std_returns_zero(self):
        returns = np.array([0.01, 0.01, 0.01])
        assert compute_sharpe(returns) == 0.0

    def test_empty_returns_zero(self):
        assert compute_sharpe(np.array([])) == 0.0

    def test_positive_returns_positive_sharpe(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.01, 500)
        assert compute_sharpe(returns, "1h") > 0


# ---------------------------------------------------------------------------
# scoring.py — compute_max_drawdown
# ---------------------------------------------------------------------------

class TestComputeMaxDrawdown:
    def test_known_drawdown(self):
        # cumulative: 1.10, 1.10*0.90=0.99, 0.99*1.05=1.0395
        returns = np.array([0.10, -0.10, 0.05])
        dd = compute_max_drawdown(returns)
        assert dd < 0
        assert dd == pytest.approx(-0.10, abs=0.01)

    def test_empty_returns_zero(self):
        assert compute_max_drawdown(np.array([])) == 0.0

    def test_monotonic_up_no_drawdown(self):
        returns = np.array([0.01, 0.02, 0.01])
        dd = compute_max_drawdown(returns)
        assert dd == pytest.approx(0.0, abs=1e-10)


# ---------------------------------------------------------------------------
# scoring.py — compute_win_rate
# ---------------------------------------------------------------------------

class TestComputeWinRate:
    def test_known_trades(self):
        returns = np.array([0.05, -0.02, 0.03, -0.01])
        trade_mask = np.array([True, True, True, True])
        assert compute_win_rate(returns, trade_mask) == pytest.approx(0.5)

    def test_no_trades_returns_zero(self):
        returns = np.array([0.05, -0.02])
        trade_mask = np.array([False, False])
        assert compute_win_rate(returns, trade_mask) == 0.0


# ---------------------------------------------------------------------------
# param_auditor.py — _recommend threshold logic
# ---------------------------------------------------------------------------

class TestParamAuditorRecommend:
    def test_adopt_when_sharpe_improves(self):
        deltas = {"sharpe": _SHARPE_IMPROVEMENT_THRESHOLD + 0.01, "max_drawdown": 0.0}
        rec, reason = ParamAuditor._recommend(deltas)
        assert rec == "adopt"

    def test_reject_when_drawdown_worsens(self):
        deltas = {"sharpe": 0.5, "max_drawdown": -(_DRAWDOWN_DEGRADATION_THRESHOLD + 0.01)}
        rec, reason = ParamAuditor._recommend(deltas)
        assert rec == "reject"

    def test_review_when_sharpe_below_threshold(self):
        deltas = {"sharpe": _SHARPE_IMPROVEMENT_THRESHOLD - 0.01, "max_drawdown": 0.0}
        rec, reason = ParamAuditor._recommend(deltas)
        assert rec == "review"

    def test_reject_takes_priority_over_adopt(self):
        deltas = {
            "sharpe": _SHARPE_IMPROVEMENT_THRESHOLD + 0.5,
            "max_drawdown": -(_DRAWDOWN_DEGRADATION_THRESHOLD + 0.1),
        }
        rec, _ = ParamAuditor._recommend(deltas)
        assert rec == "reject"


# ---------------------------------------------------------------------------
# param_writeback.py — write_best_params / read_current_params
# ---------------------------------------------------------------------------

class TestParamWriteback:
    def test_write_best_params_creates_file(self, tmp_path):
        with patch("libs.optim_utils.param_writeback._config_dir", return_value=tmp_path):
            out = write_best_params("TestModel", "BTCUSDT", "1h", {"a": 1})
            assert out.exists()
            data = yaml.safe_load(out.read_text())
            assert data["TestModel"]["BTCUSDT"]["1h"] == {"a": 1}

    def test_write_best_params_merges(self, tmp_path):
        with patch("libs.optim_utils.param_writeback._config_dir", return_value=tmp_path):
            write_best_params("M1", "BTC", "1h", {"x": 1})
            write_best_params("M2", "ETH", "4h", {"y": 2})
            data = yaml.safe_load((tmp_path / "optimized_params.yaml").read_text())
            assert data["M1"]["BTC"]["1h"] == {"x": 1}
            assert data["M2"]["ETH"]["4h"] == {"y": 2}

    def test_read_current_params_from_models_yaml(self, tmp_path):
        models_data = {
            "models": {
                "MeanReversion": {
                    "assets": {
                        "BTCUSDT": {
                            "timeframes": {
                                "1h": {"params": {"rsi_oversold": 30}}
                            }
                        }
                    }
                }
            }
        }
        (tmp_path / "models.yaml").write_text(yaml.dump(models_data))
        with patch("libs.optim_utils.param_writeback._config_dir", return_value=tmp_path):
            params = read_current_params("MeanReversion", "BTCUSDT", "1h")
            assert params == {"rsi_oversold": 30}

    def test_read_current_params_missing_returns_none(self, tmp_path):
        (tmp_path / "models.yaml").write_text(yaml.dump({"models": {}}))
        with patch("libs.optim_utils.param_writeback._config_dir", return_value=tmp_path):
            assert read_current_params("NoSuchModel", "X", "1h") is None


# ---------------------------------------------------------------------------
# Per-model optimizer objectives
# ---------------------------------------------------------------------------

def _make_feature_df(n: int = 200) -> pd.DataFrame:
    """Synthetic feature_df with OHLC + indicators."""
    rng = np.random.default_rng(42)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + rng.uniform(0.1, 1.0, n)
    low = close - rng.uniform(0.1, 1.0, n)
    return pd.DataFrame({
        "open": close + rng.normal(0, 0.2, n),
        "high": high,
        "low": low,
        "close": close,
        "volume": rng.uniform(100, 1000, n),
        "ema_5": close + rng.normal(0, 0.1, n),
        "ema_21": close + rng.normal(0, 0.3, n),
        "rsi_14": rng.uniform(20, 80, n),
    })


class TestPerModelObjectives:
    def test_mean_reversion_returns_float(self):
        from libs.models.mean_reversion.optimization.optimizer import (
            make_objective as mr_obj,
        )

        feature_df = _make_feature_df()
        obj = mr_obj(feature_df, timeframe="1h", cost_bps=10.0)
        # Simulate a trial using a trivial Optuna study
        import optuna

        study = optuna.create_study(direction="maximize")
        study.optimize(obj, n_trials=1, show_progress_bar=False)
        assert isinstance(study.best_value, float)


class TestScoringFeatureWarmup:
    def test_required_warmup_uses_max_indicator_lookback(self):
        class _Indicator:
            def __init__(self, lookback_required):
                self.lookback_required = lookback_required

        class _FeatureManager:
            indicators = [_Indicator(40), _Indicator(180), _Indicator(60)]

        assert _required_warmup_bars(_FeatureManager(), 500) == 180

    def test_required_warmup_keeps_minimum_floor(self):
        class _Indicator:
            def __init__(self, lookback_required):
                self.lookback_required = lookback_required

        class _FeatureManager:
            indicators = [_Indicator(20)]

        assert _required_warmup_bars(_FeatureManager(), 500) == 100

    def test_required_warmup_caps_at_available_bars(self):
        class _Indicator:
            def __init__(self, lookback_required):
                self.lookback_required = lookback_required

        class _FeatureManager:
            indicators = [_Indicator(180)]

        assert _required_warmup_bars(_FeatureManager(), 120) == 120

    def test_trend_following_returns_two_tuple(self):
        from libs.models.trend_following.optimization.optimizer import (
            make_objective as tf_obj,
        )

        feature_df = _make_feature_df()
        obj = tf_obj(feature_df, timeframe="1h", cost_bps=10.0)
        import optuna

        study = optuna.create_study(directions=["maximize", "maximize"])
        study.optimize(obj, n_trials=1, show_progress_bar=False)
        assert len(study.best_trials) >= 1
        assert len(study.best_trials[0].values) == 2

    def test_momentum_constraint_enforcement(self):
        from libs.models.momentum.optimization.optimizer import (
            make_objective as mom_obj,
        )

        feature_df = _make_feature_df()
        obj = mom_obj(feature_df, timeframe="1h", cost_bps=10.0)
        import optuna

        study = optuna.create_study(direction="maximize")
        study.optimize(obj, n_trials=3, show_progress_bar=False)
        assert len(study.trials) == 3
        for trial in study.trials:
            assert isinstance(trial.value, float)

    def test_squeeze_breakout_multi_tp_objective(self):
        """SqueezeBreakout optimizer uses multi-TP scoring with v7 params."""
        from libs.models.squeeze_breakout.optimization.optimizer import (
            make_objective as sb_obj,
        )

        feature_df = _make_feature_df()
        obj = sb_obj(
            feature_df, timeframe="1h", cost_bps=10.0,
            tp_pcts=(0.015, 0.03, 0.05),
            tp_portions=(0.40, 0.30, 0.30),
            sl_pct=0.02,
            trail_to_breakeven=True,
        )
        import optuna

        study = optuna.create_study(direction="maximize")
        study.optimize(obj, n_trials=2, show_progress_bar=False)
        assert len(study.trials) == 2
        for trial in study.trials:
            assert isinstance(trial.value, float)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class TestPydanticSchemas:
    def test_param_audit_report_construction(self):
        report = ParamAuditReport(
            model_name="MeanReversion",
            asset="BTCUSDT",
            timeframe="1h",
            current_params={"a": 1},
            proposed_params={"a": 2},
            current_metrics={"sharpe": 1.0},
            proposed_metrics={"sharpe": 1.2},
            deltas={"sharpe": 0.2},
            recommendation="adopt",
            reason="Sharpe improved",
        )
        assert report.recommendation == "adopt"
        assert report.deltas["sharpe"] == 0.2

    def test_schedule_entry_defaults(self):
        entry = ScheduleEntry(cron="0 2 * * 1")
        assert entry.assets == []
        assert entry.timeframes == []
        assert entry.n_trials is None
        assert entry.write_back is False

    def test_optimization_defaults(self):
        defaults = OptimizationDefaults()
        assert defaults.n_trials == 200
        assert defaults.write_back is False

    def test_optimization_config_construction(self):
        cfg = OptimizationConfig(
            defaults=OptimizationDefaults(n_trials=500),
            schedules={
                "MeanReversion": ScheduleEntry(
                    cron="0 3 * * *",
                    assets=["BTCUSDT"],
                    timeframes=["1h"],
                    n_trials=300,
                )
            },
        )
        assert cfg.defaults.n_trials == 500
        assert cfg.schedules["MeanReversion"].cron == "0 3 * * *"

    def test_optimization_config_empty(self):
        cfg = OptimizationConfig()
        assert cfg.defaults.n_trials == 200
        assert cfg.schedules == {}
