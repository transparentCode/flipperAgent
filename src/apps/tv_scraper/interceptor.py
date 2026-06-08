"""TradingView stealth WebSocket interceptor for proprietary index data."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
from pathlib import Path
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


def _iter_primary_series_values(
    messages: list[dict[str, Any]],
    allowed_series: set[str] | None = None,
) -> list[list[Any]]:
    """Yield values from the primary chart series only.

    TradingView may send auxiliary/study series in the same WebSocket frame.
    Keeping the default to ``sds_1`` prevents old or synthetic series from
    being mixed into the requested symbol history.
    """
    values: list[list[Any]] = []
    allowed = allowed_series or {"sds_1"}
    for msg in messages:
        m_type = msg.get("m")
        if m_type not in ("timescale_update", "du"):
            continue

        params = msg.get("p", [])
        for param in params:
            if not isinstance(param, dict):
                continue
            for series_key, series_data in param.items():
                if str(series_key) not in allowed:
                    continue
                s_data = series_data if isinstance(series_data, dict) else {}
                s_list = (
                    s_data.get("s", [])
                    if isinstance(s_data, dict)
                    else series_data
                    if isinstance(series_data, list)
                    else []
                )
                if not isinstance(s_list, list):
                    continue
                for candle in s_list:
                    v = candle.get("v", []) if isinstance(candle, dict) else candle
                    if isinstance(v, (list, tuple)):
                        values.append(list(v))
    return values


def extract_ohlcv_from_tv_response(
    messages: list[dict[str, Any]],
    allowed_series: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Extract OHLCV bars from TradingView timescale_update or du messages."""
    bars = []
    for v in _iter_primary_series_values(messages, allowed_series=allowed_series):
        if len(v) >= 6:
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


