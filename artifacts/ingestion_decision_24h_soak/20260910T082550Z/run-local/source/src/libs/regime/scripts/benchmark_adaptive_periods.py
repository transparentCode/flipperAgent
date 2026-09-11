"""
Adaptive Period Lengths Benchmark
=================================
Validates the 3-level adaptive period hierarchy by comparing adaptive-length
indicators against fixed-length baselines on real or synthetic market data.

Metrics:
  A. Computation Performance  — timeit for scalar and vectorized paths
  B. Signal Quality           — Forward return correlation (adaptive RSI vs fixed RSI)
  C. Regime Alignment         — Period adaptation vs regime duration
  D. Period Stability         — Flip-flop rate of adaptive periods
  E. Strategy Utility (RSI)   — Simple RSI mean-reversion PnL: adaptive vs fixed
  F. Hilbert Confidence Dist  — Tier breakdown (Level 1 / 2 / 3) driving periods
  G. Strategy Utility (BB)    — Bollinger Band touch mean-reversion: adaptive vs fixed
  H. Cross-Asset Validation   — Same tests on multiple symbols / timeframes

Usage:
    # Synthetic data (no API key needed)
    python -m libs.regime.scripts.benchmark_adaptive_periods --mode synthetic --bars 2000

    # Live Binance data (single asset)
    python -m libs.regime.scripts.benchmark_adaptive_periods --mode live --symbol BTCUSDT --timeframe 1h --start 2024-01-01 --end 2025-01-01

    # Cross-asset validation
    python -m libs.regime.scripts.benchmark_adaptive_periods --mode cross-asset --perf-runs 100
"""

import sys
import os
import argparse
import time
import logging
from pathlib import Path
from typing import Dict, Any, Tuple, List as TypingList

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from libs.regime.config_loader import load_yaml_config
from libs.regime.orchestrator import RegimeOrchestrator
from libs.regime.aggregation.rule_based import FeatureAggregator, AggregatorConfig

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("AdaptivePeriodBenchmark")


# ---------------------------------------------------------------------------
# Data Generation
# ---------------------------------------------------------------------------

def generate_synthetic_data(n_bars: int = 2000, seed: int = 42) -> pd.DataFrame:
    """
    Generate synthetic multi-regime OHLCV data.

    Creates concatenated segments with distinct statistical properties:
      - Trending:       drift=+0.001, vol=0.008
      - Mean-reverting: drift=0, vol=0.005, OU pull
      - Volatile:       drift=0, vol=0.025
      - Random-walk:    drift=0, vol=0.012
    """
    rng = np.random.RandomState(seed)
    segment_len = n_bars // 4
    segments = []

    # Trending
    r = rng.randn(segment_len) * 0.008 + 0.001
    segments.append(r)

    # Mean-reverting (OU-like)
    mr = np.zeros(segment_len)
    x = 0.0
    for i in range(segment_len):
        mr[i] = -0.15 * x + rng.randn() * 0.005
        x += mr[i]
    segments.append(mr)

    # Volatile
    r = rng.randn(segment_len) * 0.025
    segments.append(r)

    # Random walk
    r = rng.randn(n_bars - 3 * segment_len) * 0.012
    segments.append(r)

    returns = np.concatenate(segments)
    prices = 100.0 * np.exp(np.cumsum(returns))
    dates = pd.date_range('2024-01-01', periods=len(prices), freq='h')

    return pd.DataFrame({
        'close': prices,
        'volume': rng.uniform(1000, 10000, len(prices)),
    }, index=dates)


def fetch_live_data(symbol: str, timeframe: str, start: str, end: str) -> pd.DataFrame:
    """Fetch live data via BinanceConnector."""
    from app.connectors.BinanceConnector import BinanceConnector
    from datetime import datetime

    symbol = symbol.replace("/", "")
    start_ts = int(datetime.strptime(start, "%Y-%m-%d").timestamp() * 1000)
    end_ts = int(datetime.strptime(end, "%Y-%m-%d").timestamp() * 1000)

    conn = BinanceConnector()
    all_dfs = []
    current_start = start_ts

    while current_start < end_ts:
        df = conn.get_futures_klines(symbol, timeframe, current_start, end_ts, limit=1500)
        if df is None or len(df) == 0:
            break
        all_dfs.append(df)
        last_time = int(df.index[-1].timestamp() * 1000)
        if last_time >= end_ts or len(df) <= 1:
            break
        current_start = last_time + 1
        time.sleep(0.3)

    if not all_dfs:
        raise ValueError("Failed to fetch data from Binance.")

    final_df = pd.concat(all_dfs)
    final_df = final_df[~final_df.index.duplicated(keep='first')].sort_index()
    if not isinstance(final_df.index, pd.DatetimeIndex):
        final_df.index = pd.to_datetime(final_df.index, unit='ms')

    logger.info(f"Fetched {len(final_df)} bars for {symbol} {timeframe}")
    return final_df


# ---------------------------------------------------------------------------
# RSI Helpers
# ---------------------------------------------------------------------------

