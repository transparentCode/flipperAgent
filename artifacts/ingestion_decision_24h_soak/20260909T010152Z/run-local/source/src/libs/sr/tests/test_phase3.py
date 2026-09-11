"""
S/R v2 Phase 3 Unit Tests
=========================
Tests for:
    - VolumePOCKernel
  - RoundNumberKernel
  - OrderBlockKernel
  - FairValueGapKernel
  - SessionGapKernel
  - FractalChannelKernel (import + basic contract)
  - RegressionBandKernel
  - UniverseSRConfig
  - UniverseSRRouter
"""

from __future__ import annotations

import copy
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import List

import numpy as np
import pandas as pd
import pytest

from app.sr.models import LevelType
from app.sr.kernels.base import BaseSRKernel, KernelConfig
from app.sr.kernels.registry import KernelRegistry
from app.sr.models import (
    AssetMetadata,
    CandidateLevel,
    RuleDerivedParams,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(
    n: int = 200,
    base_price: float = 100.0,
    volatility: float = 0.02,
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    closes = [base_price]
    for i in range(1, n):
        closes.append(closes[-1] * (1 + volatility * rng.randn()))
    closes = np.array(closes)
    highs = closes * (1 + rng.uniform(0, volatility, n))
    lows = closes * (1 - rng.uniform(0, volatility, n))
    opens = closes * (1 + rng.uniform(-volatility / 2, volatility / 2, n))
    volumes = rng.uniform(100, 1000, n)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )


def _make_ohlcv_with_gaps(
    n: int = 200,
    base_price: float = 100.0,
    gap_indices: list | None = None,
    gap_size_pct: float = 0.03,
    seed: int = 42,
) -> pd.DataFrame:
    """Create OHLCV with price gaps and timestamp discontinuities."""
    df = _make_ohlcv(n=n, base_price=base_price, seed=seed)
    if gap_indices:
        valid_gap_indices = sorted(idx for idx in gap_indices if 0 < idx < n)
        opens = df["open"].values.copy()
        closes = df["close"].values.copy()
        shifted_index = list(df.index)
        cumulative_break = timedelta(0)

        for idx in valid_gap_indices:
            # Create a gap: open[idx] = close[idx-1] * (1 + gap)
            gap = closes[idx - 1] * gap_size_pct
            opens[idx] = closes[idx - 1] + gap
            closes[idx] = opens[idx] * 1.005  # small move after gap

        for idx, timestamp in enumerate(shifted_index):
            if idx in valid_gap_indices:
                cumulative_break += timedelta(hours=18)
            shifted_index[idx] = timestamp + cumulative_break

        df["open"] = opens
        df["close"] = closes
        # Adjust high/low to be consistent
        df["high"] = np.maximum(df["high"], np.maximum(df["open"], df["close"]))
        df["low"] = np.minimum(df["low"], np.minimum(df["open"], df["close"]))
        df.index = pd.DatetimeIndex(shifted_index)
    return df


def _make_ohlcv_with_displacement(
    n: int = 200,
    base_price: float = 100.0,
    displacement_at: int = 100,
    displacement_atr_mult: float = 3.0,
    direction: str = "bullish",
    seed: int = 42,
) -> pd.DataFrame:
    """Create OHLCV with a strong displacement candle for order block detection."""
    df = _make_ohlcv(n=n, base_price=base_price, seed=seed)
    atr = float(BaseSRKernel.calculate_atr(df[:displacement_at]))
    opens = df["open"].values.copy()
    highs = df["high"].values.copy()
    lows = df["low"].values.copy()
    closes = df["close"].values.copy()

    # Normalize the recent window so the structural break check is deterministic.
    window_start = max(0, displacement_at - 5)
    for idx in range(window_start, displacement_at - 1):
        opens[idx] = base_price
        closes[idx] = base_price
        highs[idx] = base_price + 0.2 * atr
        lows[idx] = base_price - 0.2 * atr

    ob_idx = displacement_at - 1
    displacement = displacement_atr_mult * atr

    if direction == "bullish":
        # Make candle at displacement_at-1 bearish (the OB candle)
        opens[ob_idx] = base_price + 0.5 * atr
        closes[ob_idx] = base_price - 0.5 * atr
        highs[ob_idx] = opens[ob_idx] + 0.1 * atr
        lows[ob_idx] = closes[ob_idx] - 0.1 * atr

        # Make candle at displacement_at a strong bullish displacement
        opens[displacement_at] = closes[ob_idx]
        closes[displacement_at] = opens[displacement_at] + displacement
        highs[displacement_at] = closes[displacement_at] + 0.1 * atr
        lows[displacement_at] = opens[displacement_at] - 0.05 * atr
    else:
        # Make candle at displacement_at-1 bullish (the OB candle)
        opens[ob_idx] = base_price - 0.5 * atr
        closes[ob_idx] = base_price + 0.5 * atr
        highs[ob_idx] = closes[ob_idx] + 0.1 * atr
        lows[ob_idx] = opens[ob_idx] - 0.1 * atr

        # Make candle at displacement_at a strong bearish displacement
        opens[displacement_at] = closes[ob_idx]
        closes[displacement_at] = opens[displacement_at] - displacement
        highs[displacement_at] = opens[displacement_at] + 0.05 * atr
        lows[displacement_at] = closes[displacement_at] - 0.1 * atr

    df["open"] = opens
    df["high"] = highs
    df["low"] = lows
    df["close"] = closes
    return df


def _make_ohlcv_with_fvg(
    n: int = 200,
    base_price: float = 100.0,
    fvg_at: int = 100,
    seed: int = 42,
) -> pd.DataFrame:
    """Create OHLCV with a bullish FVG (low[i+1] > high[i-1])."""
    df = _make_ohlcv(n=n, base_price=base_price, seed=seed)
    atr = float(BaseSRKernel.calculate_atr(df[:fvg_at]))
    highs = df["high"].values.copy()
    lows = df["low"].values.copy()
    opens = df["open"].values.copy()
    closes = df["close"].values.copy()

    # Candle i-1: normal, set high
    highs[fvg_at - 1] = base_price
    closes[fvg_at - 1] = base_price - 0.3 * atr

    # Candle i: strong bullish displacement
    opens[fvg_at] = base_price + 0.1 * atr
    closes[fvg_at] = base_price + 2.0 * atr
    highs[fvg_at] = closes[fvg_at] + 0.1 * atr
    lows[fvg_at] = opens[fvg_at] - 0.05 * atr

    # Candle i+1: gap up — low > high[i-1]
    lows[fvg_at + 1] = base_price + 0.8 * atr  # > high[i-1] = base_price
    opens[fvg_at + 1] = base_price + 1.0 * atr
    closes[fvg_at + 1] = base_price + 1.2 * atr
    highs[fvg_at + 1] = base_price + 1.3 * atr

    df["open"] = opens
    df["high"] = highs
    df["low"] = lows
    df["close"] = closes
    return df


def _make_ohlcv_with_liquidity_sweep(
    n: int = 60,
    sweep_at: int | None = None,
    sweep_type: str = "bearish",
) -> pd.DataFrame:
    """Create OHLCV with one deterministic liquidity sweep."""
    if sweep_at is None:
        sweep_at = n - 1

    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    opens = np.full(n, 100.0)
    highs = np.full(n, 101.0)
    lows = np.full(n, 99.0)
    closes = np.full(n, 100.0)
    volumes = np.full(n, 500.0)

    if sweep_type == "bearish":
        opens[sweep_at] = 100.9
        highs[sweep_at] = 101.5
        lows[sweep_at] = 99.5
        closes[sweep_at] = 100.8
    else:
        opens[sweep_at] = 99.1
        highs[sweep_at] = 100.5
        lows[sweep_at] = 98.5
        closes[sweep_at] = 99.2

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )


