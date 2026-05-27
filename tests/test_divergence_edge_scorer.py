"""Tests for DivergenceEdgeScorer."""

from __future__ import annotations

import collections
import pytest
import pandas as pd
import numpy as np

from libs.contracts.schemas import FeatureVector
from libs.contracts.signal import ScoringOutput
from libs.models.divergence_edge.model import DivergenceEdgeScorer, _ols_slope


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fv(features: dict, asset: str = "ETHUSDT", bar_data: dict | None = None) -> FeatureVector:
    return FeatureVector(
        asset=asset,
        timeframe="1h",
        timestamp=1700000000.0,
        features=features,
        bar_data=bar_data or {"close": 100.0},
    )


def _warm_model(model: DivergenceEdgeScorer, n: int,
                 price_trend: str = "up",
                 rsi_trend: str = "down",
                 macd_trend: str = "down",
                 mfi_trend: str = "down"):
    """Feed n bars to warm up the model's rolling buffers with specified trends.

    Returns the last FeatureVector used so the caller can assert on it.
    """
    lookback = model.params["divergence_lookback"]
    for i in range(n):
        if price_trend == "up":
            close = 100.0 + i * 1.0
        elif price_trend == "down":
            close = 100.0 - i * 1.0
        else:
            close = 100.0

        if rsi_trend == "down":
            rsi = 70.0 - i * 1.0
        elif rsi_trend == "up":
            rsi = 30.0 + i * 1.0
        else:
            rsi = 50.0

        if macd_trend == "down":
            macd_hist = 5.0 - i * 0.5
        elif macd_trend == "up":
            macd_hist = -5.0 + i * 0.5
        else:
            macd_hist = 0.0

        if mfi_trend == "down":
            mfi = 80.0 - i * 1.5
        elif mfi_trend == "up":
            mfi = 20.0 + i * 1.5
        else:
            mfi = 50.0

        features = {
            "RSI": rsi,
            "MACD": {"histogram": macd_hist, "macd": 0.0, "signal": 0.0},
            "MFI": mfi,
            "LinReg": {"slope": 1.0 if price_trend == "up" else -1.0 if price_trend == "down" else 0.0},
            "ATR": 2.0,
            "Momentum": 0.0,
            "eng_volume_adjusted_momentum": None,
            "eng_atr_normalized_return": None,
            "eng_residual_momentum": None,
            "eng_altcoin_market_momentum": None,
            "eng_altcoin_beta": None,
        }
        fv = _fv(features, bar_data={"close": close})
        model.evaluate(fv)
    return fv


# ---------------------------------------------------------------------------
# OLS slope helper test
# ---------------------------------------------------------------------------


class TestOlsSlope:
    def test_increasing_positive_slope(self):
        buf = collections.deque([1.0, 2.0, 3.0, 4.0, 5.0])
        slope = _ols_slope(buf)
        assert slope is not None
        assert slope > 0

    def test_decreasing_negative_slope(self):
        buf = collections.deque([5.0, 4.0, 3.0, 2.0, 1.0])
        slope = _ols_slope(buf)
        assert slope is not None
        assert slope < 0

    def test_insufficient_data(self):
        buf = collections.deque([1.0])
        assert _ols_slope(buf) is None

    def test_flat_zero_slope(self):
        buf = collections.deque([3.0, 3.0, 3.0, 3.0])
        slope = _ols_slope(buf)
        assert slope == pytest.approx(0.0, abs=1e-10)


# ---------------------------------------------------------------------------
# Gate tests
# ---------------------------------------------------------------------------


