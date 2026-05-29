#!/usr/bin/env python3
"""
IC Decay Diagnostic — Confidence signal half-life across forward horizons.

Computes Spearman rho between confidence * 100 and |forward return| at
multiple horizons, for one or more (asset, timeframe) pairs.

Usage:
    python app/regression/scripts/ic_decay.py
    python app/regression/scripts/ic_decay.py --assets BTCUSDT,ETHUSDT --horizons 1,4,12,24,48
    python app/regression/scripts/ic_decay.py --regime-split
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from app.regression.api import compute_single_tf_series
from app.regression.config.resolver import ConfigResolver

ROOT = Path(__file__).resolve().parents[3]
CSV_DIR = ROOT / "app" / "trendlines" / "optimization" / "results"
DEFAULT_YAML = Path(__file__).parent.parent / "config" / "regression.yaml"
WINDOW_BARS = 2500


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="IC decay diagnostic for regression confidence signal",
    )
    parser.add_argument(
        "--assets", type=str, default="BTCUSDT,ETHUSDT,SOLUSDT",
        help="Comma-separated list of assets (default: BTCUSDT,ETHUSDT,SOLUSDT)",
    )
    parser.add_argument(
        "--timeframes", type=str, default="1h,4h",
        help="Comma-separated timeframes (default: 1h,4h)",
    )
    parser.add_argument(
        "--horizons", type=str, default="1,4,12,24,48",
        help="Comma-separated forward horizons in bars (default: 1,4,12,24,48)",
    )
    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to regression YAML config",
    )
    parser.add_argument(
        "--regime-split", action="store_true",
        help="Also compute per-regime-family IC decay curves",
    )
    return parser.parse_args(argv)


def _ensure_utc(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    return out


def _load_csv(asset: str) -> pd.DataFrame | None:
    """Load cached CSV for this asset (1h resolution)."""
    candidates = sorted(CSV_DIR.glob(f"{asset}_1h_*.csv"))
    if not candidates:
        return None
    path = candidates[-1]  # most recent
    df = pd.read_csv(path, parse_dates=["open_time"]).set_index("open_time").sort_index()
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    return _ensure_utc(df).iloc[-WINDOW_BARS:]


def _resample(df_1h: pd.DataFrame, tf: str) -> pd.DataFrame:
    if tf == "1h":
        return df_1h
    return df_1h.resample(tf).agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna(subset=["close"])


def _align_results(df, results, window_size):
    """Build aligned DataFrame of confidence + close for IC computation."""
    index = df.index[window_size - 1: window_size - 1 + len(results)]
    frame = pd.DataFrame({
        "close": df["close"].reindex(index).values,
        "confidence": [float(r.confidence) if np.isfinite(r.confidence) else np.nan for r in results],
        "direction": [r.direction for r in results],
        "is_valid": [bool(r.is_valid) for r in results],
    }, index=index)
    frame["confidence_score"] = frame["confidence"] * 100.0
    return frame


def compute_ic_at_horizon(frame: pd.DataFrame, closes_full: pd.Series, horizon: int):
    """Compute Spearman rho between confidence_score and |fwd log return| at horizon."""
    fwd_lr = np.log(closes_full.shift(-horizon) / closes_full).reindex(frame.index)
    valid = frame[frame["is_valid"]].copy()
    valid["abs_fwd_lr"] = fwd_lr.reindex(valid.index).abs()
    valid = valid.dropna(subset=["confidence_score", "abs_fwd_lr"])
    if len(valid) < 30:
        return {"rho": np.nan, "p_value": np.nan, "n": len(valid), "top_quintile_move_ratio": np.nan}

    rho, p_val = stats.spearmanr(valid["confidence_score"], valid["abs_fwd_lr"])

    # Top vs bottom quintile absolute move ratio
    try:
        bins = pd.qcut(valid["confidence_score"], q=5, labels=False, duplicates="drop")
    except ValueError:
        bins = pd.Series(np.zeros(len(valid), dtype=int), index=valid.index)
    valid = valid.assign(bin=bins)
    grouped = valid.groupby("bin")["abs_fwd_lr"].mean()
    top_bin, bottom_bin = grouped.index.max(), grouped.index.min()
    denom = grouped.loc[bottom_bin]
    ratio = float(grouped.loc[top_bin] / denom) if denom > 0 else np.nan

    return {
        "rho": float(rho) if np.isfinite(rho) else np.nan,
        "p_value": float(p_val) if np.isfinite(p_val) else np.nan,
        "n": len(valid),
        "top_quintile_move_ratio": ratio,
    }


def compute_ic_by_regime(frame, closes_full, horizon, regime_results):
    """Compute IC split by regime family (TREND, CHOPPY, MR)."""
    if not regime_results:
        return {}
    # Map regime labels to families
    regime_map = {}
    for r in regime_results:
        label = getattr(r, "regime_label", None) or getattr(r, "label", "UNKNOWN")
        if "TREND" in label.upper():
            regime_map[r] = "TREND"
        elif "CHOP" in label.upper() or "RANGE" in label.upper():
            regime_map[r] = "CHOPPY"
        elif "MR" in label.upper() or "MEAN" in label.upper():
            regime_map[r] = "MR"
        else:
            regime_map[r] = "OTHER"
    # For now, this is a placeholder — regime-split requires regime alignment
    return {}


def main(argv=None) -> int:
    args = parse_args(argv)
    assets = [a.strip() for a in args.assets.split(",")]
    timeframes = [t.strip() for t in args.timeframes.split(",")]
    horizons = [int(h.strip()) for h in args.horizons.split(",")]

    config_path = args.config or str(DEFAULT_YAML)
    resolver = ConfigResolver.from_yaml(config_path)

    rows = []
    peak_horizons = []

    for asset in assets:
        df_1h = _load_csv(asset)
        if df_1h is None:
            print(f"WARNING: No CSV data for {asset}, skipping", file=sys.stderr)
            continue

        for tf in timeframes:
            df = _resample(df_1h, tf)
            if len(df) < 200:
                print(f"WARNING: {asset} {tf} has {len(df)} bars, need 200+, skipping", file=sys.stderr)
                continue

            config = resolver.resolve(asset, tf)
            print(f"Running {asset} {tf} ({len(df)} bars)...")
            results = compute_single_tf_series(df, asset, tf, config)
            frame = _align_results(df, results, config.window_size)

            best_rho, best_h = -1.0, horizons[0]
            for h in horizons:
                ic = compute_ic_at_horizon(frame, df["close"], h)
                rows.append({
                    "asset": asset,
                    "timeframe": tf,
                    "horizon": h,
                    "rho": ic["rho"],
                    "p_value": ic["p_value"],
                    "n": ic["n"],
                    "top_quintile_move_ratio": ic["top_quintile_move_ratio"],
                })
                if np.isfinite(ic["rho"]) and ic["rho"] > best_rho:
                    best_rho = ic["rho"]
                    best_h = h

            peak_horizons.append((asset, tf, best_h, best_rho))

    if not rows:
        print("ERROR: No data processed", file=sys.stderr)
        return 1

    # Print results table
    print()
    print(f"{'Asset':<12} {'TF':<6} {'Horizon':<8} {'Rho':>8} {'p-value':>10} {'N':>6} {'Top/Bot Ratio':>14}")
    print("-" * 70)
    for r in rows:
        rho_str = f"{r['rho']:.4f}" if np.isfinite(r['rho']) else "N/A"
        p_str = f"{r['p_value']:.4f}" if np.isfinite(r['p_value']) else "N/A"
        ratio_str = f"{r['top_quintile_move_ratio']:.4f}" if np.isfinite(r['top_quintile_move_ratio']) else "N/A"
        print(f"{r['asset']:<12} {r['timeframe']:<6} {r['horizon']:<8} {rho_str:>8} {p_str:>10} {r['n']:>6} {ratio_str:>14}")

    print()
    print("Peak IC horizons:")
    for asset, tf, h, rho in peak_horizons:
        print(f"  {asset} {tf}: horizon={h} bars (rho={rho:.4f})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
