"""Tests for RegimePullbackScorer."""

from __future__ import annotations

import pytest
import pandas as pd
import numpy as np

from libs.contracts.schemas import FeatureVector
from libs.contracts.signal import ScoringOutput
from libs.models.regime_pullback.model import RegimePullbackScorer


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


def _base_features(**overrides) -> dict:
    """Return features that pass all gates (ranging regime, deep pullback LONG, RSI confirms)."""
    base = {
        "eng_regime_score": -0.5,       # strongly ranging
        "eng_mean_reversion_z": -2.0,   # deep below KAMA → LONG
        "RSI": 30,                       # below oversold gate (40)
        "eng_squeeze_intensity": 0.5,
        "eng_btc_dominance_regime": 0.0,
        "eng_market_cap_breadth": 0.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Gate tests
# ---------------------------------------------------------------------------


class TestRegimePullbackGates:
    def test_ranging_regime_deep_pullback_rsi_confirms(self):
        """All gates pass → edge_score != 0."""
        m = RegimePullbackScorer({})
        out = m.evaluate(_fv(_base_features()))
        assert out.edge_score != 0.0
        assert out.conviction > 0.0

    def test_trending_regime_blocked(self):
        """ADX high (regime_score > threshold) → edge=0."""
        m = RegimePullbackScorer({})
        out = m.evaluate(_fv(_base_features(eng_regime_score=0.5)))
        assert out.edge_score == 0.0
        assert out.conviction == 0.0

    def test_shallow_pullback_blocked(self):
        """z < min_z_depth → edge=0."""
        m = RegimePullbackScorer({})
        out = m.evaluate(_fv(_base_features(eng_mean_reversion_z=-0.5)))
        assert out.edge_score == 0.0

    def test_rsi_not_confirming_long_blocked(self):
        """LONG direction but RSI too high → edge=0."""
        m = RegimePullbackScorer({})
        out = m.evaluate(_fv(_base_features(RSI=50)))
        assert out.edge_score == 0.0

    def test_rsi_not_confirming_short_blocked(self):
        """SHORT direction but RSI too low → edge=0."""
        m = RegimePullbackScorer({})
        # Positive z → SHORT, but RSI < overbought_gate
        out = m.evaluate(_fv(_base_features(eng_mean_reversion_z=2.0, RSI=55)))
        assert out.edge_score == 0.0

    def test_missing_regime_score(self):
        m = RegimePullbackScorer({})
        out = m.evaluate(_fv(_base_features(eng_regime_score=None)))
        assert out.edge_score == 0.0

    def test_missing_mr_z(self):
        m = RegimePullbackScorer({})
        feats = _base_features()
        del feats["eng_mean_reversion_z"]
        out = m.evaluate(_fv(feats))
        assert out.edge_score == 0.0

    def test_missing_rsi(self):
        m = RegimePullbackScorer({})
        feats = _base_features()
        del feats["RSI"]
        out = m.evaluate(_fv(feats))
        assert out.edge_score == 0.0


# ---------------------------------------------------------------------------
# Direction tests
# ---------------------------------------------------------------------------


class TestRegimePullbackDirection:
    def test_long_direction(self):
        """Negative z → price below KAMA → LONG → positive edge_score."""
        m = RegimePullbackScorer({})
        out = m.evaluate(_fv(_base_features(eng_mean_reversion_z=-2.0, RSI=30)))
        assert out.edge_score > 0.0

    def test_short_direction(self):
        """Positive z → price above KAMA → SHORT → negative edge_score."""
        m = RegimePullbackScorer({})
        out = m.evaluate(_fv(_base_features(eng_mean_reversion_z=2.0, RSI=65)))
        assert out.edge_score < 0.0


# ---------------------------------------------------------------------------
# Edge magnitude tests
# ---------------------------------------------------------------------------


class TestRegimePullbackMagnitude:
    def test_squeeze_bonus_increases_edge(self):
        """Deeper squeeze (lower intensity) → larger |edge|."""
        m = RegimePullbackScorer({})
        out_no_squeeze = m.evaluate(_fv(_base_features(eng_squeeze_intensity=1.0)))
        out_squeeze = m.evaluate(_fv(_base_features(eng_squeeze_intensity=0.2)))
        assert abs(out_squeeze.edge_score) > abs(out_no_squeeze.edge_score)

    def test_btc_dom_penalty_alt_long(self):
        """High BTC.D penalizes altcoin LONG trades."""
        m = RegimePullbackScorer({})
        out_no_dom = m.evaluate(_fv(_base_features(eng_btc_dominance_regime=0.0), asset="ETHUSDT"))
        out_hi_dom = m.evaluate(_fv(_base_features(eng_btc_dominance_regime=1.0), asset="ETHUSDT"))
        assert abs(out_hi_dom.edge_score) < abs(out_no_dom.edge_score)

    def test_btc_dom_no_penalty_btcusdt(self):
        """BTCUSDT should not get BTC dominance penalty."""
        m = RegimePullbackScorer({})
        out = m.evaluate(_fv(_base_features(eng_btc_dominance_regime=2.0), asset="BTCUSDT"))
        # Penalty should not apply
        out_zero_dom = m.evaluate(_fv(_base_features(eng_btc_dominance_regime=0.0), asset="BTCUSDT"))
        assert abs(out.edge_score) == pytest.approx(abs(out_zero_dom.edge_score))

    def test_breadth_supportive(self):
        """Positive market breadth → larger edge."""
        m = RegimePullbackScorer({})
        out_neutral = m.evaluate(_fv(_base_features(eng_market_cap_breadth=0.0)))
        out_broad = m.evaluate(_fv(_base_features(eng_market_cap_breadth=1.0)))
        assert abs(out_broad.edge_score) > abs(out_neutral.edge_score)


# ---------------------------------------------------------------------------
# Conviction tests
# ---------------------------------------------------------------------------


class TestRegimePullbackConviction:
    def test_conviction_scales_with_depth(self):
        """Deeper z → higher conviction."""
        m = RegimePullbackScorer({})
        out_shallow = m.evaluate(_fv(_base_features(eng_mean_reversion_z=-1.5, RSI=30)))
        out_deep = m.evaluate(_fv(_base_features(eng_mean_reversion_z=-3.0, RSI=30)))
        assert out_deep.conviction > out_shallow.conviction

    def test_conviction_capped_at_1(self):
        """Extreme z → conviction <= 1.0."""
        m = RegimePullbackScorer({})
        out = m.evaluate(_fv(_base_features(eng_mean_reversion_z=-10.0, eng_regime_score=-2.0, RSI=10)))
        assert out.conviction <= 1.0


# ---------------------------------------------------------------------------
# Batch evaluation tests
# ---------------------------------------------------------------------------


class TestRegimePullbackBatch:
    def test_batch_returns_correct_length(self):
        m = RegimePullbackScorer({})
        df = pd.DataFrame({
            "eng_regime_score": [-0.5, -0.5, 0.5],
            "eng_mean_reversion_z": [-2.0, -2.0, -0.3],
            "RSI": [30, 30, 50],
            "eng_squeeze_intensity": [0.5, 0.5, 0.5],
            "eng_market_cap_breadth": [0.0, 0.0, 0.0],
        })
        result = m.batch_evaluate(df)
        assert len(result) == len(df)

    def test_batch_gating(self):
        """Rows that fail gates should have edge_score=0."""
        m = RegimePullbackScorer({})
        df = pd.DataFrame({
            "eng_regime_score": [-0.5, 0.5],     # second row: trending → gate fail
            "eng_mean_reversion_z": [-2.0, -2.0],
            "RSI": [30, 30],
        })
        result = m.batch_evaluate(df)
        assert result.iloc[0] != 0.0
        assert result.iloc[1] == 0.0


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestRegimePullbackGraceful:
    def test_missing_optional_features_still_works(self):
        """Missing eng_squeeze_intensity etc → edge still computed."""
        m = RegimePullbackScorer({})
        feats = {
            "eng_regime_score": -0.5,
            "eng_mean_reversion_z": -2.0,
            "RSI": 30,
            # No squeeze, breadth, btc_dom
        }
        out = m.evaluate(_fv(feats))
        assert out.edge_score != 0.0
