#!/usr/bin/env python
"""Run the RegimeClassification descriptor information ladder."""

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

from libs.models.regime_classification.optimization.descriptor_ladder import (
    run_descriptor_ladder,
    run_rolling_descriptor_ladder,
    summarize_descriptor_panel,
)
from libs.models.regime_classification.optimization.settings import (
    load_regime_optimization_settings,
)
from libs.optim_utils.data_fetcher import fetch_historical_ohlcv


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Descriptor IC ladder for RegimeClassification outputs.",
    )
    parser.add_argument("--assets", nargs="+", default=["BTCUSDT"])
    parser.add_argument("--asset", default=None, help="Asset label for --input-csv mode")
    parser.add_argument("--timeframes", nargs="+", default=["1h"])
    parser.add_argument("--timeframe", default=None, help="Timeframe for --input-csv mode")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--input-csv", type=str, default=None)
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--rolling", action="store_true")
    parser.add_argument("--fold-bars", type=int, default=None)
    parser.add_argument("--step-bars", type=int, default=None)
    parser.add_argument("--null-controls", nargs="+", default=None)
    parser.add_argument(
        "--descriptor-targets",
        nargs="+",
        default=None,
        help="Descriptor/target pairs like fwd_vol_ewma:fwd_vol_5.",
    )
    parser.add_argument("--show-hmm-warnings", action="store_true")
    args = parser.parse_args()

    if not args.show_hmm_warnings:
        logging.getLogger("hmmlearn").setLevel(logging.ERROR)
        logging.getLogger("hmmlearn.base").setLevel(logging.ERROR)

    settings_override: dict[str, Any] = {}
    descriptor_override: dict[str, Any] = {}
    if args.null_controls is not None:
        descriptor_override["null_controls"] = args.null_controls
    if args.descriptor_targets is not None:
        descriptor_override["descriptor_targets"] = _parse_descriptor_targets(
            args.descriptor_targets
        )
    if descriptor_override:
        settings_override = {"descriptor_ladder": descriptor_override}
    settings = load_regime_optimization_settings(settings_override)

    reports: list[dict[str, Any]] = []
    if args.input_csv:
        asset = args.asset or (args.assets[0] if args.assets else "")
        timeframe = args.timeframe or (args.timeframes[0] if args.timeframes else "1h")
        reports.append(
            _run_one(
                _load_csv(args.input_csv),
                asset=asset,
                timeframe=timeframe,
                settings=settings,
                args=args,
            )
        )
    else:
        for asset in args.assets:
            for timeframe in args.timeframes:
                reports.append(
                    _run_one(
                        _fetch_frame(asset, timeframe, args.days),
                        asset=asset,
                        timeframe=timeframe,
                        settings=settings,
                        args=args,
                    )
                )

    payload = {
        "reports": reports,
        "panel_summary": summarize_descriptor_panel(reports),
    }
    text = json.dumps(payload, indent=2, default=_json_default)
    print(text)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def _run_one(
    frame: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    settings: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    if args.rolling:
        return run_rolling_descriptor_ladder(
            frame,
            asset=asset,
            timeframe=timeframe,
            settings=settings,
            fold_bars=args.fold_bars,
            step_bars=args.step_bars,
        )
    return run_descriptor_ladder(
        frame,
        asset=asset,
        timeframe=timeframe,
        settings=settings,
    )


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


def _parse_descriptor_targets(values: list[str]) -> list[dict[str, str]]:
    pairs = []
    for value in values:
        if ":" not in value:
            raise ValueError(
                "--descriptor-targets values must be formatted as descriptor:target"
            )
        descriptor, target = value.split(":", 1)
        pairs.append({"descriptor": descriptor, "target": target})
    return pairs


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    return str(value)


if __name__ == "__main__":
    main()
