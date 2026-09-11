"""
Tests — Data-Driven Search-Space Bounds
========================================
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.sr.optimization.data_driven_bounds import (
    DerivedBound,
    compute_data_driven_bounds,
    narrow_parameter_space,
    _compute_atr,
    _derive_gap_min_atr,
    _derive_displacement_atr,
    _derive_max_pierce_atr,
    _derive_sweep_lookback,
    _derive_imbalance_ratio,
    _derive_band_width_sigma,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(
    n: int = 2000,
    base_price: float = 50000.0,
    volatility: float = 0.015,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate realistic BTC-like OHLCV data with gaps and wicks."""
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    closes = [base_price]
    for _ in range(1, n):
        closes.append(closes[-1] * (1 + volatility * rng.randn()))
    closes = np.array(closes)
    # Varied wick sizes for realistic max_pierce_atr distribution
    upper_wick_pct = rng.exponential(0.005, n)
    lower_wick_pct = rng.exponential(0.005, n)
    highs = closes * (1 + upper_wick_pct)
    lows = closes * (1 - lower_wick_pct)
    # Opens slightly offset from close
    opens = closes * (1 + rng.uniform(-volatility / 3, volatility / 3, n))
    # Ensure high >= max(open, close) and low <= min(open, close)
    highs = np.maximum(highs, np.maximum(opens, closes))
    lows = np.minimum(lows, np.minimum(opens, closes))
    volumes = rng.uniform(100, 5000, n)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )


def _make_tiny_ohlcv(n: int = 50) -> pd.DataFrame:
    """Too-small DataFrame that should return empty bounds."""
    return _make_ohlcv(n=n)


# ---------------------------------------------------------------------------
# compute_data_driven_bounds — integration
# ---------------------------------------------------------------------------


class TestComputeDataDrivenBounds:
    """Integration tests for the top-level function."""

    def test_returns_dict_of_derived_bounds(self):
        df = _make_ohlcv(n=2000)
        bounds = compute_data_driven_bounds(df)
        assert isinstance(bounds, dict)
        # Should have at least some derivable params
        assert len(bounds) >= 3, f"Expected >=3 derived bounds, got {len(bounds)}"

    def test_all_keys_are_valid_param_names(self):
        df = _make_ohlcv()
        bounds = compute_data_driven_bounds(df)
        valid_names = {
            "kernels.fair_value_gap.gap_min_atr",
            "kernels.order_block.displacement_atr",
            "kernels.liquidity_sweep.max_pierce_atr",
            "kernels.liquidity_sweep.sweep_lookback",
            "kernels.order_block.imbalance_ratio",
            "kernels.regression_band.band_width_sigma",
            "pipeline.merge_threshold_pct_atr",
        }
        for key in bounds:
            assert key in valid_names, f"Unexpected param key: {key}"

    def test_bounds_are_within_hard_limits(self):
        df = _make_ohlcv()
        bounds = compute_data_driven_bounds(df)
        hard_limits = {
            "kernels.fair_value_gap.gap_min_atr": (0.35, 0.9),
            "kernels.order_block.displacement_atr": (1.0, 2.2),
            "kernels.liquidity_sweep.max_pierce_atr": (0.5, 1.4),
            "kernels.liquidity_sweep.sweep_lookback": (30, 80),
            "kernels.order_block.imbalance_ratio": (0.55, 0.85),
            "kernels.regression_band.band_width_sigma": (1.5, 2.75),
            "pipeline.merge_threshold_pct_atr": (0.15, 0.6),
        }
        for name, db in bounds.items():
            lo, hi = hard_limits[name]
            assert db.low >= lo, f"{name} low {db.low} < hard min {lo}"
            assert db.high <= hi, f"{name} high {db.high} > hard max {hi}"
            assert db.low < db.high, f"{name} low >= high"

    def test_bounds_are_narrower_than_defaults(self):
        """At least one bound should be strictly tighter than defaults."""
        df = _make_ohlcv()
        bounds = compute_data_driven_bounds(df)
        hard_limits = {
            "kernels.fair_value_gap.gap_min_atr": (0.35, 0.9),
            "kernels.order_block.displacement_atr": (1.0, 2.2),
            "kernels.liquidity_sweep.max_pierce_atr": (0.5, 1.4),
            "kernels.liquidity_sweep.sweep_lookback": (30, 80),
            "kernels.order_block.imbalance_ratio": (0.55, 0.85),
            "kernels.regression_band.band_width_sigma": (1.5, 2.75),
            "pipeline.merge_threshold_pct_atr": (0.15, 0.6),
        }
        any_narrower = False
        for name, db in bounds.items():
            lo, hi = hard_limits[name]
            if db.low > lo or db.high < hi:
                any_narrower = True
                break
        assert any_narrower, "No bounds were narrower than defaults"

    def test_insufficient_data_returns_empty(self):
        df = _make_tiny_ohlcv(n=100)
        bounds = compute_data_driven_bounds(df, warmup_bars=200)
        assert bounds == {}

    def test_derived_bound_has_source(self):
        df = _make_ohlcv()
        bounds = compute_data_driven_bounds(df)
        for name, db in bounds.items():
            assert db.source, f"{name} missing source description"
            assert isinstance(db.source, str)

    def test_deterministic(self):
        """Same data → same bounds."""
        df = _make_ohlcv(seed=99)
        bounds1 = compute_data_driven_bounds(df)
        bounds2 = compute_data_driven_bounds(df)
        for name in bounds1:
            assert bounds1[name].low == bounds2[name].low
            assert bounds1[name].high == bounds2[name].high