def compute_rsi_series(close: np.ndarray, period: int) -> np.ndarray:
    """Standard RSI computation returning array of same length as close."""
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)

    avg_gain = np.full_like(close, np.nan)
    avg_loss = np.full_like(close, np.nan)

    if period >= len(close):
        return np.full_like(close, 50.0)

    avg_gain[period] = gain[1:period + 1].mean()
    avg_loss[period] = loss[1:period + 1].mean()

    for i in range(period + 1, len(close)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gain[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + loss[i]) / period

    rs = np.where(avg_loss > 0, avg_gain / avg_loss, 100.0)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi[:period] = 50.0
    return rsi


def compute_adaptive_rsi(close: np.ndarray, periods: np.ndarray) -> np.ndarray:
    """
    Compute RSI with per-bar adaptive period.
    Uses a warm-up approach: for each bar, compute RSI using last `period` bars.
    """
    n = len(close)
    rsi = np.full(n, 50.0)
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)

    for i in range(20, n):
        p = int(periods[i])
        p = max(5, min(p, i))
        g = gain[i - p + 1:i + 1]
        l = loss[i - p + 1:i + 1]
        avg_g = g.mean()
        avg_l = l.mean()
        if avg_l > 0:
            rs = avg_g / avg_l
            rsi[i] = 100.0 - 100.0 / (1.0 + rs)
        else:
            rsi[i] = 100.0 if avg_g > 0 else 50.0
    return rsi


# ---------------------------------------------------------------------------
# Benchmark Functions
# ---------------------------------------------------------------------------

def benchmark_computation_performance(df: pd.DataFrame, n_runs: int = 50) -> Dict[str, Any]:
    """Benchmark scalar (analyze) and vectorized (analyze_series) pipeline speed."""
    orchestrator = RegimeOrchestrator.create("BTCUSDT", "1h")

    # Warm up
    _ = orchestrator.analyze(df)

    # --- Scalar path: full single-window analysis ---
    times_scalar = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        orchestrator.analyze(df)
        times_scalar.append((time.perf_counter() - t0) * 1e3)  # milliseconds

    # --- Vectorized path: full series analysis ---
    times_vec = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        orchestrator.analyze_series(df)
        times_vec.append((time.perf_counter() - t0) * 1e3)  # milliseconds

    return {
        'scalar_mean_us': np.mean(times_scalar) * 1000,   # convert to µs for report
        'scalar_p50_us': np.median(times_scalar) * 1000,
        'scalar_p99_us': np.percentile(times_scalar, 99) * 1000,
        'vec_mean_us': np.mean(times_vec) * 1000,
        'vec_p50_us': np.median(times_vec) * 1000,
        'vec_p99_us': np.percentile(times_vec, 99) * 1000,
        'n_bars': len(df),
        'n_runs': n_runs,
    }


