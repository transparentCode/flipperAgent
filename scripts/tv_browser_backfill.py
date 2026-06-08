#!/usr/bin/env python
"""Browser-scroll TradingView backfill using Patchright and optional cookies.

This research/offline utility mimics manual chart panning better than the direct
WebSocket script. It opens a TradingView chart, captures chart WebSocket frames,
then repeatedly pans left to ask the UI for older bars.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from apps.tv_scraper.interceptor import parse_tv_messages  # noqa: E402

CHART_BASE_URL = "https://www.tradingview.com/chart/"
DEFAULT_COOKIES_PATH = "secrets/tv_cookies.json"
DEFAULT_INDEX_SYMBOLS = ["CRYPTOCAP:BTC.D", "CRYPTOCAP:TOTAL2", "CRYPTOCAP:TOTAL3"]
_TIMEFRAME_TO_INTERVAL = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "2h": "120",
    "4h": "240",
    "1d": "D",
    "1D": "D",
    "1w": "W",
    "1W": "W",
}
_TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "1d": 86400,
    "1D": 86400,
    "1w": 604800,
    "1W": 604800,
}


def extract_ohlcv_rows(
    messages: list[dict[str, Any]],
    allowed_series: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Extract OHLCV rows from TradingView messages in seconds timestamps."""
    rows: list[dict[str, Any]] = []
    for values in _iter_series_values(messages, allowed_series=allowed_series):
        if len(values) >= 5:
            rows.append(
                {
                    "timestamp": int(values[0]),
                    "open": float(values[1]),
                    "high": float(values[2]),
                    "low": float(values[3]),
                    "close": float(values[4]),
                    "volume": float(values[5]) if len(values) > 5 else 0.0,
                }
            )
    return rows


