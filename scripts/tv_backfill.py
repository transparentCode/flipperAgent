#!/usr/bin/env python
"""Backfill TradingView OHLCV or single-value series through direct WebSocket.

Examples:
    # 2 years of 1h CRYPTOCAP index data
    PYTHONPATH=src .venv/bin/python scripts/tv_backfill.py \
        --symbols CRYPTOCAP:BTC.D CRYPTOCAP:TOTAL2 CRYPTOCAP:TOTAL3 \
        --timeframe 1h --years 2 --kind ohlcv

    # 2 years of 1h derivative series if TradingView exposes enough history
    PYTHONPATH=src .venv/bin/python scripts/tv_backfill.py \
        --symbols BINANCE:BNBUSDTPERP_OI BINANCE:BNBUSDT.P_FR \
        --timeframe 1h --years 2 --kind series --output-dir data/tv_derivatives
"""

from __future__ import annotations

import argparse
import json
import random
import re
import string
import time
from pathlib import Path
from typing import Any

import pandas as pd
import websocket

# ---------------------------------------------------------------------------
# TradingView WebSocket protocol helpers
# ---------------------------------------------------------------------------

TV_WS_URL = "wss://data.tradingview.com/socket.io/websocket"
TV_ORIGIN = "https://www.tradingview.com"
DEFAULT_INDEX_SYMBOLS = ["CRYPTOCAP:BTC.D", "CRYPTOCAP:TOTAL2", "CRYPTOCAP:TOTAL3"]

_MSG_RE = re.compile(r"~m~(\d+)~m~")
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


def _rand_session(prefix: str = "cs") -> str:
    """Generate a random session ID matching TV format."""
    chars = string.ascii_lowercase + string.digits
    return prefix + "_" + "".join(random.choices(chars, k=12))


def _encode_msg(msg: dict | str) -> str:
    """Encode a message in TradingView ~m~ protocol."""
    payload = json.dumps(msg) if isinstance(msg, dict) else msg
    return f"~m~{len(payload)}~m~{payload}"


def _decode_msgs(raw: str) -> list:
    """Decode all ~m~ framed messages from a raw WebSocket frame."""
    results = []
    pos = 0
    while pos < len(raw):
        m = _MSG_RE.match(raw, pos)
        if not m:
            break
        length = int(m.group(1))
        start = m.end()
        payload = raw[start : start + length]
        pos = start + length
        try:
            parsed = json.loads(payload)
            results.append(parsed)
        except (json.JSONDecodeError, TypeError):
            if payload.startswith("~h~"):
                results.append({"_heartbeat": payload})
    return results


def _extract_bars(
    messages: list[dict],
    allowed_series: set[str] | None = None,
) -> list[dict]:
    """Extract OHLCV bars from parsed TV messages."""
    bars = []
    for values in _iter_series_values(messages, allowed_series=allowed_series):
        if len(values) >= 5:
            bars.append(
                {
                    "timestamp": int(values[0]),
                    "open": float(values[1]),
                    "high": float(values[2]),
                    "low": float(values[3]),
                    "close": float(values[4]),
                    "volume": float(values[5]) if len(values) > 5 else 0.0,
                }
            )
    return bars


def _extract_single_series(
    messages: list[dict],
    allowed_series: set[str] | None = None,
) -> list[dict]:
    """Extract single-value points like open interest or funding rate."""
    points = []
    for values in _iter_series_values(messages, allowed_series=allowed_series):
        if len(values) >= 5:
            points.append({"timestamp": int(values[0]), "value": float(values[4])})
        elif len(values) >= 2:
            points.append({"timestamp": int(values[0]), "value": float(values[1])})
    return points


