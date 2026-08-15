"""Batch single-exit SqueezeBreakout optimization across all 5 assets.

Runs per-asset scoring optimization using purged k-fold CV,
then audits proposed vs current params on the full dataset.
Outputs a comparison table for decision-making.

Usage:
    PYTHONPATH=src python scripts/batch_optimize.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import optuna
import pandas as pd
import yaml

# Ensure src/ on path
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

optuna.logging.set_verbosity(optuna.logging.WARNING)

from libs.models.scoring_registry import ScoringModelRegistry

from libs.contracts.schemas import StudyConfig
from libs.models.legacy_bootstrap import bootstrap_legacy_model_registries
from libs.models.registry import ModelRegistry
from libs.optim_utils.data_fetcher import fetch_historical_ohlcv
from libs.optim_utils.runner import OptunaRunner
from libs.optim_utils.scoring import (
    compute_max_drawdown,
    compute_returns,
    compute_sharpe,
    compute_signal_weighted_returns,
    compute_win_rate,
)
from libs.optim_utils.scoring_feature_pipeline import build_scoring_feature_df

bootstrap_legacy_model_registries()

from libs.models.squeeze_breakout.optimization import scoring_optimizer as sb_optimizer

# ---------- Configuration ----------
ASSETS = [
    ("BTCUSDT", "1h"),
    ("XRPUSDT", "1h"),
    ("SOLUSDT", "1h"),
    ("BNBUSDT", "30m"),
    ("DOGEUSDT", "4h"),
]

DAYS = 365
N_TRIALS = 200
COST_BPS = 10.0
SEED = 42


def load_current_params(asset: str, timeframe: str) -> dict | None:
    """Read current SqueezeBreakout params from models.yaml."""
    models_path = Path(__file__).resolve().parent.parent / "configs" / "models.yaml"
    with open(models_path, "r") as f:
        data = yaml.safe_load(f) or {}
    asset_cfg = data.get("models", {}).get("assets", {}).get(asset, {})
    tf_cfg = asset_cfg.get("timeframes", {}).get(timeframe, {})
    sb_cfg = tf_cfg.get("SqueezeBreakout", {})
    return sb_cfg.get("params")


def score_discrete(model, feature_df: pd.DataFrame, timeframe: str) -> dict[str, float]:
    """Score a model using discrete directions (matches production single-exit)."""
    directions = model.batch_evaluate(feature_df)
    close = feature_df["close"].values
    returns, trade_mask = compute_returns(directions.values, close, cost_bps=COST_BPS)
    n_trades = int(trade_mask.sum())
    return {
        "sharpe": compute_sharpe(returns, timeframe),
        "max_dd": compute_max_drawdown(returns),
        "win_rate": compute_win_rate(returns, trade_mask),
        "n_trades": n_trades,
        "total_return": float(np.sum(returns)),
    }


def run_asset(asset: str, timeframe: str) -> dict:
    """Run optimization for a single asset/timeframe."""
    print(f"\n{'='*60}")
    print(f"  {asset} / {timeframe}")
    print(f"{'='*60}")

    # Fetch data
    since_ms = int((time.time() - DAYS * 86400) * 1000)
    ohlcv_df = fetch_historical_ohlcv(symbol=asset, timeframe=timeframe, since=since_ms, limit=DAYS * 24)
    print(f"  Fetched {len(ohlcv_df)} candles")

    if len(ohlcv_df) < 200:
        print(f"  SKIP: insufficient data ({len(ohlcv_df)} < 200)")
        return {"asset": asset, "timeframe": timeframe, "status": "SKIP"}

    feature_df = build_scoring_feature_df(ohlcv_df, asset, timeframe)
    print(f"  Features: {len(feature_df)} rows × {len(feature_df.columns)} cols")

    # --- Score current params ---
    current_params = load_current_params(asset, timeframe)
    current_metrics = None
    if current_params:
        model_cls = ModelRegistry.get("SqueezeBreakout")
        current_model = model_cls(current_params)
        current_metrics = score_discrete(current_model, feature_df, timeframe)
        print(f"  Current Sharpe: {current_metrics['sharpe']:.4f}  DD: {current_metrics['max_dd']:.4f}  Trades: {current_metrics['n_trades']}")
    else:
        print(f"  No current params found")

    # --- Optimize ---
    objective_fn = sb_optimizer.make_objective(feature_df, timeframe=timeframe, cost_bps=COST_BPS)
    study_config = StudyConfig(
        model_name=sb_optimizer.MODEL_NAME, asset=asset, timeframe=timeframe,
        n_trials=N_TRIALS, sampler="TPE", pruner="MedianPruner",
        objectives=["score"], directions=["maximize"],
    )
    runner = OptunaRunner(study_config)
    # Seed the sampler for reproducibility
    runner._build_sampler = lambda: optuna.samplers.TPESampler(seed=SEED)
    results = runner.run(objective_fn=objective_fn)

    completed = [r for r in results if r.state == "COMPLETE"]
    if not completed:
        print(f"  FAIL: no completed trials")
        return {"asset": asset, "timeframe": timeframe, "status": "FAIL"}

    best = max(completed, key=lambda r: list(r.values.values())[0])
    proposed_params = sb_optimizer.post_process_params(best.params)
    cv_score = list(best.values.values())[0]
    print(f"  Best trial #{best.trial_number}: CV score={cv_score:.4f}")
    print(f"  Proposed params: {proposed_params}")

    # --- Score proposed params on full data (discrete, production-like) ---
    model_cls = ModelRegistry.get("SqueezeBreakout")
    proposed_model = model_cls(proposed_params)
    proposed_metrics = score_discrete(proposed_model, feature_df, timeframe)
    print(f"  Proposed Sharpe: {proposed_metrics['sharpe']:.4f}  DD: {proposed_metrics['max_dd']:.4f}  Trades: {proposed_metrics['n_trades']}")

    return {
        "asset": asset,
        "timeframe": timeframe,
        "status": "OK",
        "cv_score": cv_score,
        "current_params": current_params,
        "current_metrics": current_metrics,
        "proposed_params": proposed_params,
        "proposed_metrics": proposed_metrics,
    }


def main():
    print("Batch SqueezeBreakout Optimization — Single-Exit Scoring")
    print(f"Config: {N_TRIALS} trials, {DAYS}d data, {COST_BPS}bps cost, seed={SEED}")

    all_results = []
    for asset, tf in ASSETS:
        result = run_asset(asset, tf)
        all_results.append(result)

    # --- Summary table ---
    print(f"\n\n{'='*90}")
    print(f"  SUMMARY: Single-Exit Optimization Results")
    print(f"{'='*90}")
    print(f"{'Asset':<12} {'TF':<5} {'Cur Sharpe':>11} {'New Sharpe':>11} {'Delta':>8} {'Cur DD':>8} {'New DD':>8} {'CV Score':>9} {'Trades':>7}")
    print(f"{'-'*90}")

    for r in all_results:
        if r["status"] != "OK":
            print(f"{r['asset']:<12} {r['timeframe']:<5} {'—':>11} {'—':>11} {'—':>8} {'—':>8} {'—':>8} {'—':>9} {'—':>7}")
            continue
        cm = r["current_metrics"]
        pm = r["proposed_metrics"]
        cur_s = f"{cm['sharpe']:.4f}" if cm else "—"
        cur_dd = f"{cm['max_dd']:.4f}" if cm else "—"
        new_s = f"{pm['sharpe']:.4f}"
        new_dd = f"{pm['max_dd']:.4f}"
        delta = f"{pm['sharpe'] - (cm['sharpe'] if cm else 0):.4f}"
        cv = f"{r['cv_score']:.4f}"
        trades = f"{pm['n_trades']}"
        print(f"{r['asset']:<12} {r['timeframe']:<5} {cur_s:>11} {new_s:>11} {delta:>8} {cur_dd:>8} {new_dd:>8} {cv:>9} {trades:>7}")

    # --- v7 multi-TP comparison ---
    v7_sharpes = {"BTCUSDT": 0.19, "XRPUSDT": 1.49, "SOLUSDT": 1.26, "BNBUSDT": 3.01, "DOGEUSDT": 2.39}
    print(f"\n\n{'='*70}")
    print(f"  v7 Multi-TP vs Single-Exit Sharpe Comparison")
    print(f"{'='*70}")
    print(f"{'Asset':<12} {'v7 Multi-TP':>12} {'Single-Exit':>12} {'Retention':>10}")
    print(f"{'-'*48}")
    for r in all_results:
        if r["status"] != "OK":
            continue
        v7 = v7_sharpes.get(r["asset"], 0)
        se = r["proposed_metrics"]["sharpe"]
        retention = f"{se/v7*100:.0f}%" if v7 != 0 else "—"
        print(f"{r['asset']:<12} {v7:>12.2f} {se:>12.4f} {retention:>10}")

    print(f"\nRetention > 70% → single-exit is sufficient, skip multi-TP production changes")
    print(f"Retention < 50% → multi-TP adds real alpha, consider Option B")


if __name__ == "__main__":
    main()
