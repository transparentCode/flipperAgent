"""Tests for the Lightpanda/CDP CoinGlass probe."""

from __future__ import annotations

import pytest

from apps.coinglass_scraper.lightpanda_testing.cdp_interceptor import (
    LightpandaCDPHeatmapInterceptor,
    build_lightpanda_launch_command,
)


def test_build_lightpanda_launch_command_defaults():
    assert (
        build_lightpanda_launch_command()
        == "lightpanda serve --host 127.0.0.1 --port 9222"
    )


class TestLightpandaCDPInterceptor:
    @pytest.mark.asyncio
    async def test_fetch_heatmaps_uses_cdp_connection(self):
        expected = {
            "coin": "SOL",
            "exchange": "Binance",
            "symbol": "SOLUSDT",
            "market_type": "pair",
            "short_name": "SOL",
            "page_url": "https://example.com",
            "response_url": "/api/index/v5/liqHeatMap",
            "captured_at_ms": 1,
            "shape": "runtime_helper",
            "payload": {"liq": [[1, 2, 3]], "prices": [], "y": []},
        }

        class FakeContext:
            def __init__(self):
                self.closed = False
                self.cookies = None

            async def add_cookies(self, cookies):
                self.cookies = cookies

            async def close(self):
                self.closed = True

        class FakeBrowser:
            def __init__(self, context):
                self.contexts = []
                self._context = context
                self.closed = False

            async def new_context(self, **kwargs):
                return self._context

            async def close(self):
                self.closed = True

        class FakeChromium:
            def __init__(self, browser):
                self._browser = browser
                self.calls = []

            async def connect_over_cdp(self, endpoint_url, **kwargs):
                self.calls.append((endpoint_url, kwargs))
                return self._browser

        class FakePlaywright:
            def __init__(self, chromium):
                self.chromium = chromium

        class FakeAsyncPlaywrightContext:
            def __init__(self, playwright):
                self._playwright = playwright

            async def __aenter__(self):
                return self._playwright

            async def __aexit__(self, exc_type, exc, tb):
                return False

        context = FakeContext()
        browser = FakeBrowser(context)
        chromium = FakeChromium(browser)
        fake_playwright = FakePlaywright(chromium)

        interceptor = LightpandaCDPHeatmapInterceptor(endpoint_url="http://127.0.0.1:9999")

        async def fake_fetch_target(_context, target):
            return {
                **expected,
                "coin": target["coin"],
                "exchange": target["exchange"],
                "symbol": target["symbol"],
                "market_type": target["market_type"],
                "short_name": target["short_name"],
            }

        interceptor._fetch_target_heatmap = fake_fetch_target  # type: ignore[method-assign]

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
            result = await interceptor.fetch_heatmaps(
                [
                    {
                        "coin": "SOL",
                        "market_type": "pair",
                        "exchange": "Binance",
                        "symbol": "SOLUSDT",
                        "short_name": "SOL",
                    }
                ]
            )

        assert result["Binance:SOL"]["shape"] == "runtime_helper"
        assert chromium.calls[0][0] == "http://127.0.0.1:9999"
        assert context.closed is True
        assert browser.closed is True