def extract_single_series_from_tv_response(
    messages: list[dict[str, Any]],
    allowed_series: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Extract single-value time series from TradingView messages.

    Funding is usually [timestamp, value]. Some OI symbols arrive as
    [timestamp, open, high, low, close], where the close is the usable value.
    """
    bars = []
    for v in _iter_primary_series_values(messages, allowed_series=allowed_series):
        if len(v) == 2:
            value = float(v[1])
        elif len(v) == 5:
            value = float(v[4])
        else:
            continue
        bars.append({"timestamp": int(v[0]) * 1000, "value": value})
    return bars


class TradingViewInterceptor(BaseExchangeAdapter):
    """Stealth WebSocket interceptor for TradingView chart data.

    Uses patchright to launch a headless Chromium browser, navigate to a TradingView chart,
    intercept the WebSocket traffic, and extract OHLCV data.
    """

    def __init__(self, cookies_path: str | None = None, proxy_url: str | None = None):
        config = ConfigManager()
        self.cookies_path = cookies_path or config.get(
            "tradingview.cookies_path", "secrets/tv_cookies.json"
        )
        self.proxy_url = proxy_url or config.get("tradingview.proxy_url")
        self._session = None
        self._config = config
        self._browser_lock = asyncio.Lock()
        self._cached_cookies: list[dict[str, Any]] | None = None
        self._cached_cookies_mtime_ns: int | None = None
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._context: Any | None = None

    async def get_historical_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int = None,
        until: int = None,
        limit: int = None,
    ) -> pd.DataFrame:
        """Fetch historical OHLCV for a TradingView symbol.

        Uses Patchright (Playwright-compatible) to launch a stealth browser,
        navigate to a TradingView chart, and intercept WebSocket frames
        carrying ``~m~`` encoded OHLCV data.

        Args:
            symbol: TradingView symbol (e.g., 'CRYPTOCAP:TOTAL2')
            timeframe: Candle timeframe (e.g., '1h', '4h', '1D')
            since: Not used (TV determines available history)
            until: Not used
            limit: Not used

        Returns:
            DataFrame with columns [timestamp, open, high, low, close, volume]
        """
        return (await self.get_historical_ohlcv_batch([symbol], timeframe)).get(
            symbol, self._empty_frame()
        )

    async def get_historical_ohlcv_batch(
        self, symbols: list[str], timeframe: str
    ) -> dict[str, pd.DataFrame]:
        """Fetch multiple TradingView symbols through one browser session."""
        results = {symbol: self._empty_frame() for symbol in symbols}
        if not symbols:
            return results

        try:
            context = await self._get_or_create_context()
        except Exception as e:
            logger.error(
                f"TradingView browser session failed for {symbols}: {e}",
                exc_info=True,
            )
            await self.close()
            return results

        try:
            fetch_delay = self._config.get("tradingview.fetch_delay_seconds", 2)
            for idx, symbol in enumerate(symbols):
                results[symbol] = await self._fetch_symbol_ohlcv(
                    context, symbol, timeframe
                )
                if idx < len(symbols) - 1 and fetch_delay > 0:
                    await asyncio.sleep(fetch_delay)
        except Exception as e:
            logger.error(
                f"TradingView symbol fetch failed for {symbols}: {e}",
                exc_info=True,
            )
            await self.close()

        return results

    async def get_historical_series(
        self,
        symbol: str,
        timeframe: str,
        since: int = None,
        until: int = None,
        limit: int = None,
    ) -> pd.DataFrame:
        """Fetch a single-value time series (OI, funding rate, etc.) from TradingView.

        Returns DataFrame with columns [timestamp, value].
        """
        result = await self.get_historical_series_batch([symbol], timeframe)
        return result.get(symbol, pd.DataFrame(columns=["timestamp", "value"]))

    async def get_historical_series_batch(
        self, symbols: list[str], timeframe: str,
    ) -> dict[str, pd.DataFrame]:
        """Fetch multiple single-value TradingView series in one browser session."""
        results = {s: pd.DataFrame(columns=["timestamp", "value"]) for s in symbols}
        if not symbols:
            return results

        try:
            context = await self._get_or_create_context()
        except Exception as e:
            logger.error(
                f"TradingView browser session failed for series {symbols}: {e}",
                exc_info=True,
            )
            await self.close()
            return results

        try:
            fetch_delay = self._config.get("tradingview.fetch_delay_seconds", 2)
            for idx, symbol in enumerate(symbols):
                df = await self._fetch_symbol_series(context, symbol, timeframe)
                if df is not None and not df.empty:
                    results[symbol] = df
                if idx < len(symbols) - 1 and fetch_delay > 0:
                    await asyncio.sleep(fetch_delay)
        except Exception as e:
            logger.error(
                f"TradingView series fetch failed for {symbols}: {e}",
                exc_info=True,
            )
            await self.close()

        return results

    async def _get_or_create_context(self) -> Any:
        if self._context is not None:
            return self._context

        async with self._browser_lock:
            if self._context is not None:
                return self._context

            try:
                from patchright.async_api import async_playwright
            except ImportError:
                logger.error(
                    "Patchright is not installed. Install with: pip install patchright"
                )
                raise

            self._playwright = await async_playwright().start()
            launch_kwargs: dict[str, Any] = {
                "headless": True,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            }
            if self.proxy_url:
                launch_kwargs["proxy"] = {"server": self.proxy_url}

            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
            self._context = await self._browser.new_context(
                viewport={
                    "width": self._config.get("tradingview.viewport_width", 1920),
                    "height": self._config.get("tradingview.viewport_height", 1080),
                },
                user_agent=self._config.get(
                    "tradingview.user_agent",
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36",
                ),
            )
            await self._apply_cookies(self._context)
            return self._context

    async def _apply_cookies(self, context: Any) -> None:
        cookies = self._load_cookies()
        if not cookies:
            return

        pw_cookies = []
        for c in cookies:
            cookie = dict(c)
            if "domain" in cookie and cookie["domain"].startswith("."):
                cookie["domain"] = cookie["domain"][1:]
            pw_cookies.append(cookie)
        await context.add_cookies(pw_cookies)

    async def _fetch_symbol_ohlcv(
        self, context: Any, symbol: str, timeframe: str
    ) -> pd.DataFrame:
        intercepted_messages: list[str] = []
        chart_url = self._build_chart_url(symbol, timeframe)
        page = None

        logger.info(f"Fetching TV data for {symbol} ({timeframe}) via WS interception...")

        try:
            page = await context.new_page()

            def on_websocket(ws):
                if "tradingview.com" in ws.url:

                    def on_frame(data):
                        payload = data if isinstance(data, str) else str(data)
                        if "~m~" in payload:
                            intercepted_messages.append(payload)

                    ws.on("framereceived", on_frame)

            page.on("websocket", on_websocket)

            await page.goto(
                chart_url,
                wait_until="domcontentloaded",
                timeout=self._config.get("tradingview.page_load_timeout_ms", 30000),
            )

            timeout_s = self._config.get("tradingview.ws_intercept_timeout_seconds", 15)
            poll_s = self._config.get("tradingview.ws_poll_interval_seconds", 0.5)
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                has_data = any(
                    "timescale_update" in m or '"du"' in m
                    for m in intercepted_messages
                )
                if has_data:
                    break
                await asyncio.sleep(poll_s)
        except Exception as e:
            logger.error(f"WS interception failed for {symbol}: {e}", exc_info=True)
            return self._empty_frame()
        finally:
            await self._close_quietly(page, "page")

        return self._messages_to_frame(symbol, intercepted_messages)

    def _messages_to_frame(
        self, symbol: str, intercepted_messages: list[str]
    ) -> pd.DataFrame:
        all_bars = []
        for raw_msg in intercepted_messages:
            parsed = parse_tv_messages(raw_msg)
            bars = extract_ohlcv_from_tv_response(parsed)
            all_bars.extend(bars)

        if not all_bars:
            logger.warning(f"No OHLCV data extracted for {symbol}")
            return self._empty_frame()

        df = pd.DataFrame(all_bars)
        df = (
            df.drop_duplicates(subset=["timestamp"])
            .sort_values("timestamp")
            .reset_index(drop=True)
        )

        logger.info(f"Extracted {len(df)} bars for {symbol}")
        return df

    async def _fetch_symbol_series(
        self, context: Any, symbol: str, timeframe: str
    ) -> pd.DataFrame:
        """Fetch a single-value series (OI, funding rate) via WS interception."""
        intercepted_messages: list[str] = []
        chart_url = self._build_chart_url(symbol, timeframe)
        page = None

        logger.info(f"Fetching TV series for {symbol} ({timeframe}) via WS interception...")

        try:
            page = await context.new_page()

            def on_websocket(ws):
                if "tradingview.com" in ws.url:

                    def on_frame(data):
                        payload = data if isinstance(data, str) else str(data)
                        if "~m~" in payload:
                            intercepted_messages.append(payload)

                    ws.on("framereceived", on_frame)

            page.on("websocket", on_websocket)

            await page.goto(
                chart_url,
                wait_until="domcontentloaded",
                timeout=self._config.get("tradingview.page_load_timeout_ms", 30000),
            )

            timeout_s = self._config.get("tradingview.ws_intercept_timeout_seconds", 15)
            poll_s = self._config.get("tradingview.ws_poll_interval_seconds", 0.5)
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                has_data = any(
                    "timescale_update" in m or '"du"' in m
                    for m in intercepted_messages
                )
                if has_data:
                    break
                await asyncio.sleep(poll_s)
        except Exception as e:
            logger.error(f"WS interception failed for series {symbol}: {e}", exc_info=True)
            return pd.DataFrame(columns=["timestamp", "value"])
        finally:
            await self._close_quietly(page, "page")

        return self._messages_to_series_frame(symbol, intercepted_messages)

    def _messages_to_series_frame(
        self, symbol: str, intercepted_messages: list[str]
    ) -> pd.DataFrame:
        all_bars = []
        for raw_msg in intercepted_messages:
            parsed = parse_tv_messages(raw_msg)
            bars = extract_single_series_from_tv_response(parsed)
            all_bars.extend(bars)

        if not all_bars:
            logger.warning(f"No series data extracted for {symbol}")
            return pd.DataFrame(columns=["timestamp", "value"])

        df = pd.DataFrame(all_bars)
        df = (
            df.drop_duplicates(subset=["timestamp"])
            .sort_values("timestamp")
            .reset_index(drop=True)
        )

        logger.info(f"Extracted {len(df)} series points for {symbol}")
        return df

    def _build_chart_url(self, symbol: str, timeframe: str) -> str:
        tv_resolution = self._map_timeframe(timeframe)
        chart_base = self._config.get(
            "tradingview.chart_base_url", "https://www.tradingview.com/chart/"
        )
        return f"{chart_base}?symbol={symbol}&interval={tv_resolution}"

    @staticmethod
    def _empty_frame() -> pd.DataFrame:
        return pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )

    @staticmethod
    async def _close_quietly(resource: Any, label: str) -> None:
        if resource is None:
            return
        with contextlib.suppress(Exception):
            await resource.close()

    def _load_cookies(self) -> list[dict] | None:
        """Load TradingView session cookies from JSON file."""
        cookie_path = Path(self.cookies_path)
        try:
            if not cookie_path.exists():
                self._cached_cookies = None
                self._cached_cookies_mtime_ns = None
                return None

            stat = cookie_path.stat()
            if (
                self._cached_cookies is not None
                and self._cached_cookies_mtime_ns == stat.st_mtime_ns
            ):
                return [dict(cookie) for cookie in self._cached_cookies]

            with open(cookie_path, encoding="utf-8") as f:
                cookies = json.load(f)

            self._cached_cookies = [dict(cookie) for cookie in cookies]
            self._cached_cookies_mtime_ns = stat.st_mtime_ns
            return [dict(cookie) for cookie in self._cached_cookies]
        except Exception as e:
            self._cached_cookies = None
            self._cached_cookies_mtime_ns = None
            logger.warning(f"Failed to load TV cookies from {self.cookies_path}: {e}")
        return None

    async def close(self) -> None:
        async with self._browser_lock:
            context = self._context
            browser = self._browser
            playwright = self._playwright
            self._context = None
            self._browser = None
            self._playwright = None

            await self._close_quietly(context, "browser context")
            await self._close_quietly(browser, "browser")
            if playwright is not None:
                stop = getattr(playwright, "stop", None)
                if callable(stop):
                    with contextlib.suppress(Exception):
                        await stop()

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
