"""Shared browser/cookie runtime for provider-specific scrapers."""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


class BrowserScraperRuntime:
    """Reusable Patchright browser/context lifecycle with cached cookies."""

    def __init__(self, *, config: Any, cookies_path: str, proxy_url: str | None = None) -> None:
        self.cookies_path = cookies_path
        self.proxy_url = proxy_url
        self._config = config
        self._browser_lock = asyncio.Lock()
        self._cached_cookies: list[dict[str, Any]] | None = None
        self._cached_cookies_mtime_ns: int | None = None
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._context: Any | None = None

    async def _get_or_create_context(self) -> Any:
        if self._context is not None:
            return self._context

        async with self._browser_lock:
            if self._context is not None:
                return self._context

            try:
                from patchright.async_api import async_playwright
            except ImportError:
                self._log_patchright_missing()
                raise

            self._playwright = await async_playwright().start()
            launch_kwargs = self._build_launch_kwargs()
            if self.proxy_url:
                launch_kwargs["proxy"] = {"server": self.proxy_url}

            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
            self._context = await self._browser.new_context(**self._build_context_kwargs())
            await self._post_create_context(self._context)
            await self._apply_cookies(self._context)
            return self._context

    def _build_launch_kwargs(self) -> dict[str, Any]:
        namespace = self._config_namespace()
        return {
            "headless": self._config.get(f"{namespace}.headless", True),
            "args": list(
                self._config.get(
                    f"{namespace}.chromium_args",
                    [
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                    ],
                )
            ),
        }

    def _build_context_kwargs(self) -> dict[str, Any]:
        namespace = self._config_namespace()
        return {
            "viewport": {
                "width": self._config.get(f"{namespace}.viewport_width", 1920),
                "height": self._config.get(f"{namespace}.viewport_height", 1080),
            },
            "user_agent": self._config.get(
                f"{namespace}.user_agent",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36",
            ),
        }

    async def _post_create_context(self, context: Any) -> None:
        return None

    async def _apply_cookies(self, context: Any) -> None:
        cookies = self._load_cookies()
        if not cookies:
            return
        await context.add_cookies([self._normalize_cookie(cookie) for cookie in cookies])

    def _normalize_cookie(self, cookie: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(cookie)

        expiration_date = normalized.pop("expirationDate", None)
        if "expires" not in normalized and expiration_date not in (None, ""):
            normalized["expires"] = self._normalize_cookie_expiry(expiration_date)

        same_site = normalized.get("sameSite")
        if isinstance(same_site, str):
            canonical_same_site = same_site[:1].upper() + same_site[1:].lower()
            if canonical_same_site in {"Lax", "Strict", "None"}:
                normalized["sameSite"] = canonical_same_site
            else:
                normalized.pop("sameSite", None)

        if "domain" in normalized and isinstance(normalized["domain"], str):
            domain = normalized["domain"]
            if domain.startswith("."):
                normalized["domain"] = domain[1:]

        allowed_keys = {
            "name",
            "value",
            "domain",
            "path",
            "expires",
            "httpOnly",
            "secure",
            "sameSite",
        }
        return {
            key: value
            for key, value in normalized.items()
            if key in allowed_keys and value is not None
        }

    @staticmethod
    def _normalize_cookie_expiry(value: Any) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError:
                return None
        return None

    def _load_cookies(self) -> list[dict[str, Any]] | None:
        cookie_path = Path(self.cookies_path)
        try:
            if not cookie_path.exists():
                self._cached_cookies = None
                self._cached_cookies_mtime_ns = None
                return None

            stat = cookie_path.stat()
            if (
                self._cached_cookies is not None
                and self._cached_cookies_mtime_ns == stat.st_mtime_ns
            ):
                return [dict(cookie) for cookie in self._cached_cookies]

            with open(cookie_path, encoding="utf-8") as handle:
                cookies = json.load(handle)

            self._cached_cookies = [dict(cookie) for cookie in cookies]
            self._cached_cookies_mtime_ns = stat.st_mtime_ns
            return [dict(cookie) for cookie in self._cached_cookies]
        except Exception:
            self._cached_cookies = None
            self._cached_cookies_mtime_ns = None
            self._log_cookie_load_failure()
            return None

    async def close(self) -> None:
        async with self._browser_lock:
            context = self._context
            browser = self._browser
            playwright = self._playwright
            self._context = None
            self._browser = None
            self._playwright = None

            await self._close_quietly(context)
            await self._close_quietly(browser)
            if playwright is not None:
                stop = getattr(playwright, "stop", None)
                if callable(stop):
                    with contextlib.suppress(Exception):
                        await stop()

    @staticmethod
    async def _close_quietly(resource: Any, *_args: Any) -> None:
        if resource is None:
            return
        with contextlib.suppress(Exception):
            await resource.close()

    def _config_namespace(self) -> str:
        raise NotImplementedError

    def _log_patchright_missing(self) -> None:
        raise NotImplementedError

    def _log_cookie_load_failure(self) -> None:
        raise NotImplementedError
