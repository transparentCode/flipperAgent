"""CLI for the RegimeV2 offline comparison harness.

Example:
    python -m libs.models.regime_v2.scripts.compare_regime_v2 \
        --csv data/BTCUSDT_1h.csv --asset BTCUSDT --timeframe 1h
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from libs.models.regime_v2.evaluation import RegimeComparisonConfig, run_regime_comparison


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare RegimeV2 against optional regime baselines.")
    parser.add_argument("--csv", required=True, help="CSV containing OHLCV columns.")
    parser.add_argument("--asset", required=True, help="Asset symbol, e.g. BTCUSDT.")
    parser.add_argument("--timeframe", required=True, help="Timeframe, e.g. 1h or 4h.")
    parser.add_argument("--timestamp-column", default=None, help="Optional timestamp column to use as index.")
    parser.add_argument("--horizon-bars", type=int, default=12)
    parser.add_argument("--skip-legacy", action="store_true", help="Do not evaluate legacy libs.regime.")
    parser.add_argument("--skip-regime-classification", action="store_true", help="Do not evaluate RegimeClassification.")
    parser.add_argument("--output-json", default=None, help="Optional path for summary JSON.")
    parser.add_argument("--output-csv", default=None, help="Optional path for full comparison dataframe.")
    args = parser.parse_args(argv)

    df = _load_csv(args.csv, timestamp_column=args.timestamp_column)
    result = run_regime_comparison(
        df,
        asset=args.asset,
        timeframe=args.timeframe,
        config=RegimeComparisonConfig(
            horizon_bars=args.horizon_bars,
            include_legacy_regime=not args.skip_legacy,
            include_regime_classification=not args.skip_regime_classification,
        ),
    )

    summary_text = json.dumps(_json_safe(result.summary), indent=2, sort_keys=True)
    print(summary_text)

    if args.output_json:
        Path(args.output_json).write_text(summary_text + "\n")
    if args.output_csv:
        result.frame.to_csv(args.output_csv)
    return 0


def _load_csv(path: str, *, timestamp_column: str | None = None) -> pd.DataFrame:
    df = pd.read_csv(path)
    if timestamp_column:
        df[timestamp_column] = pd.to_datetime(df[timestamp_column], utc=True)
        df = df.set_index(timestamp_column)
    return df


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):
        return value.item()
    return value


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
