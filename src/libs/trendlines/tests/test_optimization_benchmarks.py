"""Tests for trendlines optimization benchmark modules."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from app.trendlines.optimization.benchmarks import (
    fold_stability,
    longevity,
    penetration_gate,
    pivot_density,
    touch_accuracy,
)


# ---------------------------------------------------------------------------
# Helpers — synthetic trendlines
# ---------------------------------------------------------------------------

@dataclass
class FakeTrendline:
    slope: float
    intercept: float
    is_support: bool


def _make_test_df(n: int = 100, base: float = 100.0, noise: float = 1.0) -> pd.DataFrame:
    rng = np.random.RandomState(42)
    closes = base + np.cumsum(rng.randn(n) * noise)
    return pd.DataFrame({
        "open": closes - rng.rand(n) * 0.5,
        "high": closes + rng.rand(n) * noise,
        "low": closes - rng.rand(n) * noise,
        "close": closes,
        "volume": rng.rand(n) * 1000,
    })


# ---------------------------------------------------------------------------
# Tier 1: Longevity
# ---------------------------------------------------------------------------

class TestLongevity:
    def test_empty_lines(self):
        df = _make_test_df()
        result = longevity.compute([], df, 200)
        assert result["mean_longevity"] == 0.0
        assert result["n_lines"] == 0

    def test_empty_test_df(self):
        result = longevity.compute(
            [FakeTrendline(0.0, 50.0, True)],
            pd.DataFrame(),
            200,
        )
        assert result["mean_longevity"] == 0.0

    def test_perfect_support_survives(self):
        # Support line far below all closes → never penetrated → longevity = 1.0
        df = _make_test_df(50, base=100.0)
        line = FakeTrendline(slope=0.0, intercept=50.0, is_support=True)
        result = longevity.compute([line], df, 200)
        assert result["mean_longevity"] == 1.0
        assert result["n_lines"] == 1

    def test_immediately_penetrated_support(self):
        # Support line far above all closes → immediately penetrated
        df = _make_test_df(50, base=100.0)
        line = FakeTrendline(slope=0.0, intercept=200.0, is_support=True)
        result = longevity.compute([line], df, 200)
        assert result["mean_longevity"] < 0.2

    def test_resistance_survives(self):
        df = _make_test_df(50, base=100.0)
        line = FakeTrendline(slope=0.0, intercept=200.0, is_support=False)
        result = longevity.compute([line], df, 200)
        assert result["mean_longevity"] == 1.0


# ---------------------------------------------------------------------------
# Tier 2: Touch Accuracy
# ---------------------------------------------------------------------------

class TestTouchAccuracy:
    def test_empty_lines(self):
        df = _make_test_df()
        result = touch_accuracy.compute([], df, 200)
        assert result["touch_accuracy"] == 0.0
        assert result["total_touches"] == 0

    def test_no_touches_when_line_far(self):
        df = _make_test_df(50, base=100.0)
        line = FakeTrendline(slope=0.0, intercept=50.0, is_support=True)
        result = touch_accuracy.compute([line], df, 200)
        assert result["total_touches"] == 0

    def test_accuracy_bounded_0_1(self):
        df = _make_test_df(100, base=100.0, noise=2.0)
        # Line near the action — some touches expected
        median = df["close"].median()
        line = FakeTrendline(slope=0.0, intercept=median, is_support=True)
        result = touch_accuracy.compute([line], df, 200, slope_tolerance=5.0)
        assert 0.0 <= result["touch_accuracy"] <= 1.0


# ---------------------------------------------------------------------------
# Tier 3: Penetration Gate
# ---------------------------------------------------------------------------

class TestPenetrationGate:
    def test_empty_lines(self):
        df = _make_test_df()
        result = penetration_gate.compute([], df, 200)
        assert result["mean_pen_rate"] == 1.0
        assert result["passed_gate"] is False

    def test_no_penetration_passes_gate(self):
        df = _make_test_df(50, base=100.0)
        line = FakeTrendline(slope=0.0, intercept=50.0, is_support=True)
        result = penetration_gate.compute([line], df, 200)
        assert result["mean_pen_rate"] == 0.0
        assert result["passed_gate"] is True

    def test_gate_penalty_below_threshold(self):
        assert penetration_gate.gate_penalty(0.2, threshold=0.5) == 1.0

    def test_gate_penalty_soft(self):
        penalty = penetration_gate.gate_penalty(0.6, threshold=0.5, penalty_factor=3.0, soft=True)
        assert abs(penalty - 1.0 / 3.0) < 1e-6

    def test_gate_penalty_hard(self):
        penalty = penetration_gate.gate_penalty(0.6, threshold=0.5, soft=False)
        assert penalty == 0.0

    def test_gate_penalty_at_boundary(self):
        assert penetration_gate.gate_penalty(0.5, threshold=0.5) == 1.0


# ---------------------------------------------------------------------------
# Tier 4: Pivot Density
# ---------------------------------------------------------------------------

class TestPivotDensity:
    def test_below_min_is_zero(self):
        # 3 pivots in 100 bars = 3.0 density, but density_min=5.0 → score=0
        result = pivot_density.compute(3, 100, density_min=5.0)
        assert result["pivot_score"] == 0.0
        assert result["passed_constraint"] is False

    def test_in_optimal_range_is_one(self):
        # 15 pivots in 100 bars = 15.0 density, optimal range [8, 25] → score=1
        result = pivot_density.compute(15, 100, density_optimal_lo=8.0, density_optimal_hi=25.0)
        assert result["pivot_score"] == 1.0
        assert result["passed_constraint"] is True

    def test_ramp_up(self):
        # 5 pivots in 100 bars = 5.0 density, between min=2.0 and optimal_lo=8.0
        result = pivot_density.compute(5, 100, density_min=2.0, density_optimal_lo=8.0)
        assert 0.0 < result["pivot_score"] < 1.0

    def test_decay_above_optimal(self):
        # 35 pivots in 100 bars = 35.0 density, above optimal_hi=25.0
        result = pivot_density.compute(35, 100, density_optimal_hi=25.0)
        assert 0.0 < result["pivot_score"] < 1.0

    def test_tent_score_function(self):
        # density=2.0 at density_min=2.0 → 0
        assert pivot_density.tent_score(2.0, density_min=2.0, density_optimal_lo=8.0) == 0.0
        # density=8.0 at optimal_lo=8.0 → 1.0
        assert pivot_density.tent_score(8.0, density_optimal_lo=8.0, density_optimal_hi=25.0) == 1.0
        # density=25.0 at optimal_hi=25.0 → 1.0
        assert pivot_density.tent_score(25.0, density_optimal_lo=8.0, density_optimal_hi=25.0) == 1.0
        # density=50.0 at 2× optimal_hi=25.0 → 0
        assert pivot_density.tent_score(50.0, density_optimal_hi=25.0) == 0.0

    def test_density_field_returned(self):
        # 442 pivots in 2160 bars = 20.5 density
        result = pivot_density.compute(442, 2160)
        assert abs(result["density"] - 20.46) < 0.1

    def test_constraint_penalty_pass(self):
        assert pivot_density.constraint_penalty(0.5, min_score=0.3) == 1.0

    def test_constraint_penalty_fail(self):
        assert pivot_density.constraint_penalty(0.1, min_score=0.3, penalty=0.3) == 0.3


# ---------------------------------------------------------------------------
# Tier 5: Fold Stability
# ---------------------------------------------------------------------------

class TestFoldStability:
    def test_single_fold(self):
        result = fold_stability.compute([0.5])
        assert result["stability_score"] == 1.0
        assert result["fitness_cv"] == 0.0

    def test_identical_scores(self):
        result = fold_stability.compute([0.5, 0.5, 0.5])
        assert result["fitness_cv"] == 0.0
        assert result["stability_score"] == 1.0

    def test_high_variance(self):
        result = fold_stability.compute([0.1, 0.9, 0.1, 0.9])
        assert result["stability_score"] < 0.5
        assert result["fitness_cv"] > 0.5

    def test_stability_clamped(self):
        result = fold_stability.compute([0.001, 10.0])
        assert 0.0 <= result["stability_score"] <= 1.0

    def test_zero_mean(self):
        result = fold_stability.compute([0.0, 0.0, 0.0])
        # All zeros: cv would be undefined (0/0), defaults to 1.0
        assert result["fitness_cv"] == 1.0
        assert result["stability_score"] == 0.0
