#!/usr/bin/env python
"""Run the RegimeClassification offline benchmark ladder.

Examples:
    PYTHONPATH=src .venv/bin/python scripts/regime_classification_benchmark_ladder.py \
        --assets BTCUSDT --timeframes 1h --days 180

    PYTHONPATH=src .venv/bin/python scripts/regime_classification_benchmark_ladder.py \
        --input-csv data/btcusdt_1h.csv --asset BTCUSDT --timeframe 1h
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from libs.models.regime_classification.optimization.benchmark_ladder import (
    run_benchmark_ladder,
    summarize_ladder_panel,
)
from libs.optim_utils.data_fetcher import fetch_historical_ohlcv


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline benchmark ladder for RegimeClassification descriptors.",
    )
    parser.add_argument("--assets", nargs="+", default=["BTCUSDT"])
    parser.add_argument("--asset", default=None, help="Asset label for --input-csv mode")
    parser.add_argument("--timeframes", nargs="+", default=["1h"])
    parser.add_argument("--timeframe", default=None, help="Timeframe for --input-csv mode")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--input-csv", type=str, default=None)
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--show-hmm-warnings", action="store_true")
    args = parser.parse_args()

    if not args.show_hmm_warnings:
        logging.getLogger("hmmlearn").setLevel(logging.ERROR)
        logging.getLogger("hmmlearn.base").setLevel(logging.ERROR)

    reports: list[dict[str, Any]] = []
    if args.input_csv:
        asset = args.asset or (args.assets[0] if args.assets else "")
        timeframe = args.timeframe or (args.timeframes[0] if args.timeframes else "1h")
        reports.append(
            run_benchmark_ladder(
                _load_csv(args.input_csv),
                asset=asset,
                timeframe=timeframe,
            )
        )
    else:
        for asset in args.assets:
            for timeframe in args.timeframes:
                reports.append(
                    run_benchmark_ladder(
                        _fetch_frame(asset, timeframe, args.days),
                        asset=asset,
                        timeframe=timeframe,
                    )
                )

    payload = {
        "reports": reports,
        "panel_summary": summarize_ladder_panel(reports),
    }
    text = json.dumps(payload, indent=2, default=_json_default)
    print(text)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def _fetch_frame(asset: str, timeframe: str, days: int) -> pd.DataFrame:
    since_ms = int((time.time() - days * 86_400) * 1000)
    limit = max(_bars_for_timeframe(timeframe, days), 500)
    frame = fetch_historical_ohlcv(
        symbol=asset,
        timeframe=timeframe,
        since=since_ms,
        limit=limit,
    )
    if "timestamp" in frame.columns:
        frame.index = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    return frame


def _load_csv(path: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    for col in ("datetime", "timestamp", "time"):
        if col in frame.columns:
            if col == "timestamp":
                frame.index = pd.to_datetime(frame[col], unit="ms", utc=True)
            else:
                frame.index = pd.to_datetime(frame[col], utc=True)
            break
    return frame


def _bars_for_timeframe(timeframe: str, days: int) -> int:
    suffix = timeframe[-1].lower()
    value = int(timeframe[:-1])
    if suffix == "m":
        return int(days * 24 * 60 / value)
    if suffix == "h":
        return int(days * 24 / value)
    if suffix == "d":
        return int(days / value)
    return days * 24


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    return str(value)


if __name__ == "__main__":
    main()
