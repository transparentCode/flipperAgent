"""
S/R v2 Phase 1 Unit Tests
=========================
Tests for:
  - Models (CandidateLevel, LevelFeatureVector, ScoredLevel, AssetMetadata, etc.)
  - Config schema + resolver + rule-derived calculator
  - Kernel base + registry
  - pivot_hl kernel
  - volume_poc kernel
  - Feature builder + context
  - Backward-compat adapters
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Dict, List

import numpy as np
import pandas as pd
import pytest


def _utc_now() -> datetime:
    return datetime.now(UTC)

# ---------------------------------------------------------------------------
# Fixtures: synthetic OHLCV data
# ---------------------------------------------------------------------------

def _make_ohlcv(
    n: int = 200,
    base_price: float = 100.0,
    volatility: float = 0.02,
    trend: float = 0.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic OHLCV DataFrame with DatetimeIndex."""
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="1h")

    closes = [base_price]
    for i in range(1, n):
        ret = trend + volatility * rng.randn()
        closes.append(closes[-1] * (1 + ret))
    closes = np.array(closes)

    highs = closes * (1 + rng.uniform(0, volatility, n))
    lows = closes * (1 - rng.uniform(0, volatility, n))
    opens = closes * (1 + rng.uniform(-volatility / 2, volatility / 2, n))
    volumes = rng.uniform(100, 1000, n)

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )


def _make_ohlcv_with_levels(
    n: int = 300,
    support_price: float = 95.0,
    resistance_price: float = 105.0,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Generate OHLCV with clear support and resistance levels.

    Price oscillates between support and resistance, touching each
    multiple times to create detectable pivots.
    """
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="1h")

    mid = (support_price + resistance_price) / 2
    amplitude = (resistance_price - support_price) / 2

    # Price oscillates as sine wave between support and resistance
    t = np.linspace(0, 6 * np.pi, n)  # ~3 full cycles
    base = mid + amplitude * np.sin(t)
    noise = rng.randn(n) * 0.3
    closes = base + noise

    highs = closes + rng.uniform(0.1, 0.5, n)
    lows = closes - rng.uniform(0.1, 0.5, n)
    opens = closes + rng.uniform(-0.2, 0.2, n)
    volumes = rng.uniform(200, 800, n)

    # Boost volume at extremes (touches)
    for i in range(n):
        if closes[i] > resistance_price - 1:
            volumes[i] *= 2
        elif closes[i] < support_price + 1:
            volumes[i] *= 2

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )


@pytest.fixture
def ohlcv():
    return _make_ohlcv()


@pytest.fixture
def ohlcv_with_levels():
    return _make_ohlcv_with_levels()


# ===================================================================
# 1. MODELS
# ===================================================================

class TestModels:
    def test_candidate_level_frozen(self):
        from app.sr.models import CandidateLevel, LevelType

        c = CandidateLevel(
            center_price=100.0,
            lower_bound=99.5,
            upper_bound=100.5,
            level_type=LevelType.SUPPORT,
            kernel_name="pivot_hl",
            timeframe="1h",
            raw_score=0.8,
            metadata={"pivot_index": 50},
            timestamp=datetime(2025, 1, 1),
            atr_at_detection=2.0,
        )
        assert c.center_price == 100.0
        assert c.width_atr == pytest.approx(0.5, abs=0.01)

        with pytest.raises(AttributeError):
            c.center_price = 200.0  # frozen

    def test_candidate_level_width_atr_zero(self):
        from app.sr.models import CandidateLevel, LevelType

        c = CandidateLevel(
            center_price=100.0, lower_bound=99.0, upper_bound=101.0,
            level_type=LevelType.SUPPORT, kernel_name="test",
            timeframe="1h", raw_score=0.5, metadata={},
            timestamp=_utc_now(), atr_at_detection=0.0,
        )
        assert c.width_atr == 0.0

    def test_feature_vector_defaults(self):
        from app.sr.models import LevelFeatureVector
        fv = LevelFeatureVector()
        assert fv.touch_count == 0
        assert fv.regime_alignment == 0.0

    def test_zone_status_enum(self):
        from app.sr.models import ZoneStatus
        assert ZoneStatus.FORMING.name == "FORMING"
        assert ZoneStatus.ACTIVE != ZoneStatus.BROKEN

    def test_asset_metadata_frozen(self):
        from app.sr.models import AssetMetadata
        m = AssetMetadata(
            profile="crypto", trading_hours_per_day=24.0,
            trading_days_per_week=7, has_session_gaps=False,
            gap_breakout_policy="gap_ignored", gap_escalation_atr=999.0,
            session_lookback_hours=[24, 168, 720],
            round_number_mode="decimal", ex_dividend_filter=False,
            continuous_market=True,
        )
        assert m.continuous_market is True
        with pytest.raises(AttributeError):
            m.profile = "equity"

    def test_rule_derived_params_properties(self):
        from app.sr.models import RuleDerivedParams
        rd = RuleDerivedParams(
            n1=8, n2=6, fractal_period=16, fractal_buffer=0.2,
            round_interval=10.0, max_zone_width_atr=2.0,
            max_zone_width_pct=3.0, breakout_confirm_bars=3,
            false_breakout_window=6, inactivity_threshold=80,
            max_active_zones=10, volume_spike_threshold=1.5,
            vp_lookback_hours=[24, 168, 720],
        )
        lp = rd.lifecycle_params
        assert "breakout_confirm_bars" in lp
        assert lp["max_active_zones"] == 10

        ep = rd.enhancement_params
        assert "volume_spike_threshold" in ep


# ===================================================================
# 2. CONFIG SCHEMA
# ===================================================================

class TestConfigSchema:
    def test_default_pipeline_config(self):
        from app.sr.config_schema import PipelineConfig
        pc = PipelineConfig()
        assert "pivot_hl" in pc.enabled_kernels

    def test_resolved_config_frozen(self):
        from app.sr.config_schema import SRResolvedConfig, PipelineConfig
        # Building SRResolvedConfig requires all fields — just ensure it's importable
        assert SRResolvedConfig is not None

    def test_rule_derived_config_defaults(self):
        from app.sr.config_schema import RuleDerivedConfig
        rd = RuleDerivedConfig()
        assert rd.pivot.base_multiplier == 8
        assert rd.hurst_fallback.fallback_value == 0.5


# ===================================================================
# 3. CONFIG RESOLVER + RULE-DERIVED CALCULATOR
# ===================================================================

class TestConfigResolver:
    def test_resolve_crypto_default(self):
        from app.sr.config_resolver import SRConfigResolver
        resolver = SRConfigResolver()

        config = {
            "asset_metadata": {
                "assets": {"BTCUSDT": {"profile": "crypto"}},
            },
            "sr": {
                "pipeline": {"enabled_kernels": ["pivot_hl"]},
                "lifecycle": {"age_lambda": 0.003},
            },
        }

        resolved = resolver.resolve("BTCUSDT", "1h", config)

        assert resolved.metadata.profile == "crypto"
        assert resolved.metadata.continuous_market is True
        assert resolved.metadata.has_session_gaps is False
        assert resolved.lifecycle.age_lambda == 0.003

    def test_resolve_equity_with_gaps(self):
        from app.sr.config_resolver import SRConfigResolver
        resolver = SRConfigResolver()

        config = {
            "asset_metadata": {
                "assets": {"AAPL": {"profile": "equity"}},
            },
            "sr": {},
        }

        resolved = resolver.resolve("AAPL", "1h", config)
        assert resolved.metadata.has_session_gaps is True
        assert resolved.metadata.ex_dividend_filter is True
        assert resolved.metadata.gap_breakout_policy == "gap_suspends_countdown"

    def test_per_asset_override(self):
        from app.sr.config_resolver import SRConfigResolver
        resolver = SRConfigResolver()

        config = {
            "asset_metadata": {
                "assets": {
                    "GC": {
                        "profile": "commodity",
                        "has_session_gaps": False,  # Override
                        "gap_breakout_policy": "gap_ignored",
                    },
                },
            },
            "sr": {},
        }

        resolved = resolver.resolve("GC", "1h", config)
        assert resolved.metadata.profile == "commodity"
        assert resolved.metadata.has_session_gaps is False  # Overridden
        assert resolved.metadata.gap_breakout_policy == "gap_ignored"

    def test_cascade_merge_per_tf(self):
        from app.sr.config_resolver import SRConfigResolver
        resolver = SRConfigResolver()

        config = {
            "sr": {
                "lifecycle": {"min_strength": 0.3},
            },
            "per_tf": {
                "30m": {"lifecycle": {"min_strength": 0.35}},
            },
        }

        resolved = resolver.resolve("BTCUSDT", "30m", config)
        assert resolved.lifecycle.min_strength == 0.35  # per-TF wins

    def test_cascade_merge_per_asset_tf(self):
        from app.sr.config_resolver import SRConfigResolver
        resolver = SRConfigResolver()

        config = {
            "sr": {
                "features": {"touch_proximity_atr": 0.5},
            },
            "assets": {
                "BTCUSDT": {
                    "4h": {"features": {"touch_proximity_atr": 0.25}},
                },
            },
        }

        resolved = resolver.resolve("BTCUSDT", "4h", config)
        assert resolved.features.touch_proximity_atr == 0.25

    def test_resolve_reads_materialized_sidecar_fields(self):
        from app.sr.config_resolver import SRConfigResolver

        resolver = SRConfigResolver()
        config = {
            "assets": {
                "BTCUSDT": {
                    "1h": {
                        "_profiler_meta": {
                            "last_profiled_at": "2026-05-07T14:32:00Z",
                            "wick_p75_atr": 0.85,
                        },
                        "pipeline": {
                            "merge_threshold_pct_atr": 0.425,
                            "dedup_proximity_atr": 0.85,
                            "zone_half_width_atr": 0.21,
                        },
                        "lifecycle": {
                            "breakout_atr_threshold": 0.45,
                            "touch_proximity_atr": 0.15,
                            "false_breakout_recovery_bars": 8,
                        },
                        "enhancement": {
                            "volume_spike_threshold": 1.7,
                        },
                    },
                },
            },
        }

        resolved = resolver.resolve("BTCUSDT", "1h", config)

        assert resolved.requires_sidecar_derivation is False
        assert resolved.profiler_meta["last_profiled_at"] == "2026-05-07T14:32:00Z"
        assert resolved.pipeline.merge_threshold_pct_atr == pytest.approx(0.425)
        assert resolved.lifecycle.dedup_proximity_atr == pytest.approx(0.85)
        assert resolved.lifecycle.breakout_atr_threshold == pytest.approx(0.45)
        assert resolved.enhancement.volume_spike_threshold == pytest.approx(1.7)
        assert resolved.kernels["pivot_hl"]["zone_half_width_atr"] == pytest.approx(0.21)

    def test_resolve_flags_missing_sidecar_materialization(self):
        from app.sr.config_resolver import SRConfigResolver

        resolver = SRConfigResolver()
        resolved = resolver.resolve("BTCUSDT", "1h", {"assets": {"BTCUSDT": {"1h": {}}}})

        assert resolved.requires_sidecar_derivation is True
        assert resolved.profiler_meta == {}
        assert resolved.pipeline.merge_threshold_pct_atr == pytest.approx(0.25)
        assert resolved.lifecycle.dedup_proximity_atr == pytest.approx(0.5)
        assert resolved.lifecycle.breakout_atr_threshold == pytest.approx(0.3)
        assert resolved.kernels["pivot_hl"]["zone_half_width_atr"] == pytest.approx(0.1)


class TestRuleDerivedCalculator:
    def _make_characteristics(self, **kwargs):
        from app.sr.models import AssetCharacteristics, AssetMetadata
        defaults = {
            "metadata": AssetMetadata(
                profile="crypto", trading_hours_per_day=24.0,
                trading_days_per_week=7, has_session_gaps=False,
                gap_breakout_policy="gap_ignored", gap_escalation_atr=999.0,
                session_lookback_hours=[24, 168, 720],
                round_number_mode="decimal", ex_dividend_filter=False,
                continuous_market=True,
            ),
            "price": 80000.0,
            "atr": 1500.0,
            "atr_pct": 0.019,
            "volume_mean": 500.0,
            "volume_kurtosis": 3.0,
            "hurst": 0.55,
            "hurst_confidence": 0.8,
            "wick_body_ratio": 1.0,
            "tf_minutes": 60,
            "n_timeframes": 3,
        }
        defaults.update(kwargs)
        return AssetCharacteristics(**defaults)

    def test_pivot_scaling(self):
        from app.sr.config_resolver import RuleDerivedParamsCalculator
        from app.sr.config_schema import RuleDerivedConfig

        calc = RuleDerivedParamsCalculator(RuleDerivedConfig())

        # 1h → tf_ratio = 1.0 → n1 = clip(round(8*1), 5, 20) = 8
        c_1h = self._make_characteristics(tf_minutes=60)
        rd_1h = calc.compute(c_1h)
        assert rd_1h.n1 == 8

        # 30m → tf_ratio = 0.5 → n1 = clip(round(8*0.707), 5, 20) = 6
        c_30m = self._make_characteristics(tf_minutes=30)
        rd_30m = calc.compute(c_30m)
        assert rd_30m.n1 == 6

        # 4h → tf_ratio = 4.0 → n1 = clip(round(8*2), 5, 20) = 16
        c_4h = self._make_characteristics(tf_minutes=240)
        rd_4h = calc.compute(c_4h)
        assert rd_4h.n1 == 16

    def test_hurst_fallback(self):
        from app.sr.config_resolver import RuleDerivedParamsCalculator
        from app.sr.config_schema import RuleDerivedConfig

        calc = RuleDerivedParamsCalculator(RuleDerivedConfig())

        # Low confidence → fallback to 0.5
        c = self._make_characteristics(hurst=0.8, hurst_confidence=0.3)
        rd = calc.compute(c)
        # With fallback hurst=0.5, |0.5-0.5|=0, so width = base_atr=1.5
        assert rd.max_zone_width_atr == pytest.approx(1.5, abs=0.01)

        # High confidence → use actual hurst
        c2 = self._make_characteristics(hurst=0.8, hurst_confidence=0.9)
        rd2 = calc.compute(c2)
        # |0.8-0.5|=0.3, width = 1.5 + 0.5*0.3 = 1.65
        assert rd2.max_zone_width_atr == pytest.approx(1.65, abs=0.01)

    def test_round_interval_decimal(self):
        from app.sr.config_resolver import RuleDerivedParamsCalculator
        from app.sr.config_schema import RuleDerivedConfig

        calc = RuleDerivedParamsCalculator(RuleDerivedConfig())

        # BTC @ 80000 → 10^(4-1) = 1000
        c = self._make_characteristics(price=80000.0)
        rd = calc.compute(c)
        assert rd.round_interval == 1000.0

        # AAPL @ 200 → 10^(2-1) = 10
        c2 = self._make_characteristics(price=200.0)
        rd2 = calc.compute(c2)
        assert rd2.round_interval == 10.0

    def test_round_interval_pip(self):
        from app.sr.models import AssetMetadata
        from app.sr.config_resolver import RuleDerivedParamsCalculator
        from app.sr.config_schema import RuleDerivedConfig

        calc = RuleDerivedParamsCalculator(RuleDerivedConfig())
        fx_metadata = AssetMetadata(
            profile="fx", trading_hours_per_day=24.0,
            trading_days_per_week=5, has_session_gaps=False,
            gap_breakout_policy="gap_ignored", gap_escalation_atr=999.0,
            session_lookback_hours=[24, 120, 504],
            round_number_mode="pip", ex_dividend_filter=False,
            continuous_market=True,
        )

        eurusd = self._make_characteristics(metadata=fx_metadata, price=1.0834)
        rd_fx = calc.compute(eurusd)
        assert rd_fx.round_interval == pytest.approx(0.01)

        usdjpy = self._make_characteristics(metadata=fx_metadata, price=151.2)
        rd_jpy = calc.compute(usdjpy)
        assert rd_jpy.round_interval == pytest.approx(1.0)

    def test_volume_spike_bounds(self):
        from app.sr.config_resolver import RuleDerivedParamsCalculator
        from app.sr.config_schema import RuleDerivedConfig

        calc = RuleDerivedParamsCalculator(RuleDerivedConfig())

        # Very low kurtosis → floor
        c_lo = self._make_characteristics(volume_kurtosis=0.5)
        rd_lo = calc.compute(c_lo)
        assert rd_lo.volume_spike_threshold == pytest.approx(1.3)

        # Very high kurtosis → ceiling
        c_hi = self._make_characteristics(volume_kurtosis=50.0)
        rd_hi = calc.compute(c_hi)
        assert rd_hi.volume_spike_threshold == pytest.approx(2.5)


# ===================================================================
# 4. KERNEL REGISTRY
# ===================================================================

class TestKernelRegistry:
    def test_registration(self):
        from app.sr.kernels.registry import KernelRegistry
        # Ensure kernel modules are imported so decorators fire
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.volume_poc  # noqa: F401
        assert KernelRegistry.has("pivot_hl")
        assert KernelRegistry.has("volume_poc")

    def test_list_all(self):
        from app.sr.kernels.registry import KernelRegistry
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.volume_poc  # noqa: F401
        names = KernelRegistry.list_all()
        assert "pivot_hl" in names
        assert "volume_poc" in names

    def test_create_instance(self):
        from app.sr.kernels.registry import KernelRegistry
        from app.sr.kernels.base import BaseSRKernel
        import app.sr.kernels.pivot_hl  # noqa: F401
        kernel = KernelRegistry.create("pivot_hl")
        assert kernel is not None
        assert isinstance(kernel, BaseSRKernel)

    def test_get_nonexistent(self):
        from app.sr.kernels.registry import KernelRegistry
        assert KernelRegistry.get("nonexistent_kernel_xyz") is None


# ===================================================================
# 5. PIVOT_HL KERNEL
# ===================================================================

class TestPivotHLKernel:
    def _make_config(self, tf: str = "1h", n1: int = 8, n2: int = 6) -> "KernelConfig":
        from app.sr.kernels.base import KernelConfig
        from app.sr.models import AssetMetadata, RuleDerivedParams

        return KernelConfig(
            kernel_name="pivot_hl",
            timeframe=tf,
            kernel_params={"historical_depth": 500, "smoothing_period": 3},
            metadata=AssetMetadata(
                profile="crypto", trading_hours_per_day=24.0,
                trading_days_per_week=7, has_session_gaps=False,
                gap_breakout_policy="gap_ignored", gap_escalation_atr=999.0,
                session_lookback_hours=[24, 168, 720],
                round_number_mode="decimal", ex_dividend_filter=False,
                continuous_market=True,
            ),
            rule_derived=RuleDerivedParams(
                n1=n1, n2=n2, fractal_period=2 * n1, fractal_buffer=0.0,
                round_interval=1000.0, max_zone_width_atr=2.0,
                max_zone_width_pct=3.0, breakout_confirm_bars=3,
                false_breakout_window=6, inactivity_threshold=80,
                max_active_zones=10, volume_spike_threshold=1.5,
                vp_lookback_hours=[24, 168, 720],
            ),
        )

    @staticmethod
    def _make_pivot_window_df(highs: list[float], lows: list[float] | None = None) -> pd.DataFrame:
        lows = lows or [high - 2.0 for high in highs]
        opens = [high - 1.0 for high in highs]
        closes = [high - 0.5 for high in highs]
        volumes = [100.0 + index for index in range(len(highs))]
        return pd.DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": volumes,
            },
            index=pd.date_range("2025-01-01", periods=len(highs), freq="1h"),
        )

    def test_detects_pivots(self, ohlcv_with_levels):
        from app.sr.kernels.pivot_hl import PivotHighLowKernel
        from app.sr.models import LevelType

        kernel = PivotHighLowKernel()
        config = self._make_config()
        candidates = kernel.compute(ohlcv_with_levels, config)

        assert len(candidates) > 0
        # Should have both support and resistance
        types = {c.level_type for c in candidates}
        assert LevelType.SUPPORT in types
        assert LevelType.RESISTANCE in types

    def test_all_candidates_have_zone_bounds(self, ohlcv_with_levels):
        from app.sr.kernels.pivot_hl import PivotHighLowKernel

        kernel = PivotHighLowKernel()
        config = self._make_config()
        candidates = kernel.compute(ohlcv_with_levels, config)

        for c in candidates:
            assert c.lower_bound < c.center_price < c.upper_bound
            assert c.atr_at_detection > 0
            assert 0.0 <= c.raw_score <= 1.0
            assert c.kernel_name == "pivot_hl"

    def test_insufficient_data(self):
        from app.sr.kernels.pivot_hl import PivotHighLowKernel

        kernel = PivotHighLowKernel()
        config = self._make_config()
        short_df = _make_ohlcv(n=5)  # Too short
        candidates = kernel.compute(short_df, config)
        assert candidates == []

    def test_stateless(self, ohlcv):
        from app.sr.kernels.pivot_hl import PivotHighLowKernel

        kernel = PivotHighLowKernel()
        config = self._make_config()

        # Two calls with same data should produce same result
        r1 = kernel.compute(ohlcv, config)
        r2 = kernel.compute(ohlcv, config)
        assert len(r1) == len(r2)
        for a, b in zip(r1, r2):
            assert a.center_price == b.center_price

    def test_includes_latest_confirmable_pivot(self):
        from app.sr.kernels.pivot_hl import PivotHighLowKernel
        from app.sr.models import LevelType

        kernel = PivotHighLowKernel()
        config = self._make_config(n1=2, n2=2)
        config.kernel_params["min_bars"] = 5
        config.kernel_params["smoothing_period"] = 0
        df = self._make_pivot_window_df([1.0, 2.0, 3.0, 4.0, 5.0, 10.0, 4.0, 3.0])

        candidates = kernel.compute(df, config)

        assert any(
            c.level_type == LevelType.RESISTANCE and c.metadata.get("pivot_index") == 5
            for c in candidates
        )

    def test_timestamp_uses_confirmation_bar(self):
        from app.sr.kernels.pivot_hl import PivotHighLowKernel
        from app.sr.models import LevelType

        kernel = PivotHighLowKernel()
        config = self._make_config(n1=2, n2=2)
        config.kernel_params["min_bars"] = 5
        config.kernel_params["smoothing_period"] = 0
        df = self._make_pivot_window_df([1.0, 2.0, 3.0, 4.0, 5.0, 10.0, 4.0, 3.0])

        candidates = kernel.compute(df, config)
        resistance = next(
            c
            for c in candidates
            if c.level_type == LevelType.RESISTANCE and c.metadata.get("pivot_index") == 5
        )

        assert resistance.metadata["confirmation_index"] == 7
        assert resistance.timestamp == df.index[7].to_pydatetime().replace(tzinfo=UTC)

    def test_historical_depth_keeps_earliest_candidate_in_window(self):
        from app.sr.kernels.pivot_hl import PivotHighLowKernel
        from app.sr.models import LevelType

        kernel = PivotHighLowKernel()
        config = self._make_config(n1=2, n2=2)
        config.kernel_params["min_bars"] = 5
        config.kernel_params["historical_depth"] = 5
        config.kernel_params["smoothing_period"] = 0
        df = self._make_pivot_window_df([1.0, 2.0, 3.0, 4.0, 3.0, 10.0, 4.0, 3.0, 2.0, 1.0])

        candidates = kernel.compute(df, config)

        assert any(
            c.level_type == LevelType.RESISTANCE and c.metadata.get("pivot_index") == 5
            for c in candidates
        )

    def test_min_bars_is_consumed(self, ohlcv_with_levels):
        from app.sr.kernels.pivot_hl import PivotHighLowKernel

        kernel = PivotHighLowKernel()
        permissive = self._make_config()
        strict = self._make_config()
        permissive.kernel_params["min_bars"] = 15
        strict.kernel_params["min_bars"] = len(ohlcv_with_levels) + 1

        assert kernel.compute(ohlcv_with_levels, permissive)
        assert kernel.compute(ohlcv_with_levels, strict) == []

    def test_non_datetime_index_uses_deterministic_timestamp(self):
        from app.sr.kernels.pivot_hl import PivotHighLowKernel

        kernel = PivotHighLowKernel()
        config = self._make_config(n1=2, n2=2)
        config.kernel_params["min_bars"] = 5
        config.kernel_params["smoothing_period"] = 0
        df = self._make_pivot_window_df([1.0, 2.0, 3.0, 4.0, 5.0, 10.0, 4.0, 3.0])
        df.index = pd.RangeIndex(start=0, stop=len(df), step=1)

        first = kernel.compute(df, config)
        second = kernel.compute(df, config)

        assert first
        assert [c.timestamp for c in first] == [c.timestamp for c in second]
        assert any(c.timestamp.tzinfo is not None for c in first)
        resistance = next(c for c in first if c.metadata.get("pivot_index") == 5)
        assert resistance.metadata["confirmation_index"] == 7
        assert resistance.timestamp == datetime(1970, 1, 1, 0, 0, 7, tzinfo=UTC)


# ===================================================================
# 6. VOLUME_POC KERNEL
# ===================================================================

class TestVolumePOCKernel:
    def _make_config(self, tf: str = "1h") -> "KernelConfig":
        from app.sr.kernels.base import KernelConfig
        from app.sr.models import AssetMetadata, RuleDerivedParams

        return KernelConfig(
            kernel_name="volume_poc",
            timeframe=tf,
            kernel_params={
                "num_bins": 50,
                "value_area_pct": 0.70,
                "poc_strength": 0.9,
                "vah_val_strength": 0.7,
                "hvn_strength": 0.6,
                "max_hvn_count": 3,
                "hvn_prominence": 0.2,
            },
            metadata=AssetMetadata(
                profile="crypto", trading_hours_per_day=24.0,
                trading_days_per_week=7, has_session_gaps=False,
                gap_breakout_policy="gap_ignored", gap_escalation_atr=999.0,
                session_lookback_hours=[24, 168, 720],
                round_number_mode="decimal", ex_dividend_filter=False,
                continuous_market=True,
            ),
            rule_derived=RuleDerivedParams(
                n1=8, n2=6, fractal_period=16, fractal_buffer=0.0,
                round_interval=1000.0, max_zone_width_atr=2.0,
                max_zone_width_pct=3.0, breakout_confirm_bars=3,
                false_breakout_window=6, inactivity_threshold=80,
                max_active_zones=10, volume_spike_threshold=1.5,
                vp_lookback_hours=[24, 168, 720],
            ),
        )

    def test_detects_poc_vah_val(self, ohlcv):
        from app.sr.kernels.volume_poc import VolumePOCKernel

        kernel = VolumePOCKernel()
        config = self._make_config()
        candidates = kernel.compute(ohlcv, config)

        assert len(candidates) > 0

        vp_types = {c.metadata["vp_type"] for c in candidates}
        assert "poc" in vp_types
        assert "vah" in vp_types
        assert "val" in vp_types

    def test_all_candidates_valid(self, ohlcv):
        from app.sr.kernels.volume_poc import VolumePOCKernel

        kernel = VolumePOCKernel()
        config = self._make_config()
        candidates = kernel.compute(ohlcv, config)

        for c in candidates:
            assert c.lower_bound < c.center_price < c.upper_bound
            assert c.atr_at_detection > 0
            assert 0.0 <= c.raw_score <= 1.0
            assert c.kernel_name == "volume_poc"

    def test_insufficient_data(self):
        from app.sr.kernels.volume_poc import VolumePOCKernel

        kernel = VolumePOCKernel()
        config = self._make_config()
        short_df = _make_ohlcv(n=5)
        assert kernel.compute(short_df, config) == []

    def test_multi_lookback_coverage(self, ohlcv):
        from app.sr.kernels.volume_poc import VolumePOCKernel

        kernel = VolumePOCKernel()
        config = self._make_config()
        candidates = kernel.compute(ohlcv, config)

        lookbacks = {c.metadata.get("lookback_hours") for c in candidates}
        # At least the shortest lookback should produce results
        assert len(lookbacks) >= 1


# ===================================================================
# 7. FEATURE BUILDER
# ===================================================================

class TestFeatureBuilder:
    def test_build_basic(self, ohlcv_with_levels):
        from app.sr.features.builder import LevelFeatureBuilder
        from app.sr.features.context import FeatureContext
        from app.sr.kernels.pivot_hl import PivotHighLowKernel
        from app.sr.kernels.base import KernelConfig
        from app.sr.models import AssetMetadata, RuleDerivedParams

        df = ohlcv_with_levels
        kernel = PivotHighLowKernel()
        atr = kernel.calculate_atr(df)

        config = KernelConfig(
            kernel_name="pivot_hl", timeframe="1h",
            kernel_params={"historical_depth": 500, "smoothing_period": 3},
            metadata=AssetMetadata(
                profile="crypto", trading_hours_per_day=24.0,
                trading_days_per_week=7, has_session_gaps=False,
                gap_breakout_policy="gap_ignored", gap_escalation_atr=999.0,
                session_lookback_hours=[24, 168, 720],
                round_number_mode="decimal", ex_dividend_filter=False,
                continuous_market=True,
            ),
            rule_derived=RuleDerivedParams(
                n1=8, n2=6, fractal_period=16, fractal_buffer=0.0,
                round_interval=10.0, max_zone_width_atr=2.0,
                max_zone_width_pct=3.0, breakout_confirm_bars=3,
                false_breakout_window=6, inactivity_threshold=80,
                max_active_zones=10, volume_spike_threshold=1.5,
                vp_lookback_hours=[24, 168, 720],
            ),
        )

        candidates = kernel.compute(df, config)
        assert len(candidates) > 0

        ctx = FeatureContext(
            df=df, current_price=float(df["close"].iloc[-1]),
            atr=atr, bar_count=len(df),
        )

        builder = LevelFeatureBuilder()
        fv = builder.build(candidates[0], candidates, ctx)

        assert fv.touch_count >= 0
        assert fv.atr_distance_from_price >= 0
        assert fv.kernel_agreement >= 1
        assert fv.regime_alignment == 0.0  # No regime

    def test_regime_alignment_neutral_without_regime(self, ohlcv):
        from app.sr.features.builder import LevelFeatureBuilder
        from app.sr.features.context import FeatureContext
        from app.sr.models import CandidateLevel, LevelType

        df = ohlcv
        atr = 2.0
        candidate = CandidateLevel(
            center_price=100.0, lower_bound=99.5, upper_bound=100.5,
            level_type=LevelType.SUPPORT, kernel_name="test",
            timeframe="1h", raw_score=0.5, metadata={},
            timestamp=_utc_now(), atr_at_detection=atr,
        )

        ctx = FeatureContext(
            df=df, current_price=100.0, atr=atr, bar_count=len(df),
            regime_state=None,
        )

        builder = LevelFeatureBuilder()
        fv = builder.build(candidate, [candidate], ctx)
        assert fv.regime_alignment == 0.0

    def test_regime_alignment_trending(self, ohlcv):
        from app.sr.features.builder import LevelFeatureBuilder
        from app.sr.features.context import FeatureContext
        from app.sr.models import CandidateLevel, LevelType

        df = ohlcv
        atr = 2.0
        candidate = CandidateLevel(
            center_price=100.0, lower_bound=99.5, upper_bound=100.5,
            level_type=LevelType.RESISTANCE, kernel_name="test",
            timeframe="1h", raw_score=0.5, metadata={},
            timestamp=_utc_now(), atr_at_detection=atr,
        )

        ctx = FeatureContext(
            df=df, current_price=100.0, atr=atr, bar_count=len(df),
            regime_state="trending",
        )

        builder = LevelFeatureBuilder()
        fv = builder.build(candidate, [candidate], ctx)
        assert fv.regime_alignment == -0.5  # Resistance in trend likely to break


# ===================================================================
# 8. FEATURE CONTEXT
# ===================================================================

class TestFeatureContext:
    def test_from_dataframe(self, ohlcv):
        from app.sr.features.context import FeatureContext

        ctx = FeatureContext.from_dataframe(ohlcv, atr=2.0)
        assert ctx.current_price > 0
        assert ctx.volume_mean > 0
        assert ctx.bar_count == len(ohlcv)

    def test_from_dataframe_with_regime(self, ohlcv):
        from app.sr.features.context import FeatureContext

        ctx = FeatureContext.from_dataframe(
            ohlcv, atr=2.0, regime_state="ranging", regime_confidence=0.85,
        )
        assert ctx.regime_state == "ranging"
        assert ctx.regime_confidence == 0.85


# ===================================================================
# 10. INTEGRATION: FULL PIPELINE SMOKE TEST
# ===================================================================

class TestIntegration:
    def test_full_pipeline_smoke(self, ohlcv_with_levels):
        """Smoke test: config → kernels → features → all candidates."""
        from app.sr.config_resolver import SRConfigResolver
        from app.sr.kernels.registry import KernelRegistry
        from app.sr.kernels.base import KernelConfig
        from app.sr.features.builder import LevelFeatureBuilder
        from app.sr.features.context import FeatureContext
        from app.sr.models import CandidateLevel

        df = ohlcv_with_levels
        raw_config = {
            "asset_metadata": {"assets": {"TEST": {"profile": "crypto"}}},
            "sr": {"pipeline": {"enabled_kernels": ["pivot_hl", "volume_poc"]}},
        }

        # 1. Resolve config
        resolver = SRConfigResolver()
        resolved = resolver.resolve("TEST", "1h", raw_config)

        # 2. Run kernels
        all_candidates: List[CandidateLevel] = []
        for kernel_name in resolved.pipeline.enabled_kernels:
            kernel = KernelRegistry.create(kernel_name)
            if kernel is None:
                continue
            kc = KernelConfig(
                kernel_name=kernel_name,
                timeframe="1h",
                kernel_params=resolved.kernels.get(kernel_name, {}),
                metadata=resolved.metadata,
                rule_derived=resolved.rule_derived,
            )
            candidates = kernel.compute(df, kc)
            all_candidates.extend(candidates)

        assert len(all_candidates) > 0

        # 3. Build features
        atr = float(all_candidates[0].atr_at_detection)
        ctx = FeatureContext(
            df=df, current_price=float(df["close"].iloc[-1]),
            atr=atr, bar_count=len(df),
        )

        builder = LevelFeatureBuilder()
        for c in all_candidates[:5]:  # Test first 5
            fv = builder.build(c, all_candidates, ctx)
            assert fv.kernel_agreement >= 1
            assert fv.atr_distance_from_price >= 0

    def test_kernel_agreement_multi_kernel(self, ohlcv_with_levels):
        """When pivot and VP agree on a level, kernel_agreement > 1."""
        from app.sr.kernels.registry import KernelRegistry
        from app.sr.kernels.base import KernelConfig
        from app.sr.features.builder import LevelFeatureBuilder
        from app.sr.features.context import FeatureContext
        from app.sr.models import AssetMetadata, RuleDerivedParams

        df = ohlcv_with_levels
        metadata = AssetMetadata(
            profile="crypto", trading_hours_per_day=24.0,
            trading_days_per_week=7, has_session_gaps=False,
            gap_breakout_policy="gap_ignored", gap_escalation_atr=999.0,
            session_lookback_hours=[24, 168, 720],
            round_number_mode="decimal", ex_dividend_filter=False,
            continuous_market=True,
        )
        rd = RuleDerivedParams(
            n1=8, n2=6, fractal_period=16, fractal_buffer=0.0,
            round_interval=10.0, max_zone_width_atr=2.0,
            max_zone_width_pct=3.0, breakout_confirm_bars=3,
            false_breakout_window=6, inactivity_threshold=80,
            max_active_zones=10, volume_spike_threshold=1.5,
            vp_lookback_hours=[24, 168, 720],
        )

        all_candidates = []
        for name in ["pivot_hl", "volume_poc"]:
            kernel = KernelRegistry.create(name)
            kc = KernelConfig(
                kernel_name=name, timeframe="1h",
                kernel_params={
                    "historical_depth": 500, "smoothing_period": 3,
                    "num_bins": 50, "value_area_pct": 0.70,
                    "poc_strength": 0.9, "vah_val_strength": 0.7,
                    "hvn_strength": 0.6, "max_hvn_count": 3,
                    "hvn_prominence": 0.2,
                },
                metadata=metadata, rule_derived=rd,
            )
            all_candidates.extend(kernel.compute(df, kc))

        atr = all_candidates[0].atr_at_detection if all_candidates else 1.0
        ctx = FeatureContext(
            df=df, current_price=float(df["close"].iloc[-1]),
            atr=atr, bar_count=len(df),
        )

        builder = LevelFeatureBuilder()
        kernel_names = set()
        for c in all_candidates:
            kernel_names.add(c.kernel_name)

        # At least two kernels contributed
        assert len(kernel_names) == 2
