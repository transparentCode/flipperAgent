#!/usr/bin/env python
"""Regime overlay validation: batch-compute all 9 cross-sectional features
on historical TV index + Binance BTCUSDT data, produce analysis report.

Usage:
    cd /Users/aloobhujia/flipperAgent
    PYTHONPATH=src .venv/bin/python scripts/regime_validation.py
"""

from __future__ import annotations

import math
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Feature imports (from libs/ — not apps/)
# ---------------------------------------------------------------------------
from libs.features.engineered.cross_sectional import (
    AltcoinBeta,
    AltcoinMarketMomentum,
    BTCDominanceMomentum,
    BTCDominanceRegime,
    CrossAssetRegimeState,
    MarketCapBreadth,
    RegimeAlignmentScore,
    RelativeStrengthVsTotal3,
    Total3MomentumZ,
)
from libs.optim_utils.data_fetcher import fetch_historical_ohlcv

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TV_DATA_DIR = Path("data/tv_index")
REGIME_NAMES = {0: "RISK_OFF", 1: "ALT_SEASON", 2: "ROTATION", 3: "BROAD_SELLOFF"}

# Feature params from configs/features.yaml
FEATURE_PARAMS = {
    "btc_dominance_momentum": {"sma_period": 10, "atr_period": 14},
    "total3_momentum_z": {"sma_period": 20, "z_period": 50, "clip_range": 3.0},
    "relative_strength_vs_total3": {"period": 20, "clip_range": 10.0},
    "cross_asset_regime_state": {"btc_d_threshold": 0.3, "t3_threshold": 0.3},
    "regime_alignment_score": {
        "w_btc_d": 0.3,
        "w_t3": 0.3,
        "w_breadth": 0.2,
        "w_rs": 0.2,
        "breadth_scale": 10.0,
    },
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_tv_data(symbol: str) -> pd.DataFrame:
    """Load TV index CSV and return DataFrame with datetime index."""
    fname = f"{symbol.replace('.', '_')}_1h.csv"
    path = TV_DATA_DIR / fname
    if not path.exists():
        raise FileNotFoundError(f"TV data not found: {path}")

    df = pd.read_csv(path)
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.sort_values("datetime").reset_index(drop=True)
    return df


def load_binance_btcusdt(start_ms: int, end_ms: int) -> pd.DataFrame:
    """Fetch BTCUSDT 1h OHLCV from Binance covering the TV data range."""
    # Request enough bars to cover the range
    hours = (end_ms - start_ms) / (3600 * 1000)
    limit = int(hours) + 100  # padding

    print(f"  Fetching BTCUSDT 1h from Binance ({limit} bars)...")
    df = fetch_historical_ohlcv(
        symbol="BTCUSDT",
        timeframe="1h",
        since=start_ms,
        until=end_ms,
        limit=limit,
    )
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


def align_datasets(
    btc_d: pd.DataFrame,
    total2: pd.DataFrame,
    total3: pd.DataFrame,
    btcusdt: pd.DataFrame,
) -> pd.DataFrame:
    """Align all datasets to common hourly timestamps.

    Returns a merged DataFrame with columns for each index and BTCUSDT.
    """
    # Round all datetimes to the hour
    for df in [btc_d, total2, total3, btcusdt]:
        df["hour"] = df["datetime"].dt.floor("h")

    # Use TV data as the base timeline
    base = btc_d[["hour"]].drop_duplicates().sort_values("hour").reset_index(drop=True)

    # Merge each dataset
    for name, df, cols in [
        ("btcd", btc_d, ["open", "high", "low", "close", "volume"]),
        ("total2", total2, ["open", "high", "low", "close", "volume"]),
        ("total3", total3, ["open", "high", "low", "close", "volume"]),
        ("btcusdt", btcusdt, ["open", "high", "low", "close", "volume"]),
    ]:
        subset = df[["hour"] + cols].drop_duplicates(subset=["hour"], keep="last")
        subset = subset.rename(columns={c: f"{name}_{c}" for c in cols})
        base = base.merge(subset, on="hour", how="left")

    # Drop rows where any critical data is missing
    critical = ["btcd_close", "total2_close", "total3_close", "btcusdt_close"]
    base = base.dropna(subset=critical).reset_index(drop=True)

    return base


# ---------------------------------------------------------------------------
# Feature computation (tick-by-tick, mimicking live pipeline)
# ---------------------------------------------------------------------------


def compute_features_batch(aligned: pd.DataFrame) -> pd.DataFrame:
    """Compute all 9 cross-sectional features tick-by-tick."""

    # Instantiate feature classes with config params
    features_pass1 = [
        ("eng_btc_dominance_regime", BTCDominanceRegime()),
        ("eng_btc_dominance_momentum", BTCDominanceMomentum(FEATURE_PARAMS.get("btc_dominance_momentum"))),
        ("eng_altcoin_market_momentum", AltcoinMarketMomentum()),
        ("eng_total3_momentum_z", Total3MomentumZ(FEATURE_PARAMS.get("total3_momentum_z"))),
        ("eng_market_cap_breadth", MarketCapBreadth()),
        ("eng_altcoin_beta", AltcoinBeta()),
        ("eng_relative_strength_vs_total3", RelativeStrengthVsTotal3(FEATURE_PARAMS.get("relative_strength_vs_total3"))),
    ]

    features_pass2 = [
        ("eng_cross_asset_regime_state", CrossAssetRegimeState(FEATURE_PARAMS.get("cross_asset_regime_state"))),
        ("eng_regime_alignment_score", RegimeAlignmentScore(FEATURE_PARAMS.get("regime_alignment_score"))),
    ]

    # Per-feature state dicts (maintained across ticks)
    states = {name: {} for name, _ in features_pass1 + features_pass2}

    results = []
    n_rows = len(aligned)

    for i in range(n_rows):
        row = aligned.iloc[i]

        # Build index_data dict mimicking the live pipeline
        index_data = {
            "BTC.D": {
                "open": row["btcd_open"],
                "high": row["btcd_high"],
                "low": row["btcd_low"],
                "close": row["btcd_close"],
                "volume": row.get("btcd_volume", 0.0),
            },
            "TOTAL2": {
                "open": row["total2_open"],
                "high": row["total2_high"],
                "low": row["total2_low"],
                "close": row["total2_close"],
                "volume": row.get("total2_volume", 0.0),
            },
            "TOTAL3": {
                "open": row["total3_open"],
                "high": row["total3_high"],
                "low": row["total3_low"],
                "close": row["total3_close"],
                "volume": row.get("total3_volume", 0.0),
            },
        }

        # bar_data for asset-dependent features
        bar_data = {
            "open": row["btcusdt_open"],
            "high": row["btcusdt_high"],
            "low": row["btcusdt_low"],
            "close": row["btcusdt_close"],
            "volume": row.get("btcusdt_volume", 0.0),
        }

        # Pass 1: independent features
        computed: dict[str, float] = {}
        for name, feat in features_pass1:
            val = feat.compute(
                features=computed,
                bar_data=bar_data,
                state=states[name],
                index_data=index_data,
            )
            computed[name] = val if val is not None else 0.0

        # Pass 2: dependent features (need pass-1 values in features dict)
        for name, feat in features_pass2:
            val = feat.compute(
                features=computed,
                bar_data=bar_data,
                state=states[name],
                index_data=index_data,
            )
            computed[name] = val if val is not None else 0.0

        computed["hour"] = row["hour"]
        computed["btcusdt_close"] = row["btcusdt_close"]
        results.append(computed)

        if (i + 1) % 1000 == 0:
            print(f"  Computed {i + 1}/{n_rows} bars...")

    print(f"  Computed {n_rows}/{n_rows} bars")
    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# RSI computation (simple Wilder's RSI)
# ---------------------------------------------------------------------------


def compute_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    """Compute RSI from close prices."""
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)


