"""Tests for SR zone_quality_audit CLI."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest

from app.sr.scripts.zone_quality_audit import parse_args, main


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _make_ohlcv(n: int = 200, seed: int = 42) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC")
    closes = [100.0]
    for _ in range(1, n):
        closes.append(closes[-1] * (1 + 0.02 * rng.randn()))
    closes = np.array(closes)
    highs = closes * (1 + rng.uniform(0, 0.02, n))
    lows = closes * (1 - rng.uniform(0, 0.02, n))
    opens = closes * (1 + rng.uniform(-0.01, 0.01, n))
    volumes = rng.uniform(100, 1000, n)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )


# -----------------------------------------------------------------------
# parse_args
# -----------------------------------------------------------------------

class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])
        assert args.asset == "BTCUSDT"
        assert args.timeframe == "1h"
        assert args.lookback == 90
        assert args.bar_range is None
        assert args.quiet is False

    def test_with_dates(self):
        args = parse_args(["--start-date", "2025-01-01", "--end-date", "2026-01-01"])
        assert args.start_date == "2025-01-01"
        assert args.end_date == "2026-01-01"

    def test_bar_range(self):
        args = parse_args(["--bar-range", "50:150"])
        assert args.bar_range == "50:150"


# -----------------------------------------------------------------------
# main — integration (synthetic, no network)
# -----------------------------------------------------------------------

class TestMainIntegration:
    def test_insufficient_data(self):
        """Exit code 1 when data has too few bars."""
        tiny = _make_ohlcv(n=30)
        with patch("app.sr.scripts._utils.fetch_data", return_value=tiny):
            code = main(["-a", "BTCUSDT", "-t", "1h", "--quiet"])
            assert code == 1

    def test_audit_synthetic(self, capsys):
        """Run audit on synthetic data — verify report shape and exit code 0."""
        df = _make_ohlcv(n=200)
        with patch("app.sr.scripts._utils.fetch_data", return_value=df):
            with patch(
                "app.sr.scripts.zone_quality_audit.resolve_config"
            ) as mock_resolve:
                # Build a real config using smoke_test's pattern
                from app.sr.config_schema import (
                    EnsembleConfig,
                    EnhancementConfig,
                    LifecycleConfig,
                    PipelineConfig,
                    RegimeConfig,
                    RuleDerivedConfig,
                    SRResolvedConfig,
                )
                from app.sr.models import AssetMetadata, RuleDerivedParams

                metadata = AssetMetadata(
                    profile="crypto",
                    trading_hours_per_day=24.0,
                    trading_days_per_week=7,
                    has_session_gaps=False,
                    gap_breakout_policy="gap_ignored",
                    gap_escalation_atr=999.0,
                    session_lookback_hours=[24, 168, 720],
                    round_number_mode="decimal",
                    ex_dividend_filter=False,
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
                        enabled_kernels=["pivot_hl", "round_number"],
                    ),
                    kernels={
                        "pivot_hl": {"historical_depth": 500, "smoothing_period": 3},
                        "round_number": {},
                    },
                    ensemble=EnsembleConfig(method="weighted_average", structural_vs_micro_ratio=0.5),
                    lifecycle=LifecycleConfig(
                        age_lambda=0.002,
                        breakout_confirm_bars=3,
                        false_breakout_window=6,
                        inactivity_threshold=80,
                        max_active_zones=10,
                    ),
                    enhancement=EnhancementConfig(),
                    regime=RegimeConfig(enabled=False),
                    rule_derived=rule_derived,
                    rule_derived_config=RuleDerivedConfig(),
                )
                mock_resolve.return_value = config

                code = main(["-a", "BTCUSDT", "-t", "1h", "--quiet"])
                assert code == 0

                output = capsys.readouterr().out
                assert "ZONE QUALITY AUDIT" in output
                assert "Survival Rate" in output
                assert "COMPOSITE SCORE" in output
                assert "EVENT HISTOGRAM" in output