def _make_ohlcv_with_avwap_anchors(n: int = 80) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    base = np.linspace(100.0, 112.0, n)
    opens = base - 0.2
    closes = base + np.sin(np.linspace(0.0, 3.0 * np.pi, n)) * 0.25
    highs = np.maximum(opens, closes) + 0.6
    lows = np.minimum(opens, closes) - 0.6
    volumes = np.full(n, 100.0)

    pivot_low_idx = 20
    pivot_high_idx = 50
    spike_idx = 60

    lows[pivot_low_idx] = 90.0
    opens[pivot_low_idx] = 92.0
    closes[pivot_low_idx] = 93.0
    highs[pivot_low_idx] = 94.0

    highs[pivot_high_idx] = 125.0
    opens[pivot_high_idx] = 123.0
    closes[pivot_high_idx] = 124.0
    lows[pivot_high_idx] = 122.0

    volumes[spike_idx] = 400.0

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )


def _make_ohlcv_with_tpo_clusters() -> pd.DataFrame:
    n = 80
    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    cluster_a = np.full(60, 90.0)
    cluster_b = np.full(20, 110.0)
    closes = np.concatenate([cluster_a, cluster_b])
    opens = closes.copy()
    highs = closes + 0.5
    lows = closes - 0.5
    volumes = np.full(n, 200.0)

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )


def _make_pipeline_resolved_config(enabled_kernels: List[str], kernels: dict):
    from app.sr.config_schema import (
        EnhancementConfig,
        EnsembleConfig,
        LifecycleConfig,
        PipelineConfig,
        RegimeConfig,
        RuleDerivedConfig,
        SRResolvedConfig,
    )

    rule_derived = _default_rule_derived()
    return SRResolvedConfig(
        metadata=_default_metadata(),
        pipeline=PipelineConfig(enabled_kernels=enabled_kernels, atr_period=14),
        kernels=kernels,
        ensemble=EnsembleConfig(
            method="weighted_average",
            structural_vs_micro_ratio=0.5,
            kernel_weights={kernel_name: 1.0 for kernel_name in enabled_kernels},
            structural_kernels=["pivot_hl", "fractal_channel", "regression_band", "anchored_vwap"],
            micro_kernels=[
                "volume_poc",
                "tpo_value_area",
                "order_block",
                "fair_value_gap",
                "round_number",
                "session_gap",
                "liquidity_sweep",
            ],
        ),
        lifecycle=LifecycleConfig(
            breakout_confirm_bars=rule_derived.breakout_confirm_bars,
            false_breakout_window=rule_derived.false_breakout_window,
            inactivity_threshold=rule_derived.inactivity_threshold,
            max_active_zones=rule_derived.max_active_zones,
        ),
        enhancement=EnhancementConfig(),
        regime=RegimeConfig(enabled=False),
        rule_derived=rule_derived,
        rule_derived_config=RuleDerivedConfig(),
    )


def _default_metadata(*, has_gaps: bool = False) -> AssetMetadata:
    return AssetMetadata(
        profile="crypto",
        trading_hours_per_day=24.0,
        trading_days_per_week=7,
        has_session_gaps=has_gaps,
        gap_breakout_policy="gap_ignored",
        gap_escalation_atr=999.0,
        session_lookback_hours=[24, 168, 720],
        round_number_mode="decimal",
        ex_dividend_filter=False,
        continuous_market=not has_gaps,
    )


def _default_rule_derived() -> RuleDerivedParams:
    return RuleDerivedParams(
        n1=8, n2=6, fractal_period=16, fractal_buffer=0.2,
        round_interval=10.0, max_zone_width_atr=2.0,
        max_zone_width_pct=3.0, breakout_confirm_bars=3,
        false_breakout_window=6, inactivity_threshold=80,
        max_active_zones=10, volume_spike_threshold=1.5,
        vp_lookback_hours=[24, 168, 720],
    )


def _make_kernel_config(
    kernel_name: str,
    kernel_params: dict | None = None,
    has_gaps: bool = False,
    timeframe: str = "1h",
    **extra,
) -> KernelConfig:
    return KernelConfig(
        kernel_name=kernel_name,
        timeframe=timeframe,
        kernel_params=kernel_params or {},
        metadata=_default_metadata(has_gaps=has_gaps),
        rule_derived=_default_rule_derived(),
        extra=extra,
    )


@pytest.fixture
def ohlcv():
    return _make_ohlcv()


# ===================================================================
# 0. VOLUME POC KERNEL
# ===================================================================

class TestVolumePOCKernel:
    def test_registered(self):
        import app.sr.kernels.volume_poc  # noqa: F401
        assert KernelRegistry.has("volume_poc")

    def test_build_volume_profile_distributes_volume_across_spanned_bins(self):
        from app.sr.kernels.volume_poc import _build_volume_profile

        df = pd.DataFrame(
            {
                "open": [0.5, 1.5],
                "high": [1.9, 3.9],
                "low": [0.1, 1.1],
                "close": [1.0, 3.0],
                "volume": [4.0, 6.0],
            }
        )

        vp = _build_volume_profile(df, num_bins=4)

        assert np.allclose(vp["volumes"], np.array([2.0, 4.0, 2.0, 2.0]))
        assert vp["total_volume"] == pytest.approx(10.0)

    def test_emits_poc_vah_val(self, ohlcv):
        import app.sr.kernels.volume_poc  # noqa: F401
        kernel = KernelRegistry.create("volume_poc")
        config = _make_kernel_config("volume_poc")
        candidates = kernel.compute(ohlcv, config)

        vp_types = {candidate.metadata["vp_type"] for candidate in candidates}
        assert {"poc", "vah", "val"}.issubset(vp_types)

    def test_non_datetime_index_uses_deterministic_timestamp(self, ohlcv):
        import app.sr.kernels.volume_poc  # noqa: F401
        kernel = KernelRegistry.create("volume_poc")
        non_datetime = ohlcv.copy()
        non_datetime.index = range(len(non_datetime))
        config = _make_kernel_config("volume_poc")

        first = kernel.compute(non_datetime, config)
        second = kernel.compute(non_datetime, config)

        expected = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=len(non_datetime) - 1)
        assert first
        assert [candidate.timestamp for candidate in first] == [candidate.timestamp for candidate in second]
        assert all(candidate.timestamp.tzinfo is not None for candidate in first)
        assert first[0].timestamp == expected

    def test_non_datetime_lookback_uses_timeframe_bar_count(self):
        from app.sr.kernels.volume_poc import _get_lookback_data

        df = _make_ohlcv(n=400)
        df.index = range(len(df))

        lookback = _get_lookback_data(df, hours=24, timeframe="5m")
        assert len(lookback) == 288

    def test_naive_datetime_index_normalizes_timestamp_to_utc(self, ohlcv):
        import app.sr.kernels.volume_poc  # noqa: F401
        kernel = KernelRegistry.create("volume_poc")
        config = _make_kernel_config("volume_poc")

        candidates = kernel.compute(ohlcv, config)
        expected = ohlcv.index[-1].tz_localize(UTC).to_pydatetime()

        assert candidates
        assert candidates[0].timestamp == expected
        assert candidates[0].timestamp.tzinfo is not None


# ===================================================================
# 1. ROUND NUMBER KERNEL
# ===================================================================

class TestAnchoredVWAPKernel:
    def test_registered(self):
        import app.sr.kernels.anchored_vwap  # noqa: F401
        assert KernelRegistry.has("anchored_vwap")

    def test_emits_latest_pivot_and_volume_spike_anchors(self):
        import app.sr.kernels.anchored_vwap  # noqa: F401

        kernel = KernelRegistry.create("anchored_vwap")
        df = _make_ohlcv_with_avwap_anchors()
        config = _make_kernel_config("anchored_vwap")

        candidates = kernel.compute(df, config)

        anchor_types = {candidate.metadata["anchor_type"] for candidate in candidates}
        assert {"pivot_low", "pivot_high", "volume_spike"}.issubset(anchor_types)
        assert all(candidate.kernel_name == "anchored_vwap" for candidate in candidates)
        assert all(candidate.timestamp.tzinfo is not None for candidate in candidates)

    def test_volume_spike_mode_respects_multiplier(self):
        import app.sr.kernels.anchored_vwap  # noqa: F401

        kernel = KernelRegistry.create("anchored_vwap")
        df = _make_ohlcv_with_avwap_anchors()
        config = _make_kernel_config(
            "anchored_vwap",
            {"anchor_type": "volume_spike", "volume_spike_multiplier": 3.0},
        )

        candidates = kernel.compute(df, config)

        assert len(candidates) == 1
        assert candidates[0].metadata["anchor_type"] == "volume_spike"


