"""CLI runner for SqueezeBreakoutScorer optimization.

Usage:
    PYTHONPATH=src python -m libs.models.squeeze_breakout.optimization.scoring_optimize \
        --asset BTCUSDT --timeframe 1h --n-trials 200 --days 180 --audit
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Ensure src/ is on sys.path when run as a script
_src = str(Path(__file__).resolve().parents[4])
if _src not in sys.path:
    sys.path.insert(0, _src)

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import StudyConfig
from libs.optim_utils.data_fetcher import fetch_historical_ohlcv
from libs.optim_utils.scoring_feature_pipeline import build_scoring_feature_df
from libs.optim_utils.param_auditor import ParamAuditor
from libs.optim_utils.param_writeback import read_current_params, write_best_params
from libs.optim_utils.runner import OptunaRunner

# Trigger model registration
import libs.models  # noqa: F401

from libs.models.squeeze_breakout.optimization import scoring_optimizer as sb_optimizer

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run SqueezeBreakoutScorer optimization study"
    )
    parser.add_argument("--asset", required=True, help="Asset symbol (e.g., BTCUSDT)")
    parser.add_argument("--timeframe", required=True, help="Timeframe (e.g., 1h)")
    parser.add_argument("--n-trials", type=int, default=None)
    parser.add_argument("--days", type=int, default=180,
                        help="Number of days of historical data (default: 180)")
    parser.add_argument("--cost-bps", type=float, default=10.0,
                        help="Round-trip transaction cost in basis points")
    parser.add_argument("--write-back", action="store_true",
                        help="Write best params to configs/optimized_params.yaml")
    parser.add_argument("--audit", action="store_true",
                        help="Compare new vs current params")
    parser.add_argument("--study-name", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # --- Fetch OHLCV from Binance ---
    since_ms = int((time.time() - args.days * 86400) * 1000)
    logger.info(f"Fetching {args.days}d of {args.timeframe} candles for {args.asset}")
    ohlcv_df = fetch_historical_ohlcv(
        symbol=args.asset,
        timeframe=args.timeframe,
        since=since_ms,
        limit=args.days * 24,
    )
    logger.info(f"Fetched {len(ohlcv_df)} candles")

    if len(ohlcv_df) < 200:
        logger.warning("Insufficient data — need at least 200 candles")
        return

    # --- Build feature DataFrame ---
    logger.info("Building scoring feature DataFrame…")
    feature_df = build_scoring_feature_df(ohlcv_df, args.asset, args.timeframe)
    logger.info(f"Feature DataFrame: {len(feature_df)} rows, {len(feature_df.columns)} columns")

    # --- Build objective ---
    objective_fn = sb_optimizer.make_objective(
        feature_df, timeframe=args.timeframe, cost_bps=args.cost_bps,
    )

    # --- Study config ---
    n_trials = args.n_trials or sb_optimizer.STUDY_DEFAULTS.get("n_trials", 200)
    study_config = StudyConfig(
        model_name=sb_optimizer.MODEL_NAME,
        asset=args.asset,
        timeframe=args.timeframe,
        n_trials=n_trials,
        sampler=sb_optimizer.STUDY_DEFAULTS.get("sampler", "TPE"),
        pruner=sb_optimizer.STUDY_DEFAULTS.get("pruner", "MedianPruner"),
        objectives=["score"],
        directions=[sb_optimizer.STUDY_DEFAULTS.get("direction", "maximize")],
    )

    # --- Run ---
    runner = OptunaRunner(study_config)
    results = runner.run(objective_fn=objective_fn, study_name=args.study_name)

    completed = [r for r in results if r.state == "COMPLETE"]
    if not completed:
        logger.warning("No completed trials")
        return

    best = max(completed, key=lambda r: list(r.values.values())[0])
    processed_params = sb_optimizer.post_process_params(best.params)
    logger.info(f"Best trial #{best.trial_number}: params={processed_params} values={best.values}")

    # --- Audit ---
    if args.audit:
        current_params = read_current_params(
            sb_optimizer.MODEL_NAME, args.asset, args.timeframe,
        )
        if current_params:
            auditor = ParamAuditor(
                feature_df, timeframe=args.timeframe, cost_bps=args.cost_bps,
            )
            report = auditor.audit(
                sb_optimizer.MODEL_NAME, args.asset, args.timeframe,
                current_params, processed_params,
            )
            _print_audit_report(report)
        else:
            logger.info("No current params in models.yaml — skipping audit (first run)")

    # --- Write-back ---
    if args.write_back:
        write_best_params(
            sb_optimizer.MODEL_NAME, args.asset, args.timeframe, processed_params,
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
