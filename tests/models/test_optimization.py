"""Tests for the optimization module: OptunaRunner, objective, schemas."""

import pytest

from libs.contracts.schemas import StudyConfig, TrialResult, ParamDef
from libs.models.mean_reversion import MeanReversionModel
from libs.optimization.runner import OptunaRunner
from libs.optimization.objective import make_objective, build_suggest


class TestOptunaRunner:
    def _mock_backtest(self, model):
        """Simple mock: return sharpe proportional to rsi_oversold."""
        return {"sharpe": model.params.get("rsi_oversold", 30) / 100.0}

    def test_single_objective_study(self):
        config = StudyConfig(
            model_name="MeanReversion",
            asset="BTCUSDT",
            timeframe="1h",
            objectives=["sharpe"],
            directions=["maximize"],
            n_trials=10,
            sampler="TPE",
        )
        runner = OptunaRunner(config)
        results = runner.run(self._mock_backtest)
        assert len(results) == 10
        completed = [r for r in results if r.state == "COMPLETE"]
        assert len(completed) >= 1

    def test_multi_objective_study(self):
        def multi_backtest(model):
            s = model.params.get("rsi_oversold", 30) / 100.0
            dd = -abs(model.params.get("rsi_overbought", 70) - 70) / 100.0
            return {"sharpe": s, "max_drawdown": dd}

        config = StudyConfig(
            model_name="MeanReversion",
            asset="BTCUSDT",
            timeframe="1h",
            objectives=["sharpe", "max_drawdown"],
            directions=["maximize", "minimize"],
            n_trials=15,
            sampler="NSGA-II",
        )
        runner = OptunaRunner(config)
        results = runner.run(multi_backtest)
        assert len(results) == 15
        # At least some should be complete
        completed = [r for r in results if r.state == "COMPLETE"]
        assert len(completed) >= 2

    def test_trial_result_fields(self):
        config = StudyConfig(
            model_name="MeanReversion",
            asset="BTCUSDT",
            timeframe="1h",
            n_trials=3,
        )
        runner = OptunaRunner(config)
        results = runner.run(self._mock_backtest)
        for r in results:
            assert isinstance(r, TrialResult)
            assert isinstance(r.params, dict)
            assert isinstance(r.values, dict)


class TestObjective:
    def test_make_objective_callable(self):
        def dummy_bt(model):
            return {"sharpe": 1.0}

        obj = make_objective("MeanReversion", dummy_bt)
        assert callable(obj)


class TestSchemas:
    def test_study_config_defaults(self):
        sc = StudyConfig(model_name="X", asset="A", timeframe="1h")
        assert sc.n_trials == 200
        assert sc.sampler == "TPE"

    def test_trial_result_roundtrip(self):
        tr = TrialResult(
            study_name="test",
            trial_number=0,
            params={"a": 1},
            values={"sharpe": 1.5},
            state="COMPLETE",
            duration_seconds=0.1,
            timestamp=1000.0,
        )
        d = tr.model_dump()
        tr2 = TrialResult(**d)
        assert tr2.study_name == "test"
        assert tr2.values["sharpe"] == 1.5
