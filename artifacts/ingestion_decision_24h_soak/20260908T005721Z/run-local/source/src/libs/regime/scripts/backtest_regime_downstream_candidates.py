from __future__ import annotations

import argparse
import json
from pathlib import Path

from libs.regime.optimization.downstream_backtest import (
    DEFAULT_CANDIDATES,
    build_downstream_candidate_report,
    build_panel_summary,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline downstream backtest for frozen regime candidates.",
    )
    parser.add_argument("--assets", nargs="+", default=["BTCUSDT", "ETHUSDT", "SUIUSDT", "TAOUSDT"])
    parser.add_argument("--timeframes", nargs="+", default=["1h"])
    parser.add_argument("--days", type=int, default=300)
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--candidates", nargs="+", choices=sorted(DEFAULT_CANDIDATES), default=list(DEFAULT_CANDIDATES))
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    requested = []
    if "BTCUSDT" in args.assets and "30m" not in args.timeframes:
        pass
    for asset in args.assets:
        for timeframe in args.timeframes:
            requested.append((asset, timeframe))
    if "BTCUSDT" in args.assets and "30m" not in args.timeframes:
        requested.append(("BTCUSDT", "30m"))

    rows = [
        build_downstream_candidate_report(
            asset,
            timeframe,
            days=args.days,
            cost_bps=args.cost_bps,
            candidate_names=tuple(args.candidates),
        )
        for asset, timeframe in requested
    ]
    payload = {
        "results": rows,
        "panel_summary": build_panel_summary(rows, candidate_names=tuple(args.candidates)),
    }
    text = json.dumps(payload, indent=2)
    print(text)

    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


if __name__ == "__main__":
    main()
