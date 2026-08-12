"""Tests for the shared scraper research CLI."""

from __future__ import annotations

import json

from apps.scraper_app import cli
from apps.scraper_app.core.models import ScrapeResult


def _ohlcv_result(request):
    return ScrapeResult(
        provider=request.provider,
        dataset=request.dataset,
        intent=request.intent,
        source="live",
        symbol=request.symbol,
        timeframe=request.timeframe,
        data=[
            {
                "timestamp": 1700000000000,
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 10.0,
            }
        ],
    )


def test_coinglass_cli_writes_json(tmp_path, monkeypatch):
    output_path = tmp_path / "heatmap.json"

    class FakeService:
        async def fetch(self, request):
            return ScrapeResult(
                provider=request.provider,
                dataset=request.dataset,
                intent=request.intent,
                source="live",
                symbol=request.symbol,
                data={"coin": request.coin, "shape": "runtime_helper", "payload": {"liq": []}},
            )

    monkeypatch.setattr(cli, "ScraperFetchService", FakeService)

    exit_code = cli.main(
        ["coinglass", "--coin", "SOL", "--cookies-path", "cookies.json", "--output-path", str(output_path)]
    )

    assert exit_code == 0
    assert json.loads(output_path.read_text())["coin"] == "SOL"


def test_tradingview_cli_writes_csv(tmp_path, monkeypatch):
    output_path = tmp_path / "ohlcv.csv"

    class FakeService:
        async def fetch(self, request):
            assert request.limit is None
            return _ohlcv_result(request)

    monkeypatch.setattr(cli, "ScraperFetchService", FakeService)

    exit_code = cli.main(
        [
            "tradingview",
            "ohlcv",
            "--symbol",
            "CRYPTOCAP:TOTAL2",
            "--timeframe",
            "1h",
            "--output-path",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert "timestamp,open,high,low,close,volume" in output_path.read_text()


def test_tradingview_cli_passes_limit(tmp_path, monkeypatch):
    output_path = tmp_path / "ohlcv.json"

    class FakeService:
        async def fetch(self, request):
            assert request.symbol == "CRYPTOCAP:TOTAL2"
            assert request.timeframe == "1h"
            assert request.limit == 8760
            return _ohlcv_result(request)

    monkeypatch.setattr(cli, "ScraperFetchService", FakeService)

    exit_code = cli.main(
        [
            "tradingview",
            "ohlcv",
            "--symbol",
            "CRYPTOCAP:TOTAL2",
            "--timeframe",
            "1h",
            "--limit",
            "8760",
            "--output-path",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert "1700000000000" in output_path.read_text()
