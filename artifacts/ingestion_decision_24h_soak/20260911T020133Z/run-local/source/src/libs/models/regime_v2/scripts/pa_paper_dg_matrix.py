"""CLI for PA paper drift-gate matrix validation."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import pandas as pd

from libs.models.regime_v2.scripts.compare_binance_native import fetch_binance_native_ohlcv
from libs.models.regime_v2.scripts.label_shadow_outcomes_binance import _min_since_for_pair, _pairs_from_records
from libs.selection.regime_v2_pa_paper_dg_matrix import (
    build_pa_paper_dg_matrix_report,
    render_pa_paper_dg_matrix_markdown,
)
from libs.selection.regime_v2_pa_paper_report import load_pa_paper_decisions


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = asyncio.run(_run(args))
    text = json.dumps(_json_safe(report), indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_pa_paper_dg_matrix_markdown(report), encoding="utf-8")
    return 0


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    records, invalid = load_pa_paper_decisions(args.log)
    pairs = _pairs_from_records(records)
    ohlcv_by_pair: dict[tuple[str, str], pd.DataFrame] = {}
    fetch_errors: dict[str, str] = {}
    for asset, timeframe in pairs:
        try:
            ohlcv_by_pair[(asset, timeframe)] = await fetch_binance_native_ohlcv(
                symbol=asset,
                timeframe=timeframe,
                limit=args.limit,
                since=_min_since_for_pair(records, asset, timeframe),
                until=None,
            )
        except Exception as exc:
            fetch_errors[f"{asset}|{timeframe}"] = str(exc)
    report = build_pa_paper_dg_matrix_report(
        records,
        ohlcv_by_pair,
        horizons=tuple(args.horizon),
        fees_bps=tuple(args.fee_bps),
        rolling_windows=tuple(args.rolling_window),
        min_window=args.min_window,
        min_cell_improvement=args.min_cell_improvement,
        max_lost_avoided=args.max_lost_avoided,
        min_rolling_positive_rate=args.min_rolling_positive_rate,
    )
    report["source_log"] = args.log
    report["invalid_record_count"] = invalid
    report["fetch_errors"] = fetch_errors
    report["pairs"] = [f"{asset}|{timeframe}" for asset, timeframe in pairs]
    return report


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate PA paper drift gate across horizon/fee matrix.")
    parser.add_argument("--log", default="logs/regime_v2_pa_asset_paper_decisions.jsonl")
    parser.add_argument("--limit", type=int, default=1200)
    parser.add_argument("--horizon", action="append", type=int, default=None)
    parser.add_argument("--fee-bps", action="append", type=float, default=None)
    parser.add_argument("--rolling-window", action="append", type=int, default=None)
    parser.add_argument("--min-window", type=int, default=10)
    parser.add_argument("--min-cell-improvement", type=float, default=0.0)
    parser.add_argument("--max-lost-avoided", type=int, default=0)
    parser.add_argument("--min-rolling-positive-rate", type=float, default=0.50)
    parser.add_argument("--output-json", default="research/regime_v2_pa_paper_dg_matrix.json")
    parser.add_argument("--output-md", default="research/regime_v2_pa_paper_dg_matrix.md")
    args = parser.parse_args(argv)
    args.horizon = args.horizon or [3, 6, 12, 24]
    args.fee_bps = args.fee_bps or [2.0, 5.0, 10.0]
    args.rolling_window = args.rolling_window or [20, 30, 50]
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
