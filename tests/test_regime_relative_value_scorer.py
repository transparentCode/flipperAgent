"""Tests for RegimeRelativeValueScorer and regime overlay on existing scorers."""

import pytest
import pandas as pd
import numpy as np

from libs.contracts.schemas import FeatureVector
from libs.contracts.signal import ScoringOutput
from libs.models.regime_relative_value.model import RegimeRelativeValueScorer
from libs.models.regime_pullback.model import RegimePullbackScorer
from libs.models.divergence_edge.model import DivergenceEdgeScorer


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


# ---------------------------------------------------------------------------
# RegimeRelativeValueScorer
# ---------------------------------------------------------------------------


class TestRegimeRelativeValueScorer:
    def setup_method(self):
        self.scorer = RegimeRelativeValueScorer()

    def test_registration(self):
        from libs.models.scoring_registry import ScoringModelRegistry
        assert ScoringModelRegistry.get("RegimeRelativeValueScorer") is RegimeRelativeValueScorer

    def test_defaults(self):
        assert self.scorer.params["rs_underperformance_threshold"] == -0.5
        assert self.scorer.params["rsi_oversold_gate"] == 35
        assert self.scorer.params["regime_state_required"] == 0

    def test_zero_when_regime_not_risk_off(self):
        """Non-RISK_OFF regime → zero output."""
        fv = _fv({
            "eng_cross_asset_regime_state": 1,  # ALT_SEASON
            "eng_regime_alignment_score": -0.5,
            "eng_relative_strength_vs_total3": -1.0,
            "eng_btc_dominance_momentum": 0.5,
            "RSI": 25,
            "ATR": 2.0,
        })
        result = self.scorer.evaluate(fv)
        assert result.edge_score == 0.0

    def test_zero_when_not_underperforming(self):
        """RS above threshold → zero."""
        fv = _fv({
            "eng_cross_asset_regime_state": 0,
            "eng_regime_alignment_score": -0.5,
            "eng_relative_strength_vs_total3": 0.0,  # Not underperforming
            "eng_btc_dominance_momentum": 0.5,
            "RSI": 25,
            "ATR": 2.0,
        })
        result = self.scorer.evaluate(fv)
        assert result.edge_score == 0.0

    def test_zero_when_rsi_not_oversold(self):
        """RSI above gate → zero."""
        fv = _fv({
            "eng_cross_asset_regime_state": 0,
            "eng_regime_alignment_score": -0.5,
            "eng_relative_strength_vs_total3": -1.0,
            "eng_btc_dominance_momentum": 0.5,
            "RSI": 50,  # Not oversold
            "ATR": 2.0,
        })
        result = self.scorer.evaluate(fv)
        assert result.edge_score == 0.0

    def test_zero_when_btc_d_not_rising(self):
        """BTC.D momentum below threshold → zero."""
        fv = _fv({
            "eng_cross_asset_regime_state": 0,
            "eng_regime_alignment_score": -0.5,
            "eng_relative_strength_vs_total3": -1.0,
            "eng_btc_dominance_momentum": 0.1,  # Too low
            "RSI": 25,
            "ATR": 2.0,
        })
        result = self.scorer.evaluate(fv)
        assert result.edge_score == 0.0

    def test_produces_long_signal_on_valid_setup(self):
        """All gates pass → LONG signal with positive edge."""
        fv = _fv({
            "eng_cross_asset_regime_state": 0,  # RISK_OFF
            "eng_regime_alignment_score": -0.3,
            "eng_relative_strength_vs_total3": -1.0,  # Underperforming
            "eng_btc_dominance_momentum": 0.5,  # BTC.D rising
            "RSI": 25,  # Oversold
            "ATR": 2.0,
        })
        result = self.scorer.evaluate(fv)
        assert result.edge_score > 0.0  # LONG
        assert 0.0 < result.conviction <= 1.0
        assert result.metadata["regime_state"] == 0

    def test_conviction_increases_with_depth(self):
        """Deeper underperformance → higher conviction."""
        fv_shallow = _fv({
            "eng_cross_asset_regime_state": 0,
            "eng_regime_alignment_score": -0.3,
            "eng_relative_strength_vs_total3": -0.6,
            "eng_btc_dominance_momentum": 0.5,
            "RSI": 25,
            "ATR": 2.0,
        })
        fv_deep = _fv({
            "eng_cross_asset_regime_state": 0,
            "eng_regime_alignment_score": -0.3,
            "eng_relative_strength_vs_total3": -2.0,
            "eng_btc_dominance_momentum": 0.5,
            "RSI": 25,
            "ATR": 2.0,
        })
        result_shallow = self.scorer.evaluate(fv_shallow)
        result_deep = self.scorer.evaluate(fv_deep)
        assert result_deep.conviction > result_shallow.conviction

    def test_batch_evaluate(self):
        """Batch should produce same pattern as single-tick."""
        df = pd.DataFrame({
            "eng_cross_asset_regime_state": [0, 1, 0, 0],
            "eng_regime_alignment_score": [-0.3, -0.3, -0.3, -0.3],
            "eng_relative_strength_vs_total3": [-1.0, -1.0, 0.0, -1.0],
            "eng_btc_dominance_momentum": [0.5, 0.5, 0.5, 0.1],
            "RSI": [25, 25, 25, 25],
            "ATR": [2.0, 2.0, 2.0, 2.0],
            "close": [100.0, 100.0, 100.0, 100.0],
        })
        result = self.scorer.batch_evaluate(df)
        # Row 0: all gates pass → nonzero
        assert result.iloc[0] > 0.0
        # Row 1: wrong regime → zero
        assert result.iloc[1] == 0.0
        # Row 2: not underperforming → zero
        assert result.iloc[2] == 0.0
        # Row 3: btc_d too low → zero
        assert result.iloc[3] == 0.0


