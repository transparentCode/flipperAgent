"""Offline Phase 7N transition-regime retest runner."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from libs.models.regime_v2.evaluation.playbook_ft_transition_regime import (
    build_ft_transition_regime_matrix_report,
    build_ft_transition_regime_retest_report,
    render_ft_transition_regime_markdown,
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
        Path(args.output_md).write_text(render_ft_transition_regime_markdown(payload["matrix_report"]), encoding="utf-8")
    return 0


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    reports = []
    for asset in args.asset:
        for timeframe in args.timeframe:
            ohlcv = await fetch_binance_native_ohlcv(symbol=asset, timeframe=timeframe, limit=args.limit, since=None, until=None)
            series = RegimeV2Orchestrator.create(asset, timeframe).analyze_series(ohlcv)
            context = build_playbook_context_frame(series)
            states = build_playbook_state_frame(context)
            for threshold in args.threshold:
                for action in args.action:
                    for edge in args.min_transition_edge:
                        reports.append(
                            build_ft_transition_regime_retest_report(
                                series,
                                context,
                                states,
                                ohlcv,
                                asset=asset,
                                timeframe=timeframe,
                                threshold=float(threshold),
                                split_count=args.split_count,
                                horizons=tuple(args.horizon),
                                fees_bps=tuple(args.fee_bps),
                                min_split_support=args.min_split_support,
                                min_passing_rate=args.min_passing_rate,
                                min_avg_return=args.min_avg_return,
                                max_worst_loss=args.max_worst_loss,
                                gate_min_context_score=args.gate_min_context_score,
                                gate_max_risk_score=args.gate_max_risk_score,
                                gate_max_conflict_count=args.gate_max_conflict_count,
                                min_transition_edge=float(edge),
                                min_reversal_penalty=args.min_reversal_penalty,
                                min_transition_context_score=args.min_transition_context_score,
                                transition_directions=tuple(args.transition_direction),
                                action=action,
                            )
                        )
    matrix = build_ft_transition_regime_matrix_report(reports)
    return {
        "phase": "phase_7n_ft_transition_regime_runner",
        "asset": args.asset,
        "timeframe": args.timeframe,
        "input_rows": args.limit,
        "matrix_report": matrix,
        "variant_reports": reports,
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 7N transition-regime retest.")
    parser.add_argument("--asset", action="append", default=None)
    parser.add_argument("--timeframe", action="append", default=None)
    parser.add_argument("--limit", type=int, default=720)
    parser.add_argument("--threshold", action="append", type=float, default=None)
    parser.add_argument("--split-count", type=int, default=4)
    parser.add_argument("--action", action="append", choices=("reverse_direction", "suppress", "tag_only"), default=None)
    parser.add_argument("--min-transition-edge", action="append", type=float, default=None)
    parser.add_argument("--transition-direction", action="append", default=None)
    parser.add_argument("--min-reversal-penalty", type=float, default=0.60)
    parser.add_argument("--min-transition-context-score", type=float, default=0.70)
    parser.add_argument("--horizon", action="append", type=int, default=None)
    parser.add_argument("--fee-bps", action="append", type=float, default=None)
    parser.add_argument("--min-split-support", type=int, default=2)
    parser.add_argument("--min-passing-rate", type=float, default=0.60)
    parser.add_argument("--min-avg-return", type=float, default=0.0)
    parser.add_argument("--max-worst-loss", type=float, default=0.0010)
    parser.add_argument("--gate-min-context-score", type=float, default=0.70)
    parser.add_argument("--gate-max-risk-score", type=float, default=0.72)
    parser.add_argument("--gate-max-conflict-count", type=int, default=1)
    parser.add_argument("--output-json", default="research/regime_v2_phase7n_ft_transition_regime.json")
    parser.add_argument("--output-md", default="research/regime_v2_phase7n_ft_transition_regime.md")
    args = parser.parse_args(argv)
    args.asset = args.asset or ["BNBUSDT", "ETHUSDT", "BTCUSDT"]
    args.timeframe = args.timeframe or ["1h"]
    args.threshold = args.threshold or [0.25, 0.30]
    args.action = args.action or ["reverse_direction", "suppress", "tag_only"]
    args.min_transition_edge = args.min_transition_edge or [0.10, 0.18, 0.25]
    args.transition_direction = args.transition_direction or ["up", "down"]
    args.horizon = args.horizon or [3, 6, 12, 24]
    args.fee_bps = args.fee_bps or [2.0, 5.0, 10.0]
    return args


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
