"""CoinGlass liquidation heatmap browser interceptor."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urlencode

from apps.scraper_app.core import BrowserScraperRuntime
from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.MARKET_DATA)

CONFIG_FILE_COINGLASS = "configs/coinglass.yaml"


class CoinGlassHeatmapInterceptor(BrowserScraperRuntime):
    """Capture CoinGlass heatmap payloads via browser network interception."""

    def __init__(self, cookies_path: str | None = None, proxy_url: str | None = None):
        config = ConfigManager()
        config.register_file(CONFIG_FILE_COINGLASS)
        resolved_cookies_path = cookies_path or config.get(
            "coinglass.cookies_path", "secrets/coinglass_cookies.json"
        )
        resolved_proxy_url = proxy_url or config.get("coinglass.proxy_url")
        super().__init__(
            config=config,
            cookies_path=resolved_cookies_path,
            proxy_url=resolved_proxy_url,
        )
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
            context = await self._get_or_create_context()
        except Exception as exc:
            logger.error(
                f"CoinGlass browser session failed for {targets}: {exc}",
                exc_info=True,
            )
            await self.close()
            return results

        try:
            fetch_delay = self._config.get("coinglass.fetch_delay_seconds", 2)
            for index, target in enumerate(targets):
                key = self.target_key(target)
                results[key] = await self._fetch_target_heatmap(context, target)
                if index < len(targets) - 1 and fetch_delay > 0:
                    await asyncio.sleep(fetch_delay)
        except Exception as exc:
            logger.error(
                f"CoinGlass target fetch failed for {targets}: {exc}",
                exc_info=True,
            )
            await self.close()

        return results

    async def _post_create_context(self, context: Any) -> None:
        await self._configure_route_target(context)

    async def _fetch_target_heatmap(
        self, context: Any, target: dict[str, str]
    ) -> dict[str, Any] | None:
        page = None
        pending_tasks: list[asyncio.Task[Any]] = []
        best_candidate: dict[str, Any] | None = None
        best_score = -1
        page_url = self._build_page_url(target)
        fetch_started = time.perf_counter()
        timing_ms: dict[str, float] = {}

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
                "timing_ms": {
                    **timing_ms,
                    "total": round((time.perf_counter() - fetch_started) * 1000, 2),
                    "fallback_capture": round(
                        (time.perf_counter() - fetch_started) * 1000, 2
                    ),
                },
                "payload": candidate,
            }

        try:
            page = await context.new_page()

            def on_response(response: Any) -> None:
                pending_tasks.append(asyncio.create_task(consider_response(response)))

            page.on("response", on_response)
            navigation_started = time.perf_counter()
            await page.goto(
                page_url,
                wait_until="domcontentloaded",
                timeout=self._config.get("coinglass.page_load_timeout_ms", 30000),
            )
            timing_ms["navigation"] = round(
                (time.perf_counter() - navigation_started) * 1000, 2
            )
            runtime_candidate, helper_timing_ms = await self._poll_runtime_helper_payload(
                page, target, page_url
            )
            timing_ms.update(helper_timing_ms)
            if runtime_candidate is not None:
                runtime_candidate["timing_ms"] = {
                    **timing_ms,
                    "total": round((time.perf_counter() - fetch_started) * 1000, 2),
                }
                return runtime_candidate

            timeout_seconds = self._config.get(
                "coinglass.response_timeout_seconds", 15
            )
            poll_seconds = self._config.get("coinglass.poll_interval_seconds", 0.5)
            deadline = time.monotonic() + timeout_seconds
            fallback_started = time.perf_counter()
            while time.monotonic() < deadline:
                if best_candidate is not None and best_score > 1:
                    break
                await asyncio.sleep(poll_seconds)
            timing_ms["fallback_wait"] = round(
                (time.perf_counter() - fallback_started) * 1000, 2
            )

            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)

            if best_candidate is not None:
                best_candidate["timing_ms"] = {
                    **timing_ms,
                    **best_candidate.get("timing_ms", {}),
                    "fallback_wait": timing_ms.get("fallback_wait", 0.0),
                    "total": round((time.perf_counter() - fetch_started) * 1000, 2),
                }
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

    async def _poll_runtime_helper_payload(
        self,
        page: Any,
        target: dict[str, str],
        page_url: str,
    ) -> tuple[dict[str, Any] | None, dict[str, float]]:
        max_wait_seconds = float(
            self._config.get("coinglass.runtime_helper_delay_seconds", 2)
        )
        poll_interval_seconds = float(
            self._config.get("coinglass.runtime_helper_poll_interval_seconds", 0.25)
        )
        helper_started = time.perf_counter()
        waited_seconds = 0.0

        while True:
            runtime_candidate = await self._fetch_runtime_helper_payload(
                page, target, page_url
            )
            if runtime_candidate is not None:
                return runtime_candidate, {
                    "helper_delay": round(waited_seconds * 1000, 2),
                    "runtime_helper_attempt": round(
                        (time.perf_counter() - helper_started) * 1000, 2
                    ),
                }

            elapsed = time.perf_counter() - helper_started
            remaining = max_wait_seconds - elapsed
            if remaining <= 0:
                break

            sleep_for = min(poll_interval_seconds, remaining)
            await asyncio.sleep(sleep_for)
            waited_seconds += sleep_for

        return None, {
            "helper_delay": round(waited_seconds * 1000, 2),
            "runtime_helper_attempt": round(
                (time.perf_counter() - helper_started) * 1000, 2
            ),
        }

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

    async def _configure_route_target(self, route_target: Any) -> None:
        route = getattr(route_target, "route", None)
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

    async def _configure_page(self, page: Any) -> None:
        await self._configure_route_target(page)

    def _config_namespace(self) -> str:
        return "coinglass"

    def _log_patchright_missing(self) -> None:
        logger.error("Patchright is not installed. Install project optional tv-scraper deps.")

    def _log_cookie_load_failure(self) -> None:
        logger.warning(f"Failed to load CoinGlass cookies from {self.cookies_path}")

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

    @staticmethod
    def target_key(target: dict[str, str]) -> str:
        exchange = target.get("exchange", "Binance")
        short_name = target.get("short_name") or target.get("symbol") or target["coin"]
        return f"{exchange}:{short_name}"