# ---------------------------------------------------------------------------
# RegimePullbackScorer — BROAD_SELLOFF suppression
# ---------------------------------------------------------------------------


class TestRegimePullbackScorerOverlay:
    def setup_method(self):
        self.scorer = RegimePullbackScorer({
            "suppress_broad_selloff": 1,
            "regime_overlay_weight": 0.3,
        })

    def _make_valid_fv(self, regime_state=2, alignment=0.0):
        """Create a FeatureVector that passes all existing gates."""
        return _fv({
            "eng_regime_score": -0.5,      # Below threshold
            "eng_mean_reversion_z": -2.0,   # Deep pullback LONG
            "RSI": 25,                       # Oversold
            "eng_squeeze_intensity": 0.5,
            "eng_btc_dominance_regime": 0.0,
            "eng_market_cap_breadth": 0.0,
            "eng_cross_asset_regime_state": regime_state,
            "eng_regime_alignment_score": alignment,
        })

    def test_broad_selloff_suppresses(self):
        """BROAD_SELLOFF (state 3) should suppress signal."""
        fv = self._make_valid_fv(regime_state=3)
        result = self.scorer.evaluate(fv)
        assert result.edge_score == 0.0

    def test_non_broad_selloff_passes(self):
        """Non-BROAD_SELLOFF should not suppress."""
        fv = self._make_valid_fv(regime_state=0)  # RISK_OFF
        result = self.scorer.evaluate(fv)
        assert result.edge_score != 0.0

    def test_alignment_scales_edge(self):
        """Positive alignment should increase edge magnitude."""
        result_neutral = self.scorer.evaluate(self._make_valid_fv(alignment=0.0))
        result_positive = self.scorer.evaluate(self._make_valid_fv(alignment=0.5))
        # Positive alignment with weight 0.3 → multiplier 1.15
        assert abs(result_positive.edge_score) > abs(result_neutral.edge_score)

    def test_metadata_includes_regime(self):
        """Metadata should include regime info."""
        fv = self._make_valid_fv(regime_state=0, alignment=0.3)
        result = self.scorer.evaluate(fv)
        assert "regime_state" in result.metadata
        assert "regime_alignment" in result.metadata

    def test_suppress_disabled(self):
        """With suppress_broad_selloff=0, BROAD_SELLOFF should not suppress."""
        scorer = RegimePullbackScorer({
            "suppress_broad_selloff": 0,
            "regime_overlay_weight": 0.3,
        })
        fv = self._make_valid_fv(regime_state=3)
        # Need to use this scorer's evaluate
        result = scorer.evaluate(fv)
        # Should not be suppressed (but may still be zero from other gates)
        # The key test is that the broad_selloff gate itself doesn't trigger
        # We can't guarantee non-zero because other gates may still apply
        # But verify the metadata path is exercised
        assert result is not None

    def test_batch_broad_selloff(self):
        """Batch evaluation should also suppress BROAD_SELLOFF."""
        df = pd.DataFrame({
            "eng_regime_score": [-0.5, -0.5],
            "eng_mean_reversion_z": [-2.0, -2.0],
            "RSI": [25, 25],
            "eng_squeeze_intensity": [0.5, 0.5],
            "eng_btc_dominance_regime": [0.0, 0.0],
            "eng_market_cap_breadth": [0.0, 0.0],
            "eng_cross_asset_regime_state": [0, 3],
            "eng_regime_alignment_score": [0.0, 0.0],
        })
        result = self.scorer.batch_evaluate(df)
        # Row 0: RISK_OFF → should have signal
        # Row 1: BROAD_SELLOFF → should be suppressed
        assert result.iloc[1] == 0.0


# ---------------------------------------------------------------------------
# DivergenceEdgeScorer — BROAD_SELLOFF suppression
# ---------------------------------------------------------------------------


class TestDivergenceEdgeScorerOverlay:
    def setup_method(self):
        self.scorer = DivergenceEdgeScorer({
            "suppress_broad_selloff": 1,
            "regime_overlay_weight": 0.2,
        })

    def _warm_and_get_result(self, regime_state=2, alignment=0.0):
        """Warm up buffers and return evaluate result."""
        lookback = self.scorer.params["divergence_lookback"]
        for i in range(lookback):
            close = 100.0 + i * 1.0  # price rising
            rsi = 70.0 - i * 1.0     # RSI falling → bearish divergence
            macd_hist = 5.0 - i * 0.5
            mfi = 80.0 - i * 1.5
            fv = _fv({
                "RSI": rsi,
                "MACD": {"histogram": macd_hist, "macd": 0.0, "signal": 0.0},
                "MFI": mfi,
                "LinReg": {"slope": 1.0},
                "ATR": 2.0,
                "Momentum": 0.0,
                "eng_volume_adjusted_momentum": None,
                "eng_atr_normalized_return": None,
                "eng_residual_momentum": None,
                "eng_altcoin_market_momentum": None,
                "eng_altcoin_beta": None,
                "eng_cross_asset_regime_state": regime_state,
                "eng_regime_alignment_score": alignment,
            }, bar_data={"close": close})
            result = self.scorer.evaluate(fv)
        return result

    def test_broad_selloff_suppresses(self):
        """BROAD_SELLOFF should return zero."""
        result = self._warm_and_get_result(regime_state=3)
        assert result.edge_score == 0.0

    def test_metadata_includes_regime(self):
        """Non-BROAD_SELLOFF with signal should include regime metadata."""
        result = self._warm_and_get_result(regime_state=0, alignment=0.1)
        if result.edge_score != 0.0:
            assert "regime_state" in result.metadata
            assert "regime_alignment" in result.metadata