def _iter_series_values(
    messages: list[dict],
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


def fetch_tv_history(
    symbol: str,
    exchange: str = "CRYPTOCAP",
    interval: str = "60",
    n_bars: int = 5000,
    timeout: int = 30,
) -> pd.DataFrame:
    """Fetch historical OHLCV from TradingView via direct WebSocket."""
    full_symbol = _full_symbol(symbol, exchange)
    rows = _fetch_tv_series_rows(
        full_symbol=full_symbol,
        interval=interval,
        n_bars=n_bars,
        timeout=timeout,
        kind="ohlcv",
    )
    if not rows:
        print(f"  WARNING: No bars received for {full_symbol}")
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    return _rows_to_frame(rows)


def fetch_tv_single_series(
    symbol: str,
    exchange: str = "BINANCE",
    interval: str = "60",
    n_bars: int = 5000,
    timeout: int = 30,
) -> pd.DataFrame:
    """Fetch a single-value TradingView series via direct WebSocket."""
    full_symbol = _full_symbol(symbol, exchange)
    rows = _fetch_tv_series_rows(
        full_symbol=full_symbol,
        interval=interval,
        n_bars=n_bars,
        timeout=timeout,
        kind="series",
    )
    if not rows:
        print(f"  WARNING: No series points received for {full_symbol}")
        return pd.DataFrame(columns=["timestamp", "value"])
    return _rows_to_frame(rows)


def _fetch_tv_series_rows(
    *,
    full_symbol: str,
    interval: str,
    n_bars: int,
    timeout: int,
    kind: str,
) -> list[dict[str, Any]]:
    chart_session = _rand_session("cs")
    rows: list[dict[str, Any]] = []
    extractor = _extract_bars if kind == "ohlcv" else _extract_single_series

    ws = websocket.create_connection(
        TV_WS_URL,
        origin=TV_ORIGIN,
        header=[
            "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ],
        timeout=timeout,
    )

    try:
        ws.send(_encode_msg({"m": "set_auth_token", "p": ["unauthorized_user_token"]}))
        ws.send(_encode_msg({"m": "chart_create_session", "p": [chart_session, ""]}))
        ws.send(
            _encode_msg(
                {
                    "m": "resolve_symbol",
                    "p": [
                        chart_session,
                        "sds_sym_1",
                        f'={{"symbol":"{full_symbol}","adjustment":"splits","session":"extended"}}',
                    ],
                }
            )
        )
        ws.send(
            _encode_msg(
                {
                    "m": "create_series",
                    "p": [
                        chart_session,
                        "sds_1",
                        "s1",
                        "sds_sym_1",
                        interval,
                        int(n_bars),
                        "",
                    ],
                }
            )
        )

        deadline = time.monotonic() + timeout
        consecutive_empty = 0
        while time.monotonic() < deadline:
            try:
                ws.settimeout(max(1, deadline - time.monotonic()))
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                break

            if not raw:
                consecutive_empty += 1
                if consecutive_empty > 5:
                    break
                continue
            consecutive_empty = 0

            msgs = _decode_msgs(raw)
            for msg in msgs:
                if isinstance(msg, dict) and "_heartbeat" in msg:
                    hb = msg["_heartbeat"]
                    ws.send(f"~m~{len(hb)}~m~{hb}")

            rows.extend(extractor(msgs))

            if any(isinstance(msg, dict) and msg.get("m") == "series_completed" for msg in msgs):
                break
    finally:
        ws.close()

    return rows


def _rows_to_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    return df


def check_gaps(df: pd.DataFrame, expected_interval_seconds: int = 3600) -> list[str]:
    """Check for significant timestamp gaps in fetched TV data."""
    if len(df) < 2:
        return ["Insufficient data to check gaps"]

    gaps = []
    ts = df["timestamp"].values
    for i in range(1, len(ts)):
        delta = int(ts[i] - ts[i - 1])
        if delta > expected_interval_seconds * 3:
            gap_hours = delta / 3600
            dt1 = pd.Timestamp(ts[i - 1], unit="s", tz="UTC")
            dt2 = pd.Timestamp(ts[i], unit="s", tz="UTC")
            gaps.append(f"  Gap: {dt1} -> {dt2} ({gap_hours:.1f}h)")
    return gaps


def _full_symbol(symbol: str, default_exchange: str) -> str:
    return symbol if ":" in symbol else f"{default_exchange}:{symbol}"


def _split_symbol(symbol: str, default_exchange: str) -> tuple[str, str]:
    if ":" not in symbol:
        return symbol, default_exchange
    exchange, name = symbol.split(":", 1)
    return name, exchange


def _safe_filename(symbol: str, timeframe: str, kind: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", symbol.replace(":", "_"))
    return f"{safe}_{timeframe}_{kind}.csv"


def _interval_for_timeframe(timeframe: str, interval: str | None) -> str:
    if interval:
        return interval
    if timeframe not in _TIMEFRAME_TO_INTERVAL:
        raise ValueError(f"Unsupported timeframe {timeframe!r}; pass --interval explicitly")
    return _TIMEFRAME_TO_INTERVAL[timeframe]


def _seconds_for_timeframe(timeframe: str, interval: str | None = None) -> int:
    if timeframe in _TIMEFRAME_SECONDS:
        return _TIMEFRAME_SECONDS[timeframe]
    if interval and interval.isdigit():
        return int(interval) * 60
    raise ValueError(f"Unsupported timeframe {timeframe!r}; cannot infer gap interval")


def _bars_for_years(years: float, timeframe: str, interval: str | None = None) -> int:
    seconds = _seconds_for_timeframe(timeframe, interval)
    return int(round(years * 365 * 86400 / seconds))


def _default_output_dir(kind: str) -> Path:
    return Path("data/tv_derivatives" if kind == "series" else "data/tv_index")


def _summarize(symbol: str, df: pd.DataFrame, expected_seconds: int) -> None:
    dt_min = df["datetime"].min()
    dt_max = df["datetime"].max()
    days = (dt_max - dt_min).total_seconds() / 86400
    print(f"  Bars: {len(df)}")
    print(f"  Range: {dt_min:%Y-%m-%d %H:%M} -> {dt_max:%Y-%m-%d %H:%M} ({days:.1f} days)")
    gaps = check_gaps(df, expected_seconds)
    if gaps:
        print(f"  Gaps found ({len(gaps)}):")
        for gap in gaps[:5]:
            print(gap)
        if len(gaps) > 5:
            print(f"  ... and {len(gaps) - 5} more")
    else:
        print("  No significant gaps")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill TradingView data via direct WebSocket.")
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--default-exchange", default="CRYPTOCAP")
    parser.add_argument("--kind", choices=["ohlcv", "series"], default="ohlcv")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--interval", default=None, help="TradingView interval override, e.g. 60, 30, D")
    parser.add_argument("--n-bars", type=int, default=None)
    parser.add_argument("--years", type=float, default=None)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--output-dir", type=str, default=None)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    interval = _interval_for_timeframe(args.timeframe, args.interval)
    if args.n_bars is not None:
        n_bars = args.n_bars
    elif args.years is not None:
        n_bars = _bars_for_years(args.years, args.timeframe, interval)
    else:
        n_bars = 5000
    expected_seconds = _seconds_for_timeframe(args.timeframe, interval)
    output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir(args.kind)
    output_dir.mkdir(parents=True, exist_ok=True)
    symbols = args.symbols or DEFAULT_INDEX_SYMBOLS

    print("=" * 60)
    print("TradingView Data Backfill")
    print("=" * 60)
    print(f"Kind: {args.kind} | timeframe={args.timeframe} interval={interval} n_bars={n_bars}")

    for raw_symbol in symbols:
        symbol, exchange = _split_symbol(raw_symbol, args.default_exchange)
        full_symbol = _full_symbol(symbol, exchange)
        print(f"\nFetching {full_symbol} ({args.timeframe}, {n_bars} bars)...")
        if args.kind == "series":
            df = fetch_tv_single_series(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                n_bars=n_bars,
                timeout=args.timeout,
            )
        else:
            df = fetch_tv_history(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                n_bars=n_bars,
                timeout=args.timeout,
            )

        if df.empty:
            print(f"  FAILED: No data for {full_symbol}")
            continue

        csv_path = output_dir / _safe_filename(full_symbol, args.timeframe, args.kind)
        df.to_csv(csv_path, index=False)
        _summarize(full_symbol, df, expected_seconds)
        print(f"  Saved -> {csv_path}")

    print("\n" + "=" * 60)
    print("Backfill complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
