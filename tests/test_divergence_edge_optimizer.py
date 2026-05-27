"""Tests for DivergenceEdgeScorer optimizer."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from libs.models.divergence_edge.optimization.optimizer import (
    FIXED_PARAMS,
    MODEL_NAME,
    make_objective,
    post_process_params,
)


def _make_feature_df(n: int = 500) -> pd.DataFrame:
    """Build a minimal feature DataFrame for DivergenceEdgeScorer."""
    np.random.seed(456)
    close = 100.0 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "close": close,
        "open": close - 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "volume": np.abs(np.random.randn(n)) * 1000,
        "RSI": np.random.uniform(20, 80, n),
        "MACD_histogram": np.random.randn(n) * 2,
        "MFI": np.random.uniform(20, 80, n),
        "ATR": np.full(n, 2.0),
        "eng_volume_adjusted_momentum": np.random.randn(n) * 0.5,
        "eng_residual_momentum": np.random.randn(n) * 0.3,
        "eng_altcoin_market_momentum": np.full(n, 0.0),
        "eng_altcoin_beta": np.full(n, 0.0),
    })


class TestDivergenceEdgeOptimizer:

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
            "divergence_lookback": 14.3,
            "min_confirming_indicators": 1.8,
            "weight_rsi": 0.35,
        }
        result = post_process_params(params)
        assert result["divergence_lookback"] == 14
        assert result["min_confirming_indicators"] == 2
        assert result["weight_rsi"] == 0.35

    def test_model_name(self):
        assert MODEL_NAME == "DivergenceEdgeScorer"

    def test_insufficient_data_raises(self):
        df = _make_feature_df(10)
        with pytest.raises(ValueError, match="Not enough data"):
            make_objective(df, n_splits=5, embargo_bars=50)
