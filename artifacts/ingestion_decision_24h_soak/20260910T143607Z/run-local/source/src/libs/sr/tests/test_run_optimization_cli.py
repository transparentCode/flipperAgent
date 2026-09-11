"""Tests for SR run_optimization CLI."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest

from app.sr.config_schema import OptimizationConfig
from app.sr.scripts.run_optimization import (
    parse_args,
    build_configs,
    auto_output_path,
    print_results,
    main,
)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _make_ohlcv(n: int = 200, seed: int = 42) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC")
    closes = 100.0 * np.cumprod(1 + 0.001 * rng.randn(n))
    return pd.DataFrame(
        {
            "open": closes * (1 + 0.001 * rng.randn(n)),
            "high": closes * 1.01,
            "low": closes * 0.99,
            "close": closes,
            "volume": rng.uniform(100, 1000, n),
        },
        index=dates,
    )


# -----------------------------------------------------------------------
# parse_args
# -----------------------------------------------------------------------

class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])
        assert args.assets == "BTCUSDT"
        assert args.timeframes == "1h"
        assert args.n_trials == 50
        assert args.timeout == 3600
        assert args.stage2_n_trials == 30
        assert args.stage2_timeout == 600
        assert args.lookback == 90
        assert args.sampler == "tpe"
        assert args.apply is False
        assert args.dry_run is False
        assert args.quiet is False

    def test_multi_asset(self):
        args = parse_args(["-a", "BTCUSDT,ETHUSDT,SOLUSDT", "-t", "1h,4h"])
        assets = [a.strip() for a in args.assets.split(",")]
        tfs = [t.strip() for t in args.timeframes.split(",")]
        assert assets == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        assert tfs == ["1h", "4h"]

    def test_date_range(self):
        args = parse_args(["--start-date", "2023-01-01", "--end-date", "2026-03-01"])
        assert args.start_date == "2023-01-01"
        assert args.end_date == "2026-03-01"

    def test_apply_flags(self):
        args = parse_args(["--apply", "--dry-run"])
        assert args.apply is True
        assert args.dry_run is True

    def test_stage2_overrides(self):
        args = parse_args(["--stage2-n-trials", "20", "--stage2-timeout", "300"])
        assert args.stage2_n_trials == 20
        assert args.stage2_timeout == 300


# -----------------------------------------------------------------------
# build_configs
# -----------------------------------------------------------------------

class TestBuildConfigs:
    def test_basic(self):
        args = parse_args(["-a", "BTCUSDT,ETHUSDT", "-t", "1h"])
        stage1, stage2, universe = build_configs(args)

        assert stage1.n_trials == 50
        assert stage1.timeout_s == 3600.0
        assert stage2.n_trials == 30
        assert stage2.timeout_s == 600.0
        assert len(universe.assets) == 2
        assert universe.assets[0].symbol == "BTCUSDT"
        assert universe.assets[1].symbol == "ETHUSDT"

    def test_sampler_passthrough(self):
        args = parse_args(["--sampler", "random"])
        _, stage2, _ = build_configs(args)
        assert stage2.sampler == "random"

    def test_stage2_max_lookback_uses_yaml_default(self):
        args = parse_args([])

        with patch("app.utils.ConfigLoader.ConfigLoader.load", return_value={"sr": {"optimization": {}}}):
            with patch(
                "app.sr.config_resolver.SRConfigResolver.resolve_typed_optimization_config",
                return_value=OptimizationConfig(per_asset_max_lookback=4096),
            ):
                _, stage2, _ = build_configs(args)

        assert stage2.max_lookback == 4096


# -----------------------------------------------------------------------
# auto_output_path
# -----------------------------------------------------------------------

class TestAutoOutputPath:
    def test_format(self):
        path = auto_output_path(["BTCUSDT", "ETHUSDT"], ["1h"])
        assert "BTCUSDT_ETHUSDT" in path
        assert "1h" in path
        assert path.endswith(".json")


# -----------------------------------------------------------------------
# main — integration (synthetic, no network)
# -----------------------------------------------------------------------

class TestMainIntegration:
    def test_insufficient_data(self):
        """Exit code 1 when data has too few bars."""
        tiny_data = {
            "BTCUSDT": {"1h": _make_ohlcv(n=50)},
        }
        with patch(
            "app.sr.scripts._utils.fetch_multi_asset_data",
            return_value=tiny_data,
        ):
            code = main(["-a", "BTCUSDT", "-t", "1h", "--quiet"])
            assert code == 1

    def test_parse_only_no_crash(self):
        """parse_args with --help-like short run should not crash."""
        args = parse_args(["--n-trials", "2", "--timeout", "10", "--quiet"])
        assert args.n_trials == 2
