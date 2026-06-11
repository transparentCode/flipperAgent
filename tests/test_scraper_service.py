"""Tests for scraper service fetch and API surfaces."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.scraper_app.api.app import create_app
from apps.scraper_app.core.models import (
    ScrapeDataset,
    ScrapeIntent,
    ScrapeJobRecord,
    ScrapeJobStatus,
    ScrapeRequest,
    ScrapeResult,
    ScraperProvider,
    TradingViewSeriesField,
)
from apps.scraper_app.service.fetch_service import ScraperFetchService
from apps.scraper_app.service.job_service import ScraperJobService


class _FakeRedis:
    def __init__(self):
        self.hashes: dict[str, dict[str, str]] = {}
        self.values: dict[str, str] = {}

    async def hgetall(self, key: str):
        return self.hashes.get(key, {})

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        self.values[key] = value

    async def ping(self):
        return True


@pytest.mark.asyncio
async def test_fetch_service_tradingview_ohlcv_live(monkeypatch):
    frame = pd.DataFrame(
        [
            {"timestamp": 1, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 100.0},
            {"timestamp": 2, "open": 10.5, "high": 12.0, "low": 10.0, "close": 11.5, "volume": 120.0},
        ]
    )

    fake_interceptor = SimpleNamespace(
        get_historical_ohlcv=AsyncMock(return_value=frame),
        close=AsyncMock(),
    )
    monkeypatch.setattr(
        "apps.scraper_app.service.fetch_service.TradingViewInterceptor",
        lambda cookies_path=None: fake_interceptor,
    )

    service = ScraperFetchService()
    result = await service.fetch(
        ScrapeRequest(
            provider=ScraperProvider.TRADINGVIEW,
            dataset=ScrapeDataset.OHLCV,
            symbol="CRYPTOCAP:TOTAL3ES",
            timeframe="1h",
            limit=2,
        )
    )

    assert result.source == "live"
    assert result.summary["rows"] == 2
    assert result.summary["last_timestamp"] == 2
    assert result.data[1]["close"] == 11.5
    fake_interceptor.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_service_latest_tradingview_cache(monkeypatch):
    redis = _FakeRedis()
    redis.hashes["index:latest:TOTAL3ES"] = {
        "symbol": "TOTAL3ES",
        "timestamp": "1710000000000",
        "open": "1.0",
        "high": "2.0",
        "low": "0.5",
        "close": "1.5",
        "volume": "10.0",
        "fetched_at": "9999999999",
    }
    monkeypatch.setattr(
        "apps.scraper_app.service.fetch_service.tradingview_config.get",
        lambda key, default=None: "1h" if key == "tradingview.timeframe" else default,
    )

    service = ScraperFetchService(redis_client=redis)
    result = await service.get_latest_tradingview_ohlcv(
        symbol="CRYPTOCAP:TOTAL3ES",
        timeframe="1h",
        max_age_s=60,
    )

    assert result is not None
    assert result.source == "cache"
    assert result.data["symbol"] == "TOTAL3ES"
    assert result.data["close"] == 1.5


@pytest.mark.asyncio
async def test_job_service_dedupes_requests():
    fetch_service = ScraperFetchService()
    fetch_service.fetch = AsyncMock(
        return_value=ScrapeResult(
            provider=ScraperProvider.TRADINGVIEW,
            dataset=ScrapeDataset.OHLCV,
            intent=ScrapeIntent.ON_DEMAND_REFRESH,
            source="live",
            symbol="CRYPTOCAP:TOTAL3ES",
            timeframe="1h",
            data=[],
            summary={"rows": 0},
        )
    )
    jobs = ScraperJobService(fetch_service=fetch_service)
    request = ScrapeRequest(
        provider=ScraperProvider.TRADINGVIEW,
        dataset=ScrapeDataset.OHLCV,
        symbol="CRYPTOCAP:TOTAL3ES",
        timeframe="1h",
    )

    first = await jobs.submit(request)
    second = await jobs.submit(request)
    await asyncio.sleep(0)
    latest = await jobs.get(first.job_id)

    assert second.deduped is True
    assert latest is not None
    assert latest.status in {ScrapeJobStatus.RUNNING, ScrapeJobStatus.SUCCEEDED}
    await jobs.shutdown()


@pytest.mark.asyncio
async def test_job_service_completed_jobs_require_freshness_for_reuse():
    fetch_service = ScraperFetchService()
    fetch_service.fetch = AsyncMock(
        return_value=ScrapeResult(
            provider=ScraperProvider.TRADINGVIEW,
            dataset=ScrapeDataset.OHLCV,
            intent=ScrapeIntent.ON_DEMAND_REFRESH,
            source="live",
            symbol="CRYPTOCAP:TOTAL3ES",
            timeframe="1h",
            fetched_at=1000.0,
            data=[],
            summary={"rows": 0},
        )
    )
    jobs = ScraperJobService(fetch_service=fetch_service)
    request = ScrapeRequest(
        provider=ScraperProvider.TRADINGVIEW,
        dataset=ScrapeDataset.OHLCV,
        symbol="CRYPTOCAP:TOTAL3ES",
        timeframe="1h",
    )

    first = await jobs.submit(request)
    await asyncio.sleep(0)
    second = await jobs.submit(request)

    assert second.job_id == first.job_id
    assert second.deduped is False
    await jobs.shutdown()


@pytest.mark.asyncio
async def test_job_service_recovers_pending_jobs_from_redis():
    redis = _FakeRedis()
    fetch_service = ScraperFetchService()
    fetch_service.fetch = AsyncMock(
        return_value=ScrapeResult(
            provider=ScraperProvider.COINGLASS,
            dataset=ScrapeDataset.HEATMAP,
            intent=ScrapeIntent.ON_DEMAND_REFRESH,
            source="live",
            symbol="SOLUSDT",
            fetched_at=1234.0,
            data={"coin": "SOL"},
            summary={"shape": "runtime_helper"},
        )
    )
    request = ScrapeRequest(
        provider=ScraperProvider.COINGLASS,
        dataset=ScrapeDataset.HEATMAP,
        coin="SOL",
        symbol="SOLUSDT",
        short_name="SOLUSDT",
    )
    seed = ScrapeJobRecord(
        job_id="scrape-coinglass-heatmap-seeded",
        status=ScrapeJobStatus.RUNNING,
        request=request,
        created_at=1.0,
        updated_at=1.0,
    )
    redis.values["scraper:job:scrape-coinglass-heatmap-seeded"] = seed.model_dump_json()
    redis.scan_iter = lambda match=None: _fake_async_iter(
        ["scraper:job:scrape-coinglass-heatmap-seeded"]
    )
    redis.delete = AsyncMock()

    jobs = ScraperJobService(fetch_service=fetch_service, redis_client=redis)
    recovered = await jobs.recover_pending_jobs()
    await asyncio.sleep(0)
    latest = await jobs.get("scrape-coinglass-heatmap-seeded")

    assert recovered == 1
    assert latest is not None
    assert latest.status in {ScrapeJobStatus.RUNNING, ScrapeJobStatus.SUCCEEDED}
    await jobs.shutdown()


async def _fake_async_iter(values):
    for value in values:
        yield value


def test_scraper_api_endpoints():
    fetch_service = AsyncMock()
    fetch_service.get_latest_tradingview_ohlcv = AsyncMock(
        return_value=ScrapeResult(
            provider=ScraperProvider.TRADINGVIEW,
            dataset=ScrapeDataset.OHLCV,
            intent=ScrapeIntent.ON_DEMAND_REFRESH,
            source="cache",
            symbol="CRYPTOCAP:TOTAL3ES",
            timeframe="1h",
            data={"symbol": "TOTAL3ES", "timestamp": 1, "close": 1.5},
            summary={"rows": 1},
        )
    )
    fetch_service.get_latest_tradingview_series = AsyncMock(
        return_value=ScrapeResult(
            provider=ScraperProvider.TRADINGVIEW,
            dataset=ScrapeDataset.SERIES,
            intent=ScrapeIntent.ON_DEMAND_REFRESH,
            source="cache",
            symbol="SOLUSDT",
            timeframe="1h",
            data={"asset": "SOLUSDT", "field": "open_interest", "timestamp": 1, "value": 42.0},
            summary={"rows": 1},
        )
    )
    fetch_service.get_latest_coinglass_heatmap = AsyncMock(
        return_value=ScrapeResult(
            provider=ScraperProvider.COINGLASS,
            dataset=ScrapeDataset.HEATMAP,
            intent=ScrapeIntent.ON_DEMAND_REFRESH,
            source="cache",
            symbol="SOLUSDT",
            data={"coin": "SOL"},
            summary={"shape": "heatmap_payload"},
        )
    )
    fetch_service.fetch = AsyncMock(
        return_value=ScrapeResult(
            provider=ScraperProvider.TRADINGVIEW,
            dataset=ScrapeDataset.OHLCV,
            intent=ScrapeIntent.HISTORICAL_BACKFILL,
            source="live",
            symbol="CRYPTOCAP:TOTAL3ES",
            timeframe="1h",
            data=[],
            summary={"rows": 0},
        )
    )

    request_model = ScrapeRequest(
        provider=ScraperProvider.TRADINGVIEW,
        dataset=ScrapeDataset.OHLCV,
        symbol="CRYPTOCAP:TOTAL3ES",
        timeframe="1h",
    )
    job_record = ScrapeJobRecord(
        job_id="scrape-tradingview-ohlcv-test",
        status=ScrapeJobStatus.QUEUED,
        request=request_model,
        created_at=1.0,
        updated_at=1.0,
    )
    job_service = AsyncMock()
    job_service.submit = AsyncMock(return_value=job_record)
    job_service.get = AsyncMock(return_value=job_record)

    client = TestClient(
        create_app(fetch_service=fetch_service, job_service=job_service, redis_client=_FakeRedis())
    )

    response = client.get(
        "/latest/tradingview/ohlcv",
        params={"symbol": "CRYPTOCAP:TOTAL3ES", "timeframe": "1h"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["symbol"] == "TOTAL3ES"

    response = client.get(
        "/latest/tradingview/series",
        params={
            "asset": "SOLUSDT",
            "field": TradingViewSeriesField.OPEN_INTEREST.value,
            "timeframe": "1h",
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["value"] == 42.0

    response = client.get(
        "/latest/coinglass/heatmap",
        params={"exchange": "Binance", "short_name": "SOLUSDT"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["coin"] == "SOL"

    response = client.post("/fetch/sync", json=request_model.model_dump(mode="json"))
    assert response.status_code == 200
    assert response.json()["source"] == "live"

    response = client.post("/jobs", json=request_model.model_dump(mode="json"))
    assert response.status_code == 200
    assert response.json()["job_id"] == "scrape-tradingview-ohlcv-test"

    response = client.get("/jobs/scrape-tradingview-ohlcv-test")
    assert response.status_code == 200
    assert response.json()["status"] == "queued"


def test_scraper_api_sync_fetch_sanitizes_provider_errors():
    fetch_service = AsyncMock()
    fetch_service.fetch = AsyncMock(side_effect=RuntimeError("sensitive internals"))
    fetch_service.get_latest_tradingview_ohlcv = AsyncMock(return_value=None)
    fetch_service.get_latest_tradingview_series = AsyncMock(return_value=None)
    fetch_service.get_latest_coinglass_heatmap = AsyncMock(return_value=None)
    job_service = AsyncMock()

    client = TestClient(
        create_app(fetch_service=fetch_service, job_service=job_service, redis_client=_FakeRedis())
    )
    request_model = ScrapeRequest(
        provider=ScraperProvider.TRADINGVIEW,
        dataset=ScrapeDataset.OHLCV,
        symbol="CRYPTOCAP:TOTAL3ES",
        timeframe="1h",
    )

    response = client.post("/fetch/sync", json=request_model.model_dump(mode="json"))

    assert response.status_code == 502
    assert response.json()["detail"] == "Provider fetch failed. Check scraper-service logs for details."
