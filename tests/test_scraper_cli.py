"""Tests for the shared scraper research CLI."""

from __future__ import annotations

import json

import pandas as pd

from apps.scraper_app import cli


def test_coinglass_cli_writes_json(tmp_path, monkeypatch):
    output_path = tmp_path / "heatmap.json"

    class FakeInterceptor:
        def __init__(self, cookies_path=None):
            self.cookies_path = cookies_path

        async def fetch_heatmap(self, **kwargs):
            return {"coin": kwargs["coin"], "shape": "runtime_helper", "payload": {"liq": []}}

        async def close(self):
            return None

    monkeypatch.setattr(cli, "CoinGlassHeatmapInterceptor", FakeInterceptor)

    exit_code = cli.main(
        ["coinglass", "--coin", "SOL", "--cookies-path", "cookies.json", "--output-path", str(output_path)]
    )

    assert exit_code == 0
    assert json.loads(output_path.read_text())["coin"] == "SOL"


def test_tradingview_cli_writes_csv(tmp_path, monkeypatch):
    output_path = tmp_path / "ohlcv.csv"

    class FakeInterceptor:
        def __init__(self, cookies_path=None):
            self.cookies_path = cookies_path

        async def get_historical_ohlcv(self, symbol, timeframe):
            return pd.DataFrame(
                [
                    {
                        "timestamp": 1700000000000,
                        "open": 1.0,
                        "high": 2.0,
                        "low": 0.5,
                        "close": 1.5,
                        "volume": 10.0,
                    }
                ]
            )

        async def close(self):
            return None

    monkeypatch.setattr(cli, "TradingViewInterceptor", FakeInterceptor)

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
