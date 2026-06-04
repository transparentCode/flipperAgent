from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from libs.regime.optimization.simple_baseline_benchmark import (
    DEFAULT_STRATEGIES,
    build_simple_baseline_report,
    build_simple_panel_summary,
)
from libs.regime.optimization.downstream_backtest import DEFAULT_CANDIDATES


def _default_days_for_timeframe(timeframe: str) -> int:
    return {"30m": 180, "1h": 300, "4h": 500, "1d": 800}.get(timeframe, 300)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline benchmark ladder for regime overlays against simple deterministic strategies.",
    )
    parser.add_argument("--assets", nargs="+", default=["BTCUSDT", "ETHUSDT", "SUIUSDT", "TAOUSDT"])
    parser.add_argument("--timeframes", nargs="+", default=["1h"])
    parser.add_argument("--days", type=int, default=None)
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--candidates", nargs="+", choices=sorted(DEFAULT_CANDIDATES), default=list(DEFAULT_CANDIDATES))
    parser.add_argument("--strategies", nargs="+", choices=sorted(DEFAULT_STRATEGIES), default=list(DEFAULT_STRATEGIES))
    parser.add_argument("--show-hmm-warnings", action="store_true")
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    if not args.show_hmm_warnings:
        logging.getLogger("hmmlearn").setLevel(logging.ERROR)
        logging.getLogger("hmmlearn.base").setLevel(logging.ERROR)

    requested: list[tuple[str, str, int]] = []
    for asset in args.assets:
        for timeframe in args.timeframes:
            days = args.days if args.days is not None else _default_days_for_timeframe(timeframe)
            requested.append((asset, timeframe, days))
    if "BTCUSDT" in args.assets and "30m" not in args.timeframes:
        requested.append(("BTCUSDT", "30m", args.days if args.days is not None else _default_days_for_timeframe("30m")))

    rows = [
        build_simple_baseline_report(
            asset,
            timeframe,
            days=days,
            cost_bps=args.cost_bps,
            candidate_names=tuple(args.candidates),
            strategy_names=tuple(args.strategies),
        )
        for asset, timeframe, days in requested
    ]
    payload = {
        "results": rows,
        "panel_summary": build_simple_panel_summary(
            rows,
            candidate_names=tuple(args.candidates),
            strategy_names=tuple(args.strategies),
        ),
    }
    text = json.dumps(payload, indent=2)
    print(text)

    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


if __name__ == "__main__":
    main()
