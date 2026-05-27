"""Tests for DivergenceEdgeScorer batch_evaluate VAM/residual extensions."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from libs.models.divergence_edge.model import DivergenceEdgeScorer


def _make_feature_df(n: int = 200, with_vam: bool = False, with_residual: bool = False) -> pd.DataFrame:
    """Create a synthetic feature DataFrame with divergence-producing patterns."""
    np.random.seed(42)

    # Create price trending up, indicators trending down → bearish divergence
    close = 100.0 + np.cumsum(np.random.randn(n) * 0.5 + 0.05)
    rsi = 60.0 - np.cumsum(np.random.randn(n) * 0.3 + 0.02)
    macd_hist = 2.0 - np.cumsum(np.random.randn(n) * 0.1 + 0.01)
    mfi = 70.0 - np.cumsum(np.random.randn(n) * 0.4 + 0.03)
    atr = np.full(n, 2.0)

    data = {
        "close": close,
        "RSI": rsi,
        "MACD_histogram": macd_hist,
        "MFI": mfi,
        "ATR": atr,
    }

    if with_vam:
        # VAM same sign as divergence direction (negative → bearish)
        data["eng_volume_adjusted_momentum"] = np.full(n, -0.5)

    if with_residual:
        # Residual same sign as divergence direction
        data["eng_residual_momentum"] = np.full(n, -0.3)

    return pd.DataFrame(data)


class TestBatchEvaluateExtended:

    def test_baseline_without_vam_residual(self):
        """batch_evaluate works without VAM/residual columns."""
        df = _make_feature_df(200)
        model = DivergenceEdgeScorer()
        result = model.batch_evaluate(df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(df)

    def test_vam_changes_output(self):
        """Adding VAM column should change non-zero outputs."""
        df_no_vam = _make_feature_df(200, with_vam=False)
        df_with_vam = _make_feature_df(200, with_vam=True)

        model1 = DivergenceEdgeScorer()
        model2 = DivergenceEdgeScorer()

        result_no_vam = model1.batch_evaluate(df_no_vam)
        result_with_vam = model2.batch_evaluate(df_with_vam)

        # Where both are non-zero, the VAM version should differ
        nonzero_mask = (result_no_vam != 0) & (result_with_vam != 0)
        if nonzero_mask.any():
            assert not np.allclose(
                result_no_vam[nonzero_mask].values,
                result_with_vam[nonzero_mask].values,
            ), "VAM column should change output values"

    def test_residual_changes_output(self):
        """Adding residual column should change non-zero outputs."""
        df_no_res = _make_feature_df(200, with_residual=False)
        df_with_res = _make_feature_df(200, with_residual=True)

        model1 = DivergenceEdgeScorer()
        model2 = DivergenceEdgeScorer()

        result_no_res = model1.batch_evaluate(df_no_res)
        result_with_res = model2.batch_evaluate(df_with_res)

        nonzero_mask = (result_no_res != 0) & (result_with_res != 0)
        if nonzero_mask.any():
            assert not np.allclose(
                result_no_res[nonzero_mask].values,
                result_with_res[nonzero_mask].values,
            ), "Residual column should change output values"

    def test_vam_confirm_boost_increases_magnitude(self):
        """When VAM confirms divergence direction, magnitude should increase."""
        df = _make_feature_df(200, with_vam=True)
        model_boosted = DivergenceEdgeScorer({"vam_confirm_boost": 0.4})
        model_no_boost = DivergenceEdgeScorer({"vam_confirm_boost": 0.0})

        result_boosted = model_boosted.batch_evaluate(df)
        result_no_boost = model_no_boost.batch_evaluate(df)

        # Where VAM confirms, boosted magnitude should be >= no-boost magnitude
        nonzero = result_no_boost != 0
        if nonzero.any():
            assert (
                result_boosted[nonzero].abs().sum()
                >= result_no_boost[nonzero].abs().sum()
            )

    def test_zero_entries_unchanged(self):
        """Bars with zero edge_score should remain zero after VAM/residual."""
        df = _make_feature_df(200, with_vam=True, with_residual=True)
        model = DivergenceEdgeScorer()
        result = model.batch_evaluate(df)

        # The first lookback-1 bars (13 bars for default lookback=14) should be zero
        assert (result.iloc[:13] == 0.0).all()
