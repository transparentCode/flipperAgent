"""CLI for PA paper drift/streak gate simulation."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import pandas as pd

from libs.models.regime_v2.scripts.compare_binance_native import fetch_binance_native_ohlcv
from libs.models.regime_v2.scripts.label_shadow_outcomes_binance import _min_since_for_pair, _pairs_from_records
from libs.selection.regime_v2_pa_paper_drift_gate import (
    build_pa_paper_drift_gate_report,
    render_pa_paper_drift_gate_markdown,
)
from libs.selection.regime_v2_pa_paper_report import label_pa_paper_outcomes, load_pa_paper_decisions
from libs.selection.regime_v2_pa_paper_window_diagnostics import worst_window_from_robustness


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
        Path(args.output_md).write_text(render_pa_paper_drift_gate_markdown(report), encoding="utf-8")
    return 0


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    records, invalid = load_pa_paper_decisions(args.log)
    robustness = json.loads(Path(args.robustness).read_text(encoding="utf-8")) if args.robustness else {}
    window = worst_window_from_robustness(robustness)
    horizon_bars = int(window.get("horizon_bars") or args.default_horizon_bars)
    fee_bps = float(window.get("fee_bps") or args.default_fee_bps)
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
    labeled = label_pa_paper_outcomes(records, ohlcv_by_pair, horizon_bars=horizon_bars, fee_bps=fee_bps)
    report = build_pa_paper_drift_gate_report(
        labeled,
        failure_window=window,
        min_paused_rows=args.min_paused_rows,
    )
    report["source_log"] = args.log
    report["source_robustness"] = args.robustness
    report["invalid_record_count"] = invalid
    report["fetch_errors"] = fetch_errors
    report["pairs"] = [f"{asset}|{timeframe}" for asset, timeframe in pairs]
    report["labeling_horizon_bars"] = horizon_bars
    report["labeling_fee_bps"] = fee_bps
    return report


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate PA paper drift/streak pause gates.")
    parser.add_argument("--log", default="logs/regime_v2_pa_asset_paper_decisions.jsonl")
    parser.add_argument("--robustness", default="research/regime_v2_pa_paper_robustness.json")
    parser.add_argument("--limit", type=int, default=1200)
    parser.add_argument("--default-horizon-bars", type=int, default=12)
    parser.add_argument("--default-fee-bps", type=float, default=5.0)
    parser.add_argument("--min-paused-rows", type=int, default=1)
    parser.add_argument("--output-json", default="research/regime_v2_pa_paper_drift_gate.json")
    parser.add_argument("--output-md", default="research/regime_v2_pa_paper_drift_gate.md")
    return parser.parse_args(argv)


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