class TestTPOValueAreaKernel:
    def test_registered(self):
        import app.sr.kernels.tpo_value_area  # noqa: F401
        assert KernelRegistry.has("tpo_value_area")

    def test_emits_poc_vah_val(self):
        import app.sr.kernels.tpo_value_area  # noqa: F401

        kernel = KernelRegistry.create("tpo_value_area")
        df = _make_ohlcv_with_tpo_clusters()
        config = _make_kernel_config("tpo_value_area", {"tpo_window_bars": 40})

        candidates = kernel.compute(df, config)

        tpo_types = {candidate.metadata["tpo_type"] for candidate in candidates}
        assert {"poc", "vah", "val"}.issubset(tpo_types)
        assert all(isinstance(candidate.metadata["naked"], bool) for candidate in candidates)
        assert all(candidate.kernel_name == "tpo_value_area" for candidate in candidates)

    def test_window_bars_controls_profile_focus(self):
        import app.sr.kernels.tpo_value_area  # noqa: F401

        kernel = KernelRegistry.create("tpo_value_area")
        df = _make_ohlcv_with_tpo_clusters()
        short_candidates = kernel.compute(df, _make_kernel_config("tpo_value_area", {"tpo_window_bars": 20}))
        long_candidates = kernel.compute(df, _make_kernel_config("tpo_value_area", {"tpo_window_bars": 80}))

        short_poc = next(candidate.center_price for candidate in short_candidates if candidate.metadata["tpo_type"] == "poc")
        long_poc = next(candidate.center_price for candidate in long_candidates if candidate.metadata["tpo_type"] == "poc")

        assert short_poc > long_poc


class TestOrthogonalKernelConfigAndPipeline:
    def test_resolver_applies_tpo_per_tf_override(self):
        from app.sr.config_resolver import SRConfigResolver

        resolver = SRConfigResolver()
        resolved = resolver.resolve(
            "BTCUSDT",
            "30m",
            {
                "asset_metadata": {"assets": {"BTCUSDT": {"profile": "crypto"}}},
                "sr": {
                    "pipeline": {"enabled_kernels": ["tpo_value_area"]},
                    "kernels": {
                        "tpo_value_area": {
                            "tpo_window_bars": 120,
                            "tpo_value_area_pct": 0.68,
                        }
                    },
                },
                "per_tf": {
                    "30m": {
                        "kernels": {
                            "tpo_value_area": {"tpo_window_bars": 240}
                        }
                    }
                },
            },
        )

        assert resolved.kernels["tpo_value_area"]["tpo_window_bars"] == 240

    def test_pipeline_scores_candidates_from_new_kernels(self):
        from app.sr.pipeline import SRv2Pipeline

        config = _make_pipeline_resolved_config(
            ["anchored_vwap", "tpo_value_area"],
            {
                "anchored_vwap": {"anchor_type": "hybrid", "volume_spike_multiplier": 2.0},
                "tpo_value_area": {"tpo_window_bars": 40, "tpo_value_area_pct": 0.68},
            },
        )
        pipeline = SRv2Pipeline(config, asset="BTCUSDT", timeframe="1h")

        result = pipeline.run(_make_ohlcv_with_avwap_anchors(), bar_index=0)

        assert any(candidate.kernel_name == "anchored_vwap" for candidate in result.candidates)
        assert any(candidate.kernel_name == "tpo_value_area" for candidate in result.candidates)
        assert result.scored_levels

class TestRoundNumberKernel:
    def test_registered(self):
        import app.sr.kernels.round_number  # noqa: F401
        assert KernelRegistry.has("round_number")

    def test_compute_returns_candidates(self, ohlcv):
        import app.sr.kernels.round_number  # noqa: F401
        kernel = KernelRegistry.create("round_number")
        config = _make_kernel_config("round_number")
        candidates = kernel.compute(ohlcv, config)
        assert isinstance(candidates, list)
        assert len(candidates) > 0
        for c in candidates:
            assert c.kernel_name == "round_number"
            interval = c.metadata["interval"]
            assert c.center_price / interval == pytest.approx(round(c.center_price / interval))

    def test_levels_around_current_price(self, ohlcv):
        import app.sr.kernels.round_number  # noqa: F401
        kernel = KernelRegistry.create("round_number")
        config = _make_kernel_config("round_number")
        candidates = kernel.compute(ohlcv, config)
        current_price = float(ohlcv["close"].iloc[-1])
        # Should have both support (below) and resistance (above)
        supports = [c for c in candidates if c.level_type == LevelType.SUPPORT]
        resistances = [c for c in candidates if c.level_type == LevelType.RESISTANCE]
        assert len(supports) > 0
        assert len(resistances) > 0

    def test_max_levels_respected(self, ohlcv):
        import app.sr.kernels.round_number  # noqa: F401
        kernel = KernelRegistry.create("round_number")
        config = _make_kernel_config("round_number", {"max_levels": 5})
        candidates = kernel.compute(ohlcv, config)
        assert len(candidates) <= 5

    def test_empty_for_short_data(self):
        import app.sr.kernels.round_number  # noqa: F401
        kernel = KernelRegistry.create("round_number")
        config = _make_kernel_config("round_number")
        short_df = _make_ohlcv(n=5)
        assert kernel.compute(short_df, config) == []

    def test_score_decays_with_distance(self, ohlcv):
        import app.sr.kernels.round_number  # noqa: F401
        kernel = KernelRegistry.create("round_number")
        config = _make_kernel_config("round_number")
        candidates = kernel.compute(ohlcv, config)
        current_price = float(ohlcv["close"].iloc[-1])
        # Sort by distance
        sorted_cands = sorted(candidates, key=lambda c: abs(c.center_price - current_price))
        if len(sorted_cands) >= 2:
            assert sorted_cands[0].raw_score >= sorted_cands[-1].raw_score

    def test_uses_pip_spacing_for_fx_metadata(self):
        import app.sr.kernels.round_number  # noqa: F401
        kernel = KernelRegistry.create("round_number")
        fx_metadata = AssetMetadata(
            profile="fx",
            trading_hours_per_day=24.0,
            trading_days_per_week=5,
            has_session_gaps=False,
            gap_breakout_policy="gap_ignored",
            gap_escalation_atr=999.0,
            session_lookback_hours=[24, 120, 504],
            round_number_mode="pip",
            ex_dividend_filter=False,
            continuous_market=True,
        )
        config = KernelConfig(
            kernel_name="round_number",
            timeframe="1h",
            kernel_params={"max_levels": 6, "score_skip_threshold": 0.0},
            metadata=fx_metadata,
            rule_derived=_default_rule_derived(),
        )

        candidates = kernel.compute(_make_ohlcv(n=40, base_price=1.0834, volatility=0.001), config)

        assert candidates
        assert {candidate.metadata["interval"] for candidate in candidates} == {0.01}
        assert any(candidate.center_price == pytest.approx(1.08) for candidate in candidates)

    def test_non_datetime_index_uses_deterministic_timestamp(self, ohlcv):
        import app.sr.kernels.round_number  # noqa: F401
        kernel = KernelRegistry.create("round_number")
        config = _make_kernel_config("round_number")
        non_datetime = ohlcv.reset_index(drop=True)

        first = kernel.compute(non_datetime, config)
        second = kernel.compute(non_datetime, config)

        assert first
        expected_timestamp = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=len(non_datetime) - 1)
        assert first[0].timestamp == second[0].timestamp == expected_timestamp


# ===================================================================
# 2. ORDER BLOCK KERNEL
# ===================================================================

