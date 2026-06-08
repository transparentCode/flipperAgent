"""Tests for the CoinGlass heatmap scraper."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from apps.coinglass_scraper.interceptor import CoinGlassHeatmapInterceptor
from apps.coinglass_scraper.worker import fetch_coinglass_heatmaps


class TestCoinGlassHelpers:
    def test_extract_heatmap_payload_from_nested_envelope(self):
        payload = {
            "code": "0",
            "data": {
                "y": [1, 2],
                "liq": [[0, 0, 10.5]],
                "prices": [[1700000000, "100", "110", "90", "105", "1000"]],
            },
        }

        extracted = CoinGlassHeatmapInterceptor._extract_heatmap_payload(payload)

        assert extracted == payload["data"]

    def test_target_key_prefers_short_name(self):
        key = CoinGlassHeatmapInterceptor.target_key(
            {"exchange": "Binance", "coin": "SOL", "short_name": "SOLUSDT"}
        )
        assert key == "Binance:SOLUSDT"

    def test_detects_api_envelope_shape(self):
        payload = {"code": "40000", "msg": "40000", "success": False}

        assert (
            CoinGlassHeatmapInterceptor._is_api_envelope_shape(
                payload,
                "https://capi.coinglass.com/api/index/v5/liqHeatMap?symbol=Binance_SOLUSDT",
            )
            is True
        )

    def test_load_cookies_missing_file(self):
        interceptor = CoinGlassHeatmapInterceptor(cookies_path="/nonexistent/path.json")
        assert interceptor._load_cookies() is None

    def test_load_cookies_valid_file(self, tmp_path):
        cookie_file = tmp_path / "cookies.json"
        cookie_file.write_text(json.dumps([{"name": "session", "value": "secret"}]))
        interceptor = CoinGlassHeatmapInterceptor(cookies_path=str(cookie_file))
        assert interceptor._load_cookies() == [{"name": "session", "value": "secret"}]


class TestCoinGlassNoPatchright:
    @pytest.mark.asyncio
    async def test_returns_none_when_patchright_missing(self):
        interceptor = CoinGlassHeatmapInterceptor()

        import unittest.mock as mock

        with mock.patch.dict("sys.modules", {"patchright": None, "patchright.async_api": None}):
            result = await interceptor.fetch_heatmap("SOL")

        assert result is None


class TestCoinGlassPatchrightSession:
    @pytest.mark.asyncio
    async def test_fetch_heatmap_uses_runtime_helper_when_available(self):
        runtime_payload = {
            "code": "0",
            "msg": "success",
            "success": True,
            "data": {
                "y": [100.0, 101.0],
                "liq": [[0, 0, 54321.0]],
                "prices": [[1700000000, "100", "110", "90", "105", "1000"]],
            },
        }

        class FakePage:
            def __init__(self):
                self._response_cb = None
                self.closed = False

            def on(self, event, cb):
                if event == "response":
                    self._response_cb = cb

            async def goto(self, *args, **kwargs):
                await asyncio.sleep(0)

            async def evaluate(self, expression, arg=None, isolated_context=True):
                return runtime_payload

            async def close(self):
                self.closed = True

        class FakeContext:
            def __init__(self, page):
                self._page = page
                self.closed = False

            async def add_cookies(self, cookies):
                return None

            async def new_page(self):
                return self._page

            async def close(self):
                self.closed = True

        class FakeBrowser:
            def __init__(self, context):
                self._context = context
                self.closed = False

            async def new_context(self, **kwargs):
                return self._context

            async def close(self):
                self.closed = True

        class FakeChromium:
            def __init__(self, browser):
                self._browser = browser

            async def launch(self, **kwargs):
                return self._browser

        class FakePlaywright:
            def __init__(self, browser):
                self.chromium = FakeChromium(browser)

        class FakeAsyncPlaywrightContext:
            def __init__(self, playwright):
                self._playwright = playwright

            async def __aenter__(self):
                return self._playwright

            async def __aexit__(self, exc_type, exc, tb):
                return False

        page = FakePage()
        context = FakeContext(page)
        browser = FakeBrowser(context)
        fake_playwright = FakePlaywright(browser)

        interceptor = CoinGlassHeatmapInterceptor()

        import sys
        import types
        import unittest.mock as mock

        patchright_mod = types.ModuleType("patchright")
        async_api_mod = types.ModuleType("patchright.async_api")
        async_api_mod.async_playwright = lambda: FakeAsyncPlaywrightContext(fake_playwright)
        patchright_mod.async_api = async_api_mod

        with mock.patch.dict(
            sys.modules,
            {"patchright": patchright_mod, "patchright.async_api": async_api_mod},
        ):
            result = await interceptor.fetch_heatmap("SOL", symbol="SOLUSDT")

        assert result is not None
        assert result["shape"] == "runtime_helper"
        assert result["payload"]["liq"] == [[0, 0, 54321.0]]
        assert result["response_url"] == "/api/index/v5/liqHeatMap"
        assert context.closed is True
        assert browser.closed is True
        assert page.closed is True

    @pytest.mark.asyncio
    async def test_fetch_heatmap_captures_best_response(self):
        response_payload = {
            "code": "0",
            "data": {
                "y": [100.0, 101.0],
                "liq": [[0, 0, 12345.0]],
                "prices": [[1700000000, "100", "110", "90", "105", "1000"]],
            },
        }

        class FakeResponse:
            def __init__(self, url, payload):
                self.url = url
                self._payload = payload

            async def json(self):
                return self._payload

        class FakePage:
            def __init__(self, responses):
                self._responses = list(responses)
                self._response_cb = None
                self.closed = False

            def on(self, event, cb):
                if event == "response":
                    self._response_cb = cb

            async def goto(self, *args, **kwargs):
                for response in self._responses:
                    if self._response_cb:
                        self._response_cb(response)
                await asyncio.sleep(0)

            async def close(self):
                self.closed = True

        class FakeContext:
            def __init__(self, pages):
                self._pages = list(pages)
                self.cookies = None
                self.closed = False

            async def add_cookies(self, cookies):
                self.cookies = cookies

            async def new_page(self):
                return self._pages.pop(0)

            async def close(self):
                self.closed = True

        class FakeBrowser:
            def __init__(self, context):
                self._context = context
                self.closed = False

            async def new_context(self, **kwargs):
                return self._context

            async def close(self):
                self.closed = True

        class FakeChromium:
            def __init__(self, browser):
                self._browser = browser

            async def launch(self, **kwargs):
                return self._browser

        class FakePlaywright:
            def __init__(self, browser):
                self.chromium = FakeChromium(browser)

        class FakeAsyncPlaywrightContext:
            def __init__(self, playwright):
                self._playwright = playwright

            async def __aenter__(self):
                return self._playwright

            async def __aexit__(self, exc_type, exc, tb):
                return False

        responses = [
            FakeResponse("https://api.example.com/other", {"ok": True}),
            FakeResponse(
                "https://api.example.com/liquidation/heatmap/model1",
                response_payload,
            ),
        ]
        page = FakePage(responses)
        context = FakeContext([page])
        browser = FakeBrowser(context)
        fake_playwright = FakePlaywright(browser)

        interceptor = CoinGlassHeatmapInterceptor()

        import sys
        import types
        import unittest.mock as mock

        patchright_mod = types.ModuleType("patchright")
        async_api_mod = types.ModuleType("patchright.async_api")
        async_api_mod.async_playwright = lambda: FakeAsyncPlaywrightContext(fake_playwright)
        patchright_mod.async_api = async_api_mod

        with mock.patch.dict(
            sys.modules,
            {"patchright": patchright_mod, "patchright.async_api": async_api_mod},
        ):
            result = await interceptor.fetch_heatmap("SOL", symbol="SOLUSDT")

        assert result is not None
        assert result["coin"] == "SOL"
        assert result["symbol"] == "SOLUSDT"
        assert result["shape"] == "heatmap_payload"
        assert result["payload"]["liq"] == [[0, 0, 12345.0]]
        assert context.closed is True
        assert browser.closed is True
        assert page.closed is True

    @pytest.mark.asyncio
    async def test_fetch_heatmap_keeps_api_error_envelope_when_no_payload_shape(self):
        response_payload = {"code": "40000", "msg": "40000", "success": False}

        class FakeResponse:
            def __init__(self, url, payload):
                self.url = url
                self._payload = payload

            async def json(self):
                return self._payload

        class FakePage:
            def __init__(self, responses):
                self._responses = list(responses)
                self._response_cb = None

            def on(self, event, cb):
                if event == "response":
                    self._response_cb = cb

            async def goto(self, *args, **kwargs):
                for response in self._responses:
                    if self._response_cb:
                        self._response_cb(response)
                await asyncio.sleep(0)

            async def close(self):
                return None

        class FakeContext:
            def __init__(self, page):
                self._page = page

            async def add_cookies(self, cookies):
                return None

            async def new_page(self):
                return self._page

            async def close(self):
                return None

        class FakeBrowser:
            def __init__(self, context):
                self._context = context

            async def new_context(self, **kwargs):
                return self._context

            async def close(self):
                return None

        class FakeChromium:
            def __init__(self, browser):
                self._browser = browser

            async def launch(self, **kwargs):
                return self._browser

        class FakePlaywright:
            def __init__(self, browser):
                self.chromium = FakeChromium(browser)

        class FakeAsyncPlaywrightContext:
            def __init__(self, playwright):
                self._playwright = playwright

            async def __aenter__(self):
                return self._playwright

            async def __aexit__(self, exc_type, exc, tb):
                return False

        page = FakePage(
            [
                FakeResponse(
                    "https://capi.coinglass.com/api/index/v5/liqHeatMap?symbol=Binance_SOLUSDT",
                    response_payload,
                )
            ]
        )
        context = FakeContext(page)
        browser = FakeBrowser(context)
        fake_playwright = FakePlaywright(browser)

        interceptor = CoinGlassHeatmapInterceptor()

        import sys
        import types
        import unittest.mock as mock

        patchright_mod = types.ModuleType("patchright")
        async_api_mod = types.ModuleType("patchright.async_api")
        async_api_mod.async_playwright = lambda: FakeAsyncPlaywrightContext(fake_playwright)
        patchright_mod.async_api = async_api_mod

        with mock.patch.dict(
            sys.modules,
            {"patchright": patchright_mod, "patchright.async_api": async_api_mod},
        ):
            result = await interceptor.fetch_heatmap("SOL", symbol="SOLUSDT")

        assert result is not None
        assert result["shape"] == "api_envelope"
        assert result["payload"]["code"] == "40000"


class TestCoinGlassWorker:
    @pytest.mark.asyncio
    async def test_worker_publishes_heatmap_payload_to_valkey(self, monkeypatch):
        redis = AsyncMock()

        class FakeInterceptor:
            @staticmethod
            def target_key(target):
                return f"{target['exchange']}:{target['short_name']}"

            async def fetch_heatmaps(self, targets):
                target = targets[0]
                key = self.target_key(target)
                return {
                    key: {
                        "coin": target["coin"],
                        "exchange": target["exchange"],
                        "symbol": target["symbol"],
                        "market_type": target["market_type"],
                        "shape": "heatmap_payload",
                        "response_url": "https://api.example.com/liquidation/heatmap/model1",
                        "page_url": "https://www.coinglass.com/pro/futures/LiquidationHeatMapNew?coin=SOL&type=pair",
                        "captured_at_ms": 1700000000000,
                        "payload": {"liq": [[0, 0, 1]], "prices": [], "y": []},
                    }
                }

        monkeypatch.setattr(
            "apps.coinglass_scraper.worker.HEATMAP_TARGETS",
            [
                {
                    "coin": "SOL",
                    "market_type": "pair",
                    "exchange": "Binance",
                    "symbol": "SOLUSDT",
                    "short_name": "SOLUSDT",
                }
            ],
        )

        ctx = {"redis": redis, "coinglass_interceptor": FakeInterceptor()}

        await fetch_coinglass_heatmaps(ctx)

        redis.hset.assert_awaited_once()
        kwargs = redis.hset.await_args.kwargs
        assert kwargs["mapping"]["coin"] == "SOL"
        assert "payload_json" in kwargs["mapping"]
        redis.expire.assert_awaited_once()
