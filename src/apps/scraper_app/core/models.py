"""Shared request/response models for scraper service interfaces."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ScraperProvider(str, Enum):
    TRADINGVIEW = "tradingview"
    COINGLASS = "coinglass"


class ScrapeDataset(str, Enum):
    OHLCV = "ohlcv"
    SERIES = "series"
    HEATMAP = "heatmap"


class ScrapeIntent(str, Enum):
    REALTIME_CLOSE = "realtime_close"
    HISTORICAL_BACKFILL = "historical_backfill"
    ON_DEMAND_REFRESH = "on_demand_refresh"
    RETRY_RECOVERY = "retry_recovery"


class ScrapePriority(str, Enum):
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class TradingViewSeriesField(str, Enum):
    OPEN_INTEREST = "open_interest"
    FUNDING_RATE = "funding_rate"


class ScrapeRequest(BaseModel):
    provider: ScraperProvider
    dataset: ScrapeDataset
    intent: ScrapeIntent = ScrapeIntent.ON_DEMAND_REFRESH
    priority: ScrapePriority = ScrapePriority.NORMAL
    symbol: str | None = None
    timeframe: str | None = None
    limit: int | None = Field(default=None, ge=1)
    coin: str | None = None
    market_type: str = "pair"
    exchange: str = "Binance"
    short_name: str | None = None
    cookies_path: str | None = None
    freshness_s: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_request(self) -> "ScrapeRequest":
        if self.provider == ScraperProvider.TRADINGVIEW:
            if self.dataset not in {ScrapeDataset.OHLCV, ScrapeDataset.SERIES}:
                raise ValueError("TradingView requests support only 'ohlcv' or 'series' datasets.")
            if not self.symbol:
                raise ValueError("TradingView requests require 'symbol'.")
            if not self.timeframe:
                raise ValueError("TradingView requests require 'timeframe'.")
        elif self.provider == ScraperProvider.COINGLASS:
            if self.dataset != ScrapeDataset.HEATMAP:
                raise ValueError("CoinGlass requests support only the 'heatmap' dataset.")
            if not self.coin:
                raise ValueError("CoinGlass requests require 'coin'.")
        return self


class ScrapeResult(BaseModel):
    provider: ScraperProvider
    dataset: ScrapeDataset
    intent: ScrapeIntent
    source: str
    symbol: str | None = None
    timeframe: str | None = None
    cache_key: str | None = None
    fetched_at: float | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    data: Any


class ScrapeJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ScrapeJobRecord(BaseModel):
    job_id: str
    status: ScrapeJobStatus
    request: ScrapeRequest
    created_at: float
    updated_at: float
    deduped: bool = False
    error: str | None = None
    result_key: str | None = None
    result: ScrapeResult | None = None


class HealthResponse(BaseModel):
    status: str
    valkey_available: bool