class TestOrderBlockKernel:
    def test_registered(self):
        import app.sr.kernels.order_block  # noqa: F401
        assert KernelRegistry.has("order_block")

    def test_compute_with_displacement(self):
        import app.sr.kernels.order_block  # noqa: F401
        kernel = KernelRegistry.create("order_block")
        df = _make_ohlcv_with_displacement(displacement_atr_mult=3.0)
        config = _make_kernel_config("order_block")
        candidates = kernel.compute(df, config)
        assert isinstance(candidates, list)
        assert len(candidates) > 0
        for c in candidates:
            assert c.kernel_name == "order_block"
            assert c.level_type in (LevelType.SUPPORT, LevelType.RESISTANCE)

    def test_bullish_ob_is_support(self):
        import app.sr.kernels.order_block  # noqa: F401
        kernel = KernelRegistry.create("order_block")
        df = _make_ohlcv_with_displacement(displacement_atr_mult=3.0)
        config = _make_kernel_config("order_block")
        candidates = kernel.compute(df, config)
        bullish = [c for c in candidates if c.metadata.get("ob_type") == "bullish"]
        for c in bullish:
            assert c.level_type == LevelType.SUPPORT

    def test_bearish_ob_is_resistance(self):
        import app.sr.kernels.order_block  # noqa: F401

        kernel = KernelRegistry.create("order_block")
        df = _make_ohlcv_with_displacement(displacement_atr_mult=3.0, direction="bearish")
        config = _make_kernel_config("order_block")
        candidates = kernel.compute(df, config)
        bearish = [c for c in candidates if c.metadata.get("ob_type") == "bearish"]

        assert len(bearish) > 0
        for c in bearish:
            assert c.level_type == LevelType.RESISTANCE

    def test_latest_bar_displacement_is_included(self):
        import app.sr.kernels.order_block  # noqa: F401

        kernel = KernelRegistry.create("order_block")
        df = _make_ohlcv_with_displacement(
            n=120,
            displacement_at=119,
            displacement_atr_mult=3.0,
        )
        config = _make_kernel_config("order_block")
        candidates = kernel.compute(df, config)

        assert any(c.metadata.get("ob_index") == 118 for c in candidates)

    def test_zone_bounds_from_ob_candle(self):
        import app.sr.kernels.order_block  # noqa: F401
        kernel = KernelRegistry.create("order_block")
        df = _make_ohlcv_with_displacement(displacement_atr_mult=3.0)
        config = _make_kernel_config("order_block")
        candidates = kernel.compute(df, config)
        for c in candidates:
            # Zone bounds should be the OB candle high/low
            assert c.upper_bound > c.lower_bound
            assert c.lower_bound <= c.center_price <= c.upper_bound

    def test_no_displacement_no_candidates(self):
        """Very small moves shouldn't produce order blocks."""
        import app.sr.kernels.order_block  # noqa: F401
        kernel = KernelRegistry.create("order_block")
        # Use very low volatility data — no displacement
        df = _make_ohlcv(volatility=0.001, seed=99)
        config = _make_kernel_config("order_block", {"displacement_atr": 5.0})
        candidates = kernel.compute(df, config)
        # With very high threshold, should find few/no candidates
        assert len(candidates) < 5


# ===================================================================
# 3. FAIR VALUE GAP KERNEL
# ===================================================================

class TestFairValueGapKernel:
    def test_registered(self):
        import app.sr.kernels.fair_value_gap  # noqa: F401
        assert KernelRegistry.has("fair_value_gap")

    def test_detect_bullish_fvg(self):
        import app.sr.kernels.fair_value_gap  # noqa: F401
        kernel = KernelRegistry.create("fair_value_gap")
        df = _make_ohlcv_with_fvg(fvg_at=100)
        config = _make_kernel_config("fair_value_gap")
        candidates = kernel.compute(df, config)
        assert isinstance(candidates, list)
        bullish = [c for c in candidates if c.metadata.get("fvg_type") == "bullish"]
        assert len(bullish) > 0
        for c in bullish:
            assert c.level_type == LevelType.SUPPORT
            assert c.upper_bound > c.lower_bound

    def test_gap_size_in_metadata(self):
        import app.sr.kernels.fair_value_gap  # noqa: F401
        kernel = KernelRegistry.create("fair_value_gap")
        df = _make_ohlcv_with_fvg(fvg_at=100)
        config = _make_kernel_config("fair_value_gap")
        candidates = kernel.compute(df, config)
        for c in candidates:
            assert "gap_atr" in c.metadata
            assert c.metadata["gap_atr"] > 0

    def test_filled_fvg_has_lower_score(self):
        import app.sr.kernels.fair_value_gap  # noqa: F401
        kernel = KernelRegistry.create("fair_value_gap")
        df = _make_ohlcv_with_fvg(fvg_at=50)  # early FVG — likely filled by later bars
        config = _make_kernel_config("fair_value_gap")
        candidates = kernel.compute(df, config)
        filled = [c for c in candidates if c.metadata.get("filled")]
        unfilled = [c for c in candidates if not c.metadata.get("filled")]
        if filled and unfilled:
            # Filled should have lower average score
            avg_filled = sum(c.raw_score for c in filled) / len(filled)
            avg_unfilled = sum(c.raw_score for c in unfilled) / len(unfilled)
            assert avg_filled <= avg_unfilled

    def test_score_bounded(self):
        import app.sr.kernels.fair_value_gap  # noqa: F401
        kernel = KernelRegistry.create("fair_value_gap")
        df = _make_ohlcv_with_fvg()
        config = _make_kernel_config("fair_value_gap")
        candidates = kernel.compute(df, config)
        for c in candidates:
            assert 0.0 <= c.raw_score <= 1.0

    def test_fill_threshold_changes_fill_detection(self):
        """Looser fill_threshold marks more FVGs as filled than stricter one."""
        import app.sr.kernels.fair_value_gap  # noqa: F401
        kernel = KernelRegistry.create("fair_value_gap")

        df = _make_ohlcv_with_fvg(fvg_at=50)  # early FVG — partial fill likely

        # Loose threshold → more gaps counted as filled
        config_loose = _make_kernel_config(
            "fair_value_gap",
            kernel_params={"fill_threshold": 0.1},
        )
        candidates_loose = kernel.compute(df, config_loose)
        filled_loose = [c for c in candidates_loose if c.metadata.get("filled")]

        # Strict threshold → fewer gaps counted as filled
        config_strict = _make_kernel_config(
            "fair_value_gap",
            kernel_params={"fill_threshold": 0.9},
        )
        candidates_strict = kernel.compute(df, config_strict)
        filled_strict = [c for c in candidates_strict if c.metadata.get("filled")]

        assert len(filled_loose) >= len(filled_strict)


# ===================================================================
# 4. SESSION GAP KERNEL
# ===================================================================

class TestSessionGapKernel:
    def test_registered(self):
        import app.sr.kernels.session_gap  # noqa: F401
        assert KernelRegistry.has("session_gap")

    def test_noop_for_continuous_market(self, ohlcv):
        """Continuous markets (no session gaps) → empty result."""
        import app.sr.kernels.session_gap  # noqa: F401
        kernel = KernelRegistry.create("session_gap")
        config = _make_kernel_config("session_gap", has_gaps=False)
        candidates = kernel.compute(ohlcv, config)
        assert candidates == []

    def test_detects_gaps_for_equity(self):
        """Non-continuous market with gaps → produces candidates."""
        import app.sr.kernels.session_gap  # noqa: F401
        kernel = KernelRegistry.create("session_gap")
        df = _make_ohlcv_with_gaps(
            gap_indices=[50, 100, 150],
            gap_size_pct=0.05,
        )
        config = _make_kernel_config("session_gap", has_gaps=True)
        candidates = kernel.compute(df, config)
        assert len(candidates) > 0
        for c in candidates:
            assert c.kernel_name == "session_gap"
            assert "gap_role" in c.metadata

    def test_gap_produces_origin_and_destination(self):
        import app.sr.kernels.session_gap  # noqa: F401
        kernel = KernelRegistry.create("session_gap")
        df = _make_ohlcv_with_gaps(gap_indices=[100], gap_size_pct=0.05)
        config = _make_kernel_config("session_gap", has_gaps=True)
        candidates = kernel.compute(df, config)
        roles = {c.metadata["gap_role"] for c in candidates}
        assert "origin" in roles
        assert "destination" in roles

    def test_fill_levels_emitted(self):
        import app.sr.kernels.session_gap  # noqa: F401
        kernel = KernelRegistry.create("session_gap")
        df = _make_ohlcv_with_gaps(gap_indices=[100], gap_size_pct=0.05)
        config = _make_kernel_config(
            "session_gap",
            {"fill_level_fractions": [0.5]},
            has_gaps=True,
        )
        candidates = kernel.compute(df, config)
        fill_cands = [c for c in candidates if "fill" in c.metadata.get("gap_role", "")]
        assert len(fill_cands) > 0

    def test_ignores_intraday_price_jump_without_session_break(self):
        import app.sr.kernels.session_gap  # noqa: F401
        kernel = KernelRegistry.create("session_gap")
        df = _make_ohlcv(n=80, base_price=100.0)
        opens = df["open"].values.copy()
        closes = df["close"].values.copy()
        highs = df["high"].values.copy()
        lows = df["low"].values.copy()

        jump_index = 40
        opens[jump_index] = closes[jump_index - 1] * 1.05
        closes[jump_index] = opens[jump_index] * 1.005
        highs[jump_index] = max(highs[jump_index], opens[jump_index], closes[jump_index])
        lows[jump_index] = min(lows[jump_index], opens[jump_index], closes[jump_index])

        df["open"] = opens
        df["close"] = closes
        df["high"] = highs
        df["low"] = lows

        config = _make_kernel_config("session_gap", has_gaps=True)
        assert kernel.compute(df, config) == []

    def test_numeric_index_uses_deterministic_timestamp_fallback(self):
        import app.sr.kernels.session_gap  # noqa: F401
        kernel = KernelRegistry.create("session_gap")
        df = _make_ohlcv_with_gaps(gap_indices=[100], gap_size_pct=0.05)

        numeric_index = np.arange(len(df), dtype=int)
        numeric_index[100:] += 18
        df.index = numeric_index

        config = _make_kernel_config("session_gap", has_gaps=True)
        candidates = kernel.compute(df, config)

        assert len(candidates) > 0
        assert candidates[0].timestamp == datetime(1970, 1, 1, 0, 1, 58, tzinfo=UTC)


