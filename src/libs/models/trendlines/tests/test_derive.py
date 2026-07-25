"""Tests for derivation functions and AssetProfile."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from libs.models.trendlines.config.asset_profile import AssetProfile, _MIN_BARS_FOR_PROFILE
from libs.models.trendlines.config.derive import (
    compute_all_derived,
    derive_atr_window,
    derive_consecutive_penetration_bars,
    derive_flat_tol,
    derive_forward_lookahead_bars,
    derive_full_confidence_touches,
    derive_hold_bars,
    derive_min_history,
    derive_parallel_tol,
    derive_slope_accel_threshold,
    derive_slope_match_tol,
    derive_volume_lookback,
)


def _make_ohlcv(n_bars: int = 200, base_price: float = 100.0) -> pd.DataFrame:
    """Build synthetic OHLCV DataFrame for testing."""
    rng = np.random.default_rng(42)
    close = base_price + np.cumsum(rng.normal(0, 0.5, n_bars))
    high = close + rng.uniform(0.2, 1.0, n_bars)
    low = close - rng.uniform(0.2, 1.0, n_bars)
    opn = close + rng.normal(0, 0.3, n_bars)
    volume = rng.uniform(100, 1000, n_bars)
    idx = pd.date_range("2025-01-01", periods=n_bars, freq="1h")
    return pd.DataFrame(
        {"open": opn, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def _make_profile(tf: str = "1h", **overrides) -> AssetProfile:
    """Build a profile with sensible defaults, overridable for edge-case tests."""
    defaults = dict(
        tf_minutes=60,
        bar_duration_hours=1.0,
        mean_atr=2.5,
        mean_price=100.0,
        n_bars=200,
        median_touch_count=4.0,
        mean_slope_abs=0.03,
        slope_diff_std=0.015,
        hull_width_atr_p20=1.8,
    )
    defaults.update(overrides)
    return AssetProfile(**defaults)


# ── AssetProfile.from_dataframe ──────────────────────────────────────────


class TestAssetProfileFromDataframe:
    def test_basic_build(self):
        df = _make_ohlcv(200)
        profile = AssetProfile.from_dataframe(df, "1h")
        assert profile.tf_minutes == 60
        assert profile.bar_duration_hours == 1.0
        assert profile.mean_atr > 0
        assert profile.mean_price > 0
        assert profile.n_bars == 200

    def test_minimum_bars(self):
        df = _make_ohlcv(_MIN_BARS_FOR_PROFILE)
        profile = AssetProfile.from_dataframe(df, "1h")
        assert profile.n_bars == _MIN_BARS_FOR_PROFILE

    def test_insufficient_bars_raises(self):
        df = _make_ohlcv(_MIN_BARS_FOR_PROFILE - 1)
        with pytest.raises(ValueError, match="bars"):
            AssetProfile.from_dataframe(df, "1h")

    def test_missing_column_raises(self):
        df = _make_ohlcv(50)
        df = df.drop(columns=["high"])
        with pytest.raises(ValueError, match="high"):
            AssetProfile.from_dataframe(df, "1h")

    def test_different_timeframes(self):
        df = _make_ohlcv(200)
        p1h = AssetProfile.from_dataframe(df, "1h")
        p4h = AssetProfile.from_dataframe(df, "4h")
        assert p1h.tf_minutes == 60
        assert p4h.tf_minutes == 240
        assert p4h.bar_duration_hours == 4.0

    def test_to_dict_roundtrip(self):
        df = _make_ohlcv(200)
        profile = AssetProfile.from_dataframe(df, "1h")
        d = profile.to_dict()
        assert isinstance(d, dict)
        assert d["tf_minutes"] == 60
        assert "mean_atr" in d


# ── TF-derived functions ────────────────────────────────────────────────


class TestTfDerived:
    def test_hold_bars_1h(self):
        p = _make_profile(tf_minutes=60, bar_duration_hours=1.0)
        assert derive_hold_bars(p) == 3  # 3h / 1h = 3

    def test_hold_bars_15m(self):
        p = _make_profile(tf_minutes=15, bar_duration_hours=0.25)
        assert derive_hold_bars(p) == 12  # 3h / 0.25h = 12

    def test_hold_bars_4h(self):
        p = _make_profile(tf_minutes=240, bar_duration_hours=4.0)
        assert derive_hold_bars(p) == 1  # ceil(3/4) = 1

    def test_hold_bars_minimum_is_1(self):
        p = _make_profile(tf_minutes=1440, bar_duration_hours=24.0)
        assert derive_hold_bars(p) >= 1

    def test_volume_lookback_1h(self):
        p = _make_profile(tf_minutes=60, bar_duration_hours=1.0)
        assert derive_volume_lookback(p) == 20  # 20h / 1h = 20

    def test_volume_lookback_15m(self):
        p = _make_profile(tf_minutes=15, bar_duration_hours=0.25)
        assert derive_volume_lookback(p) == 80  # 20h / 0.25h = 80

    def test_volume_lookback_minimum_is_5(self):
        p = _make_profile(tf_minutes=1440, bar_duration_hours=24.0)
        assert derive_volume_lookback(p) >= 5

    def test_min_history_1h(self):
        p = _make_profile(tf_minutes=60, bar_duration_hours=1.0)
        assert derive_min_history(p) == 6  # 6h / 1h = 6

    def test_atr_window_1h(self):
        p = _make_profile(tf_minutes=60)
        result = derive_atr_window(p)
        # 14 days * 24 bars/day = 336
        assert result == 336

    def test_atr_window_4h(self):
        p = _make_profile(tf_minutes=240)
        result = derive_atr_window(p)
        # 14 days * 6 bars/day = 84
        assert result == 84

    def test_atr_window_minimum_is_5(self):
        p = _make_profile(tf_minutes=1440)
        assert derive_atr_window(p) >= 5

    def test_consecutive_penetration_bars(self):
        p = _make_profile(tf_minutes=60, bar_duration_hours=1.0)
        assert derive_consecutive_penetration_bars(p) == 3

    def test_forward_lookahead_bars(self):
        p = _make_profile(tf_minutes=60, bar_duration_hours=1.0)
        assert derive_forward_lookahead_bars(p) == 3


# ── Stats-derived functions ─────────────────────────────────────────────


class TestStatsDerived:
    def test_parallel_tol_normal(self):
        p = _make_profile(mean_atr=2.5, mean_price=100.0)
        result = derive_parallel_tol(p)
        assert result == pytest.approx(0.5 * 2.5 / 100.0)

    def test_parallel_tol_zero_price(self):
        p = _make_profile(mean_price=0.0)
        assert derive_parallel_tol(p) == 0.02  # fallback

    def test_parallel_tol_minimum(self):
        p = _make_profile(mean_atr=0.001, mean_price=100.0)
        assert derive_parallel_tol(p) >= 0.005

    def test_flat_tol_normal(self):
        p = _make_profile(mean_atr=2.5, mean_price=100.0)
        result = derive_flat_tol(p)
        assert result == pytest.approx(0.25 * 2.5 / 100.0)

    def test_flat_tol_zero_price(self):
        p = _make_profile(mean_price=0.0)
        assert derive_flat_tol(p) == 0.01

    def test_full_confidence_touches_with_median(self):
        p = _make_profile(median_touch_count=4.0)
        result = derive_full_confidence_touches(p, role="structural")
        assert result == pytest.approx(6.0)  # 4 * 1.5 = 6

    def test_full_confidence_touches_zero_median(self):
        p = _make_profile(median_touch_count=0.0, tf_minutes=60)
        result = derive_full_confidence_touches(p, role="structural")
        assert 3.0 <= result <= 8.0

    def test_full_confidence_touches_pattern_vs_structural(self):
        p = _make_profile(median_touch_count=0.0, tf_minutes=60)
        s = derive_full_confidence_touches(p, role="structural")
        pat = derive_full_confidence_touches(p, role="pattern")
        assert pat >= s  # pattern threshold is generally higher

    def test_slope_match_tol_with_data(self):
        p = _make_profile(mean_slope_abs=0.03)
        result = derive_slope_match_tol(p)
        assert result == pytest.approx(0.03 * 0.5)

    def test_slope_match_tol_zero_slope(self):
        p = _make_profile(mean_slope_abs=0.0, mean_atr=2.5, mean_price=100.0)
        result = derive_slope_match_tol(p)
        assert result == pytest.approx(2.5 / 100.0)

    def test_slope_accel_with_data(self):
        p = _make_profile(slope_diff_std=0.015)
        result = derive_slope_accel_threshold(p)
        assert result == pytest.approx(0.015 * 0.5)

    def test_slope_accel_zero_std(self):
        p = _make_profile(slope_diff_std=0.0, mean_atr=2.5, mean_price=100.0)
        result = derive_slope_accel_threshold(p)
        assert result > 0


# ── compute_all_derived ─────────────────────────────────────────────────


class TestComputeAllDerived:
    def test_returns_all_keys(self):
        p = _make_profile()
        d = compute_all_derived(p)
        expected_keys = {
            "hold_bars",
            "volume_lookback",
            "min_history",
            "atr_window",
            "consecutive_penetration_bars",
            "forward_lookahead_bars",
            "parallel_tol",
            "flat_tol",
            "full_confidence_touches_structural",
            "full_confidence_touches_pattern",
            "slope_match_tol",
            "slope_accel_threshold",
        }
        assert set(d.keys()) == expected_keys

    def test_all_values_positive(self):
        p = _make_profile()
        d = compute_all_derived(p)
        for key, val in d.items():
            assert val > 0, f"{key} should be > 0, got {val}"

    def test_bar_counts_are_ints(self):
        p = _make_profile()
        d = compute_all_derived(p)
        for key in ["hold_bars", "volume_lookback", "min_history", "atr_window",
                     "consecutive_penetration_bars", "forward_lookahead_bars"]:
            assert isinstance(d[key], int), f"{key} should be int"
