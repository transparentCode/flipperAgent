"""Tests for RegimePullbackScorer optimizer."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from libs.models.regime_pullback.optimization.optimizer import (
    FIXED_PARAMS,
    MODEL_NAME,
    make_objective,
    post_process_params,
)


def _make_feature_df(n: int = 500) -> pd.DataFrame:
    """Build a minimal feature DataFrame for RegimePullbackScorer."""
    np.random.seed(123)
    return pd.DataFrame({
        "close": 100.0 + np.cumsum(np.random.randn(n) * 0.5),
        "open": 100.0 + np.cumsum(np.random.randn(n) * 0.5),
        "high": 101.0 + np.cumsum(np.random.randn(n) * 0.5),
        "low": 99.0 + np.cumsum(np.random.randn(n) * 0.5),
        "volume": np.abs(np.random.randn(n)) * 1000,
        "RSI": np.random.uniform(20, 80, n),
        "eng_regime_score": np.random.uniform(-1.0, 0.5, n),
        "eng_mean_reversion_z": np.random.uniform(-3, 3, n),
        "eng_squeeze_intensity": np.random.uniform(0, 1, n),
        "eng_btc_dominance_regime": np.full(n, 0.0),
        "eng_market_cap_breadth": np.full(n, 0.0),
    })


class TestRegimePullbackOptimizer:

    def test_objective_returns_float(self):
        df = _make_feature_df()
        objective = make_objective(df, n_splits=3, embargo_bars=10)

        import optuna
        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=1, show_progress_bar=False)

        assert study.best_value is not None
        assert isinstance(study.best_value, float)

    def test_fixed_params_excluded_from_trial(self):
        df = _make_feature_df()
        objective = make_objective(df, n_splits=3, embargo_bars=10)

        import optuna
        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=1, show_progress_bar=False)

        trial_params = study.best_trial.params
        for fp in FIXED_PARAMS:
            assert fp not in trial_params, f"Fixed param '{fp}' should not be in trial params"

    def test_smoke_3_trials(self):
        df = _make_feature_df()
        objective = make_objective(df, n_splits=3, embargo_bars=10)

        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=3, show_progress_bar=False)

        completed = [t for t in study.trials if t.state.name == "COMPLETE"]
        assert len(completed) == 3

    def test_post_process_rounds_integers(self):
        params = {
            "rsi_oversold_gate": 35.7,
            "rsi_overbought_gate": 64.2,
            "regime_threshold": -0.15,
        }
        result = post_process_params(params)
        assert result["rsi_oversold_gate"] == 36
        assert result["rsi_overbought_gate"] == 64
        assert result["regime_threshold"] == -0.15

    def test_model_name(self):
        assert MODEL_NAME == "RegimePullbackScorer"

    def test_insufficient_data_raises(self):
        df = _make_feature_df(10)
        with pytest.raises(ValueError, match="Not enough data"):
            make_objective(df, n_splits=5, embargo_bars=50)