# ===================================================================
# 5. FRACTAL CHANNEL KERNEL
# ===================================================================

class TestFractalChannelKernel:
    def test_registered(self):
        import app.sr.kernels.fractal_channel  # noqa: F401
        assert KernelRegistry.has("fractal_channel")

    def test_returns_list(self, ohlcv):
        """Kernel returns list (may be empty if no valid channel is available)."""
        import app.sr.kernels.fractal_channel  # noqa: F401
        kernel = KernelRegistry.create("fractal_channel")
        config = _make_kernel_config("fractal_channel")
        candidates = kernel.compute(ohlcv, config)
        assert isinstance(candidates, list)

    def test_candidates_have_correct_type(self, ohlcv):
        import app.sr.kernels.fractal_channel  # noqa: F401
        kernel = KernelRegistry.create("fractal_channel")
        config = _make_kernel_config("fractal_channel")
        candidates = kernel.compute(ohlcv, config)
        for c in candidates:
            assert isinstance(c, CandidateLevel)
            assert c.kernel_name == "fractal_channel"
            assert c.level_type in (LevelType.SUPPORT, LevelType.RESISTANCE)

    def test_empty_for_short_data(self):
        import app.sr.kernels.fractal_channel  # noqa: F401
        kernel = KernelRegistry.create("fractal_channel")
        config = _make_kernel_config("fractal_channel")
        short_df = _make_ohlcv(n=10)
        assert kernel.compute(short_df, config) == []

    def test_uses_exact_output_columns_for_requested_lookback(self, ohlcv, monkeypatch):
        import app.indicators.fractal_channel as fc_module
        import app.sr.kernels.fractal_channel  # noqa: F401

        class FakeFractalChannel:
            def __init__(self, *args, **kwargs):
                pass

            def calculate(self, df, **kwargs):
                result = pd.DataFrame(index=df.index)
                result["fc_upper_32_geometric"] = np.nan
                result["fc_lower_32_geometric"] = np.nan
                result["fc_upper_16_geometric"] = np.nan
                result["fc_lower_16_geometric"] = np.nan
                result.iloc[-1, result.columns.get_loc("fc_upper_32_geometric")] = 130.0
                result.iloc[-1, result.columns.get_loc("fc_lower_32_geometric")] = 90.0
                result.iloc[-1, result.columns.get_loc("fc_upper_16_geometric")] = 999.0
                result.iloc[-1, result.columns.get_loc("fc_lower_16_geometric")] = 1.0
                return result

        monkeypatch.setattr(fc_module, "FractalChannel", FakeFractalChannel)

        kernel = KernelRegistry.create("fractal_channel")
        config = _make_kernel_config("fractal_channel", {"channel_lookback": 32})
        candidates = kernel.compute(ohlcv, config)
        centers = {c.metadata["channel_role"]: c.center_price for c in candidates}

        assert centers["upper"] == 130.0
        assert centers["lower"] == 90.0

    def test_uses_rule_derived_buffer_when_enabled(self, ohlcv, monkeypatch):
        import app.indicators.fractal_channel as fc_module
        import app.sr.kernels.fractal_channel  # noqa: F401

        class FakeFractalChannel:
            def __init__(self, *args, **kwargs):
                pass

            def calculate(self, df, **kwargs):
                result = pd.DataFrame(index=df.index)
                result["fc_upper_32_geometric"] = np.nan
                result["fc_lower_32_geometric"] = np.nan
                result.iloc[-1, result.columns.get_loc("fc_upper_32_geometric")] = 130.0
                result.iloc[-1, result.columns.get_loc("fc_lower_32_geometric")] = 90.0
                return result

        monkeypatch.setattr(fc_module, "FractalChannel", FakeFractalChannel)

        kernel = KernelRegistry.create("fractal_channel")
        config = _make_kernel_config(
            "fractal_channel",
            {"channel_lookback": 32, "boundary_buffer_atr": 999.0, "use_rule_derived_buffer": True},
        )
        candidates = kernel.compute(ohlcv, config)
        by_role = {c.metadata["channel_role"]: c for c in candidates}

        assert by_role["upper"].lower_bound == pytest.approx(129.8)
        assert by_role["upper"].upper_bound == pytest.approx(130.2)
        assert by_role["lower"].lower_bound == pytest.approx(89.8)
        assert by_role["lower"].upper_bound == pytest.approx(90.2)

    def test_propagates_unexpected_indicator_errors(self, ohlcv, monkeypatch):
        import app.indicators.fractal_channel as fc_module
        import app.sr.kernels.fractal_channel  # noqa: F401

        class FakeFractalChannel:
            def __init__(self, *args, **kwargs):
                pass

            def calculate(self, df, **kwargs):
                raise RuntimeError("boom")

        monkeypatch.setattr(fc_module, "FractalChannel", FakeFractalChannel)

        kernel = KernelRegistry.create("fractal_channel")
        config = _make_kernel_config("fractal_channel")

        with pytest.raises(RuntimeError, match="boom"):
            kernel.compute(ohlcv, config)


# ===================================================================
# 6. REGRESSION BAND KERNEL
# ===================================================================