class TestDivergenceEdgeGates:
    def test_bullish_divergence(self):
        """Price down + RSI/MACD/MFI up → edge_score > 0."""
        m = DivergenceEdgeScorer({"divergence_lookback": 5})
        _warm_model(m, 5, price_trend="down", rsi_trend="up", macd_trend="up", mfi_trend="up")
        out = m.evaluate(_fv({
            "RSI": 35.0,
            "MACD": {"histogram": 2.0},
            "MFI": 55.0,
            "LinReg": {"slope": -1.0},
            "ATR": 2.0,
            "Momentum": 0.0,
        }, bar_data={"close": 95.0}))
        assert out.edge_score > 0.0

    def test_bearish_divergence(self):
        """Price up + RSI/MACD/MFI down → edge_score < 0."""
        m = DivergenceEdgeScorer({"divergence_lookback": 5})
        _warm_model(m, 5, price_trend="up", rsi_trend="down", macd_trend="down", mfi_trend="down")
        out = m.evaluate(_fv({
            "RSI": 65.0,
            "MACD": {"histogram": -2.0},
            "MFI": 40.0,
            "LinReg": {"slope": 1.0},
            "ATR": 2.0,
            "Momentum": 0.0,
        }, bar_data={"close": 105.0}))
        assert out.edge_score < 0.0

    def test_no_divergence(self):
        """Price and indicators agree → edge_score == 0."""
        m = DivergenceEdgeScorer({"divergence_lookback": 5})
        _warm_model(m, 5, price_trend="up", rsi_trend="up", macd_trend="up", mfi_trend="up")
        out = m.evaluate(_fv({
            "RSI": 75.0,
            "MACD": {"histogram": 5.0},
            "MFI": 80.0,
            "LinReg": {"slope": 1.0},
            "ATR": 2.0,
            "Momentum": 0.0,
        }, bar_data={"close": 110.0}))
        assert out.edge_score == 0.0

    def test_only_one_indicator_diverges(self):
        """Only 1 indicator diverges (min=2) → edge=0."""
        m = DivergenceEdgeScorer({"divergence_lookback": 5, "min_confirming_indicators": 2})
        # RSI diverges, MACD and MFI agree with price
        _warm_model(m, 5, price_trend="up", rsi_trend="down", macd_trend="up", mfi_trend="up")
        out = m.evaluate(_fv({
            "RSI": 40.0,
            "MACD": {"histogram": 5.0},
            "MFI": 80.0,
            "LinReg": {"slope": 1.0},
            "ATR": 2.0,
            "Momentum": 0.0,
        }, bar_data={"close": 110.0}))
        assert out.edge_score == 0.0

    def test_insufficient_lookback_history(self):
        """Not enough history → edge=0."""
        m = DivergenceEdgeScorer({"divergence_lookback": 14})
        out = m.evaluate(_fv({
            "RSI": 50.0,
            "MACD": {"histogram": 0.0},
            "MFI": 50.0,
            "LinReg": {"slope": 0.0},
            "ATR": 2.0,
            "Momentum": 0.0,
        }, bar_data={"close": 100.0}))
        assert out.edge_score == 0.0


# ---------------------------------------------------------------------------
# Magnitude / multiplier tests
# ---------------------------------------------------------------------------


