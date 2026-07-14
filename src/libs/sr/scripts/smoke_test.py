#!/usr/bin/env python3
"""
S/R v2 Smoke Test
==================
Quick validation that the full v2 pipeline and universe router work end-to-end
with synthetic data. Exits 0 on success, 1 on failure.

Usage::

    python -m app.sr.scripts.smoke_test
    python -m app.sr.scripts.smoke_test --universe
    python -m app.sr.scripts.smoke_test --debug --timing
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Synthetic data
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
    for _ in range(1, n):
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


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _make_resolved_config():
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
    return SRResolvedConfig(
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


# ---------------------------------------------------------------------------
# Single-asset smoke
# ---------------------------------------------------------------------------

def run_single_asset(debug: bool = False, timing: bool = False) -> bool:
    """Run single-asset pipeline smoke test. Returns True on success."""
    from app.sr.pipeline import SRv2Pipeline

    print("[single-asset] Generating synthetic data...")
    df = _make_ohlcv(n=200, base_price=100.0)

    config = _make_resolved_config()
    pipeline = SRv2Pipeline(config, asset="SMOKE_TEST", timeframe="1h")

    print("[single-asset] Running pipeline (bar 0)...")
    t0 = time.perf_counter()
    result = pipeline.run(df, bar_index=0, debug=debug, timing=timing)
    elapsed = (time.perf_counter() - t0) * 1000

    print(f"[single-asset] Candidates:     {len(result.candidates)}")
    print(f"[single-asset] Scored levels:   {len(result.scored_levels)}")
    print(f"[single-asset] Active zones:    {len(result.active_zones)}")
    print(f"[single-asset] Events:          {len(result.events)}")
    print(f"[single-asset] Ensemble:        {result.ensemble_method}")
    print(f"[single-asset] Wall time:       {elapsed:.1f}ms")

    if timing and result.timing:
        print("[single-asset] Timing breakdown:")
        for stage, ms in result.timing.items():
            print(f"  {stage}: {ms:.2f}ms")

    if debug and result.debug:
        print("[single-asset] Debug info keys:", list(result.debug.keys()))

    if len(result.candidates) == 0:
        print("[single-asset] WARN: no candidates produced")
    if len(result.scored_levels) == 0:
        print("[single-asset] WARN: no scored levels produced")

    print("[single-asset] PASSED")
    return True


# ---------------------------------------------------------------------------
# Universe smoke
# ---------------------------------------------------------------------------

def run_universe(debug: bool = False) -> bool:
    """Run universe router smoke test. Returns True on success."""
    from app.sr.universe.config import UniverseSRConfig, AssetSRConfig
    from app.sr.universe.router import UniverseSRRouter

    assets = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    tfs = ["1h"]

    print(f"[universe] Assets: {assets}, TFs: {tfs}")
    print("[universe] Generating synthetic data...")

    data_map = {}
    for i, asset in enumerate(assets):
        data_map[asset] = {}
        for tf in tfs:
            data_map[asset][tf] = _make_ohlcv(
                n=200, base_price=100.0 * (i + 1), seed=42 + i,
            )

    asset_configs = [AssetSRConfig(symbol=a, timeframes=tfs) for a in assets]
    universe_config = UniverseSRConfig(
        assets=asset_configs,
        max_workers=1,
        global_config={
            "pipeline": {"enabled_kernels": ["pivot_hl", "round_number"]},
        },
    )
    router = UniverseSRRouter(universe_config)

    print("[universe] Processing...")
    t0 = time.perf_counter()
    result = router.process(data_map, bar_index=0, timestamp=datetime.now(UTC))
    elapsed = (time.perf_counter() - t0) * 1000

    print(f"[universe] Results: {len(result.all_results)} asset-TF pairs")
    for atr in result.all_results:
        status = "OK"
        print(f"  {atr.asset}:{atr.timeframe} — {status}")

    print(f"[universe] Wall time: {elapsed:.1f}ms")
    print("[universe] PASSED")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="S/R v2 smoke test")
    parser.add_argument("--universe", action="store_true", help="Also run universe mode")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--timing", action="store_true", help="Enable timing mode")
    args = parser.parse_args()

    ok = True
    try:
        ok = run_single_asset(debug=args.debug, timing=args.timing) and ok
    except Exception as e:
        print(f"[single-asset] FAILED: {e}")
        ok = False

    if args.universe:
        try:
            ok = run_universe(debug=args.debug) and ok
        except Exception as e:
            print(f"[universe] FAILED: {e}")
            ok = False

    if ok:
        print("\nAll smoke tests PASSED")
    else:
        print("\nSome smoke tests FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