class TestRegressionBandKernel:
    def test_registered(self):
        import app.sr.kernels.regression_band  # noqa: F401
        assert KernelRegistry.has("regression_band")

    def test_fallback_regression(self, ohlcv):
        """Without pre-computed result, uses simple OLS fallback."""
        import app.sr.kernels.regression_band  # noqa: F401
        kernel = KernelRegistry.create("regression_band")
        config = _make_kernel_config("regression_band")
        candidates = kernel.compute(ohlcv, config)
        assert isinstance(candidates, list)
        assert len(candidates) == 2  # upper + lower
        types = {c.level_type for c in candidates}
        assert LevelType.RESISTANCE in types
        assert LevelType.SUPPORT in types

    def test_uses_inline_regression_when_asset_context_present(self, ohlcv, monkeypatch):
        import app.sr.kernels.regression_band as regression_band

        kernel = KernelRegistry.create("regression_band")

        class MockResult:
            upper_band = np.array([120.0, 121.0])
            lower_band = np.array([80.0, 79.0])
            mid_line = np.array([100.0, 100.0])
            confidence = 0.75
            is_valid = True
            timestamp = datetime(2025, 1, 2)

        monkeypatch.setattr(
            regression_band,
            "_compute_inline_regression_result",
            lambda df, config, band_width_sigma: MockResult(),
        )

        config = _make_kernel_config("regression_band", asset="BTCUSDT")
        candidates = kernel.compute(ohlcv, config)

        upper = [c for c in candidates if c.metadata["band_role"] == "upper"][0]
        lower = [c for c in candidates if c.metadata["band_role"] == "lower"][0]
        assert abs(upper.center_price - 121.0) < 0.01
        assert abs(lower.center_price - 79.0) < 0.01
        assert upper.timestamp.tzinfo is not None

    def test_upper_above_lower(self, ohlcv):
        import app.sr.kernels.regression_band  # noqa: F401
        kernel = KernelRegistry.create("regression_band")
        config = _make_kernel_config("regression_band")
        candidates = kernel.compute(ohlcv, config)
        upper = [c for c in candidates if c.metadata.get("band_role") == "upper"][0]
        lower = [c for c in candidates if c.metadata.get("band_role") == "lower"][0]
        assert upper.center_price > lower.center_price

    def test_with_precomputed_result(self, ohlcv):
        import app.sr.kernels.regression_band  # noqa: F401
        kernel = KernelRegistry.create("regression_band")

        # Mock regression result with upper_band / lower_band / mid_line arrays
        class MockResult:
            upper_band = np.array([110.0, 111.0, 112.0])
            lower_band = np.array([90.0, 89.0, 88.0])
            mid_line = np.array([100.0, 100.0, 100.0])
            confidence = 0.8

        config = _make_kernel_config(
            "regression_band",
            regression_result=MockResult(),
        )
        candidates = kernel.compute(ohlcv, config)
        assert len(candidates) == 2
        # Should use last values from the mock
        upper = [c for c in candidates if c.metadata["band_role"] == "upper"][0]
        lower = [c for c in candidates if c.metadata["band_role"] == "lower"][0]
        assert abs(upper.center_price - 112.0) < 0.01
        assert abs(lower.center_price - 88.0) < 0.01

    def test_emit_center(self, ohlcv):
        import app.sr.kernels.regression_band  # noqa: F401
        kernel = KernelRegistry.create("regression_band")
        config = _make_kernel_config("regression_band", {"emit_center": True})
        candidates = kernel.compute(ohlcv, config)
        assert len(candidates) == 3  # upper + lower + center
        center = [c for c in candidates if c.metadata["band_role"] == "center"]
        assert len(center) == 1

    def test_invalid_precomputed_result_falls_back(self, ohlcv, monkeypatch):
        import app.sr.kernels.regression_band as regression_band

        kernel = KernelRegistry.create("regression_band")

        class InvalidResult:
            upper_band = np.array([999.0])
            lower_band = np.array([1.0])
            mid_line = np.array([500.0])
            confidence = 0.95
            is_valid = False

        monkeypatch.setattr(
            regression_band.RegressionBandKernel,
            "_simple_regression_bands",
            staticmethod(lambda df, sigma: (130.0, 120.0, 110.0, 0.6)),
        )

        config = _make_kernel_config(
            "regression_band",
            regression_result=InvalidResult(),
        )
        candidates = kernel.compute(ohlcv, config)

        upper = [c for c in candidates if c.metadata["band_role"] == "upper"][0]
        lower = [c for c in candidates if c.metadata["band_role"] == "lower"][0]
        assert abs(upper.center_price - 130.0) < 0.01
        assert abs(lower.center_price - 110.0) < 0.01

    def test_center_line_type_tracks_price_location(self, ohlcv):
        import app.sr.kernels.regression_band  # noqa: F401

        kernel = KernelRegistry.create("regression_band")

        class MockResult:
            upper_band = np.array([125.0])
            lower_band = np.array([75.0])
            mid_line = np.array([ohlcv["close"].iloc[-1] + 5.0])
            confidence = 0.8
            is_valid = True

        config = _make_kernel_config(
            "regression_band",
            {"emit_center": True},
            regression_result=MockResult(),
        )
        candidates = kernel.compute(ohlcv, config)
        center = [c for c in candidates if c.metadata["band_role"] == "center"][0]
        assert center.level_type == LevelType.RESISTANCE

    def test_non_datetime_index_uses_deterministic_timestamp(self, ohlcv):
        import app.sr.kernels.regression_band  # noqa: F401

        kernel = KernelRegistry.create("regression_band")
        ranged = ohlcv.reset_index(drop=True)
        config = _make_kernel_config("regression_band")

        first = kernel.compute(ranged, config)
        second = kernel.compute(ranged, config)

        assert len(first) == len(second) == 2
        assert all(candidate.timestamp.tzinfo is not None for candidate in first)
        assert [candidate.timestamp for candidate in first] == [candidate.timestamp for candidate in second]

    def test_empty_for_short_data(self):
        import app.sr.kernels.regression_band  # noqa: F401
        kernel = KernelRegistry.create("regression_band")
        config = _make_kernel_config("regression_band")
        short_df = _make_ohlcv(n=10)
        assert kernel.compute(short_df, config) == []


# ===================================================================
# 7. LIQUIDITY SWEEP KERNEL
# ===================================================================

class TestLiquiditySweepKernel:
    def test_detects_bearish_sweep_on_latest_bar(self):
        import app.sr.kernels.liquidity_sweep  # noqa: F401

        kernel = KernelRegistry.create("liquidity_sweep")
        df = _make_ohlcv_with_liquidity_sweep(n=60, sweep_at=59, sweep_type="bearish")
        config = _make_kernel_config("liquidity_sweep", {"sweep_lookback": 10})

        candidates = kernel.compute(df, config)
        bearish = [c for c in candidates if c.metadata.get("sweep_type") == "bearish"]

        assert len(bearish) == 1
        assert bearish[0].center_price == pytest.approx(101.0)
        expected_ts = df.index[-1].to_pydatetime().replace(tzinfo=__import__("datetime").timezone.utc)
        assert bearish[0].timestamp == expected_ts

    def test_detects_bullish_sweep(self):
        import app.sr.kernels.liquidity_sweep  # noqa: F401

        kernel = KernelRegistry.create("liquidity_sweep")
        df = _make_ohlcv_with_liquidity_sweep(n=60, sweep_at=40, sweep_type="bullish")
        config = _make_kernel_config("liquidity_sweep", {"sweep_lookback": 10})

        candidates = kernel.compute(df, config)
        bullish = [c for c in candidates if c.metadata.get("sweep_type") == "bullish"]

        assert len(bullish) == 1
        assert bullish[0].center_price == pytest.approx(99.0)

    def test_max_age_bars_controls_search_horizon(self):
        import app.sr.kernels.liquidity_sweep  # noqa: F401

        kernel = KernelRegistry.create("liquidity_sweep")
        df = _make_ohlcv_with_liquidity_sweep(n=260, sweep_at=30, sweep_type="bearish")

        narrow = _make_kernel_config(
            "liquidity_sweep",
            {"sweep_lookback": 10, "max_age_bars": 20},
        )
        wide = _make_kernel_config(
            "liquidity_sweep",
            {"sweep_lookback": 10, "max_age_bars": 260},
        )

        assert kernel.compute(df, narrow) == []
        assert any(c.metadata.get("sweep_type") == "bearish" for c in kernel.compute(df, wide))

    def test_empty_for_short_data(self):
        import app.sr.kernels.liquidity_sweep  # noqa: F401

        kernel = KernelRegistry.create("liquidity_sweep")
        config = _make_kernel_config("liquidity_sweep")
        short_df = _make_ohlcv(n=10)
        assert kernel.compute(short_df, config) == []


# ===================================================================
# 8. KERNEL REGISTRY — ALL PHASE 3 KERNELS
# ===================================================================

class TestKernelRegistryPhase3:
    def test_all_phase3_kernels_registered(self):
        import app.sr.kernels.round_number  # noqa: F401
        import app.sr.kernels.order_block  # noqa: F401
        import app.sr.kernels.fair_value_gap  # noqa: F401
        import app.sr.kernels.session_gap  # noqa: F401
        import app.sr.kernels.fractal_channel  # noqa: F401
        import app.sr.kernels.regression_band  # noqa: F401
        import app.sr.kernels.liquidity_sweep  # noqa: F401

        expected = [
            "round_number", "order_block", "fair_value_gap",
            "session_gap", "fractal_channel", "regression_band",
            "liquidity_sweep",
        ]
        for name in expected:
            assert KernelRegistry.has(name), f"Kernel {name} not registered"

    def test_all_produce_candidate_levels(self, ohlcv):
        import app.sr.kernels.round_number  # noqa: F401
        import app.sr.kernels.order_block  # noqa: F401
        import app.sr.kernels.fair_value_gap  # noqa: F401
        import app.sr.kernels.fractal_channel  # noqa: F401
        import app.sr.kernels.regression_band  # noqa: F401

        for name in ["round_number", "regression_band"]:
            kernel = KernelRegistry.create(name)
            config = _make_kernel_config(name)
            result = kernel.compute(ohlcv, config)
            assert isinstance(result, list)
            for c in result:
                assert isinstance(c, CandidateLevel)