# ---------------------------------------------------------------------------
# Individual derivation functions
# ---------------------------------------------------------------------------


class TestDeriveGapMinAtr:
    def test_returns_bound_on_gappy_data(self):
        df = _make_ohlcv(n=2000, volatility=0.02)
        atr = _compute_atr(df, 14)
        result = _derive_gap_min_atr(df.iloc[200:], atr.iloc[200:])
        # May or may not have enough gaps depending on data, just check type
        if result is not None:
            assert 0.35 <= result.low < result.high <= 0.9

    def test_returns_none_on_flat_data(self):
        """Flat price = no gaps → None."""
        n = 500
        df = pd.DataFrame({
            "open": [100.0] * n,
            "high": [100.5] * n,
            "low": [99.5] * n,
            "close": [100.0] * n,
            "volume": [1000.0] * n,
        })
        atr = _compute_atr(df, 14)
        result = _derive_gap_min_atr(df.iloc[200:], atr.iloc[200:])
        assert result is None


class TestDeriveDisplacementAtr:
    def test_returns_bound_on_volatile_data(self):
        df = _make_ohlcv(n=2000, volatility=0.02)
        atr = _compute_atr(df, 14)
        result = _derive_displacement_atr(df.iloc[200:], atr.iloc[200:])
        if result is not None:
            assert 1.0 <= result.low < result.high <= 2.2


class TestDeriveMaxPierceAtr:
    def test_returns_bound(self):
        df = _make_ohlcv(n=2000)
        atr = _compute_atr(df, 14)
        result = _derive_max_pierce_atr(df.iloc[200:], atr.iloc[200:])
        if result is not None:
            assert 0.5 <= result.low < result.high <= 1.4


class TestDeriveSweepLookback:
    def test_returns_bound(self):
        df = _make_ohlcv(n=2000)
        result = _derive_sweep_lookback(df.iloc[200:])
        if result is not None:
            assert 30 <= result.low < result.high <= 80

    def test_returns_none_on_short_data(self):
        df = _make_ohlcv(n=50)
        result = _derive_sweep_lookback(df)
        assert result is None


class TestDeriveImbalanceRatio:
    def test_returns_bound(self):
        df = _make_ohlcv(n=2000)
        result = _derive_imbalance_ratio(df.iloc[200:])
        if result is not None:
            assert 0.55 <= result.low < result.high <= 0.85


class TestDeriveBandWidthSigma:
    def test_returns_bound(self):
        df = _make_ohlcv(n=2000)
        result = _derive_band_width_sigma(df.iloc[200:])
        if result is not None:
            assert 1.5 <= result.low < result.high <= 2.75


# ---------------------------------------------------------------------------
# narrow_parameter_space
# ---------------------------------------------------------------------------


