"""CoinGlass liquidation heatmap browser interceptor."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)

CONFIG_FILE_COINGLASS = "configs/coinglass.yaml"


class CoinGlassHeatmapInterceptor:
    """Capture CoinGlass heatmap payloads via browser network interception."""

    def __init__(self, cookies_path: str | None = None, proxy_url: str | None = None):
        config = ConfigManager()
        config.register_file(CONFIG_FILE_COINGLASS)
        self.cookies_path = cookies_path or config.get(
            "coinglass.cookies_path", "secrets/coinglass_cookies.json"
        )
        self.proxy_url = proxy_url or config.get("coinglass.proxy_url")
        self._config = config
        self._blocked_resource_types = set(
            self._config.get("coinglass.blocked_resource_types", ["image", "media", "font"])
        )

    async def fetch_heatmap(
        self,
        coin: str,
        market_type: str = "pair",
        exchange: str = "Binance",
        symbol: str | None = None,
        short_name: str | None = None,
    ) -> dict[str, Any] | None:
        """Fetch one CoinGlass heatmap payload."""
        target = {
            "coin": coin,
            "market_type": market_type,
            "exchange": exchange,
            "symbol": symbol or f"{coin}USDT",
            "short_name": short_name or symbol or coin,
        }
        result = await self.fetch_heatmaps([target])
        return result.get(self.target_key(target))

    async def fetch_heatmaps(
        self, targets: list[dict[str, str]]
    ) -> dict[str, dict[str, Any] | None]:
        """Fetch multiple heatmap payloads in one browser session."""
        results = {self.target_key(target): None for target in targets}
        if not targets:
            return results

        try:
            from patchright.async_api import async_playwright
        except ImportError:
            logger.error(
                "Patchright is not installed. Install project optional tv-scraper deps."
            )
            return results

        browser = None
        context = None

        try:
            async with async_playwright() as playwright:
                launch_kwargs = self._build_launch_kwargs()
                if self.proxy_url:
                    launch_kwargs["proxy"] = {"server": self.proxy_url}

                browser = await playwright.chromium.launch(**launch_kwargs)
                context = await browser.new_context(
                    viewport={
                        "width": self._config.get("coinglass.viewport_width", 1920),
                        "height": self._config.get("coinglass.viewport_height", 1080),
                    },
                    user_agent=self._config.get(
                        "coinglass.user_agent",
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36",
                    ),
                )
                await self._apply_cookies(context)

                fetch_delay = self._config.get("coinglass.fetch_delay_seconds", 2)
                for index, target in enumerate(targets):
                    key = self.target_key(target)
                    results[key] = await self._fetch_target_heatmap(context, target)
                    if index < len(targets) - 1 and fetch_delay > 0:
                        await asyncio.sleep(fetch_delay)
        except Exception as exc:
            logger.error(
                f"CoinGlass browser session failed for {targets}: {exc}",
                exc_info=True,
            )
        finally:
            await self._close_quietly(context)
            await self._close_quietly(browser)

        return results

    async def _fetch_target_heatmap(
        self, context: Any, target: dict[str, str]
    ) -> dict[str, Any] | None:
        page = None
        pending_tasks: list[asyncio.Task[Any]] = []
        best_candidate: dict[str, Any] | None = None
        best_score = -1
        page_url = self._build_page_url(target)
        helper_delay_seconds = self._config.get(
            "coinglass.runtime_helper_delay_seconds", 2
        )

        async def consider_response(response: Any) -> None:
            nonlocal best_candidate, best_score

            url = getattr(response, "url", "")
            if not self._response_url_matches(url):
                return

            try:
                payload = await response.json()
            except Exception:
                return

            shape = "url_fallback"
            candidate = self._extract_heatmap_payload(payload)
            score = self._score_candidate(candidate, url) if candidate else 0
            if candidate is None and self._is_api_envelope_shape(payload, url):
                candidate = payload
                score = 6
                shape = "api_envelope"
            elif candidate is None and self._looks_like_fallback_url(url):
                candidate = payload
                score = 1

            if candidate is None or score < best_score:
                return

            if score > 1 and shape == "url_fallback":
                shape = "heatmap_payload"

            best_score = score
            best_candidate = {
                "coin": target["coin"],
                "exchange": target.get("exchange", "Binance"),
                "symbol": target.get("symbol", ""),
                "market_type": target.get("market_type", "pair"),
                "short_name": target.get("short_name", target["coin"]),
                "page_url": page_url,
                "response_url": url,
                "captured_at_ms": int(time.time() * 1000),
                "shape": shape,
                "payload": candidate,
            }

        try:
            page = await context.new_page()
            await self._configure_page(page)
            await page.goto(
                page_url,
                wait_until="domcontentloaded",
                timeout=self._config.get("coinglass.page_load_timeout_ms", 30000),
            )
            if helper_delay_seconds > 0:
                await asyncio.sleep(helper_delay_seconds)

            runtime_candidate = await self._fetch_runtime_helper_payload(
                page, target, page_url
            )
            if runtime_candidate is not None:
                return runtime_candidate

            def on_response(response: Any) -> None:
                pending_tasks.append(asyncio.create_task(consider_response(response)))

            page.on("response", on_response)
            await page.goto(
                page_url,
                wait_until="domcontentloaded",
                timeout=self._config.get("coinglass.page_load_timeout_ms", 30000),
            )

            timeout_seconds = self._config.get(
                "coinglass.response_timeout_seconds", 15
            )
            poll_seconds = self._config.get("coinglass.poll_interval_seconds", 0.5)
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                if best_candidate is not None and best_score > 1:
                    break
                await asyncio.sleep(poll_seconds)

            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)
        except Exception as exc:
            logger.error(
                f"CoinGlass interception failed for {target}: {exc}",
                exc_info=True,
            )
            return None
        finally:
            await self._close_quietly(page)

        if best_candidate is None:
            logger.warning(f"No CoinGlass payload captured for {target}")
        return best_candidate

    async def _fetch_runtime_helper_payload(
        self,
        page: Any,
        target: dict[str, str],
        page_url: str,
    ) -> dict[str, Any] | None:
        evaluate = getattr(page, "evaluate", None)
        if not callable(evaluate):
            return None

        params = {
            "merge": True,
            "symbol": self._build_helper_symbol(target),
            "interval": self._config.get("coinglass.runtime_helper_interval", 5),
            "limit": self._config.get("coinglass.runtime_helper_limit", 288),
            "ua": self._config.get("coinglass.runtime_helper_user_agent", "Mozilla/5.0"),
            "helperExportUrls": self._helper_export_urls(page_url),
        }

        try:
            runtime_result = await evaluate(
                """
                async (params) => {
                  const chunkStore = globalThis.webpackChunk_N_E;
                  if (!Array.isArray(chunkStore)) {
                    return null;
                  }

                  let webpackRequire;
                  chunkStore.push([[Math.random()], {}, (req) => { webpackRequire = req; }]);
                  if (!webpackRequire || !webpackRequire.m) {
                    return null;
                  }

                  let helper = null;
                  let helperUrl = null;
                  let helperPriority = Number.POSITIVE_INFINITY;
                  for (const id of Object.keys(webpackRequire.m)) {
                    let exported;
                    try {
                      exported = webpackRequire(id);
                    } catch {
                      continue;
                    }
                    if (!exported || typeof exported !== "object") {
                      continue;
                    }
                    for (const [name, candidate] of Object.entries(exported)) {
                      if (typeof candidate !== "function") {
                        continue;
                      }
                      let source = "";
                      try {
                        source = Function.prototype.toString.call(candidate);
                      } catch {
                        source = "";
                      }
                      const matchIndex = params.helperExportUrls.findIndex((url) =>
                        source.includes(url),
                      );
                      if (matchIndex !== -1 && matchIndex < helperPriority) {
                        helper = candidate;
                        helperUrl = params.helperExportUrls[matchIndex];
                        helperPriority = matchIndex;
                      }
                    }
                  }

                  if (typeof helper !== "function") {
                    return null;
                  }

                  const cookies = Object.fromEntries(
                    document.cookie
                      .split("; ")
                      .filter(Boolean)
                      .map((item) => {
                        const index = item.indexOf("=");
                        return [
                          decodeURIComponent(item.slice(0, index)),
                          decodeURIComponent(item.slice(index + 1)),
                        ];
                      }),
                  );

                  const requestParams = {
                    merge: params.merge,
                    symbol: params.symbol,
                    interval: params.interval,
                    limit: params.limit,
                    ua: params.ua,
                    obe: cookies.obe,
                  };

                  const payload = await helper(requestParams);
                  return { helperUrl, payload };
                }
                """,
                params,
                isolated_context=False,
            )
        except Exception as exc:
            logger.debug(f"CoinGlass runtime helper fetch failed for {target}: {exc}")
            return None

        helper_url = params["helperExportUrls"][0]
        payload = runtime_result
        if isinstance(runtime_result, dict) and isinstance(runtime_result.get("payload"), dict):
            payload = runtime_result["payload"]
            helper_url = runtime_result.get("helperUrl") or helper_url

        if not isinstance(payload, dict):
            return None

        candidate = payload.get("data") if isinstance(payload.get("data"), dict) else None
        if candidate is None or not self._is_heatmap_shape(candidate):
            return None

        return {
            "coin": target["coin"],
            "exchange": target.get("exchange", "Binance"),
            "symbol": target.get("symbol", ""),
            "market_type": target.get("market_type", "pair"),
            "short_name": target.get("short_name", target["coin"]),
            "page_url": page_url,
            "response_url": helper_url,
            "captured_at_ms": int(time.time() * 1000),
            "shape": "runtime_helper",
            "payload": candidate,
        }

    def _build_page_url(self, target: dict[str, str]) -> str:
        base_url = self._config.get(
            "coinglass.heatmap_base_url",
            "https://www.coinglass.com/pro/futures/LiquidationHeatMapNew",
        )
        query = urlencode(
            {
                "coin": target["coin"],
                "type": target.get("market_type", "pair"),
            }
        )
        return f"{base_url}?{query}"

    @staticmethod
    def _build_helper_symbol(target: dict[str, str]) -> str:
        exchange = target.get("exchange", "Binance")
        symbol = target.get("symbol") or f"{target['coin']}USDT"
        return f"{exchange}_{symbol}"

    def _build_launch_kwargs(self) -> dict[str, Any]:
        return {
            "headless": self._config.get("coinglass.headless", True),
            "args": list(
                self._config.get(
                    "coinglass.chromium_args",
                    [
                        "--disable-blink-features=AutomationControlled",
                        "--disable-background-networking",
                        "--disable-component-update",
                        "--disable-default-apps",
                        "--disable-dev-shm-usage",
                        "--disable-extensions",
                        "--disable-sync",
                        "--disable-translate",
                        "--metrics-recording-only",
                        "--mute-audio",
                        "--no-first-run",
                        "--no-sandbox",
                    ],
                )
            ),
        }

    async def _configure_page(self, page: Any) -> None:
        route = getattr(page, "route", None)
        if not callable(route) or not self._blocked_resource_types:
            return

        async def handle_request(route_obj: Any) -> None:
            request = getattr(route_obj, "request", None)
            resource_type = getattr(request, "resource_type", None)
            if resource_type in self._blocked_resource_types:
                await route_obj.abort()
                return
            await route_obj.continue_()

        await route("**/*", handle_request)

    @staticmethod
    def _helper_export_urls(page_url: str) -> list[str]:
        if "LiquidationHeatMapNew" in page_url:
            return ["/api/index/v5/liqHeatMap", "/api/index/v2/liqHeatMap"]
        return ["/api/index/v2/liqHeatMap", "/api/index/v5/liqHeatMap"]

    def _response_url_matches(self, url: str) -> bool:
        keywords = self._config.get(
            "coinglass.response_url_keywords",
            ["liquidation", "heatmap", "map"],
        )
        lowered = url.lower()
        return any(keyword.lower() in lowered for keyword in keywords)

    @staticmethod
    def _looks_like_fallback_url(url: str) -> bool:
        lowered = url.lower()
        return "liquidation" in lowered and "heatmap" in lowered

    @staticmethod
    def _is_api_envelope_shape(payload: Any, url: str) -> bool:
        if not isinstance(payload, dict):
            return False
        lowered = url.lower()
        return (
            "liqheatmap" in lowered
            and "code" in payload
            and "success" in payload
        )

    @classmethod
    def _extract_heatmap_payload(cls, payload: Any) -> dict[str, Any] | None:
        if isinstance(payload, dict):
            if cls._is_heatmap_shape(payload):
                return payload
            data = payload.get("data")
            if isinstance(data, dict):
                nested = cls._extract_heatmap_payload(data)
                if nested is not None:
                    return nested
            for value in payload.values():
                nested = cls._extract_heatmap_payload(value)
                if nested is not None:
                    return nested

        if isinstance(payload, list):
            for item in payload:
                nested = cls._extract_heatmap_payload(item)
                if nested is not None:
                    return nested

        return None

    @staticmethod
    def _is_heatmap_shape(payload: dict[str, Any]) -> bool:
        return "liq" in payload and ("prices" in payload or "y" in payload)

    @staticmethod
    def _score_candidate(candidate: dict[str, Any] | None, url: str) -> int:
        if candidate is None:
            return 0

        score = 0
        if "liq" in candidate:
            score += 4
        if "prices" in candidate:
            score += 3
        if "y" in candidate:
            score += 2
        lowered = url.lower()
        if "heatmap" in lowered:
            score += 2
        if "liquidation" in lowered:
            score += 1
        return score

    async def _apply_cookies(self, context: Any) -> None:
        cookies = self._load_cookies()
        if not cookies:
            return
        await context.add_cookies([dict(cookie) for cookie in cookies])

    def _load_cookies(self) -> list[dict[str, Any]] | None:
        try:
            if Path(self.cookies_path).exists():
                with open(self.cookies_path, encoding="utf-8") as handle:
                    return json.load(handle)
        except Exception as exc:
            logger.warning(
                f"Failed to load CoinGlass cookies from {self.cookies_path}: {exc}"
            )
        return None

    @staticmethod
    async def _close_quietly(resource: Any) -> None:
        if resource is None:
            return
        with contextlib.suppress(Exception):
            await resource.close()

    @staticmethod
    def target_key(target: dict[str, str]) -> str:
        exchange = target.get("exchange", "Binance")
        short_name = target.get("short_name") or target.get("symbol") or target["coin"]
        return f"{exchange}:{short_name}"