def benchmark_signal_quality(df: pd.DataFrame, features_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Compare forward-return correlation of adaptive RSI vs fixed RSI signals.

    For RSI-based mean-reversion signals, a good RSI should produce negative
    correlation with forward returns (oversold → bounce, overbought → drop).
    """
    close = df['close'].values
    n = len(close)

    # Forward returns (1-bar, 5-bar, 10-bar)
    fwd_1 = np.full(n, np.nan)
    fwd_5 = np.full(n, np.nan)
    fwd_10 = np.full(n, np.nan)
    fwd_1[:-1] = close[1:] / close[:-1] - 1
    fwd_5[:-5] = close[5:] / close[:-5] - 1
    fwd_10[:-10] = close[10:] / close[:-10] - 1

    # Fixed RSI (period=14)
    fixed_rsi = compute_rsi_series(close, 14)

    # Adaptive RSI
    adaptive_periods = features_df['adaptive_rsi_period'].values if 'adaptive_rsi_period' in features_df.columns else np.full(n, 14)
    adaptive_rsi = compute_adaptive_rsi(close, adaptive_periods)

    # RSI deviation from 50 (signal strength)
    fixed_signal = fixed_rsi - 50.0
    adaptive_signal = adaptive_rsi - 50.0

    # Correlation with forward returns (RSI deviation → fwd return)
    valid = ~(np.isnan(fwd_5) | np.isnan(fixed_signal))
    valid_idx = np.where(valid)[0]

    if len(valid_idx) < 50:
        return {'error': 'Insufficient data for correlation'}

    fixed_corr_1 = np.corrcoef(fixed_signal[~np.isnan(fwd_1)], fwd_1[~np.isnan(fwd_1)])[0, 1]
    fixed_corr_5 = np.corrcoef(fixed_signal[valid], fwd_5[valid])[0, 1]
    fixed_corr_10 = np.corrcoef(fixed_signal[~np.isnan(fwd_10)], fwd_10[~np.isnan(fwd_10)])[0, 1]

    adaptive_corr_1 = np.corrcoef(adaptive_signal[~np.isnan(fwd_1)], fwd_1[~np.isnan(fwd_1)])[0, 1]
    adaptive_corr_5 = np.corrcoef(adaptive_signal[valid], fwd_5[valid])[0, 1]
    adaptive_corr_10 = np.corrcoef(adaptive_signal[~np.isnan(fwd_10)], fwd_10[~np.isnan(fwd_10)])[0, 1]

    return {
        'fixed_rsi14_fwd1_corr': fixed_corr_1,
        'fixed_rsi14_fwd5_corr': fixed_corr_5,
        'fixed_rsi14_fwd10_corr': fixed_corr_10,
        'adaptive_rsi_fwd1_corr': adaptive_corr_1,
        'adaptive_rsi_fwd5_corr': adaptive_corr_5,
        'adaptive_rsi_fwd10_corr': adaptive_corr_10,
        'delta_fwd1': adaptive_corr_1 - fixed_corr_1,
        'delta_fwd5': adaptive_corr_5 - fixed_corr_5,
        'delta_fwd10': adaptive_corr_10 - fixed_corr_10,
    }


def benchmark_regime_alignment(features_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Check how adaptive periods align with regime type.

    Expectation:
      - TRENDING  → longer periods (scale > 1.0)
      - MEAN_REVERTING → shorter periods (scale < 1.0)
      - VOLATILE → longer periods (wider BB)
      - RANDOM_WALK → neutral (~1.0)
    """
    if 'adaptive_scale' not in features_df.columns or 'regime' not in features_df.columns:
        return {'error': 'Missing adaptive_scale or regime columns'}

    regime_stats = {}
    for regime in ['CLEAN_TREND', 'VOLATILE_TREND', 'QUIET_MR', 'CHOPPY']:
        mask = features_df['regime'] == regime
        count = mask.sum()
        if count > 0:
            scales = features_df.loc[mask, 'adaptive_scale']
            regime_stats[regime] = {
                'count': int(count),
                'pct': float(count / len(features_df) * 100),
                'scale_mean': float(scales.mean()),
                'scale_std': float(scales.std()),
                'scale_min': float(scales.min()),
                'scale_max': float(scales.max()),
                'rsi_period_mean': float(features_df.loc[mask, 'adaptive_rsi_period'].mean()),
                'bb_period_mean': float(features_df.loc[mask, 'adaptive_bb_period'].mean()),
            }

    # Alignment score: CLEAN_TREND scale > QUIET_MR scale > CHOPPY scale
    trending_scale = regime_stats.get('CLEAN_TREND', {}).get('scale_mean', 1.0)
    mr_scale = regime_stats.get('CHOPPY', {}).get('scale_mean', 1.0)
    rw_scale = regime_stats.get('QUIET_MR', {}).get('scale_mean', 1.0)

    order_correct = (trending_scale > rw_scale) and (rw_scale > mr_scale)

    return {
        'regime_stats': regime_stats,
        'trending_scale': trending_scale,
        'mr_scale': mr_scale,
        'rw_scale': rw_scale,
        'order_correct': order_correct,
    }


def benchmark_period_stability(features_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Measure flip-flop rate of adaptive periods.

    A good adaptive system should change smoothly — not jump wildly bar to bar.
    """
    if 'adaptive_rsi_period' not in features_df.columns:
        return {'error': 'Missing adaptive_rsi_period column'}

    rsi_periods = features_df['adaptive_rsi_period'].values.astype(float)
    n = len(rsi_periods)

    # Bar-to-bar change
    diffs = np.abs(np.diff(rsi_periods))
    pct_changes = diffs / np.maximum(rsi_periods[:-1], 1.0)

    # Flip-flop: bars where period changes by >30%
    large_jumps = np.sum(pct_changes > 0.30)
    flip_flop_rate = large_jumps / max(n - 1, 1) * 100.0

    # Smoothness: autocorrelation of periods
    if n > 2:
        autocorr = np.corrcoef(rsi_periods[:-1], rsi_periods[1:])[0, 1]
    else:
        autocorr = 0.0

    return {
        'mean_abs_change': float(diffs.mean()),
        'mean_pct_change': float(pct_changes.mean() * 100),
        'flip_flop_rate_pct': float(flip_flop_rate),
        'large_jumps_count': int(large_jumps),
        'autocorrelation': float(autocorr),
        'period_std': float(np.std(rsi_periods)),
        'period_range': (int(rsi_periods.min()), int(rsi_periods.max())),
    }


def benchmark_strategy_utility(df: pd.DataFrame, features_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Simple RSI mean-reversion strategy comparison: adaptive vs fixed.

    Strategy: Buy when RSI < 30, sell when RSI > 70. Hold until opposite signal.
    Compares cumulative return, Sharpe, max drawdown.
    """
    close = df['close'].values
    n = len(close)

    # Fixed RSI-14
    fixed_rsi = compute_rsi_series(close, 14)

    # Adaptive RSI
    adaptive_periods = features_df['adaptive_rsi_period'].values if 'adaptive_rsi_period' in features_df.columns else np.full(n, 14)
    adaptive_rsi = compute_adaptive_rsi(close, adaptive_periods)

    def simulate_rsi_strategy(rsi: np.ndarray) -> Dict[str, float]:
        position = 0  # +1 long, -1 short, 0 flat
        returns_arr = []
        daily_ret = np.diff(close) / close[:-1]

        for i in range(1, n):
            if rsi[i - 1] < 30 and position <= 0:
                position = 1
            elif rsi[i - 1] > 70 and position >= 0:
                position = -1

            returns_arr.append(position * daily_ret[i - 1])

        rets = np.array(returns_arr)
        cum_ret = float(np.exp(np.sum(np.log1p(rets))) - 1)

        # Sharpe (annualized, hourly data → 8760 hours/year)
        if rets.std() > 0:
            sharpe = float(rets.mean() / rets.std() * np.sqrt(8760))
        else:
            sharpe = 0.0

        # Max drawdown
        equity = np.cumprod(1 + rets)
        running_max = np.maximum.accumulate(equity)
        dd = (equity - running_max) / running_max
        max_dd = float(dd.min())

        # Win rate
        wins = np.sum(rets > 0)
        total = np.sum(rets != 0)
        win_rate = float(wins / total * 100) if total > 0 else 0.0

        return {
            'cumulative_return': cum_ret,
            'sharpe': sharpe,
            'max_drawdown': max_dd,
            'win_rate': win_rate,
            'n_trades': int(total),
        }

    fixed_result = simulate_rsi_strategy(fixed_rsi)
    adaptive_result = simulate_rsi_strategy(adaptive_rsi)

    return {
        'fixed': fixed_result,
        'adaptive': adaptive_result,
        'delta_sharpe': adaptive_result['sharpe'] - fixed_result['sharpe'],
        'delta_cumret': adaptive_result['cumulative_return'] - fixed_result['cumulative_return'],
        'delta_maxdd': adaptive_result['max_drawdown'] - fixed_result['max_drawdown'],
    }


# ---------------------------------------------------------------------------
# F. Hilbert Confidence Distribution
# ---------------------------------------------------------------------------

def benchmark_hilbert_distribution(features_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Analyse the Hilbert confidence tier distribution across the dataset.

    Tiers:
      Level 1 (HILBERT_HIGH):  confidence >= 0.70 → direct cycle use
      Level 2 (HILBERT_BLEND): 0.40 <= confidence < 0.70 → blended
      Level 3 (REGIME_FALLBACK): confidence < 0.40 → pure regime fallback
    """
    n = len(features_df)

    # Check if Hilbert columns are present in the pipeline output
    has_hilbert = 'hilbert_confidence' in features_df.columns
    has_period = 'hilbert_period' in features_df.columns

    if has_hilbert:
        conf = features_df['hilbert_confidence'].values
    else:
        # If no hilbert_confidence column, everything is Level 3
        conf = np.zeros(n)

    # Tier thresholds (must match AggregatorConfig defaults)
    HIGH_THRESH = 0.70
    LOW_THRESH = 0.40

    level1_mask = conf >= HIGH_THRESH
    level2_mask = (~level1_mask) & (conf >= LOW_THRESH)
    level3_mask = conf < LOW_THRESH

    level1_cnt = int(level1_mask.sum())
    level2_cnt = int(level2_mask.sum())
    level3_cnt = int(level3_mask.sum())

    result: Dict[str, Any] = {
        'hilbert_column_present': has_hilbert,
        'hilbert_period_present': has_period,
        'total_bars': n,
        'level1_count': level1_cnt,
        'level1_pct': level1_cnt / n * 100,
        'level2_count': level2_cnt,
        'level2_pct': level2_cnt / n * 100,
        'level3_count': level3_cnt,
        'level3_pct': level3_cnt / n * 100,
    }

    if has_hilbert:
        result['conf_mean'] = float(np.mean(conf))
        result['conf_median'] = float(np.median(conf))
        result['conf_std'] = float(np.std(conf))
        result['conf_min'] = float(np.min(conf))
        result['conf_max'] = float(np.max(conf))
    else:
        result['conf_mean'] = 0.0
        result['conf_median'] = 0.0

    # Per-level adaptive scale stats
    if 'adaptive_scale' in features_df.columns:
        for mask, label in [(level1_mask, 'level1'), (level2_mask, 'level2'), (level3_mask, 'level3')]:
            if mask.sum() > 0:
                scales = features_df.loc[mask, 'adaptive_scale'].values
                result[f'{label}_scale_mean'] = float(np.mean(scales))
                result[f'{label}_scale_std'] = float(np.std(scales))
            else:
                result[f'{label}_scale_mean'] = None
                result[f'{label}_scale_std'] = None

    return result


# ---------------------------------------------------------------------------
# G. BB Strategy Utility
# ---------------------------------------------------------------------------

def compute_bollinger_bands(close: np.ndarray, period: int, num_std: float = 2.0
                            ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute Bollinger Bands (middle, upper, lower)."""
    n = len(close)
    middle = np.full(n, np.nan)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)

    for i in range(period - 1, n):
        window = close[i - period + 1:i + 1]
        m = window.mean()
        s = window.std(ddof=0)
        middle[i] = m
        upper[i] = m + num_std * s
        lower[i] = m - num_std * s

    return middle, upper, lower


def compute_adaptive_bollinger(close: np.ndarray, periods: np.ndarray,
                                stddevs: np.ndarray
                                ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute Bollinger Bands with per-bar adaptive period and stddev."""
    n = len(close)
    middle = np.full(n, np.nan)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)

    for i in range(20, n):
        p = int(periods[i])
        p = max(5, min(p, i))
        window = close[i - p + 1:i + 1]
        m = window.mean()
        s = window.std(ddof=0)
        ns = stddevs[i]
        middle[i] = m
        upper[i] = m + ns * s
        lower[i] = m - ns * s

    return middle, upper, lower


def benchmark_bb_strategy(df: pd.DataFrame, features_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Bollinger Band touch mean-reversion strategy: adaptive vs fixed.

    Strategy: Buy when close touches lower band, sell on upper band touch.
    """
    close = df['close'].values
    n = len(close)

    # Fixed BB (20, 2.0)
    _, f_upper, f_lower = compute_bollinger_bands(close, 20, 2.0)

    # Adaptive BB
    a_periods = features_df['adaptive_bb_period'].values if 'adaptive_bb_period' in features_df.columns else np.full(n, 20)
    a_stddevs = features_df['adaptive_bb_stddev'].values if 'adaptive_bb_stddev' in features_df.columns else np.full(n, 2.0)
    _, a_upper, a_lower = compute_adaptive_bollinger(close, a_periods, a_stddevs)

    def simulate_bb_strategy(upper: np.ndarray, lower: np.ndarray) -> Dict[str, float]:
        position = 0
        returns_arr = []
        daily_ret = np.diff(close) / close[:-1]
        n_entries = 0

        for i in range(1, n):
            if not np.isnan(lower[i - 1]) and close[i - 1] <= lower[i - 1] and position <= 0:
                position = 1
                n_entries += 1
            elif not np.isnan(upper[i - 1]) and close[i - 1] >= upper[i - 1] and position >= 0:
                position = -1
                n_entries += 1
            returns_arr.append(position * daily_ret[i - 1])

        rets = np.array(returns_arr)
        if len(rets) == 0:
            return {'cumulative_return': 0.0, 'sharpe': 0.0, 'max_drawdown': 0.0, 'win_rate': 0.0, 'n_trades': 0}

        cum_ret = float(np.exp(np.sum(np.log1p(rets))) - 1)
        sharpe = float(rets.mean() / rets.std() * np.sqrt(8760)) if rets.std() > 0 else 0.0
        equity = np.cumprod(1 + rets)
        running_max = np.maximum.accumulate(equity)
        dd = (equity - running_max) / running_max
        max_dd = float(dd.min())
        wins = np.sum(rets > 0)
        total = np.sum(rets != 0)
        win_rate = float(wins / total * 100) if total > 0 else 0.0
        return {'cumulative_return': cum_ret, 'sharpe': sharpe, 'max_drawdown': max_dd,
                'win_rate': win_rate, 'n_trades': n_entries}

    fixed_result = simulate_bb_strategy(f_upper, f_lower)
    adaptive_result = simulate_bb_strategy(a_upper, a_lower)

    return {
        'fixed': fixed_result,
        'adaptive': adaptive_result,
        'delta_sharpe': adaptive_result['sharpe'] - fixed_result['sharpe'],
        'delta_cumret': adaptive_result['cumulative_return'] - fixed_result['cumulative_return'],
        'delta_maxdd': adaptive_result['max_drawdown'] - fixed_result['max_drawdown'],
    }


# ---------------------------------------------------------------------------
# Report Printing
# ---------------------------------------------------------------------------

def print_report(perf: Dict, quality: Dict, alignment: Dict, stability: Dict,
                 utility: Dict, hilbert: Dict = None, bb_utility: Dict = None,
                 label: str = ""):
    """Print a formatted benchmark report."""
    sep = "=" * 72

    header = "        ADAPTIVE PERIOD LENGTHS — BENCHMARK REPORT"
    if label:
        header += f"  [{label}]"

    print(f"\n{sep}")
    print(header)
    print(sep)

    # A. Performance
    print("\n┌─ A. COMPUTATION PERFORMANCE ─────────────────────────────────────┐")
    print(f"│  Bars: {perf['n_bars']}   Runs: {perf['n_runs']}")
    print(f"│  Scalar path:  mean={perf['scalar_mean_us']:.1f}µs  "
          f"p50={perf['scalar_p50_us']:.1f}µs  p99={perf['scalar_p99_us']:.1f}µs")
    print(f"│  Vector path:  mean={perf['vec_mean_us']:.1f}µs  "
          f"p50={perf['vec_p50_us']:.1f}µs  p99={perf['vec_p99_us']:.1f}µs")
    print("└──────────────────────────────────────────────────────────────────┘")

    # B. Signal Quality
    print("\n┌─ B. SIGNAL QUALITY (RSI → Forward Return Correlation) ─────────┐")
    print(f"│  {'Horizon':<12} {'Fixed RSI-14':>14} {'Adaptive RSI':>14} {'Delta':>10}")
    print(f"│  {'─'*12} {'─'*14} {'─'*14} {'─'*10}")
    for h in [1, 5, 10]:
        fk = f'fixed_rsi14_fwd{h}_corr'
        ak = f'adaptive_rsi_fwd{h}_corr'
        dk = f'delta_fwd{h}'
        if fk in quality:
            f_val = quality[fk]
            a_val = quality[ak]
            d_val = quality[dk]
            marker = "✓" if abs(a_val) > abs(f_val) else " "
            print(f"│  {f'Fwd-{h} bar':<12} {f_val:>14.6f} {a_val:>14.6f} {d_val:>+10.6f} {marker}")
    print("│  (More negative = better mean-reversion signal)")
    print("└──────────────────────────────────────────────────────────────────┘")

    # C. Regime Alignment
    print("\n┌─ C. REGIME ALIGNMENT ────────────────────────────────────────────┐")
    if 'regime_stats' in alignment:
        print(f"│  {'Regime':<16} {'Count':>6} {'Pct':>6} {'Scale':>7} {'RSI':>5} {'BB':>5}")
        print(f"│  {'─'*16} {'─'*6} {'─'*6} {'─'*7} {'─'*5} {'─'*5}")
        for regime, stats in alignment['regime_stats'].items():
            print(f"│  {regime:<16} {stats['count']:>6} {stats['pct']:>5.1f}% "
                  f"{stats['scale_mean']:>7.3f} {stats['rsi_period_mean']:>5.1f} {stats['bb_period_mean']:>5.1f}")
        order_mark = "✓" if alignment['order_correct'] else "✗"
        print(f"│  Order check (CLEAN_TREND > QUIET_MR > CHOPPY): {order_mark}")
    print("└──────────────────────────────────────────────────────────────────┘")

    # D. Period Stability
    print("\n┌─ D. PERIOD STABILITY ────────────────────────────────────────────┐")
    print(f"│  Mean absolute change:   {stability['mean_abs_change']:.2f} bars")
    print(f"│  Mean percent change:    {stability['mean_pct_change']:.1f}%")
    print(f"│  Flip-flop rate (>30%):  {stability['flip_flop_rate_pct']:.1f}% ({stability['large_jumps_count']} jumps)")
    print(f"│  Autocorrelation:        {stability['autocorrelation']:.4f}")
    print(f"│  Period range:           {stability['period_range'][0]}–{stability['period_range'][1]}")
    stable = stability['flip_flop_rate_pct'] < 5.0 and stability['autocorrelation'] > 0.9
    print(f"│  Assessment:             {'STABLE ✓' if stable else 'NEEDS TUNING ⚠'}")
    print("└──────────────────────────────────────────────────────────────────┘")

    # E. Strategy Utility (RSI)
    print("\n┌─ E. STRATEGY UTILITY — RSI 30/70 Mean-Reversion ─────────────────┐")
    _print_strategy_section(utility)

    # F. Hilbert Confidence Distribution
    if hilbert:
        print("\n┌─ F. HILBERT CONFIDENCE DISTRIBUTION ─────────────────────────────┐")
        print(f"│  Hilbert column in pipeline: {'YES' if hilbert['hilbert_column_present'] else 'NO (all Level 3)'}")
        print(f"│")
        print(f"│  {'Tier':<24} {'Count':>7} {'Pct':>7}   Scale")
        print(f"│  {'─'*24} {'─'*7} {'─'*7}   {'─'*12}")
        for lvl, name, thresh in [(1, 'Level 1 (HILBERT_HIGH)', '≥ 0.70'),
                                   (2, 'Level 2 (HILBERT_BLEND)', '0.40–0.70'),
                                   (3, 'Level 3 (REGIME_FALLBACK)', '< 0.40')]:
            cnt = hilbert[f'level{lvl}_count']
            pct = hilbert[f'level{lvl}_pct']
            sc = hilbert.get(f'level{lvl}_scale_mean')
            sc_str = f"{sc:.3f}" if sc is not None else "N/A"
            print(f"│  {name:<24} {cnt:>7} {pct:>6.1f}%   {sc_str}")
        print(f"│")
        if hilbert['hilbert_column_present']:
            print(f"│  Confidence stats:  mean={hilbert['conf_mean']:.3f}  "
                  f"median={hilbert['conf_median']:.3f}  std={hilbert['conf_std']:.3f}  "
                  f"range=[{hilbert['conf_min']:.3f}, {hilbert['conf_max']:.3f}]")
        else:
            print(f"│  Note: No upstream Hilbert component populates hilbert_confidence")
            print(f"│        in RegimeState.metadata yet — adaptive lengths are purely")
            print(f"│        regime-driven (Level 3). Levels 1-2 activate once Hilbert")
            print(f"│        data is wired into the pipeline.")
        print("└──────────────────────────────────────────────────────────────────┘")

    # G. Strategy Utility (BB)
    if bb_utility:
        print("\n┌─ G. STRATEGY UTILITY — BB Touch Mean-Reversion ──────────────────┐")
        _print_strategy_section(bb_utility, fixed_label="Fixed BB(20,2)", adaptive_label="Adaptive BB")

    print(f"\n{sep}\n")


def _print_strategy_section(utility: Dict, fixed_label: str = "Fixed RSI-14",
                            adaptive_label: str = "Adaptive RSI"):
    """Shared printer for strategy utility sections."""
    print(f"│  {'Metric':<22} {fixed_label:>14} {adaptive_label:>14} {'Delta':>10}")
    print(f"│  {'─'*22} {'─'*14} {'─'*14} {'─'*10}")
    for metric, label in [('cumulative_return', 'Cumulative Return'),
                          ('sharpe', 'Sharpe Ratio'),
                          ('max_drawdown', 'Max Drawdown'),
                          ('win_rate', 'Win Rate %')]:
        f_val = utility['fixed'][metric]
        a_val = utility['adaptive'][metric]
        d_val = a_val - f_val
        fmt = '.2%' if metric in ('cumulative_return', 'max_drawdown') else '.3f' if metric == 'sharpe' else '.1f'
        print(f"│  {label:<22} {f_val:>14{fmt}} {a_val:>14{fmt}} {d_val:>+10{fmt}}")
    better = utility['delta_sharpe'] > 0
    print(f"│  Verdict:               {'ADAPTIVE WINS ✓' if better else 'FIXED WINS'}")
    print("└──────────────────────────────────────────────────────────────────┘")


def print_cross_asset_summary(results: Dict[str, Dict]):
    """Print a compact comparison table across multiple assets/timeframes."""
    sep = "=" * 96
    print(f"\n{sep}")
    print("        CROSS-ASSET / CROSS-TIMEFRAME SUMMARY")
    print(sep)

    # Header
    print(f"\n{'Asset':<18} {'Bars':>6} {'RSI Sharpe Δ':>13} {'BB Sharpe Δ':>12} "
          f"{'CumRet Δ RSI':>13} {'CumRet Δ BB':>12} {'Stability':>10} {'Order':>6}")
    print(f"{'─'*18} {'─'*6} {'─'*13} {'─'*12} {'─'*13} {'─'*12} {'─'*10} {'─'*6}")

    for label, data in results.items():
        bars = data.get('bars', 0)
        rsi_d = data.get('rsi_delta_sharpe', 0.0)
        bb_d = data.get('bb_delta_sharpe', 0.0)
        rsi_cr = data.get('rsi_delta_cumret', 0.0)
        bb_cr = data.get('bb_delta_cumret', 0.0)
        stable = data.get('stable', False)
        order = data.get('order_correct', False)
        stable_str = "STABLE ✓" if stable else "⚠"
        order_str = "✓" if order else "✗"
        print(f"{label:<18} {bars:>6} {rsi_d:>+13.3f} {bb_d:>+12.3f} "
              f"{rsi_cr:>+13.2%} {bb_cr:>+12.2%} {stable_str:>10} {order_str:>6}")

    print(f"\n{sep}\n")


# ---------------------------------------------------------------------------
# Runner helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Asset-class profiles loaded from config
# ---------------------------------------------------------------------------

def load_asset_profile(profile_name: str) -> Dict[str, Any]:
    """Load an asset-class profile from aggregator.yaml."""
    try:
        cfg = load_yaml_config(Path(__file__).resolve().parents[1] / "config" / "aggregator.yaml")
    except (FileNotFoundError, OSError):
        return {}
    profiles = cfg.get('asset_class_profiles', {})
    return profiles.get(profile_name, {})


def load_timeframe_profile(timeframe: str) -> Dict[str, Any]:
    """Load a timeframe BB stddev multiplier from aggregator.yaml."""
    try:
        cfg = load_yaml_config(Path(__file__).resolve().parents[1] / "config" / "aggregator.yaml")
    except (FileNotFoundError, OSError):
        return {}
    profiles = cfg.get('timeframe_profiles', {})
    return profiles.get(timeframe, {})


# Map symbols to their asset-class profile
SYMBOL_PROFILES: Dict[str, str] = {
    "SUIUSDT": "high_vol_alt",
    "DOGEUSDT": "high_vol_alt",
    "PEPEUSDT": "high_vol_alt",
    "SHIBUSDT": "high_vol_alt",
    "ETHUSDT": "major_alt",
    # All others default to major_crypto (no override needed)
}


def run_full_benchmark(df: pd.DataFrame, perf_runs: int, label: str = "",
                       asset: str = "BTCUSDT", timeframe: str = "1h") -> Dict[str, Any]:
    """Run all benchmarks on a single dataset. Returns all results in a dict."""
    logger.info(f"Data: {len(df)} bars from {df.index[0]} to {df.index[-1]}")

    logger.info("Running regime pipeline (series)...")
    orchestrator = RegimeOrchestrator.create(asset, timeframe)
    features_df = orchestrator.analyze_series(df)
    logger.info(f"Pipeline output: {features_df.shape[1]} columns, {len(features_df)} rows")

    logger.info("Running computation performance benchmark...")
    perf = benchmark_computation_performance(df, n_runs=perf_runs)

    logger.info("Running signal quality benchmark...")
    quality = benchmark_signal_quality(df, features_df)

    logger.info("Running regime alignment benchmark...")
    alignment = benchmark_regime_alignment(features_df)

    logger.info("Running period stability benchmark...")
    stability = benchmark_period_stability(features_df)

    logger.info("Running RSI strategy utility benchmark...")
    utility = benchmark_strategy_utility(df, features_df)

    logger.info("Running Hilbert confidence distribution...")
    hilbert = benchmark_hilbert_distribution(features_df)

    logger.info("Running BB strategy utility benchmark...")
    bb_utility = benchmark_bb_strategy(df, features_df)

    print_report(perf, quality, alignment, stability, utility,
                 hilbert=hilbert, bb_utility=bb_utility, label=label)

    # Return summary for cross-asset table
    stable = stability['flip_flop_rate_pct'] < 5.0 and stability['autocorrelation'] > 0.9
    return {
        'bars': len(df),
        'rsi_delta_sharpe': utility['delta_sharpe'],
        'rsi_delta_cumret': utility['delta_cumret'],
        'bb_delta_sharpe': bb_utility['delta_sharpe'],
        'bb_delta_cumret': bb_utility['delta_cumret'],
        'stable': stable,
        'order_correct': alignment.get('order_correct', False),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Benchmark Adaptive Period Lengths")
    parser.add_argument("--mode", choices=["synthetic", "live", "cross-asset"], default="synthetic",
                        help="Data source: synthetic | live (single) | cross-asset (multi)")
    parser.add_argument("--bars", type=int, default=2000, help="Number of bars for synthetic mode")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="Symbol for live mode")
    parser.add_argument("--timeframe", type=str, default="1h", help="Timeframe for live mode")
    parser.add_argument("--start", type=str, default="2024-01-01", help="Start date for live mode")
    parser.add_argument("--end", type=str, default="2025-01-01", help="End date for live mode")
    parser.add_argument("--perf-runs", type=int, default=50, help="Number of timing runs")
    args = parser.parse_args()

    if args.mode == "synthetic":
        logger.info(f"Generating {args.bars}-bar synthetic multi-regime data...")
        df = generate_synthetic_data(n_bars=args.bars)
        run_full_benchmark(df, args.perf_runs, label="SYNTHETIC", asset="BTCUSDT", timeframe="1h")

    elif args.mode == "live":
        logger.info(f"Fetching live data: {args.symbol} {args.timeframe} {args.start}→{args.end}")
        df = fetch_live_data(args.symbol, args.timeframe, args.start, args.end)
        run_full_benchmark(df, args.perf_runs, label=f"{args.symbol} {args.timeframe}",
                           asset=args.symbol, timeframe=args.timeframe)

    elif args.mode == "cross-asset":
        # Define test matrix
        test_matrix = [
            # (symbol, timeframe, start, end, label)
            ("BTCUSDT", "1h", "2025-03-06", "2026-03-06", "BTCUSDT 1h"),
            ("ETHUSDT", "1h", "2025-03-06", "2026-03-06", "ETHUSDT 1h"),
            ("SUIUSDT", "1h", "2025-03-06", "2026-03-06", "SUIUSDT 1h"),
            ("BTCUSDT", "30m", "2025-09-06", "2026-03-06", "BTCUSDT 30m (6mo)"),
            ("BTCUSDT", "4h", "2025-03-06", "2026-03-06", "BTCUSDT 4h"),
        ]

        cross_results = {}
        for symbol, tf, start, end, label in test_matrix:
            logger.info(f"\n{'='*72}")
            logger.info(f"Fetching {label}: {symbol} {tf} {start}→{end}")
            try:
                df = fetch_live_data(symbol, tf, start, end)
                summary = run_full_benchmark(df, args.perf_runs, label=label,
                                             asset=symbol, timeframe=tf)
                cross_results[label] = summary
            except Exception as e:
                logger.error(f"Failed {label}: {e}")
                cross_results[label] = {
                    'bars': 0, 'rsi_delta_sharpe': 0, 'rsi_delta_cumret': 0,
                    'bb_delta_sharpe': 0, 'bb_delta_cumret': 0,
                    'stable': False, 'order_correct': False,
                }

        print_cross_asset_summary(cross_results)


if __name__ == "__main__":
    main()