# ---------------------------------------------------------------------------
# Analysis and reporting
# ---------------------------------------------------------------------------


def report_regime_distribution(df: pd.DataFrame):
    """Regime state distribution and transition analysis."""
    print("\n--- Regime State Distribution ---")

    regime = df["eng_cross_asset_regime_state"]
    total = len(regime)

    # Count per state
    for state_val in sorted(REGIME_NAMES.keys()):
        name = REGIME_NAMES[state_val]
        count = (regime == state_val).sum()
        pct = 100 * count / total if total > 0 else 0

        # Average duration: find consecutive runs
        runs = []
        current_run = 0
        for v in regime:
            if v == state_val:
                current_run += 1
            else:
                if current_run > 0:
                    runs.append(current_run)
                current_run = 0
        if current_run > 0:
            runs.append(current_run)

        avg_dur = np.mean(runs) if runs else 0
        max_dur = max(runs) if runs else 0
        print(
            f"  {name:16s} ({state_val}): {count:5d} bars ({pct:5.1f}%)  "
            f"avg duration: {avg_dur:5.1f}h  max streak: {max_dur}h  "
            f"episodes: {len(runs)}"
        )

    # Transitions per day
    transitions = (regime.diff().fillna(0) != 0).sum()
    hours = df["hour"]
    if len(hours) >= 2:
        days = (hours.iloc[-1] - hours.iloc[0]).total_seconds() / 86400
        trans_per_day = transitions / max(days, 1)
    else:
        days = 0
        trans_per_day = 0

    print(f"\n  Total transitions: {transitions}")
    print(f"  Transitions per day: {trans_per_day:.2f}")

    # Check: no single state > 60%
    max_pct = max((regime == v).sum() / total for v in REGIME_NAMES.keys()) * 100
    if max_pct > 60:
        print(f"  ⚠ WARNING: Dominant state has {max_pct:.1f}% (> 60% threshold)")
    else:
        print(f"  ✓ No single state dominates (max={max_pct:.1f}%)")

    all_states = set(int(v) for v in regime.unique())
    missing = set(REGIME_NAMES.keys()) - all_states
    if missing:
        print(f"  ⚠ WARNING: Missing states: {[REGIME_NAMES[m] for m in missing]}")
    else:
        print("  ✓ All 4 regime states represented")