# ===================================================================
# 8. UNIVERSE CONFIG
# ===================================================================

class TestUniverseSRConfig:
    def test_from_dict(self):
        from app.sr.universe.config import UniverseSRConfig, AssetSRConfig
        d = {
            "assets": [
                {"symbol": "BTCUSDT", "timeframes": ["1h", "4h"]},
                {"symbol": "ETHUSDT"},
            ],
            "max_workers": 2,
            "default_timeframes": ["1h"],
            "global_config": {"ensemble": {"method": "weighted_average"}},
            "timeframe_overrides": {"4h": {"ensemble": {"method": "regime_conditional"}}},
        }
        config = UniverseSRConfig.from_dict(d)
        assert len(config.assets) == 2
        assert config.assets[0].symbol == "BTCUSDT"
        assert config.assets[0].timeframes == ["1h", "4h"]
        assert config.max_workers == 2
        assert config.global_config["ensemble"]["method"] == "weighted_average"

    def test_defaults(self):
        from app.sr.universe.config import UniverseSRConfig
        config = UniverseSRConfig()
        assert config.max_workers == 4
        assert config.default_timeframes == ["1h"]
        assert config.cross_asset_enabled is False

    def test_asset_config_overrides(self):
        from app.sr.universe.config import AssetSRConfig
        acfg = AssetSRConfig(
            symbol="BTCUSDT",
            enabled_kernels=["pivot_hl", "round_number"],
            config_overrides={"lifecycle": {"min_strength": 0.4}},
        )
        assert acfg.enabled_kernels == ["pivot_hl", "round_number"]
        assert acfg.config_overrides["lifecycle"]["min_strength"] == 0.4


# ===================================================================
# 9. UNIVERSE ROUTER
# ===================================================================

