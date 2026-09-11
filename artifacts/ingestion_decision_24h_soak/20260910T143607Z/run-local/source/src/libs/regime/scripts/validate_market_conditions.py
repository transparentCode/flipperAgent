#!/usr/bin/env python3
"""Phase 0 validation: MarketConditionFeatures (continuous condition_scale).

Demonstrates p < 0.10 conditional return separation between top and bottom
condition_scale quintiles.  If this gate fails, we fall back to Option D
(abandon regime entirely).

Usage:
    PYTHONPATH=src .venv/bin/python src/libs/regime/scripts/validate_market_conditions.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu, spearmanr

from libs.optim_utils.data_fetcher import fetch_historical_ohlcv
from libs.optim_utils.scoring import compute_sharpe

# ---------------------------------------------------------------------------
# 1. Data loading helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[4]  # -> flipperAgent/
TV_INDEX_DIR = PROJECT_ROOT / "data" / "tv_index"


def _load_ohlcv_frame(asset: str, timeframe: str, *, days: int) -> pd.DataFrame:
    """Minimal copy of downstream_backtest.load_ohlcv_frame (no regime deps)."""
    end = pd.Timestamp.now("UTC")
    start = end - pd.Timedelta(days=days)
    seconds_per_bar = {"30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}[timeframe]
    limit = int(((end - start).total_seconds()) / seconds_per_bar) + 32
    df = fetch_historical_ohlcv(
        asset,
        timeframe,
        since=int(start.timestamp() * 1000),
        until=int(end.timestamp() * 1000),
        limit=limit,
    )
    if df.empty:
        return df
    frame = df.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    frame = frame.set_index("timestamp").sort_index()
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = frame[col].astype(float)
    return frame[["open", "high", "low", "close", "volume"]]


def _load_breadth_csv(name: str) -> pd.Series:
    """Load a TV-index CSV and return its close series with DatetimeIndex."""
    path = TV_INDEX_DIR / name
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    # The CSV may have a 'datetime' column as well; use it if index is epoch.
    if not isinstance(df.index, pd.DatetimeIndex):
        if "datetime" in df.columns:
            df.index = pd.to_datetime(df["datetime"], utc=True)
        else:
            df.index = pd.to_datetime(df.index, unit="s", utc=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df["close"].sort_index().astype(float)


# ---------------------------------------------------------------------------
# 2. Feature computation
# ---------------------------------------------------------------------------


def compute_vol_rank(
    close: pd.Series, lookback: int = 168, rank_window: int = 1000
) -> pd.Series:
    """Rolling log-return stddev percentile-ranked over *rank_window* bars."""
    log_ret = np.log(close).diff()
    rolling_vol = log_ret.rolling(lookback, min_periods=lookback).std()
    vol_rank = rolling_vol.rolling(rank_window, min_periods=rank_window).apply(
        lambda w: (w.values[:-1] < w.values[-1]).sum() / (len(w) - 1) * 100,
        raw=False,
    )
    return vol_rank


def compute_trend_strength(close: pd.Series, n: int = 20) -> pd.Series:
    """Directional efficiency: |close[-N]-close[0]| / sum(|diff|) over N bars."""
    abs_diff = close.diff().abs()
    sum_abs_diff = abs_diff.rolling(n, min_periods=n).sum()
    net_move = (close - close.shift(n)).abs()
    ts = net_move / sum_abs_diff.replace(0, np.nan)
    return ts.clip(0, 1)


def compute_breadth_score(
    btc_d: pd.Series,
    total3: pd.Series,
    asset_index: pd.DatetimeIndex,
) -> pd.Series:
    """Breadth signal from BTC.D and TOTAL3, aligned to asset bars."""
    tolerance = pd.Timedelta(hours=2)
    btc_d = btc_d.reindex(asset_index, method="ffill", tolerance=tolerance)
    total3 = total3.reindex(asset_index, method="ffill", tolerance=tolerance)

    btc_d_z = (btc_d - btc_d.rolling(50, min_periods=50).mean()) / btc_d.rolling(
        50, min_periods=50
    ).std()
    total3_mom = (
        total3 - total3.rolling(20, min_periods=20).mean()
    ) / total3.rolling(20, min_periods=20).std()

    raw = 0.5 * (-btc_d_z + total3_mom)
    return np.tanh(raw)


def compute_condition_scale(
    trend_strength: pd.Series,
    vol_rank: pd.Series,
    breadth_score: pd.Series | None = None,
) -> pd.Series:
    if breadth_score is not None:
        raw = (
            0.4 * trend_strength
            + 0.3 * (1 - vol_rank / 100)
            + 0.3 * (breadth_score + 1) / 2
        )
    else:
        # No breadth: 55/45 split between trend and inverse-vol
        raw = 0.55 * trend_strength + 0.45 * (1 - vol_rank / 100)
    return raw.clip(0, 1)


# ---------------------------------------------------------------------------
# 3. Validation tests
# ---------------------------------------------------------------------------

FORWARD_BARS = 4  # 4-bar forward log return


def _forward_log_returns(close: pd.Series, n: int = FORWARD_BARS) -> pd.Series:
    return np.log(close.shift(-n) / close)


def run_validation(
    condition_scale: pd.Series,
    close: pd.Series,
    train_frac: float = 0.60,
) -> dict:
    """Run all Phase-0 validation tests on the out-of-sample portion."""

    fwd_ret = _forward_log_returns(close)

    # Combine and drop NaN
    combined = pd.DataFrame(
        {"cs": condition_scale, "fwd": fwd_ret}
    ).dropna()

    n_train = int(len(combined) * train_frac)
    test = combined.iloc[n_train:].copy()

    results: dict = {"n_test_bars": len(test)}

    # --- (a) Quintile return separation ---
    test["quintile"] = pd.qcut(test["cs"], 5, labels=False, duplicates="drop") + 1
    q_means = test.groupby("quintile")["fwd"].mean()
    results["quintile_means"] = q_means.to_dict()

    q1 = test.loc[test["quintile"] == q_means.index.min(), "fwd"].values
    q5 = test.loc[test["quintile"] == q_means.index.max(), "fwd"].values
    u_stat, p_value = mannwhitneyu(q5, q1, alternative="greater")
    results["mann_whitney_u"] = float(u_stat)
    results["p_value"] = float(p_value)
    results["gate_pass"] = p_value < 0.10

    # --- (b) Monotonicity ---
    quintile_nums = np.array(list(q_means.index))
    quintile_vals = np.array(list(q_means.values))
    sp_corr, sp_p = spearmanr(quintile_nums, quintile_vals)
    results["monotonicity_spearman"] = float(sp_corr)
    results["monotonicity_p"] = float(sp_p)

    # --- (c) Conditional Sharpe lift ---
    high_mask = test["cs"] > 0.6
    low_mask = test["cs"] < 0.4
    sharpe_high = compute_sharpe(test.loc[high_mask, "fwd"].values, "1h") if high_mask.sum() > 30 else float("nan")
    sharpe_low = compute_sharpe(test.loc[low_mask, "fwd"].values, "1h") if low_mask.sum() > 30 else float("nan")
    results["sharpe_high_cs"] = sharpe_high
    results["sharpe_low_cs"] = sharpe_low
    results["sharpe_lift"] = sharpe_high - sharpe_low if not (math.isnan(sharpe_high) or math.isnan(sharpe_low)) else float("nan")

    # --- (d) IC ---
    ic, ic_p = spearmanr(test["cs"].values, test["fwd"].values)
    n_obs = len(test)
    ic_t = ic * math.sqrt((n_obs - 2) / (1 - ic**2)) if abs(ic) < 1 else float("nan")
    results["ic"] = float(ic)
    results["ic_p"] = float(ic_p)
    results["ic_t"] = float(ic_t)

    # --- (e) Position-scaled equity curve ---
    log_ret = np.log(close / close.shift(1)).reindex(test.index)
    pos = test["cs"].values
    pos_change = np.abs(np.diff(pos, prepend=pos[0]))
    cost_per_bar = np.where(pos_change > 0.1, 10 / 1e4, 0.0)  # 10bps round-trip
    scaled_ret = pos * log_ret.values - cost_per_bar
    bh_ret = log_ret.values

    mask_valid = ~np.isnan(scaled_ret) & ~np.isnan(bh_ret)
    sharpe_scaled = compute_sharpe(scaled_ret[mask_valid], "1h")
    sharpe_bh = compute_sharpe(bh_ret[mask_valid], "1h")
    results["sharpe_scaled"] = sharpe_scaled
    results["sharpe_bh"] = sharpe_bh
    results["sharpe_vs_bh"] = sharpe_scaled - sharpe_bh

    # Cumulative returns
    cum_scaled = np.nancumsum(scaled_ret)
    cum_bh = np.nancumsum(bh_ret)
    results["total_ret_scaled"] = float(np.exp(cum_scaled[-1]) - 1) if len(cum_scaled) else float("nan")
    results["total_ret_bh"] = float(np.exp(cum_bh[-1]) - 1) if len(cum_bh) else float("nan")

    return results


# ---------------------------------------------------------------------------
# 4. Report
# ---------------------------------------------------------------------------


def print_report(results: dict, label: str = "") -> None:
    sep = "=" * 60
    title = f"  PHASE 0 VALIDATION: {label}" if label else "  PHASE 0 VALIDATION: MarketConditionFeatures"
    print(f"\n{sep}")
    print(title)
    print(sep)

    print(f"\n  Test bars: {results['n_test_bars']:,}")

    print("\n  --- (a) Quintile Return Separation ---")
    for q, m in sorted(results["quintile_means"].items()):
        print(f"    Q{q} mean 4-bar fwd log-ret: {m:+.6f}")
    print(f"    Mann-Whitney U statistic: {results['mann_whitney_u']:.1f}")
    print(f"    p-value (one-sided):       {results['p_value']:.6f}")

    print("\n  --- (b) Monotonicity ---")
    print(f"    Spearman rho (quintile vs mean ret): {results['monotonicity_spearman']:+.4f}")
    print(f"    Spearman p-value:                    {results['monotonicity_p']:.4f}")

    print("\n  --- (c) Conditional Sharpe Lift ---")
    print(f"    Sharpe (condition_scale > 0.6): {results['sharpe_high_cs']:+.4f}")
    print(f"    Sharpe (condition_scale < 0.4): {results['sharpe_low_cs']:+.4f}")
    print(f"    Lift:                           {results['sharpe_lift']:+.4f}")

    print("\n  --- (d) Information Coefficient ---")
    print(f"    IC (Spearman):  {results['ic']:+.6f}")
    print(f"    IC t-stat:      {results['ic_t']:+.4f}")
    print(f"    IC p-value:     {results['ic_p']:.6f}")

    print("\n  --- (e) Position-Scaled Equity ---")
    print(f"    Sharpe (scaled):      {results['sharpe_scaled']:+.4f}")
    print(f"    Sharpe (buy & hold):  {results['sharpe_bh']:+.4f}")
    print(f"    Sharpe delta:         {results['sharpe_vs_bh']:+.4f}")
    print(f"    Total return scaled:  {results['total_ret_scaled']:+.2%}")
    print(f"    Total return B&H:     {results['total_ret_bh']:+.2%}")

    print(f"\n{sep}")
    if results["gate_pass"]:
        print("  >>> GATE RESULT: PASS  (p = {:.4f} < 0.10) <<<".format(results["p_value"]))
    else:
        print("  >>> GATE RESULT: FAIL  (p = {:.4f} >= 0.10) <<<".format(results["p_value"]))
    print(sep)


# ---------------------------------------------------------------------------
# 5. Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("Loading BTCUSDT 1h OHLCV (3 years)...")
    df = _load_ohlcv_frame("BTCUSDT", "1h", days=1095)
    if df.empty:
        print("ERROR: No OHLCV data returned.", file=sys.stderr)
        sys.exit(1)
    print(f"  {len(df):,} bars from {df.index[0]} to {df.index[-1]}")

    close = df["close"]

    print("Computing core features (vol_rank, trend_strength)...")
    vol_rank = compute_vol_rank(close)
    trend_strength = compute_trend_strength(close)

    # ── Variant A: vol_rank + trend_strength only (full 3-year dataset) ──
    print("\n" + "#" * 60)
    print("  VARIANT A: vol_rank + trend_strength (NO breadth)")
    print("#" * 60)
    cs_no_breadth = compute_condition_scale(trend_strength, vol_rank, breadth_score=None)
    valid_a = cs_no_breadth.dropna()
    print(f"  condition_scale: {len(valid_a):,} valid bars "
          f"(mean={valid_a.mean():.3f}, std={valid_a.std():.3f})")
    print("Running walk-forward validation (60/40 split)...")
    results_a = run_validation(cs_no_breadth, close)
    print_report(results_a, label="Variant A — vol_rank + trend_strength only")

    # ── Variant B: vol_rank + trend_strength + breadth (limited data) ──
    print("\n" + "#" * 60)
    print("  VARIANT B: vol_rank + trend_strength + breadth_score")
    print("#" * 60)
    print("Loading breadth data (BTC.D, TOTAL2, TOTAL3)...")
    btc_d = _load_breadth_csv("BTC_D_1h.csv")
    total3 = _load_breadth_csv("TOTAL3_1h.csv")
    print(f"  BTC.D: {len(btc_d):,} bars,  TOTAL3: {len(total3):,} bars")

    breadth_score = compute_breadth_score(btc_d, total3, close.index)
    cs_with_breadth = compute_condition_scale(trend_strength, vol_rank, breadth_score)
    valid_b = cs_with_breadth.dropna()
    print(f"  condition_scale: {len(valid_b):,} valid bars "
          f"(mean={valid_b.mean():.3f}, std={valid_b.std():.3f})")
    print("Running walk-forward validation (60/40 split)...")
    results_b = run_validation(cs_with_breadth, close)
    print_report(results_b, label="Variant B — vol_rank + trend_strength + breadth")

    # ── Side-by-side comparison ──
    sep = "=" * 60
    print(f"\n{sep}")
    print("  SIDE-BY-SIDE COMPARISON")
    print(sep)
    fmt = "  {:<30s} {:>12s} {:>12s}"
    print(fmt.format("Metric", "A (no brdth)", "B (w/ brdth)"))
    print("  " + "-" * 56)
    print(fmt.format("Test bars", f"{results_a['n_test_bars']:,}", f"{results_b['n_test_bars']:,}"))
    print(fmt.format("p-value (Q5 vs Q1)", f"{results_a['p_value']:.4f}", f"{results_b['p_value']:.4f}"))
    print(fmt.format("Monotonicity rho", f"{results_a['monotonicity_spearman']:+.4f}", f"{results_b['monotonicity_spearman']:+.4f}"))
    print(fmt.format("IC (Spearman)", f"{results_a['ic']:+.6f}", f"{results_b['ic']:+.6f}"))
    print(fmt.format("Sharpe lift (hi-lo CS)", f"{results_a['sharpe_lift']:+.4f}" if not math.isnan(results_a.get('sharpe_lift', float('nan'))) else "N/A",
                      f"{results_b['sharpe_lift']:+.4f}" if not math.isnan(results_b.get('sharpe_lift', float('nan'))) else "N/A"))
    print(fmt.format("Sharpe scaled", f"{results_a['sharpe_scaled']:+.4f}", f"{results_b['sharpe_scaled']:+.4f}"))
    print(fmt.format("Sharpe B&H", f"{results_a['sharpe_bh']:+.4f}", f"{results_b['sharpe_bh']:+.4f}"))
    print(fmt.format("Sharpe delta", f"{results_a['sharpe_vs_bh']:+.4f}", f"{results_b['sharpe_vs_bh']:+.4f}"))
    print(fmt.format("Total return scaled", f"{results_a['total_ret_scaled']:+.2%}", f"{results_b['total_ret_scaled']:+.2%}"))
    print(fmt.format("Total return B&H", f"{results_a['total_ret_bh']:+.2%}", f"{results_b['total_ret_bh']:+.2%}"))

    gate_a = "PASS" if results_a["gate_pass"] else "FAIL"
    gate_b = "PASS" if results_b["gate_pass"] else "FAIL"
    print(f"\n  Gate A (no breadth):   {gate_a}  (p={results_a['p_value']:.4f})")
    print(f"  Gate B (with breadth): {gate_b}  (p={results_b['p_value']:.4f})")
    print(sep)


if __name__ == "__main__":
    main()