def report_feature_statistics(df: pd.DataFrame):
    """Feature-level statistics."""
    print("\n--- Feature Statistics ---")

    feature_cols = [c for c in df.columns if c.startswith("eng_")]

    for col in sorted(feature_cols):
        vals = df[col].dropna()
        if len(vals) == 0:
            print(f"  {col:40s}  NO DATA")
            continue

        mean = vals.mean()
        std = vals.std()
        vmin = vals.min()
        vmax = vals.max()
        non_zero = (vals != 0).sum() / len(vals) * 100

        print(
            f"  {col:40s}  mean={mean:+7.3f}  std={std:6.3f}  "
            f"[{vmin:+8.4f}, {vmax:+8.4f}]  non-zero={non_zero:5.1f}%"
        )

    # Specific checks
    t3z = df["eng_total3_momentum_z"].dropna()
    if len(t3z) > 0:
        if abs(t3z.mean()) < 0.5:
            print(f"\n  ✓ total3_momentum_z roughly centered (mean={t3z.mean():+.4f})")
        else:
            print(f"\n  ⚠ total3_momentum_z NOT centered (mean={t3z.mean():+.4f}, expected |mean| < 0.5)")

    ras = df["eng_regime_alignment_score"].dropna()
    if len(ras) > 0:
        if abs(ras.mean()) < 0.3:
            print(f"  ✓ regime_alignment_score approximately centered (mean={ras.mean():+.4f})")
        else:
            print(f"  ⚠ regime_alignment_score NOT centered (mean={ras.mean():+.4f}, expected |mean| < 0.3)")


def report_signal_analysis(df: pd.DataFrame):
    """RegimeRelativeValueScorer signal analysis."""
    print("\n--- RegimeRelativeValueScorer Signal Analysis ---")

    regime = df["eng_cross_asset_regime_state"]
    rs = df["eng_relative_strength_vs_total3"]

    # Compute RSI for BTCUSDT
    rsi = compute_rsi(df["btcusdt_close"])

    # Entry signal: regime==RISK_OFF AND rs < threshold AND RSI oversold
    rs_threshold = -0.5  # default threshold
    rsi_oversold = 35.0  # typical oversold level

    signals = (regime == 0) & (rs < rs_threshold) & (rsi < rsi_oversold)
    n_signals = signals.sum()
    total = len(df)
    pct = 100 * n_signals / total if total > 0 else 0

    print(f"  Signal criteria: regime==RISK_OFF AND rs<{rs_threshold} AND RSI<{rsi_oversold}")
    print(f"  Total signals: {n_signals} ({pct:.2f}% of {total} bars)")

    if pct > 5:
        print("  ⚠ Signal frequency > 5% — thresholds may be too loose")
    elif n_signals == 0:
        print("  ⚠ No signals — thresholds may be too tight")
        # Try relaxed criteria
        for rs_t, rsi_t in [(-0.3, 40), (-0.2, 45), (0.0, 50)]:
            relaxed = (regime == 0) & (rs < rs_t) & (rsi < rsi_t)
            n_r = relaxed.sum()
            if n_r > 0:
                print(f"     With relaxed rs<{rs_t}, RSI<{rsi_t}: {n_r} signals ({100 * n_r / total:.2f}%)")
    else:
        print(f"  ✓ Signal frequency {pct:.2f}% is within expected range (< 5%)")

    # Basic PnL analysis if signals exist
    if n_signals > 0:
        signal_indices = df.index[signals].tolist()
        for lookforward in [5, 10, 20]:
            returns = []
            for idx in signal_indices:
                if idx + lookforward < len(df):
                    entry_price = df.loc[idx, "btcusdt_close"]
                    exit_price = df.loc[idx + lookforward, "btcusdt_close"]
                    ret = (exit_price - entry_price) / entry_price * 100
                    returns.append(ret)
            if returns:
                avg_ret = np.mean(returns)
                win_rate = sum(1 for r in returns if r > 0) / len(returns) * 100
                print(
                    f"  Next-{lookforward}-bar: avg return={avg_ret:+.3f}%  "
                    f"win rate={win_rate:.1f}%  (n={len(returns)})"
                )


