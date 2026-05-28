"""MeanReversion v7-style per-asset optimization across 5 assets.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/mr_optimization_v7.py

Runs 200 Optuna trials per asset with 180-day data, train/test/val split,
and reports per-asset optimal params + metrics.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Ensure src/ is on sys.path
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

import numpy as np
import optuna
import pandas as pd

# Suppress Optuna trial-by-trial logging
optuna.logging.set_verbosity(optuna.logging.WARNING)

from libs.optim_utils.data_fetcher import fetch_historical_ohlcv
from libs.optim_utils.scoring_feature_pipeline import build_scoring_feature_df
from libs.optim_utils.scoring import (
    compute_max_drawdown,
    compute_returns,
    compute_sharpe,
    compute_win_rate,
    split_temporal,
)

# Trigger model registration
import libs.models  # noqa: F401

from libs.models.registry import ModelRegistry
from libs.models.mean_reversion.optimization.optimizer import (
    MODEL_NAME,
    STUDY_DEFAULTS,
    make_objective,
    post_process_params,
)

# ── Configuration ──────────────────────────────────────────────────────

ASSETS = ["BTCUSDT", "XRPUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"]
TIMEFRAME = "1h"
N_TRIALS = 200
DAYS = 180
COST_BPS = 10.0
TRAIN_RATIO = 0.6
TEST_RATIO = 0.2
VAL_RATIO = 0.2


def _evaluate_params(
    params: dict,
    feature_df: pd.DataFrame,
    label: str,
) -> dict:
    """Evaluate params on a dataset, return metrics dict."""
    model_cls = ModelRegistry.get(MODEL_NAME)
    model = model_cls(params)
    directions = model.batch_evaluate(feature_df)
    close = feature_df["close"].values
    returns, trade_mask = compute_returns(directions.values, close, COST_BPS)
    sharpe = compute_sharpe(returns, TIMEFRAME)
    max_dd = compute_max_drawdown(returns)
    win_rate = compute_win_rate(returns, trade_mask)
    n_trades = int(np.sum(trade_mask))
    return {
        "label": label,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "win_rate": win_rate,
        "n_trades": n_trades,
        "n_bars": len(feature_df),
    }


def run_asset(asset: str) -> dict:
    """Run full optimization for one asset."""
    print(f"\n{'='*70}")
    print(f"  {asset} — {DAYS}d data, {N_TRIALS} trials")
    print(f"{'='*70}")

    # Fetch OHLCV
    since_ms = int((time.time() - DAYS * 86400) * 1000)
    print(f"  Fetching {DAYS}d of {TIMEFRAME} candles...")
    ohlcv_df = fetch_historical_ohlcv(
        symbol=asset, timeframe=TIMEFRAME, since=since_ms, limit=DAYS * 24,
    )
    print(f"  Fetched {len(ohlcv_df)} candles")

    if len(ohlcv_df) < 200:
        print(f"  ⚠ Insufficient data ({len(ohlcv_df)} < 200), skipping")
        return {"asset": asset, "status": "SKIP", "reason": "insufficient data"}

    # Build feature DataFrame
    print("  Computing indicators...")
    feature_df = build_scoring_feature_df(ohlcv_df, asset, TIMEFRAME)
    print(f"  Feature DataFrame: {len(feature_df)} rows, {len(feature_df.columns)} cols")

    # Split
    train_df, test_df, val_df = split_temporal(
        feature_df, train=TRAIN_RATIO, test=TEST_RATIO, val=VAL_RATIO,
    )
    print(f"  Split: train={len(train_df)}, test={len(test_df)}, val={len(val_df)}")

    # Run Optuna on train set
    print(f"  Running {N_TRIALS} Optuna trials on train set...")
    t0 = time.time()
    objective_fn = make_objective(train_df, timeframe=TIMEFRAME, cost_bps=COST_BPS)

    study = optuna.create_study(
        direction=STUDY_DEFAULTS.get("direction", "maximize"),
        sampler=optuna.samplers.TPESampler(seed=42),
    )
    study.optimize(objective_fn, n_trials=N_TRIALS, show_progress_bar=False)
    elapsed = time.time() - t0

    best_params = post_process_params(study.best_params)
    print(f"  Best trial #{study.best_trial.number}: score={study.best_value:.4f} ({elapsed:.1f}s)")
    print(f"  Params: {best_params}")

    # Default params for comparison
    model_cls = ModelRegistry.get(MODEL_NAME)
    default_params = {k: v.default for k, v in model_cls.meta.hyperparameter_schema.items()}

    # Evaluate on all splits
    results = {
        "asset": asset,
        "status": "OK",
        "best_params": best_params,
        "best_score": study.best_value,
        "elapsed_s": elapsed,
    }

    for label, df in [("train", train_df), ("test", test_df), ("val", val_df), ("full", feature_df)]:
        opt_metrics = _evaluate_params(best_params, df, f"{label}_optimized")
        def_metrics = _evaluate_params(default_params, df, f"{label}_defaults")
        results[f"{label}_opt"] = opt_metrics
        results[f"{label}_def"] = def_metrics

    # Print comparison table
    print(f"\n  {'Split':<10} {'Metric':<12} {'Defaults':>10} {'Optimized':>10} {'Delta':>10}")
    print(f"  {'-'*52}")
    for split in ["train", "test", "val", "full"]:
        opt = results[f"{split}_opt"]
        dflt = results[f"{split}_def"]
        for metric in ["sharpe", "max_dd", "win_rate", "n_trades"]:
            o = opt[metric]
            d = dflt[metric]
            delta = o - d
            if metric == "n_trades":
                print(f"  {split:<10} {metric:<12} {d:>10d} {o:>10d} {delta:>+10d}")
            else:
                print(f"  {split:<10} {metric:<12} {d:>10.4f} {o:>10.4f} {delta:>+10.4f}")
        print()

    # Overfit check: full-sample vs val gap
    full_sharpe = results["full_opt"]["sharpe"]
    val_sharpe = results["val_opt"]["sharpe"]
    gap = abs(full_sharpe - val_sharpe)
    overfit = "OVERFIT ⚠" if gap > 1.0 else "CONSISTENT ✓"
    print(f"  Full vs Val Sharpe gap: {gap:.4f} → {overfit}")

    # Headroom check: optimized vs defaults on full sample
    full_def_sharpe = results["full_def"]["sharpe"]
    headroom = full_sharpe - full_def_sharpe
    has_headroom = "HEADROOM ✓" if headroom > 0.1 else "PLATEAU ⚠" if headroom > 0 else "DEGRADED ⚠"
    print(f"  Optimization headroom: {headroom:+.4f} → {has_headroom}")

    return results


def main() -> None:
    print("=" * 70)
    print("  MEANREVERSION v7 PER-ASSET OPTIMIZATION")
    print(f"  Assets: {', '.join(ASSETS)}")
    print(f"  Config: {N_TRIALS} trials, {DAYS}d data, {COST_BPS}bps cost")
    print("=" * 70)

    all_results = []
    for asset in ASSETS:
        result = run_asset(asset)
        all_results.append(result)

    # ── Summary ──
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print(f"\n  {'Asset':<12} {'Full Sharpe':>12} {'Val Sharpe':>12} {'Max DD':>10} {'Trades':>8} {'Status':>12}")
    print(f"  {'-'*66}")

    for r in all_results:
        if r["status"] != "OK":
            print(f"  {r['asset']:<12} {'SKIP':>12}")
            continue
        fs = r["full_opt"]["sharpe"]
        vs = r["val_opt"]["sharpe"]
        dd = r["full_opt"]["max_dd"]
        nt = r["full_opt"]["n_trades"]
        gap = abs(fs - vs)
        status = "✓" if gap < 1.0 else "⚠ overfit"
        print(f"  {r['asset']:<12} {fs:>+12.4f} {vs:>+12.4f} {dd:>10.4f} {nt:>8d} {status:>12}")

    print(f"\n  Per-asset optimized params:")
    for r in all_results:
        if r["status"] == "OK":
            p = r["best_params"]
            print(f"  {r['asset']}: {p}")

    print("\n" + "=" * 70)
    print("  Optimization complete")
    print("=" * 70)


if __name__ == "__main__":
    main()
