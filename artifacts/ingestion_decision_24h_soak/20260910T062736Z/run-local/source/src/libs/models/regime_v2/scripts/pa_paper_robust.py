"""PA paper robustness CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import pandas as pd

from libs.models.regime_v2.scripts.compare_binance_native import fetch_binance_native_ohlcv
from libs.models.regime_v2.scripts.label_shadow_outcomes_binance import _min_since_for_pair, _pairs_from_records
from libs.selection.regime_v2_pa_paper_report import load_pa_paper_decisions
from libs.selection.regime_v2_pa_paper_robustness import build_pa_paper_robustness_report, render_pa_paper_robustness_markdown


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
        Path(args.output_md).write_text(render_pa_paper_robustness_markdown(report), encoding="utf-8")
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
    report = build_pa_paper_robustness_report(
        records,
        ohlcv_by_pair,
        horizons=tuple(args.horizon),
        fees_bps=tuple(args.fee_bps),
        rolling_windows=tuple(args.rolling_window),
        min_window=args.min_window,
        min_support=args.min_support,
        min_positive_rate=args.min_positive_rate,
        passing_cell_floor=args.passing_cell_floor,
        max_negative_cells=args.max_negative_cells,
        rolling_stable_floor=args.rolling_stable_floor,
    )
    report["source_log"] = args.log
    report["invalid_record_count"] = invalid
    report["pairs"] = [f"{asset}|{timeframe}" for asset, timeframe in pairs]
    report["fetch_errors"] = fetch_errors
    return report


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build PA paper robustness report.")
    parser.add_argument("--log", default="logs/regime_v2_pa_asset_paper_decisions.jsonl")
    parser.add_argument("--limit", type=int, default=1200)
    parser.add_argument("--horizon", action="append", type=int, default=None)
    parser.add_argument("--fee-bps", action="append", type=float, default=None)
    parser.add_argument("--rolling-window", action="append", type=int, default=None)
    parser.add_argument("--min-window", type=int, default=10)
    parser.add_argument("--min-support", type=int, default=30)
    parser.add_argument("--min-positive-rate", type=float, default=0.60)
    parser.add_argument("--passing-cell-floor", type=int, default=10)
    parser.add_argument("--max-negative-cells", type=int, default=1)
    parser.add_argument("--rolling-stable-floor", type=int, default=8)
    parser.add_argument("--output-json", default="research/regime_v2_pa_paper_robustness.json")
    parser.add_argument("--output-md", default="research/regime_v2_pa_paper_robustness.md")
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
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


if __name__ == "__main__":
    raise SystemExit(main())
