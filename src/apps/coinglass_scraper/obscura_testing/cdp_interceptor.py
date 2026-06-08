"""CDP-attached CoinGlass scraper prototype for Obscura-based testing."""

from __future__ import annotations

from typing import Any

from apps.coinglass_scraper.interceptor import CoinGlassHeatmapInterceptor


def build_obscura_launch_command(host: str = "127.0.0.1", port: int = 9222) -> str:
    """Return a minimal Obscura launch command for local CDP testing."""
    return f"obscura serve --host {host} --port {port}"


class ObscuraCDPHeatmapInterceptor(CoinGlassHeatmapInterceptor):
    """Fetch CoinGlass heatmaps by attaching Patchright to a CDP endpoint."""

    def __init__(
        self,
        endpoint_url: str | None = None,
        cookies_path: str | None = None,
        proxy_url: str | None = None,
        cdp_headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(cookies_path=cookies_path, proxy_url=proxy_url)
        self.endpoint_url = endpoint_url or self._config.get(
            "coinglass.obscura_testing.endpoint_url", "http://127.0.0.1:9222"
        )
        self.connect_timeout_ms = int(
            self._config.get("coinglass.obscura_testing.connect_timeout_ms", 30000)
        )
        self.cdp_headers = cdp_headers or self._config.get(
            "coinglass.obscura_testing.cdp_headers"
        )

    async def fetch_heatmaps(
        self, targets: list[dict[str, str]]
    ) -> dict[str, dict[str, Any] | None]:
        """Fetch multiple heatmap payloads by attaching to an existing CDP browser."""
        results = {self.target_key(target): None for target in targets}
        if not targets:
            return results

        try:
            from patchright.async_api import async_playwright
        except ImportError:
            return results

        browser = None
        context = None

        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.connect_over_cdp(
                    self.endpoint_url,
                    timeout=self.connect_timeout_ms,
                    headers=self.cdp_headers,
                    is_local=True,
                )
                context = await self._resolve_context(browser)
                await self._apply_cookies(context)

                fetch_delay = self._config.get("coinglass.fetch_delay_seconds", 2)
                for index, target in enumerate(targets):
                    key = self.target_key(target)
                    results[key] = await self._fetch_target_heatmap(context, target)
                    if index < len(targets) - 1 and fetch_delay > 0:
                        import asyncio

                        await asyncio.sleep(fetch_delay)
        finally:
            if context is not None:
                await self._close_quietly(context)
            if browser is not None:
                await self._close_quietly(browser)

        return results

    async def _resolve_context(self, browser: Any) -> Any:
        """Prefer a fresh context, but fall back to an existing CDP context."""
        context_kwargs = {
            "viewport": {
                "width": self._config.get("coinglass.viewport_width", 1920),
                "height": self._config.get("coinglass.viewport_height", 1080),
            },
            "user_agent": self._config.get(
                "coinglass.user_agent",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36",
            ),
        }

        try:
            return await browser.new_context(**context_kwargs)
        except Exception:
            contexts = getattr(browser, "contexts", [])
            if contexts:
                return contexts[0]
            raise