def extract_series_rows(
    messages: list[dict[str, Any]],
    allowed_series: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Extract single-value rows, using close for OHLC-shaped derivative series."""
    rows: list[dict[str, Any]] = []
    for values in _iter_series_values(messages, allowed_series=allowed_series):
        if len(values) >= 5:
            rows.append({"timestamp": int(values[0]), "value": float(values[4])})
        elif len(values) >= 2:
            rows.append({"timestamp": int(values[0]), "value": float(values[1])})
    return rows


def _iter_series_values(
    messages: list[dict[str, Any]],
    allowed_series: set[str] | None = None,
) -> list[list[Any]]:
    values: list[list[Any]] = []
    allowed = allowed_series or {"sds_1"}
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("m") not in {"timescale_update", "du"}:
            continue
        params = msg.get("p", [])
        for param in params:
            if not isinstance(param, dict):
                continue
            for series_key, val in param.items():
                if str(series_key) not in allowed:
                    continue
                if not isinstance(val, dict):
                    continue
                series = val.get("s", [])
                if not isinstance(series, list):
                    continue
                for candle in series:
                    raw = candle.get("v", []) if isinstance(candle, dict) else []
                    if isinstance(raw, (list, tuple)):
                        values.append(list(raw))
    return values


def rows_to_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame = (
        frame.drop_duplicates(subset=["timestamp"])
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    frame["datetime"] = pd.to_datetime(frame["timestamp"], unit="s", utc=True)
    return frame


def check_gaps(frame: pd.DataFrame, expected_seconds: int) -> list[str]:
    if len(frame) < 2:
        return ["Insufficient data to check gaps"]
    gaps: list[str] = []
    timestamps = frame["timestamp"].astype(int).to_numpy()
    for idx in range(1, len(timestamps)):
        delta = int(timestamps[idx] - timestamps[idx - 1])
        if delta > expected_seconds * 3:
            start = pd.Timestamp(timestamps[idx - 1], unit="s", tz="UTC")
            end = pd.Timestamp(timestamps[idx], unit="s", tz="UTC")
            gaps.append(f"  Gap: {start} -> {end} ({delta / 3600:.1f}h)")
    return gaps


def load_cookies(path: str) -> list[dict[str, Any]]:
    cookie_path = Path(path)
    if not cookie_path.exists():
        return []
    cookies = json.loads(cookie_path.read_text(encoding="utf-8"))
    if not isinstance(cookies, list):
        raise ValueError(f"Cookie file must contain a JSON list: {path}")
    sanitized = []
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        if "name" not in cookie or "value" not in cookie:
            continue
        row = dict(cookie)
        if row.get("domain", "").startswith("."):
            row["domain"] = row["domain"][1:]
        sanitized.append(row)
    return sanitized


def timeframe_interval(timeframe: str, interval: str | None) -> str:
    if interval:
        return interval
    if timeframe not in _TIMEFRAME_TO_INTERVAL:
        raise ValueError(f"Unsupported timeframe {timeframe!r}; pass --interval")
    return _TIMEFRAME_TO_INTERVAL[timeframe]


def timeframe_seconds(timeframe: str, interval: str | None = None) -> int:
    if timeframe in _TIMEFRAME_SECONDS:
        return _TIMEFRAME_SECONDS[timeframe]
    if interval and interval.isdigit():
        return int(interval) * 60
    raise ValueError(f"Unsupported timeframe {timeframe!r}; cannot infer seconds")


def target_bars_for_years(years: float, timeframe: str, interval: str | None = None) -> int:
    return int(round(years * 365 * 86400 / timeframe_seconds(timeframe, interval)))


def chart_url(symbol: str, interval: str) -> str:
    return f"{CHART_BASE_URL}?symbol={symbol}&interval={interval}"


def safe_filename(symbol: str, timeframe: str, kind: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", symbol.replace(":", "_"))
    return f"{safe}_{timeframe}_{kind}_browser.csv"


async def browser_backfill_symbol(
    *,
    browser_context: Any,
    symbol: str,
    timeframe: str,
    interval: str,
    kind: str,
    target_bars: int,
    target_since_ts: int | None,
    max_scrolls: int,
    settle_seconds: float,
    scroll_pixels: int,
    pan_method: str,
) -> pd.DataFrame:
    page = await browser_context.new_page()
    raw_messages: list[str] = []
    extractor = extract_ohlcv_rows if kind == "ohlcv" else extract_series_rows
    try:
        def on_websocket(ws: Any) -> None:
            if "tradingview.com" not in ws.url:
                return

            def on_frame(data: Any) -> None:
                payload = data if isinstance(data, str) else str(data)
                if "~m~" in payload:
                    raw_messages.append(payload)

            ws.on("framereceived", on_frame)

        page.on("websocket", on_websocket)
        await page.goto(chart_url(symbol, interval), wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(int(settle_seconds * 1000))

        best_count = 0
        stale_scrolls = 0
        frame = _frame_from_raw(raw_messages, extractor)
        _print_progress(symbol, "initial", frame)

        for scroll_idx in range(max_scrolls):
            if _target_reached(frame, target_bars, target_since_ts):
                break
            await _pan_left(page, scroll_pixels, pan_method)
            await page.wait_for_timeout(int(settle_seconds * 1000))
            frame = _frame_from_raw(raw_messages, extractor)
            count = len(frame)
            if count <= best_count:
                stale_scrolls += 1
            else:
                stale_scrolls = 0
                best_count = count
            if scroll_idx == 0 or (scroll_idx + 1) % 10 == 0 or stale_scrolls >= 5:
                _print_progress(symbol, f"scroll={scroll_idx + 1}", frame)
            if stale_scrolls >= 8:
                break
        return frame
    finally:
        with contextlib.suppress(Exception):
            await page.close()


def _frame_from_raw(raw_messages: list[str], extractor: Any) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for raw in raw_messages:
        rows.extend(extractor(parse_tv_messages(raw), allowed_series={"sds_1"}))
    return rows_to_frame(rows)


def _target_reached(frame: pd.DataFrame, target_bars: int, target_since_ts: int | None) -> bool:
    if frame.empty:
        return False
    if len(frame) >= target_bars:
        return True
    return target_since_ts is not None and int(frame["timestamp"].min()) <= target_since_ts


async def _pan_left(page: Any, pixels: int, pan_method: str = "drag") -> None:
    viewport = page.viewport_size or {"width": 1920, "height": 1080}
    width = int(viewport.get("width", 1920))
    height = int(viewport.get("height", 1080))
    y = int(height * 0.55)
    await page.mouse.move(int(width * 0.35), y)
    await page.mouse.down()
    drag_end = min(int(width * 0.35) + abs(pixels), int(width * 0.85))
    await page.mouse.move(drag_end, y, steps=18)
    await page.mouse.up()
    if pan_method == "drag":
        return
    await page.mouse.move(int(width * 0.50), y)
    if pan_method in {"wheel", "both"}:
        await page.mouse.wheel(-abs(pixels), 0)
    if pan_method == "both":
        await page.keyboard.down("Shift")
        await page.mouse.wheel(0, -abs(pixels))
        await page.keyboard.up("Shift")


def _print_progress(symbol: str, label: str, frame: pd.DataFrame) -> None:
    if frame.empty:
        print(f"  {symbol} {label}: no rows", flush=True)
        return
    start = frame["datetime"].min()
    end = frame["datetime"].max()
    print(f"  {symbol} {label}: rows={len(frame)} range={start} -> {end}", flush=True)


def summarize_and_save(
    *,
    symbol: str,
    frame: pd.DataFrame,
    output_dir: Path,
    timeframe: str,
    kind: str,
    expected_seconds: int,
) -> None:
    if frame.empty:
        print(f"  FAILED: no data for {symbol}")
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / safe_filename(symbol, timeframe, kind)
    frame.to_csv(output_path, index=False)
    start = frame["datetime"].min()
    end = frame["datetime"].max()
    days = (end - start).total_seconds() / 86400
    print(f"  Bars: {len(frame)}")
    print(f"  Range: {start:%Y-%m-%d %H:%M} -> {end:%Y-%m-%d %H:%M} ({days:.1f} days)")
    gaps = check_gaps(frame, expected_seconds)
    if gaps:
        print(f"  Gaps found ({len(gaps)}):")
        for gap in gaps[:5]:
            print(gap)
        if len(gaps) > 5:
            print(f"  ... and {len(gaps) - 5} more")
    else:
        print("  No significant gaps")
    print(f"  Saved -> {output_path}")


async def run(args: argparse.Namespace) -> None:
    try:
        from patchright.async_api import async_playwright
    except ImportError as exc:
        raise SystemExit("patchright is required. Install project optional tv-scraper deps.") from exc

    interval = timeframe_interval(args.timeframe, args.interval)
    target_bars = args.n_bars or target_bars_for_years(args.years, args.timeframe, interval)
    target_since_ts = (
        None
        if args.n_bars is not None
        else int(time.time() - args.years * 365 * 86400)
        if args.years
        else None
    )
    expected_seconds = timeframe_seconds(args.timeframe, interval)
    output_dir = Path(args.output_dir)
    symbols = args.symbols or DEFAULT_INDEX_SYMBOLS
    cookies = load_cookies(args.cookies_path)

    print("=" * 60)
    print("TradingView Browser Scroll Backfill")
    print("=" * 60)
    print(
        f"kind={args.kind} timeframe={args.timeframe} interval={interval} "
        f"target_bars={target_bars} cookies_loaded={len(cookies)}"
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=not args.headful,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = await browser.new_context(
            viewport={"width": args.viewport_width, "height": args.viewport_height},
            user_agent=args.user_agent,
        )
        if cookies:
            await context.add_cookies(cookies)
        try:
            for symbol in symbols:
                print(f"\nFetching {symbol} with browser scroll...")
                frame = await browser_backfill_symbol(
                    browser_context=context,
                    symbol=symbol,
                    timeframe=args.timeframe,
                    interval=interval,
                    kind=args.kind,
                    target_bars=target_bars,
                    target_since_ts=target_since_ts,
                    max_scrolls=args.max_scrolls,
                    settle_seconds=args.settle_seconds,
                    scroll_pixels=args.scroll_pixels,
                    pan_method=args.pan_method,
                )
                summarize_and_save(
                    symbol=symbol,
                    frame=frame,
                    output_dir=output_dir,
                    timeframe=args.timeframe,
                    kind=args.kind,
                    expected_seconds=expected_seconds,
                )
        finally:
            await context.close()
            await browser.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill TradingView by scrolling chart left in a browser.")
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--kind", choices=["ohlcv", "series"], default="ohlcv")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--interval", default=None)
    parser.add_argument("--years", type=float, default=2.0)
    parser.add_argument("--n-bars", type=int, default=None)
    parser.add_argument("--output-dir", default="data/tv_browser")
    parser.add_argument("--cookies-path", default=DEFAULT_COOKIES_PATH)
    parser.add_argument("--max-scrolls", type=int, default=120)
    parser.add_argument("--settle-seconds", type=float, default=1.0)
    parser.add_argument("--scroll-pixels", type=int, default=900)
    parser.add_argument("--pan-method", choices=["drag", "wheel", "both"], default="drag")
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--viewport-width", type=int, default=1920)
    parser.add_argument("--viewport-height", type=int, default=1080)
    parser.add_argument(
        "--user-agent",
        default=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
    )
    return parser.parse_args()


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
