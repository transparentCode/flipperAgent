"""Offline Phase 7D playbook state-transition validation CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from libs.models.regime_v2.evaluation.playbook_state_transitions import (
    build_playbook_state_transition_matrix,
    render_playbook_state_transition_matrix_markdown,
)
from libs.models.regime_v2.orchestrator import RegimeV2Orchestrator
from libs.models.regime_v2.policy import build_playbook_context_frame, build_playbook_state_frame
from libs.models.regime_v2.scripts.compare_binance_native import fetch_binance_native_ohlcv


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    matrix = asyncio.run(_run(args))
    text = json.dumps(_json_safe(matrix), indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_playbook_state_transition_matrix_markdown(matrix), encoding="utf-8")
    return 0


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    ohlcv = await fetch_binance_native_ohlcv(
        symbol=args.asset,
        timeframe=args.timeframe,
        limit=args.limit,
        since=None,
        until=None,
    )
    series = RegimeV2Orchestrator.create(args.asset, args.timeframe).analyze_series(ohlcv)
    context = build_playbook_context_frame(series)
    states = build_playbook_state_frame(context)
    matrix = build_playbook_state_transition_matrix(
        states,
        ohlcv,
        transition_bars=tuple(args.transition_bars),
        outcome_horizons=tuple(args.outcome_horizon),
        large_move_bps=args.large_move_bps,
    )
    matrix["asset"] = args.asset
    matrix["timeframe"] = args.timeframe
    matrix["input_rows"] = int(len(ohlcv))
    return matrix


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate playbook state transitions across outcomes.")
    parser.add_argument("--asset", default="BNBUSDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--limit", type=int, default=720)
    parser.add_argument("--transition-bars", action="append", type=int, default=None)
    parser.add_argument("--outcome-horizon", action="append", type=int, default=None)
    parser.add_argument("--large-move-bps", type=float, default=20.0)
    parser.add_argument("--output-json", default="research/regime_v2_phase7d_state_transitions.json")
    parser.add_argument("--output-md", default="research/regime_v2_phase7d_state_transitions.md")
    args = parser.parse_args(argv)
    args.transition_bars = args.transition_bars or [1, 3, 6]
    args.outcome_horizon = args.outcome_horizon or [3, 6, 12, 24]
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
