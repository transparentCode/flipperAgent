"""Shared fetch and cache access helpers for scraper consumers."""

from __future__ import annotations

import time
from typing import Any

import pandas as pd

from apps.scraper_app.core.models import (
    ScrapeDataset,
    ScrapeIntent,
    ScrapeRequest,
    ScrapeResult,
    ScraperProvider,
    TradingViewSeriesField,
)
from apps.scraper_app.providers.coinglass import CoinGlassHeatmapInterceptor
from apps.scraper_app.providers.tradingview import TradingViewInterceptor
from apps.scraper_app.providers.tradingview.config import config_manager as tradingview_config


class ScraperFetchService:
    """Shared interface used by the scraper API, workers, and CLI."""

    def __init__(self, *, redis_client: Any | None = None) -> None:
        self.redis_client = redis_client

    async def fetch(self, request: ScrapeRequest) -> ScrapeResult:
        """Fetch live data from the configured provider."""
        if request.provider == ScraperProvider.TRADINGVIEW:
            return await self._fetch_tradingview(request)
        return await self._fetch_coinglass(request)

    async def get_latest_tradingview_ohlcv(
        self,
        *,
        symbol: str,
        timeframe: str,
        max_age_s: int | None = None,
    ) -> ScrapeResult | None:
        self._ensure_redis()
        self._ensure_tradingview_cached_timeframe(timeframe)
        cache_key = f"index:latest:{symbol.split(':')[-1]}"
        raw = await self.redis_client.hgetall(cache_key)
        if not raw:
            return None

        fetched_at = self._coerce_float(raw.get("fetched_at"))
        if not self._is_fresh_enough(fetched_at, max_age_s):
            return None

        timestamp = self._coerce_int(raw.get("timestamp"))
        data = {
            "symbol": raw.get("symbol", symbol.split(":")[-1]),
            "timestamp": timestamp,
            "open": self._coerce_float(raw.get("open")),
            "high": self._coerce_float(raw.get("high")),
            "low": self._coerce_float(raw.get("low")),
            "close": self._coerce_float(raw.get("close")),
            "volume": self._coerce_float(raw.get("volume")),
        }
        return ScrapeResult(
            provider=ScraperProvider.TRADINGVIEW,
            dataset=ScrapeDataset.OHLCV,
            intent=ScrapeIntent.ON_DEMAND_REFRESH,
            source="cache",
            symbol=symbol,
            timeframe=timeframe,
            cache_key=cache_key,
            fetched_at=fetched_at,
            summary={"rows": 1, "latest_timestamp": timestamp},
            data=data,
        )

    async def get_latest_tradingview_series(
        self,
        *,
        asset: str,
        field: TradingViewSeriesField,
        timeframe: str,
        max_age_s: int | None = None,
    ) -> ScrapeResult | None:
        self._ensure_redis()
        self._ensure_tradingview_cached_timeframe(timeframe)
        suffix = "oi" if field == TradingViewSeriesField.OPEN_INTEREST else "funding"
        cache_key = f"derivatives:latest:{asset}:{suffix}"
        raw = await self.redis_client.hgetall(cache_key)
        if not raw:
            return None

        fetched_at = self._coerce_float(raw.get("fetched_at"))
        if not self._is_fresh_enough(fetched_at, max_age_s):
            return None

        timestamp = self._coerce_int(raw.get("timestamp"))
        data = {
            "asset": raw.get("symbol", asset),
            "field": field.value,
            "timestamp": timestamp,
            "value": self._coerce_float(raw.get("value")),
        }
        return ScrapeResult(
            provider=ScraperProvider.TRADINGVIEW,
            dataset=ScrapeDataset.SERIES,
            intent=ScrapeIntent.ON_DEMAND_REFRESH,
            source="cache",
            symbol=asset,
            timeframe=timeframe,
            cache_key=cache_key,
            fetched_at=fetched_at,
            summary={"rows": 1, "latest_timestamp": timestamp},
            data=data,
        )

    async def get_latest_coinglass_heatmap(
        self,
        *,
        exchange: str,
        short_name: str,
        max_age_s: int | None = None,
    ) -> ScrapeResult | None:
        self._ensure_redis()
        cache_key = f"coinglass:latest:liquidation_heatmap:{exchange}:{short_name}"
        raw = await self.redis_client.hgetall(cache_key)
        if not raw:
            return None

        fetched_at = self._coerce_float(raw.get("fetched_at"))
        if not self._is_fresh_enough(fetched_at, max_age_s):
            return None

        data = {
            "coin": raw.get("coin"),
            "exchange": raw.get("exchange"),
            "symbol": raw.get("symbol"),
            "market_type": raw.get("market_type"),
            "shape": raw.get("shape"),
            "response_url": raw.get("response_url"),
            "page_url": raw.get("page_url"),
            "captured_at_ms": self._coerce_int(raw.get("captured_at_ms")),
            "payload_json": raw.get("payload_json"),
        }
        return ScrapeResult(
            provider=ScraperProvider.COINGLASS,
            dataset=ScrapeDataset.HEATMAP,
            intent=ScrapeIntent.ON_DEMAND_REFRESH,
            source="cache",
            symbol=raw.get("symbol", short_name),
            cache_key=cache_key,
            fetched_at=fetched_at,
            summary={"shape": raw.get("shape"), "captured_at_ms": data["captured_at_ms"]},
            data=data,
        )

    async def _fetch_tradingview(self, request: ScrapeRequest) -> ScrapeResult:
        interceptor = TradingViewInterceptor(cookies_path=request.cookies_path)
        try:
            if request.dataset == ScrapeDataset.OHLCV:
                frame = await interceptor.get_historical_ohlcv(
                    request.symbol,
                    request.timeframe,
                    limit=request.limit,
                )
            else:
                frame = await interceptor.get_historical_series(
                    request.symbol,
                    request.timeframe,
                    limit=request.limit,
                )
        finally:
            await interceptor.close()

        return ScrapeResult(
            provider=request.provider,
            dataset=request.dataset,
            intent=request.intent,
            source="live",
            symbol=request.symbol,
            timeframe=request.timeframe,
            fetched_at=time.time(),
            summary=self._summarize_frame(frame),
            data=self._frame_to_records(frame),
        )

    async def _fetch_coinglass(self, request: ScrapeRequest) -> ScrapeResult:
        interceptor = CoinGlassHeatmapInterceptor(cookies_path=request.cookies_path)
        try:
            envelope = await interceptor.fetch_heatmap(
                coin=request.coin or "",
                market_type=request.market_type,
                exchange=request.exchange,
                symbol=request.symbol,
                short_name=request.short_name,
            )
        finally:
            await interceptor.close()

        if envelope is None:
            raise RuntimeError("No CoinGlass payload captured")

        return ScrapeResult(
            provider=request.provider,
            dataset=request.dataset,
            intent=request.intent,
            source="live",
            symbol=envelope.get("symbol", request.symbol),
            fetched_at=time.time(),
            summary={
                "shape": envelope.get("shape"),
                "captured_at_ms": envelope.get("captured_at_ms"),
            },
            data=envelope,
        )

    @staticmethod
    def _frame_to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
        if frame is None or frame.empty:
            return []
        return frame.to_dict(orient="records")

    @staticmethod
    def _summarize_frame(frame: pd.DataFrame) -> dict[str, Any]:
        if frame is None or frame.empty:
            return {"rows": 0}
        summary: dict[str, Any] = {"rows": int(len(frame))}
        if "timestamp" in frame.columns:
            summary["first_timestamp"] = int(frame["timestamp"].iloc[0])
            summary["last_timestamp"] = int(frame["timestamp"].iloc[-1])
        return summary

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        return float(value)

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        return int(float(value))

    @staticmethod
    def _is_fresh_enough(fetched_at: float | None, max_age_s: int | None) -> bool:
        if fetched_at is None or max_age_s is None:
            return True
        return (time.time() - fetched_at) <= max_age_s

    def _ensure_redis(self) -> None:
        if self.redis_client is None:
            raise RuntimeError("Valkey client unavailable for cached latest lookups.")

    @staticmethod
    def _ensure_tradingview_cached_timeframe(timeframe: str) -> None:
        configured = tradingview_config.get("tradingview.timeframes", None)
        if configured is None:
            configured = [tradingview_config.get("tradingview.timeframe", "1h")]
        if isinstance(configured, str):
            configured = [configured]
        configured = [str(item) for item in configured]
        if len(configured) != 1:
            raise ValueError(
                "Cached TradingView latest endpoints currently support exactly one configured timeframe."
            )
        if timeframe != configured[0]:
            raise ValueError(
                f"Cached TradingView latest data is only available for configured timeframe '{configured[0]}'."
            )
