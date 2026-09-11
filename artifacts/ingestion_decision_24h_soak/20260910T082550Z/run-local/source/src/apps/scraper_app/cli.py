"""CLI entrypoints for offline scraper research fetches."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import pandas as pd

from apps.scraper_app.core.models import ScrapeDataset, ScrapeRequest, ScraperProvider
from apps.scraper_app.service import ScraperFetchService


def build_parser() -> argparse.ArgumentParser:
    """Build the scraper research CLI parser."""
    parser = argparse.ArgumentParser(
        prog="flipper-scraper-fetch",
        description="Fetch data from browser scrapers for offline research.",
    )
    subparsers = parser.add_subparsers(dest="provider", required=True)

    coinglass_parser = subparsers.add_parser("coinglass", help="Fetch CoinGlass heatmap data")
    coinglass_parser.add_argument("--coin", required=True)
    coinglass_parser.add_argument("--market-type", default="pair")
    coinglass_parser.add_argument("--exchange", default="Binance")
    coinglass_parser.add_argument("--symbol")
    coinglass_parser.add_argument("--short-name")
    coinglass_parser.add_argument("--cookies-path")
    coinglass_parser.add_argument("--output-path")

    tv_parser = subparsers.add_parser("tradingview", help="Fetch TradingView data")
    tv_subparsers = tv_parser.add_subparsers(dest="tv_mode", required=True)

    tv_ohlcv = tv_subparsers.add_parser("ohlcv", help="Fetch TradingView OHLCV candles")
    tv_ohlcv.add_argument("--symbol", required=True)
    tv_ohlcv.add_argument("--timeframe", default="1h")
    tv_ohlcv.add_argument("--limit", type=int)
    tv_ohlcv.add_argument("--cookies-path")
    tv_ohlcv.add_argument("--output-path")

    tv_series = tv_subparsers.add_parser("series", help="Fetch TradingView single-value series")
    tv_series.add_argument("--symbol", required=True)
    tv_series.add_argument("--timeframe", default="1h")
    tv_series.add_argument("--limit", type=int)
    tv_series.add_argument("--cookies-path")
    tv_series.add_argument("--output-path")

    return parser


async def _run_coinglass(args: argparse.Namespace) -> int:
    service = ScraperFetchService()
    result = await service.fetch(
        ScrapeRequest(
            provider=ScraperProvider.COINGLASS,
            dataset=ScrapeDataset.HEATMAP,
            coin=args.coin,
            market_type=args.market_type,
            exchange=args.exchange,
            symbol=args.symbol,
            short_name=args.short_name,
            cookies_path=args.cookies_path,
        )
    )
    payload = json.dumps(result.data, indent=2)
    _write_output(payload, args.output_path)
    return 0


async def _run_tradingview_ohlcv(args: argparse.Namespace) -> int:
    service = ScraperFetchService()
    result = await service.fetch(
        ScrapeRequest(
            provider=ScraperProvider.TRADINGVIEW,
            dataset=ScrapeDataset.OHLCV,
            symbol=args.symbol,
            timeframe=args.timeframe,
            limit=args.limit,
            cookies_path=args.cookies_path,
        )
    )
    frame = pd.DataFrame(result.data)
    _write_frame_output(frame, args.output_path)
    return 0


async def _run_tradingview_series(args: argparse.Namespace) -> int:
    service = ScraperFetchService()
    result = await service.fetch(
        ScrapeRequest(
            provider=ScraperProvider.TRADINGVIEW,
            dataset=ScrapeDataset.SERIES,
            symbol=args.symbol,
            timeframe=args.timeframe,
            limit=args.limit,
            cookies_path=args.cookies_path,
        )
    )
    frame = pd.DataFrame(result.data)
    _write_frame_output(frame, args.output_path)
    return 0


def _write_output(content: str, output_path: str | None) -> None:
    """Write text output to stdout or a file."""
    if output_path:
        Path(output_path).write_text(content)
        return
    print(content)


def _write_frame_output(frame: pd.DataFrame, output_path: str | None) -> None:
    """Write DataFrame output for research usage."""
    if output_path:
        path = Path(output_path)
        if path.suffix.lower() == ".csv":
            frame.to_csv(path, index=False)
            return
        path.write_text(frame.to_json(orient="records", indent=2))
        return

    print(frame.to_json(orient="records", indent=2))


async def run_args(args: argparse.Namespace) -> int:
    """Dispatch parsed CLI arguments."""
    if args.provider == "coinglass":
        return await _run_coinglass(args)
    if args.provider == "tradingview" and args.tv_mode == "ohlcv":
        return await _run_tradingview_ohlcv(args)
    if args.provider == "tradingview" and args.tv_mode == "series":
        return await _run_tradingview_series(args)
    raise RuntimeError(f"Unsupported scraper command: {args}")


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for scraper research fetches."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(run_args(args))


if __name__ == "__main__":
    raise SystemExit(main())
