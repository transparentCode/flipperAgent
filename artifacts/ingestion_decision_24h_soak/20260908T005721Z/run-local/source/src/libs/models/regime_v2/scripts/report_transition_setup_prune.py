"""Offline Phase 7R setup-transition pruning discovery runner."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from libs.models.regime_v2.evaluation.playbook_transition_setup_prune import (
    build_setup_transition_prune_matrix_report,
    build_setup_transition_prune_retest_report,
    render_setup_transition_prune_markdown,
)
from libs.models.regime_v2.orchestrator import RegimeV2Orchestrator
from libs.models.regime_v2.policy import build_playbook_context_frame, build_playbook_state_frame
from libs.models.regime_v2.scripts.compare_binance_native import fetch_binance_native_ohlcv


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    payload = asyncio.run(_run(args))
    text = json.dumps(_json_safe(payload), indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_setup_transition_prune_markdown(payload["matrix_report"]), encoding="utf-8")
    return 0


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    reports = []
    for asset in args.asset:
        for timeframe in args.timeframe:
            ohlcv = await fetch_binance_native_ohlcv(symbol=asset, timeframe=timeframe, limit=args.limit, since=None, until=None)
            series = RegimeV2Orchestrator.create(asset, timeframe).analyze_series(ohlcv)
            context = build_playbook_context_frame(series)
            states = build_playbook_state_frame(context)
            for lookback in args.lookback_bars:
                for candidate_score in args.min_candidate_score:
                    for score_gap in args.min_score_gap:
                        for continuation in args.max_continuation_score:
                            for volatility_q in args.max_volatility_quantile:
                                for phase_mode in args.phase_mode:
                                    reports.append(
                                        build_setup_transition_prune_retest_report(
                                            series,
                                            context,
                                            states,
                                            ohlcv,
                                            asset=asset,
                                            timeframe=timeframe,
                                            split_count=args.split_count,
                                            horizons=tuple(args.horizon),
                                            fees_bps=tuple(args.fee_bps),
                                            min_split_support=args.min_split_support,
                                            min_passing_rate=args.min_passing_rate,
                                            min_avg_return=args.min_avg_return,
                                            max_worst_loss=args.max_worst_loss,
                                            lookback_bars=int(lookback),
                                            min_candidate_score=float(candidate_score),
                                            min_context_score=args.min_context_score,
                                            max_risk_score=args.max_risk_score,
                                            max_conflict_count=args.max_conflict_count,
                                            min_wick_score=args.min_wick_score,
                                            min_attempt_score=args.min_attempt_score,
                                            min_score_gap=float(score_gap),
                                            max_continuation_score=_continuation_arg(continuation),
                                            max_volatility_quantile=float(volatility_q),
                                            allowed_market_phases=_phase_mode_arg(phase_mode),
                                            allowed_directions=tuple(args.direction),
                                        )
                                    )
    matrix = build_setup_transition_prune_matrix_report(reports)
    return {
        "phase": "phase_7r_setup_transition_prune_runner",
        "asset": args.asset,
        "timeframe": args.timeframe,
        "input_rows": args.limit,
        "matrix_report": matrix,
        "variant_reports": reports,
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 7R setup-transition pruning discovery.")
    parser.add_argument("--asset", action="append", default=None)
    parser.add_argument("--timeframe", action="append", default=None)
    parser.add_argument("--limit", type=int, default=720)
    parser.add_argument("--lookback-bars", action="append", type=int, default=None)
    parser.add_argument("--min-candidate-score", action="append", type=float, default=None)
    parser.add_argument("--min-context-score", type=float, default=0.70)
    parser.add_argument("--max-risk-score", type=float, default=0.72)
    parser.add_argument("--max-conflict-count", type=int, default=1)
    parser.add_argument("--min-wick-score", type=float, default=0.35)
    parser.add_argument("--min-attempt-score", type=float, default=0.50)
    parser.add_argument("--min-score-gap", action="append", type=float, default=None)
    parser.add_argument("--max-continuation-score", action="append", type=float, default=None, help="Use -1 for no continuation prune.")
    parser.add_argument("--max-volatility-quantile", action="append", type=float, default=None)
    parser.add_argument("--phase-mode", action="append", choices=("all", "breakout_setup", "compressed_wait"), default=None)
    parser.add_argument("--direction", action="append", choices=("up", "down"), default=None)
    parser.add_argument("--split-count", type=int, default=4)
    parser.add_argument("--horizon", action="append", type=int, default=None)
    parser.add_argument("--fee-bps", action="append", type=float, default=None)
    parser.add_argument("--min-split-support", type=int, default=2)
    parser.add_argument("--min-passing-rate", type=float, default=0.60)
    parser.add_argument("--min-avg-return", type=float, default=0.0)
    parser.add_argument("--max-worst-loss", type=float, default=0.0010)
    parser.add_argument("--output-json", default="research/regime_v2_phase7r_transition_setup_prune.json")
    parser.add_argument("--output-md", default="research/regime_v2_phase7r_transition_setup_prune.md")
    args = parser.parse_args(argv)
    args.asset = args.asset or ["ETHUSDT", "BNBUSDT", "BTCUSDT"]
    args.timeframe = args.timeframe or ["1h"]
    args.lookback_bars = args.lookback_bars or [8]
    args.min_candidate_score = args.min_candidate_score or [0.62]
    args.min_score_gap = args.min_score_gap or [0.0, 0.15, 0.25]
    args.max_continuation_score = args.max_continuation_score or [-1.0, 0.70, 0.80]
    args.max_volatility_quantile = args.max_volatility_quantile or [1.0, 0.85, 0.70]
    args.phase_mode = args.phase_mode or ["all", "breakout_setup", "compressed_wait"]
    args.direction = args.direction or ["up", "down"]
    args.horizon = args.horizon or [3, 6, 12, 24]
    args.fee_bps = args.fee_bps or [2.0, 5.0, 10.0]
    return args


def _continuation_arg(value: float) -> float | None:
    return None if float(value) < 0.0 else float(value)


def _phase_mode_arg(value: str) -> tuple[str, ...] | None:
    if value == "all":
        return None
    return (value,)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_safe(val) for val in value]
    if isinstance(value, tuple):
        return [_json_safe(val) for val in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
