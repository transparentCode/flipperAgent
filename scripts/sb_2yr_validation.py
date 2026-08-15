"""SqueezeBreakout 2yr validation with multi-TP backtester.

Tests v7 per-asset optimized params on 2 years of data using:
1. Multi-TP exits (TP1=1.5%/40%, TP2=3%/30%, TP3=5%/rest, SL=2%)
2. Single-TP exits (TP=1.5%, SL=2%)
3. Next-bar returns (baseline comparison)

Usage:
    PYTHONPATH=src .venv/bin/python scripts/sb_2yr_validation.py
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

import numpy as np
import pandas as pd

from libs.models.legacy_bootstrap import bootstrap_legacy_model_registries
from libs.optim_utils.data_fetcher import fetch_historical_ohlcv
from libs.optim_utils.scoring import (
    compute_max_drawdown,
    compute_returns,
    compute_sharpe,
)
from libs.optim_utils.scoring_feature_pipeline import build_scoring_feature_df

bootstrap_legacy_model_registries()
from libs.models.registry import ModelRegistry

# ── Config ─────────────────────────────────────────────────────────────

# Asset configs: (asset, production_timeframe)
ASSET_CONFIGS = [
    ("BTCUSDT", "1h"),
    ("XRPUSDT", "1h"),
    ("SOLUSDT", "1h"),
    ("BNBUSDT", "30m"),
    ("DOGEUSDT", "4h"),
]
DAYS = 730  # ~2 years
COMMISSION_PCT = 0.0004  # 4bps per side (taker)

# Full v7 per-asset optimized params from models.yaml (all 13 params)
V7_PARAMS: dict[str, dict] = {
    "BTCUSDT": {
        "kama_fast_period": 15, "kama_slow_period": 44, "mom_period": 29,
        "squeeze_lookback": 2, "ss_threshold": 1,
        "cci_period": 5, "adx_period": 20, "adx_threshold": 26.0,
        "ad_sma_period": 19, "mfi_period": 9, "mfi_sma_period": 12,
        "mom_lr_period": 18, "mom_lr_mom_period": 6,
    },
    "XRPUSDT": {
        "kama_fast_period": 4, "kama_slow_period": 28, "mom_period": 30,
        "squeeze_lookback": 3, "ss_threshold": 5,
        "cci_period": 3, "adx_period": 13, "adx_threshold": 16.0,
        "ad_sma_period": 23, "mfi_period": 12, "mfi_sma_period": 12,
        "mom_lr_period": 14, "mom_lr_mom_period": 5,
    },
    "SOLUSDT": {
        "kama_fast_period": 5, "kama_slow_period": 43, "mom_period": 19,
        "squeeze_lookback": 1, "ss_threshold": 1,
        "cci_period": 11, "adx_period": 18, "adx_threshold": 20.0,
        "ad_sma_period": 27, "mfi_period": 10, "mfi_sma_period": 5,
        "mom_lr_period": 20, "mom_lr_mom_period": 8,
    },
    "BNBUSDT": {
        "kama_fast_period": 5, "kama_slow_period": 43, "mom_period": 20,
        "squeeze_lookback": 1, "ss_threshold": 3,
        "cci_period": 10, "adx_period": 9, "adx_threshold": 30.0,
        "ad_sma_period": 23, "mfi_period": 21, "mfi_sma_period": 8,
        "mom_lr_period": 9, "mom_lr_mom_period": 10,
    },
    "DOGEUSDT": {
        "kama_fast_period": 3, "kama_slow_period": 29, "mom_period": 16,
        "squeeze_lookback": 1, "ss_threshold": 4,
        "cci_period": 7, "adx_period": 21, "adx_threshold": 20.0,
        "ad_sma_period": 14, "mfi_period": 13, "mfi_sma_period": 7,
        "mom_lr_period": 17, "mom_lr_mom_period": 20,
    },
}


@dataclass
class TradeResult:
    entry_idx: int
    exit_idx: int
    entry_price: float
    exit_price: float
    direction: int
    pnl_pct: float
    exit_type: str
    bars_held: int


@dataclass
class BacktestResult:
    total_return: float
    sharpe: float
    max_drawdown: float
    win_rate: float
    num_trades: int
    avg_bars_held: float
    trades: list[TradeResult]


# ── Multi-TP Backtester ────────────────────────────────────────────────

def multi_tp_backtest(
    df: pd.DataFrame,
    signals: pd.Series,
    sl_pct: float = 0.02,
    tp_levels: list[tuple[float, float]] | None = None,
    commission_pct: float = COMMISSION_PCT,
    bars_per_year: int = 8760,
) -> BacktestResult:
    """Bar-by-bar backtest with tiered take-profit exits.

    tp_levels: list of (target_pct, portion_to_close).
    E.g. [(0.015, 0.4), (0.03, 0.3), (0.05, 1.0)] means:
        TP1 at +1.5%: close 40% of position
        TP2 at +3.0%: close 30%
        TP3 at +5.0%: close remaining
    """
    if tp_levels is None:
        tp_levels = [(0.015, 0.4), (0.03, 0.3), (0.05, 1.0)]

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    sig = signals.values.astype(float)
    n = len(close)

    capital = 1.0
    position = 0
    entry_price = 0.0
    entry_idx = 0
    remaining_size = 0.0  # fraction of original position still open
    tp_stage = 0  # which TP level we're targeting next
    trades: list[TradeResult] = []
    equity = np.ones(n)

    for i in range(1, n):
        if position != 0:
            # Check SL first
            if position == 1:
                sl_hit = low[i] <= entry_price * (1 - sl_pct)
            else:
                sl_hit = high[i] >= entry_price * (1 + sl_pct)

            if sl_hit:
                # Close entire remaining position at SL
                exit_price = entry_price * (1 - sl_pct * position)
                pnl_pct = (exit_price / entry_price - 1) * position
                pnl_pct -= 2 * commission_pct
                capital *= (1 + pnl_pct * remaining_size)
                trades.append(TradeResult(
                    entry_idx=entry_idx, exit_idx=i,
                    entry_price=entry_price, exit_price=exit_price,
                    direction=position, pnl_pct=pnl_pct,
                    exit_type="SL", bars_held=i - entry_idx,
                ))
                position = 0
                remaining_size = 0.0
                tp_stage = 0
            else:
                # Check TP levels
                while tp_stage < len(tp_levels):
                    target_pct, portion = tp_levels[tp_stage]
                    if position == 1:
                        tp_hit = high[i] >= entry_price * (1 + target_pct)
                    else:
                        tp_hit = low[i] <= entry_price * (1 - target_pct)

                    if tp_hit:
                        exit_price = entry_price * (1 + target_pct * position)
                        pnl_pct = (exit_price / entry_price - 1) * position
                        pnl_pct -= 2 * commission_pct

                        if tp_stage < len(tp_levels) - 1:
                            # Partial close
                            close_size = remaining_size * portion
                            capital *= (1 + pnl_pct * close_size)
                            remaining_size -= close_size
                            tp_stage += 1
                            # After TP1: move SL to breakeven
                            if tp_stage == 1:
                                sl_pct_effective = 0.0  # breakeven stop
                                # We'll handle this by checking against entry_price
                        else:
                            # Final TP — close everything
                            capital *= (1 + pnl_pct * remaining_size)
                            trades.append(TradeResult(
                                entry_idx=entry_idx, exit_idx=i,
                                entry_price=entry_price, exit_price=exit_price,
                                direction=position,
                                pnl_pct=(capital / (capital / (1 + pnl_pct * remaining_size)) - 1),
                                exit_type=f"TP{tp_stage + 1}",
                                bars_held=i - entry_idx,
                            ))
                            position = 0
                            remaining_size = 0.0
                            tp_stage = 0
                            break
                    else:
                        break

                # Check breakeven stop (after TP1 hit)
                if position != 0 and tp_stage >= 1:
                    if position == 1 and low[i] <= entry_price:
                        # Breakeven stop hit
                        pnl_pct = -2 * commission_pct  # just commission
                        capital *= (1 + pnl_pct * remaining_size)
                        trades.append(TradeResult(
                            entry_idx=entry_idx, exit_idx=i,
                            entry_price=entry_price, exit_price=entry_price,
                            direction=position, pnl_pct=pnl_pct,
                            exit_type="BE", bars_held=i - entry_idx,
                        ))
                        position = 0
                        remaining_size = 0.0
                        tp_stage = 0
                    elif position == -1 and high[i] >= entry_price:
                        pnl_pct = -2 * commission_pct
                        capital *= (1 + pnl_pct * remaining_size)
                        trades.append(TradeResult(
                            entry_idx=entry_idx, exit_idx=i,
                            entry_price=entry_price, exit_price=entry_price,
                            direction=position, pnl_pct=pnl_pct,
                            exit_type="BE", bars_held=i - entry_idx,
                        ))
                        position = 0
                        remaining_size = 0.0
                        tp_stage = 0

        # New entry
        if position == 0 and sig[i] != 0:
            position = int(sig[i])
            entry_price = close[i]
            entry_idx = i
            remaining_size = 1.0
            tp_stage = 0

        # Mark-to-market
        if position != 0:
            unrealized = (close[i] / entry_price - 1) * position
            equity[i] = capital * (1 + unrealized * remaining_size)
        else:
            equity[i] = capital

    # Close any remaining position at last bar
    if position != 0:
        pnl_pct = (close[-1] / entry_price - 1) * position - 2 * commission_pct
        capital *= (1 + pnl_pct * remaining_size)
        trades.append(TradeResult(
            entry_idx=entry_idx, exit_idx=n - 1,
            entry_price=entry_price, exit_price=close[-1],
            direction=position, pnl_pct=pnl_pct,
            exit_type="EOD", bars_held=n - 1 - entry_idx,
        ))
        equity[-1] = capital

    # Metrics
    eq = pd.Series(equity)
    returns = eq.pct_change().dropna()
    sharpe = float(returns.mean() / returns.std() * np.sqrt(bars_per_year)) if returns.std() > 0 else 0.0
    cum = np.cumprod(1 + returns.values)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    max_dd = float(np.min(dd)) if len(dd) > 0 else 0.0

    win_count = sum(1 for t in trades if t.pnl_pct > 0)
    win_rate = win_count / len(trades) if trades else 0.0
    avg_bars = np.mean([t.bars_held for t in trades]) if trades else 0.0

    return BacktestResult(
        total_return=capital - 1.0,
        sharpe=sharpe,
        max_drawdown=max_dd,
        win_rate=win_rate,
        num_trades=len(trades),
        avg_bars_held=avg_bars,
        trades=trades,
    )


def single_tp_backtest(
    df: pd.DataFrame,
    signals: pd.Series,
    sl_pct: float = 0.02,
    tp_pct: float = 0.015,
    commission_pct: float = COMMISSION_PCT,
    bars_per_year: int = 8760,
) -> BacktestResult:
    """Simple single SL/TP backtest."""
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    sig = signals.values.astype(float)
    n = len(close)

    capital = 1.0
    position = 0
    entry_price = 0.0
    entry_idx = 0
    trades: list[TradeResult] = []
    equity = np.ones(n)

    for i in range(1, n):
        if position != 0:
            if position == 1:
                sl_hit = low[i] <= entry_price * (1 - sl_pct)
                tp_hit = high[i] >= entry_price * (1 + tp_pct)
            else:
                sl_hit = high[i] >= entry_price * (1 + sl_pct)
                tp_hit = low[i] <= entry_price * (1 - tp_pct)

            if sl_hit or tp_hit:
                if tp_hit:
                    exit_price = entry_price * (1 + tp_pct * position)
                    exit_type = "TP"
                else:
                    exit_price = entry_price * (1 - sl_pct * position)
                    exit_type = "SL"

                pnl_pct = (exit_price / entry_price - 1) * position - 2 * commission_pct
                capital *= (1 + pnl_pct)
                trades.append(TradeResult(
                    entry_idx=entry_idx, exit_idx=i,
                    entry_price=entry_price, exit_price=exit_price,
                    direction=position, pnl_pct=pnl_pct,
                    exit_type=exit_type, bars_held=i - entry_idx,
                ))
                position = 0

        if position == 0 and sig[i] != 0:
            position = int(sig[i])
            entry_price = close[i]
            entry_idx = i

        if position != 0:
            unrealized = (close[i] / entry_price - 1) * position
            equity[i] = capital * (1 + unrealized)
        else:
            equity[i] = capital

    if position != 0:
        pnl_pct = (close[-1] / entry_price - 1) * position - 2 * commission_pct
        capital *= (1 + pnl_pct)
        trades.append(TradeResult(
            entry_idx=entry_idx, exit_idx=n - 1,
            entry_price=entry_price, exit_price=close[-1],
            direction=position, pnl_pct=pnl_pct,
            exit_type="EOD", bars_held=n - 1 - entry_idx,
        ))
        equity[-1] = capital

    eq = pd.Series(equity)
    returns = eq.pct_change().dropna()
    sharpe = float(returns.mean() / returns.std() * np.sqrt(bars_per_year)) if returns.std() > 0 else 0.0
    cum = np.cumprod(1 + returns.values)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    max_dd = float(np.min(dd)) if len(dd) > 0 else 0.0

    win_count = sum(1 for t in trades if t.pnl_pct > 0)
    win_rate = win_count / len(trades) if trades else 0.0
    avg_bars = np.mean([t.bars_held for t in trades]) if trades else 0.0

    return BacktestResult(
        total_return=capital - 1.0,
        sharpe=sharpe, max_drawdown=max_dd,
        win_rate=win_rate, num_trades=len(trades),
        avg_bars_held=avg_bars, trades=trades,
    )


# ── Main ───────────────────────────────────────────────────────────────

def run_asset(asset: str, timeframe: str) -> dict:
    # Estimate bars per day based on timeframe
    tf_bars_per_day = {"1m": 1440, "5m": 288, "15m": 96, "30m": 48, "1h": 24, "4h": 6, "1d": 1}
    bars_per_day = tf_bars_per_day.get(timeframe, 24)

    print(f"\n{'='*70}")
    print(f"  {asset} — {DAYS}d (2yr), {timeframe}")
    print(f"{'='*70}")

    # Fetch data
    since_ms = int((time.time() - DAYS * 86400) * 1000)
    limit = DAYS * bars_per_day
    print(f"  Fetching {DAYS}d of {timeframe} candles (~{limit} bars)...")
    ohlcv_df = fetch_historical_ohlcv(
        symbol=asset, timeframe=timeframe, since=since_ms, limit=limit,
    )
    print(f"  Fetched {len(ohlcv_df)} candles")

    if len(ohlcv_df) < 500:
        print(f"  ⚠ Insufficient data, skipping")
        return {"asset": asset, "status": "SKIP"}

    # Build features
    print("  Computing indicators...")
    feature_df = build_scoring_feature_df(ohlcv_df, asset, timeframe)
    print(f"  Features: {len(feature_df)} rows, {len(feature_df.columns)} cols")

    # Buy & Hold baseline
    bnh_return = (ohlcv_df["close"].iloc[-1] / ohlcv_df["close"].iloc[0]) - 1
    bnh_returns = ohlcv_df["close"].pct_change().dropna()
    bnh_sharpe = float(bnh_returns.mean() / bnh_returns.std() * np.sqrt(365 * bars_per_day)) if bnh_returns.std() > 0 else 0.0

    model_cls = ModelRegistry.get("SqueezeBreakout")

    # v7 optimized params (all 13 from models.yaml)
    v7_p = V7_PARAMS[asset]
    model_opt = model_cls(v7_p)
    dirs_opt = model_opt.batch_evaluate(feature_df)

    # Default params
    default_p = {k: v.default for k, v in model_cls.meta.hyperparameter_schema.items()}
    model_def = model_cls(default_p)
    dirs_def = model_def.batch_evaluate(feature_df)

    n_signals_opt = int((dirs_opt != 0).sum())
    n_signals_def = int((dirs_def != 0).sum())
    print(f"  Signals: {n_signals_opt} (v7 optimized), {n_signals_def} (defaults)")

    results = {"asset": asset, "timeframe": timeframe, "status": "OK",
               "n_bars": len(feature_df),
               "bnh_return": bnh_return, "bnh_sharpe": bnh_sharpe}

    # Bars per year for Sharpe annualization
    bars_per_year = 365 * bars_per_day

    # Run backtests
    for label, dirs, params_label in [
        ("v7_opt", dirs_opt, "v7 optimized"),
        ("defaults", dirs_def, "defaults"),
    ]:
        # Multi-TP
        mtp = multi_tp_backtest(feature_df, dirs, bars_per_year=bars_per_year)
        # Single-TP
        stp = single_tp_backtest(feature_df, dirs, bars_per_year=bars_per_year)
        # Next-bar returns
        close = feature_df["close"].values
        nb_returns, nb_mask = compute_returns(dirs.values, close, cost_bps=8.0)
        nb_sharpe = compute_sharpe(nb_returns, timeframe)
        nb_dd = compute_max_drawdown(nb_returns)
        nb_return = float(np.prod(1 + nb_returns) - 1)
        nb_trades = int(np.sum(nb_mask))

        results[f"{label}_multi_tp"] = mtp
        results[f"{label}_single_tp"] = stp
        results[f"{label}_nextbar"] = {
            "sharpe": nb_sharpe, "return": nb_return,
            "max_dd": nb_dd, "trades": nb_trades,
        }

    # Print results
    print(f"\n  Buy & Hold: Return={bnh_return:+.2%}  Sharpe={bnh_sharpe:.2f}")
    print(f"\n  {'Method':<18} {'Params':<12} {'Sharpe':>8} {'Return':>10} {'MaxDD':>8} {'Trades':>7} {'WR':>6} {'AvgBars':>8}")
    print(f"  {'-'*73}")

    for label, params_label in [("v7_opt", "v7 opt"), ("defaults", "defaults")]:
        mtp = results[f"{label}_multi_tp"]
        stp = results[f"{label}_single_tp"]
        nb = results[f"{label}_nextbar"]

        print(f"  {'Multi-TP':<18} {params_label:<12} {mtp.sharpe:>+8.2f} {mtp.total_return:>+10.2%} {mtp.max_drawdown:>8.2%} {mtp.num_trades:>7} {mtp.win_rate:>5.0%} {mtp.avg_bars_held:>8.1f}")
        print(f"  {'Single-TP':<18} {params_label:<12} {stp.sharpe:>+8.2f} {stp.total_return:>+10.2%} {stp.max_drawdown:>8.2%} {stp.num_trades:>7} {stp.win_rate:>5.0%} {stp.avg_bars_held:>8.1f}")
        print(f"  {'Next-bar':<18} {params_label:<12} {nb['sharpe']:>+8.2f} {nb['return']:>+10.2%} {nb['max_dd']:>8.2%} {nb['trades']:>7} {'—':>6} {'—':>8}")
        print()

    # Exit type breakdown for v7 multi-TP
    mtp_trades = results["v7_opt_multi_tp"].trades
    if mtp_trades:
        types = {}
        for t in mtp_trades:
            types[t.exit_type] = types.get(t.exit_type, 0) + 1
        print(f"  v7 Multi-TP exit breakdown: {types}")

    return results


def main():
    print("=" * 70)
    print("  SQUEEZEBREAKOUT 2yr VALIDATION (Production Params + Timeframes)")
    print(f"  Assets: {', '.join(a + '/' + tf for a, tf in ASSET_CONFIGS)}")
    print(f"  Period: ~{DAYS}d ({DAYS/365:.1f}yr)")
    print(f"  Backtester modes: Multi-TP, Single-TP, Next-bar")
    print("=" * 70)

    all_results = []
    for asset, timeframe in ASSET_CONFIGS:
        r = run_asset(asset, timeframe)
        all_results.append(r)

    # Summary
    print("\n" + "=" * 70)
    print("  SUMMARY — v7 Optimized Params, Multi-TP Backtester")
    print("=" * 70)
    print(f"\n  {'Asset':<14} {'TF':<5} {'Sharpe':>8} {'Return':>10} {'MaxDD':>8} {'Trades':>7} {'WR':>6} {'B&H Sharpe':>10} {'vs B&H':>8}")
    print(f"  {'-'*72}")

    for r in all_results:
        if r["status"] != "OK":
            print(f"  {r['asset']:<14} SKIP")
            continue
        mtp = r["v7_opt_multi_tp"]
        bnh_s = r["bnh_sharpe"]
        diff = mtp.sharpe - bnh_s
        tf = r["timeframe"]
        print(f"  {r['asset']:<14} {tf:<5} {mtp.sharpe:>+8.2f} {mtp.total_return:>+10.2%} {mtp.max_drawdown:>8.2%} {mtp.num_trades:>7} {mtp.win_rate:>5.0%} {bnh_s:>+10.2f} {diff:>+8.2f}")

    print(f"\n  SINGLE-TP RESULTS (v7 optimized):")
    print(f"  {'Asset':<14} {'TF':<5} {'Sharpe':>8} {'Return':>10} {'MaxDD':>8} {'Trades':>7} {'WR':>6}")
    print(f"  {'-'*55}")
    for r in all_results:
        if r["status"] != "OK":
            continue
        stp = r["v7_opt_single_tp"]
        tf = r["timeframe"]
        print(f"  {r['asset']:<14} {tf:<5} {stp.sharpe:>+8.2f} {stp.total_return:>+10.2%} {stp.max_drawdown:>8.2%} {stp.num_trades:>7} {stp.win_rate:>5.0%}")

    print(f"\n  BACKTESTER EFFECT (v7 opt: Multi-TP vs Next-bar):")
    print(f"  {'Asset':<14} {'MultiTP':>10} {'SingleTP':>10} {'NextBar':>10}")
    print(f"  {'-'*50}")
    for r in all_results:
        if r["status"] != "OK":
            continue
        mtp_s = r["v7_opt_multi_tp"].sharpe
        stp_s = r["v7_opt_single_tp"].sharpe
        nb_s = r["v7_opt_nextbar"]["sharpe"]
        print(f"  {r['asset']:<14} {mtp_s:>+10.2f} {stp_s:>+10.2f} {nb_s:>+10.2f}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