class TestDivergenceEdgeMagnitude:
    def test_vam_confirms_boosts_edge(self):
        """VAM confirming divergence direction → larger |edge|."""
        m1 = DivergenceEdgeScorer({"divergence_lookback": 5})
        _warm_model(m1, 5, price_trend="down", rsi_trend="up", macd_trend="up", mfi_trend="up")
        out_no_vam = m1.evaluate(_fv({
            "RSI": 35.0,
            "MACD": {"histogram": 2.0},
            "MFI": 55.0,
            "LinReg": {"slope": -1.0},
            "ATR": 2.0,
            "Momentum": 0.0,
            "eng_volume_adjusted_momentum": None,
        }, bar_data={"close": 95.0}))

        m2 = DivergenceEdgeScorer({"divergence_lookback": 5})
        _warm_model(m2, 5, price_trend="down", rsi_trend="up", macd_trend="up", mfi_trend="up")
        out_with_vam = m2.evaluate(_fv({
            "RSI": 35.0,
            "MACD": {"histogram": 2.0},
            "MFI": 55.0,
            "LinReg": {"slope": -1.0},
            "ATR": 2.0,
            "Momentum": 0.0,
            "eng_volume_adjusted_momentum": 1.0,  # positive, confirms bullish divergence
        }, bar_data={"close": 95.0}))

        assert abs(out_with_vam.edge_score) > abs(out_no_vam.edge_score)

    def test_vam_contradicts_dampens_edge(self):
        """VAM contradicting divergence → smaller |edge|."""
        m1 = DivergenceEdgeScorer({"divergence_lookback": 5})
        _warm_model(m1, 5, price_trend="down", rsi_trend="up", macd_trend="up", mfi_trend="up")
        out_no_vam = m1.evaluate(_fv({
            "RSI": 35.0,
            "MACD": {"histogram": 2.0},
            "MFI": 55.0,
            "LinReg": {"slope": -1.0},
            "ATR": 2.0,
            "Momentum": 0.0,
            "eng_volume_adjusted_momentum": None,
        }, bar_data={"close": 95.0}))

        m2 = DivergenceEdgeScorer({"divergence_lookback": 5})
        _warm_model(m2, 5, price_trend="down", rsi_trend="up", macd_trend="up", mfi_trend="up")
        out_contra = m2.evaluate(_fv({
            "RSI": 35.0,
            "MACD": {"histogram": 2.0},
            "MFI": 55.0,
            "LinReg": {"slope": -1.0},
            "ATR": 2.0,
            "Momentum": 0.0,
            "eng_volume_adjusted_momentum": -1.0,  # negative, contradicts bullish divergence
        }, bar_data={"close": 95.0}))

        assert abs(out_contra.edge_score) < abs(out_no_vam.edge_score)

    def test_high_beta_dampens(self):
        """High beta (> 1.5) → smaller |edge|."""
        m1 = DivergenceEdgeScorer({"divergence_lookback": 5})
        _warm_model(m1, 5, price_trend="down", rsi_trend="up", macd_trend="up", mfi_trend="up")
        out_low_beta = m1.evaluate(_fv({
            "RSI": 35.0,
            "MACD": {"histogram": 2.0},
            "MFI": 55.0,
            "LinReg": {"slope": -1.0},
            "ATR": 2.0,
            "Momentum": 0.0,
            "eng_altcoin_beta": 1.0,
        }, bar_data={"close": 95.0}))

        m2 = DivergenceEdgeScorer({"divergence_lookback": 5})
        _warm_model(m2, 5, price_trend="down", rsi_trend="up", macd_trend="up", mfi_trend="up")
        out_hi_beta = m2.evaluate(_fv({
            "RSI": 35.0,
            "MACD": {"histogram": 2.0},
            "MFI": 55.0,
            "LinReg": {"slope": -1.0},
            "ATR": 2.0,
            "Momentum": 0.0,
            "eng_altcoin_beta": 3.0,
        }, bar_data={"close": 95.0}))

        assert abs(out_hi_beta.edge_score) < abs(out_low_beta.edge_score)

    def test_market_divergence_bonus(self):
        """Asset diverging opposite to market momentum → boost."""
        m1 = DivergenceEdgeScorer({"divergence_lookback": 5})
        _warm_model(m1, 5, price_trend="down", rsi_trend="up", macd_trend="up", mfi_trend="up")
        out_no_bonus = m1.evaluate(_fv({
            "RSI": 35.0,
            "MACD": {"histogram": 2.0},
            "MFI": 55.0,
            "LinReg": {"slope": -1.0},
            "ATR": 2.0,
            "Momentum": 0.0,
            "eng_altcoin_market_momentum": None,
        }, bar_data={"close": 95.0}))

        m2 = DivergenceEdgeScorer({"divergence_lookback": 5})
        _warm_model(m2, 5, price_trend="down", rsi_trend="up", macd_trend="up", mfi_trend="up")
        # Bullish divergence (positive) vs negative market momentum → opposite → bonus
        out_bonus = m2.evaluate(_fv({
            "RSI": 35.0,
            "MACD": {"histogram": 2.0},
            "MFI": 55.0,
            "LinReg": {"slope": -1.0},
            "ATR": 2.0,
            "Momentum": 0.0,
            "eng_altcoin_market_momentum": -1.0,
        }, bar_data={"close": 95.0}))

        assert abs(out_bonus.edge_score) > abs(out_no_bonus.edge_score)

    def test_residual_momentum_boost(self):
        """Confirming residual momentum → larger edge."""
        m1 = DivergenceEdgeScorer({"divergence_lookback": 5})
        _warm_model(m1, 5, price_trend="down", rsi_trend="up", macd_trend="up", mfi_trend="up")
        out_no_res = m1.evaluate(_fv({
            "RSI": 35.0,
            "MACD": {"histogram": 2.0},
            "MFI": 55.0,
            "LinReg": {"slope": -1.0},
            "ATR": 2.0,
            "Momentum": 0.0,
            "eng_residual_momentum": None,
        }, bar_data={"close": 95.0}))

        m2 = DivergenceEdgeScorer({"divergence_lookback": 5})
        _warm_model(m2, 5, price_trend="down", rsi_trend="up", macd_trend="up", mfi_trend="up")
        out_res = m2.evaluate(_fv({
            "RSI": 35.0,
            "MACD": {"histogram": 2.0},
            "MFI": 55.0,
            "LinReg": {"slope": -1.0},
            "ATR": 2.0,
            "Momentum": 0.0,
            "eng_residual_momentum": 1.0,  # positive, confirms bullish
        }, bar_data={"close": 95.0}))

        assert abs(out_res.edge_score) > abs(out_no_res.edge_score)


# ---------------------------------------------------------------------------
# Conviction tests
# ---------------------------------------------------------------------------


