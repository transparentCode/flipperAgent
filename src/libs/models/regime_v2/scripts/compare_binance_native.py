"""Fetch Binance USD-M futures candles and run the RegimeV2 comparison harness.

This script uses the repository's native Binance adapter instead of a custom
HTTP fetcher.

Example:
    PYTHONPATH=src python -m libs.models.regime_v2.scripts.compare_binance_native \
        --symbol BTCUSDT --timeframe 1h --limit 1000 --skip-legacy
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pandas as pd

from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter
from libs.models.regime_v2.evaluation import RegimeComparisonConfig, run_regime_comparison


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = asyncio.run(_run(args))

    summary_text = json.dumps(_json_safe(result.summary), indent=2, sort_keys=True)
    print(summary_text)

    if args.output_json:
        Path(args.output_json).write_text(summary_text + "\n")
    if args.output_csv:
        result.frame.to_csv(args.output_csv)
    return 0


async def _run(args: argparse.Namespace):
    df = await fetch_binance_native_ohlcv(
        symbol=args.symbol,
        timeframe=args.timeframe,
        limit=args.limit,
        since=_parse_millis(args.since),
        until=_parse_millis(args.until),
    )
    return run_regime_comparison(
        df,
        asset=args.symbol,
        timeframe=args.timeframe,
        config=RegimeComparisonConfig(
            horizon_bars=args.horizon_bars,
            include_legacy_regime=not args.skip_legacy,
            include_regime_classification=not args.skip_regime_classification,
        ),
    )


async def fetch_binance_native_ohlcv(
    *,
    symbol: str,
    timeframe: str,
    limit: int | None = None,
    since: int | None = None,
    until: int | None = None,
) -> pd.DataFrame:
    """Fetch and normalize OHLCV using BinanceNativeAdapter."""
    adapter = BinanceNativeAdapter()
    raw = await adapter.get_historical_ohlcv(
        symbol.upper(),
        timeframe,
        since=since,
        until=until,
        limit=limit,
    )
    return normalize_binance_native_ohlcv(raw)


def normalize_binance_native_ohlcv(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize BinanceNativeAdapter output for RegimeV2.

    Adapter output keeps ``timestamp`` in milliseconds.  The comparison harness
    expects OHLCV columns and benefits from a datetime index.
    """
    required = ["timestamp", "open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in raw.columns]
    if missing:
        raise ValueError(f"BinanceNativeAdapter output missing columns: {missing}")

    df = raw.loc[:, required].copy()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    df = df.dropna(subset=required)
    df["open_time"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms", utc=True)
    df = df.set_index("open_time").sort_index()
    return df[["open", "high", "low", "close", "volume"]]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Binance candles and compare RegimeV2.")
    parser.add_argument("--symbol", required=True, help="Binance USD-M futures symbol, e.g. BTCUSDT.")
    parser.add_argument("--timeframe", required=True, help="Binance interval, e.g. 30m, 1h, 4h.")
    parser.add_argument("--limit", type=int, default=1000, help="Kline limit. Binance usually caps this at 1500.")
    parser.add_argument("--since", default=None, help="Start time: epoch ms or ISO datetime.")
    parser.add_argument("--until", default=None, help="End time: epoch ms or ISO datetime.")
    parser.add_argument("--horizon-bars", type=int, default=12)
    parser.add_argument("--skip-legacy", action="store_true", help="Do not evaluate legacy libs.regime.")
    parser.add_argument("--skip-regime-classification", action="store_true", help="Do not evaluate RegimeClassification.")
    parser.add_argument("--output-json", default=None, help="Optional path for summary JSON.")
    parser.add_argument("--output-csv", default=None, help="Optional path for full comparison dataframe.")
    return parser.parse_args(argv)


def _parse_millis(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    if value.isdigit():
        return int(value)
    dt = pd.to_datetime(value, utc=True)
    return int(dt.timestamp() * 1000)


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