class TestUniverseSRRouter:
    def _make_router(self, assets=None):
        from app.sr.universe.config import UniverseSRConfig, AssetSRConfig
        from app.sr.universe.router import UniverseSRRouter

        if assets is None:
            assets = [
                AssetSRConfig(symbol="BTCUSDT", timeframes=["1h"]),
                AssetSRConfig(symbol="ETHUSDT", timeframes=["1h"]),
            ]
        config = UniverseSRConfig(
            assets=assets,
            max_workers=1,  # Sequential for deterministic tests
            global_config={
                "pipeline": {"enabled_kernels": ["pivot_hl", "round_number"]},
            },
        )
        return UniverseSRRouter(config)

    def test_global_enabled_kernels_reach_resolver(self):
        from app.sr.universe.config import AssetSRConfig, UniverseSRConfig
        from app.sr.universe.router import UniverseSRRouter

        asset = AssetSRConfig(symbol="BTCUSDT", timeframes=["1h"])
        router = UniverseSRRouter(
            UniverseSRConfig(
                assets=[asset],
                max_workers=1,
                global_config={
                    "pipeline": {"enabled_kernels": ["round_number"]},
                },
            ),
        )

        pipeline = router._get_or_create_pipeline("BTCUSDT", "1h", asset)
        assert pipeline._config.pipeline.enabled_kernels == ["round_number"]

    def test_asset_config_overrides_reach_resolver(self):
        from app.sr.universe.config import AssetSRConfig, UniverseSRConfig
        from app.sr.universe.router import UniverseSRRouter

        asset = AssetSRConfig(
            symbol="BTCUSDT",
            timeframes=["1h"],
            config_overrides={"lifecycle": {"min_strength": 0.4}},
        )
        router = UniverseSRRouter(
            UniverseSRConfig(
                assets=[asset],
                max_workers=1,
                global_config={"lifecycle": {"min_strength": 0.2}},
            ),
        )

        pipeline = router._get_or_create_pipeline("BTCUSDT", "1h", asset)
        assert pipeline._config.lifecycle.min_strength == 0.4

    def test_disabled_kernels_filter_resolved_pipeline(self):
        from app.sr.universe.config import AssetSRConfig, UniverseSRConfig
        from app.sr.universe.router import UniverseSRRouter

        asset = AssetSRConfig(
            symbol="BTCUSDT",
            timeframes=["1h"],
            disabled_kernels=["round_number"],
        )
        router = UniverseSRRouter(
            UniverseSRConfig(
                assets=[asset],
                max_workers=1,
                global_config={
                    "pipeline": {"enabled_kernels": ["pivot_hl", "round_number"]},
                },
            ),
        )

        pipeline = router._get_or_create_pipeline("BTCUSDT", "1h", asset)
        assert pipeline._config.pipeline.enabled_kernels == ["pivot_hl"]

    def test_process_single_asset(self):
        from app.sr.universe.config import AssetSRConfig

        router = self._make_router([AssetSRConfig(symbol="BTCUSDT")])
        data_map = {"BTCUSDT": {"1h": _make_ohlcv()}}
        result = router.process(data_map, bar_index=100)
        assert "BTCUSDT" in result.results
        assert "1h" in result.results["BTCUSDT"]
        atr = result.results["BTCUSDT"]["1h"]
        assert atr.asset == "BTCUSDT"
        assert atr.timeframe == "1h"

    def test_process_multiple_assets(self):
        router = self._make_router()
        data_map = {
            "BTCUSDT": {"1h": _make_ohlcv(seed=1)},
            "ETHUSDT": {"1h": _make_ohlcv(seed=2)},
        }
        result = router.process(data_map, bar_index=50)
        assert len(result.all_results) == 2
        assert result.elapsed_ms > 0

    def test_process_rejects_unconfigured_timeframes(self):
        from app.sr.universe.config import AssetSRConfig

        router = self._make_router([AssetSRConfig(symbol="BTCUSDT", timeframes=["4h"])])
        data_map = {
            "BTCUSDT": {
                "1h": _make_ohlcv(seed=1),
                "4h": _make_ohlcv(seed=2),
            },
        }
        result = router.process(data_map, bar_index=50)

        assert result.get("BTCUSDT", "1h") is None
        assert result.get("BTCUSDT", "4h") is not None
        assert "BTCUSDT:1h" in result.errors

    def test_default_timeframes_apply_when_asset_timeframes_unspecified(self):
        from app.sr.universe.config import AssetSRConfig, UniverseSRConfig
        from app.sr.universe.router import UniverseSRRouter

        router = UniverseSRRouter(
            UniverseSRConfig(
                assets=[AssetSRConfig(symbol="BTCUSDT")],
                max_workers=1,
                default_timeframes=["4h"],
                global_config={
                    "pipeline": {"enabled_kernels": ["pivot_hl"]},
                },
            ),
        )
        data_map = {
            "BTCUSDT": {
                "1h": _make_ohlcv(seed=1),
                "4h": _make_ohlcv(seed=2),
            },
        }
        result = router.process(data_map, bar_index=50)

        assert result.get("BTCUSDT", "1h") is None
        assert result.get("BTCUSDT", "4h") is not None
        assert "BTCUSDT:1h" in result.errors

    def test_pipeline_caching(self):
        from app.sr.universe.config import AssetSRConfig

        router = self._make_router([AssetSRConfig(symbol="BTCUSDT")])
        data_map = {"BTCUSDT": {"1h": _make_ohlcv()}}
        router.process(data_map, bar_index=1)
        assert "BTCUSDT:1h" in router._pipelines
        # Second call reuses pipeline
        router.process(data_map, bar_index=2)
        assert len(router._pipelines) == 1

    def test_process_keeps_live_path_characteristics_free(self, monkeypatch):
        from app.sr.universe.config import AssetSRConfig, UniverseSRConfig
        from app.sr.universe.router import UniverseSRRouter

        asset = AssetSRConfig(symbol="BTCUSDT", timeframes=["1h"])
        router = UniverseSRRouter(
            UniverseSRConfig(
                assets=[asset],
                max_workers=1,
                global_config={
                    "pipeline": {"enabled_kernels": ["pivot_hl"]},
                },
            ),
        )

        original_resolve = router._resolver.resolve
        seen_characteristics = []

        def _spy_resolve(*args, **kwargs):
            seen_characteristics.append(kwargs.get("characteristics"))
            return original_resolve(*args, **kwargs)

        monkeypatch.setattr(router._resolver, "resolve", _spy_resolve)

        result = router.process(
            {"BTCUSDT": {"1h": _make_ohlcv(n=30)}},
            bar_index=10,
        )

        assert result.get("BTCUSDT", "1h") is not None
        assert len(seen_characteristics) == 1
        assert seen_characteristics[0] is None
        assert router._pipelines["BTCUSDT:1h"]._config.requires_sidecar_derivation is True

    def test_process_enqueues_sidecar_task_when_profile_missing(self, tmp_path: Path):
        from app.sr.sidecar.queue import create_profile_task_queue
        from app.sr.universe.config import AssetSRConfig, UniverseSRConfig
        from app.sr.universe.router import UniverseSRRouter

        queue_path = tmp_path / "sr_sidecar.sqlite3"
        router = UniverseSRRouter(
            UniverseSRConfig(
                assets=[AssetSRConfig(symbol="BTCUSDT", timeframes=["1h"])],
                max_workers=1,
                global_config={"pipeline": {"enabled_kernels": ["pivot_hl"]}},
                sidecar_enabled=True,
                sidecar_queue_path=str(queue_path),
            ),
        )

        try:
            router.process({"BTCUSDT": {"1h": _make_ohlcv(n=30)}}, bar_index=10)

            queue = create_profile_task_queue("sqlite", str(queue_path))
            pending = queue.list_pending()
            assert len(pending) == 1
            assert pending[0].symbol == "BTCUSDT"
            assert pending[0].timeframe == "1h"
            assert pending[0].reason == "missing_microstructure_profile"
        finally:
            router.close()

    def test_reload_pipelines_from_config_swaps_pipeline_and_preserves_candidate_cache(self, tmp_path: Path):
        import yaml

        from app.sr.universe.config import AssetSRConfig, UniverseSRConfig
        from app.sr.universe.router import UniverseSRRouter

        yaml_path = tmp_path / "sr.yaml"
        base_config = {
            "assets": {
                "BTCUSDT": {
                    "1h": {
                        "_profiler_meta": {
                            "last_profiled_at": "2026-05-07T14:32:00Z",
                            "wick_p75_atr": 0.85,
                        },
                        "pipeline": {
                            "merge_threshold_pct_atr": 0.25,
                            "dedup_proximity_atr": 0.50,
                            "zone_half_width_atr": 0.10,
                        },
                        "lifecycle": {
                            "breakout_atr_threshold": 0.30,
                            "touch_proximity_atr": 0.10,
                            "false_breakout_recovery_bars": 6,
                        },
                        "enhancement": {
                            "volume_spike_threshold": 1.5,
                        },
                    },
                },
            },
        }
        yaml_path.write_text(yaml.safe_dump(base_config, sort_keys=False))

        router = UniverseSRRouter(
            UniverseSRConfig(
                assets=[AssetSRConfig(symbol="BTCUSDT", timeframes=["1h"])],
                max_workers=1,
                global_config={"pipeline": {"enabled_kernels": ["pivot_hl"]}},
                sidecar_enabled=True,
                sidecar_config_path=str(yaml_path),
                sidecar_watch_config=False,
            ),
        )

        try:
            pipeline = router._get_or_create_pipeline("BTCUSDT", "1h")
            pipeline._candidate_cache["cached-zone"] = 7

            updated_config = copy.deepcopy(base_config)
            updated_config["assets"]["BTCUSDT"]["1h"]["pipeline"]["merge_threshold_pct_atr"] = 0.40
            yaml_path.write_text(yaml.safe_dump(updated_config, sort_keys=False))

            router._reload_pipelines_from_config()

            reloaded = router._pipelines["BTCUSDT:1h"]
            assert reloaded is not pipeline
            assert reloaded._candidate_cache == {"cached-zone": 7}
            assert reloaded._config.pipeline.merge_threshold_pct_atr == pytest.approx(0.40)
        finally:
            router.close()

    def test_reset(self):
        from app.sr.universe.config import AssetSRConfig

        router = self._make_router([AssetSRConfig(symbol="BTCUSDT")])
        data_map = {"BTCUSDT": {"1h": _make_ohlcv()}}
        router.process(data_map, bar_index=1)
        assert len(router._pipelines) == 1
        router.reset()
        assert len(router._pipelines) == 0

    def test_reset_specific_asset(self):
        router = self._make_router()
        data_map = {
            "BTCUSDT": {"1h": _make_ohlcv(seed=1)},
            "ETHUSDT": {"1h": _make_ohlcv(seed=2)},
        }
        router.process(data_map)
        assert len(router._pipelines) == 2
        router.reset(symbol="BTCUSDT")
        assert len(router._pipelines) == 1
        assert "ETHUSDT:1h" in router._pipelines

    def test_universe_result_get(self):
        router = self._make_router()
        data_map = {
            "BTCUSDT": {"1h": _make_ohlcv(seed=1)},
            "ETHUSDT": {"1h": _make_ohlcv(seed=2)},
        }
        result = router.process(data_map)
        btc = result.get("BTCUSDT", "1h")
        assert btc is not None
        assert btc.asset == "BTCUSDT"
        assert result.get("XYZUSDT", "1h") is None

    def test_error_handling(self):
        """Bad data should produce error, not crash."""
        router = self._make_router()
        # Empty DataFrame
        data_map = {
            "BTCUSDT": {"1h": pd.DataFrame()},
            "ETHUSDT": {"1h": _make_ohlcv(seed=2)},
        }
        result = router.process(data_map)
        # BTCUSDT skipped (empty df), ETHUSDT processed
        assert "ETHUSDT" in result.results

    def test_kernel_failure_surfaces_as_asset_error(self, monkeypatch):
        from app.sr.universe.router import UniverseSRRouter

        router = self._make_router()

        class _FailingPipeline:
            def run(self, df, bar_index=0, timestamp=None):
                raise RuntimeError("SR pipeline aborted because kernels failed: pivot_hl")

        monkeypatch.setattr(router, "_get_or_create_pipeline", lambda *args, **kwargs: _FailingPipeline())

        result = router.process(
            {"BTCUSDT": {"1h": _make_ohlcv(seed=1)}},
            bar_index=10,
        )

        assert not result.results
        assert result.errors["BTCUSDT:1h"] == "SR pipeline aborted because kernels failed: pivot_hl"

    def test_parallel_timeout_reports_errors(self, monkeypatch):
        from app.sr.universe.config import AssetSRConfig, UniverseSRConfig
        from app.sr.universe.router import AssetTimeframeResult, UniverseSRRouter

        router = UniverseSRRouter(
            UniverseSRConfig(
                assets=[AssetSRConfig(symbol="BTCUSDT"), AssetSRConfig(symbol="ETHUSDT")],
                max_workers=2,
                timeout_per_asset_s=0.01,
                global_config={
                    "pipeline": {"enabled_kernels": ["pivot_hl"]},
                },
            ),
        )

        def _slow_process(symbol, timeframe, df, bar_index, timestamp, asset_config):
            time.sleep(0.1)
            return AssetTimeframeResult(
                asset=symbol,
                timeframe=timeframe,
                result=SimpleNamespace(scored_levels=[]),
                elapsed_ms=100.0,
            )

        monkeypatch.setattr(router, "_process_one", _slow_process)

        result = router.process(
            {
                "BTCUSDT": {"1h": _make_ohlcv(seed=1)},
                "ETHUSDT": {"1h": _make_ohlcv(seed=2)},
            },
            bar_index=10,
        )

        assert not result.results
        assert "BTCUSDT:1h" in result.errors
        assert "ETHUSDT:1h" in result.errors
        assert "timed out" in result.errors["BTCUSDT:1h"]