def report_regime_transitions(df: pd.DataFrame):
    """Detailed regime transition analysis."""
    print("\n--- Regime Transition Matrix ---")

    regime = df["eng_cross_asset_regime_state"].astype(int)
    n = len(regime)

    # Transition matrix
    matrix = defaultdict(lambda: defaultdict(int))
    for i in range(1, n):
        fr = int(regime.iloc[i - 1])
        to = int(regime.iloc[i])
        if fr != to:
            matrix[fr][to] += 1

    # Print matrix
    states = sorted(REGIME_NAMES.keys())
    header = f"  {'From/To':16s}" + "".join(f"{REGIME_NAMES[s]:>16s}" for s in states)
    print(header)
    for fr in states:
        row = f"  {REGIME_NAMES[fr]:16s}"
        for to in states:
            count = matrix[fr][to]
            row += f"{count:16d}"
        print(row)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("=" * 70)
    print("REGIME OVERLAY VALIDATION")
    print("=" * 70)

    # Load TV index data
    print("\nLoading TV index data...")
    try:
        btc_d = load_tv_data("BTC.D")
        total2 = load_tv_data("TOTAL2")
        total3 = load_tv_data("TOTAL3")
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        print("Run scripts/tv_backfill.py first to fetch TV data.")
        sys.exit(1)

    print(f"  BTC.D:  {len(btc_d)} bars  ({btc_d['datetime'].min():%Y-%m-%d} → {btc_d['datetime'].max():%Y-%m-%d})")
    print(f"  TOTAL2: {len(total2)} bars  ({total2['datetime'].min():%Y-%m-%d} → {total2['datetime'].max():%Y-%m-%d})")
    print(f"  TOTAL3: {len(total3)} bars  ({total3['datetime'].min():%Y-%m-%d} → {total3['datetime'].max():%Y-%m-%d})")

    # Determine time range for Binance fetch
    all_dts = pd.concat([btc_d["datetime"], total2["datetime"], total3["datetime"]])
    start_ms = int(all_dts.min().timestamp() * 1000)
    end_ms = int(all_dts.max().timestamp() * 1000)

    # Load Binance BTCUSDT
    print("\nLoading Binance BTCUSDT data...")
    btcusdt = load_binance_btcusdt(start_ms, end_ms)
    print(f"  BTCUSDT: {len(btcusdt)} bars  ({btcusdt['datetime'].min():%Y-%m-%d} → {btcusdt['datetime'].max():%Y-%m-%d})")

    # Align datasets
    print("\nAligning datasets...")
    aligned = align_datasets(btc_d, total2, total3, btcusdt)
    hours = aligned["hour"]
    days = (hours.iloc[-1] - hours.iloc[0]).total_seconds() / 86400
    print(f"  Aligned: {len(aligned)} bars over {days:.1f} days")
    print(f"  Range: {hours.iloc[0]:%Y-%m-%d %H:%M} → {hours.iloc[-1]:%Y-%m-%d %H:%M}")

    # Compute features
    print("\nComputing cross-sectional features (tick-by-tick)...")
    result = compute_features_batch(aligned)

    # Merge hour and btcusdt_close back for reporting
    # (already included in compute_features_batch output)

    # Report
    print("\n" + "=" * 70)
    print("=== REGIME OVERLAY VALIDATION RESULTS ===")
    print(f"Date range: {hours.iloc[0]:%Y-%m-%d %H:%M} → {hours.iloc[-1]:%Y-%m-%d %H:%M}")
    print(f"Total bars: {len(result):,} ({days:.1f} days)")
    print("=" * 70)

    report_regime_distribution(result)
    report_feature_statistics(result)
    report_signal_analysis(result)
    report_regime_transitions(result)

    print("\n" + "=" * 70)
    print("Validation complete")
    print("=" * 70)


if __name__ == "__main__":
    main()
