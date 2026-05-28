#!/usr/bin/env python
"""Fetch 90+ days of 1h OHLCV data for BTC.D, TOTAL2, TOTAL3 from TradingView.

Uses TradingView's public WebSocket protocol directly — no browser automation.
Saves CSV files to data/tv_index/.

Usage:
    cd /Users/aloobhujia/flipperAgent
    PYTHONPATH=src .venv/bin/python scripts/tv_backfill.py
"""

from __future__ import annotations

import json
import os
import random
import re
import string
import time
from pathlib import Path

import pandas as pd
import websocket

# ---------------------------------------------------------------------------
# TradingView WebSocket protocol helpers
# ---------------------------------------------------------------------------

TV_WS_URL = "wss://data.tradingview.com/socket.io/websocket"
TV_ORIGIN = "https://www.tradingview.com"

_MSG_RE = re.compile(r"~m~(\d+)~m~")


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
            # Heartbeat or non-JSON message
            if payload.startswith("~h~"):
                results.append({"_heartbeat": payload})
            pass
    return results


def _extract_bars(messages: list[dict]) -> list[dict]:
    """Extract OHLCV bars from parsed TV messages (timescale_update or du)."""
    bars = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        m_type = msg.get("m")
        if m_type not in ("timescale_update", "du"):
            continue
        params = msg.get("p", [])
        for param in params:
            if not isinstance(param, dict):
                continue
            for key, val in param.items():
                if not isinstance(val, dict):
                    continue
                s_list = val.get("s", [])
                if not isinstance(s_list, list):
                    continue
                for candle in s_list:
                    v = candle.get("v", []) if isinstance(candle, dict) else []
                    if isinstance(v, (list, tuple)) and len(v) >= 5:
                        bars.append(
                            {
                                "timestamp": int(v[0]),
                                "open": float(v[1]),
                                "high": float(v[2]),
                                "low": float(v[3]),
                                "close": float(v[4]),
                                "volume": float(v[5]) if len(v) > 5 else 0.0,
                            }
                        )
    return bars


def fetch_tv_history(
    symbol: str,
    exchange: str = "CRYPTOCAP",
    interval: str = "60",
    n_bars: int = 5000,
    timeout: int = 30,
) -> pd.DataFrame:
    """Fetch historical OHLCV from TradingView via direct WebSocket.

    Parameters
    ----------
    symbol : str
        TradingView symbol name (e.g. "BTC.D", "TOTAL2").
    exchange : str
        Exchange prefix (e.g. "CRYPTOCAP").
    interval : str
        TradingView resolution ("60" = 1h, "240" = 4h, "D" = daily).
    n_bars : int
        Number of bars to request.
    timeout : int
        Max seconds to wait for data.

    Returns
    -------
    pd.DataFrame with columns [timestamp, open, high, low, close, volume].
    """
    chart_session = _rand_session("cs")
    quote_session = _rand_session("qs")
    full_symbol = f"{exchange}:{symbol}"

    all_bars: list[dict] = []

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
        # 1. Auth
        ws.send(_encode_msg({"m": "set_auth_token", "p": ["unauthorized_user_token"]}))

        # 2. Create chart session
        ws.send(_encode_msg({"m": "chart_create_session", "p": [chart_session, ""]}))

        # 3. Resolve symbol
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

        # 4. Create series with requested bar count
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
                        n_bars,
                        "",
                    ],
                }
            )
        )

        # 5. Collect responses
        deadline = time.monotonic() + timeout
        got_data = False
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

            # Handle heartbeats
            for msg in msgs:
                if isinstance(msg, dict) and "_heartbeat" in msg:
                    # Echo heartbeat back
                    hb = msg["_heartbeat"]
                    ws.send(f"~m~{len(hb)}~m~{hb}")

            bars = _extract_bars(msgs)
            if bars:
                all_bars.extend(bars)
                got_data = True

            # Check for series_completed
            for msg in msgs:
                if isinstance(msg, dict) and msg.get("m") == "series_completed":
                    # All data received
                    deadline = 0  # exit loop

    finally:
        ws.close()

    if not all_bars:
        print(f"  WARNING: No bars received for {full_symbol}")
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(all_bars)
    # TV timestamps are in seconds; convert to datetime for CSV
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    return df


def check_gaps(df: pd.DataFrame, expected_interval_h: int = 1) -> list[str]:
    """Check for significant gaps in the data."""
    if len(df) < 2:
        return ["Insufficient data to check gaps"]

    gaps = []
    ts = df["timestamp"].values
    expected_delta = expected_interval_h * 3600

    for i in range(1, len(ts)):
        delta = ts[i] - ts[i - 1]
        if delta > expected_delta * 3:  # Gap > 3x expected
            gap_hours = delta / 3600
            dt1 = pd.Timestamp(ts[i - 1], unit="s", tz="UTC")
            dt2 = pd.Timestamp(ts[i], unit="s", tz="UTC")
            gaps.append(f"  Gap: {dt1} → {dt2} ({gap_hours:.1f}h)")

    return gaps


def main():
    output_dir = Path("data/tv_index")
    output_dir.mkdir(parents=True, exist_ok=True)

    symbols = [
        ("BTC.D", "CRYPTOCAP"),
        ("TOTAL2", "CRYPTOCAP"),
        ("TOTAL3", "CRYPTOCAP"),
    ]

    print("=" * 60)
    print("TradingView Index Data Backfill")
    print("=" * 60)

    for symbol, exchange in symbols:
        print(f"\nFetching {exchange}:{symbol} (1h, 5000 bars)...")
        df = fetch_tv_history(
            symbol=symbol,
            exchange=exchange,
            interval="60",
            n_bars=5000,
            timeout=30,
        )

        if df.empty:
            print(f"  FAILED: No data for {symbol}")
            continue

        # Save to CSV
        csv_path = output_dir / f"{symbol.replace('.', '_')}_1h.csv"
        df.to_csv(csv_path, index=False)

        # Summary
        dt_min = df["datetime"].min()
        dt_max = df["datetime"].max()
        days = (dt_max - dt_min).total_seconds() / 86400

        print(f"  Bars: {len(df)}")
        print(f"  Range: {dt_min:%Y-%m-%d %H:%M} → {dt_max:%Y-%m-%d %H:%M} ({days:.1f} days)")

        gaps = check_gaps(df)
        if gaps:
            print(f"  Gaps found ({len(gaps)}):")
            for g in gaps[:5]:
                print(g)
            if len(gaps) > 5:
                print(f"  ... and {len(gaps) - 5} more")
        else:
            print("  No significant gaps")

        print(f"  Saved → {csv_path}")

    print("\n" + "=" * 60)
    print("Backfill complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
