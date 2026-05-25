"""CLI runner for TrendFollowing optimization.

Usage:
    PYTHONPATH=src python -m libs.models.trend_following.optimization.optimize \
        --asset BTCUSDT --timeframe 4h --n-trials 300 --audit --write-back
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_src = str(Path(__file__).resolve().parents[4])
if _src not in sys.path:
    sys.path.insert(0, _src)

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import StudyConfig
from libs.optim_utils.data_fetcher import fetch_historical_ohlcv
from libs.optim_utils.param_auditor import ParamAuditor
from libs.optim_utils.param_writeback import read_current_params, write_best_params
from libs.optim_utils.runner import OptunaRunner

import libs.models  # noqa: F401

from libs.models.trend_following.optimization import optimizer as tf_optimizer

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run TrendFollowing optimization study"
    )
    parser.add_argument("--asset", required=True)
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--n-trials", type=int, default=None)
    parser.add_argument("--since", type=int, default=None)
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--train-ratio", type=float, default=0.6)
    parser.add_argument("--test-ratio", type=float, default=0.2)
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--write-back", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--study-name", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    import time
    since_ms = args.since
    if since_ms is None:
        since_ms = int((time.time() - args.days * 86400) * 1000)

    logger.info(f"Fetching {args.days}d of {args.timeframe} candles for {args.asset}")
    feature_df = fetch_historical_ohlcv(
        symbol=args.asset,
        timeframe=args.timeframe,
        since=since_ms,
        limit=args.days * 24,
    )
    logger.info(f"Fetched {len(feature_df)} candles")

    if len(feature_df) < 50:
        logger.warning("Insufficient data for optimization — need at least 50 candles")
        return

    from libs.optim_utils.scoring import split_temporal
    train_df, test_df, val_df = split_temporal(
        feature_df, train=args.train_ratio, test=args.test_ratio, val=args.val_ratio,
    )
    logger.info(f"Split: train={len(train_df)}, test={len(test_df)}, val={len(val_df)}")

    objective_fn = tf_optimizer.make_objective(
        train_df, timeframe=args.timeframe, cost_bps=args.cost_bps,
    )

    n_trials = args.n_trials or tf_optimizer.STUDY_DEFAULTS.get("n_trials", 300)
    directions = tf_optimizer.STUDY_DEFAULTS.get("directions", ["maximize", "maximize"])
    study_config = StudyConfig(
        model_name=tf_optimizer.MODEL_NAME,
        asset=args.asset,
        timeframe=args.timeframe,
        n_trials=n_trials,
        sampler=tf_optimizer.STUDY_DEFAULTS.get("sampler", "NSGAIISampler"),
        pruner=tf_optimizer.STUDY_DEFAULTS.get("pruner", "MedianPruner"),
        objectives=["sharpe", "win_rate"],
        directions=directions,
    )

    runner = OptunaRunner(study_config)
    results = runner.run(objective_fn=objective_fn, study_name=args.study_name)

    completed = [r for r in results if r.state == "COMPLETE"]
    if not completed:
        logger.warning("No completed trials")
        return

    # Multi-objective: select from Pareto front — pick highest Sharpe among Pareto-optimal
    best = max(completed, key=lambda r: r.values.get("sharpe", 0.0))
    processed_params = tf_optimizer.post_process_params(best.params)
    logger.info(f"Best trial #{best.trial_number}: params={processed_params} values={best.values}")

    if args.audit:
        current_params = read_current_params(
            tf_optimizer.MODEL_NAME, args.asset, args.timeframe,
        )
        if current_params:
            auditor = ParamAuditor(
                val_df, timeframe=args.timeframe, cost_bps=args.cost_bps,
            )
            report = auditor.audit(
                tf_optimizer.MODEL_NAME, args.asset, args.timeframe,
                current_params, processed_params,
            )
            _print_audit_report(report)
        else:
            logger.info("No current params in models.yaml — skipping audit (first run)")

    if args.write_back:
        write_best_params(
            tf_optimizer.MODEL_NAME, args.asset, args.timeframe, processed_params,
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
