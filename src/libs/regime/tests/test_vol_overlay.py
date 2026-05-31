"""Tests for VolOverlay."""

import numpy as np
import pandas as pd
import pytest

from app.regime.vol_overlay import VolConfig, VolOverlay
from app.regime.models import VolState


def _make_df(n=500, seed=42):
    np.random.seed(seed)
    close = 100 + np.random.randn(n).cumsum()
    return pd.DataFrame({"close": close})


class TestVolOverlay:
    def test_returns_vol_state(self):
        overlay = VolOverlay()
        state = overlay.compute(_make_df())
        assert isinstance(state, VolState)

    def test_vol_regime_is_valid(self):
        overlay = VolOverlay()
        state = overlay.compute(_make_df())
        assert state.vol_regime in ("LOW_VOL", "HIGH_VOL")

    def test_percentile_in_range(self):
        overlay = VolOverlay()
        state = overlay.compute(_make_df())
        assert 0.0 <= state.vol_percentile <= 100.0

    def test_high_vol_returns_high_regime(self):
        """Spike in volatility should push regime to HIGH_VOL."""
        np.random.seed(0)
        # Low vol data followed by extreme spike
        close = list(100 + np.random.randn(800) * 0.1)
        close += list(100 + np.random.randn(200) * 10.0)
        df = pd.DataFrame({"close": close})
        overlay = VolOverlay(VolConfig(lookback=20, high_percentile=70, rank_window=1000))
        state = overlay.compute(df)
        assert state.vol_regime == "HIGH_VOL"

    def test_series_same_length_as_input(self):
        overlay = VolOverlay()
        df = _make_df()
        result = overlay.compute_series(df)
        assert len(result) == len(df)
        assert "vol_percentile" in result.columns
        assert "vol_regime" in result.columns

    def test_insufficient_data_returns_default(self):
        overlay = VolOverlay()
        df = pd.DataFrame({"close": [100.0]})
        state = overlay.compute(df)
        assert state.vol_percentile == 50.0
