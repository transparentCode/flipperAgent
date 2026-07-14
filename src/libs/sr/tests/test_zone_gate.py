"""Tests for the pipeline zone gate (min_emit_strength + max_new_zones_per_bar)."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from app.sr.models import CandidateLevel, LevelFeatureVector, LevelType, ScoredLevel


def _make_scored_level(strength: float, price: float = 100.0) -> ScoredLevel:
    """Create a minimal ScoredLevel with the given strength."""
    candidate = CandidateLevel(
        center_price=price,
        lower_bound=price - 1.0,
        upper_bound=price + 1.0,
        level_type=LevelType.SUPPORT,
        kernel_name="pivot_hl",
        timeframe="1h",
        raw_score=strength,
        metadata={},
        timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        atr_at_detection=10.0,
    )
    features = LevelFeatureVector(kernel_agreement=1)
    return ScoredLevel(
        candidate=candidate,
        features=features,
        strength=strength,
        confidence=0.5,
        contributing_kernels=["pivot_hl"],
        ensemble_method="weighted_average",
    )


class TestZoneGate:
    """Unit tests for _apply_zone_gate in SRv2Pipeline."""

    def _make_pipeline(self, min_emit_strength=0.5, max_new_zones_per_bar=5):
        from app.sr.config_schema import (
            SRResolvedConfig, PipelineConfig, EnsembleConfig,
            LifecycleConfig, EnhancementConfig,
            RegimeConfig, RuleDerivedConfig,
        )
        from app.sr.models import AssetMetadata, RuleDerivedParams
        from app.sr.pipeline import SRv2Pipeline
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.volume_poc  # noqa: F401

        metadata = AssetMetadata(
            profile="crypto", trading_hours_per_day=24.0,
            trading_days_per_week=7, has_session_gaps=False,
            gap_breakout_policy="gap_ignored", gap_escalation_atr=999.0,
            session_lookback_hours=[24, 168, 720],
            round_number_mode="decimal", ex_dividend_filter=False,
            continuous_market=True,
        )
        rule_derived = RuleDerivedParams(
            n1=8, n2=6, fractal_period=16, fractal_buffer=0.2,
            round_interval=10.0, max_zone_width_atr=2.0,
            max_zone_width_pct=3.0, breakout_confirm_bars=3,
            false_breakout_window=6, inactivity_threshold=80,
            max_active_zones=10, volume_spike_threshold=1.5,
            vp_lookback_hours=[24, 168, 720],
        )
        config = SRResolvedConfig(
            metadata=metadata,
            pipeline=PipelineConfig(
                enabled_kernels=["pivot_hl", "volume_poc"],
                min_emit_strength=min_emit_strength,
                max_new_zones_per_bar=max_new_zones_per_bar,
            ),
            kernels={
                "pivot_hl": {"historical_depth": 500, "smoothing_period": 3},
                "volume_poc": {"num_bins": 50, "value_area_pct": 0.70},
            },
            ensemble=EnsembleConfig(method="weighted_average"),
            lifecycle=LifecycleConfig(
                age_lambda=0.002, breakout_confirm_bars=3,
                false_breakout_window=6, inactivity_threshold=80,
                max_active_zones=10,
            ),
            enhancement=EnhancementConfig(),
            regime=RegimeConfig(enabled=False),
            rule_derived=rule_derived,
            rule_derived_config=RuleDerivedConfig(),
        )
        return SRv2Pipeline(config, asset="TEST", timeframe="1h")

    def test_gate_filters_weak_levels(self):
        """Levels with strength < min_emit_strength are removed."""
        pipeline = self._make_pipeline(min_emit_strength=0.5, max_new_zones_per_bar=5)
        levels = [_make_scored_level(s / 10.0) for s in range(1, 11)]  # 0.1..1.0

        result = pipeline._apply_zone_gate(levels)

        assert len(result) == 5
        assert all(sl.strength >= 0.5 for sl in result)
        # Should be sorted descending by strength
        strengths = [sl.strength for sl in result]
        assert strengths == sorted(strengths, reverse=True)

    def test_gate_caps_per_bar(self):
        """Only top-N levels remain when all pass the strength threshold."""
        pipeline = self._make_pipeline(min_emit_strength=0.0, max_new_zones_per_bar=3)
        levels = [_make_scored_level(0.8, price=100.0 + i) for i in range(20)]

        result = pipeline._apply_zone_gate(levels)

        assert len(result) == 3

    def test_gate_disabled_when_threshold_zero(self):
        """min_emit_strength=0.0 + max_new_zones_per_bar=0 passes everything through."""
        pipeline = self._make_pipeline(min_emit_strength=0.0, max_new_zones_per_bar=0)
        levels = [_make_scored_level(s / 10.0) for s in range(1, 11)]

        result = pipeline._apply_zone_gate(levels)

        assert len(result) == 10

    def test_gate_combined_filter_and_cap(self):
        """Strength filter first, then cap — verifies ordering."""
        pipeline = self._make_pipeline(min_emit_strength=0.3, max_new_zones_per_bar=3)
        # 10 levels: strengths 0.1..1.0, 8 pass threshold (0.3..1.0), top 3 kept
        levels = [_make_scored_level(s / 10.0) for s in range(1, 11)]

        result = pipeline._apply_zone_gate(levels)

        assert len(result) == 3
        assert result[0].strength == pytest.approx(1.0)
        assert result[1].strength == pytest.approx(0.9)
        assert result[2].strength == pytest.approx(0.8)


class TestPipelineZoneCreationCapped:
    """Integration test: full pipeline with gate enabled."""

    def test_pipeline_zone_creation_capped(self):
        from app.sr.config_schema import (
            SRResolvedConfig, PipelineConfig, EnsembleConfig,
            LifecycleConfig, EnhancementConfig,
            RegimeConfig, RuleDerivedConfig,
        )
        from app.sr.models import AssetMetadata, RuleDerivedParams
        from app.sr.pipeline import SRv2Pipeline
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.volume_poc  # noqa: F401
        import app.sr.kernels.fair_value_gap  # noqa: F401
        import app.sr.kernels.order_block  # noqa: F401
        import app.sr.kernels.regression_band  # noqa: F401
        import app.sr.kernels.liquidity_sweep  # noqa: F401

        np.random.seed(42)
        n = 200
        close = 100.0 + np.cumsum(np.random.randn(n) * 0.5)
        high = close + np.abs(np.random.randn(n) * 0.3)
        low = close - np.abs(np.random.randn(n) * 0.3)
        open_ = close + np.random.randn(n) * 0.1
        volume = np.random.randint(100, 1000, n).astype(float)
        dates = pd.date_range("2025-01-01", periods=n, freq="1h", tz=UTC)

        df = pd.DataFrame({
            "open": open_, "high": high, "low": low, "close": close,
            "volume": volume,
        }, index=dates)

        metadata = AssetMetadata(
            profile="crypto", trading_hours_per_day=24.0,
            trading_days_per_week=7, has_session_gaps=False,
            gap_breakout_policy="gap_ignored", gap_escalation_atr=999.0,
            session_lookback_hours=[24, 168, 720],
            round_number_mode="decimal", ex_dividend_filter=False,
            continuous_market=True,
        )
        rule_derived = RuleDerivedParams(
            n1=8, n2=6, fractal_period=16, fractal_buffer=0.2,
            round_interval=10.0, max_zone_width_atr=2.0,
            max_zone_width_pct=3.0, breakout_confirm_bars=3,
            false_breakout_window=6, inactivity_threshold=80,
            max_active_zones=10, volume_spike_threshold=1.5,
            vp_lookback_hours=[24, 168, 720],
        )
        config = SRResolvedConfig(
            metadata=metadata,
            pipeline=PipelineConfig(
                enabled_kernels=[
                    "pivot_hl", "volume_poc", "fair_value_gap",
                    "order_block", "regression_band", "liquidity_sweep",
                ],
                min_emit_strength=0.3,
                max_new_zones_per_bar=5,
            ),
            kernels={
                "pivot_hl": {"historical_depth": 200, "smoothing_period": 3},
                "volume_poc": {"num_bins": 50, "value_area_pct": 0.70},
                "fair_value_gap": {},
                "order_block": {},
                "regression_band": {},
                "liquidity_sweep": {},
            },
            ensemble=EnsembleConfig(method="weighted_average"),
            lifecycle=LifecycleConfig(
                age_lambda=0.002, breakout_confirm_bars=3,
                false_breakout_window=6, inactivity_threshold=80,
                max_active_zones=10,
            ),
            enhancement=EnhancementConfig(),
            regime=RegimeConfig(enabled=False),
            rule_derived=rule_derived,
            rule_derived_config=RuleDerivedConfig(),
        )
        pipeline = SRv2Pipeline(config, asset="TEST", timeframe="1h")

        # Run bar-by-bar for 50 bars (after min_bars warmup)
        max_per_bar = config.pipeline.max_new_zones_per_bar
        for bar_idx in range(50, 100):
            result = pipeline.run(df.iloc[:bar_idx + 1], bar_index=bar_idx)
            assert len(result.new_zones) <= max_per_bar, (
                f"Bar {bar_idx}: {len(result.new_zones)} new zones exceeds cap {max_per_bar}"
            )
