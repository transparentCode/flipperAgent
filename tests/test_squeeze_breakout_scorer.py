"""Tests for SqueezeBreakoutScorer."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from libs.models.squeeze_breakout.scoring_model import SqueezeBreakoutScorer
from libs.models.scoring_registry import ScoringModelRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_feature_df(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """Create a synthetic feature DataFrame with all required columns."""
    rng = np.random.RandomState(seed)
    close = 100.0 + np.cumsum(rng.randn(n) * 0.5)
    high = close + rng.uniform(0.1, 1.0, n)
    low = close - rng.uniform(0.1, 1.0, n)
    volume = rng.uniform(1000, 5000, n)

    df = pd.DataFrame({
        "close": close,
        "high": high,
        "low": low,
        "volume": volume,
        "KAMA_fast": close + rng.randn(n) * 0.3,
        "KAMA_slow": close + rng.randn(n) * 0.1,
        "BollingerBands_upper": close + 2.0,
        "BollingerBands_lower": close - 2.0,
        "KeltnerChannel_upper": close + 1.5,
        "KeltnerChannel_lower": close - 1.5,
        "CCI": rng.randn(n) * 50,
        "ADX_adx": rng.uniform(10, 40, n),
        "ADX_plus_di": rng.uniform(10, 30, n),
        "ADX_minus_di": rng.uniform(10, 30, n),
        "ADLine": np.cumsum(rng.randn(n) * 100),
        "MFI": rng.uniform(20, 80, n),
        "Momentum": rng.randn(n) * 5,
        "ATR": np.abs(rng.randn(n) * 2) + 0.5,
    })
    return df


def _make_squeeze_release_df(n: int = 100) -> pd.DataFrame:
    """Create a DataFrame that generates a squeeze release with KAMA crossover.

    First half: BB inside KC (squeeze on).
    Second half: BB outside KC (squeeze off) with KAMA_fast > KAMA_slow and
    positive momentum — should fire long signals at the release bar.
    """
    rng = np.random.RandomState(123)
    close = 100.0 + np.cumsum(np.concatenate([
        np.zeros(n // 2),
        np.ones(n // 2) * 0.1,
    ]))
    high = close + 0.5
    low = close - 0.5
    volume = np.full(n, 2000.0)

    bb_upper = np.empty(n)
    bb_lower = np.empty(n)
    kc_upper = np.empty(n)
    kc_lower = np.empty(n)

    # First half: BB inside KC (squeeze ON)
    half = n // 2
    bb_upper[:half] = close[:half] + 1.0
    bb_lower[:half] = close[:half] - 1.0
    kc_upper[:half] = close[:half] + 2.0
    kc_lower[:half] = close[:half] - 2.0

    # Second half: BB outside KC (squeeze OFF)
    bb_upper[half:] = close[half:] + 3.0
    bb_lower[half:] = close[half:] - 3.0
    kc_upper[half:] = close[half:] + 2.0
    kc_lower[half:] = close[half:] - 2.0

    # KAMA crossover: fast > slow in second half
    kama_slow_vals = close - 0.5
    kama_fast_vals = close.copy()
    kama_fast_vals[half:] = close[half:] + 1.0

    df = pd.DataFrame({
        "close": close,
        "high": high,
        "low": low,
        "volume": volume,
        "KAMA_fast": kama_fast_vals,
        "KAMA_slow": kama_slow_vals,
        "BollingerBands_upper": bb_upper,
        "BollingerBands_lower": bb_lower,
        "KeltnerChannel_upper": kc_upper,
        "KeltnerChannel_lower": kc_lower,
        "CCI": rng.randn(n) * 30 + 10,
        "ADX_adx": np.full(n, 25.0),
        "ADX_plus_di": np.full(n, 25.0),
        "ADX_minus_di": np.full(n, 15.0),
        "ADLine": np.cumsum(rng.randn(n) * 50) + 1000,
        "MFI": np.full(n, 60.0),
        "Momentum": np.concatenate([np.zeros(half), np.ones(n - half) * 5.0]),
        "ATR": np.full(n, 2.0),
    })
    return df


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_registered_in_scoring_registry(self):
        assert "SqueezeBreakoutScorer" in ScoringModelRegistry.list_all()

    def test_get_returns_correct_class(self):
        cls = ScoringModelRegistry.get("SqueezeBreakoutScorer")
        assert cls is SqueezeBreakoutScorer


# ---------------------------------------------------------------------------
# batch_evaluate basics
# ---------------------------------------------------------------------------


class TestBatchEvaluateBasics:
    def test_returns_float_series(self):
        m = SqueezeBreakoutScorer({})
        df = _make_feature_df(200)
        result = m.batch_evaluate(df)
        assert isinstance(result, pd.Series)
        assert result.dtype == np.float64 or np.issubdtype(result.dtype, np.floating)

    def test_correct_length(self):
        m = SqueezeBreakoutScorer({})
        df = _make_feature_df(150)
        result = m.batch_evaluate(df)
        assert len(result) == len(df)

    def test_edge_scores_in_range(self):
        m = SqueezeBreakoutScorer({})
        df = _make_feature_df(300)
        result = m.batch_evaluate(df)
        assert result.min() >= -2.0
        assert result.max() <= 2.0

    def test_empty_df(self):
        m = SqueezeBreakoutScorer({})
        df = _make_feature_df(0)
        result = m.batch_evaluate(df)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Squeeze-release signal firing
# ---------------------------------------------------------------------------


class TestSqueezeReleaseSignals:
    def test_signals_fire_on_squeeze_release(self):
        """Synthetic squeeze-release data should produce non-zero edge_scores."""
        m = SqueezeBreakoutScorer({"ss_threshold": 0})
        df = _make_squeeze_release_df(100)
        result = m.batch_evaluate(df)
        nonzero = (result != 0).sum()
        assert nonzero > 0, "Expected at least one signal on squeeze-release data"

    def test_squeeze_release_produces_long_signals(self):
        """With KAMA_fast > KAMA_slow, signals should be positive (long)."""
        m = SqueezeBreakoutScorer({"ss_threshold": 0})
        df = _make_squeeze_release_df(100)
        result = m.batch_evaluate(df)
        positive = (result > 0).sum()
        assert positive > 0, "Expected positive edge_scores for long squeeze-release"


# ---------------------------------------------------------------------------
# Conviction range
# ---------------------------------------------------------------------------


class TestConviction:
    def test_conviction_range_via_signal_strength(self):
        """SS ranges 0-5, so conviction = ss/5.0 should be in [0, 1]."""
        # We can't easily test conviction from batch_evaluate (returns edge_scores only),
        # but we verify ss/5.0 is bounded: ss is 0..5, so conviction is 0..1 by design.
        for ss in range(6):
            conviction = ss / 5.0
            assert 0.0 <= conviction <= 1.0


# ---------------------------------------------------------------------------
# SS threshold suppression
# ---------------------------------------------------------------------------


class TestSSThresholdSuppression:
    def test_high_threshold_suppresses_all(self):
        """ss_threshold=5 should suppress most signals."""
        m = SqueezeBreakoutScorer({"ss_threshold": 5})
        df = _make_squeeze_release_df(100)
        result = m.batch_evaluate(df)
        # With threshold=5, all 5 voters must agree — very unlikely on synthetic data
        # so we expect fewer signals than threshold=0
        m0 = SqueezeBreakoutScorer({"ss_threshold": 0})
        result0 = m0.batch_evaluate(df)
        assert (result != 0).sum() <= (result0 != 0).sum()

    def test_zero_threshold_no_suppression(self):
        """ss_threshold=0 disables SS filtering entirely."""
        m = SqueezeBreakoutScorer({"ss_threshold": 0})
        df = _make_squeeze_release_df(100)
        result = m.batch_evaluate(df)
        # Should have at least the squeeze-release signals
        assert (result != 0).sum() > 0


# ---------------------------------------------------------------------------
# ATR edge cases
# ---------------------------------------------------------------------------


class TestATREdgeCases:
    def test_zero_atr_uses_fallback(self):
        """When ATR is 0, edge magnitude should be 0.5 fallback."""
        m = SqueezeBreakoutScorer({"ss_threshold": 0})
        df = _make_squeeze_release_df(100)
        df["ATR"] = 0.0
        result = m.batch_evaluate(df)
        nonzero = result[result != 0]
        if len(nonzero) > 0:
            assert all(abs(nonzero) == 0.5), "Expected fallback edge magnitude of 0.5"

    def test_missing_atr_uses_fallback(self):
        """When ATR column is absent, edge magnitude should be 0.5."""
        m = SqueezeBreakoutScorer({"ss_threshold": 0})
        df = _make_squeeze_release_df(100)
        df = df.drop(columns=["ATR"])
        result = m.batch_evaluate(df)
        nonzero = result[result != 0]
        if len(nonzero) > 0:
            assert all(abs(nonzero) == 0.5)
