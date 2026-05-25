"""CLI runner for MeanReversion optimization.

Usage:
    PYTHONPATH=src python -m libs.models.mean_reversion.optimization.optimize \
        --asset BTCUSDT --timeframe 1h --n-trials 200 --audit --write-back
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure src/ is on sys.path when run as a script
_src = str(Path(__file__).resolve().parents[4])
if _src not in sys.path:
    sys.path.insert(0, _src)

import optuna

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import StudyConfig
from libs.optimization.data_fetcher import fetch_historical_ohlcv
from libs.optimization.param_auditor import ParamAuditor
from libs.optimization.param_writeback import read_current_params, write_best_params
from libs.optimization.runner import OptunaRunner

# Trigger model registration
import libs.models  # noqa: F401

# Import this model's optimizer module
from libs.models.mean_reversion.optimization import optimizer as mr_optimizer

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run MeanReversion optimization study"
    )
    parser.add_argument("--asset", required=True, help="Asset symbol (e.g., BTCUSDT)")
    parser.add_argument("--timeframe", required=True, help="Timeframe (e.g., 1h)")
    parser.add_argument("--n-trials", type=int, default=None)
    parser.add_argument("--since", type=int, default=None,
                        help="Start time in ms (Binance timestamp)")
    parser.add_argument("--days", type=int, default=90,
                        help="Number of days of historical data (default: 90)")
    parser.add_argument("--cost-bps", type=float, default=10.0,
                        help="Round-trip transaction cost in basis points")
    parser.add_argument("--train-ratio", type=float, default=0.6,
                        help="Train set ratio (default: 0.6)")
    parser.add_argument("--test-ratio", type=float, default=0.2,
                        help="Test set ratio (default: 0.2)")
    parser.add_argument("--val-ratio", type=float, default=0.2,
                        help="Validation set ratio for audit (default: 0.2)")
    parser.add_argument("--write-back", action="store_true",
                        help="Write best params to configs/optimized_params.yaml")
    parser.add_argument("--audit", action="store_true",
                        help="Compare new vs current params")
    parser.add_argument("--study-name", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # --- Fetch data from Binance ---
    import time
    since_ms = args.since
    if since_ms is None:
        since_ms = int((time.time() - args.days * 86400) * 1000)

    logger.info(f"Fetching {args.days}d of {args.timeframe} candles for {args.asset}")
    feature_df = fetch_historical_ohlcv(
        symbol=args.asset,
        timeframe=args.timeframe,
        since=since_ms,
        limit=args.days * 24,  # rough upper bound for 1h candles
    )
    logger.info(f"Fetched {len(feature_df)} candles")

    if len(feature_df) < 50:
        logger.warning("Insufficient data for optimization — need at least 50 candles")
        return

    # --- Split data: train / test / val ---
    from libs.optimization.scoring import split_temporal
    train_df, test_df, val_df = split_temporal(
        feature_df, train=args.train_ratio, test=args.test_ratio, val=args.val_ratio,
    )
    logger.info(f"Split: train={len(train_df)}, test={len(test_df)}, val={len(val_df)}")

    # --- Build objective from this model's optimizer (train set only) ---
    objective_fn = mr_optimizer.make_objective(
        train_df, timeframe=args.timeframe, cost_bps=args.cost_bps,
    )

    # --- Resolve study config ---
    n_trials = args.n_trials or mr_optimizer.STUDY_DEFAULTS.get("n_trials", 200)
    study_config = StudyConfig(
        model_name=mr_optimizer.MODEL_NAME,
        asset=args.asset,
        timeframe=args.timeframe,
        n_trials=n_trials,
        sampler=mr_optimizer.STUDY_DEFAULTS.get("sampler", "TPE"),
        pruner=mr_optimizer.STUDY_DEFAULTS.get("pruner", "MedianPruner"),
        objectives=["score"],
        directions=[mr_optimizer.STUDY_DEFAULTS.get("direction", "maximize")],
    )

    # --- Run Optuna study ---
    runner = OptunaRunner(study_config)
    results = runner.run(objective_fn=objective_fn, study_name=args.study_name)

    completed = [r for r in results if r.state == "COMPLETE"]
    if not completed:
        logger.warning("No completed trials")
        return

    best = max(completed, key=lambda r: list(r.values.values())[0])
    processed_params = mr_optimizer.post_process_params(best.params)
    logger.info(f"Best trial #{best.trial_number}: params={processed_params} values={best.values}")

    # --- Audit (on validation set — never seen during optimization) ---
    if args.audit:
        current_params = read_current_params(
            mr_optimizer.MODEL_NAME, args.asset, args.timeframe,
        )
        if current_params:
            auditor = ParamAuditor(
                val_df, timeframe=args.timeframe, cost_bps=args.cost_bps,
            )
            report = auditor.audit(
                mr_optimizer.MODEL_NAME, args.asset, args.timeframe,
                current_params, processed_params,
            )
            _print_audit_report(report)
        else:
            logger.info("No current params in models.yaml — skipping audit (first run)")

    # --- Write-back ---
    if args.write_back:
        write_best_params(
            mr_optimizer.MODEL_NAME, args.asset, args.timeframe, processed_params,
        )
        logger.info("Wrote best params to configs/optimized_params.yaml")

    logger.info(f"Optimization complete: {len(completed)}/{len(results)} trials completed")


def _print_audit_report(report) -> None:
    print(f"\n{'='*60}")
    print(f"PARAM AUDIT: {report.model_name} / {report.asset} / {report.timeframe}")
    print(f"{'='*60}")
    print(f"Recommendation: {report.recommendation.upper()}")
    print(f"Reason: {report.reason}")
    print(f"\n{'Metric':<20} {'Current':>12} {'Proposed':>12} {'Delta':>12}")
    print(f"{'-'*56}")
    for k in report.current_metrics:
        cur = report.current_metrics[k]
        prop = report.proposed_metrics[k]
        delta = report.deltas[k]
        print(f"{k:<20} {cur:>12.4f} {prop:>12.4f} {delta:>+12.4f}")
    print(f"\nCurrent params:  {report.current_params}")
    print(f"Proposed params: {report.proposed_params}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
