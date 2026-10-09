"""One CoinGlass cycle: a fresh page in the engine, one helper call per dataset.

Nothing is kept between cycles: not the socket, the target, the session or the
URL. Results are written into a caller-owned list as they arrive, so a cycle
deadline that cancels the walk still leaves the finished datasets behind.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any

from apps.scraper_app.adapters.coinglass.cdp import CdpConnection, CommandTimeout
from apps.scraper_app.adapters.coinglass.cookies import CookieStore
from apps.scraper_app.adapters.coinglass.helper import (
    READY_JS,
    HelperRequest,
    HelperResult,
    build_expression,
    interpret_result,
)
from apps.scraper_app.domain import errors
from apps.scraper_app.domain.errors import ScraperError
from apps.scraper_app.settings import CoinGlassSettings
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.MARKET_DATA)

CycleOutcome = HelperResult | ScraperError
Opener = Callable[[CoinGlassSettings], Awaitable[CdpConnection]]
_POLL_SECONDS = 0.25
_MARGIN_BYTES = 1 << 20


async def open_engine(settings: CoinGlassSettings) -> CdpConnection:
    return await CdpConnection.open(
        settings.engine_url,
        connect_timeout=settings.connect_timeout_seconds,
        command_timeout=settings.command_timeout_seconds,
        max_size=2 * settings.max_payload_bytes + _MARGIN_BYTES,
    )


class CoinGlassClient:
    def __init__(
        self,
        settings: CoinGlassSettings,
        *,
        cookies: CookieStore,
        clock: Callable[[], datetime],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        opener: Opener = open_engine,
    ) -> None:
        self._settings = settings
        self._cookies = cookies
        self._clock = clock
        self._sleep = sleep
        self._opener = opener

    async def run_cycle(
        self, requests: Sequence[HelperRequest], results: list[CycleOutcome | None]
    ) -> None:
        """Fill ``results`` (same length as ``requests``).

        Raises ``ScraperError`` for a failure before the first helper call.
        """
        s = self._settings
        connection = await self._opener(s)
        target_id: str | None = None
        try:
            await self._sweep(connection)
            target_id, session = await self._open_page(connection)
            await self._navigate(connection, session)
            for index, request in enumerate(requests):
                if index:
                    await self._sleep(s.call_spacing_seconds)
                try:
                    results[index] = await self._call(connection, session, request)
                except ScraperError as exc:
                    results[index] = exc
                    if exc.code == errors.ENGINE_UNREACHABLE:
                        for rest in range(index + 1, len(requests)):
                            results[rest] = exc
                        return
        finally:
            await self._cleanup(connection, target_id)

    async def _sweep(self, connection: CdpConnection) -> None:
        listing = await connection.send("Target.getTargets")
        for info in listing.get("targetInfos", []):
            if info.get("type") != "page":
                continue
            try:
                await connection.send(
                    "Target.closeTarget", {"targetId": info["targetId"]}
                )
            except ScraperError as exc:
                if exc.code == errors.ENGINE_UNREACHABLE:
                    raise
                logger.warning("could not close a stale page target: %s", exc.code)

    async def _open_page(self, connection: CdpConnection) -> tuple[str, str]:
        created = await connection.send("Target.createTarget", {"url": "about:blank"})
        target_id = str(created["targetId"])
        attached = await connection.send(
            "Target.attachToTarget", {"targetId": target_id, "flatten": True}
        )
        return target_id, str(attached["sessionId"])

    async def _navigate(self, connection: CdpConnection, session: str) -> None:
        s = self._settings
        for method in ("Page.enable", "Network.enable", "Runtime.enable"):
            await connection.send(method, session_id=session)
        await connection.send(
            "Network.setCacheDisabled", {"cacheDisabled": True}, session_id=session
        )
        cookies = self._cookies.load()
        if cookies:
            try:
                await connection.send(
                    "Network.setCookies", {"cookies": cookies}, session_id=session
                )
            except ScraperError as exc:
                if exc.code == errors.ENGINE_UNREACHABLE:
                    raise
                # Never echo the engine's text: it could quote a cookie.
                raise ScraperError(
                    errors.ENGINE_ERROR, "setting cookies failed"
                ) from None
            logger.info("cookies sent to the engine: %d", len(cookies))
        try:
            async with asyncio.timeout(s.navigation_timeout_seconds):
                navigated = await connection.send(
                    "Page.navigate", {"url": s.host_page_url}, session_id=session
                )
                if navigated.get("errorText"):
                    raise ScraperError(
                        errors.NAVIGATION_FAILED, str(navigated["errorText"])[:100]
                    )
                while not await self._ready(connection, session):
                    await asyncio.sleep(_POLL_SECONDS)
        except TimeoutError as exc:
            raise ScraperError(
                errors.NAVIGATION_FAILED,
                f"page not ready within {s.navigation_timeout_seconds:g}s",
            ) from exc
        except CommandTimeout as exc:
            raise ScraperError(errors.NAVIGATION_FAILED, str(exc)[:100]) from exc

    async def _ready(self, connection: CdpConnection, session: str) -> bool:
        try:
            return (await self._evaluate(connection, session, READY_JS, 5.0)) is True
        except CommandTimeout:
            return False
        except ScraperError as exc:
            if exc.code == errors.ENGINE_UNREACHABLE:
                raise
            return False

    @staticmethod
    async def _evaluate(
        connection: CdpConnection, session: str, expression: str, timeout: float
    ) -> Any:
        result = await connection.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
            },
            session_id=session,
            timeout=timeout,
        )
        if "exceptionDetails" in result:
            raise ScraperError(errors.ENGINE_ERROR, "page evaluation raised")
        return result.get("result", {}).get("value")

    async def _call(
        self, connection: CdpConnection, session: str, request: HelperRequest
    ) -> HelperResult:
        s = self._settings
        expression = build_expression(
            request,
            timeout_seconds=s.helper_timeout_seconds,
            max_chars=s.max_payload_bytes,
        )
        try:
            value = await self._evaluate(
                connection,
                session,
                expression,
                s.helper_timeout_seconds + s.command_timeout_seconds,
            )
        except CommandTimeout as exc:
            raise ScraperError(
                errors.HELPER_TIMEOUT, "evaluate did not return in time"
            ) from exc
        return interpret_result(value, returned_at=self._clock())

    async def _cleanup(self, connection: CdpConnection, target_id: str | None) -> None:
        if target_id is not None:
            try:
                await connection.send("Target.closeTarget", {"targetId": target_id})
            except Exception as exc:  # noqa: BLE001 - the next cycle sweeps it
                logger.warning(
                    "closing the page target failed: %s", getattr(exc, "code", "error")
                )
        await connection.close()


__all__ = ["CoinGlassClient", "CycleOutcome", "open_engine"]
