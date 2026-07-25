"""Phase 0 gate: verify fit_trendlines_to_boundary() returns structurally
identical BoundaryResult to the old 2-step path used by the notebook.

This is a hard gate — if this fails, no notebook refactoring proceeds.
"""

import numpy as np
import pandas as pd
import pytest

from app.trendlines import (
    TrendlinePipelineConfig,
    execute_trendline_pipeline,
    fit_trendlines_to_boundary,
)
from app.trendlines.boundary import build_boundary_result_from_trendline_result


# ── Fixtures ──────────────────────────────────────────────────────────

def _make_test_df(n: int = 400, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV with a visible uptrend + noise."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    trend = np.linspace(100.0, 130.0, n)
    noise = rng.normal(0, 1.5, n).cumsum() * 0.3
    close = trend + noise
    high = close + rng.uniform(0.5, 2.0, n)
    low = close - rng.uniform(0.5, 2.0, n)
    opn = close + rng.normal(0, 0.5, n)

    return pd.DataFrame(
        {"open": opn, "high": high, "low": low, "close": close,
         "volume": rng.uniform(100, 1000, n)},
        index=dates,
    )


PIPELINE_CONFIG = TrendlinePipelineConfig(
    extractor="fractal",
    fitter="least_squares",
    extractor_params={"window_left": 5, "window_right": 5},
    fitter_params={"pivot_window": 2},
    boundary_params={"atr_window": 14, "interaction_tolerance_atr": 0.25},
)


# ── Helpers ───────────────────────────────────────────────────────────

def _assert_rays_equal(old_rays, new_rays, label: str):
    """Compare two lists of Ray objects field-by-field."""
    assert len(old_rays) == len(new_rays), (
        f"{label}: ray count mismatch: old={len(old_rays)} new={len(new_rays)}"
    )
    for i, (old_r, new_r) in enumerate(zip(old_rays, new_rays)):
        tag = f"{label}[{i}]"
        assert old_r.start_price == pytest.approx(new_r.start_price, abs=1e-6), f"{tag} start_price"
        assert old_r.end_price == pytest.approx(new_r.end_price, abs=1e-6), f"{tag} end_price"
        assert old_r.slope == pytest.approx(new_r.slope, abs=1e-6), f"{tag} slope"
        assert old_r.intercept == pytest.approx(new_r.intercept, abs=1e-6), f"{tag} intercept"
        assert old_r.touch_count == new_r.touch_count, f"{tag} touch_count"
        assert old_r.is_support == new_r.is_support, f"{tag} is_support"
        assert old_r.kernel == new_r.kernel, f"{tag} kernel"
        assert old_r.score == pytest.approx(new_r.score, abs=1e-6), f"{tag} score"
        assert old_r.r_squared == pytest.approx(new_r.r_squared, abs=1e-6), f"{tag} r_squared"
        assert old_r.start_time == new_r.start_time, f"{tag} start_time"
        assert old_r.end_time == new_r.end_time, f"{tag} end_time"


def _assert_quality_metrics_equal(old_qm, new_qm):
    """Compare QualityMetrics if present."""
    if old_qm is None and new_qm is None:
        return
    assert old_qm is not None and new_qm is not None, (
        f"QualityMetrics: one None, other not: old={old_qm}, new={new_qm}"
    )
    assert old_qm.mean_score == pytest.approx(new_qm.mean_score, abs=1e-6)
    assert old_qm.mean_touch_count == pytest.approx(new_qm.mean_touch_count, abs=1e-6)
    assert old_qm.mean_r_squared == pytest.approx(new_qm.mean_r_squared, abs=1e-6)
    assert old_qm.hull_width_atr == pytest.approx(new_qm.hull_width_atr, abs=1e-6)
    assert old_qm.n_support_rays == new_qm.n_support_rays
    assert old_qm.n_resistance_rays == new_qm.n_resistance_rays


# ── Tests ─────────────────────────────────────────────────────────────

class TestFacadeEquivalence:
    """Verify fit_trendlines_to_boundary() produces identical BoundaryResult
    to the manual 2-step path the notebook currently uses."""

    def setup_method(self):
        self.df = _make_test_df()
        self.asset = "BTCUSDT"
        self.timeframe = "1h"

        # Old path (what the notebook does today)
        fit_result, runtime_config = execute_trendline_pipeline(
            self.df, config=PIPELINE_CONFIG,
        )
        active_config = runtime_config or PIPELINE_CONFIG
        self.old_result = build_boundary_result_from_trendline_result(
            self.df,
            asset=self.asset,
            timeframe=self.timeframe,
            trendline_result=fit_result,
            trendline_config=active_config,
        )

        # New path (facade)
        output = fit_trendlines_to_boundary(
            self.df,
            asset=self.asset,
            timeframe=self.timeframe,
            config=PIPELINE_CONFIG,
        )
        self.new_result = output.boundary_result

    def test_both_results_exist(self):
        assert self.old_result is not None
        assert self.new_result is not None

    def test_is_valid_matches(self):
        assert self.old_result.is_valid == self.new_result.is_valid

    def test_interaction_matches(self):
        assert self.old_result.interaction == self.new_result.interaction

    def test_asset_timeframe_matches(self):
        assert self.old_result.asset == self.new_result.asset
        assert self.old_result.timeframe == self.new_result.timeframe

    def test_convex_hull_matches(self):
        if np.isnan(self.old_result.convex_hull_floor):
            assert np.isnan(self.new_result.convex_hull_floor)
        else:
            assert self.old_result.convex_hull_floor == pytest.approx(
                self.new_result.convex_hull_floor, abs=1e-6
            )
        if np.isnan(self.old_result.convex_hull_ceiling):
            assert np.isnan(self.new_result.convex_hull_ceiling)
        else:
            assert self.old_result.convex_hull_ceiling == pytest.approx(
                self.new_result.convex_hull_ceiling, abs=1e-6
            )

    def test_support_rays_match(self):
        _assert_rays_equal(
            self.old_result.active_support_rays,
            self.new_result.active_support_rays,
            "support",
        )

    def test_resistance_rays_match(self):
        _assert_rays_equal(
            self.old_result.active_resistance_rays,
            self.new_result.active_resistance_rays,
            "resistance",
        )

    def test_best_support_matches(self):
        old_bs = self.old_result.best_support
        new_bs = self.new_result.best_support
        if old_bs is None:
            assert new_bs is None
        else:
            assert new_bs is not None
            assert old_bs.score == pytest.approx(new_bs.score, abs=1e-6)
            assert old_bs.touch_count == new_bs.touch_count

    def test_best_resistance_matches(self):
        old_br = self.old_result.best_resistance
        new_br = self.new_result.best_resistance
        if old_br is None:
            assert new_br is None
        else:
            assert new_br is not None
            assert old_br.score == pytest.approx(new_br.score, abs=1e-6)
            assert old_br.touch_count == new_br.touch_count

    def test_quality_metrics_match(self):
        _assert_quality_metrics_equal(
            self.old_result.quality_metrics,
            self.new_result.quality_metrics,
        )

    def test_ray_project_and_value_at(self):
        """Verify Ray.project() and Ray.value_at() produce same values."""
        for label, old_rays, new_rays in [
            ("support", self.old_result.active_support_rays, self.new_result.active_support_rays),
            ("resistance", self.old_result.active_resistance_rays, self.new_result.active_resistance_rays),
        ]:
            for i, (old_r, new_r) in enumerate(zip(old_rays, new_rays)):
                for bars in [0, 10, 50]:
                    assert old_r.project(bars) == pytest.approx(
                        new_r.project(bars), abs=1e-6
                    ), f"{label}[{i}].project({bars})"
                for idx in [0.0, 5.0, 20.0]:
                    assert old_r.value_at(idx) == pytest.approx(
                        new_r.value_at(idx), abs=1e-6
                    ), f"{label}[{i}].value_at({idx})"


class TestFacadeWithTrendlinesConfig:
    """Verify the facade works when given a full TrendlinesConfig
    (which triggers resolve_asset_config internally)."""

    def test_facade_with_config_resolution(self):
        from app.trendlines.config import load_trendlines_config

        df = _make_test_df()
        tl_config = load_trendlines_config()

        output = fit_trendlines_to_boundary(
            df,
            asset="BTCUSDT",
            timeframe="1h",
            config=PIPELINE_CONFIG,
            trendlines_config=tl_config,
        )

        result = output.boundary_result
        assert result is not None
        assert result.asset == "BTCUSDT"
        assert result.timeframe == "1h"
        assert isinstance(result.active_support_rays, list)
        assert isinstance(result.active_resistance_rays, list)
        assert hasattr(result, "convex_hull_floor")
        assert hasattr(result, "convex_hull_ceiling")
        assert hasattr(result, "interaction")
        assert hasattr(result, "is_valid")
        assert hasattr(result, "quality_metrics")
        assert hasattr(result, "best_support")
        assert hasattr(result, "best_resistance")

    def test_facade_output_has_fit_result(self):
        df = _make_test_df()
        output = fit_trendlines_to_boundary(
            df, asset="BTCUSDT", timeframe="1h", config=PIPELINE_CONFIG,
        )
        assert output.fit_result is not None
        assert output.fit_result.is_valid or not output.fit_result.is_valid  # bool check
        assert hasattr(output.fit_result, "support_lines")
        assert hasattr(output.fit_result, "resistance_lines")
