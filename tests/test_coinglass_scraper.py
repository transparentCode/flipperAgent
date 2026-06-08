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

    def test_build_launch_kwargs_uses_configured_memory_saving_defaults(self):
        interceptor = CoinGlassHeatmapInterceptor()

        launch_kwargs = interceptor._build_launch_kwargs()

        assert launch_kwargs["headless"] is True
        assert "--disable-dev-shm-usage" in launch_kwargs["args"]
        assert "--disable-extensions" in launch_kwargs["args"]
        assert "--no-sandbox" in launch_kwargs["args"]

    @pytest.mark.asyncio
    async def test_configure_page_blocks_only_configured_resource_types(self):
        interceptor = CoinGlassHeatmapInterceptor()

        class FakeRequest:
            def __init__(self, resource_type):
                self.resource_type = resource_type

        class FakeRoute:
            def __init__(self, resource_type):
                self.request = FakeRequest(resource_type)
                self.aborted = False
                self.continued = False

            async def abort(self):
                self.aborted = True

            async def continue_(self):
                self.continued = True

        class FakePage:
            def __init__(self):
                self.pattern = None
                self.handler = None

            async def route(self, pattern, handler):
                self.pattern = pattern
                self.handler = handler

        page = FakePage()

        await interceptor._configure_page(page)

        image_route = FakeRoute("image")
        xhr_route = FakeRoute("xhr")
        await page.handler(image_route)
        await page.handler(xhr_route)

        assert page.pattern == "**/*"
        assert image_route.aborted is True
        assert xhr_route.continued is True


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
                self.stopped = False

            async def stop(self):
                self.stopped = True

        class FakeAsyncPlaywrightManager:
            def __init__(self, playwright):
                self._playwright = playwright

            async def start(self):
                return self._playwright

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
        async_api_mod.async_playwright = lambda: FakeAsyncPlaywrightManager(fake_playwright)
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
        assert page.closed is True

        await interceptor.close()

        assert context.closed is True
        assert browser.closed is True
        assert fake_playwright.stopped is True

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
                self.goto_calls = 0

            def on(self, event, cb):
                if event == "response":
                    self._response_cb = cb

            async def goto(self, *args, **kwargs):
                self.goto_calls += 1
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
                self.stopped = False

            async def stop(self):
                self.stopped = True

        class FakeAsyncPlaywrightManager:
            def __init__(self, playwright):
                self._playwright = playwright

            async def start(self):
                return self._playwright

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
        async_api_mod.async_playwright = lambda: FakeAsyncPlaywrightManager(fake_playwright)
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
        assert page.goto_calls == 1
        assert page.closed is True

        await interceptor.close()

        assert context.closed is True
        assert browser.closed is True
        assert fake_playwright.stopped is True

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

            async def stop(self):
                return None

        class FakeAsyncPlaywrightManager:
            def __init__(self, playwright):
                self._playwright = playwright

            async def start(self):
                return self._playwright

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
        async_api_mod.async_playwright = lambda: FakeAsyncPlaywrightManager(fake_playwright)
        patchright_mod.async_api = async_api_mod

        with mock.patch.dict(
            sys.modules,
            {"patchright": patchright_mod, "patchright.async_api": async_api_mod},
        ):
            result = await interceptor.fetch_heatmap("SOL", symbol="SOLUSDT")

        assert result is not None
        assert result["shape"] == "api_envelope"
        assert result["payload"]["code"] == "40000"

    @pytest.mark.asyncio
    async def test_fetch_heatmap_reuses_browser_context_across_calls(self):
        runtime_payload = {
            "code": "0",
            "data": {
                "y": [100.0, 101.0],
                "liq": [[0, 0, 54321.0]],
                "prices": [[1700000000, "100", "110", "90", "105", "1000"]],
            },
        }

        class FakePage:
            def __init__(self):
                self.closed = False

            def on(self, event, cb):
                return None

            async def route(self, pattern, handler):
                return None

            async def goto(self, *args, **kwargs):
                await asyncio.sleep(0)

            async def evaluate(self, expression, arg=None, isolated_context=True):
                return runtime_payload

            async def close(self):
                self.closed = True

        class FakeContext:
            def __init__(self):
                self.new_page_calls = 0
                self.closed = False
                self.route_calls = []

            async def add_cookies(self, cookies):
                return None

            async def route(self, pattern, handler):
                self.route_calls.append((pattern, handler))

            async def new_page(self):
                self.new_page_calls += 1
                return FakePage()

            async def close(self):
                self.closed = True

        class FakeBrowser:
            def __init__(self, context):
                self._context = context
                self.new_context_calls = 0
                self.closed = False

            async def new_context(self, **kwargs):
                self.new_context_calls += 1
                return self._context

            async def close(self):
                self.closed = True

        class FakeChromium:
            def __init__(self, browser):
                self._browser = browser
                self.launch_calls = 0

            async def launch(self, **kwargs):
                self.launch_calls += 1
                return self._browser

        class FakePlaywright:
            def __init__(self, browser):
                self.chromium = FakeChromium(browser)
                self.stopped = False

            async def stop(self):
                self.stopped = True

        class FakeAsyncPlaywrightManager:
            def __init__(self, playwright):
                self._playwright = playwright
                self.start_calls = 0

            async def start(self):
                self.start_calls += 1
                return self._playwright

        context = FakeContext()
        browser = FakeBrowser(context)
        fake_playwright = FakePlaywright(browser)
        fake_manager = FakeAsyncPlaywrightManager(fake_playwright)
        interceptor = CoinGlassHeatmapInterceptor()

        import sys
        import types
        import unittest.mock as mock

        patchright_mod = types.ModuleType("patchright")
        async_api_mod = types.ModuleType("patchright.async_api")
        async_api_mod.async_playwright = lambda: fake_manager
        patchright_mod.async_api = async_api_mod

        with mock.patch.dict(
            sys.modules,
            {"patchright": patchright_mod, "patchright.async_api": async_api_mod},
        ):
            first = await interceptor.fetch_heatmap("SOL", symbol="SOLUSDT")
            second = await interceptor.fetch_heatmap("BTC", symbol="BTCUSDT")

        assert first is not None
        assert second is not None
        assert fake_manager.start_calls == 1
        assert fake_playwright.chromium.launch_calls == 1
        assert browser.new_context_calls == 1
        assert len(context.route_calls) == 1
        assert context.route_calls[0][0] == "**/*"
        assert context.new_page_calls == 2

        await interceptor.close()


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
