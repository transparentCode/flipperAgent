"""Tests for config resolution pipeline."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from libs.models.trendlines.config import (
    TrendlinesConfig,
    OptimizableDefaults,
    AssetConfig,
    AssetTimeframeConfig,
    load_trendlines_config,
)
from libs.models.trendlines.config.resolve import ResolvedConfig, ResolvedSignalConfig, resolve_asset_config


def _make_ohlcv(n_bars: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = 100.0 + np.cumsum(rng.normal(0, 0.5, n_bars))
    high = close + rng.uniform(0.2, 1.0, n_bars)
    low = close - rng.uniform(0.2, 1.0, n_bars)
    opn = close + rng.normal(0, 0.3, n_bars)
    idx = pd.date_range("2025-01-01", periods=n_bars, freq="1h")
    return pd.DataFrame(
        {"open": opn, "high": high, "low": low, "close": close},
        index=idx,
    )


class TestResolveAssetConfig:
    def test_basic_resolve(self):
        cfg = TrendlinesConfig()
        df = _make_ohlcv()
        resolved = resolve_asset_config(cfg, "BTCUSDT", "1h", df)

        assert isinstance(resolved, ResolvedConfig)
        assert isinstance(resolved.signals, ResolvedSignalConfig)
        assert resolved.asset == "BTCUSDT"
        assert resolved.timeframe == "1h"
        assert resolved.profile is not None
        assert resolved.profile.tf_minutes == 60

    def test_defaults_propagated(self):
        from dataclasses import replace

        cfg = replace(
            TrendlinesConfig(),
            defaults=OptimizableDefaults(
                interaction_tolerance_atr=0.30,
                squeeze_threshold=2.5,
            ),
        )
        df = _make_ohlcv()
        resolved = resolve_asset_config(cfg, "BTCUSDT", "1h", df)

        assert resolved.signals.squeeze_threshold == 2.5
        assert resolved.boundary.interaction_tolerance_atr == 0.30

    def test_per_asset_tf_override(self):
        from dataclasses import replace

        cfg = replace(
            TrendlinesConfig(),
            assets={
                "BTCUSDT": AssetConfig(
                    metadata={"asset_class": "crypto"},
                    timeframes={
                        "1h": AssetTimeframeConfig(interaction_tolerance_atr=0.15),
                    },
                ),
            },
        )
        df = _make_ohlcv()
        resolved = resolve_asset_config(cfg, "BTCUSDT", "1h", df)

        # Override should win
        assert resolved.boundary.interaction_tolerance_atr == 0.15
        # Non-overridden should use default
        assert resolved.signals.squeeze_threshold == 3.0

    def test_unknown_asset_uses_defaults(self):
        cfg = TrendlinesConfig()
        df = _make_ohlcv()
        resolved = resolve_asset_config(cfg, "UNKNOWNUSDT", "1h", df)
        assert resolved.signals.asymmetry_threshold == 0.3

    def test_derived_params_populated(self):
        cfg = TrendlinesConfig()
        df = _make_ohlcv()
        resolved = resolve_asset_config(cfg, "BTCUSDT", "1h", df)

        assert resolved.signals.hold_bars >= 1
        assert resolved.signals.volume_lookback >= 5
        assert resolved.signals.min_history >= 2
        assert resolved.signals.parallel_tol > 0
        assert resolved.signals.flat_tol > 0
        assert resolved.signals.slope_match_tol > 0
        assert resolved.signals.slope_accel_threshold > 0
        assert resolved.signals.full_confidence_touches_structural > 0
        assert resolved.signals.full_confidence_touches_pattern > 0
        assert resolved.boundary.atr_window >= 5

    def test_state_transitions_populated(self):
        cfg = TrendlinesConfig()
        df = _make_ohlcv()
        resolved = resolve_asset_config(cfg, "BTCUSDT", "1h", df)

        st = resolved.signals.state_transitions
        assert len(st) == 14
        for (from_s, to_s), (direction, confidence) in st.items():
            assert isinstance(direction, float)
            assert isinstance(confidence, float)
            assert 0 < confidence <= 1.0

    def test_frozen(self):
        cfg = TrendlinesConfig()
        df = _make_ohlcv()
        resolved = resolve_asset_config(cfg, "BTCUSDT", "1h", df)

        with pytest.raises(AttributeError):
            resolved.asset = "ETHUSDT"  # type: ignore[misc]

    def test_asset_metadata_propagated(self):
        from dataclasses import replace

        cfg = replace(
            TrendlinesConfig(),
            assets={
                "BTCUSDT": AssetConfig(
                    metadata={"asset_class": "crypto", "universe": "major"},
                    timeframes={},
                ),
            },
        )
        df = _make_ohlcv()
        resolved = resolve_asset_config(cfg, "BTCUSDT", "1h", df)
        assert resolved.asset_metadata["asset_class"] == "crypto"
        assert resolved.asset_metadata["universe"] == "major"

    def test_from_yaml_config(self):
        cfg = load_trendlines_config()
        df = _make_ohlcv()
        resolved = resolve_asset_config(cfg, "BTCUSDT", "1h", df)
        assert resolved.profile is not None
        assert resolved.signals.state_transitions

    def test_4h_vs_1h_derived_differ(self):
        cfg = TrendlinesConfig()
        df = _make_ohlcv(500)
        r1h = resolve_asset_config(cfg, "BTCUSDT", "1h", df)
        r4h = resolve_asset_config(cfg, "BTCUSDT", "4h", df)

        # TF-derived bar counts should differ
        assert r1h.signals.hold_bars != r4h.signals.hold_bars
        assert r1h.boundary.atr_window != r4h.boundary.atr_window
