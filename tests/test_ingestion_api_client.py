from __future__ import annotations

import pytest

from apps.scraper_app.core.models import (
    ScrapeDataset,
    ScrapeIntent,
    ScrapeJobStatus,
    ScrapeRequest,
    ScraperProvider,
)
from libs.common.clients.ingestion_api import IngestionApiClient, IngestionApiClientError


class _FakeResponse:
    def __init__(self, *, status: int, payload: dict, reason: str = "OK") -> None:
        self.status = status
        self._payload = payload
        self.reason = reason

    async def json(self, content_type=None):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.requests: list[dict] = []

    def request(self, method, url, params=None, json=None):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "params": params,
                "json": json,
            }
        )
        return self.response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_ingestion_api_client_scraper_fetch(monkeypatch):
    session = _FakeSession(
        _FakeResponse(
            status=200,
            payload={
                "provider": "tradingview",
                "dataset": "ohlcv",
                "intent": "on_demand_refresh",
                "source": "live",
                "symbol": "CRYPTOCAP:TOTAL3ES",
                "timeframe": "1h",
                "summary": {"rows": 1},
                "data": [{"timestamp": 1, "close": 2.0}],
            },
        )
    )
    monkeypatch.setattr(
        "libs.common.clients.ingestion_api.aiohttp.ClientSession",
        lambda timeout=None: session,
    )

    client = IngestionApiClient(base_url="http://ingestion-api")
    result = await client.scraper_fetch(
        ScrapeRequest(
            provider=ScraperProvider.TRADINGVIEW,
            dataset=ScrapeDataset.OHLCV,
            symbol="CRYPTOCAP:TOTAL3ES",
            timeframe="1h",
        )
    )

    assert result.source == "live"
    assert result.summary["rows"] == 1
    assert result.data[0]["close"] == 2.0
    assert session.requests[0]["url"] == "http://ingestion-api/ingestion/scraper/fetch"


@pytest.mark.asyncio
async def test_ingestion_api_client_scraper_job_flow(monkeypatch):
    request = ScrapeRequest(
        provider=ScraperProvider.COINGLASS,
        dataset=ScrapeDataset.HEATMAP,
        coin="SOL",
        symbol="SOLUSDT",
        short_name="SOLUSDT",
    )
    create_session = _FakeSession(
        _FakeResponse(
            status=200,
            payload={
                "job_id": "scrape-tv-job-1",
                "status": "queued",
                "request": request.model_dump(mode="json"),
                "created_at": 1.0,
                "updated_at": 1.0,
                "deduped": False,
                "error": None,
                "result_key": None,
                "result": None,
            },
        )
    )
    get_session = _FakeSession(
        _FakeResponse(
            status=200,
            payload={
                "job_id": "scrape-tv-job-1",
                "status": "succeeded",
                "request": request.model_dump(mode="json"),
                "created_at": 1.0,
                "updated_at": 2.0,
                "deduped": False,
                "error": None,
                "result_key": "scraper:job:scrape-tv-job-1",
                "result": {
                    "provider": "coinglass",
                    "dataset": "heatmap",
                    "intent": "on_demand_refresh",
                    "source": "cache",
                    "symbol": "SOLUSDT",
                    "timeframe": None,
                    "cache_key": "coinglass:latest:liquidation_heatmap:Binance:SOLUSDT",
                    "fetched_at": 2.0,
                    "summary": {"shape": "runtime_helper"},
                    "data": {"coin": "SOL"},
                },
            },
        )
    )
    sessions = iter([create_session, get_session])
    monkeypatch.setattr(
        "libs.common.clients.ingestion_api.aiohttp.ClientSession",
        lambda timeout=None: next(sessions),
    )

    client = IngestionApiClient(base_url="http://ingestion-api")

    created = await client.create_scraper_job(request)
    fetched = await client.get_scraper_job(created.job_id, include_result=False)

    assert created.status == ScrapeJobStatus.QUEUED
    assert fetched.status == ScrapeJobStatus.SUCCEEDED
    assert fetched.result is not None
    assert fetched.result.data["coin"] == "SOL"
    assert get_session.requests[0]["params"] == {"include_result": "false"}


@pytest.mark.asyncio
async def test_ingestion_api_client_surfaces_api_errors(monkeypatch):
    session = _FakeSession(
        _FakeResponse(
            status=502,
            payload={"detail": "Scraper service unavailable."},
            reason="Bad Gateway",
        )
    )
    monkeypatch.setattr(
        "libs.common.clients.ingestion_api.aiohttp.ClientSession",
        lambda timeout=None: session,
    )

    client = IngestionApiClient(base_url="http://ingestion-api")

    with pytest.raises(IngestionApiClientError) as exc_info:
        await client.scraper_fetch(
            ScrapeRequest(
                provider=ScraperProvider.TRADINGVIEW,
                dataset=ScrapeDataset.OHLCV,
                symbol="CRYPTOCAP:TOTAL3ES",
                timeframe="1h",
                intent=ScrapeIntent.ON_DEMAND_REFRESH,
            )
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Scraper service unavailable."
