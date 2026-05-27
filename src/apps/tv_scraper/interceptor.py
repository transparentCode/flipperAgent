"""TradingView stealth WebSocket interceptor for proprietary index data."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import pandas as pd

from apps.ingestion_app.adapters.base import BaseExchangeAdapter
from libs.common.config import ConfigManager
from libs.common.logging.logger_utils import bind_logger
from libs.common.enums import SystemComponent

logger = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)

# TradingView ~m~ protocol parser
_MSG_PATTERN = re.compile(r"~m~(\d+)~m~(.+)", re.DOTALL)


def parse_tv_messages(raw: str) -> list[dict[str, Any]]:
    """Parse TradingView WebSocket ~m~ framed messages into JSON dicts."""
    results = []
    pos = 0
    while pos < len(raw):
        match = _MSG_PATTERN.match(raw, pos)
        if not match:
            break
        length = int(match.group(1))
        payload = match.group(2)[:length]
        pos = match.end(1) + 3 + length  # skip past ~m~{len}~m~{payload}
        try:
            parsed = json.loads(payload)
            if isinstance(parsed, dict):
                results.append(parsed)
        except (json.JSONDecodeError, TypeError):
            pass
    return results


def extract_ohlcv_from_tv_response(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract OHLCV bars from TradingView timescale_update or du messages."""
    bars = []
    for msg in messages:
        # TradingView sends chart data in 'timescale_update' or 'du' messages
        m_type = msg.get("m")
        if m_type not in ("timescale_update", "du"):
            continue

        params = msg.get("p", [])
        for param in params:
            if not isinstance(param, dict):
                continue
            # Navigate to the series data
            for series_key, series_data in param.items():
                if series_key.startswith("sds_") or series_key.startswith("s"):
                    s_data = series_data if isinstance(series_data, dict) else {}
                    s_list = (
                        s_data.get("s", [])
                        if isinstance(s_data, dict)
                        else series_data
                        if isinstance(series_data, list)
                        else []
                    )
                    if isinstance(s_list, list):
                        for candle in s_list:
                            v = candle.get("v", []) if isinstance(candle, dict) else candle
                            if isinstance(v, (list, tuple)) and len(v) >= 6:
                                bars.append(
                                    {
                                        "timestamp": int(v[0]) * 1000,  # TV sends seconds
                                        "open": float(v[1]),
                                        "high": float(v[2]),
                                        "low": float(v[3]),
                                        "close": float(v[4]),
                                        "volume": float(v[5]) if len(v) > 5 else 0.0,
                                    }
                                )
    return bars


class TradingViewInterceptor(BaseExchangeAdapter):
    """Stealth WebSocket interceptor for TradingView chart data.

    Uses Scrapling to launch a headless browser, navigate to a TradingView chart,
    intercept the WebSocket traffic, and extract OHLCV data.
    """

    def __init__(self, cookies_path: str | None = None, proxy_url: str | None = None):
        config = ConfigManager()
        self.cookies_path = cookies_path or config.get(
            "tradingview.cookies_path", "secrets/tv_cookies.json"
        )
        self.proxy_url = proxy_url
        self._session = None

    async def get_historical_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int = None,
        until: int = None,
        limit: int = None,
    ) -> pd.DataFrame:
        """Fetch historical OHLCV for a TradingView symbol.

        Args:
            symbol: TradingView symbol (e.g., 'CRYPTOCAP:TOTAL2')
            timeframe: Candle timeframe (e.g., '1h', '4h', '1D')
            since: Not used (TV determines available history)
            until: Not used
            limit: Not used

        Returns:
            DataFrame with columns [timestamp, open, high, low, close, volume]
        """
        try:
            from scrapling import StealthyFetcher
        except ImportError:
            logger.error(
                "Scrapling is not installed. Install with: pip install 'scrapling[all]'"
            )
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        intercepted_messages: list[str] = []

        # Map timeframe to TV resolution
        tv_resolution = self._map_timeframe(timeframe)

        # Build chart URL
        chart_url = f"https://www.tradingview.com/chart/?symbol={symbol}&interval={tv_resolution}"

        logger.info(f"Fetching TV data for {symbol} ({timeframe}) via stealth interception...")

        try:
            fetcher = StealthyFetcher()

            cookies = self._load_cookies()

            page = await fetcher.async_fetch(
                chart_url,
                headless=True,
                network_idle=True,
                wait_selector="div.chart-container",
                timeout=30000,
                cookies=cookies,
            )

            # Extract WS messages from page network log
            for entry in getattr(page, "network_log", []):
                if "data.tradingview.com" in str(entry.get("url", "")):
                    data = entry.get("data", "")
                    if isinstance(data, str) and "~m~" in data:
                        intercepted_messages.append(data)

        except Exception as e:
            logger.error(f"Stealth fetch failed for {symbol}: {e}", exc_info=True)
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        # Parse intercepted messages
        all_bars = []
        for raw_msg in intercepted_messages:
            parsed = parse_tv_messages(raw_msg)
            bars = extract_ohlcv_from_tv_response(parsed)
            all_bars.extend(bars)

        if not all_bars:
            logger.warning(f"No OHLCV data extracted for {symbol}")
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        df = pd.DataFrame(all_bars)
        df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

        logger.info(f"Extracted {len(df)} bars for {symbol}")
        return df

    def _load_cookies(self) -> list[dict] | None:
        """Load TradingView session cookies from JSON file."""
        try:
            import os

            if os.path.exists(self.cookies_path):
                with open(self.cookies_path) as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load TV cookies from {self.cookies_path}: {e}")
        return None

    @staticmethod
    def _map_timeframe(timeframe: str) -> str:
        """Map standard timeframe notation to TradingView resolution."""
        mapping = {
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
        return mapping.get(timeframe, "60")