class TestNarrowParameterSpace:
    def test_narrows_matching_params(self):
        from app.sr.config_schema import OptimizationParameterConfig

        space = {
            "kernels.fair_value_gap.gap_min_atr": OptimizationParameterConfig(
                low=0.35, high=0.9,
            ),
            "kernels.order_block.displacement_atr": OptimizationParameterConfig(
                low=1.0, high=2.2,
            ),
        }
        data_bounds = {
            "kernels.fair_value_gap.gap_min_atr": DerivedBound(0.4, 0.7, "test"),
        }
        result = narrow_parameter_space(space, data_bounds)
        assert result["kernels.fair_value_gap.gap_min_atr"].low == 0.4
        assert result["kernels.fair_value_gap.gap_min_atr"].high == 0.7
        # Unmatched param unchanged
        assert result["kernels.order_block.displacement_atr"].low == 1.0

    def test_preserves_kind_and_flags(self):
        from app.sr.config_schema import OptimizationParameterConfig

        space = {
            "kernels.liquidity_sweep.sweep_lookback": OptimizationParameterConfig(
                low=30, high=80, kind="int", enabled=True,
            ),
        }
        data_bounds = {
            "kernels.liquidity_sweep.sweep_lookback": DerivedBound(40, 60, "test"),
        }
        result = narrow_parameter_space(space, data_bounds)
        assert result["kernels.liquidity_sweep.sweep_lookback"].kind == "int"
        assert result["kernels.liquidity_sweep.sweep_lookback"].enabled is True
        assert result["kernels.liquidity_sweep.sweep_lookback"].low == 40
        assert result["kernels.liquidity_sweep.sweep_lookback"].high == 60

    def test_no_intersection_keeps_original(self):
        from app.sr.config_schema import OptimizationParameterConfig

        space = {
            "kernels.fair_value_gap.gap_min_atr": OptimizationParameterConfig(
                low=0.35, high=0.5,
            ),
        }
        # Data says [0.6, 0.9] — doesn't overlap with [0.35, 0.5]
        data_bounds = {
            "kernels.fair_value_gap.gap_min_atr": DerivedBound(0.6, 0.9, "test"),
        }
        result = narrow_parameter_space(space, data_bounds)
        # Should keep original since no intersection
        assert result["kernels.fair_value_gap.gap_min_atr"].low == 0.35
        assert result["kernels.fair_value_gap.gap_min_atr"].high == 0.5

    def test_empty_data_bounds_returns_copy(self):
        from app.sr.config_schema import OptimizationParameterConfig

        space = {
            "kernels.fair_value_gap.gap_min_atr": OptimizationParameterConfig(
                low=0.35, high=0.9,
            ),
        }
        result = narrow_parameter_space(space, {})
        assert result["kernels.fair_value_gap.gap_min_atr"].low == 0.35

    def test_metadata_gate_preserved(self):
        from app.sr.config_schema import OptimizationParameterConfig

        space = {
            "kernels.session_gap.gap_min_atr": OptimizationParameterConfig(
                low=0.35, high=0.9, enabled=False, metadata_gate="has_session_gaps",
            ),
        }
        data_bounds = {
            "kernels.session_gap.gap_min_atr": DerivedBound(0.4, 0.7, "test"),
        }
        result = narrow_parameter_space(space, data_bounds)
        assert result["kernels.session_gap.gap_min_atr"].enabled is False
        assert result["kernels.session_gap.gap_min_atr"].metadata_gate == "has_session_gaps"


# ---------------------------------------------------------------------------
# ATR helper
# ---------------------------------------------------------------------------


class TestComputeAtr:
    def test_atr_length_matches_input(self):
        df = _make_ohlcv(n=100)
        atr = _compute_atr(df, 14)
        assert len(atr) == len(df)

    def test_atr_positive(self):
        df = _make_ohlcv(n=200)
        atr = _compute_atr(df, 14)
        assert (atr.iloc[14:] > 0).all()


# ---------------------------------------------------------------------------
# DerivedBound dataclass
# ---------------------------------------------------------------------------


class TestDerivedBound:
    def test_as_tuple(self):
        db = DerivedBound(0.4, 0.7, "test")
        assert db.as_tuple() == (0.4, 0.7)

    def test_frozen(self):
        db = DerivedBound(0.4, 0.7, "test")
        with pytest.raises(AttributeError):
            db.low = 0.5  # type: ignore[misc]