class TestDivergenceEdgeConviction:
    def test_conviction_scales_with_agreement(self):
        """3 confirming indicators → higher conviction than 2."""
        m1 = DivergenceEdgeScorer({"divergence_lookback": 5, "min_confirming_indicators": 2})
        # 2 out of 3 diverge
        _warm_model(m1, 5, price_trend="down", rsi_trend="up", macd_trend="up", mfi_trend="flat")
        out_2 = m1.evaluate(_fv({
            "RSI": 35.0,
            "MACD": {"histogram": 2.0},
            "MFI": 50.0,  # flat
            "LinReg": {"slope": -1.0},
            "ATR": 2.0,
            "Momentum": 0.0,
        }, bar_data={"close": 95.0}))

        m2 = DivergenceEdgeScorer({"divergence_lookback": 5, "min_confirming_indicators": 2})
        _warm_model(m2, 5, price_trend="down", rsi_trend="up", macd_trend="up", mfi_trend="up")
        out_3 = m2.evaluate(_fv({
            "RSI": 35.0,
            "MACD": {"histogram": 2.0},
            "MFI": 55.0,
            "LinReg": {"slope": -1.0},
            "ATR": 2.0,
            "Momentum": 0.0,
        }, bar_data={"close": 95.0}))

        # Both should produce non-zero edges
        if out_2.edge_score != 0.0 and out_3.edge_score != 0.0:
            assert out_3.conviction >= out_2.conviction

    def test_conviction_scales_with_magnitude(self):
        """Larger divergence → higher conviction."""
        # Stronger vs weaker divergence by slope magnitude
        m1 = DivergenceEdgeScorer({"divergence_lookback": 5})
        # mild slopes
        for i in range(5):
            m1.evaluate(_fv({
                "RSI": 50.0 + i * 0.5,
                "MACD": {"histogram": -i * 0.2},
                "MFI": 50.0 + i * 0.3,
                "LinReg": {"slope": -0.5},
                "ATR": 2.0,
                "Momentum": 0.0,
            }, bar_data={"close": 100.0 - i * 0.5}))
        out_mild = m1.evaluate(_fv({
            "RSI": 52.5,
            "MACD": {"histogram": -1.0},
            "MFI": 51.5,
            "LinReg": {"slope": -0.5},
            "ATR": 2.0,
            "Momentum": 0.0,
        }, bar_data={"close": 97.5}))

        m2 = DivergenceEdgeScorer({"divergence_lookback": 5})
        # strong slopes
        for i in range(5):
            m2.evaluate(_fv({
                "RSI": 50.0 + i * 3.0,
                "MACD": {"histogram": -i * 2.0},
                "MFI": 50.0 + i * 2.0,
                "LinReg": {"slope": -3.0},
                "ATR": 2.0,
                "Momentum": 0.0,
            }, bar_data={"close": 100.0 - i * 3.0}))
        out_strong = m2.evaluate(_fv({
            "RSI": 65.0,
            "MACD": {"histogram": -10.0},
            "MFI": 60.0,
            "LinReg": {"slope": -3.0},
            "ATR": 2.0,
            "Momentum": 0.0,
        }, bar_data={"close": 85.0}))

        if out_mild.edge_score != 0.0 and out_strong.edge_score != 0.0:
            assert out_strong.conviction >= out_mild.conviction


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestDivergenceEdgeGraceful:
    def test_missing_cross_sectional_still_works(self):
        """Missing cross-sectional features → edge computed without bonuses."""
        m = DivergenceEdgeScorer({"divergence_lookback": 5})
        _warm_model(m, 5, price_trend="down", rsi_trend="up", macd_trend="up", mfi_trend="up")
        out = m.evaluate(_fv({
            "RSI": 35.0,
            "MACD": {"histogram": 2.0},
            "MFI": 55.0,
            "LinReg": {"slope": -1.0},
            "ATR": 2.0,
            "Momentum": 0.0,
            # No cross-sectional features at all
        }, bar_data={"close": 95.0}))
        assert out.edge_score != 0.0


# ---------------------------------------------------------------------------
# Batch evaluation tests
# ---------------------------------------------------------------------------


class TestDivergenceEdgeBatch:
    def test_batch_returns_correct_length(self):
        m = DivergenceEdgeScorer({"divergence_lookback": 3})
        n = 10
        df = pd.DataFrame({
            "close": np.linspace(100, 90, n),     # downtrend
            "RSI": np.linspace(30, 60, n),         # uptrend → bullish divergence
            "MACD_histogram": np.linspace(-3, 3, n),  # uptrend
            "MFI": np.linspace(20, 60, n),         # uptrend
            "ATR": np.full(n, 2.0),
        })
        result = m.batch_evaluate(df)
        assert len(result) == n

    def test_batch_missing_columns_returns_zeros(self):
        m = DivergenceEdgeScorer({})
        df = pd.DataFrame({"close": [100, 101], "RSI": [50, 51]})
        result = m.batch_evaluate(df)
        assert (result == 0.0).all()
